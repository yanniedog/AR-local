"""Shared constants for AR-local launcher scripts (avoid drift across cron, systemd, Task Scheduler)."""

from __future__ import annotations

TASK_NAME = "AustralianRates-Local-CDR-Ingest"
DAILY_WORKER_COUNT = 8
INGEST_EXTRA_ARGS = f"--workers {DAILY_WORKER_COUNT}"
SCHEDULE_UTC_HOUR = 20
SCHEDULE_UTC_MINUTE = 0
CRON_BEGIN = "# BEGIN AR-local CDR"
CRON_END = "# END AR-local CDR"
SYSTEMD_UNIT_NAME = "ar-local-boot-ingest.service"

# PRAGMA quick_check scans the whole DB; enable explicitly when needed.
ENV_DB_QUICK_CHECK = "AR_LOCAL_DB_QUICK_CHECK"
ENV_DB_QUICK_CHECK_ALT = "DB_QUICK_CHECK"
