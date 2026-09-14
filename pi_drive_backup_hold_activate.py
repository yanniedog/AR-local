"""Activate the operator hold at the backup acceptance lock boundary.

An in-flight operation must reach a terminal state before activation succeeds.
This command never waits, kills workers, contacts Drive, or releases a hold.
"""
from __future__ import annotations

import argparse
import os
import sys
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

from ar_local_operation_lock import production_lock
from pi_drive_backup_hold import SYSTEM_HOLD


def activate_hold(spools: list[Path], reason: str) -> dict:
    from pi_drive_backup import atomic_json

    if not spools or not reason.strip():
        raise ValueError('inventoried spools and operator reason are required')
    if SYSTEM_HOLD.resolve() != SYSTEM_HOLD or SYSTEM_HOLD.is_symlink():
        raise ValueError('canonical system hold path required')
    paths = sorted(set(spools))
    for spool in paths:
        if not spool.is_absolute() or spool.resolve() != spool or not spool.is_dir():
            raise ValueError('every inventoried spool must be an existing canonical directory')
    # A marker written outside this protocol can refuse new operations, but it
    # cannot retrospectively revoke an acceptance already inside its lock.
    with ExitStack() as stack:
        for spool in paths:
            stack.enter_context(production_lock(spool / 'backup.lock', 'drive-hold-activation'))
        if SYSTEM_HOLD.exists():
            return {'result': 'ALREADY_HELD', 'path': str(SYSTEM_HOLD),
                    'coordinated_spools': [str(path) for path in paths]}
        value = {'schema_version': 1, 'state': 'HELD',
                 'activated_at': datetime.now(timezone.utc).isoformat(),
                 'reason': reason.strip(), 'explicit_operator_resume_required': True,
                 'coordinated_spools': [str(path) for path in paths]}
        SYSTEM_HOLD.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_json(SYSTEM_HOLD, value, immutable=True)
        return {'result': 'HELD', 'path': str(SYSTEM_HOLD), **value}


def main():
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spool', action='append', type=Path, required=True)
    parser.add_argument('--reason', required=True)
    args = parser.parse_args()
    if sys.platform != 'linux' or os.geteuid() != 0:
        raise SystemExit('activation requires the root operator on the Pi')
    try:
        result = activate_hold(args.spool, args.reason)
    except (OSError, RuntimeError, ValueError):
        print(json.dumps({'result': 'BLOCKED', 'reason': 'activation_lock_or_path_unavailable'}))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
