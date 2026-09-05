"""Ordinary-user backup scheduling, without an elevated installer or S4U token."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


SCHEMA = "ARL-USER-SESSION-BACKUP-V1"
CONFIG_NAME = "user-session-backup.json"
HOBART = ZoneInfo("Australia/Hobart")
KEYS = {
    "schema", "operator_sid", "candidate_sha", "protected_sha", "receiver",
    "target", "legacy_target", "legacy_task", "recovery_image", "python_path",
    "python_sha256", "git_path", "git_sha256", "transport", "authority",
}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else _digest(stream)


def _digest(stream) -> str:
    value = hashlib.sha256()
    for block in iter(lambda: stream.read(4 * 1024**2), b""):
        value.update(block)
    return value.hexdigest()


def ordinary_identity() -> str:
    if os.name != "nt":
        raise ValueError("user-session backup requires Windows")
    if ctypes.windll.shell32.IsUserAnAdmin():
        raise ValueError("user-session backup refuses an elevated token")
    whoami = Path(os.environ["SystemRoot"]) / "System32/whoami.exe"
    result = subprocess.run([str(whoami), "/user", "/fo", "csv", "/nh"],
                            capture_output=True, text=True, check=True, timeout=10)
    import csv
    rows = list(csv.reader(result.stdout.splitlines()))
    if len(rows) != 1 or len(rows[0]) != 2 or not rows[0][1].startswith("S-1-"):
        raise ValueError("current Windows SID is unavailable")
    return rows[0][1]


def unlinked(path: Path) -> Path:
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError("backup path must be absolute and canonical")
    for part in (path, *path.parents):
        if part.exists() and (part.is_symlink() or getattr(part.stat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("backup path traverses a reparse point")
    return path


def separate_targets(target: Path, legacy: Path) -> None:
    unlinked(target)
    unlinked(legacy)
    if target == legacy or target in legacy.parents or legacy in target.parents:
        raise ValueError("user and legacy backup targets must be disjoint")


def strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate user-session configuration key")
        result[key] = value
    return result


def load_config(path: Path, expected_digest: str | None = None) -> dict:
    unlinked(path)
    if expected_digest is not None and digest(path) != expected_digest:
        raise ValueError("user-session configuration changed")
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=strict_pairs)
    if not isinstance(value, dict) or set(value) != KEYS or value["schema"] != SCHEMA:
        raise ValueError("user-session configuration schema is invalid")
    if value["operator_sid"] != ordinary_identity():
        raise ValueError("user-session operator SID changed")
    receiver = unlinked(Path(value["receiver"]))
    if receiver != Path(__file__).resolve().parent or path != receiver.parent / CONFIG_NAME:
        raise ValueError("user-session configuration is outside its exact release")
    separate_targets(Path(value["target"]), Path(value["legacy_target"]))
    for name in ("python", "git"):
        executable = unlinked(Path(value[f"{name}_path"]))
        if digest(executable) != value[f"{name}_sha256"]:
            raise ValueError(f"user-session {name} executable changed")
    if Path(sys.executable).resolve() != Path(value["python_path"]):
        raise ValueError("user-session Python interpreter differs from configuration")
    return value


def transport_contract() -> dict:
    """Explicit ordinary-user contract; never claim administrator protection."""
    expected = os.environ.get("AR_USER_BACKUP_CONFIG_SHA256")
    if not expected:
        raise ValueError("user-session transport requires its verified runner")
    config = load_config(Path(__file__).resolve().parent.parent / CONFIG_NAME, expected)
    value = config["transport"]
    fields = {"ssh_path", "ssh_sha256", "scp_path", "scp_sha256", "ssh_host",
              "ssh_user", "ssh_port", "ssh_logical_host", "ssh_identity_path",
              "ssh_identity_sha256", "ssh_known_hosts_path", "ssh_known_hosts_sha256"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("user-session transport fields are not exact")
    return value


def allowed_start(now: datetime) -> bool:
    local = now.astimezone(HOBART)
    # A six-hour task timeout leaves two hours before the 22:00 cutoff.
    return 6 <= local.hour < 14


def verify_release(config: dict) -> None:
    git = config["git_path"]
    root = config["receiver"]
    def call(*args):
        return subprocess.run([git, "-C", root, *args], capture_output=True,
                              text=True, check=True, timeout=30).stdout.strip()
    if call("rev-parse", "HEAD") != config["candidate_sha"] or call("status", "--porcelain"):
        raise ValueError("user-session receiver is not clean at its pinned commit")
    if call("log", "-1", "--format=%H", "--", "docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md") != "9094a8e115958fcaf2cb36525736bd5e297e6b04":
        raise ValueError("receiver plan authority changed")
    if config["authority"] != "D-015-USER-SESSION-NO-UAC":
        raise ValueError("user-session continuation authority is invalid")


def legacy_idle(name: str) -> None:
    # Task name goes through an environment value, never shell interpolation.
    env = dict(os.environ, AR_USER_BACKUP_LEGACY_TASK=name)
    script = "$ErrorActionPreference='Stop'; $t=Get-ScheduledTask -TaskName $env:AR_USER_BACKUP_LEGACY_TASK -ErrorAction Stop; Write-Output $t.State"
    ps = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([str(ps), "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True, timeout=30, env=env)
    if result.returncode or result.stdout.strip() not in {"Ready", "Disabled"}:
        raise ValueError("legacy backup task is running or its state cannot be verified")


def record(config: dict, result: str, detail: str, **extra) -> Path:
    from laptop_backup_atomic import atomic_create
    root = unlinked(Path(config["target"])) / "user-session-executions"
    root.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    value = {"schema": SCHEMA, "result": result, "detail": detail,
             "at": now.isoformat(), "operator_sid": config["operator_sid"],
             "candidate_sha": config["candidate_sha"], "authority": config["authority"],
             "elevated": False, **extra}
    path = root / f"{now:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex}.json"
    atomic_create(path, (json.dumps(value, sort_keys=True) + "\n").encode())
    return path


def execute(config: dict, mode: str, config_sha256: str) -> int:
    verify_release(config)
    # Pin subsequent transport reloads to the exact bytes accepted by this task.
    os.environ["AR_USER_BACKUP_CONFIG_SHA256"] = config_sha256
    if mode == "probe":
        path = record(config, "PASS", "ordinary-token and pinned release verified; no backup invoked")
        print(json.dumps({"result": "PASS", "evidence": str(path), "elevated": False}))
        return 0
    if not allowed_start(datetime.now(timezone.utc)):
        record(config, "BLOCKED", "outside 06:00-14:00 Hobart start window; no Pi access")
        return 2
    legacy_idle(config["legacy_task"])
    from laptop_backup_atomic import ReceiverLock
    import laptop_backup_scheduled as scheduled
    transport = transport_contract()
    discovery = subprocess.run(
        [sys.executable, "-B", str(Path(config["receiver"]) / "laptop_backup_ssh_endpoint.py"),
         "--name", "ar.local"], capture_output=True, text=True, check=True, timeout=15,
    )
    from laptop_backup_ssh_endpoint import lan_ipv4
    endpoint = lan_ipv4(discovery.stdout.strip())
    args = ["--target", config["target"], "--recovery-image", config["recovery_image"],
            "--candidate-code-sha", config["candidate_sha"],
            "--protected-code-sha", config["protected_sha"],
            "--plan-git-commit", "9094a8e115958fcaf2cb36525736bd5e297e6b04",
            "--operator", config["operator_sid"], "--host", endpoint,
            "--ssh-user", transport["ssh_user"], "--ssh-port", str(transport["ssh_port"])]
    for arg, field in (("ssh-path", "ssh_path"), ("ssh-sha256", "ssh_sha256"),
                       ("scp-path", "scp_path"), ("scp-sha256", "scp_sha256"),
                       ("ssh-identity", "ssh_identity_path"), ("ssh-known-hosts", "ssh_known_hosts_path")):
        args.extend(("--" + arg, transport[field]))
    if mode == "check":
        args.append("--check-only")
    # Separate lock root: the receiver owns target/catalog/.receiver.lock itself.
    lock_root = unlinked(Path(config["target"])) / "user-session-lock"
    lock_root.mkdir(parents=True, exist_ok=True)
    with ReceiverLock(lock_root):
        code = scheduled.main(args)
    record(config, "PASS" if code == 0 else "FAIL", "scheduled receiver returned", exit_code=code)
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("run", "check", "probe"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--config-sha256", required=True)
    args = parser.parse_args()
    try:
        config = load_config(args.config, args.config_sha256)
        return execute(config, args.mode, args.config_sha256)
    except Exception as exc:
        print(json.dumps({"result": "BLOCKED", "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
