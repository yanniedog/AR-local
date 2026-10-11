"""Bounded, interface-only network recovery for the shared Pi (no global restart)."""
from __future__ import annotations

import json
import ipaddress
from contextlib import contextmanager
import os
import re
import stat
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TRUSTED_ROOT = Path('/usr/local/lib/ar-local-shared-host')
LOCK_MODULES = ('ar_local_operation_lock', 'ar_local_backup_policy', 'cdr_file_lock', 'process_safety')
QUEUE_ROOT = Path('/var/lib/shared-pi-queue')


def command(args, *, timeout=5):
    return subprocess.run(args, capture_output=True, text=True, check=False, timeout=timeout)


def remote_sessions_active() -> bool:
    # Fail closed if either source of session evidence is unavailable.
    ssh = command(['ss', '-Htn', 'state', 'established', '( sport = :22 )'])
    users = command(['who'])
    processes = command(['ps', '-eo', 'comm=,args='])
    remote_login = any(not re.fullmatch(r':\d+(?:\.\d+)?', host)
                       for host in re.findall(r'\(([^)]+)\)', users.stdout))
    # Tailscale SSH's userspace socket and non-PTY commands do not appear in
    # ss/who. Its be-child worker is a separate process for each SSH session.
    remote_process = any(
        (line.split()[0].startswith('sshd') and '[listener]' not in line)
        or (line.split()[0].startswith('tailscaled') and 'be-child' in line.split())
        for line in processes.stdout.splitlines() if line.split())
    return (ssh.returncode != 0 or users.returncode != 0 or processes.returncode != 0 or not processes.stdout.strip()
            or bool(ssh.stdout.strip()) or remote_login or remote_process)


def quiet_window(now=None) -> bool:
    now = now or datetime.now(ZoneInfo('Australia/Hobart'))
    local = now.astimezone(ZoneInfo('Australia/Hobart'))
    start = local.replace(hour=0, minute=30, second=0, microsecond=0)
    end = local.replace(hour=2, minute=0, second=0, microsecond=0)
    # The complete service budget plus cleanup must fit before the quiet window.
    return start - timedelta(seconds=150) <= local < end


def production_lock_factory():
    # Never execute a module from AR_LOCAL_REPO as root. Verify the full
    # standard-library-only closure and its protected ancestors before import.
    for path in [*reversed(TRUSTED_ROOT.parents), TRUSTED_ROOT,
                 *(TRUSTED_ROOT / (name + '.py') for name in LOCK_MODULES)]:
        info = path.lstat()
        if (path.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022
                or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))):
            raise RuntimeError('network lock bundle is not protected')
    for name in LOCK_MODULES:
        loaded = sys.modules.get(name)
        if loaded is not None and Path(loaded.__file__) != TRUSTED_ROOT / (name + '.py'):
            raise RuntimeError('network lock module already loaded from an untrusted location')
    sys.path.insert(0, str(TRUSTED_ROOT))
    from ar_local_operation_lock import production_lock
    return production_lock


@contextmanager
def queue_guard():
    """Root observes cooperative queue state without importing operator code."""
    if not QUEUE_ROOT.exists() and not QUEUE_ROOT.is_symlink():
        yield
        return
    import fcntl
    root = QUEUE_ROOT.lstat()
    if not stat.S_ISDIR(root.st_mode) or stat.S_IMODE(root.st_mode) != 0o700:
        raise RuntimeError('unsafe shared queue root')
    fd = os.open(QUEUE_ROOT / 'queue.lock', os.O_RDWR | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != root.st_uid or info.st_nlink != 1:
            raise RuntimeError('unsafe shared queue lock')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state_fd = os.open(QUEUE_ROOT / 'state.json', os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(state_fd, 'rb') as handle:
            info = os.fstat(handle.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != root.st_uid
                    or info.st_nlink != 1 or info.st_size > 4 * 1024 * 1024):
                raise RuntimeError('unsafe shared queue state')
            state = json.loads(handle.read(4 * 1024 * 1024 + 1))
        if (not isinstance(state, dict) or set(state) != {'version', 'next_sequence', 'jobs'}
                or state['version'] != 1 or type(state['next_sequence']) is not int
                or not isinstance(state['jobs'], list) or state['jobs']):
            raise RuntimeError('shared queue occupied or ownership unavailable')
        yield
    finally:
        os.close(fd)


def default_route():
    result = command(['ip', '-j', 'route', 'show', 'default'])
    if result.returncode:
        raise RuntimeError('route evidence unavailable')
    routes = json.loads(result.stdout)
    if len(routes) != 1:
        raise RuntimeError('default route absent or ambiguous')
    gateway, interface = routes[0].get('gateway', ''), routes[0].get('dev', '')
    if not gateway or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,32}', interface):
        raise RuntimeError('unsafe or incomplete default route')
    ipaddress.ip_address(gateway)
    return gateway, interface


def recover(state: Path, data: Path, *, dry_run=False) -> str:
    gateway, interface = default_route()
    ping = command(['ping', '-c1', '-W3', gateway])
    if not dry_run:
        state.parent.mkdir(parents=True, exist_ok=True)
    try:
        previous = json.loads(state.read_text()) if state.exists() else {}
    except json.JSONDecodeError:
        previous = {}
    except OSError:
        if not dry_run:
            raise
        previous = {}
    if not isinstance(previous, dict):
        previous = {}
    count = previous.get('failures', 0)
    if type(count) is not int or not 0 <= count <= 3:
        count = 0
    same_route = previous.get('gateway') == gateway and previous.get('interface') == interface
    streak = min(3, count + 1) if same_route else 1
    record = {'gateway': gateway, 'interface': interface, 'failures': streak if ping.returncode else 0}
    temporary = state.with_suffix('.tmp')
    if not dry_run:
        temporary.write_text(json.dumps(record) + '\n')
        temporary.replace(state)
    if not ping.returncode:
        return 'gateway healthy; no network mutation'
    if streak < 3:
        return 'gateway failure below three-check threshold'
    if quiet_window():
        return 'recovery deferred: protected ingest window'
    kind = command(['nmcli', '-g', 'GENERAL.TYPE', 'device', 'show', interface])
    if kind.returncode or kind.stdout.strip() != 'wifi':
        return 'recovery deferred: default interface is not verified Wi-Fi'
    if remote_sessions_active():
        return 'recovery deferred: remote session active'
    if dry_run:
        units = command(['systemctl', 'is-active', 'ar-local-daily.service',
                         'ar-local-ingest-now.service', 'ar-local-daily-watchdog.service'])
        states = units.stdout.splitlines()
        if (data / 'state/daily-ingest.lock').exists() or len(states) != 3 or any(
                value not in {'inactive', 'failed'} for value in states):
            return 'dry run: recovery deferred for ingest or occupied lease'
        return 'dry run: eligible for interface-only recovery'
    production_lock = production_lock_factory()
    with queue_guard(), production_lock(data / 'state/daily-ingest.lock', 'network-watchdog'):
        units = command(['systemctl', 'is-active', 'ar-local-daily.service',
                         'ar-local-ingest-now.service', 'ar-local-daily-watchdog.service'])
        states = units.stdout.splitlines()
        if len(states) != 3 or any(value not in {'inactive', 'failed'} for value in states):
            return 'recovery deferred: ingest active or unknown'
        if quiet_window() or remote_sessions_active() or default_route() != (gateway, interface):
            return 'recovery deferred: activity or route changed'
        # A failed reconnect must not trigger another attempt on every tick.
        record['failures'] = 0
        temporary.write_text(json.dumps(record) + '\n')
        temporary.replace(state)
        # Never restart NetworkManager, tailscaled, Ethernet, or other profiles.
        result = command(['nmcli', '--wait', '20', 'device', 'connect', interface], timeout=25)
        return 'interface recovery requested' if not result.returncode else 'interface recovery failed'


def main():
    try:
        state = Path(os.environ.get('AR_LOCAL_NETWORK_STATE', '/run/ar-local-net-watchdog/state.json'))
        data = Path(os.environ.get('AR_LOCAL_DATA_ROOT', '/srv/ar-local/data'))
        outcome = recover(state, data, dry_run='--dry-run' in sys.argv)
        print(outcome)
        return 1 if outcome == 'interface recovery failed' else 0
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f'recovery deferred: {type(error).__name__}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
