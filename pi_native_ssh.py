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
from zoneinfo import ZoneInfo

ROOT = Path('/etc/ar-local-native-ssh')
UNIT = Path('/etc/systemd/system/ar-local-native-ssh.service')
HOST_KEY = Path('/etc/ssh/ssh_host_ed25519_key')
SERVICE = UNIT.name
QUEUE = Path('/var/lib/shared-pi-queue/state.json')
LEASE = Path('/srv/ar-local/data/state/daily-ingest.lock')
TZ = ZoneInfo('Australia/Hobart')
SCHEMA = 'ar-local-native-ssh-v1'


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
    fields = {'schema', 'source_commit', 'installer_sha256', 'address', 'port', 'user', 'authorized_key', 'host_public_key'}
    if not isinstance(value, dict) or set(value) != fields or value['schema'] != SCHEMA:
        raise ValueError('invalid approval schema')
    if not re.fullmatch('[0-9a-f]{40}', str(value['source_commit'])) or not re.fullmatch('[0-9a-f]{64}', str(value['installer_sha256'])):
        raise ValueError('exact reviewed source identity required')
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
    actual = run(['/usr/bin/ssh-keygen', '-y', '-f', str(HOST_KEY)]).stdout.strip()
    if public_key(actual) != value['host_public_key']:
        raise ValueError('native host public key differs from independently retained key')
    addresses = json.loads(run(['/usr/sbin/ip', '-j', '-4', 'addr', 'show', 'dev', 'tailscale0']).stdout)
    if value['address'] not in {a.get('local') for item in addresses for a in item.get('addr_info', [])}:
        raise ValueError('approved address is not on tailscale0')
    return owner.pw_uid


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


def create(path, body, mode=0o444):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(body); stream.flush(); os.fchmod(stream.fileno(), mode); os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def installed(bodies, approval):
    paths = {ROOT / name: body for name, body in bodies.items() if name != 'unit'}
    paths[UNIT] = bodies['unit']; paths[ROOT / 'approval.json'] = approval
    for path, body in paths.items():
        if protected(path) != body:
            raise ValueError('commissioned path changed; preserve and inspect')
    return paths


def mutate(action, value, bodies, approval, uid, proof=None):
    admit(uid)
    if action == 'install':
        if ROOT.exists() or ROOT.is_symlink() or UNIT.exists() or UNIT.is_symlink():
            raise ValueError('create-only commissioning: existing paths are never replaced')
        protected_directory(ROOT.parent); protected_directory(UNIT.parent)
        state = run(['/usr/bin/systemctl', 'show', SERVICE, '--property=LoadState']).stdout.strip()
        if state != 'LoadState=not-found':
            raise ValueError('existing service must not be replaced')
        # Retain any failed preparation for inspection. No service definition
        # exists until syntax/effective authentication checks succeed.
        ROOT.mkdir(mode=0o755)
        os.chmod(ROOT, 0o755)
        create(ROOT / 'approval.json', approval)
        for name in ('authorized_keys', 'sshd_config'):
            create(ROOT / name, bodies[name])
        effective_validate(value, ROOT / 'sshd_config')
        admit(uid)
        create(UNIT, bodies['unit'])
        return 'INSTALLED_DISABLED'
    paths = installed(bodies, approval)
    if action != 'rollback':
        effective_validate(value, ROOT / 'sshd_config')
    admit(uid)
    if action == 'start':
        run(['/usr/bin/systemctl', 'daemon-reload'])
        service_definition()
        run(['/usr/bin/systemctl', 'start', SERVICE])
        run(['/usr/bin/systemctl', 'is-active', SERVICE])
        return 'STARTED_NOT_ENABLED'
    if action == 'enable':
        validate_proof(proof, hashlib.sha256(approval).hexdigest(), datetime.now(timezone.utc))
        service_definition()
        run(['/usr/bin/systemctl', 'is-active', SERVICE])
        live_limits()
        run(['/usr/bin/systemctl', 'enable', SERVICE])
        return 'ENABLED_AFTER_WIRE_PROOF'
    if action == 'rollback':
        run(['/usr/bin/systemctl', 'disable', '--now', SERVICE])
        stopped = dict(line.split('=', 1) for line in run(['/usr/bin/systemctl', 'show', SERVICE,
                       '--property=ActiveState,MainPID,ControlGroup']).stdout.splitlines())
        if (stopped.get('ActiveState') not in ('inactive', 'failed')
                or stopped.get('MainPID') != '0' or stopped.get('ControlGroup') != ''):
            raise ValueError('listener did not stop; preserve all definitions')
        # Preserve every approval/config/key byte. Only our exact unit moves to
        # an evidence name; nothing about the incumbent port22 service changes.
        retired = ROOT / 'retired-unit.service'
        if retired.exists() or retired.is_symlink():
            raise ValueError('previous rollback evidence exists')
        installed(bodies, approval)
        admit(uid)
        create(retired, paths[UNIT]); UNIT.unlink()
        run(['/usr/bin/systemctl', 'daemon-reload'])
        return 'ROLLED_BACK_EVIDENCE_RETAINED'
    raise ValueError('unsupported mutation')


def service_definition():
    result = run(['/usr/bin/systemctl', 'show', SERVICE, '--property=FragmentPath,DropInPaths'])
    facts = dict(line.split('=', 1) for line in result.stdout.splitlines())
    if facts != {'FragmentPath': str(UNIT), 'DropInPaths': ''}:
        raise ValueError('unexpected service override; do not start or enable')


def live_limits():
    result = run(['/usr/bin/systemctl', 'show', SERVICE,
                  '--property=MemoryMax,MemorySwapMax,CPUQuotaPerSecUSec,TasksMax,ControlGroup'])
    facts = dict(line.split('=', 1) for line in result.stdout.splitlines())
    expected = {'MemoryMax': '536870912', 'MemorySwapMax': '0', 'CPUQuotaPerSecUSec': '1s',
                'TasksMax': '128', 'ControlGroup': '/system.slice/' + SERVICE}
    if facts != expected:
        raise ValueError('effective listener resource limits differ')
    root = Path('/sys/fs/cgroup') / facts['ControlGroup'].lstrip('/')
    values = {name: (root / name).read_text().strip() for name in
              ('memory.max', 'memory.swap.max', 'pids.max', 'cpu.max')}
    quota = values['cpu.max'].split()
    if (values['memory.max'] != '536870912' or values['memory.swap.max'] != '0'
            or values['pids.max'] != '128' or len(quota) != 2
            or not all(v.isdigit() for v in quota) or not 0 < int(quota[0]) == int(quota[1])):
        raise ValueError('kernel listener resource enforcement unavailable or different')
    return facts


def validate_proof(proof, digest, now):
    required = {'schema', 'approval_sha256', 'verified_at', 'native_banner', 'publickey_authenticated',
                'host_pin_matched', 'sftp_roundtrip_verified', 'wrong_key_rejected', 'password_rejected', 'root_rejected', 'exclusive_tailnet_binding'}
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
    if args.action != 'validate':
        result = mutate(args.action, value, bodies, approval, uid, proof)
    print(json.dumps({'result': result, 'source_commit': value['source_commit'],
                      'approval_sha256': args.approval_sha256,
                      'artifacts': {k: hashlib.sha256(v).hexdigest() for k, v in bodies.items()}}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
