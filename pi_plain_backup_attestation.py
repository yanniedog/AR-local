"""Root-sealed host admission for a worker confined to a private PID namespace.

The worker cannot inspect outside PIDs by design. The qualified root monitor
owns continuous queue/native/resource checks and kills the sandbox on failure.
This capability validates the sealed handoff and the worker's actual kernel
confinement; it is not a substitute for the monitor's terminal resource proof.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time


def protected_file(path):
    if path != path.resolve(strict=True):
        raise ValueError('protected path must be canonical')
    for directory in reversed(path.parents):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('unprotected runtime ancestry')
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o022:
        raise ValueError('runtime binary must be root protected')


def _sha(value):
    return isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value)


def _positive(value):
    return type(value) is int and value > 0


def _utc(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.utcoffset() is None:
        raise ValueError('attestation timestamps require timezone')
    return result.astimezone(timezone.utc)


def sealed_context(fd):
    import fcntl
    if type(fd) is not int or fd < 3:
        raise ValueError('explicit root attestation descriptor required')
    info = os.fstat(fd)
    required = fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 0
            or not 0 < info.st_size <= 16384 or stat.S_IMODE(info.st_mode) not in (0o400, 0o440)
            or fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY
            or fcntl.fcntl(fd, fcntl.F_GET_SEALS) & required != required):
        raise ValueError('root-owned read-only fully sealed memfd required')
    raw = os.pread(fd, 16385, 0)
    if len(raw) != info.st_size:
        raise ValueError('attestation descriptor length changed')
    return json.loads(raw), hashlib.sha256(raw).hexdigest(), (info.st_dev, info.st_ino)


def parse_native(raw):
    if not 0 < len(raw) <= 4096:
        raise ValueError('native ownership record size differs')
    rows = [line.split('=', 1) for line in raw.decode('ascii').splitlines()]
    if len(rows) != 4 or any(len(row) != 2 for row in rows) or len(dict(rows)) != 4:
        raise ValueError('ambiguous native ownership record')
    return dict(rows)


def read_native(path, identity):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600 or not 0 < info.st_size <= 4096
                or (info.st_dev, info.st_ino) != identity):
            raise ValueError('native lease changed while opening read-only source')
        raw = os.read(fd, 4097)
        if len(raw) != info.st_size:
            raise ValueError('native lease bytes changed while reading')
        return parse_native(raw)
    finally:
        os.close(fd)


def validate_context(value):
    fields = {'schema', 'nonce', 'unit', 'boot_id', 'queue', 'source', 'data_root', 'operation',
        'source_closure_sha256', 'remote', 'drive_root_folder_id', 'issued_at', 'expires_at',
        'issued_monotonic', 'deadline_monotonic', 'monitor', 'sandbox', 'worker'}
    if not isinstance(value, dict) or set(value) != fields or value['schema'] != 'ar-local-plain-backup-attestation-v1':
        raise ValueError('unsupported root attestation schema')
    if (not re.fullmatch('[a-f0-9]{32}', value['nonce'])
            or value['unit'] != 'ar-local-plain-backup-' + value['nonce'] + '.service'
            or not _sha(value['source_closure_sha256'])):
        raise ValueError('invalid exact attestation operation identity')
    queue, source, monitor = value['queue'], value['source'], value['monitor']
    if set(value['worker']) != {'uid', 'gid'} or not all(_positive(v) for v in value['worker'].values()):
        raise ValueError('explicit nonroot host worker UID/GID required')
    if set(queue) != {'job_id', 'owner_pid', 'owner_ticks', 'invocation', 'cgroup', 'device', 'inode'}:
        raise ValueError('incomplete host queue binding')
    if (not re.fullmatch('[a-f0-9]{32}', queue['job_id']) or not re.fullmatch('[a-f0-9]{32}', queue['invocation'])
            or queue['cgroup'] != '/system.slice/' + value['unit']
            or any(not _positive(queue[k]) for k in ('owner_pid', 'owner_ticks', 'device', 'inode'))):
        raise ValueError('invalid queue/native owner identity')
    if set(source) != {'device', 'inode'} or not all(_positive(v) for v in source.values()):
        raise ValueError('invalid source identity')
    if (set(monitor) != {'pid', 'start_ticks', 'user_namespace_inode', 'pid_namespace_inode', 'mount_namespace_inode'}
            or not all(_positive(v) for v in monitor.values())):
        raise ValueError('invalid root monitor identity')
    expected = {'private_mount', 'private_pid', 'host_uid_mapping', 'readonly_source',
        'no_new_privileges', 'capabilities_dropped'}
    if set(value['sandbox']) != expected or any(v is not True for v in value['sandbox'].values()):
        raise ValueError('incomplete sandbox attestation')
    issued, expires = _utc(value['issued_at']), _utc(value['expires_at'])
    mono_issued, mono_deadline = value['issued_monotonic'], value['deadline_monotonic']
    if (any(type(v) not in (int, float) or not math.isfinite(v) for v in (mono_issued, mono_deadline))
            or not 0 < (expires - issued).total_seconds() <= 21600
            or not 0 <= mono_issued < mono_deadline <= mono_issued + 21600
            or mono_deadline - mono_issued > (expires - issued).total_seconds() + 2):
        raise ValueError('attestation lifetime exceeds bounded operation')
    for key in ('data_root', 'operation'):
        path = Path(value[key])
        if not path.is_absolute() or path != path.resolve() or '..' in path.parts:
            raise ValueError('attested paths must be canonical')
    return value


class AttestedHostLease:
    def __init__(self, fd, context, sha, identity):
        self.fd, self.context, self.sha, self.identity = fd, validate_context(context), sha, identity

    def verify(self, data):
        if os.name != 'posix' or os.getuid() == 0:
            raise ValueError('sandbox worker must use host Pi user identity')
        context, sha, identity = sealed_context(self.fd)
        if sha != self.sha or identity != self.identity or context != self.context:
            raise ValueError('root attestation capability changed')
        ctx, current = self.context, datetime.now(timezone.utc)
        if (os.getuid() != ctx['worker']['uid'] or os.geteuid() != ctx['worker']['uid']
                or os.getgid() != ctx['worker']['gid'] or os.getegid() != ctx['worker']['gid']):
            raise ValueError('worker identity differs from root-approved Pi account')
        if not (_utc(ctx['issued_at']) <= current < _utc(ctx['expires_at'])
                and ctx['issued_monotonic'] <= time.monotonic() < ctx['deadline_monotonic']):
            raise ValueError('root attestation expired or clocks changed')
        if Path('/proc/sys/kernel/random/boot_id').read_text().strip() != ctx['boot_id']:
            raise ValueError('attested host boot changed')
        status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
        if (status.get('NoNewPrivs', '').strip() != '1' or
                any(int(status[k].strip(), 16) != 0 for k in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'))):
            raise ValueError('sandbox must retain NNP and empty capabilities')
        monitor = ctx['monitor']
        namespaces = {name: Path('/proc/self/ns/' + name).stat().st_ino for name in ('user', 'pid', 'mnt')}
        if (namespaces['user'] != monitor['user_namespace_inode']
                or namespaces['pid'] == monitor['pid_namespace_inode']
                or namespaces['mnt'] == monitor['mount_namespace_inode']):
            raise ValueError('sandbox lacks private PID/mount or changed host UID mapping')
        if Path('/proc/self/cgroup').read_text().strip() != '0::' + ctx['queue']['cgroup']:
            raise ValueError('sandbox escaped its admitted queue cgroup')
        if str(data) != ctx['data_root'] or not os.statvfs(data).f_flag & os.ST_RDONLY:
            raise ValueError('attested source must retain read-only mount')
        info = data.stat()
        native_path = data / 'state/daily-ingest.lock'
        native = native_path.lstat()
        if ((info.st_dev, info.st_ino) != (ctx['source']['device'], ctx['source']['inode'])
                or not stat.S_ISREG(native.st_mode) or native.st_uid != os.getuid() or native.st_nlink != 1
                or stat.S_IMODE(native.st_mode) != 0o600 or not 0 < native.st_size <= 4096
                or (native.st_dev, native.st_ino) != (ctx['queue']['device'], ctx['queue']['inode'])):
            raise ValueError('attested source/native inode changed')
        if read_native(native_path, (native.st_dev, native.st_ino)) != {
                'pid': str(ctx['queue']['owner_pid']), 'boot_id': ctx['boot_id'],
                'role': 'shared-pi-host-task:' + ctx['queue']['job_id'], 'recovery': 'manual'}:
            raise ValueError('attested native manual ownership bytes changed')

    @contextmanager
    def hold(self, data):
        self.verify(data)
        try:
            yield
        except BaseException as primary:
            try:
                self.verify(data)
            except Exception as secondary:
                if hasattr(primary, 'add_note'):
                    primary.add_note('lease exit verification also failed: ' + type(secondary).__name__)
            raise
        else:
            self.verify(data)


def inherited_from_attestation_fd(fd, *, deadline, remote, drive_root_folder_id, data_root, operation):
    context, sha, identity = sealed_context(fd)
    validate_context(context)
    if (context['remote'] != remote or context['drive_root_folder_id'] != drive_root_folder_id
            or context['data_root'] != str(data_root) or context['operation'] != str(operation)
            or _utc(context['expires_at']) != _utc(deadline)):
        raise ValueError('worker arguments differ from root-approved context')
    lease = AttestedHostLease(fd, context, sha, identity)
    lease.verify(data_root)
    return lease
