#!/usr/bin/python3
"""Raise or clear one GitHub issue for the monthly Pi OS recovery image.

Healthy only when the last run completed, was verified against Drive, and is
no older than MAX_AGE_DAYS. Runs as the alert user; reads a status file only.
"""
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

MAX_AGE_DAYS = 35
STATUS = Path("/var/lib/pi-os-recovery-image/last-result.json")
TITLE = "Pi monthly OS recovery image needs attention"

for code in ("/srv/ar-local/AR-local", "/srv/ar-local/alert-component-cbb75df1-20261102/code"):
    if Path(code, "pi_github_alerts.py").is_file():
        sys.path.insert(0, code)
        break
from pi_github_alerts import configured_store, deliver


def verdict():
    try:
        row = json.loads(STATUS.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "OS_IMAGE_NEVER_RAN"
    except (OSError, ValueError):
        return "OS_IMAGE_STATUS_UNREADABLE"
    if row.get("result") == "FAILED" or not row.get("completed_at"):
        return "OS_IMAGE_RUN_FAILED"
    if row.get("credentials_on_drive") is not False or not row.get("sha256sums_sha256"):
        return "OS_IMAGE_STATUS_UNREADABLE"
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(row["completed_at"])
    except (TypeError, ValueError):
        return "OS_IMAGE_STATUS_UNREADABLE"
    return "OS_IMAGE_STALE" if age.days > MAX_AGE_DAYS else None


problem = verdict()
store = configured_store()
store.observe("os-recovery-image", TITLE, problem or "OS_IMAGE_RUN_FAILED", healthy=problem is None)
print(json.dumps({"problem": problem, "delivery": deliver(store)}, default=str))
