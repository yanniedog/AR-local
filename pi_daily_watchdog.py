"""Catch up the Pi daily ingest if the systemd daily timer misses its slot."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from ar_local_ingest_schedule import expected_run_date_for_due, latest_daily_due_utc
from ar_local_pi_runtime import (
    data_runs_root,
    data_state_root,
    ensure_runtime_data_writable,
    load_exports_manifest,
    manifest_banks_rate_count,
)
from cdr_daily import marker_is_trustworthy, marker_path

REPO_ROOT = Path(__file__).resolve().parent
GRACE_MINUTES = 30
SERVICE_NAME = "ar-local-daily.service"
SUBPROCESS_STATUS_TIMEOUT_SEC = 10
SUBPROCESS_INGEST_TIMEOUT_SEC = 2 * 60 * 60


def export_root_for(date_text: str) -> Path:
    return data_runs_root(REPO_ROOT) / date_text / "_exports"


def run_complete(date_text: str) -> bool:
    export_root = export_root_for(date_text)
    marker = marker_path(data_state_root(REPO_ROOT), date_text)
    if marker_is_trustworthy(marker, export_root, date_text):
        return True
    manifest = load_exports_manifest(export_root)
    return bool(manifest and str(manifest.get("run_date") or "") == date_text and manifest_banks_rate_count(manifest) > 0)


def service_active() -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", SERVICE_NAME],
            check=False,
            shell=False,
            timeout=SUBPROCESS_STATUS_TIMEOUT_SEC,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0


def run_daily_ingest(dry_run: bool) -> None:
    cmd = [sys.executable, str(REPO_ROOT / "pi_daily_sync.py"), "--banks-only"]
    if dry_run:
        print(f"DRY RUN: would run {shlex.join(cmd)}")
        return
    subprocess.run(cmd, cwd=REPO_ROOT, check=True, shell=False, timeout=SUBPROCESS_INGEST_TIMEOUT_SEC)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Pi daily ingest if today's scheduled run is missing.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would happen without running ingest.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable status.")
    parser.add_argument("--grace-minutes", type=int, default=GRACE_MINUTES)
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    try:
        ensure_runtime_data_writable(REPO_ROOT)
        writable_error = ""
    except RuntimeError as exc:
        writable_error = str(exc)
        if not args.json:
            print(f"pi_daily_watchdog: {writable_error}", file=sys.stderr)
        if not args.dry_run:
            return 1
    now_utc = datetime.now(timezone.utc)
    due_utc = latest_daily_due_utc(now_utc)
    run_date = expected_run_date_for_due(due_utc)
    local_today = datetime.now().astimezone().date().isoformat()
    ready_at = due_utc + timedelta(minutes=max(0, args.grace_minutes))
    complete = run_complete(run_date)
    active = service_active()
    current_day_due = run_date == local_today
    should_start = not writable_error and now_utc >= ready_at and current_day_due and not complete and not active
    if should_start:
        run_daily_ingest(args.dry_run)
    payload = {
        "now_utc": now_utc.isoformat(),
        "due_utc": due_utc.isoformat(),
        "ready_at_utc": ready_at.isoformat(),
        "run_date": run_date,
        "complete": complete,
        "service_active": active,
        "current_day_due": current_day_due,
        "runtime_writable": not bool(writable_error),
        "runtime_writable_error": writable_error,
        "started": should_start and not args.dry_run,
        "dry_run": bool(args.dry_run),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        status = "complete" if complete else "missing"
        action = "started" if payload["started"] else "no action"
        print(f"pi_daily_watchdog: {run_date} is {status}; service_active={active}; {action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
