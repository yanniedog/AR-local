#!/usr/bin/env python3
"""Create and validate append-only terminal failure evidence for scheduled Pi ingests."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ar_local_backup_policy import BackupPolicy, COMMIT_RE, sha256_file, utc_now, validate_plan_identity
from ar_local_checkout import git_state
from cdr_atomic import atomic_write_bytes, atomic_write_json

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DEFAULT_CONFIG = Path("/etc/ar-local/backup.env")


def _failure_root(state_root: Path, run_date: str) -> Path:
    if not DATE_RE.fullmatch(run_date):
        raise ValueError("terminal ingest date is invalid")
    return state_root.resolve() / "ingest-executions" / run_date


def record_failure(
    repo_root: Path,
    state_root: Path,
    run_date: str,
    operator: str,
    exact_command: str,
    started_at: str,
    error: BaseException,
    *,
    config_path: Path = DEFAULT_CONFIG,
) -> Path:
    """Write failure text first, then an immutable record that hashes it."""

    policy = BackupPolicy.from_env_file(config_path)
    repository = git_state(repo_root)
    record_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex
    root = _failure_root(state_root, run_date)
    evidence_path = root / f"{record_id}.failure.txt"
    evidence = f"{type(error).__name__}: {str(error)[:2000]}\n".encode("utf-8", errors="replace")
    atomic_write_bytes(evidence_path, evidence, create_once=True)
    record = {
        "schema_version": 1,
        **policy.plan_identity(),
        "candidate_code_sha": repository["commit"],
        "repository_clean": repository["clean"],
        "operator": operator or "unknown",
        "started_at": started_at,
        "completed_at": utc_now(),
        "run_date": run_date,
        "exact_commands": [exact_command],
        "evidence": [{"path": str(evidence_path.resolve()), "sha256": hashlib.sha256(evidence).hexdigest()}],
        "error_type": type(error).__name__,
        "deviations": [],
        "deviation_authorization": None,
        "result": "FAIL",
    }
    record_path = root / f"{record_id}.FAIL.json"
    atomic_write_json(record_path, record, create_once=True)
    return record_path


def latest_valid_failure(
    state_root: Path, run_date: str, *, config_path: Path = DEFAULT_CONFIG
) -> dict[str, object] | None:
    """Return the newest fully verified terminal failure for a day."""

    policy = BackupPolicy.from_env_file(config_path)
    root = _failure_root(state_root, run_date)
    if not root.is_dir() or root.is_symlink():
        return None
    for path in sorted(root.glob("*.FAIL.json"), reverse=True):
        try:
            if path.is_symlink() or not path.is_file():
                continue
            record = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(record, dict)
                or record.get("result") != "FAIL"
                or record.get("run_date") != run_date
                or record.get("deviations") != []
                or record.get("deviation_authorization") is not None
                or record.get("repository_clean") is not True
                or not COMMIT_RE.fullmatch(str(record.get("candidate_code_sha") or ""))
                or not record.get("exact_commands")
                or not validate_plan_identity(record, policy)
            ):
                continue
            entries = record.get("evidence")
            if not isinstance(entries, list) or not entries:
                continue
            valid = True
            for entry in entries:
                evidence_path = Path(str(entry.get("path") or "")) if isinstance(entry, dict) else Path()
                resolved = evidence_path.resolve(strict=False)
                if (
                    not evidence_path.is_absolute()
                    or evidence_path.is_symlink()
                    or not evidence_path.is_file()
                    or resolved != evidence_path
                    or not resolved.is_relative_to(root.resolve())
                    or sha256_file(evidence_path) != str(entry.get("sha256") or "")
                ):
                    valid = False
                    break
            if valid:
                return record
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate",))
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    record = latest_valid_failure(args.state_root, args.date, config_path=args.config)
    if record is None:
        return 1
    print(json.dumps(record, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
