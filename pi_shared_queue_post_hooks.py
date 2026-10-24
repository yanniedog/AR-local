"""Fixed approved maintenance stop-hook contracts; separate from ingest hooks.

Only root-owned, bounded authority/terminal records are trusted. A recognizable
name alone never approves launch or releases a retained native/queue claim.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess

PLAIN = re.compile(r"ar-local-plain-backup-([0-9a-f]{32})\.service\Z")
ROOT = Path("/usr/local/lib/ar-local-plain-backup")
HANDOFF = Path("/var/lib/ar-local-plain-backup-handoff")
BROKER = str(ROOT / "broker.py")
IMAGE_ROOT = Path("/usr/local/lib/ar-local-system-recovery")
IMAGE_HANDOFF = Path("/var/lib/ar-local-system-recovery-handoff")
CI = re.compile(r"ar-local-ci-activate-([0-9a-f]{64})\.service\Z")
CI_ROOT = Path("/usr/local/lib/ar-local-ci")
CI_STATE = Path("/var/lib/ar-local-ci")
CI_CONTROL = Path("/usr/local/sbin/ar-local-ci-control")
CI_RUNTIME = Path("/etc/ar-local/ci-runtime.json")
QUEUE_ROOT = Path("/usr/local/lib/shared-pi-queue")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
IMAGE_PHASES = frozenset({"PROBE", "baseline", "prepare", "finalize", "archive", "build", "compress", "upload", "fetch", "restore", "rejoin"})


def retained_stop(unit):
    return isinstance(unit, str) and (PLAIN.fullmatch(unit) is not None or CI.fullmatch(unit) is not None)


def pairs(rows):
    value = {}
    for key, item in rows:
        if key in value:
            raise ValueError("duplicate structured field")
        value[key] = item
    return value


def root_bytes(path, maximum=1048576):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError("noncanonical root authority")
    for item in (path, *path.parents):
        info = item.lstat()
        if info.st_uid != 0 or stat.S_ISLNK(info.st_mode) or info.st_mode & 0o022:
            raise ValueError("untrusted root authority")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > maximum:
        raise ValueError("invalid bounded root authority")
    data = path.read_bytes()
    after = path.stat()
    if len(data) > maximum or (info.st_ino, info.st_dev, info.st_size, info.st_mtime_ns) != (
            after.st_ino, after.st_dev, after.st_size, after.st_mtime_ns):
        raise ValueError("root authority changed during read")
    return data


def root_json(path, maximum=65536):
    value = json.loads(root_bytes(path, maximum), object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise ValueError("root authority object required")
    return value


def _plain_approval(unit, *, current=False, now=None):
    match = PLAIN.fullmatch(unit or "")
    if not match:
        raise ValueError("not a retained plaintext backup service")
    value = root_json(HANDOFF / match[1] / "approval.json")
    expiry = datetime.fromisoformat(value["expires_at"])
    if (value.get("schema") != "ar-local-plain-backup-authority-v1"
            or value.get("nonce") != match[1] or value.get("unit") != unit
            or value.get("manual_plaintext_drive_write") is not True
            or value.get("data_root") != "/srv/ar-local/data"
            or expiry.utcoffset() != timezone.utc.utcoffset(expiry)
            or any(not re.fullmatch("[0-9a-f]{64}", str(value.get(key, ""))) for key in
                   ("source_closure_sha256", "parent_sha256", "resources_sha256", "broker_sha256", "queue_argv_sha256"))):
        raise ValueError("plaintext backup approval differs")
    if current and expiry <= (now or datetime.now(timezone.utc)):
        raise ValueError("plaintext backup authority expired")
    return value


def _native(unit, prop, run):
    encoded = "".join(char if char.isalnum() else f"_{ord(char):02x}" for char in unit)
    result = run(["/usr/bin/busctl", "--system", "--json=short", "--timeout=10", "get-property",
        "org.freedesktop.systemd1", "/org/freedesktop/systemd1/unit/" + encoded,
        "org.freedesktop.systemd1.Service", prop], text=True, capture_output=True, timeout=10, check=True)
    value = json.loads(result.stdout, object_pairs_hook=pairs)
    if value.get("type") != "a(sasasttttuii)" or not isinstance(value.get("data"), list):
        raise ValueError("native execution evidence unavailable")
    return value["data"]


def _present(path):
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False


def _hashes(value, keys):
    return all(isinstance(value.get(key), str) and HEX64.fullmatch(value[key]) for key in keys)


def _expiry(value, current, now):
    expiry = datetime.fromisoformat(value["expires_at"])
    if expiry.utcoffset() != timezone.utc.utcoffset(expiry):
        raise ValueError("UTC maintenance expiry required")
    if current and expiry <= (now or datetime.now(timezone.utc)):
        raise ValueError("maintenance authority expired")


def _image_approval(unit, nonce, *, current=False, now=None):
    value = root_json(IMAGE_HANDOFF / nonce / "approval.json")
    if (value.get("schema") != "ar-local-system-recovery-authority-v1"
            or value.get("nonce") != nonce or value.get("unit") != unit
            or value.get("manual_system_recovery") is not True
            or value.get("phase") not in IMAGE_PHASES or value.get("mode") not in ("PROBE", "RUN_ARCHIVE")
            or (value["phase"] == "PROBE") != (value["mode"] == "PROBE")
            or value["phase"] == "upload" and value.get("manual_image_drive_write") is not True
            or value["phase"] == "fetch" and value.get("manual_image_drive_read") is not True
            or value["phase"] == "fetch" and value.get("manual_image_drive_write") is not None
            or not _hashes(value, ("source_closure_sha256", "parent_sha256", "resources_sha256",
                                  "broker_sha256", "queue_argv_sha256"))):
        raise ValueError("image recovery approval differs")
    _expiry(value, current, now)
    for name,key in (('parent.py','parent_sha256'),('broker.py','broker_sha256'),
                     ('pi_system_guard_resources.py','resources_sha256')):
        if _sha(root_bytes(IMAGE_ROOT/name))!=value[key]:
            raise ValueError('fixed image control source differs')
    return value


def ci_start(plan):
    return ['/usr/bin/python3', str(QUEUE_ROOT / 'pi_shared_queue.py'), 'run',
        '--project', 'ar-local', '--resource', 'ar-local', '--resource', 'host', '--mode', 'exclusive',
        '--cpu-slots', '2', '--wait-timeout', '900', '--max-runtime', '1800', '--',
        '/usr/bin/sudo', '-n', '--', '/usr/bin/python3', '-I', str(CI_CONTROL), '--worker', plan]


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _argv_sha(argv):
    return _sha(json.dumps(argv, separators=(",", ":")).encode())


def _ci_closure(value):
    if (_sha(root_bytes(CI_CONTROL)) != value['control_sha256']
            or _sha(root_bytes(CI_ROOT / 'pi_ci_activate.py')) != value['adapter_sha256']
            or _sha(root_bytes(CI_RUNTIME)) != value['runtime_profile_sha256']):
        raise ValueError('commissioned CI root source differs')
    profile = root_json(CI_RUNTIME)
    expected = {'pi_ci_release.py', 'pi_ci_resources.py', 'pi_ci_activate.py', 'pi_ci_snapshot.py', 'pi_ci_worker.py'}
    required = {'pi_shared_queue.py', 'pi_shared_queue_policy.py', 'pi_shared_queue_store.py',
                'pi_shared_queue_native.py', 'pi_shared_queue_post_hooks.py', 'pi_shared_queue_stop_hook.py'}
    modules, queue = profile.get('modules', {}), profile.get('queue_files', {})
    if (profile.get('schema') != 'ar-local-ci-runtime-v1' or profile.get('queue_contract') != 'ci-retained-v1'
            or not isinstance(modules, dict) or set(modules) != expected or not isinstance(queue, dict)
            or not required <= set(queue) or len(queue) > 32):
        raise ValueError('complete commissioned CI closure required')
    if modules['pi_ci_activate.py'] != value['adapter_sha256']:
        raise ValueError('CI adapter differs from runtime closure')
    for root, files in ((CI_ROOT, modules), (QUEUE_ROOT, queue)):
        for name, digest in files.items():
            if (not re.fullmatch(r'pi_(?:ci|shared_queue)(?:_[a-z_]+)?\.py', name)
                    or not isinstance(digest, str) or not HEX64.fullmatch(digest)
                    or _sha(root_bytes(root / name)) != digest):
                raise ValueError('commissioned CI dependency differs')


def _ci_approval(unit, plan, *, current=False, now=None):
    value = root_json(CI_STATE / 'authority' / (plan + '.json'))
    if (value.get('schema') != 'ar-local-ci-authority-v1' or value.get('plan') != plan
            or value.get('unit') != unit or value.get('scope') != 'activate-immutable-d027'
            or not re.fullmatch('[0-9a-f]{40}', str(value.get('target_commit', '')))
            or not _hashes(value, ('runtime_profile_sha256', 'adapter_sha256', 'control_sha256', 'queue_argv_sha256'))
            or value['queue_argv_sha256'] != _argv_sha(ci_start(plan))):
        raise ValueError('CI activation authority differs')
    _expiry(value, current, now)
    _ci_closure(value)
    return value


def approval(unit, *, current=False, now=None):
    """Select only one fixed root authority; no path or executable comes from JSON."""
    ci = CI.fullmatch(unit or '')
    if ci:
        return _ci_approval(unit, ci[1], current=current, now=now)
    match = PLAIN.fullmatch(unit or '')
    if not match:
        raise ValueError('unsupported retained maintenance service')
    plain = HANDOFF / match[1] / 'approval.json'
    image = IMAGE_HANDOFF / match[1] / 'approval.json'
    if _present(image):
        if _present(plain):
            raise ValueError('conflicting maintenance authorities')
        return _image_approval(unit, match[1], current=current, now=now)
    return _plain_approval(unit, current=current, now=now)


def _commands(unit, value, expected, run, *, expected_start=None):
    start, stop = _native(unit, "ExecStartEx", run), _native(unit, "ExecStopPostEx", run)
    if (len(start) != 1 or len(start[0]) != 10 or start[0][2] != []
            or not isinstance(start[0][1],list) or not start[0][1]
            or not all(isinstance(item,str) for item in start[0][1]) or start[0][0]!=start[0][1][0]
            or _argv_sha(start[0][1]) != value["queue_argv_sha256"]
            or expected_start is not None and start[0][1] != expected_start
            or len(stop) != 1 or len(stop[0]) != 10 or stop[0][:3] != [expected[0], expected, ["privileged"]]):
        raise ValueError("root-created fixed maintenance commands differ")
    for prop in ("ExecConditionEx", "ExecStartPreEx", "ExecStartPostEx", "ExecStopEx"):
        if _native(unit, prop, run):
            raise ValueError("unexpected maintenance service hook")


def _typed_property(unit, name, kind, expected, run):
    encoded = ''.join(char if char.isalnum() else f'_{ord(char):02x}' for char in unit)
    response = run(['/usr/bin/busctl', '--system', '--json=short', '--timeout=10', 'get-property',
        'org.freedesktop.systemd1', '/org/freedesktop/systemd1/unit/' + encoded,
        'org.freedesktop.systemd1.Service', name], text=True, capture_output=True, timeout=10, check=True)
    value = json.loads(response.stdout, object_pairs_hook=pairs)
    actual=value.get('data')
    if kind=='as' and isinstance(actual,list) and all(isinstance(item,str) for item in actual):
        matches=len(actual)==len(expected) and set(actual)==set(expected)
    else:matches=type(actual) is type(expected) and actual==expected
    if value.get('type') != kind or not matches:
        raise ValueError('fixed CI service profile differs: ' + name)


def _ci_service(unit, value, run):
    _commands(unit, value, ['/usr/bin/python3', '-I', str(CI_CONTROL), '--finalize', value['plan']],
              run, expected_start=ci_start(value['plan']))
    strings = {'User': 'pi', 'Group': 'pi', 'Type': 'notify', 'NotifyAccess': 'main',
        'KillMode': 'control-group', 'ProtectSystem': 'strict', 'ProtectHome': 'yes', 'WorkingDirectory': '/'}
    booleans = {'NoNewPrivileges': False, 'SendSIGKILL': True,
        'PrivateTmp': True, 'ProtectControlGroups': True}
    integers = {'RuntimeMaxUSec': 1800_000_000, 'TimeoutStartUSec': 960_000_000,
        'TimeoutStopUSec': 900_000_000, 'CPUQuotaPerSecUSec': 2_000_000,
        'LimitAS': 2 * 1024**3, 'MemoryHigh': 768 * 1024**2,
        'MemoryMax': 1024**3, 'MemorySwapMax': 0}
    for name, expected in strings.items():
        _typed_property(unit, name, 's', expected, run)
    for name, expected in booleans.items():
        _typed_property(unit, name, 'b', expected, run)
    for name, expected in integers.items():
        _typed_property(unit, name, 't', expected, run)
    _typed_property(unit, 'ReadWritePaths', 'as',
        ['/srv/ar-local', '/var/lib/ar-local-ci', '/var/lib/shared-pi-queue'], run)
    _typed_property(unit, 'Environment', 'as',
        ['HOME=/nonexistent', 'PATH=/usr/sbin:/usr/bin:/sbin:/bin'], run)
    _typed_property(unit, 'EnvironmentFiles', 'a(sb)', [], run)


def verify_plain_service(unit, run=subprocess.run):
    """Compatibility entrypoint, now with distinct fixed image and CI profiles."""
    value = approval(unit, current=True)
    if CI.fullmatch(unit):
        _ci_service(unit, value, run)
    elif value['schema'] == 'ar-local-system-recovery-authority-v1':
        _commands(unit, value, ['/usr/bin/python3', '-I', '-S', '-B',
            str(IMAGE_ROOT / 'broker.py'), 'recover', value['nonce']], run)
    else:
        _commands(unit, value, ['/usr/bin/python3', '-I', '-B', BROKER, 'recover', value['nonce']], run)
    return value


def stop_grace(unit, default):
    if CI.fullmatch(unit or ''):
        verify_plain_service(unit)
        return 900
    return default


def _binding(value, job):
    return (value.get('unit') == job['unit'] and value.get('job_id') == job['id']
        and value.get('invocation') == job['invocation_id'] and value.get('boot_id') == job['boot_id']
        and value.get('owner_pid') == job['pid'] and value.get('owner_ticks') == job['start_ticks'])


def _ci_completion(job, authority, *, native_identity=None):
    value = root_json(CI_STATE / 'completed' / (authority['plan'] + '.json'))
    binding = value.get('binding', {})
    if not isinstance(binding, dict):
        return False
    identity = (binding.get('native_device'), binding.get('native_inode'))
    return (value.get('schema') == 'ar-local-ci-terminal-v1' and value.get('plan') == authority['plan']
        and _binding(binding, job) and binding.get('cgroup') == job['cgroup']
        and all(type(item) is int and item > 0 for item in identity)
        and (native_identity is None or identity == native_identity)
        and value.get('result') in ('PASS', 'ROLLED_BACK', 'FAILED_BEFORE_SWITCH', 'ABORTED_RESTORED')
        and (value.get('result') != 'PASS' or HEX64.fullmatch(str(value.get('accepted_release_sha256', ''))))
        and value.get('restored_timers') is True and value.get('previous_checkout') == 'RETAINED_COMPLETE'
        and value.get('untrusted_processes_gone') is True and value.get('code_restore_proved') is True)


def completion_proved(job, *, native_identity=None):
    """Caller must additionally prove the whole invocation/cgroup has ended."""
    if not retained_stop(job.get("unit")):
        return False
    try:
        authority = approval(job['unit'])
        if CI.fullmatch(job['unit']):
            return bool(_ci_completion(job, authority, native_identity=native_identity))
        image = authority['schema'] == 'ar-local-system-recovery-authority-v1'
        root = IMAGE_HANDOFF if image else HANDOFF
        value = root_json(root / authority['nonce'] / 'completion.json')
        if not (_binding(value, job) and value.get('nonce') == authority['nonce']
                and value.get('readback') == 60 and value.get('result') in ('RESTORED', 'NOT_ACQUIRED')
                and value.get('untrusted_processes_gone') is True):
            return False
        if image:
            return (value.get('schema') == 'ar-local-system-recovery-root-completion-v1'
                and value.get('phase') == authority['phase']
                and value.get('source_closure_sha256') == authority['source_closure_sha256']
                and value.get('credential_custody') == ('QUARANTINED' if authority['phase'] in ('upload','fetch') else 'NOT_EXPOSED')
                and type(value.get('stop_post_verified')) is bool
                and value.get('owned_loop_terminal') is True and value.get('writers_restored') is True)
        return (value.get('schema') == 'ar-local-plain-backup-root-completion-v1'
            and value.get('credential_quarantined') is True)
    except (OSError, KeyError, TypeError, ValueError):
        return False


def native_completion_proved(job, identity):
    # Plain behavior is unchanged; CI's root finalizer also binds the successor
    # inode. This check runs under the existing recovery lock before unlink.
    return not CI.fullmatch(job.get('unit', '')) or completion_proved(job, native_identity=identity)
