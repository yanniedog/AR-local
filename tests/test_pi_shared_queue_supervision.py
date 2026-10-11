"""Service lifecycle, process termination and execution budget tests."""
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


def test_supervisor_requires_exact_mainpid_and_bounded_effective_quota():
    supervisor = FakeSupervisor()
    assert supervisor.current(1, 1200)['invocation_id'] == 'a' * 32
    supervisor.details['MainPID'] = '999'
    with pytest.raises(ValueError): supervisor.current(1, 1200)
    supervisor.details['MainPID'] = str(os.getpid())
    supervisor.details['CPUQuotaPerSecUSec'] = '2s'
    with pytest.raises(ValueError): supervisor.current(1, 1200)


def test_supervisor_rejects_direct_ssh_cgroup():
    supervisor = FakeSupervisor()
    supervisor.cgroup = lambda pid: '/user.slice/session-1.scope'
    with pytest.raises(ValueError): supervisor.current(1, 100)


def test_supervisor_rejects_excessively_long_finite_runtime():
    supervisor = FakeSupervisor()
    supervisor.details['RuntimeMaxUSec'] = '365d'
    with pytest.raises(ValueError):
        supervisor.current(1, 1200)


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


def test_whole_unit_termination_rejects_changed_invocation(monkeypatch):
    supervisor = FakeSupervisor()
    supervisor.details['InvocationID'] = 'b' * 32
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: pytest.fail('wrong invocation killed'))
    with pytest.raises(ValueError):
        Supervisor.terminate(supervisor, record(pid=os.getpid()), 'SIGKILL')


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


def test_fixed_service_has_bounded_additional_post_hook_startup_budget():
    supervisor = fixed_supervisor()
    supervisor.details.update(Type='oneshot', TimeoutStartUSec='13h')
    assert supervisor.current(1, 43260)['unit'] == 'ar-local-daily.service'
    supervisor.details['TimeoutStartUSec'] = '14h'
    with pytest.raises(ValueError):
        supervisor.current(1, 43260)


def test_transient_service_cannot_use_fixed_service_post_hook_allowance():
    supervisor = FakeSupervisor()
    supervisor.details['RuntimeMaxUSec'] = '13h'
    with pytest.raises(ValueError):
        supervisor.current(1, 43260)


def test_transient_fallback_discards_unused_waiting_allowance(monkeypatch):
    fixture = NotifyFixture(monkeypatch)
    supervisor = fixture.supervisor
    assert supervisor.current(1, 16260, execution_runtime=1800, wait_seconds=14400)
    Supervisor.arm_execution_deadline(supervisor, fixture.job, 1920)
    assert fixture.messages == [b'READY=1']
    # Execution activated at admission, without the 14400s waiting allowance.
    assert 120 + duration(supervisor.details['RuntimeMaxUSec']) + 45 <= 1920 + 60
    Supervisor.arm_execution_deadline(supervisor, fixture.job, 1921)
    assert fixture.messages == [b'READY=1']  # Native-lock retry never resets PID 1.


@pytest.mark.parametrize('failure', ['notify-failed', 'new-invocation', 'bad-clock',
                                   'long-stop', 'extended-runtime', 'missing-socket'])
def test_transient_deadline_arm_fails_closed(monkeypatch, failure):
    import pi_shared_queue_store as module
    fixture = NotifyFixture(monkeypatch)
    if failure == 'notify-failed':
        monkeypatch.setattr(module.socket, 'socket', lambda *a: (_ for _ in ()).throw(OSError()))
    elif failure == 'new-invocation': fixture.supervisor.details['InvocationID'] = 'b' * 32
    elif failure == 'long-stop': fixture.supervisor.details['TimeoutStopUSec'] = '60s'
    elif failure == 'extended-runtime': fixture.supervisor.details['RuntimeMaxUSec'] = '16320s'
    elif failure == 'missing-socket': monkeypatch.delenv('NOTIFY_SOCKET')
    elif failure == 'bad-clock':
        fixture.supervisor.details.update(ActiveState='active', ActiveEnterTimestampMonotonic='0')
    with pytest.raises((ValueError, OSError)):
        Supervisor.arm_execution_deadline(fixture.supervisor, fixture.job, 1920)


@pytest.mark.parametrize('unit,seconds,accepted', [
    ('ar-local-daily.service', 900, True),
    ('ar-local-daily.service', 901, False),
    ('shared-pi-task-test.service', 900, False),
])
def test_only_fixed_lifecycle_hooks_receive_larger_stop_budget(unit, seconds, accepted):
    supervisor = FakeSupervisor()
    group = '/system.slice/' + unit
    supervisor.cgroup = lambda pid: group
    supervisor.details.update(ControlGroup=group, TimeoutStopUSec=f'{seconds}s')
    if accepted:
        assert supervisor.current(1, 1200)
    else:
        with pytest.raises(ValueError): supervisor.current(1, 1200)


@pytest.mark.parametrize('change', [{'RuntimeMaxUSec': '16320s'},
                                   {'TimeoutStartUSec': 'infinity'},
                                   {'TimeoutStartUSec': '14400s'}])
def test_notify_wait_and_execution_timers_are_verified_separately(monkeypatch, change):
    fixture = NotifyFixture(monkeypatch)
    fixture.supervisor.details.update(change)
    with pytest.raises(ValueError):
        fixture.supervisor.current(1, 16260, execution_runtime=1800, wait_seconds=14400)


def test_late_systemd_activation_cannot_exceed_reserved_quiet_window_grace(monkeypatch):
    import pi_shared_queue_store as module
    fixture = NotifyFixture(monkeypatch)
    fixture.supervisor.details.update(ActiveState='active', ActiveEnterTimestampMonotonic='136000000')
    monkeypatch.setattr(module.time, 'monotonic', lambda: 136)
    with pytest.raises(ValueError, match='deadline readback'):
        Supervisor.arm_execution_deadline(fixture.supervisor, fixture.job, 1920)
