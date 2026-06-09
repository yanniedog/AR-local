"""Shared schedule constants for Pi banking ingest."""

from __future__ import annotations

from datetime import datetime, time as datetime_time, timedelta, timezone
from zoneinfo import ZoneInfo

# Pi systemd local time (timedatectl on ar-local-pi5: Australia/Hobart).
# Keep in lockstep with deploy/pi/ar-local-daily.timer OnCalendar 01:00 local.
DAILY_INGEST_TZ = ZoneInfo("Australia/Hobart")
DAILY_INGEST_LOCAL_HOUR = 1
DAILY_INGEST_SCHEDULE_LABEL = f"{DAILY_INGEST_LOCAL_HOUR:02d}:00 {DAILY_INGEST_TZ.key} daily"


def latest_daily_due_utc(now_utc: datetime) -> datetime:
    local_now = now_utc.astimezone(DAILY_INGEST_TZ)
    due_local = datetime.combine(
        local_now.date(),
        datetime_time(DAILY_INGEST_LOCAL_HOUR, 0),
        tzinfo=DAILY_INGEST_TZ,
    )
    if local_now < due_local:
        due_local -= timedelta(days=1)
    return due_local.astimezone(timezone.utc)


def next_daily_due_utc(now_utc: datetime) -> datetime:
    return latest_daily_due_utc(now_utc) + timedelta(days=1)


def expected_run_date_for_due(due_utc: datetime) -> str:
    return due_utc.astimezone(DAILY_INGEST_TZ).date().isoformat()
