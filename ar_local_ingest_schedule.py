"""Shared schedule constants for Pi banking ingest."""

from __future__ import annotations

from datetime import datetime, time as datetime_time, timedelta, timezone

# 07:00 UTC == 17:00 AEST (UTC+10). During AEDT summer (UTC+11) this lands at
# 18:00 local — the schedule is intentionally pinned to UTC, matching the systemd
# timer in deploy/pi/ar-local-daily.timer (keep the two in lockstep).
DAILY_INGEST_UTC_HOUR = 7
DAILY_INGEST_SCHEDULE_LABEL = f"{DAILY_INGEST_UTC_HOUR:02d}:00 UTC daily"


def latest_daily_due_utc(now_utc: datetime) -> datetime:
    due = datetime.combine(now_utc.date(), datetime_time(DAILY_INGEST_UTC_HOUR, 0), tzinfo=timezone.utc)
    if now_utc < due:
        due -= timedelta(days=1)
    return due


def next_daily_due_utc(now_utc: datetime) -> datetime:
    return latest_daily_due_utc(now_utc) + timedelta(days=1)


def expected_run_date_for_due(due_utc: datetime) -> str:
    return due_utc.astimezone().date().isoformat()
