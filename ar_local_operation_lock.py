"""Crash-recoverable exclusive lock shared by Pi backup operations."""

from __future__ import annotations

import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ar_local_backup_policy import fsync_directory

LOCK_STALE_SECONDS = 6 * 60 * 60
BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")
UPTIME_PATH = Path("/proc/uptime")


def _current_boot_id() -> str:
    try:
        return BOOT_ID_PATH.read_text(encoding="ascii").strip()
    except OSError:
        return ""


def _boot_epoch() -> float | None:
    try:
        uptime = float(UPTIME_PATH.read_text(encoding="ascii").split()[0])
    except (OSError, ValueError, IndexError):
        return None
    return time.time() - uptime


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _lock_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return values
    for line in lines:
        key, separator, value = line.partition("=")
        if separator and key and key not in values:
            values[key] = value.strip()
    return values


def _existing_lock_is_stale(path: Path) -> bool:
    if path.is_symlink():
        return False
    try:
        info = path.stat()
    except OSError:
        return False
    values = _lock_values(path)
    boot_id = _current_boot_id()
    recorded_boot = values.get("boot_id", "")
    if boot_id and recorded_boot and boot_id != recorded_boot:
        return True
    boot_epoch = _boot_epoch()
    if boot_epoch is not None and info.st_mtime < boot_epoch - 1:
        return True
    try:
        owner_pid = int(values.get("pid", ""))
    except ValueError:
        owner_pid = 0
    if owner_pid:
        return not _pid_is_alive(owner_pid)
    return time.time() - info.st_mtime > LOCK_STALE_SECONDS


def _open_exclusive(path: Path, role: str) -> int:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    boot_id = _current_boot_id()
    payload = f"pid={os.getpid()}\nrole={role}\n"
    if boot_id:
        payload += f"boot_id={boot_id}\n"
    os.write(descriptor, payload.encode("utf-8"))
    os.fsync(descriptor)
    fsync_directory(path.parent)
    return descriptor


@contextmanager
def production_lock(lock_path: Path, role: str) -> Iterator[None]:
    """Hold an O_EXCL lock and recover only a provably stale predecessor."""

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = _open_exclusive(lock_path, role)
    except FileExistsError as exc:
        if not _existing_lock_is_stale(lock_path):
            raise RuntimeError(f"production lock is active: {lock_path}") from exc
        stale = lock_path.with_name(f".{lock_path.name}.stale-{uuid.uuid4().hex}")
        try:
            lock_path.replace(stale)
            fsync_directory(lock_path.parent)
            stale.unlink()
            fsync_directory(lock_path.parent)
            descriptor = _open_exclusive(lock_path, role)
        except FileExistsError as retry_exc:
            raise RuntimeError(f"production lock was acquired concurrently: {lock_path}") from retry_exc
    try:
        yield
    finally:
        owned_path = False
        try:
            owned = os.fstat(descriptor)
            current = lock_path.stat()
            owned_path = (owned.st_dev, owned.st_ino) == (current.st_dev, current.st_ino)
            if owned_path and os.name != "nt":
                lock_path.unlink()
                fsync_directory(lock_path.parent)
        except OSError:
            pass
        finally:
            os.close(descriptor)
        if owned_path and os.name == "nt":
            lock_path.unlink(missing_ok=True)
