"""Require OS-enforced containment before a backfill owns the production lock."""
from __future__ import annotations

import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ar_local_pi_runtime import PI_DATA_ROOT, data_runs_root

TZ = ZoneInfo('Australia/Hobart')


def _seconds(value: str) -> float:
    units = {'us': 1e-6, 'ms': .001, 's': 1, 'min': 60, 'h': 3600, 'd': 86400}
    if value == '0':
        return 0
    parts = re.findall(r'(\d+(?:\.\d+)?)(us|ms|min|s|h|d)', value)
    if not parts or ''.join(n + u for n, u in parts) != value.replace(' ', ''):
        raise RuntimeError('backfill requires finite systemd time bounds')
    return sum(float(n) * units[u] for n, u in parts)


def _unit_properties() -> dict[str, str]:
    try:
        groups = Path('/proc/self/cgroup').read_text(encoding='utf8').splitlines()
        units = {line.rsplit('/', 1)[-1] for line in groups if line.endswith('.service')}
        if len(units) != 1:
            raise ValueError('no unique containing service')
        unit = units.pop()
        if not re.fullmatch(r'[A-Za-z0-9_.@\\-]+\.service', unit):
            raise ValueError('invalid containing unit')
        fields = ('Type,ActiveState,KillMode,SendSIGKILL,FinalKillSignal,TimeoutStopFailureMode,'
                  'ExecStop,ExecStopPost,Restart,RuntimeMaxUSec,TimeoutStopUSec,RuntimeRandomizedExtraUSec')
        result = subprocess.run(['systemctl', 'show', unit, '--no-pager', '--all', '--property=' + fields],
            check=True, capture_output=True, text=True, timeout=5)
        return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise RuntimeError('production backfill requires a bounded systemd service') from exc


def validate_containment(properties: dict[str, str], now: datetime) -> None:
    now = now.astimezone(TZ)
    minute = now.hour * 60 + now.minute
    if not 210 <= minute < 1320:
        raise RuntimeError('backfill quiet window: starts allowed 03:30-22:00 Hobart')
    if (properties.get('Type') not in {'exec', 'simple'}
            or properties.get('ActiveState') != 'active'
            or properties.get('KillMode') != 'control-group'
            or properties.get('SendSIGKILL') != 'yes'
            or properties.get('FinalKillSignal') != '9'
            or properties.get('TimeoutStopFailureMode') not in {'terminate', 'kill'}
            or properties.get('ExecStop') != '' or properties.get('ExecStopPost') != ''
            or properties.get('Restart') != 'no'):
        raise RuntimeError('backfill requires active non-restarting service with full process-tree termination')
    runtime = _seconds(properties.get('RuntimeMaxUSec', 'infinity'))
    stop = _seconds(properties.get('TimeoutStopUSec', 'infinity'))
    extra = _seconds(properties.get('RuntimeRandomizedExtraUSec', '0'))
    freeze = (now + timedelta(days=1)).replace(hour=0, minute=30, second=0, microsecond=0)
    # Conservatively charge the entire configured lifetime, even if already running.
    if not (0 < runtime <= 3600 and 0 <= stop <= 30 and extra == 0
            and runtime + stop + 60 < (freeze - now).total_seconds()):
        raise RuntimeError('backfill runtime must terminate before the 00:30 ingest freeze')


def require_backfill_window(runs_root: Path, repo_root: Path) -> None:
    # Private copies do not hold the scheduled Pi's lock. Resolve aliases and also
    # protect the canonical Pi root when a caller changes its runtime environment.
    targets = {data_runs_root(repo_root).resolve(), (PI_DATA_ROOT / 'runs').resolve()}
    locks = {(root.parent / 'state/daily-ingest.lock').resolve() for root in targets}
    if (runs_root.resolve() not in targets
            and (runs_root.parent / 'state/daily-ingest.lock').resolve() not in locks):
        return
    validate_containment(_unit_properties(), datetime.now(TZ))
