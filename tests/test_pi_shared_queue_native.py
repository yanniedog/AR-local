"""Native AR-local transaction bridge and host admission tests."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import pi_shared_queue as queue
from pi_shared_queue_store import Store, Supervisor, duration
from tests.shared_pi_queue_fixtures import (
    NOW, FakeSupervisor, MemoryStore, NotifyFixture, collected_snapshot,
    fixed_record, fixed_supervisor, record, _recovery_lock_factory,
)


def test_host_native_busy_demotes_without_resetting_age_or_deadline(monkeypatch):
    from pi_shared_queue_native import NativeHostBusy
    store = MemoryStore([record(project='other', resources=['host'])])
    job = store.state['jobs'][0]
    deadlines, attempts, clock = [], [], [100.0]
    def admitted(store, job, seconds, cancelled, deadline=None):
        deadlines.append(deadline)
        store.state['jobs'][0]['state'] = 'running'
        return True
    class Guard:
        def __init__(self, store): pass
        @contextmanager
        def hold(self, job, deadline=None):
            attempts.append('guard')
            if len(attempts) == 1:
                raise NativeHostBusy('occupied')
            yield
    monkeypatch.setattr(queue, 'wait_admission', admitted)
    monkeypatch.setattr(queue.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(queue.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(queue, 'execute', lambda *args, **kwargs: 42)
    assert queue.run_supervised(store, job, ['private-argv'], 10, queue.Cancellation(), Guard) == 42
    assert deadlines == [110, 110]
    assert job['queued_monotonic'] == 100
    assert attempts == ['guard', 'guard']


def test_ar_local_native_command_is_never_nested_in_host_guard(monkeypatch):
    def forbidden(store):
        pytest.fail('AR-local must retain its own native lock acquisition')
    monkeypatch.setattr(queue, 'wait_admission', lambda *args, **kwargs: True)
    monkeypatch.setattr(queue, 'execute', lambda *args, **kwargs: 0)
    assert queue.run_supervised(MemoryStore(), record(resources=['ar-local']), ['command'],
                                10, queue.Cancellation(), forbidden) == 0


def test_native_host_guard_holds_production_lease_through_child_execution():
    from pi_shared_queue_native import NativeHostGuard
    store = MemoryStore([record(project='other', resources=['host'], state='running')])
    events = []
    @contextmanager
    def lease(path, role):
        assert path == Path('/srv/ar-local/data/state/daily-ingest.lock')
        assert role == 'shared-pi-host-task:job-1'
        events.append('locked')
        yield
        events.append('released')
    def ready(units):
        assert events == ['locked']
        assert record()['unit'] in units
        events.append('inspected')
        return True
    with NativeHostGuard(store, lock_factory=lambda: lease, ready=ready, marker=lambda job: None).hold(record()):
        assert events == ['locked', 'inspected']
        events.append('child')
    assert events == ['locked', 'inspected', 'child', 'released']


def test_legacy_service_busy_releases_native_lease_before_retry():
    from pi_shared_queue_native import NativeHostGuard, NativeHostBusy
    store = MemoryStore([record(state='running')])
    events = []
    @contextmanager
    def lease(path, role):
        events.append('locked')
        yield
        events.append('released')
    with pytest.raises(NativeHostBusy):
        with NativeHostGuard(store, lock_factory=lambda: lease, ready=lambda units: False, marker=lambda job: None).hold(record()):
            pytest.fail('legacy service busy must not execute')
    assert events == ['locked', 'released']


@pytest.mark.parametrize('failure', [ValueError('incomplete observation'), OSError('unavailable'), subprocess.TimeoutExpired('systemctl', 10)])
def test_transient_legacy_observation_is_busy_and_releases_lease(failure):
    from pi_shared_queue_native import NativeHostGuard, NativeHostBusy
    store = MemoryStore([record(state='running')])
    events = []
    @contextmanager
    def lease(*args):
        events.append('locked')
        try:
            yield
        finally:
            events.append('released')
    def unavailable(units):
        raise failure
    with pytest.raises(NativeHostBusy, match='observation unavailable'):
        with NativeHostGuard(store, lock_factory=lambda: lease, ready=unavailable, marker=lambda job: None).hold(record()):
            pytest.fail('uncertain legacy ownership must not start the command')
    assert events == ['locked', 'released']


def test_legacy_service_gate_ignores_readonly_and_completed_but_blocks_backup(monkeypatch):
    from pi_shared_queue_native import legacy_host_ready
    services = [
        {'unit': 'ar-local-runtime-health.service', 'active': 'active', 'sub': 'running'},
        {'unit': 'ar-local-daily.service', 'active': 'active', 'sub': 'running'},
        {'unit': 'ar-local-backup.service', 'active': 'active', 'sub': 'running'},
        {'unit': 'ar-local-capacity.service', 'active': 'active', 'sub': 'exited'},
    ]
    seen = []
    def inspect(command, **kwargs):
        seen.append(command)
        if 'list-units' in command:
            return subprocess.CompletedProcess(command, 0, json.dumps(services))
        if 'ar-local-backup.service' in command:
            return subprocess.CompletedProcess(command, 0, 'Id=ar-local-backup.service\nMainPID=456\nActiveState=active\nSubState=running\n\nId=ar-local-capacity.service\nMainPID=0\nActiveState=active\nSubState=exited\n')
        return subprocess.CompletedProcess(command, 0, 'Id=ar-local-capacity.service\nMainPID=0\nActiveState=active\nSubState=exited\n')
    monkeypatch.setattr(subprocess, 'run', inspect)
    assert not legacy_host_ready({'ar-local-daily.service'})
    assert len(seen) == 2
    assert not any('ar-local-runtime-health.service' in call for call in seen)
    services[:] = [services[-1]]
    assert legacy_host_ready(set())


def test_missing_native_helper_fails_closed(tmp_path):
    from pi_shared_queue_native import native_lock_factory
    with pytest.raises(ValueError):
        native_lock_factory(tmp_path)


def test_native_guard_does_not_release_while_host_descendants_survive(monkeypatch):
    import pi_shared_queue_native as store_module
    from pi_shared_queue_native import NativeHostGuard
    supervisor = FakeSupervisor()
    store = MemoryStore([record(state='running')], supervisor)
    events = []
    @contextmanager
    def lease(path, role):
        events.append('locked')
        yield
        events.append('released')
    def waited(seconds):
        assert events == ['locked', 'child-error']
        supervisor.processes = [os.getpid()]
        events.append('descendants-ended')
    monkeypatch.setattr(store_module.time, 'sleep', waited)
    with pytest.raises(ValueError):
        with NativeHostGuard(store, lock_factory=lambda: lease, ready=lambda units: True, marker=lambda job: None).hold(record()):
            supervisor.processes = [os.getpid(), 999]
            events.append('child-error')
            raise ValueError('child supervision failed')
    assert events == ['locked', 'child-error', 'descendants-ended', 'released']


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux native bridge lease durability')
def test_manual_native_bridge_retained_for_live_children_and_cleared_only_after_cgroup_proof(tmp_path, monkeypatch):
    import pi_shared_queue_native as module
    job = record(project='other', resources=['host'], state='running', pid=os.getpid())
    path = tmp_path / 'native.lock'
    path.write_text(f"pid={job['pid']}\nrole=shared-pi-host-task:{job['id']}\nboot_id={job['boot_id']}\n")
    module.mark_native_manual(job, path)
    assert 'recovery=manual\n' in path.read_text()
    supervisor = FakeSupervisor()
    supervisor.wrapper = False
    supervisor.processes = [555]
    store = MemoryStore([job], supervisor)
    original = module.clear_native_manual
    monkeypatch.setattr(module, 'clear_native_manual', lambda job: original(job, path, recovery_lock_factory=_recovery_lock_factory))
    assert store.reconcile(store.state)
    assert path.exists() and len(store.state['jobs']) == 1
    supervisor.processes = []
    supervisor.details['ActiveState'] = 'inactive'
    assert store.reconcile(store.state)
    assert not path.exists() and store.state['jobs'] == []


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux native bridge file identity')
@pytest.mark.parametrize('corruption', ['role', 'boot', 'pid', 'duplicate', 'truncated'])
def test_manual_native_bridge_mismatch_or_corruption_is_never_cleared(tmp_path, corruption):
    from pi_shared_queue_native import clear_native_manual
    job = record(project='other', resources=['host'], pid=os.getpid())
    body = f"pid={job['pid']}\nrole=shared-pi-host-task:{job['id']}\nboot_id={job['boot_id']}\nrecovery=manual\n"
    if corruption == 'role': body = body.replace('job-1', 'job-2')
    if corruption == 'boot': body = body.replace(job['boot_id'], '22222222-2222-4222-8222-222222222222')
    if corruption == 'pid': body = body.replace(f"pid={job['pid']}", 'pid=99999')
    if corruption == 'duplicate': body += 'recovery=manual\n'
    if corruption == 'truncated': body = body[:-3]
    path = tmp_path / 'native.lock'
    path.write_text(body)
    assert not clear_native_manual(job, path, recovery_lock_factory=_recovery_lock_factory)
    assert path.read_text() == body


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux real production lease bridge')
def test_real_native_helper_respects_manual_hold_and_unlinks_healthy_exit(tmp_path):
    from ar_local_operation_lock import production_lock, _existing_lock_is_stale
    from pi_shared_queue_native import mark_native_manual
    job = record(project='other', resources=['host'], pid=os.getpid(), boot_id=Supervisor().boot_id())
    path = tmp_path / 'native.lock'
    with production_lock(path, 'shared-pi-host-task:' + job['id']):
        mark_native_manual(job, path)
        # Even a provably dead PID cannot override the manual recovery field.
        body = path.read_text()
        path.write_text(body.replace(f"pid={job['pid']}", 'pid=2147483647'))
        assert not _existing_lock_is_stale(path)
        path.write_text(body)
    assert not path.exists()


def test_host_native_claim_remains_until_guard_has_exited(monkeypatch):
    store = MemoryStore([record(project='other', resources=['host'])])
    events = []
    class Guard:
        def __init__(self, store): self.store = store
        @contextmanager
        def hold(self, job, deadline=None):
            events.append('native-enter')
            yield
            assert self.store.state['jobs'][0]['state'] == 'running'
            events.append('native-exit')
    def admit(store, job, *args, **kwargs):
        store.state['jobs'][0]['state'] = 'running'
        return True
    def execute(store, job, command, cancelled, **kwargs):
        assert kwargs['release_claim'] is False
        events.append('command-finished')
        return 0
    monkeypatch.setattr(queue, 'wait_admission', admit)
    monkeypatch.setattr(queue, 'execute', execute)
    assert queue.run_supervised(store, store.state['jobs'][0], ['command'], 10,
                                queue.Cancellation(), Guard) == 0
    assert events == ['native-enter', 'command-finished', 'native-exit']


def test_ar_local_host_task_uses_native_bridge_and_retries_busy(monkeypatch):
    from pi_shared_queue_native import NativeHostBusy
    job = record(resources=['ar-local', 'host'])
    store = MemoryStore([job])
    attempts = []
    class Guard:
        def __init__(self, store): pass
        @contextmanager
        def hold(self, job, deadline=None):
            attempts.append(job['project'])
            raise NativeHostBusy('occupied')
            yield
    def admitted(store, job, *args, **kwargs):
        store.state['jobs'][0]['state'] = 'running'
        return True
    monkeypatch.setattr(queue, 'wait_admission', admitted)
    monkeypatch.setattr(queue, 'execute', lambda *args, **kwargs: pytest.fail('busy native lease executed'))
    assert queue.run_supervised(store, job, ['command'], 0, queue.Cancellation(), Guard) == 75
    assert attempts == ['ar-local']
    assert store.state['jobs'][0]['state'] == 'waiting'


def test_ar_local_host_completed_record_cleans_only_its_native_marker(monkeypatch):
    import pi_shared_queue_native as native
    job = record(resources=['ar-local', 'host'], state='running')
    supervisor = FakeSupervisor()
    supervisor.processes = []
    supervisor.details['ActiveState'] = 'inactive'
    store = MemoryStore([job], supervisor)
    cleaned = []
    monkeypatch.setattr(native, 'clear_native_manual', lambda job: cleaned.append(job['id']) or True)
    assert store.reconcile(store.state)
    assert cleaned == ['job-1'] and store.state['jobs'] == []


def test_deadline_arm_failure_never_enters_native_guard_or_spawns(monkeypatch):
    store = MemoryStore()
    def unavailable(job, deadline): raise ValueError('deadline unavailable')
    store.supervisor.arm_execution_deadline = unavailable
    monkeypatch.setattr(queue, 'wait_admission', lambda *a, **k: True)
    monkeypatch.setattr(queue, 'execute', lambda *a, **k: pytest.fail('unbounded execution'))
    with pytest.raises(ValueError):
        queue.run_supervised(store, record(resources=['host']), ['command'], 10,
                             queue.Cancellation(), lambda store: pytest.fail('native guard entered'))
