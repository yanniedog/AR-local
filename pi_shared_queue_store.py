"""Crash-safe state transactions and systemd ownership checks for the Pi queue."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import stat
import signal
import subprocess
import tempfile
import uuid

MAX_BYTES = 1024 * 1024
UNIT = re.compile(r'(?:ar-local-(?:daily|daily-watchdog|ingest-now)|ar-local-payload-[a-zA-Z0-9_.-]+|ar-local-queue-task-[a-zA-Z0-9_.-]+|shared-pi-task-[a-zA-Z0-9_.-]+)\.service\Z')


NAME = re.compile(r'[a-z0-9][a-z0-9_.-]{0,63}\Z')


def validate_job(job):
    required = {'id','project','resources','mode','cpu_slots','max_duration_seconds','state','sequence','queued_monotonic','pid','start_ticks','boot_id','unit','invocation_id','cgroup'}
    if not isinstance(job, dict) or set(job) != required or job['state'] not in ('waiting', 'running', 'quarantined'):
        raise ValueError('invalid queue record')
    for name in ('id', 'project'):
        if not isinstance(job[name], str) or not NAME.fullmatch(job[name]):
            raise ValueError('invalid queue name')
    for name in ('boot_id', 'unit', 'invocation_id', 'cgroup'):
        if not isinstance(job[name], str) or not 1 <= len(job[name]) <= 256:
            raise ValueError('invalid ownership metadata')
    if str(uuid.UUID(job['boot_id'])) != job['boot_id']:
        raise ValueError('boot ID must be a canonical UUID')
    if not UNIT.fullmatch(job['unit']) or not job['cgroup'].startswith('/') or not job['cgroup'].endswith('/' + job['unit']) or '..' in Path(job['cgroup']).parts:
        raise ValueError('unsafe unit ownership')
    if not re.fullmatch('[0-9a-f]{32}', job['invocation_id']):
        raise ValueError('invalid invocation')
    limits = {'pid': (1, 2**31-1), 'start_ticks': (1, 2**63-1), 'sequence': (0, 2**63-1),
              'cpu_slots': (1, 3 if job['project'] == 'ar-local' else 1),
              'max_duration_seconds': (1, 21600 if job['project'] == 'ar-local' else 1800)}
    for name, (low, high) in limits.items():
        if type(job[name]) is not int or not low <= job[name] <= high:
            raise ValueError('invalid bounded integer metadata')
    if job['mode'] not in ('shared', 'exclusive'):
        raise ValueError('invalid resource mode')
    resources = job['resources']
    if not isinstance(resources, list) or not 1 <= len(resources) <= 32:
        raise ValueError('invalid resource declarations')
    if any(not isinstance(name, str) or not NAME.fullmatch(name) for name in resources) or len(set(resources)) != len(resources):
        raise ValueError('invalid resource name')
    if job['project'] == 'ar-local' and 'ar-local' not in resources:
        raise ValueError('AR-local resource declaration required')
    if type(job['queued_monotonic']) not in (int, float) or not 0 <= job['queued_monotonic'] < 1e15:
        raise ValueError('invalid monotonic metadata')


def duration(value):
    if value in ('infinity', '[not set]', ''):
        raise ValueError('unbounded supervisor setting')
    total = 0.0
    for number, suffix in re.findall(r'([0-9.]+)(us|ms|s|min|h|d)', value):
        total += float(number) * {'us': 1e-6, 'ms': .001, 's': 1, 'min': 60, 'h': 3600, 'd': 86400}[suffix]
    if total <= 0:
        raise ValueError('invalid supervisor duration')
    return total


def allow_collected_show(result, records):
    """Only a complete, explicit not-found result may bypass show exit 1."""
    if result.returncode == 0:
        return
    missing = {record.get('Id') for record in records
               if record.get('LoadState') == 'not-found'
               and record.get('ActiveState') == 'inactive'
               and record.get('MainPID') == '0'
               and record.get('ControlGroup') == ''
               and record.get('InvocationID') == ''}
    if result.returncode != 1 or not missing or None in missing:
        raise subprocess.CalledProcessError(result.returncode, result.args)
    for line in result.stderr.splitlines():
        if not line.strip():
            continue
        matched = re.fullmatch(r'Unit (.+) could not be found\.', line.strip())
        if matched is None or matched.group(1) not in missing:
            raise subprocess.CalledProcessError(result.returncode, result.args)


class Supervisor:
    def __init__(self, proc=Path('/proc'), cgroups=Path('/sys/fs/cgroup')):
        self.proc, self.cgroups = proc, cgroups
        self._snapshot = None

    def boot_id(self):
        return (self.proc / 'sys/kernel/random/boot_id').read_text().strip()

    def ticks(self, pid):
        # comm may contain spaces or parentheses; fields after its final close start at field 3.
        return int((self.proc / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()[19])

    def cgroup(self, pid):
        records = (self.proc / str(pid) / 'cgroup').read_text().splitlines()
        paths = [line.split(':', 2)[2] for line in records if line.startswith('0::')]
        if len(paths) != 1 or '..' in Path(paths[0]).parts:
            raise ValueError('unified cgroup required')
        return paths[0]

    def prepare(self, jobs):
        self._snapshot = None
        units = sorted({job['unit'] for job in jobs})
        if not units:
            return
        result = subprocess.run(['systemctl', 'show', *units, '--no-pager',
                                 '--property=Id,MainPID,InvocationID,ControlGroup,LoadState,ActiveState'],
                                text=True, capture_output=True, timeout=10, check=False, env=dict(os.environ, LC_ALL='C'))
        snapshot = {}
        for block in result.stdout.strip().split('\n\n'):
            details = dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
            if details.get('Id') in snapshot or details.get('Id') not in units:
                raise ValueError('ambiguous service snapshot')
            snapshot[details['Id']] = details
        if set(snapshot) != set(units):
            raise ValueError('incomplete service snapshot')
        allow_collected_show(result, list(snapshot.values()))
        self._snapshot = snapshot

    def show(self, unit):
        snapshot = getattr(self, '_snapshot', None)
        if snapshot is not None:
            return snapshot[unit]
        result = subprocess.run(['systemctl', 'show', unit, '--no-pager',
                                 '--property=Id,MainPID,InvocationID,ControlGroup,LoadState,ActiveState,Type,CPUQuotaPerSecUSec,RuntimeMaxUSec,TimeoutStartUSec,KillMode,SendSIGKILL,TimeoutStopUSec'],
                                text=True, capture_output=True, timeout=10, check=False, env=dict(os.environ, LC_ALL='C'))
        details = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        if details.get('Id') != unit:
            raise ValueError('ambiguous single service snapshot')
        allow_collected_show(result, [details])
        return details

    def current(self, slots, required_runtime):
        pid = os.getpid()
        group = self.cgroup(pid)
        unit = group.rsplit('/', 1)[-1]
        if not UNIT.fullmatch(unit):
            raise ValueError('queue run requires a dedicated supported systemd service')
        details = self.show(unit)
        invocation = details.get('InvocationID', '')
        if details.get('MainPID') != str(pid) or details.get('ControlGroup') != group or not re.fullmatch('[0-9a-f]{32}', invocation):
            raise ValueError('wrapper must be the exact service MainPID')
        if details.get('KillMode') != 'control-group' or details.get('SendSIGKILL') != 'yes':
            raise ValueError('supervisor must kill the whole service cgroup')
        if duration(details.get('TimeoutStopUSec', '')) > 60:
            raise ValueError('supervisor stop grace must be finite and at most 60 seconds')
        if duration(details.get('CPUQuotaPerSecUSec', '')) > slots:
            raise ValueError('service CPU quota exceeds requested slots')
        runtime_property = 'TimeoutStartUSec' if details.get('Type') == 'oneshot' else 'RuntimeMaxUSec'
        runtime = duration(details.get(runtime_property, ''))
        if not required_runtime <= runtime <= required_runtime + 240:
            raise ValueError('service runtime must cover wait and execution with bounded grace')
        return {'pid': pid, 'start_ticks': self.ticks(pid), 'boot_id': self.boot_id(),
                'unit': unit, 'invocation_id': invocation, 'cgroup': group}

    def members(self, group):
        directory = self.cgroups / group.lstrip('/')
        if not directory.exists():
            return []
        members = set()
        for entry in directory.rglob('cgroup.procs'):
            members.update(int(value) for value in entry.read_text().split())
        return sorted(members)

    def ownership(self, job):
        validate_job(job)
        if job['boot_id'] != self.boot_id():
            return 'gone'
        details = self.show(job['unit'])
        members = self.members(job['cgroup'])
        if details.get('InvocationID') == job['invocation_id'] and details.get('ControlGroup') == job['cgroup']:
            if members:
                return 'live'
            if details.get('ActiveState') in ('inactive', 'failed'):
                return 'gone'
            return 'unknown'
        # A reused unit can replace its cgroup path. A nonempty path is ambiguous.
        if not members and details.get('ActiveState') in ('inactive', 'failed'):
            return 'gone'
        return 'unknown'

    def terminate(self, job, signum):
        if signum not in ('SIGTERM', 'SIGKILL'):
            raise ValueError('unsupported cgroup termination signal')
        self._snapshot = None
        details = self.show(job['unit'])
        if (job['pid'] != os.getpid() or not self.wrapper_alive(job)
                or details.get('InvocationID') != job['invocation_id']
                or details.get('ControlGroup') != job['cgroup']
                or details.get('MainPID') != str(os.getpid())):
            raise ValueError('service identity changed before cgroup termination')
        try:
            subprocess.run(['sudo', '-n', '/usr/bin/systemctl', 'kill', '--kill-whom=all',
                            '--signal=' + signum, job['unit']], capture_output=True,
                           text=True, timeout=10, check=True)
        except subprocess.CalledProcessError as exc:
            # TERM also reaches this verified invocation's sudo/systemctl child.
            # Its death by that exact signal is expected after kill-all succeeds.
            if signum != 'SIGTERM' or exc.returncode != -signal.SIGTERM:
                raise

    def wrapper_alive(self, job):
        try:
            return self.ticks(job['pid']) == job['start_ticks'] and self.cgroup(job['pid']) == job['cgroup']
        except FileNotFoundError:
            return False


class Store:
    def __init__(self, root=Path('/var/lib/shared-pi-queue'), supervisor=None):
        self.root = Path(root)
        self.supervisor = supervisor or Supervisor()

    def _directory(self):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError('queue directory must be user-owned mode 0700 without symlinks')
        if self.root.resolve() != self.root.absolute():
            raise ValueError('queue directory parents must not be symlinks')

    def _read(self):
        path = self.root / 'state.json'
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return {'version': 1, 'next_sequence': 0, 'jobs': []}
        with os.fdopen(fd, 'rb') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_size > MAX_BYTES:
                raise ValueError('unsafe queue state file')
            value = json.load(handle)
        self.validate(value)
        return value

    @staticmethod
    def validate(value):
        if not isinstance(value, dict) or set(value) != {'version', 'next_sequence', 'jobs'} or value['version'] != 1:
            raise ValueError('invalid queue schema')
        if type(value['next_sequence']) is not int or not 0 <= value['next_sequence'] < 2**63:
            raise ValueError('invalid queue sequence')
        jobs = value['jobs']
        if not isinstance(jobs, list) or len(jobs) > 1024:
            raise ValueError('invalid queue jobs')
        for job in jobs:
            validate_job(job)
        if len({job['id'] for job in jobs}) != len(jobs) or len({job['sequence'] for job in jobs}) != len(jobs):
            raise ValueError('duplicate queue ownership')
        if any(job['sequence'] >= value['next_sequence'] for job in jobs):
            raise ValueError('invalid next sequence')

    def _write(self, value):
        self.validate(value)
        payload = json.dumps(value, separators=(',', ':')).encode()
        if len(payload) > MAX_BYTES:
            raise ValueError('queue state exceeds size limit')
        fd, name = tempfile.mkstemp(prefix='.state-', dir=self.root)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.root / 'state.json')
            directory = os.open(self.root, os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    @contextmanager
    def transaction(self):
        import fcntl  # Linux only; importing this module on Windows is harmless.
        self._directory()
        fd = os.open(self.root / 'queue.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise ValueError('unsafe queue lock')
            fcntl.flock(fd, fcntl.LOCK_EX)
            value = self._read()
            yield value
            self._write(value)
        finally:
            os.close(fd)

    def reconcile(self, value):
        """Return whether this transaction has trustworthy admission observations.

        Transient observations never alter a job's persisted waiting/running
        phase. Uncertain ownership denies only this transaction and is retried.
        Proven running descendants retain their slots even if the wrapper dies.
        """
        self.validate(value)
        retained, trustworthy = [], True
        try:
            self.supervisor.prepare(value['jobs'])
        except (OSError, ValueError, subprocess.SubprocessError):
            self.supervisor._snapshot = None
            return False
        for job in value['jobs']:
            try:
                ownership = self.supervisor.ownership(job)
                if ownership == 'gone':
                    bridged = 'host' in job['resources']
                    if bridged:
                        from pi_shared_queue_native import clear_native_manual
                    if not bridged or clear_native_manual(job):
                        continue
                    trustworthy = False
                if ownership == 'unknown':
                    trustworthy = False
                elif job['state'] == 'waiting' and not self.supervisor.wrapper_alive(job):
                    # A dead waiting wrapper with surviving members is ambiguous.
                    # Keep the phase and deny admission until termination is proven.
                    trustworthy = False
            except (OSError, ValueError, subprocess.SubprocessError):
                trustworthy = False
            retained.append(job)
        self.supervisor._snapshot = None
        value['jobs'] = retained
        return trustworthy
