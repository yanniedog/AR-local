"""Bounded, interface-only network recovery for the shared Pi (no global restart)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


def command(args, *, timeout=5):
    return subprocess.run(args, capture_output=True, text=True, check=False, timeout=timeout)


def remote_sessions_active() -> bool:
    # Fail closed if either source of session evidence is unavailable.
    ssh = command(['ss', '-Htn', 'state', 'established', '( sport = :22 )'])
    users = command(['who'])
    remote_login = any(not re.fullmatch(r':\d+(?:\.\d+)?', host)
                       for host in re.findall(r'\(([^)]+)\)', users.stdout))
    return ssh.returncode != 0 or users.returncode != 0 or bool(ssh.stdout.strip()) or remote_login


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
    repo = Path(os.environ.get('AR_LOCAL_REPO', '/srv/ar-local/AR-local'))
    sys.path.insert(0, str(repo))
    from ar_local_operation_lock import production_lock
    with production_lock(data / 'state/daily-ingest.lock', 'network-watchdog'):
        units = command(['systemctl', 'is-active', 'ar-local-daily.service',
                         'ar-local-ingest-now.service', 'ar-local-daily-watchdog.service'])
        states = units.stdout.splitlines()
        if len(states) != 3 or any(value not in {'inactive', 'failed'} for value in states):
            return 'recovery deferred: ingest active or unknown'
        if remote_sessions_active() or default_route() != (gateway, interface):
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
        print(recover(state, data, dry_run='--dry-run' in sys.argv))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f'recovery deferred: {type(error).__name__}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
