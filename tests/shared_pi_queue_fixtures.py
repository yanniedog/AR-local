"""Shared queue test doubles; process control is injected on Windows."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import os

from pi_shared_queue_store import Store, Supervisor


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
    def arm_execution_deadline(self, job, deadline): pass
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


def collected_snapshot(unit):
    return (f'Id={unit}\nMainPID=0\nInvocationID=\nControlGroup=\n'
            'LoadState=not-found\nActiveState=inactive\n')


def fixed_record(**changes):
    result = record(unit='ar-local-daily.service', cgroup='/system.slice/ar-local-daily.service')
    result.update(changes)
    return result


def fixed_supervisor():
    supervisor = FakeSupervisor()
    supervisor.cgroup = lambda pid: fixed_record()['cgroup']
    supervisor.details['ControlGroup'] = fixed_record()['cgroup']
    return supervisor


def _recovery_lock_factory(path):
    from cdr_file_lock import FileLock
    return FileLock(path.with_name('.' + path.name + '.recovery-lock'))


class NotifyFixture:
    def __init__(self, monkeypatch):
        import pi_shared_queue_store as module
        self.supervisor = FakeSupervisor()
        self.job = record(pid=os.getpid(), project='other', max_duration_seconds=1800)
        self.supervisor.details.update(Type='notify', NotifyAccess='main',
                                       ActiveState='activating', RuntimeMaxUSec='1800s',
                                       TimeoutStartUSec='14460s')
        self.messages = []
        monkeypatch.setattr(module.time, 'monotonic', lambda: 120)
        monkeypatch.setenv('NOTIFY_SOCKET', '/fixture-notify')
        # The notifier is injected; older Windows Python lacks this constant.
        monkeypatch.setattr(module.socket, 'AF_UNIX', 1, raising=False)
        fixture = self
        class Notifier:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def settimeout(self, seconds): pass
            def connect(self, address): assert address == '/fixture-notify'
            def sendall(self, message):
                fixture.messages.append(message)
                fixture.supervisor.details.update(ActiveState='active',
                                                  ActiveEnterTimestampMonotonic='120000000')
        monkeypatch.setattr(module.socket, 'socket', lambda *a: Notifier())
