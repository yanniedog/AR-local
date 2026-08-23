"""Fail-closed policy primitives for AR-local off-device backups."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

PLAN_DOCUMENT_ID = "ARL-OPS-001"
PLAN_VERSION = "1.0"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(value: Mapping[str, object]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def fsync_directory(path: Path) -> None:
    """Make a completed create, replace, or unlink durable on POSIX filesystems."""

    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_create_json(path: Path, value: Mapping[str, object]) -> None:
    """Create an immutable record; an existing path is never replaced."""

    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o444)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(canonical_json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    os.chmod(path, 0o444)
    fsync_directory(path.parent)


def atomic_replace_json(path: Path, value: Mapping[str, object]) -> None:
    """Durably replace a mutable pointer without exposing partial JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{os.urandom(6).hex()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(canonical_json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _decode_mount_field(value: str) -> str:
    return value.replace("\\040", " ").replace("\\011", "\t").replace("\\134", "\\")


def parse_mountinfo(lines: Iterable[str]) -> list[dict[str, str]]:
    mounts: list[dict[str, str]] = []
    for raw in lines:
        left, separator, right = raw.rstrip("\n").partition(" - ")
        if not separator:
            continue
        fields = left.split()
        tail = right.split()
        if len(fields) < 6 or len(tail) < 2:
            continue
        mounts.append(
            {
                "mount_id": fields[0],
                "device": fields[2],
                "root": _decode_mount_field(fields[3]),
                "mountpoint": _decode_mount_field(fields[4]),
                "options": fields[5],
                "fstype": tail[0],
                "source": _decode_mount_field(tail[1]),
            }
        )
    return mounts


def _root_block_device(node: Path) -> str:
    parts = node.resolve(strict=True).parts
    try:
        index = parts.index("block")
        return parts[index + 1]
    except (ValueError, IndexError) as exc:
        raise ValueError(f"cannot resolve physical block device for {node}") from exc


def physical_block_devices(
    device: str,
    *,
    sys_dev_block: Path = Path("/sys/dev/block"),
    _seen: set[str] | None = None,
) -> set[str]:
    """Resolve a major:minor filesystem device to its leaf physical disks."""

    if not re.fullmatch(r"\d+:\d+", device):
        raise ValueError(f"invalid block device number: {device}")
    seen = _seen or set()
    if device in seen:
        raise ValueError("block device ancestry loop")
    seen.add(device)
    node = (sys_dev_block / device).resolve(strict=True)
    slaves = node / "slaves"
    children = sorted(slaves.iterdir()) if slaves.is_dir() else []
    if not children:
        return {_root_block_device(node)}
    leaves: set[str] = set()
    for child in children:
        info = child.resolve(strict=True) / "dev"
        leaves.update(
            physical_block_devices(
                info.read_text(encoding="ascii").strip(),
                sys_dev_block=sys_dev_block,
                _seen=set(seen),
            )
        )
    return leaves


def load_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip():
            raise ValueError(f"invalid configuration line {number}")
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


@dataclass(frozen=True)
class BackupPolicy:
    mountpoint: Path
    expected_source: str
    expected_fstype: str
    backup_dir: Path
    expected_uid: int
    expected_gid: int
    max_backup_age_hours: int
    max_restore_age_hours: int
    max_boot_proof_age_hours: int
    min_free_bytes: int
    retention_count: int
    plan_git_commit: str
    plan_sha256: str
    plan_raw_sha256: str

    @classmethod
    def from_env_file(cls, path: Path) -> "BackupPolicy":
        values = load_env(path)
        required = {
            "AR_BACKUP_MOUNTPOINT",
            "AR_BACKUP_EXPECTED_SOURCE",
            "AR_BACKUP_EXPECTED_FSTYPE",
            "AR_BACKUP_DIRECTORY",
            "AR_BACKUP_EXPECTED_UID",
            "AR_BACKUP_EXPECTED_GID",
            "AR_BACKUP_PLAN_GIT_COMMIT",
            "AR_BACKUP_PLAN_SHA256",
            "AR_BACKUP_PLAN_RAW_SHA256",
        }
        missing = sorted(required - values.keys())
        if missing:
            raise ValueError(f"missing backup configuration: {', '.join(missing)}")
        configured_mountpoint = Path(values["AR_BACKUP_MOUNTPOINT"])
        configured_backup_dir = Path(values["AR_BACKUP_DIRECTORY"])
        if not configured_mountpoint.is_absolute() or not configured_backup_dir.is_absolute():
            raise ValueError("backup paths must be absolute")
        mountpoint = configured_mountpoint.resolve(strict=True)
        backup_dir = configured_backup_dir.resolve(strict=True)
        if (
            configured_mountpoint != mountpoint
            or configured_backup_dir != backup_dir
            or configured_mountpoint.is_symlink()
            or configured_backup_dir.is_symlink()
            or not backup_dir.is_dir()
            or mountpoint not in backup_dir.parents
        ):
            raise ValueError("backup paths must be canonical real directories with the backup below the mountpoint")
        commit = values["AR_BACKUP_PLAN_GIT_COMMIT"].lower()
        digest = values["AR_BACKUP_PLAN_SHA256"].lower()
        raw_digest = values["AR_BACKUP_PLAN_RAW_SHA256"].lower()
        if not COMMIT_RE.fullmatch(commit) or not SHA256_RE.fullmatch(digest) or not SHA256_RE.fullmatch(raw_digest):
            raise ValueError("plan commit or SHA-256 is invalid")
        max_backup_age_hours = int(values.get("AR_BACKUP_MAX_AGE_HOURS", "36"))
        max_restore_age_hours = int(values.get("AR_BACKUP_RESTORE_MAX_AGE_HOURS", "192"))
        max_boot_proof_age_hours = int(values.get("AR_BACKUP_BOOT_PROOF_MAX_AGE_HOURS", "2160"))
        min_free_bytes = int(values.get("AR_BACKUP_MIN_FREE_BYTES", "10737418240"))
        retention_count = int(values.get("AR_BACKUP_RETENTION_COUNT", "14"))
        if min(max_backup_age_hours, max_restore_age_hours, max_boot_proof_age_hours, min_free_bytes) <= 0:
            raise ValueError("backup ages and minimum free bytes must be positive")
        if retention_count < 2:
            raise ValueError("backup retention count must be at least two")
        return cls(
            mountpoint=mountpoint,
            expected_source=values["AR_BACKUP_EXPECTED_SOURCE"],
            expected_fstype=values["AR_BACKUP_EXPECTED_FSTYPE"],
            backup_dir=backup_dir,
            expected_uid=int(values["AR_BACKUP_EXPECTED_UID"]),
            expected_gid=int(values["AR_BACKUP_EXPECTED_GID"]),
            max_backup_age_hours=max_backup_age_hours,
            max_restore_age_hours=max_restore_age_hours,
            max_boot_proof_age_hours=max_boot_proof_age_hours,
            min_free_bytes=min_free_bytes,
            retention_count=retention_count,
            plan_git_commit=commit,
            plan_sha256=digest,
            plan_raw_sha256=raw_digest,
        )

    def plan_identity(self) -> dict[str, str]:
        return {
            "plan_document_id": PLAN_DOCUMENT_ID,
            "plan_version": PLAN_VERSION,
            "plan_git_commit": self.plan_git_commit,
            "plan_sha256": self.plan_sha256,
            "plan_raw_sha256": self.plan_raw_sha256,
        }


def mount_preflight(
    policy: BackupPolicy,
    protected_roots: Iterable[Path],
    *,
    mountinfo_path: Path = Path("/proc/self/mountinfo"),
    perform_probe: bool = True,
    sys_dev_block: Path = Path("/sys/dev/block"),
) -> dict[str, object]:
    findings: list[str] = []
    mountpoint = policy.mountpoint.resolve(strict=True)
    if mountpoint != policy.mountpoint or policy.mountpoint.is_symlink():
        findings.append("mountpoint_not_canonical")
    matches = [m for m in parse_mountinfo(mountinfo_path.read_text().splitlines()) if m["mountpoint"] == str(mountpoint)]
    if len(matches) != 1:
        findings.append("mountpoint_not_exactly_mounted")
        mount = None
    else:
        mount = matches[0]
        actual_source = os.path.realpath(mount["source"]) if Path(mount["source"]).exists() else mount["source"]
        expected_source = os.path.realpath(policy.expected_source) if Path(policy.expected_source).exists() else policy.expected_source
        if actual_source != expected_source:
            findings.append("mount_source_mismatch")
        if mount["fstype"] != policy.expected_fstype:
            findings.append("mount_fstype_mismatch")
        if "rw" not in mount["options"].split(","):
            findings.append("mount_not_read_write")
    mount_device = mountpoint.stat().st_dev
    backup_physical: set[str] = set()
    if mount is not None:
        try:
            backup_physical = physical_block_devices(mount["device"], sys_dev_block=sys_dev_block)
        except (OSError, ValueError):
            findings.append("backup_physical_device_unresolved")
    for root in protected_roots:
        resolved = root.resolve(strict=True)
        if resolved == mountpoint or mountpoint in resolved.parents:
            findings.append(f"protected_root_on_backup_mount:{resolved}")
        if resolved.stat().st_dev == mount_device:
            findings.append(f"backup_not_physically_separate:{resolved}")
        try:
            source_number = f"{os.major(resolved.stat().st_dev)}:{os.minor(resolved.stat().st_dev)}"
            source_physical = physical_block_devices(source_number, sys_dev_block=sys_dev_block)
            if backup_physical & source_physical:
                findings.append(f"backup_shares_physical_device:{resolved}")
        except (AttributeError, OSError, ValueError):
            findings.append(f"source_physical_device_unresolved:{resolved}")
    backup_dir = policy.backup_dir
    if not backup_dir.is_dir() or backup_dir.is_symlink():
        findings.append("backup_directory_missing_or_symlink")
    else:
        info = backup_dir.stat()
        if info.st_dev != mount_device:
            findings.append("backup_directory_on_nested_or_other_mount")
        if info.st_uid != policy.expected_uid or info.st_gid != policy.expected_gid:
            findings.append("backup_directory_owner_mismatch")
        if stat.S_IMODE(info.st_mode) != 0o700:
            findings.append("backup_directory_mode_not_0700")
    if backup_dir.exists() and shutil.disk_usage(backup_dir).free < policy.min_free_bytes:
        findings.append("backup_capacity_below_minimum")
    if perform_probe and not findings:
        probe = backup_dir / f".write-probe-{os.getpid()}"
        renamed = backup_dir / f".write-probe-{os.getpid()}.verified"
        payload = os.urandom(64)
        try:
            with probe.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if sha256_file(probe) != hashlib.sha256(payload).hexdigest():
                findings.append("backup_write_probe_hash_mismatch")
            probe.replace(renamed)
        except OSError as exc:
            findings.append(f"backup_write_probe_failed:{type(exc).__name__}")
        finally:
            probe.unlink(missing_ok=True)
            renamed.unlink(missing_ok=True)
    return {"ok": not findings, "mount": mount, "findings": findings}


def record_is_fresh(record: Mapping[str, object], max_age_hours: int, now: datetime) -> bool:
    try:
        created = parse_timestamp(str(record["created_at"]))
    except (KeyError, TypeError, ValueError):
        return False
    age = (now.astimezone(timezone.utc) - created).total_seconds()
    return 0 <= age <= max_age_hours * 3600


def validate_plan_identity(record: Mapping[str, object], policy: BackupPolicy) -> bool:
    return all(record.get(key) == value for key, value in policy.plan_identity().items())
