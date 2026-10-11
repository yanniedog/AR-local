"""Recover the dashboard only after this queued ingest actually started."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from pi_shared_queue_native import NATIVE_LOCK, legacy_host_ready, native_lock_factory
from pi_shared_queue_store import FIXED_AR_UNITS, Store


def start_dashboard():
    subprocess.run(['sudo', '-n', '/usr/bin/systemctl', 'start',
                    'ar-local-dashboard.service'], check=True,
                   capture_output=True, timeout=30)


def restoration_allowed(unit, now=None):
    if unit != 'ar-local-daily-watchdog.service':
        return True
    local = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('Australia/Hobart'))
    return not time(0, 30) <= local.time() < time(3, 30)


def recover(store, unit, invocation, factory=native_lock_factory,
            ready=legacy_host_ready, restart=start_dashboard, now=None):
    if unit not in FIXED_AR_UNITS or not invocation:
        return False
    if not restoration_allowed(unit, now):
        return False  # Preserve the watchdog's natural-ingest restore gate.
    with store.transaction() as state:
        matches = [job for job in state['jobs']
                   if job['unit'] == unit and job['invocation_id'] == invocation
                   and job['state'] == 'running' and job.get('command_started') is True]
        if len(matches) != 1:
            return False
        job = matches[0]
        if (store.supervisor.cgroup(os.getpid()) != job['cgroup']
                or store.supervisor.ownership(job) != 'live'):
            return False
        registered = {record['unit'] for record in state['jobs']}
    # The running queue claim persists through this hook. A native incumbent
    # must also have ended before restoring a dashboard paused by ingest.
    try:
        with factory()(NATIVE_LOCK, 'shared-pi-stop-hook:' + job['id']):
            if not ready(registered) or not restoration_allowed(unit, now):
                return False
            restart()
    except RuntimeError:
        return False  # A native owner retains authority; normal health can retry.
    return True


def main():
    try:
        store = Store()
        unit = store.supervisor.cgroup(os.getpid()).rsplit('/', 1)[-1]
        recovered = recover(store, unit, os.environ.get('INVOCATION_ID', ''))
        print(json.dumps({'dashboard_recovered': recovered,
                          'reason': 'started-ingest-and-idle-lease' if recovered
                          else 'not-started-or-owner-still-active'}))
        return 0
    except (OSError, ValueError, ImportError, subprocess.SubprocessError):
        print('shared queue dashboard recovery deferred: ownership unavailable')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
