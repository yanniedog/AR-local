#!/usr/bin/python3 -I
"""Fixed CI login protocol and root-owned deployment admission.

Installed copies must be root-owned. No repository code is imported at runtime.
Root imports only the independently approved installed coordinator closure.
Candidate code executes only in an unprivileged, read-only namespace.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CONTROL = "/usr/local/sbin/ar-local-ci-control"
ADAPTER = Path("/usr/local/lib/ar-local-ci/pi_ci_activate.py")
RUNTIME = Path('/etc/ar-local/ci-runtime.json')
LIBRARY = Path('/usr/local/lib/ar-local-ci')
PLANS = Path("/etc/ar-local/ci-plans")
STATE = Path("/var/lib/ar-local-ci")
HEX64 = re.compile(r"[0-9a-f]{64}")
HEX40 = re.compile(r"[0-9a-f]{40}")
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "HOME": "/nonexistent"}
UNITS = ("ar-local-dashboard.service", "ar-local-daily.service", "ar-local-daily.timer")
# Commissioning binds the immutable production source and retained queue closure.
RUNTIME_MODULES = ('pi_ci_release', 'pi_ci_resources', 'pi_ci_activate', 'pi_ci_snapshot')


def parse_command(command: str) -> dict:
    if command == "status":
        return {"action": "status"}
    match = re.fullmatch(r"activate ([0-9a-f]{64})", command)
    if match:
        return {"action": "activate", "plan": match[1]}
    match = re.fullmatch(r"check ([0-9a-f]{64})", command)
    if match:
        return {"action": "check", "plan": match[1]}
    raise ValueError("only status or activate <approved-plan-sha256> is permitted")


def request_from_json(body: str) -> dict:
    value = json.loads(body)
    if value == {"action": "status"}:
        return value
    if (isinstance(value, dict) and set(value) == {"action", "plan"}
            and value["action"] in {'activate', 'check'} and isinstance(value["plan"], str)
            and HEX64.fullmatch(value["plan"])):
        return value
    raise ValueError("invalid CI request")


def require_root_path(path: Path, *, directory: bool = False) -> None:
    """Reject writable/symlink ancestors, files and unexpected hard links."""
    if not path.is_absolute() or path != Path(os.path.normpath(path)):
        raise ValueError("trusted path must be canonical and absolute")
    for entry in (*reversed(path.parents), path):
        info = entry.lstat()
        if info.st_uid != 0 or info.st_mode & 0o022 or stat.S_ISLNK(info.st_mode):
            raise ValueError("trusted path is not exclusively root controlled")
        last = entry == path
        if not last or directory:
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError("trusted ancestor is not a directory")
        elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("trusted file must be a regular file with one link")


def trusted_bytes(path: Path, *, limit: int = 1024 * 1024) -> bytes:
    require_root_path(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_mode & 0o022 or info.st_nlink != 1 or info.st_size > limit):
            raise ValueError("invalid trusted file")
        body = stream.read(limit + 1)
    if len(body) > limit:
        raise ValueError("trusted file too large")
    return body


def require_digest(body: bytes, digest: str) -> None:
    if not isinstance(digest, str) or not HEX64.fullmatch(digest):
        raise ValueError("invalid SHA-256")
    if hashlib.sha256(body).hexdigest() != digest:
        raise ValueError("approved file digest differs")


def validate_recovery(body: bytes) -> dict:
    """An operator approval binding real retained evidence, never a Drive probe."""
    value = json.loads(body)
    if (not isinstance(value, dict) or type(value.get("schema_version")) is not int
            or value["schema_version"] != 1 or value.get("result") != "PASS"):
        raise ValueError("offsite recovery approval is unavailable")
    required = {"raw_archive", "system_image", "restore_proof", "boot_structure_proof"}
    evidence = value.get("evidence")
    if not isinstance(evidence, dict) or set(evidence) != required:
        raise ValueError("complete offsite recovery evidence is required")
    for reference in evidence.values():
        if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
            raise ValueError("invalid recovery evidence reference")
        body = trusted_bytes(Path(reference["path"]))
        require_digest(body, reference["sha256"])
    return value


def validate_plan(plan_id: str, *, now: datetime | None = None) -> dict:
    if not HEX64.fullmatch(plan_id):
        raise ValueError("invalid plan identity")
    body = trusted_bytes(PLANS / (plan_id + ".json"))
    require_digest(body, plan_id)
    plan = json.loads(body)
    required = {"schema_version", "scope", "target_commit", "previous_commit", "expires_at",
                "sealed_manifest_sha256", "recovery_approval_sha256", "adapter_sha256"}
    if (not isinstance(plan, dict) or set(plan) != required or type(plan["schema_version"]) is not int
            or plan["schema_version"] != 1
            or plan["scope"] != "activate-sealed-d027"
            or not isinstance(plan["target_commit"], str) or not HEX40.fullmatch(plan["target_commit"])
            or not isinstance(plan["previous_commit"], str) or not HEX40.fullmatch(plan["previous_commit"])):
        raise ValueError("invalid root-approved deployment plan")
    expiry = datetime.fromisoformat(plan["expires_at"])
    if expiry.utcoffset() is None:
        raise ValueError("plan expiry must include a timezone")
    remaining = (expiry - (now or datetime.now(timezone.utc))).total_seconds()
    if not 1800 <= remaining <= 21600:
        raise ValueError("plan requires 30 minutes to 6 hours of remaining validity")
    for key, suffix in (("sealed_manifest_sha256", ".activation.json"),
                        ("recovery_approval_sha256", ".recovery.json")):
        require_digest(trusted_bytes(PLANS / (plan_id + suffix)), plan[key])
    validate_recovery(trusted_bytes(PLANS / (plan_id + ".recovery.json")))
    require_digest(trusted_bytes(ADAPTER), plan["adapter_sha256"])
    return plan


def run(argv: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, env=ENV, cwd="/", timeout=timeout,
                          shell=False, close_fds=True)


def status() -> dict:
    if RUNTIME.exists() or RUNTIME.is_symlink():
        return load_runtime()['pi_ci_snapshot'].snapshot()
    result = {}
    for unit in UNITS:
        response = run(["/usr/bin/systemctl", "show", unit,
                        "--property=LoadState,ActiveState,SubState,Result,MainPID", "--no-pager"])
        if response.returncode:
            raise RuntimeError("service status unavailable")
        result[unit] = dict(line.split("=", 1) for line in response.stdout.splitlines() if "=" in line)
    return {"result": "OBSERVED", "units": result, "deployment_acceptance": "NOT_ASSESSED"}


def load_runtime():
    """Import only the complete root-owned, independently approved installed closure."""
    profile = json.loads(trusted_bytes(RUNTIME))
    expected = {name + '.py' for name in (*RUNTIME_MODULES, 'pi_ci_worker')}
    if (profile.get('schema') != 'ar-local-ci-runtime-v1' or set(profile.get('modules', {})) != expected
            or profile.get('queue_contract') != 'ci-retained-v1' or not profile.get('queue_files')):
        raise ValueError('complete commissioned immutable activation profile is unavailable')
    bodies = {}
    for name, digest in profile['modules'].items():
        bodies[name] = trusted_bytes(LIBRARY / name)
        require_digest(bodies[name], digest)
    queue = Path('/usr/local/lib/shared-pi-queue')
    required_queue = {'pi_shared_queue.py', 'pi_shared_queue_policy.py', 'pi_shared_queue_store.py',
                      'pi_shared_queue_native.py', 'pi_shared_queue_post_hooks.py', 'pi_shared_queue_stop_hook.py'}
    if not required_queue <= set(profile['queue_files']):
        raise ValueError('complete retained queue source closure is required')
    for name, digest in profile['queue_files'].items():
        if not re.fullmatch(r'pi_shared_queue(?:_[a-z_]+)?\.py', name):
            raise ValueError('unsupported installed queue source name')
        require_digest(trusted_bytes(queue / name), digest)
    result = {}
    for name in RUNTIME_MODULES:
        spec = importlib.util.spec_from_file_location(name, LIBRARY / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        # Execute exactly the verified bytes, never reopen an import via cwd/PATH.
        exec(compile(bodies[name + '.py'], str(LIBRARY / (name + '.py')), 'exec'), module.__dict__)
        result[name] = module
    return result


def check_plan(plan_id):
    module = load_runtime()['pi_ci_activate']
    context = module.plan_context(plan_id)
    module.require_code_only_profile(context)
    return dict(result='APPROVED_PLAN', plan=plan_id, target_commit=context['plan']['target_commit'],
                canary_manifest_sha256=context['plan']['canary_manifest_sha256'],
                canary_release_tag=context['plan']['canary_release_tag'], mutated=False)


def activation_argv(plan_id: str) -> list[str]:
    # No executable, path, environment, service name or systemd property comes
    # from SSH input or from the plan. The root-approved adapter receives one ID.
    if not HEX64.fullmatch(plan_id):
        raise ValueError("invalid plan identity")
    return ["/usr/bin/systemd-run", "--wait", "--pipe", "--collect",
            "--unit=ar-local-ci-activate-" + plan_id,
            "--property=User=pi", "--property=Group=pi", "--property=NoNewPrivileges=no",
            '--property=Type=notify', '--property=NotifyAccess=main', '--property=CPUQuota=200%',
            '--property=TimeoutStartSec=960', '--property=TimeoutStopSec=900', '--property=SendSIGKILL=yes',
            "--property=ProtectSystem=strict", "--property=ProtectHome=yes",
            "--property=PrivateTmp=yes", "--property=ProtectControlGroups=yes",
            "--property=RestrictNamespaces=no",
            "--property=KillMode=control-group", "--property=RuntimeMaxSec=1800", '--property=LimitAS=2G',
            '--property=MemoryHigh=768M', '--property=MemoryMax=1G', '--property=MemorySwapMax=0',
            "--property=ReadWritePaths=/srv/ar-local /var/lib/ar-local-ci /var/lib/shared-pi-queue",
            '--property=ExecStopPost=+/usr/bin/python3 -I /usr/local/sbin/ar-local-ci-control --finalize ' + plan_id,
            "--property=WorkingDirectory=/", "--setenv=HOME=/nonexistent",
            "--setenv=PATH=/usr/sbin:/usr/bin:/sbin:/bin", "--",
            '/usr/bin/python3', '/usr/local/lib/shared-pi-queue/pi_shared_queue.py', 'run',
            '--project', 'ar-local', '--resource', 'ar-local', '--resource', 'host', '--mode', 'exclusive',
            '--cpu-slots', '2', '--wait-timeout', '900', '--max-runtime', '1800', '--',
            '/usr/bin/sudo', '-n', '--', '/usr/bin/python3', '-I', CONTROL, '--worker', plan_id]


def activate(plan_id: str) -> dict:
    module = load_runtime()['pi_ci_activate']
    context = module.plan_context(plan_id)
    module.require_code_only_profile(context)
    plan = context['plan']
    require_root_path(STATE, directory=True)
    claim = STATE / (plan_id + ".claimed.json")
    descriptor = os.open(claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump({"plan": plan_id, "target_commit": plan["target_commit"],
                   "claimed_at": datetime.now(timezone.utc).isoformat()}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    argv = activation_argv(plan_id)
    start = argv[argv.index('--') + 1:]
    authority = {'schema': 'ar-local-ci-authority-v1', 'plan': plan_id,
        'unit': 'ar-local-ci-activate-' + plan_id + '.service', 'expires_at': plan['expires_at'],
        'target_commit': plan['target_commit'], 'scope': 'activate-immutable-d027',
        'runtime_profile_sha256': plan['runtime_profile_sha256'], 'adapter_sha256': plan['adapter_sha256'],
        'control_sha256': hashlib.sha256(trusted_bytes(Path(CONTROL))).hexdigest(),
        'queue_argv_sha256': hashlib.sha256(json.dumps(start, separators=(',', ':')).encode()).hexdigest()}
    path = STATE / 'authority' / (plan_id + '.json')
    require_root_path(path.parent, directory=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
    with os.fdopen(fd, 'w') as stream:
        json.dump(authority, stream, sort_keys=True); stream.flush(); os.fchmod(stream.fileno(), 0o444); os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    directory = os.open(STATE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    # A timeout/error consumes this plan. Never replay an ambiguous transaction.
    response = run(argv, timeout=3700)
    if response.returncode:
        raise RuntimeError("activation worker failed; plan consumed; operator must inspect retained receipts")
    # Worker exit 0 is not adequate proof of deployed code/data/public acceptance.
    return {"result": "WORKER_COMPLETED", "plan": plan_id, "acceptance": "REQUIRES_OPERATOR_VERIFICATION"}


def login_main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "-c":
        raise ValueError("interactive shells, file transfer and forwarding are unavailable")
    request = parse_command(argv[1])
    response = subprocess.run(["/usr/bin/sudo", "-n", "--", CONTROL],
                              input=json.dumps(request), env=ENV, cwd="/", text=True,
                              timeout=3800, shell=False, close_fds=True)
    return response.returncode


def control_main() -> int:
    if (os.geteuid() == 0 and len(sys.argv) == 4 and sys.argv[1] == '--stage'
            and HEX64.fullmatch(sys.argv[2])):
        modules = load_runtime()
        context = modules['pi_ci_activate'].plan_context(sys.argv[2])
        parent = context['stage'].parent
        require_root_path(parent.parent, directory=True)
        parent.mkdir(mode=0o700)
        import time
        deadline = time.monotonic() + 1200
        def guard():
            if time.monotonic() >= deadline:
                raise RuntimeError('bounded root staging deadline reached')
        modules['pi_ci_release'].stage_input(Path(sys.argv[3]), context['stage'], context['release'], guard)
        print(json.dumps({'result': 'STAGED', 'plan': sys.argv[2]}), flush=True)
        return 0
    if os.geteuid() == 0 and len(sys.argv) == 3 and sys.argv[1] in {'--worker', '--finalize'} and HEX64.fullmatch(sys.argv[2]):
        module = load_runtime()['pi_ci_activate']
        result = module.main([sys.argv[2]]) if sys.argv[1] == '--worker' else module.finalize(sys.argv[2])
        return result
    if os.geteuid() != 0 or len(sys.argv) != 1 or os.environ.get("SUDO_USER") != "ar-local-ci":
        raise ValueError("control requires the dedicated CI sudo entry without arguments")
    body = sys.stdin.buffer.read(4097)
    if len(body) > 4096:
        raise ValueError("request too large")
    request = request_from_json(body.decode("utf-8"))
    result = (status() if request['action'] == 'status' else check_plan(request['plan'])
              if request['action'] == 'check' else activate(request['plan']))
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0


def main() -> int:
    try:
        return control_main() if Path(sys.argv[0]).name == "ar-local-ci-control" else login_main(sys.argv[1:])
    except (ValueError, RuntimeError, OSError, TypeError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps({"result": "BLOCKED", "reason": str(error)}), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
