"""Commission one private native SSH listener without altering port 22.

Independently verify/copy this exact helper and approval into root-controlled
read-only staging BEFORE running Python -I. Validation is the default; mutations
require an exclusive host+AR-local queue claim inside the maintenance window.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, time, timedelta, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import uuid
from zoneinfo import ZoneInfo

ROOT = Path('/etc/ar-local-native-ssh')
# Persistent SSH must remain outside the legacy queue's ar-local-*.service batch scan.
UNIT = Path('/etc/systemd/system/sshd-ar-local-tailnet.service')
HOST_KEY = Path('/etc/ssh/ssh_host_ed25519_key')
SERVICE = UNIT.name
QUEUE = Path('/var/lib/shared-pi-queue/state.json')
LEASE = Path('/srv/ar-local/data/state/daily-ingest.lock')
TZ = ZoneInfo('Australia/Hobart')
SCHEMA = 'ar-local-native-ssh-v1'
RESOURCE_POLICY = 'native-ssh-cpu-pids-address-space-v1'
ADDRESS_BYTES = 512 * 1024**2
QUEUE_NAME = re.compile(r'[a-z0-9][a-z0-9_.-]{0,63}\Z')
QUEUE_UNIT = re.compile(r'(?:ar-local-(?:daily|daily-watchdog|ingest-now)|ar-local-plain-backup-[0-9a-f]{32}|ar-local-ci-activate-[0-9a-f]{64}|ar-local-payload-[a-zA-Z0-9_.-]+|ar-local-queue-task-[a-zA-Z0-9_.-]+|shared-pi-task-[a-zA-Z0-9_.-]+)\.service\Z')


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON field')
        result[key] = value
    return result


def protected(path, *, readonly=True, owner=0, limit=2**20):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path or str(path) != os.path.normpath(path):
        raise ValueError('canonical non-symlink path required')
    for ancestor in path.parents:
        info = ancestor.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, owner) or info.st_mode & 0o022:
            raise ValueError('unsafe ancestor')
    before = path.lstat()
    mask = 0o222 if readonly else 0o022
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != owner
            or before.st_mode & mask or before.st_size > limit):
        raise ValueError('unsafe protected file')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        after = os.fstat(stream.fileno())
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_mode, s.st_uid, s.st_nlink)
        if identity(before) != identity(after):
            raise ValueError('file identity changed')
        body = stream.read(limit + 1)
        if len(body) > limit or identity(after) != identity(os.fstat(stream.fileno())):
            raise ValueError('file changed during read')
        return body


def checked(path, digest):
    body = protected(path)
    if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest) or hashlib.sha256(body).hexdigest() != digest:
        raise ValueError('independent approval hash mismatch')
    return body


def public_key(value):
    if not isinstance(value, str) or not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/]+={0,2}', value):
        raise ValueError('one option-free Ed25519 public key required')
    wire = base64.b64decode(value.split()[1], validate=True)
    if len(wire) != 51 or wire[:19] != b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20':
        raise ValueError('invalid Ed25519 public key encoding')
    return value


def validate_approval(value):
    fields = {'schema', 'source_commit', 'installer_sha256', 'address', 'port', 'user', 'authorized_key', 'host_public_key', 'resource_policy'}
    if not isinstance(value, dict) or set(value) != fields or value['schema'] != SCHEMA:
        raise ValueError('invalid approval schema')
    if not re.fullmatch('[0-9a-f]{40}', str(value['source_commit'])) or not re.fullmatch('[0-9a-f]{64}', str(value['installer_sha256'])):
        raise ValueError('exact reviewed source identity required')
    if value['resource_policy'] != RESOURCE_POLICY:
        raise ValueError('reviewed listener resource policy required')
    address = ipaddress.IPv4Address(value['address'])
    if str(address) != value['address'] or address not in ipaddress.IPv4Network('100.64.0.0/10'):
        raise ValueError('exact tailnet IPv4 required')
    if type(value['port']) is not int or not 1024 <= value['port'] <= 65535:
        raise ValueError('dedicated unprivileged port required')
    if not isinstance(value['user'], str) or not re.fullmatch('[a-z_][a-z0-9_-]{0,31}', value['user']) or value['user'] == 'root':
        raise ValueError('one non-root owner required')
    public_key(value['authorized_key']); public_key(value['host_public_key'])
    return value


def render(value):
    validate_approval(value)
    config = f'''# Standalone: deliberately no Include or Match inheritance.
Port {value['port']}
AddressFamily inet
ListenAddress {value['address']}
HostKey {HOST_KEY.as_posix()}
PidFile /run/ar-local-native-ssh/sshd.pid
AuthorizedKeysFile {ROOT.as_posix()}/authorized_keys
AuthorizedKeysCommand none
TrustedUserCAKeys none
AllowUsers {value['user']}
StrictModes yes
AuthenticationMethods publickey
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
PermitRootLogin no
HostbasedAuthentication no
GSSAPIAuthentication no
UsePAM yes
PermitUserEnvironment no
PermitUserRC no
DisableForwarding yes
AllowAgentForwarding no
AllowTcpForwarding no
X11Forwarding no
PermitTunnel no
GatewayPorts no
PermitTTY yes
LoginGraceTime 20
MaxAuthTries 3
MaxSessions 4
MaxStartups 2:50:4
ClientAliveInterval 30
ClientAliveCountMax 3
LogLevel VERBOSE
Subsystem sftp internal-sftp
'''
    unit = f'''[Unit]
Description=Private native SSH for AR-local operator
Wants=network-online.target tailscaled.service
After=network-online.target tailscaled.service
StartLimitIntervalSec=0

[Service]
Type=simple
RuntimeDirectory=ar-local-native-ssh
RuntimeDirectoryMode=0755
ExecStartPre=/usr/sbin/sshd -t -f {ROOT.as_posix()}/sshd_config
ExecStart=/usr/sbin/sshd -D -e -f {ROOT.as_posix()}/sshd_config
Restart=on-failure
RestartSec=30s
TimeoutStartSec=30s
TimeoutStopSec=20s
KillMode=control-group
CPUQuota=100%
LimitAS=536870912:536870912
MemoryMax=512M
MemorySwapMax=0
TasksMax=128
UMask=0077

[Install]
WantedBy=multi-user.target
'''
    return {'sshd_config': config.encode(), 'authorized_keys': (value['authorized_key'] + '\n').encode(), 'unit': unit.encode()}


def run(args, *, check=True):
    if (args[:1] == ['/usr/bin/systemctl'] and len(args) > 1
            and args[1] in ('daemon-reload', 'start', 'enable', 'disable')):
        window(datetime.now(timezone.utc))
    return subprocess.run(args, check=check, capture_output=True, text=True, timeout=30,
                          env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'})


def window(now):
    if now.tzinfo is None:
        raise ValueError('timezone-aware time required')
    local = now.astimezone(TZ)
    if time(0, 30) <= local.time().replace(tzinfo=None) < time(3, 30):
        raise ValueError('natural-ingest quiet window')
    close = datetime.combine(local.date(), time(0, 30), TZ)
    if local >= close:
        close += timedelta(days=1)
    if (close - local).total_seconds() < 120:
        raise ValueError('insufficient maintenance time')


def queue_claim(state, cgroup, boot, properties, lease):
    jobs = state.get('jobs') if isinstance(state, dict) else None
    if not isinstance(jobs, list) or any(not isinstance(j, dict) for j in jobs):
        raise ValueError('complete queue records required')
    matches = [j for j in jobs if j.get('cgroup') == cgroup]
    if len(matches) != 1:
        raise ValueError('unique current host queue claim required')
    job = matches[0]
    if any(other is not job and other.get('state') != 'waiting' for other in jobs):
        raise ValueError('another active or ambiguous queue claim exists')
    for record in jobs:
        queue_record(record)
    expected_lease = {'pid': str(job.get('pid')), 'boot_id': boot,
                      'role': 'shared-pi-host-task:' + str(job.get('id')), 'recovery': 'manual'}
    if (not re.fullmatch(r'/system.slice/ar-local-queue-task-[0-9a-f]{32}\.service', cgroup)
            or job.get('state') != 'running' or job.get('project') != 'ar-local'
            or job.get('mode') != 'exclusive' or not isinstance(job.get('resources'), list)
            or any(not isinstance(r, str) for r in job['resources'])
            or not {'host', 'ar-local'} <= set(job['resources']) or job.get('boot_id') != boot
            or job.get('unit') != cgroup.rsplit('/', 1)[-1]
            or properties.get('ControlGroup') != cgroup or properties.get('ActiveState') != 'active'
            or properties.get('InvocationID') != job.get('invocation_id')
            or properties.get('MainPID') != str(job.get('pid'))
            or lease != expected_lease):
        raise ValueError('exclusive current host/native ownership differs')
    return job


def queue_record(job):
    """Self-contained copy of the installed queue's complete record contract.

    Waiting records already own their supervisor identity, before admission.
    Never import owner-writable queue modules into this privileged helper.
    """
    required = {'id', 'project', 'resources', 'mode', 'cpu_slots', 'max_duration_seconds',
                'state', 'sequence', 'queued_monotonic', 'pid', 'start_ticks', 'boot_id',
                'unit', 'invocation_id', 'cgroup'}
    if not required <= set(job) or set(job) - required - {'command_started'}:
        raise ValueError('incomplete queue record')
    if job['state'] not in ('waiting', 'running', 'quarantined') or ('command_started' in job and type(job['command_started']) is not bool):
        raise ValueError('invalid queue state')
    if any(not isinstance(job[k], str) or not QUEUE_NAME.fullmatch(job[k]) for k in ('id', 'project')):
        raise ValueError('invalid queue name')
    if any(not isinstance(job[k], str) or not 1 <= len(job[k]) <= 256 for k in ('boot_id', 'unit', 'invocation_id', 'cgroup')):
        raise ValueError('invalid queue ownership')
    if (str(uuid.UUID(job['boot_id'])) != job['boot_id'] or not QUEUE_UNIT.fullmatch(job['unit'])
            or not job['cgroup'].startswith('/') or not job['cgroup'].endswith('/' + job['unit'])
            or '..' in Path(job['cgroup']).parts or not re.fullmatch('[0-9a-f]{32}', job['invocation_id'])):
        raise ValueError('invalid queue identity')
    limits = {'pid': (1, 2**31 - 1), 'start_ticks': (1, 2**63 - 1), 'sequence': (0, 2**63 - 1),
              'cpu_slots': (1, 3 if job['project'] == 'ar-local' else 1),
              'max_duration_seconds': (1, 21600 if job['project'] == 'ar-local' else 1800)}
    if any(type(job[k]) is not int or not low <= job[k] <= high for k, (low, high) in limits.items()):
        raise ValueError('invalid queue bounds')
    resources = job['resources']
    if (job['mode'] not in ('shared', 'exclusive') or not isinstance(resources, list)
            or not 1 <= len(resources) <= 32
            or any(not isinstance(r, str) or not QUEUE_NAME.fullmatch(r) for r in resources)
            or len(set(resources)) != len(resources)
            or (job['project'] == 'ar-local' and 'ar-local' not in resources)
            or type(job['queued_monotonic']) not in (int, float) or not 0 <= job['queued_monotonic'] < 1e15):
        raise ValueError('invalid queue resources or age')


def admit(uid):
    window(datetime.now(timezone.utc))
    lines = Path('/proc/self/cgroup').read_text().splitlines()
    groups = [line[3:] for line in lines if line.startswith('0::')]
    if len(groups) != 1:
        raise ValueError('unified owned cgroup required')
    group = groups[0]
    if not re.fullmatch(r'/system.slice/ar-local-queue-task-[0-9a-f]{32}\.service', group):
        raise ValueError('owned queue service required')
    result = run(['/usr/bin/systemctl', 'show', group.rsplit('/', 1)[-1],
                  '--property=ControlGroup,ActiveState,InvocationID,MainPID'])
    props = dict(line.split('=', 1) for line in result.stdout.splitlines())
    state = json.loads(protected(QUEUE, readonly=False, owner=uid), object_pairs_hook=unique)
    lease = dict(line.split('=', 1) for line in protected(LEASE, readonly=False, owner=uid).decode().splitlines())
    return queue_claim(state, group, Path('/proc/sys/kernel/random/boot_id').read_text().strip(), props, lease)


def host_validate(value):
    import pwd  # Linux-only; importing this module remains portable for tests.
    owner = pwd.getpwnam(value['user'])
    if owner.pw_uid < 1000 or owner.pw_shell in ('/usr/sbin/nologin', '/bin/false'):
        raise ValueError('existing interactive non-system owner required')
    keys = protected(Path(owner.pw_dir) / '.ssh/authorized_keys', readonly=False, owner=owner.pw_uid).decode().splitlines()
    if not any(line.split()[:2] == value['authorized_key'].split() for line in keys):
        raise ValueError('approved key must already be an option-free owner key')
    protected(HOST_KEY, readonly=False, limit=16384)
    actual = run(['/usr/bin/ssh-keygen', '-y', '-f', str(HOST_KEY)]).stdout
    if derived_host_key(actual) != value['host_public_key']:
        raise ValueError('native host public key differs from independently retained key')
    addresses = json.loads(run(['/usr/sbin/ip', '-j', '-4', 'addr', 'show', 'dev', 'tailscale0']).stdout)
    if value['address'] not in {a.get('local') for item in addresses for a in item.get('addr_info', [])}:
        raise ValueError('approved address is not on tailscale0')
    return owner.pw_uid


def derived_host_key(output):
    # ssh-keygen -y can retain the private key's comment. Only this trusted
    # command output permits comments; approval/authorized-key grammar stays strict.
    lines = output.splitlines()
    if len(lines) != 1 or len(lines[0].split()) < 2:
        raise ValueError('one derived native host public key required')
    return public_key(' '.join(lines[0].split()[:2]))


def effective_validate(value, path):
    run(['/usr/sbin/sshd', '-t', '-f', str(path)])
    context = f"user={value['user']},host=localhost,addr={value['address']},laddr={value['address']},lport={value['port']}"
    output = run(['/usr/sbin/sshd', '-T', '-f', str(path), '-C', context]).stdout
    facts = {}
    for line in output.splitlines():
        key, _, text = line.partition(' ')
        facts.setdefault(key, []).append(text)
    expected = {'port': str(value['port']), 'addressfamily': 'inet',
                'listenaddress': f"{value['address']}:{value['port']}", 'hostkey': HOST_KEY.as_posix(),
                'authorizedkeysfile': (ROOT / 'authorized_keys').as_posix(), 'allowusers': value['user'],
                'authenticationmethods': 'publickey', 'pubkeyauthentication': 'yes',
                'passwordauthentication': 'no', 'kbdinteractiveauthentication': 'no',
                'permitrootlogin': 'no', 'disableforwarding': 'yes', 'strictmodes': 'yes',
                'permituserenvironment': 'no', 'permituserrc': 'no', 'trustedusercakeys': 'none',
                'authorizedkeyscommand': 'none', 'subsystem': 'sftp internal-sftp'}
    if any(facts.get(k) != [v] for k, v in expected.items()):
        raise ValueError('effective native authentication/binding differs')
    return facts


def protected_directory(path):
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError('canonical destination parent required')
    for item in (path, *path.parents):
        info = item.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('destination parents must remain root controlled')


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def create(path, body, mode=0o444):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(body); stream.flush(); os.fchmod(stream.fileno(), mode); os.fsync(stream.fileno())
    sync_directory(path.parent)


def installed(bodies, approval, *, retired=False):
    paths = {ROOT / name: body for name, body in bodies.items() if name != 'unit'}
    paths[ROOT / 'retired-unit.service' if retired else UNIT] = bodies['unit']
    paths[ROOT / 'approval.json'] = approval
    for path, body in paths.items():
        if protected(path) != body:
            raise ValueError('commissioned path changed; preserve and inspect')
    return paths


def no_existing_links():
    """Inspect manager search paths, including dangling enablement/alias links."""
    roots = run(['/usr/bin/systemd-analyze', 'unit-paths']).stdout.splitlines()
    if not 1 <= len(roots) <= 64 or any(not Path(p).is_absolute() for p in roots):
        raise ValueError('bounded systemd unit search paths required')
    remaining = 32768
    for name in roots:
        root = Path(name)
        if not root.exists():
            continue
        root = root.resolve()
        protected_directory(root)
        pending = [root]
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                for item in entries:
                    remaining -= 1
                    if remaining < 0:
                        raise ValueError('systemd link inventory exceeds bound')
                    path = Path(item.path)
                    if item.name == SERVICE or (item.is_symlink() and path.resolve() == UNIT):
                        raise ValueError('existing service enablement or alias must be inspected')
                    if directory == root and item.name.endswith(('.wants', '.requires', '.upholds')):
                        protected_directory(path)
                        pending.append(path)


def disabled():
    result = run(['/usr/bin/systemctl', 'is-enabled', SERVICE], check=False)
    if result.returncode != 1 or result.stdout.strip() != 'disabled':
        raise ValueError('listener must remain disabled pending wire proof')


def mutate(action, value, bodies, approval, uid, proof=None, evidence=None):
    admit(uid)
    if action == 'install':
        if ROOT.exists() or ROOT.is_symlink() or UNIT.exists() or UNIT.is_symlink():
            raise ValueError('create-only commissioning: existing paths are never replaced')
        protected_directory(ROOT.parent); protected_directory(UNIT.parent)
        state = run(['/usr/bin/systemctl', 'show', SERVICE, '--property=LoadState']).stdout.strip()
        if state != 'LoadState=not-found':
            raise ValueError('existing service must not be replaced')
        no_existing_links()
        admit(uid)
        # Retain any failed preparation for inspection. No service definition
        # exists until syntax/effective authentication checks succeed.
        ROOT.mkdir(mode=0o755)
        os.chmod(ROOT, 0o755)
        sync_directory(ROOT.parent)
        create(ROOT / 'approval.json', approval)
        for name in ('authorized_keys', 'sshd_config'):
            admit(uid)
            create(ROOT / name, bodies[name])
        effective_validate(value, ROOT / 'sshd_config')
        admit(uid)
        create(UNIT, bodies['unit'])
        disabled()
        return 'INSTALLED_DISABLED'
    if action == 'rollback':
        return rollback(bodies, approval, uid)
    paths = installed(bodies, approval)
    effective_validate(value, ROOT / 'sshd_config')
    admit(uid)
    if action == 'start':
        run(['/usr/bin/systemctl', 'daemon-reload'])
        service_definition()
        disabled()
        run(['/usr/bin/systemctl', 'start', SERVICE])
        run(['/usr/bin/systemctl', 'is-active', SERVICE])
        return 'STARTED_NOT_ENABLED'
    if action == 'enable':
        validate_proof(proof, hashlib.sha256(approval).hexdigest(), datetime.now(timezone.utc))
        service_definition()
        run(['/usr/bin/systemctl', 'is-active', SERVICE])
        limits = live_limits()
        if evidence is not None:
            evidence['resource_evidence'] = limits
        run(['/usr/bin/systemctl', 'enable', SERVICE])
        return 'ENABLED_AFTER_WIRE_PROOF'
    raise ValueError('unsupported mutation')


def stopped_listener():
    stopped = dict(line.split('=', 1) for line in run(['/usr/bin/systemctl', 'show', SERVICE,
                   '--property=ActiveState,MainPID,ControlGroup']).stdout.splitlines())
    if (stopped.get('ActiveState') not in ('inactive', 'failed')
            or stopped.get('MainPID') != '0' or stopped.get('ControlGroup') != ''):
        raise ValueError('listener did not stop; preserve all definitions')


def rollback(bodies, approval, uid):
    retired = ROOT / 'retired-unit.service'
    unit_present = UNIT.exists() or UNIT.is_symlink()
    installed(bodies, approval, retired=not unit_present)
    if retired.exists() or retired.is_symlink():
        if protected(retired) != bodies['unit']:
            raise ValueError('previous rollback evidence differs')
    admit(uid)
    if unit_present:
        # Load a just-installed definition; refuse pending or loaded overrides
        # before invoking any stop hook. No network/key readiness is required.
        run(['/usr/bin/systemctl', 'daemon-reload'])
        service_definition()
        run(['/usr/bin/systemctl', 'disable', '--now', SERVICE])
        stopped_listener()
        installed(bodies, approval)
        admit(uid)
        if not retired.exists():
            create(retired, bodies['unit'])
        admit(uid)
        UNIT.unlink()
        sync_directory(UNIT.parent)
    else:
        # A previous attempt may have durably retired the file, then expired
        # before reload. Resume only with the exact retained artifacts and no PID.
        stopped_listener()
        service_definition(allow_retired=True)
        admit(uid)
        sync_directory(UNIT.parent)
    run(['/usr/bin/systemctl', 'daemon-reload'])
    stopped_listener()
    service_definition(allow_retired=True)
    return 'ROLLED_BACK_EVIDENCE_RETAINED'


def service_definition(*, allow_retired=False):
    result = run(['/usr/bin/systemctl', 'show', SERVICE, '--property=FragmentPath,DropInPaths'])
    facts = dict(line.split('=', 1) for line in result.stdout.splitlines())
    expected = [str(UNIT), ''] if allow_retired else [str(UNIT)]
    if set(facts) != {'FragmentPath', 'DropInPaths'} or facts['FragmentPath'] not in expected or facts['DropInPaths']:
        raise ValueError('unexpected service override; do not mutate listener')


def daemon_identity(pid):
    path = Path('/proc') / str(pid)
    record = (path / 'stat').read_text()
    rest = record.rsplit(')', 1)[1].split()
    if record.split(' ', 1)[0] != str(pid) or rest[0] == 'Z' or os.readlink(path / 'exe') != '/usr/sbin/sshd':
        raise ValueError('current native sshd process identity required')
    return int(rest[19])


def live_limits():
    fields = 'MemoryMax,MemorySwapMax,CPUQuotaPerSecUSec,TasksMax,ControlGroup,MainPID,InvocationID,ActiveState,LimitAS,LimitASSoft'
    result = run(['/usr/bin/systemctl', 'show', SERVICE, '--property=' + fields])
    facts = dict(line.split('=', 1) for line in result.stdout.splitlines())
    expected = {'CPUQuotaPerSecUSec': '1s', 'TasksMax': '128',
                'ControlGroup': '/system.slice/' + SERVICE, 'ActiveState': 'active',
                'LimitAS': str(ADDRESS_BYTES), 'LimitASSoft': str(ADDRESS_BYTES)}
    if (set(facts) != set(fields.split(',')) or any(facts.get(k) != v for k, v in expected.items())
            or not facts['MainPID'].isdigit() or int(facts['MainPID']) < 1
            or not re.fullmatch('[0-9a-f]{32}', facts['InvocationID'])):
        raise ValueError('effective listener resource limits differ')
    pid = int(facts['MainPID']); identity = daemon_identity(pid)
    limits = (Path('/proc') / str(pid) / 'limits').read_text()
    pattern = rf'^Max address space\s+{ADDRESS_BYTES}\s+{ADDRESS_BYTES}\s+bytes\s*$'
    if not re.search(pattern, limits, re.MULTILINE):
        raise ValueError('actual native daemon hard/soft address-space limit differs')
    root = Path('/sys/fs/cgroup') / facts['ControlGroup'].lstrip('/')
    values = {name: (root / name).read_text().strip() for name in ('pids.max', 'cpu.max')}
    quota = values['cpu.max'].split()
    if (values['pids.max'] != '128' or len(quota) != 2
            or not all(v.isdigit() for v in quota) or not 0 < int(quota[0]) == int(quota[1])):
        raise ValueError('kernel listener CPU/task enforcement differs')
    controllers = Path('/sys/fs/cgroup/cgroup.controllers').read_text().split()
    if not {'cpu', 'pids'} <= set(controllers):
        raise ValueError('complete root kernel controller capability required')
    memory = {'state': 'UNAVAILABLE', 'reason': 'kernel memory controller absent'}
    if 'memory' in controllers:
        values.update({name: (root / name).read_text().strip() for name in ('memory.max', 'memory.swap.max')})
        if (facts['MemoryMax'] != str(ADDRESS_BYTES) or facts['MemorySwapMax'] != '0'
                or values['memory.max'] != str(ADDRESS_BYTES) or values['memory.swap.max'] != '0'):
            raise ValueError('advertised memory controller lacks expected live limits')
        memory = {'state': 'ENFORCED', 'memory_max_bytes': ADDRESS_BYTES, 'swap_max_bytes': 0}
    elif any((root / name).exists() for name in ('memory.max', 'memory.swap.max')):
        raise ValueError('contradictory kernel memory capability evidence')
    after = run(['/usr/bin/systemctl', 'show', SERVICE,
                 '--property=MainPID,InvocationID,ControlGroup,ActiveState']).stdout
    if (dict(line.split('=', 1) for line in after.splitlines()) !=
            {k: facts[k] for k in ('MainPID', 'InvocationID', 'ControlGroup', 'ActiveState')}
            or daemon_identity(pid) != identity):
        raise ValueError('native daemon changed during resource verification')
    return {'profile': RESOURCE_POLICY, 'systemd': facts, 'kernel_cgroup': values,
            'address_space_bytes_per_process': ADDRESS_BYTES, 'daemon_start_ticks': identity,
            'listener_cgroup_memory_and_swap': memory,
            'scope': 'CPU/pids and optional memory/swap apply to listener cgroup only; PAM sessions may leave it. '
                     'Address-space limit is per process; fresh authenticated-session inheritance is separately proven. '
                     'No aggregate authenticated-session memory/CPU/pids or zero-swap guarantee.'}


def validate_proof(proof, digest, now):
    required = {'schema', 'approval_sha256', 'verified_at', 'native_banner', 'publickey_authenticated',
                'host_pin_matched', 'sftp_roundtrip_verified', 'address_space_limit_inherited', 'wrong_key_rejected', 'password_rejected', 'root_rejected', 'exclusive_tailnet_binding'}
    if (not isinstance(proof, dict) or set(proof) != required or proof['schema'] != 'ar-local-native-ssh-wire-v1'
            or proof['approval_sha256'] != digest or not isinstance(proof['native_banner'], str)
            or not proof['native_banner'].startswith('SSH-2.0-OpenSSH_')
            or any(proof[key] is not True for key in required - {'schema', 'approval_sha256', 'verified_at', 'native_banner'})):
        raise ValueError('complete independently retained positive/negative wire proof required')
    stamp = datetime.fromisoformat(proof['verified_at'])
    if stamp.tzinfo is None or not 0 <= (now - stamp).total_seconds() <= 900:
        raise ValueError('fresh wire proof required')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approval', type=Path, required=True)
    parser.add_argument('--approval-sha256', required=True)
    parser.add_argument('--action', choices=('validate', 'install', 'start', 'enable', 'rollback'), default='validate')
    parser.add_argument('--proof', type=Path)
    parser.add_argument('--proof-sha256')
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        raise ValueError('independently reviewed root commissioning required')
    approval = checked(args.approval, args.approval_sha256)
    value = validate_approval(json.loads(approval, object_pairs_hook=unique))
    checked(Path(__file__), value['installer_sha256'])
    bodies = render(value)
    if args.action == 'rollback':
        import pwd
        uid = pwd.getpwnam(value['user']).pw_uid
    else:
        uid = host_validate(value)
    proof = json.loads(checked(args.proof, args.proof_sha256), object_pairs_hook=unique) if args.proof else None
    result = 'VALIDATED_DEFINITION_ONLY'
    evidence = {}
    if args.action != 'validate':
        result = mutate(args.action, value, bodies, approval, uid, proof, evidence)
    print(json.dumps({'result': result, 'source_commit': value['source_commit'],
                      'approval_sha256': args.approval_sha256, **evidence,
                      'artifacts': {k: hashlib.sha256(v).hexdigest() for k, v in bodies.items()}}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
