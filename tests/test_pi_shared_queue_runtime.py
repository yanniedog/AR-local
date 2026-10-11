"""Queue admission, durable state and ownership recovery tests."""
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


def test_oneshot_uses_timeoutstart_not_ineffective_runtimemax():
    supervisor = FakeSupervisor()
    supervisor.details.update(Type='oneshot', RuntimeMaxUSec='infinity', TimeoutStartUSec='12h 2min')
    assert supervisor.current(1, 43260)
    supervisor.details['TimeoutStartUSec'] = 'infinity'
    with pytest.raises(ValueError): supervisor.current(1, 1200)


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


def test_expired_host_guard_budget_never_spawns_child(monkeypatch):
    monkeypatch.setattr(queue.time, 'monotonic', lambda: 200)
    monkeypatch.setattr(subprocess, 'Popen', lambda *args, **kwargs: pytest.fail('expired job spawned'))
    assert queue.execute(None, record(), ['command'], queue.Cancellation(), deadline=199) == 75


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


def test_unreadable_descendants_retain_claim_until_observation_recovers():
    store = MemoryStore([record(state='running')])
    def unavailable(group): raise PermissionError('cgroup unavailable')
    store.supervisor.members = unavailable
    assert not queue.descendants_done(store, record())
    assert not queue.release(store, record())
    assert len(store.state['jobs']) == 1
    store.supervisor.members = lambda group: [os.getpid()]
    assert queue.release(store, record())
