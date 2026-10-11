"""Focused ownership and admission tests; no Windows signal-zero probing."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import pi_shared_queue as queue
from pi_shared_queue_store import Store, Supervisor, duration


def record(**changes):
    result = {'id': 'job-1', 'project': 'ar-local', 'resources': ['ar-local'],
              'mode': 'exclusive', 'cpu_slots': 1, 'max_duration_seconds': 600,
              'state': 'waiting', 'sequence': 0, 'queued_monotonic': 100,
              'pid': 123, 'start_ticks': 900, 'boot_id': '11111111-1111-4111-8111-111111111111',
              'unit': 'ar-local-payload-test.service', 'invocation_id': 'a' * 32,
              'cgroup': '/system.slice/ar-local-payload-test.service'}
    result.update(changes)
    return result


class FakeSupervisor(Supervisor):
    def __init__(self):
        self.details = {'InvocationID': 'a' * 32, 'ControlGroup': record()['cgroup'],
                        'ActiveState': 'active', 'MainPID': str(os.getpid()),
                        'CPUQuotaPerSecUSec': '1s', 'RuntimeMaxUSec': '1260s', 'Type': 'exec', 'KillMode': 'control-group',
                        'SendSIGKILL': 'yes', 'TimeoutStopUSec': '45s'}
        self.processes = [os.getpid()]
        self.boot = '11111111-1111-4111-8111-111111111111'
        self.wrapper = True

    def prepare(self, jobs): pass
    def terminate(self, job, signum): pass
    def boot_id(self): return self.boot
    def show(self, unit): return self.details
    def members(self, group): return self.processes
    def wrapper_alive(self, job): return self.wrapper
    def cgroup(self, pid): return record()['cgroup']
    def ticks(self, pid): return 900


class MemoryStore(Store):
    def __init__(self, jobs=(), supervisor=None):
        self.supervisor = supervisor or FakeSupervisor()
        self.state = {'version': 1, 'next_sequence': len(jobs), 'jobs': deepcopy(list(jobs))}

    @contextmanager
    def transaction(self):
        value = deepcopy(self.state)
        yield value
        Store.validate(value)
        self.state = value


NOW = datetime(2026, 10, 11, 4, 0, tzinfo=timezone.utc)


def test_monotonic_age_survives_wall_clock_jump():
    first = queue.policy_view([record()], NOW, 7300)[0]
    later_wall = datetime(2030, 1, 1, tzinfo=timezone.utc)
    second = queue.policy_view([record()], later_wall, 7300)[0]
    assert (NOW - first['ready_since']).total_seconds() == 7200
    assert (later_wall - second['ready_since']).total_seconds() == 7200
    with pytest.raises(ValueError):
        queue.policy_view([record()], NOW, 99)


def test_admission_persists_before_child_spawn_and_blocks_conflict():
    jobs = [record(), record(id='job-2', sequence=1)]
    store = MemoryStore(jobs)
    assert queue.admit(store, 'job-1', NOW, 101, pressure=lambda: True) == (True, 'admitted')
    assert store.state['jobs'][0]['state'] == 'running'
    assert queue.admit(store, 'job-2', NOW, 101, pressure=lambda: True) == (False, 'running-conflict')


def test_memory_pressure_does_not_claim_slot():
    store = MemoryStore([record()])
    assert queue.admit(store, 'job-1', NOW, 101, pressure=lambda: False) == (False, 'memory-pressure')
    assert store.state['jobs'][0]['state'] == 'waiting'


def test_wrapper_death_with_child_alive_retains_ownership():
    supervisor = FakeSupervisor()
    supervisor.wrapper = False
    supervisor.processes = [555]
    store = MemoryStore([record()], supervisor)
    assert not store.reconcile(store.state)
    assert store.state['jobs'][0]['state'] == 'waiting'
    assert not queue.release(store, record())


def test_running_record_survives_arbitrary_age_and_pid_reuse():
    supervisor = FakeSupervisor()
    supervisor.wrapper = False
    store = MemoryStore([record(state='running')], supervisor)
    store.reconcile(store.state)
    assert store.state['jobs'][0]['state'] == 'running'
    assert queue.admit(store, 'job-1', NOW, 999999, pressure=lambda: True) == (False, 'already-running')


def test_previous_boot_reclaims_but_unknown_live_cgroup_defers():
    supervisor = FakeSupervisor()
    assert supervisor.ownership(record(boot_id='22222222-2222-4222-8222-222222222222')) == 'gone'
    supervisor.details['InvocationID'] = 'b' * 32
    assert supervisor.ownership(record()) == 'unknown'
    store = MemoryStore([record()], supervisor)
    assert not store.reconcile(store.state)
    assert store.state['jobs'][0]['state'] == 'waiting'
    supervisor.processes = []
    supervisor.details['ActiveState'] = 'inactive'
    store.reconcile(store.state)
    assert store.state['jobs'] == []


def test_unknown_unit_state_never_reclaimed_with_empty_cgroup():
    supervisor = FakeSupervisor()
    supervisor.processes = []
    assert supervisor.ownership(record()) == 'unknown'


def test_descendants_prevent_successful_release():
    supervisor = FakeSupervisor()
    store = MemoryStore([record(state='running')], supervisor)
    supervisor.processes = [os.getpid(), 999]
    assert not queue.release(store, record())
    assert len(store.state['jobs']) == 1
    supervisor.processes = [os.getpid()]
    assert queue.release(store, record())
    assert store.state['jobs'] == []


def test_supervisor_requires_exact_mainpid_and_bounded_effective_quota():
    supervisor = FakeSupervisor()
    assert supervisor.current(1, 1200)['invocation_id'] == 'a' * 32
    supervisor.details['MainPID'] = '999'
    with pytest.raises(ValueError): supervisor.current(1, 1200)
    supervisor.details['MainPID'] = str(os.getpid())
    supervisor.details['CPUQuotaPerSecUSec'] = '2s'
    with pytest.raises(ValueError): supervisor.current(1, 1200)


def test_oneshot_uses_timeoutstart_not_ineffective_runtimemax():
    supervisor = FakeSupervisor()
    supervisor.details.update(Type='oneshot', RuntimeMaxUSec='infinity', TimeoutStartUSec='12h 2min')
    assert supervisor.current(1, 43260)
    supervisor.details['TimeoutStartUSec'] = 'infinity'
    with pytest.raises(ValueError): supervisor.current(1, 1200)


def test_supervisor_rejects_direct_ssh_cgroup():
    supervisor = FakeSupervisor()
    supervisor.cgroup = lambda pid: '/user.slice/session-1.scope'
    with pytest.raises(ValueError): supervisor.current(1, 100)


@pytest.mark.parametrize('changes', [
    {'invocation_id': 'wrong'}, {'unit': 'ssh.service'}, {'cgroup': '/../evil'},
    {'queued_monotonic': float('nan')}, {'pid': '123'}, {'state': 'complete'},
])
def test_invalid_ownership_state_rejected(changes):
    with pytest.raises(ValueError):
        Store.validate({'version': 1, 'next_sequence': 1, 'jobs': [record(**changes)]})


def test_memory_readback_fail_closed_and_threshold(tmp_path):
    path = tmp_path / 'meminfo'
    assert not queue.pressure_ready(path)
    path.write_text('MemAvailable: 1048575 kB\n')
    assert not queue.pressure_ready(path)
    path.write_text('MemAvailable: 1048576 kB\n')
    assert queue.pressure_ready(path)
    path.write_text('MemAvailable: invalid\n')
    assert not queue.pressure_ready(path)


def test_proc_start_ticks_handles_parenthesized_names(tmp_path):
    proc = tmp_path / '123'
    proc.mkdir()
    # Field 3 state, followed by fields 4..22; starttime is field 22.
    (proc / 'stat').write_text('123 (worker (private)) S ' + ' '.join(['0'] * 18 + ['987']))
    assert Supervisor(proc=tmp_path).ticks(123) == 987


def test_readonly_status_does_not_create_state(tmp_path, capsys):
    directory = tmp_path / 'missing'
    assert queue.status(directory) == 0
    assert not directory.exists()
    assert json.loads(capsys.readouterr().out)['jobs'] == []


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux flock and no-follow integration')
def test_real_store_atomic_write_and_corruption_fail_closed(tmp_path):
    root = tmp_path / 'queue'
    store = Store(root, FakeSupervisor())
    with store.transaction() as state:
        state['jobs'].append(record())
        state['next_sequence'] = 1
    with store.transaction() as state:
        assert state['jobs'][0]['id'] == 'job-1'
    (root / 'state.json').write_text('{broken')
    with pytest.raises(ValueError):
        with store.transaction():
            pytest.fail('corrupt state admitted')


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux flock integration')
def test_real_transactions_serialize_concurrent_processes(tmp_path):
    root = tmp_path / 'queue'
    script = '''from pathlib import Path
import sys,time
from pi_shared_queue_store import Store
store=Store(Path(sys.argv[1]))
with store.transaction() as state:
    old=state['next_sequence']
    time.sleep(.1)
    state['next_sequence']=old+1
'''
    processes = [subprocess.Popen([sys.executable, '-c', script, str(root)]) for _ in range(4)]
    assert all(process.wait(timeout=10) == 0 for process in processes)
    assert json.loads((root / 'state.json').read_text())['next_sequence'] == 4


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux no-follow integration')
def test_real_store_rejects_symlink_state(tmp_path):
    root = tmp_path / 'queue'
    root.mkdir(mode=0o700)
    outside = tmp_path / 'outside'
    outside.write_text('{}')
    (root / 'state.json').symlink_to(outside)
    with pytest.raises(OSError):
        with Store(root).transaction():
            pytest.fail('symlink state admitted')

def test_independent_projects_admitted_concurrently():
    jobs = [record(state='running'), record(id='mining-1', project='crypto-mining', resources=['mining'], sequence=1)]
    store = MemoryStore(jobs)
    assert queue.admit(store, 'mining-1', NOW, 101, pressure=lambda: True) == (True, 'admitted')
    assert all(job['state'] == 'running' for job in store.state['jobs'])


def test_incomplete_service_snapshot_defers_without_freeing_slots():
    supervisor = FakeSupervisor()
    def unavailable(jobs):
        raise ValueError('incomplete service snapshot')
    supervisor.prepare = unavailable
    store = MemoryStore([record(state='running')], supervisor)
    assert not store.reconcile(store.state)
    assert len(store.state['jobs']) == 1
    assert store.state['jobs'][0]['state'] == 'running'


def test_supervisor_rejects_excessively_long_finite_runtime():
    supervisor = FakeSupervisor()
    supervisor.details['RuntimeMaxUSec'] = '365d'
    with pytest.raises(ValueError):
        supervisor.current(1, 1200)


def test_only_proven_inactive_empty_cgroup_can_reclaim_current_boot():
    supervisor = FakeSupervisor()
    supervisor.processes = []
    supervisor.details['ActiveState'] = 'failed'
    assert supervisor.ownership(record()) == 'gone'
    supervisor.processes = [888]
    assert supervisor.ownership(record()) == 'live'

@pytest.mark.parametrize('changes', [
    {'boot_id': 'wrong-boot'}, {'boot_id': '11111111111141118111111111111111'},
    {'pid': 0}, {'start_ticks': 0}, {'cpu_slots': 4}, {'mode': 'unsafe'},
    {'resources': []}, {'resources': ['ar-local', 'ar-local']},
    {'resources': ['../host']}, {'project': '../other'}, {'max_duration_seconds': 21601},
])
def test_invalid_metadata_cannot_be_reclaimed_before_validation(changes):
    supervisor = FakeSupervisor()
    with pytest.raises(ValueError):
        supervisor.ownership(record(**changes))
    store = MemoryStore([record(**changes)], supervisor)
    with pytest.raises(ValueError):
        store.reconcile(store.state)
    assert len(store.state['jobs']) == 1


def test_ar_local_manual_queue_unit_is_supported():
    supervisor = FakeSupervisor()
    group = '/system.slice/ar-local-queue-task-123456.service'
    supervisor.cgroup = lambda pid: group
    supervisor.details['ControlGroup'] = group
    assert supervisor.current(1, 1200)['unit'] == 'ar-local-queue-task-123456.service'


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux child signal-mask integration')
def test_child_receives_graceful_sigterm_before_kill_deadline(monkeypatch, tmp_path):
    import time
    # Exercise the actual masked Popen path. The child handles TERM, records it
    # and exits itself; an inherited blocked mask would force the 30-second kill.
    marker = tmp_path / 'terminated'
    child = '''import signal,sys,time
from pathlib import Path
def stop(sig,frame):
    Path(sys.argv[1]).write_text('graceful')
    raise SystemExit(42)
signal.signal(signal.SIGTERM,stop)
while True: time.sleep(.01)
'''
    monkeypatch.setattr(queue, 'release', lambda store, job: True)
    started = time.monotonic()
    outcome = queue.execute(MemoryStore(), record(max_duration_seconds=1),
                            [sys.executable, '-c', child, str(marker)], queue.Cancellation())
    assert outcome == 124
    assert marker.read_text() == 'graceful'
    assert time.monotonic() - started < 5

@pytest.mark.parametrize('changed', [
    {'KillMode': 'process'}, {'KillMode': 'mixed'}, {'SendSIGKILL': 'no'},
    {'TimeoutStopUSec': 'infinity'}, {'TimeoutStopUSec': '61s'},
])
def test_supervisor_requires_hard_descendant_termination(changed):
    supervisor = FakeSupervisor()
    supervisor.details.update(changed)
    with pytest.raises(ValueError):
        supervisor.current(1, 1200)


def test_transient_snapshot_failure_recovers_waiting_admission_automatically():
    supervisor = FakeSupervisor()
    healthy = supervisor.prepare
    def unavailable(jobs):
        raise subprocess.TimeoutExpired('systemctl', 10)
    supervisor.prepare = unavailable
    store = MemoryStore([record()], supervisor)
    assert queue.admit(store, 'job-1', NOW, 101, pressure=lambda: True) == (False, 'ownership-observation-deferred')
    assert store.state['jobs'][0]['state'] == 'waiting'
    supervisor.prepare = healthy
    assert queue.admit(store, 'job-1', NOW, 102, pressure=lambda: True) == (True, 'admitted')


def test_transient_proc_failure_preserves_running_phase_and_slot():
    supervisor = FakeSupervisor()
    healthy = supervisor.members
    supervisor.members = lambda group: (_ for _ in ()).throw(PermissionError())
    store = MemoryStore([record(state='running'), record(id='job-2', sequence=1)], supervisor)
    assert queue.admit(store, 'job-2', NOW, 101, pressure=lambda: True) == (False, 'ownership-observation-deferred')
    assert store.state['jobs'][0]['state'] == 'running'
    supervisor.members = healthy
    assert queue.admit(store, 'job-2', NOW, 102, pressure=lambda: True) == (False, 'running-conflict')


def test_dead_waiting_wrapper_with_children_stays_deferred_until_empty():
    supervisor = FakeSupervisor()
    supervisor.wrapper = False
    supervisor.processes = [555]
    store = MemoryStore([record()], supervisor)
    assert not store.reconcile(store.state)
    assert store.state['jobs'][0]['state'] == 'waiting'
    assert not store.reconcile(store.state)
    assert len(store.state['jobs']) == 1
    supervisor.processes = []
    supervisor.details['ActiveState'] = 'inactive'
    assert store.reconcile(store.state)
    assert store.state['jobs'] == []

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
    assert queue.run_supervised(None, record(resources=['ar-local']), ['command'],
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


def test_escaped_descendant_deadline_targets_entire_unit_then_kills(monkeypatch):
    store = MemoryStore()
    signals = []
    store.supervisor.terminate = lambda job, signum: signals.append(signum)
    clock = [100]
    monkeypatch.setattr(queue.time, 'monotonic', lambda: clock[0])
    assert queue.enforce_cgroup_deadline(store, record(), 101, None) is None
    clock[0] = 101
    started = queue.enforce_cgroup_deadline(store, record(), 101, None)
    assert signals == ['SIGTERM']
    clock[0] = 130
    assert queue.enforce_cgroup_deadline(store, record(), 101, started) == 101
    assert signals == ['SIGTERM']
    clock[0] = 131
    queue.enforce_cgroup_deadline(store, record(), 101, started)
    assert signals == ['SIGTERM', 'SIGKILL']


def test_expired_host_guard_budget_never_spawns_child(monkeypatch):
    monkeypatch.setattr(queue.time, 'monotonic', lambda: 200)
    monkeypatch.setattr(subprocess, 'Popen', lambda *args, **kwargs: pytest.fail('expired job spawned'))
    assert queue.execute(None, record(), ['command'], queue.Cancellation(), deadline=199) == 75


def test_whole_unit_termination_rejects_changed_invocation(monkeypatch):
    supervisor = FakeSupervisor()
    supervisor.details['InvocationID'] = 'b' * 32
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: pytest.fail('wrong invocation killed'))
    with pytest.raises(ValueError):
        Supervisor.terminate(supervisor, record(pid=os.getpid()), 'SIGKILL')

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

def test_main_child_zero_with_escaped_descendant_deadline_returns_timeout(monkeypatch):
    import signal
    store = MemoryStore()
    clock, checks, signals = [100.0], [0], []
    cancelled = queue.Cancellation()
    class Child:
        pid = 999
        returncode = 0
        def poll(self): return 0
    def released(store, job):
        checks[0] += 1
        return checks[0] >= 3
    def terminate(job, signum):
        signals.append(signum)
        cancelled.requested = True  # Whole-unit TERM also reaches the wrapper.
    store.supervisor.terminate = terminate
    monkeypatch.setattr(signal, 'SIG_BLOCK', 0, raising=False)
    monkeypatch.setattr(signal, 'SIG_SETMASK', 2, raising=False)
    monkeypatch.setattr(signal, 'pthread_sigmask', lambda *args: set(), raising=False)
    monkeypatch.setattr(subprocess, 'Popen', lambda *args, **kwargs: Child())
    monkeypatch.setattr(queue, 'release', released)
    monkeypatch.setattr(queue.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(queue.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    assert queue.execute(store, record(), ['command'], cancelled, deadline=101) == 124
    assert signals == ['SIGTERM']


def test_operator_cancel_cannot_report_main_child_zero_as_success(monkeypatch):
    import signal
    cancelled = queue.Cancellation()
    class Child:
        pid = 999
        returncode = 0
        def poll(self): return 0
    def spawn(*args, **kwargs):
        cancelled.requested = True
        return Child()
    monkeypatch.setattr(signal, 'SIG_BLOCK', 0, raising=False)
    monkeypatch.setattr(signal, 'SIG_SETMASK', 2, raising=False)
    monkeypatch.setattr(signal, 'pthread_sigmask', lambda *args: set(), raising=False)
    monkeypatch.setattr(subprocess, 'Popen', spawn)
    monkeypatch.setattr(queue, 'release', lambda *args: True)
    assert queue.execute(MemoryStore(), record(), ['command'], cancelled) == 143

def collected_snapshot(unit):
    return (f'Id={unit}\nMainPID=0\nInvocationID=\nControlGroup=\n'
            'LoadState=not-found\nActiveState=inactive\n')


def test_collected_unit_nonzero_show_is_reclaimed_only_with_empty_cgroup(monkeypatch):
    unit = record()['unit']
    monkeypatch.setattr(subprocess, 'run', lambda command, **kwargs:
                        subprocess.CompletedProcess(command, 1, collected_snapshot(unit), f'Unit {unit} could not be found.\n'))
    supervisor = Supervisor()
    supervisor.boot_id = lambda: record()['boot_id']
    supervisor.members = lambda group: []
    supervisor.prepare([record()])
    assert supervisor.ownership(record()) == 'gone'
    supervisor._snapshot = None
    supervisor.members = lambda group: [999]
    assert supervisor.ownership(record()) == 'unknown'


@pytest.mark.parametrize('stderr', ['Failed to connect to bus: Permission denied',
                                    'Failed to get properties: Access denied',
                                    'Unit unrelated.service could not be found.'])
def test_collected_snapshot_does_not_hide_bus_or_permission_errors(monkeypatch, stderr):
    unit = record()['unit']
    monkeypatch.setattr(subprocess, 'run', lambda command, **kwargs:
                        subprocess.CompletedProcess(command, 1, collected_snapshot(unit), stderr))
    supervisor = Supervisor()
    with pytest.raises(subprocess.CalledProcessError):
        supervisor.prepare([record()])
    with pytest.raises(subprocess.CalledProcessError):
        supervisor.show(unit)


def test_incomplete_collected_unit_ownership_remains_untrusted(monkeypatch):
    unit = record()['unit']
    body = collected_snapshot(unit).replace('InvocationID=\n', '')
    monkeypatch.setattr(subprocess, 'run', lambda command, **kwargs:
                        subprocess.CompletedProcess(command, 1, body, f'Unit {unit} could not be found.'))
    with pytest.raises(subprocess.CalledProcessError):
        Supervisor().prepare([record()])


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

def test_operator_cancel_stops_escaped_descendants_immediately_before_budget(monkeypatch):
    import signal
    store, cancelled = MemoryStore(), queue.Cancellation()
    clock, checks, signals = [100.0], [0], []
    class Child:
        pid = 999
        returncode = 0
        def poll(self): return 0
    def released(store, job):
        checks[0] += 1
        if checks[0] == 1:
            cancelled.handle(signal.SIGTERM, None)
            return False
        return True
    store.supervisor.terminate = lambda job, signum: signals.append((signum, clock[0]))
    monkeypatch.setattr(signal, 'SIG_BLOCK', 0, raising=False)
    monkeypatch.setattr(signal, 'SIG_SETMASK', 2, raising=False)
    monkeypatch.setattr(signal, 'pthread_sigmask', lambda *args: set(), raising=False)
    monkeypatch.setattr(subprocess, 'Popen', lambda *args, **kwargs: Child())
    monkeypatch.setattr(queue, 'release', released)
    monkeypatch.setattr(queue.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(queue.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    assert queue.execute(store, record(), ['command'], cancelled, deadline=1900) == 143
    assert signals == [('SIGTERM', 100)]
    assert cancelled.stop_reason == 'operator'


def test_operator_cancel_escalates_after_thirty_seconds_before_execution_deadline(monkeypatch):
    store, cancelled, signals = MemoryStore(), queue.Cancellation(), []
    cancelled.requested = True
    clock = [100.0]
    store.supervisor.terminate = lambda job, signum: signals.append(signum)
    monkeypatch.setattr(queue.time, 'monotonic', lambda: clock[0])
    started = queue.enforce_cgroup_deadline(store, record(), 1900, None, cancelled)
    clock[0] = 130
    queue.enforce_cgroup_deadline(store, record(), 1900, started, cancelled)
    assert signals == ['SIGTERM', 'SIGKILL']
    assert cancelled.stop_reason == 'operator'


@pytest.mark.parametrize('signum,code,allowed', [
    ('SIGTERM', -15, True), ('SIGTERM', 1, False), ('SIGTERM', -9, False), ('SIGKILL', -15, False),
])
def test_verified_kill_all_expected_term_of_its_own_command_is_not_an_error(monkeypatch, signum, code, allowed):
    supervisor = FakeSupervisor()
    def killed(command, **kwargs):
        raise subprocess.CalledProcessError(code, command)
    monkeypatch.setattr(subprocess, 'run', killed)
    job = record(pid=os.getpid())
    if allowed:
        Supervisor.terminate(supervisor, job, signum)
    else:
        with pytest.raises(subprocess.CalledProcessError):
            Supervisor.terminate(supervisor, job, signum)

def fixed_record(**changes):
    result = record(unit='ar-local-daily.service', cgroup='/system.slice/ar-local-daily.service')
    result.update(changes)
    return result


def fixed_supervisor():
    supervisor = FakeSupervisor()
    supervisor.cgroup = lambda pid: fixed_record()['cgroup']
    supervisor.details['ControlGroup'] = fixed_record()['cgroup']
    return supervisor


def test_fixed_service_claim_covers_post_hooks_until_inactive_empty_cgroup():
    supervisor = fixed_supervisor()
    job = fixed_record(state='running', pid=os.getpid())
    store = MemoryStore([job], supervisor)
    assert not queue.release(store, job)
    supervisor.wrapper = False
    supervisor.processes = [777]  # ExecStartPost/ExecStopPost survives the wrapper.
    supervisor.details.update(MainPID='0', ActiveState='activating')
    assert store.reconcile(store.state)
    assert store.state['jobs'][0]['state'] == 'running'
    supervisor.processes = []
    assert not store.reconcile(store.state)  # Between hooks is not termination.
    assert len(store.state['jobs']) == 1
    supervisor.details['ActiveState'] = 'inactive'
    assert store.reconcile(store.state)
    assert store.state['jobs'] == []


def test_fixed_new_invocation_can_register_after_exact_wrapper_only_handoff():
    supervisor = fixed_supervisor()
    supervisor.details['InvocationID'] = 'b' * 32
    supervisor.wrapper = False
    owner = supervisor.current(1, 1200)
    old = fixed_record(state='running', pid=777, start_ticks=100)
    assert supervisor.ownership(old) == 'gone'
    store = MemoryStore([old], supervisor)
    new = queue.register(store, {'project': 'ar-local', 'resources': ['ar-local'],
                                'mode': 'exclusive', 'cpu_slots': 1, 'max_duration_seconds': 600}, owner, 100)
    assert store.state['jobs'] == [new]
    assert new['invocation_id'] == 'b' * 32 and new['state'] == 'waiting'


@pytest.mark.parametrize('uncertainty', ['child', 'old-wrapper-live', 'no-current-proof', 'old-wrapper-unknown'])
def test_fixed_handoff_never_reclaims_surviving_or_unverified_predecessor(uncertainty):
    supervisor = fixed_supervisor()
    supervisor.details['InvocationID'] = 'b' * 32
    supervisor.wrapper = False
    if uncertainty != 'no-current-proof':
        supervisor.current(1, 1200)
    if uncertainty == 'child': supervisor.processes = [os.getpid(), 555]
    if uncertainty == 'old-wrapper-live': supervisor.wrapper = True
    if uncertainty == 'old-wrapper-unknown':
        supervisor.wrapper_alive = lambda job: (_ for _ in ()).throw(PermissionError())
    old = fixed_record(state='running', pid=777, start_ticks=100)
    store = MemoryStore([old], supervisor)
    assert not store.reconcile(store.state)
    assert store.state['jobs'] == [old]


def test_fixed_service_execute_returns_without_releasing_or_waiting_for_own_exit(monkeypatch):
    import signal
    supervisor = fixed_supervisor()
    job = fixed_record(state='running', pid=os.getpid())
    store = MemoryStore([job], supervisor)
    class Child:
        pid = 999
        returncode = 0
        def poll(self): return 0
    monkeypatch.setattr(signal, 'SIG_BLOCK', 0, raising=False)
    monkeypatch.setattr(signal, 'SIG_SETMASK', 2, raising=False)
    monkeypatch.setattr(signal, 'pthread_sigmask', lambda *args: set(), raising=False)
    monkeypatch.setattr(subprocess, 'Popen', lambda *args, **kwargs: Child())
    assert queue.execute(store, job, ['command'], queue.Cancellation()) == 0
    assert store.state['jobs'] == [dict(job, command_started=True)]

@pytest.mark.parametrize('marker', [None, 0, 1, 'true', []])
def test_command_start_receipt_requires_bool(marker):
    with pytest.raises(ValueError):
        Store.validate({'version': 1, 'next_sequence': 1, 'jobs': [record(command_started=marker)]})


def test_fixed_waiting_registration_has_false_start_receipt():
    supervisor = fixed_supervisor()
    owner = supervisor.current(1, 1200)
    store = MemoryStore([], supervisor)
    job = queue.register(store, {'project': 'ar-local', 'resources': ['ar-local'],
                                'mode': 'exclusive', 'cpu_slots': 1, 'max_duration_seconds': 600}, owner, 100)
    assert job['state'] == 'waiting' and job['command_started'] is False
    with pytest.raises(ValueError):
        queue.mark_command_started(store, job)
    assert store.state['jobs'][0]['command_started'] is False


def test_fixed_spawn_receipt_persistence_failure_keeps_running_claim(monkeypatch):
    import signal
    job = fixed_record(state='running', pid=os.getpid(), command_started=False)
    store = MemoryStore([job], fixed_supervisor())
    class Child:
        pid = 999
        returncode = 0
        def poll(self):
            pytest.fail('child polled before spawn receipt committed')
    @contextmanager
    def failed_commit():
        raise OSError('receipt persistence unavailable')
        yield
    monkeypatch.setattr(store, 'transaction', failed_commit)
    monkeypatch.setattr(signal, 'SIG_BLOCK', 0, raising=False)
    monkeypatch.setattr(signal, 'SIG_SETMASK', 2, raising=False)
    monkeypatch.setattr(signal, 'pthread_sigmask', lambda *args: set(), raising=False)
    monkeypatch.setattr(subprocess, 'Popen', lambda *args, **kwargs: Child())
    with pytest.raises(OSError):
        queue.execute(store, job, ['command'], queue.Cancellation())
    assert store.state['jobs'] == [job]
    assert store.state['jobs'][0]['command_started'] is False
    assert not queue.release(store, job)


def test_legacy_records_without_command_marker_remain_valid_and_false_by_default():
    job = fixed_record(state='running')
    Store.validate({'version': 1, 'next_sequence': 1, 'jobs': [job]})
    assert job.get('command_started', False) is False


def _recovery_lock_factory(path):
    from cdr_file_lock import FileLock
    return FileLock(path.with_name('.' + path.name + '.recovery-lock'))
