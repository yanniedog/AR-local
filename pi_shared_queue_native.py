"""Native AR-local lease bridge for supervised shared host operations."""
from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

from pi_shared_queue_store import validate_job

NATIVE_LOCK = Path('/srv/ar-local/data/state/daily-ingest.lock')


def _native_values(fd):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_size > 16384:
        raise ValueError('unsafe native bridge lease')
    os.lseek(fd, 0, os.SEEK_SET)
    text = os.read(fd, 16385).decode('ascii')
    values = {}
    for line in text.splitlines():
        key, separator, value = line.partition('=')
        if not separator or not key or key in values:
            raise ValueError('ambiguous native bridge lease')
        values[key] = value
    return info, values


def mark_native_manual(job, path=NATIVE_LOCK):
    """Before spawning, prevent legacy dead-PID recovery until cgroup proof."""
    validate_job(job)
    fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW)
    try:
        _, values = _native_values(fd)
        expected = {'pid': str(job['pid']), 'boot_id': job['boot_id'],
                    'role': 'shared-pi-host-task:' + job['id']}
        if values != expected or job['pid'] != os.getpid():
            raise ValueError('native bridge lease ownership mismatch')
        os.write(fd, b'recovery=manual\n')
        os.fsync(fd)
    finally:
        os.close(fd)


def clear_native_manual(job, path=NATIVE_LOCK):
    """Called only after exact service termination proof under queue.lock."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    try:
        info, values = _native_values(fd)
        expected = {'pid': str(job['pid']), 'boot_id': job['boot_id'],
                    'role': 'shared-pi-host-task:' + job['id'], 'recovery': 'manual'}
        if values != expected:
            return False
        current = path.lstat()
        if (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino):
            return False
        path.unlink()
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return True
    except (OSError, UnicodeError, ValueError):
        return False
    finally:
        os.close(fd)


class NativeHostBusy(RuntimeError):
    """A legacy AR-local operation has not yielded its native transaction lock."""


def native_lock_factory(repo=Path('/srv/ar-local/AR-local')):
    """Load the deployed lock implementation without shadowing queue modules."""
    path = repo / 'ar_local_operation_lock.py'
    if not path.is_file() or path.is_symlink():
        raise ValueError('deployed production lock helper is unavailable')
    # These dependency names are shared by the deployed helper; reject a cached
    # module from a different source before importing the reviewed implementation.
    for name in ('ar_local_backup_policy', 'cdr_file_lock', 'process_safety'):
        cached = sys.modules.get(name)
        if cached is not None and Path(getattr(cached, '__file__', '')).resolve().parent != repo.resolve():
            raise ValueError('production helper dependency source collision')
    old_path = list(sys.path)
    try:
        sys.path.insert(0, str(repo))
        spec = importlib.util.spec_from_file_location('_shared_pi_native_lock', path)
        if spec is None or spec.loader is None:
            raise ValueError('production helper loader unavailable')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        factory = getattr(module, 'production_lock', None)
        if not callable(factory):
            raise ValueError('deployed production lock function unavailable')
        return factory
    finally:
        sys.path[:] = old_path


def legacy_host_ready(registered_units):
    """Read-only legacy service gate; uncertainty is never eligibility."""
    result = subprocess.run(['systemctl', 'list-units', '--all', '--type=service',
                             '--output=json', 'ar-local-*.service'],
                            text=True, capture_output=True, timeout=10, check=True)
    services = json.loads(result.stdout)
    if not isinstance(services, list) or len(services) > 1024:
        raise ValueError('invalid legacy service inspection')
    excluded = {'ar-local-dashboard.service', 'ar-local-runtime-health.service',
                'ar-local-deploy-watchdog.service', 'ar-local-net-watchdog.service'}
    units = []
    for service in services:
        if not isinstance(service, dict) or not all(key in service for key in ('unit', 'active', 'sub')):
            raise ValueError('incomplete legacy service inspection')
        unit = service['unit']
        if not isinstance(unit, str) or not unit.startswith('ar-local-') or not unit.endswith('.service'):
            raise ValueError('unexpected legacy service unit')
        if unit in registered_units or unit in excluded or service['active'] in ('inactive', 'failed'):
            continue
        if service['active'] not in ('active', 'activating', 'deactivating'):
            raise ValueError('unknown legacy service state')
        units.append(unit)
    if not units:
        return True
    if len(set(units)) != len(units):
        raise ValueError('duplicate legacy service unit')
    result = subprocess.run(['systemctl', 'show', *units, '--property=Id,MainPID,ActiveState,SubState'],
                            text=True, capture_output=True, timeout=10, check=True)
    snapshot = {}
    for block in result.stdout.strip().split('\n\n'):
        values = dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
        if values.get('Id') in snapshot or values.get('Id') not in units or 'MainPID' not in values:
            raise ValueError('ambiguous legacy service snapshot')
        snapshot[values['Id']] = values
    if set(snapshot) != set(units):
        raise ValueError('incomplete legacy service snapshot')
    for values in snapshot.values():
        pid = int(values['MainPID'])
        if pid < 0:
            raise ValueError('invalid legacy service PID')
        if values.get('ActiveState') in ('inactive', 'failed'):
            continue
        if values.get('ActiveState') == 'active' and values.get('SubState') == 'exited' and pid == 0:
            continue
        return False
    return True



class NativeHostGuard:
    def __init__(self, store, lock_factory=native_lock_factory, ready=legacy_host_ready, marker=mark_native_manual):
        self.store, self.lock_factory, self.ready = store, lock_factory, ready
        self.marker = marker

    @contextmanager
    def hold(self, job, deadline=None):
        validate_job(job)
        factory = self.lock_factory()
        lease = factory(NATIVE_LOCK, 'shared-pi-host-task:' + job['id'])
        try:
            lease.__enter__()
        except RuntimeError as exc:
            raise NativeHostBusy('native AR-local transaction is occupied') from exc
        try:
            self.marker(job)
            with self.store.transaction() as state:
                if not self.store.reconcile(state):
                    raise NativeHostBusy('queue ownership observation unavailable')
                units = {job['unit'] for job in state['jobs']}
            if not self.ready(units):
                raise NativeHostBusy('legacy AR-local service occupies the host')
            yield
        finally:
            # Do not expose legacy AR-local to surviving host-task children if
            # execution or a readback fails. The verified unit hard deadline
            # eventually terminates the whole cgroup and its native lock owner.
            stop_started = None
            while True:
                try:
                    group = self.store.supervisor.cgroup(os.getpid())
                    if self.store.supervisor.members(group) == [os.getpid()]:
                        break
                except (OSError, ValueError):
                    pass
                now = time.monotonic()
                if deadline is not None and now >= deadline:
                    signum = 'SIGTERM' if stop_started is None else 'SIGKILL' if now - stop_started >= 30 else None
                    if signum is not None:
                        try:
                            self.store.supervisor.terminate(job, signum)
                        except (OSError, ValueError, subprocess.SubprocessError):
                            print(json.dumps({'job_id': job['id'], 'project': job['project'],
                                              'reason': 'native-cgroup-termination-unavailable'}), flush=True)
                        stop_started = now
                time.sleep(1)
            lease.__exit__(None, None, None)
