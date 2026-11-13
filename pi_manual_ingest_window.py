"""Admission for the legacy long-running manual service, not scheduled ingest."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import sys

from ar_local_ingest_schedule import maintenance_closes_at, maintenance_window_open

MANUAL_UNIT = 'ar-local-ingest-now.service'
# shared-queue-ingest-now.conf: 21600s child, 46800s startup minus 21600s
# queue wait and child = 3600s inherited hooks, plus 900s TimeoutStopSec.
# This also covers the shorter direct template's 6h15min +45s stop lifetime.
EXECUTION_SECONDS = 21600
POST_HOOK_SECONDS = 3600
STOP_SECONDS = 900
LIFETIME_SECONDS = EXECUTION_SECONDS + POST_HOOK_SECONDS + STOP_SECONDS


def manual_service(cgroup_path: Path | None = None) -> bool:
    """Recognize the actual unit even when an installed argv predates the flag."""
    if cgroup_path is None and os.name != 'posix':
        return False
    path = cgroup_path or Path('/proc/self/cgroup')
    try:
        with path.open('rb') as stream:
            raw = stream.read(65537)
        if not raw or len(raw) > 65536:
            raise ValueError('invalid cgroup inventory size')
        paths = []
        for line in raw.decode('utf-8').splitlines():
            parts = line.split(':', 2)
            if len(parts) != 3 or not parts[0].isdigit() or not parts[2].startswith('/'):
                raise ValueError('invalid cgroup inventory record')
            paths.append(parts[2])
        return any(MANUAL_UNIT in path.split('/') for path in paths)
    except (OSError, UnicodeError, ValueError) as error:
        raise RuntimeError('cannot establish manual ingest service context') from error


def require_window(now: datetime | None = None) -> None:
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('timezone-aware manual admission clock required')
    if not maintenance_window_open(now):
        raise RuntimeError('manual ingest is blocked during 00:30-03:30 Australia/Hobart')
    remaining = (maintenance_closes_at(now).astimezone(timezone.utc)
                 - now.astimezone(timezone.utc)).total_seconds()
    if remaining <= LIFETIME_SECONDS:
        raise RuntimeError('manual ingest needs its full 7h15min lifetime before 00:30 Australia/Hobart')


def main() -> int:
    try:
        require_window()
    except (ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 75
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
