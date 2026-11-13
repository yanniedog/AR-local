"""Cleanup authority, current stop invocation, quiet hours and real POSIX leases."""
from contextlib import contextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import pi_manual_ingest_restore as restore


def details(**changes):
    return dict(Id=restore.UNIT, LoadState='loaded', ActiveState='deactivating',
                SubState='stop-post', MainPID='0', ControlPID='234', ExecMainPID='99999999',
                InvocationID='a' * 32, ControlGroup='/system.slice/' + restore.UNIT,
                User='pi', **changes)


def body(values):
    return ''.join(key + '=' + value + '\n' for key, value in values.items())


def test_own_stop_post_is_eligible_even_while_unit_deactivates():
    expected = details()
    assert restore.parse_context(body(expected), 'a' * 32, 234, expected['ControlGroup']) == expected


@pytest.mark.parametrize('field,value', [('ControlPID', '235'), ('MainPID', '42'),
    ('InvocationID', 'b' * 32), ('SubState', 'stop-sigterm'), ('ActiveState', 'active'),
    ('ExecMainPID', '0'), ('User', ''), ('ControlGroup', '/other'), ('Id', 'other.service')])
def test_another_or_live_invocation_is_never_ignored(field, value):
    values = details()
    values[field] = value
    with pytest.raises(ValueError):
        restore.parse_context(body(values), 'a' * 32, 234, '/system.slice/' + restore.UNIT)


@pytest.mark.parametrize('processes,root_user,allowed', [('self', False, True),
    ('self child', False, False), ('', False, False), ('self', True, False)])
def test_native_context_requires_sole_stop_process_and_nonroot_producer(monkeypatch, processes, root_user, allowed):
    current = details(); current['ControlPID'] = str(os.getpid())
    monkeypatch.setenv('INVOCATION_ID', 'a' * 32)
    account = SimpleNamespace(pw_uid=0 if root_user else 1000)
    monkeypatch.setitem(sys.modules, 'pwd', SimpleNamespace(getpwnam=lambda _: account))
    monkeypatch.setattr(restore, 'command', lambda *_: body(current))
    group = '/system.slice/' + restore.UNIT
    def read(path, limit=65536):
        if str(path) == '/proc/self/cgroup': return '0::' + group + '\n'
        return processes.replace('self', str(os.getpid())).replace('child', '987654321')
    monkeypatch.setattr(restore, 'bounded_read', read)
    monkeypatch.setattr(restore.os, 'walk', lambda *args, **kwargs: [('/sys/fs/cgroup' + group, [], [])])
    if allowed:
        assert restore.context() == (current, account)
    else:
        with pytest.raises(ValueError): restore.context()


@pytest.mark.parametrize('value,allowed', [('00:29:24', True), ('00:29:25', False),
    ('00:30:00', False), ('02:30:00', False), ('03:29:59', False), ('03:30:00', True),
    ('22:00:00', True), ('23:59:59', True)])
def test_restore_window_reserves_the_entire_start_and_cleanup_timeout(value, allowed):
    now = datetime.fromisoformat('2026-11-14T' + value).replace(tzinfo=ZoneInfo('Australia/Hobart'))
    assert restore.window_allowed(now) is allowed


def configured(monkeypatch):
    events = []
    @contextmanager
    def guard(*_):
        events.append('acquired')
        try:
            yield
        finally:
            events.append('released')
    monkeypatch.setattr(restore.os, 'geteuid', lambda: 0, raising=False)
    monkeypatch.setenv('AR_LOCAL_DATA_ROOT', '/srv/ar-local/data')
    monkeypatch.setattr(restore, 'context', lambda: (details(), SimpleNamespace(pw_uid=1000)))
    monkeypatch.setattr(restore, 'queue_guard', guard)
    monkeypatch.setattr(restore, 'native_lease', guard)
    monkeypatch.setattr(restore, 'window_allowed', lambda: True)
    monkeypatch.setattr(restore, 'other_owners_idle', lambda: True)
    monkeypatch.setattr(restore, 'command', lambda *args, **kwargs: events.append((args, kwargs)))
    return events


def test_only_fixed_dashboard_start_under_both_guards(monkeypatch):
    events = configured(monkeypatch)
    assert restore.recover('/srv/ar-local/data')
    assert events == ['acquired', 'acquired',
                      (('start', restore.DASHBOARD), {'timeout': 10}), 'released', 'released']


@pytest.mark.parametrize('reason', ['quiet', 'owner', 'invocation', 'nonroot', 'wrong-data'])
def test_no_restore_on_any_late_gate_change(monkeypatch, reason):
    events = configured(monkeypatch)
    if reason == 'quiet':
        clocks = iter([True, False])
        monkeypatch.setattr(restore, 'window_allowed', lambda: next(clocks))
    elif reason == 'owner':
        monkeypatch.setattr(restore, 'other_owners_idle', lambda: False)
    elif reason == 'invocation':
        current = details(); current['InvocationID'] = 'b' * 32
        contexts = iter([(details(), SimpleNamespace(pw_uid=1000)), (current, None)])
        monkeypatch.setattr(restore, 'context', lambda: next(contexts))
    elif reason == 'nonroot':
        monkeypatch.setattr(restore.os, 'geteuid', lambda: 1000)
    else:
        monkeypatch.setenv('AR_LOCAL_DATA_ROOT', '/other')
    if reason in ('nonroot', 'wrong-data'):
        with pytest.raises(ValueError): restore.recover('/srv/ar-local/data')
    else:
        assert not restore.recover('/srv/ar-local/data')
    assert not any(isinstance(item, tuple) for item in events)


@pytest.mark.skipif(os.name != 'posix', reason='real Linux flock/dirfd ownership protocol')
@pytest.mark.parametrize('previous', ['absent', 'own-dead', 'other-pid', 'other-role', 'manual-recovery', 'live-pid'])
def test_native_lease_reclaims_only_exact_dead_producer_and_preserves_bytes(tmp_path, previous):
    state = tmp_path / 'state'; state.mkdir()
    account = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    current = details()
    lock = state / restore.LOCK
    original = f"pid={current['ExecMainPID']}\nrole=ingest\nboot_id={boot}\n"
    if previous == 'other-pid': original = original.replace('99999999', '99999998')
    if previous == 'other-role': original = original.replace('role=ingest', 'role=backup')
    if previous == 'manual-recovery': original += 'recovery=manual\n'
    if previous == 'live-pid':
        original = original.replace('99999999', str(os.getpid()))
        current['ExecMainPID'] = str(os.getpid())
    if previous != 'absent': lock.write_text(original)
    if previous in ('absent', 'own-dead'):
        with restore.native_lease(str(tmp_path), current, account):
            assert 'role=manual-dashboard-restore' in lock.read_text()
        assert not lock.exists()
        retained = list(state.glob('.daily-ingest.lock.stale-*'))
        assert len(retained) == (1 if previous == 'own-dead' else 0)
        if retained: assert retained[0].read_text() == original
    else:
        with pytest.raises(ValueError):
            with restore.native_lease(str(tmp_path), current, account): pytest.fail('acquired foreign lease')
        assert lock.read_text() == original


@pytest.mark.skipif(os.name != 'posix', reason='real Linux queue flock protocol')
@pytest.mark.parametrize('jobs', [[], [{'state': 'waiting'}], [{'state': 'running'}], None])
def test_queue_guard_never_overwrites_or_ignores_occupied_state(tmp_path, monkeypatch, jobs):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(restore, 'QUEUE_ROOT', tmp_path)
    (tmp_path / 'queue.lock').write_bytes(b'')
    state = tmp_path / 'state.json'
    before = json.dumps({'version': 1, 'next_sequence': 0, 'jobs': jobs}).encode()
    state.write_bytes(before)
    if jobs == []:
        with restore.queue_guard(os.getuid()): pass
    else:
        with pytest.raises(ValueError):
            with restore.queue_guard(os.getuid()): pytest.fail('ignored queue owner')
    assert state.read_bytes() == before


def test_installer_and_service_do_not_elevate_repository_python():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'pi_manual_ingest_restore.py').read_text()
    assert 'from pi_' not in source and 'import pi_' not in source
    unit = (root / 'deploy/pi/ar-local-ingest-now.service').read_text()
    assert '+/usr/bin/python3 -I -S /usr/local/lib/ar-local-manual-ingest/' in unit
    assert '+/usr/bin/python3 {{AR_LOCAL_REPO}}' not in unit
    for name in ('install-pi-systemd.sh', 'apply-pi-runtime-units.sh'):
        text = (root / 'deploy/pi' / name).read_text()
        assert 'install-manual-ingest-restore.sh' in text
        assert text.index('install-manual-ingest-restore.sh') < text.index('sudo install -m 0644')
