"""Retain one finalized daily payload on GitHub without promoting it to the app.

The parent reserves a durable retry before launching a bounded worker. The
worker rechecks admission and source identity under the production lease.
Scheduled activation supplies --since to avoid duplicating older archives.
An explicit --once without --since considers every retained finalized date.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime, time as daytime, timedelta, timezone
from itertools import islice
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid
from zoneinfo import ZoneInfo

from app_payload_observation_gate import contract_coverage, publication_allowed
from app_payload_source_verification import publication_source
from ar_local_operation_lock import production_lock
from ar_local_pi_runtime import data_runs_root, data_state_root
from cdr_atomic import atomic_write_json
from cdr_export_contract import load_contract
from cdr_file_lock import FileLock
from cdr_finalization import verify_completion_marker
from cdr_observation_selection import safe_child
from pi_payload_retry_policy import CLEANUP_SECONDS, PAYLOAD_TIMEOUT_SECONDS
from pi_process_group import run_process_group

REPO_ROOT = Path(__file__).resolve().parent
HOBART = ZoneInfo("Australia/Hobart")
STATE_DIRECTORY = "app-payload-daily-archive"
UNITS = ("ar-local-daily.service", "ar-local-ingest-now.service")
PROPERTIES = ("LoadState,ActiveState,MainPID,ControlPID,ControlGroup,"
              "ExecMainStartTimestampMonotonic,ExecMainExitTimestampMonotonic,"
              "InactiveEnterTimestampMonotonic")


class ArchiveInterrupted(RuntimeError):
    """A termination request must unwind owned locks and reap worker processes."""


@contextmanager
def archive_signals():
    """Make normal service/timeout termination run Python cleanup on both roles.

    Ignore repeated termination while unwinding; systemd's hard cgroup deadline
    still handles an unresponsive process. SIGKILL residue remains a conservative
    admission refusal until an operator proves the entire old cgroup is gone.
    """
    signals = (signal.SIGTERM, signal.SIGINT)
    previous = {number: signal.getsignal(number) for number in signals}
    def interrupted(number, _frame):
        for handled in signals:
            signal.signal(handled, signal.SIG_IGN)
        raise ArchiveInterrupted("archive termination requested")
    try:
        for number in signals:
            signal.signal(number, interrupted)
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def window_reason(now: datetime) -> str:
    local = now.astimezone(HOBART)
    if not daytime(3, 30) <= local.time() < daytime(22):
        return "protected_natural_ingest_window"
    closing = local.replace(hour=22, minute=0, second=0, microsecond=0)
    if (closing - local).total_seconds() < PAYLOAD_TIMEOUT_SECONDS + CLEANUP_SECONDS:
        return "insufficient_publication_window"
    return ""


def ingest_clearance(repo_root: Path, now: datetime, *, include_lock=True,
                     cgroup_root=Path("/sys/fs/cgroup")) -> str:
    """Unknown systemd state and surviving control/cgroup processes fail closed."""
    if include_lock and os.path.lexists(data_state_root(repo_root) / "daily-ingest.lock"):
        return "natural_ingest_lease_present"
    try:
        for unit in UNITS:
            result = subprocess.run(["systemctl", "show", unit, "--property=" + PROPERTIES],
                                    check=True, capture_output=True, text=True, timeout=5)
            row = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
            if (row.get("LoadState") != "loaded" or row.get("ActiveState") not in {"inactive", "failed"}
                    or row.get("MainPID") != "0" or row.get("ControlPID") != "0"):
                return "ingest_not_terminal"
            group = row.get("ControlGroup") or "/system.slice/" + unit
            if group != "/system.slice/" + unit:
                return "ingest_cgroup_identity_unverified"
            path = cgroup_root / group.lstrip("/")
            if path.exists():
                members = list(islice(path.rglob("cgroup.procs"), 257))
                if not members or len(members) > 256 or any(p.read_text().strip() for p in members):
                    return "ingest_cgroup_not_clear"
            if unit == UNITS[0]:
                started, ended, terminal = (int(row[key]) / 1_000_000 for key in (
                    "ExecMainStartTimestampMonotonic", "ExecMainExitTimestampMonotonic",
                    "InactiveEnterTimestampMonotonic"))
                monotonic = time.monotonic()
                source_day = (now - timedelta(seconds=monotonic - started)).astimezone(HOBART).date()
                if (not 0 < started <= ended <= terminal <= monotonic
                        or source_day != now.astimezone(HOBART).date()):
                    return "current_natural_ingest_terminal_unverified"
    except (OSError, ValueError, TypeError, KeyError, OverflowError, subprocess.SubprocessError):
        return "ingest_terminal_state_unavailable"
    return ""


def archive_state(repo_root: Path) -> Path:
    return data_state_root(repo_root) / STATE_DIRECTORY


def selected_source(repo_root: Path, day: str) -> tuple[dict, Path]:
    if date.fromisoformat(day).isoformat() != day:
        raise ValueError("invalid archive date")
    contract, exports = publication_source(data_state_root(repo_root), day,
                                           data_runs_root(repo_root) / day / "_exports")
    if (not contract or contract.get("observation_date") != day
            or contract.get("observation_state") not in {"complete", "partial"}
            or not re.fullmatch("[0-9a-f]{64}", str(contract.get("contract_digest", "")))):
        raise ValueError("missing finalized archive source")
    return contract, exports


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    if path.is_symlink() or path.stat().st_size > 65536:
        raise ValueError("invalid archive state file")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("invalid archive state")
    return value


def _receipt(root: Path, digest: str) -> dict:
    value = _read(root / "receipts" / (digest + ".json"))
    if value and (value.get("contract_digest") != digest or value.get("status") != "archived"
                  or value.get("selected_for_app") is not False or not value.get("manifest_url")):
        raise ValueError("invalid archive receipt")
    return value


def _attempt_path(root: Path, day: str) -> Path:
    return root / "attempts" / (day + ".json")


def _reserve(root: Path, day: str, digest: str, now: datetime, *, dry_run=False) -> dict:
    path = _attempt_path(root, day)
    previous = _read(path)
    if previous:
        stamp = datetime.fromisoformat(previous["next_attempt_at"])
        if stamp.tzinfo is None or previous.get("day") != day:
            raise ValueError("invalid archive retry identity")
        if now < stamp:
            return {"status": "deferred", "reason": "archive_retry_cooldown", "day": day}
    attempt = previous.get("attempts", 0) + 1
    if type(attempt) is not int or attempt < 1:
        raise ValueError("invalid archive attempt count")
    delay = min(3600 * 2 ** min(attempt - 1, 3), 21600)
    record = {"schema_version": 1, "day": day, "contract_digest": digest,
              "attempt_id": uuid.uuid4().hex, "attempts": attempt, "status": "running",
              "started_at": now.isoformat(), "cooldown_seconds": delay,
              "next_attempt_at": (now + timedelta(seconds=PAYLOAD_TIMEOUT_SECONDS
                                    + CLEANUP_SECONDS + delay)).isoformat()}
    if not dry_run:
        atomic_write_json(path, record)
    return record


def archive_worker(repo_root: Path, day: str, digest: str) -> dict:
    """No ingest, promotion, Drive, repair claim, or operational receipt writes."""
    now = datetime.now(timezone.utc)
    if reason := window_reason(now) or ingest_clearance(repo_root, now):
        raise RuntimeError(reason)
    with production_lock(data_state_root(repo_root) / "daily-ingest.lock", "daily-payload-archive"):
        now = datetime.now(timezone.utc)
        if reason := window_reason(now) or ingest_clearance(repo_root, now, include_lock=False):
            raise RuntimeError(reason)
        contract, exports = selected_source(repo_root, day)
        if contract["contract_digest"] != digest:
            raise ValueError("archive source changed after admission")
        state = data_state_root(repo_root)
        marker = json.loads(safe_child(state, contract["completion_marker_path"]).read_bytes())
        stored = load_contract(safe_child(state, marker["export_contract_path"]))
        if (stored != contract or marker.get("export_contract_digest") != digest
                or marker.get("generation_id") != contract["generation_id"]
                or marker.get("observation_state") != contract["observation_state"]
                or not verify_completion_marker(marker, state, day)):
            raise ValueError("archive completion, ledger or artifact verification failed")
        from app_payload_archive import build_and_archive_payload
        result = build_and_archive_payload(exports, state_dir=archive_state(repo_root) / "bundles",
            contract_coverage=contract_coverage(contract), source_observation={key: contract[key]
                for key in ("generation_id", "observation_date", "observation_state", "contract_digest", "source_path")},
            promotion_reason=publication_allowed(contract)[1])
        receipt = {"schema_version": 1, "status": "archived", "selected_for_app": False,
                   "day": day, "contract_digest": digest, "generation_id": contract["generation_id"],
                   "observation_state": contract["observation_state"], "tag": result.tag,
                   "manifest_url": result.manifest_url, "manifest_sha256": result.manifest_sha256}
        atomic_write_json(archive_state(repo_root) / "receipts" / (digest + ".json"),
                          receipt, create_once=True)
        return receipt


def run_once(repo_root: Path, *, day: str | None = None, since: str | None = None,
             dry_run=False) -> dict:
    if day is not None and since is not None:
        raise ValueError("--since applies only to --once")
    if since is not None and date.fromisoformat(since).isoformat() != since:
        raise ValueError("archive start date must be YYYY-MM-DD")
    now = datetime.now(timezone.utc)
    if reason := window_reason(now) or ingest_clearance(repo_root, now):
        return {"status": "deferred", "reason": reason}
    today = now.astimezone(HOBART).date().isoformat()
    if day and (date.fromisoformat(day).isoformat() != day or day > today):
        raise ValueError("archive date must be a retained date no later than today")
    root = archive_state(repo_root)
    candidates = [day] if day else []
    if day is None:
        try:
            candidates = sorted({p.name for p in
                (data_state_root(repo_root) / "export-contracts-v2").iterdir()
                if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name)
                and (since is None or since <= p.name) and p.name <= today}, reverse=True)
        except FileNotFoundError:
            # No finalized observation yet; retain other I/O failures as blocked.
            pass
    deferred = []
    for candidate in candidates:
        try:
            contract, _ = selected_source(repo_root, candidate)
            digest = contract["contract_digest"]
            if receipt := _receipt(root, digest):
                if day:
                    return {**receipt, "status": "already_archived"}
                continue
            if dry_run:
                reservation = _reserve(root, candidate, digest, now, dry_run=True)
            else:
                with FileLock(root / "admission.lock"):
                    reservation = _reserve(root, candidate, digest, now)
            if reservation["status"] == "deferred":
                deferred.append(reservation)
                continue
        except (OSError, ValueError, KeyError, TypeError) as error:
            deferred.append({"status": "blocked", "day": candidate, "reason": type(error).__name__})
            continue
        if dry_run:
            return {"status": "dry_run", "day": candidate, "contract_digest": digest}
        status, error_name = "failed", ""
        try:
            run_process_group([sys.executable, str(Path(__file__).resolve()), "--worker-date", candidate,
                               "--expected-contract", digest], cwd=repo_root,
                              timeout_seconds=PAYLOAD_TIMEOUT_SECONDS)
            receipt = _receipt(root, digest)
            if not receipt:
                raise RuntimeError("archive worker did not produce verified receipt")
            status = "archived"
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            error_name = type(error).__name__
        with FileLock(root / "admission.lock"):
            path = _attempt_path(root, candidate)
            latest = _read(path)
            if latest.get("attempt_id") == reservation["attempt_id"]:
                latest.update(status=status, reason=error_name, finished_at=datetime.now(timezone.utc).isoformat())
                atomic_write_json(path, latest)
        return {"status": status, "day": candidate, "reason": error_name,
                **({"receipt": receipt} if status == "archived" else {})}
    return {"status": "blocked" if deferred else "up_to_date", "deferred": deferred}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--date")
    mode.add_argument("--worker-date", help=argparse.SUPPRESS)
    parser.add_argument("--expected-contract", help=argparse.SUPPRESS)
    parser.add_argument("--since", help="With --once, consider only dates on or after YYYY-MM-DD.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.since is not None and not args.once:
        parser.error("--since requires --once")
    if bool(args.worker_date) != bool(args.expected_contract) or (args.worker_date and args.dry_run):
        parser.error("internal worker requires its exact contract and cannot be dry-run")
    try:
        with archive_signals():
            result = (archive_worker(REPO_ROOT, args.worker_date, args.expected_contract)
                      if args.worker_date else run_once(REPO_ROOT, day=args.date, since=args.since,
                                                       dry_run=args.dry_run))
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        result = {"status": "blocked", "reason": type(error).__name__}
    print(json.dumps(result, sort_keys=True))
    return 1 if result["status"] in {"blocked", "failed"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
