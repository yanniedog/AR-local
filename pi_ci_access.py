#!/usr/bin/python3 -I
"""Fixed CI login protocol and root-owned deployment admission.

Installed copies must be root-owned. No repository code is imported at runtime.
The activation adapter is a separate, reviewed integration, deliberately absent
from this package: the existing D-027 worker cannot run under NoNewPrivileges.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CONTROL = "/usr/local/sbin/ar-local-ci-control"
ADAPTER = Path("/usr/local/lib/ar-local-ci/activate_adapter.py")
PLANS = Path("/etc/ar-local/ci-plans")
STATE = Path("/var/lib/ar-local-ci")
HEX64 = re.compile(r"[0-9a-f]{64}")
HEX40 = re.compile(r"[0-9a-f]{40}")
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "HOME": "/nonexistent"}
UNITS = ("ar-local-dashboard.service", "ar-local-daily.service", "ar-local-daily.timer")
# Foundation only: enabling this requires a separately reviewed integration,
# including NNP on every service that can execute the writable production tree.
# A sandboxed worker must not plant code later executed with unrestricted sudo.
ACTIVATION_INTEGRATION_READY = False


def parse_command(command: str) -> dict:
    if command == "status":
        return {"action": "status"}
    match = re.fullmatch(r"activate ([0-9a-f]{64})", command)
    if match:
        return {"action": "activate", "plan": match[1]}
    raise ValueError("only status or activate <approved-plan-sha256> is permitted")


def request_from_json(body: str) -> dict:
    value = json.loads(body)
    if value == {"action": "status"}:
        return value
    if (isinstance(value, dict) and set(value) == {"action", "plan"}
            and value["action"] == "activate" and isinstance(value["plan"], str)
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
    if not isinstance(value, dict) or value.get("schema_version") != 1 or value.get("result") != "PASS":
        raise ValueError("offsite recovery approval is unavailable")
    required = {"raw_archive", "system_image", "restore_proof", "boot_proof"}
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
    if (not isinstance(plan, dict) or set(plan) != required or plan["schema_version"] != 1
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
    result = {}
    for unit in UNITS:
        response = run(["/usr/bin/systemctl", "show", unit,
                        "--property=LoadState,ActiveState,SubState,Result,MainPID", "--no-pager"])
        if response.returncode:
            raise RuntimeError("service status unavailable")
        result[unit] = dict(line.split("=", 1) for line in response.stdout.splitlines() if "=" in line)
    return {"result": "OBSERVED", "units": result, "deployment_acceptance": "NOT_ASSESSED"}


def activation_argv(plan_id: str) -> list[str]:
    # No executable, path, environment, service name or systemd property comes
    # from SSH input or from the plan. The root-approved adapter receives one ID.
    if not HEX64.fullmatch(plan_id):
        raise ValueError("invalid plan identity")
    return ["/usr/bin/systemd-run", "--wait", "--pipe", "--collect",
            "--unit=ar-local-ci-activate-" + plan_id,
            "--property=User=pi", "--property=Group=pi", "--property=NoNewPrivileges=yes",
            "--property=ProtectSystem=strict", "--property=ProtectHome=yes",
            "--property=PrivateTmp=yes", "--property=PrivateDevices=yes",
            "--property=ProtectKernelTunables=yes", "--property=ProtectKernelModules=yes",
            "--property=ProtectControlGroups=yes", "--property=RestrictNamespaces=yes",
            "--property=CapabilityBoundingSet=", "--property=AmbientCapabilities=",
            "--property=KillMode=control-group", "--property=RuntimeMaxSec=1800",
            "--property=ReadWritePaths=/srv/ar-local/AR-local /srv/ar-local/data /var/lib/ar-local-ci/worker",
            "--property=WorkingDirectory=/", "--setenv=HOME=/nonexistent",
            "--setenv=PATH=/usr/sbin:/usr/bin:/sbin:/bin", "--",
            "/usr/bin/python3", "-I", str(ADAPTER), plan_id]


def activate(plan_id: str) -> dict:
    if not ACTIVATION_INTEGRATION_READY:
        raise RuntimeError("activation integration unavailable: verify per-service NoNewPrivileges and root-owned controls first")
    # Missing adapter blocks before creating a claim or changing any Pi state.
    plan = validate_plan(plan_id)
    require_root_path(STATE, directory=True)
    claim = STATE / (plan_id + ".claimed.json")
    descriptor = os.open(claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump({"plan": plan_id, "target_commit": plan["target_commit"],
                   "claimed_at": datetime.now(timezone.utc).isoformat()}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(STATE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    # A timeout/error consumes this plan. Never replay an ambiguous transaction.
    response = run(activation_argv(plan_id), timeout=1860)
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
                              timeout=1900, shell=False, close_fds=True)
    return response.returncode


def control_main() -> int:
    if os.geteuid() != 0 or len(sys.argv) != 1 or os.environ.get("SUDO_USER") != "ar-local-ci":
        raise ValueError("control requires the dedicated CI sudo entry without arguments")
    body = sys.stdin.buffer.read(4097)
    if len(body) > 4096:
        raise ValueError("request too large")
    request = request_from_json(body.decode("utf-8"))
    result = status() if request["action"] == "status" else activate(request["plan"])
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
