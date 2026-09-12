#!/usr/bin/env python3
"""Reserve and run one full, bounded current-day recapture after a gated code repair.

This entrypoint does not edit code or bypass review/deployment. The Codex owner
supplies the exact tested, already deployed clean commit and selected generation.
Existing same-day cooldown, budget, operation lock and 22:00 cutoff still apply.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from ar_local_checkout import git_state
from ar_local_pi_runtime import data_state_root
from cdr_observation_selection import selected_observation
from pi_cdr_recovery import (
    EXPECTED_GENERATION_ENV, HOBART, _capture_allowed, _finish, _history, _recovery_lock,
    _reserve, capture_timeout, recovery_block_reason, recovery_window, restore_dashboard_if_idle,
)
from pi_daily_watchdog import run_ingest_process_group


def verify_candidate(repo: Path, expected: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise ValueError("exact tested deployed commit is required")
    actual = git_state(repo)
    if actual["commit"] != expected or actual["clean"] is not True:
        raise ValueError("runtime must be clean at the exact tested deployed commit")


def recapture(repo: Path, expected: str, generation: str, reason: str, *, dry_run: bool = False) -> dict:
    verify_candidate(repo, expected)
    now = datetime.now(timezone.utc)
    if not recovery_window(now) or capture_timeout(now) < 60:
        return {"status": "BLOCKED", "reason": "outside_03:30_to_22:00_Hobart_window"}
    block = recovery_block_reason(repo)
    if block:
        return {"status": "BLOCKED", "reason": block}
    if not reason.strip() or len(reason) > 500:
        raise ValueError("a concise repaired issue or PR reference is required")
    state, run_date = data_state_root(repo), now.astimezone(HOBART).date().isoformat()
    with _recovery_lock(state / ".cdr-recovery.lock") as acquired:
        if not acquired:
            return {"status": "BLOCKED", "reason": "recovery_already_active"}
        selected = selected_observation(state, run_date)
        if not selected or selected["contract"]["generation_id"] != generation:
            return {"status": "BLOCKED", "reason": "selected_generation_changed_or_missing"}
        from pi_daily_sync import payload_publication_pending

        if payload_publication_pending(repo):
            return {"status": "BLOCKED", "reason": "pending_publication_must_settle"}
        root = state / "cdr-recovery-v1" / run_date
        allowed, block = _capture_allowed(_history(root, run_date), [], now)
        if not allowed:
            return {"status": "BLOCKED", "reason": block}
        if dry_run:
            return {"status": "READY", "run_date": run_date, "generation_id": generation, "commit": expected}
        reservation = _reserve(root, run_date, generation, "capture", now, purpose="quality_full_recapture",
                               repaired_issue=reason, candidate_commit=expected)
        environment = dict(os.environ, AR_LOCAL_QUALITY_EXPECTED_COMMIT=expected)
        environment[EXPECTED_GENERATION_ENV] = generation
        command = [sys.executable, str(repo / "pi_daily_sync.py"), "--banks-only", "--skip-git-sync",
                   "--date", run_date, "--force", "--quality-recapture"]
        report = {"status": "FAIL", "run_date": run_date, "previous_generation": generation,
                  "candidate_commit": expected, "reservation_id": reservation["reservation_id"]}
        try:
            run_ingest_process_group(command, timeout_seconds=capture_timeout(now), env=environment)
            after = selected_observation(state, run_date)
            report.update(status="CAPTURED" if after and after["contract"]["generation_id"] != generation else "NOT_SELECTED",
                          selected_generation=(after or {}).get("contract", {}).get("generation_id"),
                          acceptance="Separate producer/public/app/backup audits remain required")
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            report["reason"] = type(exc).__name__
            restore_dashboard_if_idle(repo)
        _finish(root, reservation, report)
        return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-generation", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = recapture(Path(__file__).resolve().parent, args.expected_commit, args.expected_generation,
                           args.reason, dry_run=args.dry_run)
    except (ValueError, RuntimeError, OSError) as exc:
        report = {"status": "BLOCKED", "reason": str(exc)}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] in {"READY", "CAPTURED"} else 3 if report["status"] == "BLOCKED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
