"""Bounded, interface-only network recovery for the shared Pi (no global restart)."""
from __future__ import annotations

import json
import ipaddress
import os
import re
import subprocess
import sys
import stat
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

COMMAND_DEADLINE = None
RECOVERY_BUDGET_SECONDS = 120
QUEUE_ROOT = Path('/var/lib/shared-pi-queue')
BOOT_ID_PATH = Path('/proc/sys/kernel/random/boot_id')


def _sync_directory(path: Path) -> None:
    if os.name != 'posix':
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def native_network_lease(path: Path):
    """Try the producer's native lease once, never recovering a predecessor.

    Even a provably stale record is occupied for this optional health check.
    Avoiding producer stale recovery also avoids its unbounded recovery flock.
    The record remains compatible with the pinned producer's native schema.
    """
    boot_id = BOOT_ID_PATH.read_text(encoding='ascii').strip()
    if len(boot_id) != 36 or str(uuid.UUID(boot_id)) != boot_id:
        raise ValueError('network lease requires a canonical boot identifier')
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        yield False
        return
    owned = os.fstat(descriptor)
    try:
        payload = f'pid={os.getpid()}\nrole=network-watchdog\nboot_id={boot_id}\n'.encode('ascii')
        with os.fdopen(os.dup(descriptor), 'wb') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _sync_directory(path.parent)
        yield True
    finally:
        # Windows cannot unlink our open descriptor. Production is POSIX; keep
        # it open there until after verifying/removing only our original inode.
        if os.name == 'nt':
            os.close(descriptor)
        try:
            current = path.lstat()
            if (owned.st_dev, owned.st_ino) == (current.st_dev, current.st_ino):
                path.unlink()
                _sync_directory(path.parent)
        except FileNotFoundError:
            pass
        finally:
            if os.name != 'nt':
                os.close(descriptor)


def command(args, *, timeout=5):
    if COMMAND_DEADLINE is not None:
        timeout = min(timeout, COMMAND_DEADLINE - time.monotonic())
        if timeout <= 0:
            raise TimeoutError('network watchdog execution budget exhausted')
    return subprocess.run(args, capture_output=True, text=True, check=False, timeout=timeout)


def remote_sessions_active() -> bool:
    # Fail closed if either source of session evidence is unavailable.
    ssh = command(['ss', '-Htn', 'state', 'established', '( sport = :22 )'])
    users = command(['who'])
    processes = command(['ps', '-eo', 'comm,args'])
    prefs = command(['tailscale', 'debug', 'prefs'])
    if processes.returncode or prefs.returncode:
        return True
    try:
        settings = json.loads(prefs.stdout)
    except (TypeError, ValueError):
        return True
    # Userspace Tailscale SSH, especially non-PTY commands, is not reliably
    # visible in ss/who. Enabled or unknown SSH cannot prove session idleness.
    if not isinstance(settings, dict) or settings.get('RunSSH') is not False:
        return True
    remote_process = any(
        re.match(r'^\s*sshd\S*\s+sshd(?:-[A-Za-z0-9_-]+)?:', line)
        or (line.split() and line.split()[0].startswith('tailscaled') and 'be-child' in line.split())
        for line in processes.stdout.splitlines())
    remote_login = any(not re.fullmatch(r':\d+(?:\.\d+)?', host)
                       for host in re.findall(r'\(([^)]+)\)', users.stdout))
    return ssh.returncode != 0 or users.returncode != 0 or bool(ssh.stdout.strip()) or remote_login or remote_process


def recovery_window_blocked(now=None) -> bool:
    now = datetime.now(timezone.utc) if now is None else now
    if now.utcoffset() is None:
        raise ValueError('network recovery clock requires timezone evidence')
    local = now.astimezone(ZoneInfo('Australia/Hobart'))
    start = local.replace(hour=0, minute=30, second=0, microsecond=0)
    end = local.replace(hour=2, minute=0, second=0, microsecond=0)
    if start <= local < end:
        return True
    if local >= start:
        start += timedelta(days=1)
    return local + timedelta(seconds=RECOVERY_BUDGET_SECONDS) >= start


@contextmanager
def queue_guard():
    """Observe cooperative queue state without importing producer code."""
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
                or not 0 <= state['next_sequence'] < 2**63
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
    if not isinstance(routes, list) or len(routes) != 1 or not isinstance(routes[0], dict):
        raise RuntimeError('default route absent or ambiguous')
    gateway, interface = routes[0].get('gateway', ''), routes[0].get('dev', '')
    if not isinstance(gateway, str) or not isinstance(interface, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,31}', interface):
        raise RuntimeError('unsafe or incomplete default route')
    try:
        ipaddress.ip_address(gateway)
    except ValueError as exc:
        raise RuntimeError('unsafe default gateway') from exc
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
    if recovery_window_blocked():
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
    if os.geteuid() == 0:
        raise RuntimeError('network recovery must run as the non-root service user')
    if recovery_window_blocked():
        return 'recovery deferred: protected ingest window'
    with queue_guard(), native_network_lease(data / 'state/daily-ingest.lock') as acquired:
        if not acquired:
            return 'recovery deferred: production lease occupied'
        units = command(['systemctl', 'is-active', 'ar-local-daily.service',
                         'ar-local-ingest-now.service', 'ar-local-daily-watchdog.service'])
        states = units.stdout.splitlines()
        if len(states) != 3 or any(value not in {'inactive', 'failed'} for value in states):
            return 'recovery deferred: ingest active or unknown'
        if remote_sessions_active() or default_route() != (gateway, interface):
            return 'recovery deferred: activity or route changed'
        if recovery_window_blocked():
            return 'recovery deferred: protected ingest window'
        # A failed reconnect must not trigger another attempt on every tick.
        record['failures'] = 0
        temporary.write_text(json.dumps(record) + '\n')
        temporary.replace(state)
        # Never restart NetworkManager, tailscaled, Ethernet, or other profiles.
        result = command(['sudo', '-n', '/usr/bin/nmcli', '--wait', '20', 'device', 'connect', interface], timeout=25)
        if result.returncode:
            raise RuntimeError('interface recovery failed')
        return 'interface recovery requested'


def main():
    global COMMAND_DEADLINE
    previous_deadline = COMMAND_DEADLINE
    COMMAND_DEADLINE = time.monotonic() + RECOVERY_BUDGET_SECONDS
    try:
        state = Path(os.environ.get('AR_LOCAL_NETWORK_STATE', '/run/ar-local-net-watchdog/state.json'))
        data = Path(os.environ.get('AR_LOCAL_DATA_ROOT', '/srv/ar-local/data'))
        print(recover(state, data, dry_run='--dry-run' in sys.argv))
    except (OSError, RuntimeError, ValueError, ImportError, subprocess.SubprocessError) as error:
        print(f'network watchdog check aborted: {type(error).__name__}', file=sys.stderr)
        return 1
    finally:
        COMMAND_DEADLINE = previous_deadline
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
