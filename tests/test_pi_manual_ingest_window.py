"""Real manual entrypoint admission, including stale installed argv and waits."""
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
import shlex

import pytest

import pi_daily_sync as daily
import pi_manual_ingest_window as window
from ar_local_ingest_schedule import DAILY_INGEST_TZ as TZ

ROOT = Path(__file__).resolve().parents[1]


def clock(value, day='2026-11-14'):
    return datetime.fromisoformat(day + 'T' + value).replace(tzinfo=TZ).astimezone(timezone.utc)


@pytest.mark.parametrize('day', ['2026-04-05', '2026-10-04', '2026-11-14'])
@pytest.mark.parametrize('value,allowed', [('00:00', False), ('00:29:59', False),
    ('00:30', False), ('02:30', False), ('03:29:59', False), ('03:30', True),
    ('17:14:59', True), ('17:15', False), ('22:00', False), ('23:59', False)])
def test_clock_and_full_existing_lifetime(day, value, allowed):
    if day == '2026-10-04' and value == '02:30':
        # This wall time does not exist: the UTC round trip is real 03:30.
        assert clock(value, day).astimezone(TZ).strftime('%H:%M') == '03:30'
        allowed = True
    if allowed:
        window.require_window(clock(value, day))
    else:
        with pytest.raises(RuntimeError):
            window.require_window(clock(value, day))


@pytest.mark.parametrize('group,manual', [
    ('/system.slice/ar-local-ingest-now.service', True),
    ('/system.slice/ar-local-ingest-now.service/child', True),
    ('/system.slice/ar-local-daily.service', False),
    ('/system.slice/ar-local-queue-task-daily-repair.service', False),
    ('/system.slice/ar-local-ingest-now.service-extra', False)])
def test_stale_argv_detected_by_exact_service_component(tmp_path, group, manual):
    path = tmp_path / 'cgroup'
    path.write_text('0::' + group + '\n', encoding='utf-8')
    assert window.manual_service(path) is manual


@pytest.mark.parametrize('content', ['', 'invalid', '0::relative', 'x::/system.slice', 'x' * 65537],
                         ids=['empty', 'missing-fields', 'relative', 'bad-id', 'oversize'])
def test_unknown_service_inventory_fails_closed(tmp_path, content):
    path = tmp_path / 'cgroup'
    path.write_text(content, encoding='utf-8')
    with pytest.raises(RuntimeError, match='context'):
        window.manual_service(path)


def test_actual_queue_can_admit0230_but_manual_child_cannot():
    from pi_shared_queue_policy import admission
    from tests.shared_pi_queue_fixtures import record
    now = clock('02:30')
    job = record(unit='ar-local-ingest-now.service', cpu_slots=3,
                 max_duration_seconds=21600, ready_since=now.isoformat())
    assert admission(job, [job], now) == (True, 'admitted')
    with pytest.raises(RuntimeError, match='00:30-03:30'):
        window.require_window(now)


@pytest.mark.parametrize('flag', [True, False])
def test_manual_rejects_before_runtime_writes_even_without_new_flag(monkeypatch, flag):
    monkeypatch.setattr(window, 'manual_service', lambda: True)
    real = window.require_window
    monkeypatch.setattr(window, 'require_window', lambda: real(clock('02:30')))
    monkeypatch.setattr(daily, 'ensure_runtime_data_writable', lambda *_: pytest.fail('runtime writes'))
    with pytest.raises(RuntimeError, match='00:30-03:30'):
        daily.main(['--force', *(['--manual-ingest'] if flag else [])])


def test_manual_rechecks_after_lock_wait(monkeypatch, tmp_path):
    real = window.require_window
    times = iter([clock('17:14:59'), clock('17:15')])
    monkeypatch.setattr(window, 'require_window', lambda: real(next(times)))
    monkeypatch.setattr(daily, 'ensure_runtime_data_writable', lambda *_: None)
    monkeypatch.setattr(daily, 'data_state_root', lambda *_: tmp_path)
    monkeypatch.setattr(daily, 'DailyIngestLock', lambda *_: nullcontext())
    monkeypatch.setattr(daily, 'pause_dashboard_for_ingest', lambda: pytest.fail('must not pause'))
    with pytest.raises(RuntimeError, match='7h15min'):
        daily.main(['--force', '--manual-ingest'])


def test_natural_and_claimed_repair_keep_their_own_admission(monkeypatch):
    monkeypatch.setattr(window, 'manual_service', lambda: False)
    monkeypatch.setattr(window, 'require_window', lambda: pytest.fail('not manual'))
    class ReachedExistingPath(Exception):
        pass
    def reached(*_):
        raise ReachedExistingPath
    monkeypatch.setattr(daily, 'ensure_runtime_data_writable', reached)
    for args in (['--banks-only'], ['--force', '--resume-same-day'], ['--force', '--quality-recapture']):
        with pytest.raises(ReachedExistingPath):
            daily.main(args)


def test_checked_in_unit_argv_and_lifetime_are_bound():
    direct = (ROOT / 'deploy/pi/ar-local-ingest-now.service').read_text()
    queued = (ROOT / 'deploy/pi/shared-queue-ingest-now.conf').read_text()
    for text in (direct, queued):
        argv = shlex.split(next(line.split('=', 1)[1] for line in text.splitlines()
                               if line.startswith('ExecStart=') and len(line) > len('ExecStart=')))
        script = next(i for i, item in enumerate(argv) if item.endswith('/pi_daily_sync.py'))
        assert daily.parse_args(argv[script + 1:]).manual_ingest is True
    assert '--max-runtime 21600' in queued and '--wait-timeout 21600' in queued
    assert 'TimeoutStartSec=46800s' in queued and 'TimeoutStopSec=900s' in queued
    assert window.LIFETIME_SECONDS == 21600 + (46800 - 21600 - 21600) + 900
    assert 'TimeoutStartSec=6h15min' in direct and 'TimeoutStopSec=45s' in direct
    assert window.LIFETIME_SECONDS >= 6 * 3600 + 15 * 60 + 45
    assert 'ExecStopPost=+/usr/bin/python3 -I -S /usr/local/lib/ar-local-manual-ingest/pi_manual_ingest_restore.py --data-root {{AR_LOCAL_DATA_ROOT}}' in direct
    wrapper = (ROOT / 'deploy/pi/cdr-ingest').read_text()
    assert wrapper.index('/usr/bin/python3 "$repo/pi_manual_ingest_window.py"') < wrapper.index('sudo systemctl reset-failed')


@pytest.mark.parametrize('args', [[], ['--force', '--quality-recapture'], ['--force', '--resume-same-day']])
def test_manual_flag_cannot_relabel_natural_or_bounded_modes(args):
    with pytest.raises(SystemExit):
        daily.parse_args([*args, '--manual-ingest'])
