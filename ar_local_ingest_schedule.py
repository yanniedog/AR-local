"""Shared schedule constants for Pi banking ingest."""

from __future__ import annotations

from datetime import date, datetime, time as datetime_time, timedelta, timezone
from zoneinfo import ZoneInfo

try:
    import tzdata  # noqa: F401 — IANA tz database for zoneinfo on Windows
except ImportError:
    pass

# Pi systemd local time (timedatectl on ar-local-pi5: Australia/Hobart).
# Keep in lockstep with deploy/pi/ar-local-daily.timer OnCalendar 01:00 local.
DAILY_INGEST_TZ_KEY = "Australia/Hobart"
DAILY_INGEST_TZ = ZoneInfo(DAILY_INGEST_TZ_KEY)
DAILY_INGEST_LOCAL_HOUR = 1
DAILY_INGEST_SCHEDULE_LABEL = f"{DAILY_INGEST_LOCAL_HOUR:02d}:00 {DAILY_INGEST_TZ_KEY} daily"

# Operator decision 2026-11-14: maintenance may continue until 00:30 daily.
# Admission still requires enough time for each operation's cleanup budget.
MAINTENANCE_WINDOW_LABEL = "03:30-00:30 Australia/Hobart"


def maintenance_window_open(now_utc: datetime) -> bool:
    local = _as_utc(now_utc).astimezone(DAILY_INGEST_TZ)
    return not datetime_time(0, 30) <= local.time() < datetime_time(3, 30)


def maintenance_closes_at(now_utc: datetime) -> datetime:
    """Next 00:30 boundary, including today's boundary just after midnight."""
    local = _as_utc(now_utc).astimezone(DAILY_INGEST_TZ)
    boundary = local.replace(hour=0, minute=30, second=0, microsecond=0)
    return boundary if local < boundary else boundary + timedelta(days=1)


def _as_utc(now_utc: datetime) -> datetime:
    if now_utc.tzinfo is None:
        return now_utc.replace(tzinfo=timezone.utc)
    return now_utc.astimezone(timezone.utc)


def _due_local_on(day: date) -> datetime:
    return datetime.combine(day, datetime_time(DAILY_INGEST_LOCAL_HOUR, 0), tzinfo=DAILY_INGEST_TZ)


def latest_daily_due_utc(now_utc: datetime) -> datetime:
    local_now = _as_utc(now_utc).astimezone(DAILY_INGEST_TZ)
    due_day = local_now.date()
    due_local = _due_local_on(due_day)
    if local_now < due_local:
        due_local = _due_local_on(due_day - timedelta(days=1))
    return due_local.astimezone(timezone.utc)


def next_daily_due_utc(now_utc: datetime) -> datetime:
    last_local = latest_daily_due_utc(now_utc).astimezone(DAILY_INGEST_TZ)
    next_local = _due_local_on(last_local.date() + timedelta(days=1))
    return next_local.astimezone(timezone.utc)


def expected_run_date_for_due(due_utc: datetime) -> str:
    return due_utc.astimezone(DAILY_INGEST_TZ).date().isoformat()
