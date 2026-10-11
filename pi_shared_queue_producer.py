"""Fail closed before a fixed queue override launches a producer checkout."""
from pathlib import Path
import os
import subprocess
import sys

from pi_shared_queue_native import verify_native_deployment

REPO = Path('/srv/ar-local/AR-local')
PRODUCERS = frozenset({'pi_daily_sync.py', 'pi_daily_watchdog.py'})


def producer_command(arguments, *, cwd=None, verify=verify_native_deployment):
    # WorkingDirectory is preserved from the rendered producer unit. Reject a
    # custom installation rather than silently executing a stale default tree.
    cwd = Path.cwd() if cwd is None else Path(cwd)
    if cwd != REPO or cwd.resolve(strict=True) != REPO:
        raise ValueError('fixed queue producer requires the commissioned repository root')
    if not arguments or arguments[0] not in PRODUCERS:
        raise ValueError('unsupported fixed queue producer')
    verify()
    return ['/usr/bin/python3', str(REPO / arguments[0]), *arguments[1:]]


def main():
    try:
        command = producer_command(sys.argv[1:])
        os.execv(command[0], command)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'queue producer activation refused: {type(error).__name__}', file=sys.stderr)
        return 75


if __name__ == '__main__':
    raise SystemExit(main())
