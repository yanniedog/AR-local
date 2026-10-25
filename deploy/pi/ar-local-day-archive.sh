#!/bin/bash
set -euo pipefail
set -a
# shellcheck disable=SC1091
source /etc/ar-local/day-archive.env
set +a
ROOT="${AR_LOCAL_DAY_ARCHIVE_SRC:-/var/lib/ar-local-day-archives/src/AR-local}"
cd "$ROOT"
exec /usr/bin/python3 pi_daily_cdr_day_archive.py "$@"
