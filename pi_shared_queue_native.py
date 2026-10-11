"""Native AR-local lease bridge for supervised shared host operations."""
from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import inspect
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import time

from pi_shared_queue_store import validate_job

NATIVE_LOCK = Path('/srv/ar-local/data/state/daily-ingest.lock')
FIXED_ROOTS = {'AR_LOCAL_DATA_ROOT': '/srv/ar-local/data',
               'AR_LOCAL_PORTABLE_ROOT': '/srv/ar-local'}


def _fixed_root_values(values):
    for name, expected in FIXED_ROOTS.items():
        if name in values and values[name] != expected:
            raise ValueError('unsupported native bridge data configuration')


def _environment_file_roots(path):
    """Read only supported root assignments; never report environment contents."""
    try:
        with path.open('rb') as handle:
            body = handle.read(65537)
    except PermissionError:
        # Deployed environment files can contain credentials and have root-only
        # parent directories. Read a bounded, root-owned regular file privately;
        # stdout is captured and only root assignments leave this function.
        reader = (
            'import os,stat,sys\n'
            'try: fd=os.open(sys.argv[1],os.O_RDONLY|os.O_NOFOLLOW)\n'
            'except FileNotFoundError: sys.exit(44)\n'
            's=os.fstat(fd)\n'
            'if not (stat.S_ISREG(s.st_mode) and s.st_uid==0 and s.st_nlink==1 '
            'and not s.st_mode & 0o022 and s.st_size<=65536): '
            'raise ValueError("unsafe producer environment file")\n'
            'body=os.read(fd,65537); os.close(fd); os.write(1,body)'
        )
        try:
            result = subprocess.run(['sudo', '-n', '/usr/bin/python3', '-c', reader, str(path)],
                                    capture_output=True, timeout=10, check=True)
        except subprocess.CalledProcessError as exc:
            if exc.returncode == 44:
                raise FileNotFoundError(path) from None
            raise
        body = result.stdout
    if len(body) > 65536:
        raise ValueError('oversized producer environment file')
    values = {}
    for line in body.decode('utf-8').splitlines():
        match = re.match(r'^\s*(AR_LOCAL_DATA_ROOT|AR_LOCAL_PORTABLE_ROOT)\s*=(.*)$', line)
        if match:
            name, value = match.groups()
            value = value.strip()
            expected = FIXED_ROOTS[name]
            if value not in (expected, '"' + expected + '"', "'" + expected + "'"):
                raise ValueError('unsupported producer environment root assignment')
            values[name] = expected
    return values


def verify_native_deployment(environ=None, run=subprocess.run, resolve=None, read_roots=_environment_file_roots):
    """The native bridge supports this fixed Pi layout, never an inferred lock.

    systemctl's Environment excludes EnvironmentFile overrides. Inspect both,
    rejecting unsupported syntax rather than silently fencing the wrong data.
    """
    _fixed_root_values(os.environ if environ is None else environ)
    result = run(['systemctl', 'show', 'ar-local-daily.service', '--no-pager',
                  '--property=LoadState,Environment,EnvironmentFiles,PassEnvironment,UnsetEnvironment'],
                 text=True, capture_output=True, timeout=10, check=True)
    details, environment_files = {}, []
    for line in result.stdout.splitlines():
        key, separator, value = line.partition('=')
        if not separator:
            raise ValueError('ambiguous producer environment inspection')
        if key == 'EnvironmentFiles':
            environment_files.append(value)
        elif key in details:
            raise ValueError('duplicate producer environment inspection field')
        else:
            details[key] = value
    if environment_files:
        details['EnvironmentFiles'] = ' '.join(value for value in environment_files if value)
    required = {'LoadState', 'Environment', 'EnvironmentFiles', 'PassEnvironment', 'UnsetEnvironment'}
    if set(details) != required or details['LoadState'] != 'loaded':
        raise ValueError('producer environment inspection unavailable')
    for key in ('PassEnvironment', 'UnsetEnvironment'):
        if any(token.split('=', 1)[0] in FIXED_ROOTS for token in shlex.split(details[key])):
            raise ValueError('ambiguous producer root inheritance')
    environment = {}
    for token in shlex.split(details['Environment']):
        name, separator, value = token.partition('=')
        if not separator:
            raise ValueError('ambiguous producer environment')
        if name in FIXED_ROOTS:
            environment[name] = value
    _fixed_root_values(environment)
    files = details['EnvironmentFiles'].strip()
    entries = re.findall(r'(/[^\s]+) \(ignore_errors=(yes|no)\)', files)
    if len(entries) > 64 or ' '.join(path + ' (ignore_errors=' + optional + ')' for path, optional in entries) != files:
        raise ValueError('unsupported producer environment file configuration')
    for name, optional in entries:
        path = Path(name)
        if '..' in path.parts or any(char in name for char in '*?[]%\\'):
            raise ValueError('ambiguous producer environment file path')
        try:
            overrides = read_roots(path)
        except FileNotFoundError:
            if optional == 'yes':
                continue
            raise
        _fixed_root_values(overrides)
        environment.update(overrides)
    if environment.get('AR_LOCAL_DATA_ROOT') != FIXED_ROOTS['AR_LOCAL_DATA_ROOT']:
        raise ValueError('explicit fixed producer data root required')
    resolve = resolve or (lambda path: path.resolve(strict=True))
    for root in FIXED_ROOTS.values():
        if resolve(Path(root)) != Path(root):
            raise ValueError('native bridge roots must not contain symlinks')


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


def _native_recovery_lock(path):
    factory = native_lock_factory()
    # production_lock is decorated with contextmanager; the visible wrapper's
    # globals belong to contextlib, not the verified deployed source module.
    deployed = getattr(inspect.unwrap(factory), '__globals__', {})
    lock_type, recovery_path = deployed.get('FileLock'), deployed.get('recovery_lock_path')
    if not callable(lock_type) or not callable(recovery_path):
        raise ValueError('deployed native recovery lock API unavailable')
    return lock_type(recovery_path(path))


def clear_native_manual(job, path=NATIVE_LOCK, recovery_lock_factory=None):
    """After cgroup termination proof, serialize with legacy stale reclamation.

    The wrapper can die after lease acquisition but before its manual marker.
    Only its exact base or fully marked record is recoverable here.
    """
    try:
        validate_job(job)
        factory = recovery_lock_factory or _native_recovery_lock
        with factory(path):
            return _clear_native_owned_file(job, path)
    except (OSError, UnicodeError, ValueError, ImportError, subprocess.SubprocessError):
        return False


def _clear_native_owned_file(job, path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    try:
        info, values = _native_values(fd)
        expected = {'pid': str(job['pid']), 'boot_id': job['boot_id'],
                    'role': 'shared-pi-host-task:' + job['id']}
        if values != expected and values != dict(expected, recovery='manual'):
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
    verify_native_deployment()
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
