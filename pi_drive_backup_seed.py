"""Read-only untrusted restore hints, copied into an exclusively new target.

No seed byte is acceptance evidence. Restic must check all reused chunks and
the caller must still verify every manifest byte and SQLite database.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import stat

from pi_drive_backup_manifest import encoded
from pi_drive_backup_read import chunks, discard_created_cache
from pi_drive_backup_source import restore_relative
from pi_drive_backup_write import CreatedWriter

SCHEMA = "ar-local-drive-restore-seed-v1"


class MissingSeed(FileNotFoundError):
    """Only absence before a seed file is opened is an optional cache miss."""


def validate_seed(value):
    if (not isinstance(value, dict) or set(value) != {"directory", "device", "inode"}
            or not re.fullmatch(r"restore-[a-z0-9_]{8}", str(value.get("directory", "")))
            or any(type(value.get(key)) is not int or value[key] < 0 for key in ("device", "inode"))
            or value["inode"] == 0):
        raise ValueError("invalid direct-spool restore seed identity")
    return value


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@contextmanager
def seed_root(spool: Path, seed):
    validate_seed(seed)
    if os.name != "posix" or os.open not in os.supports_dir_fd or not hasattr(os, "O_NOFOLLOW"):
        raise ValueError("restore seeds require a read-only POSIX mount")
    path = spool / seed["directory"]
    if path.resolve(strict=True) != path or path.parent != spool or path.is_symlink():
        raise ValueError("restore seed leaves its canonical spool")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if ((info.st_dev, info.st_ino) != (seed["device"], seed["inode"])
                or not os.fstatvfs(fd).f_flag & os.ST_RDONLY):
            raise ValueError("restore seed identity or read-only mount differs")
        yield fd
        end = path.lstat()
        if (end.st_dev, end.st_ino) != (info.st_dev, info.st_ino) or path.resolve() != path:
            raise ValueError("restore seed root changed")
    finally:
        os.close(fd)


@contextmanager
def seed_file(root_fd, relative: Path, device):
    """Walk beneath an open root without following a directory or file symlink."""
    parents = [os.dup(root_fd)]
    edges = []
    source = None
    opened = False
    try:
        for part in relative.parts[:-1]:
            parent = parents[-1]
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            parents.append(child)
            info = os.fstat(child)
            edges.append((parent, part, (info.st_dev, info.st_ino)))
            if info.st_dev != device:
                raise ValueError("restore seed crosses a filesystem")
        parent = parents[-1]
        source = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        info = os.fstat(source)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_dev != device:
            raise ValueError("restore seed file is not an isolated regular file")
        opened = True
        with os.fdopen(source, "rb") as stream:
            source = None
            yield stream, info
            current = os.stat(relative.name, dir_fd=parent, follow_symlinks=False)
            if _identity(current) != _identity(info) or _identity(os.fstat(stream.fileno())) != _identity(info):
                raise ValueError("restore seed file changed while copying")
            for directory, name, expected in edges:
                current = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != expected:
                    raise ValueError("restore seed parent changed while copying")
    except FileNotFoundError as error:
        if opened: raise ValueError("restore seed or destination disappeared during copying") from error
        raise MissingSeed("listed restore seed file is absent") from error
    finally:
        if source is not None: os.close(source)
        for parent in reversed(parents): os.close(parent)


def copy_file(stream, info, destination, guard):
    """Bound the copy by the observed size; preserve no seed metadata or links."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    copied, digest = 0, hashlib.sha256()
    with destination.open("xb") as output:
        writer = CreatedWriter(output)
        for block in chunks(stream):
            guard()
            copied += len(block)
            if copied > info.st_size:
                raise ValueError("restore seed grew beyond its observed size")
            writer.write(block, guard)
            digest.update(block)
        if copied != info.st_size:
            raise ValueError("restore seed was truncated during copying")
        output.flush(); os.fsync(output.fileno())
        discard_created_cache(output)
    return copied, digest.hexdigest()


def copy_seed(spool: Path, target: Path, rows, seed, *, guard):
    """Copy only listed hints. Full snapshot verification is still mandatory."""
    validate_seed(seed)
    if (target.parent != spool or target.resolve() != target or target.is_symlink()
            or target == spool / seed["directory"] or not target.is_dir() or any(target.iterdir())):
        raise ValueError("restore seed destination must be a fresh empty private directory")
    result = {"schema": SCHEMA, "seed": dict(seed), "untrusted": True, "read_only": True,
              "files_considered": 0, "files_copied": 0, "bytes_copied": 0,
              "files_missing": 0, "files_oversize": 0}
    inventory = hashlib.sha256()
    with seed_root(spool, seed) as root_fd:
        for row in rows:
            guard()
            relative = restore_relative(row["backup_path"])
            if not relative.parts or len(relative.parts) > 64 or type(row["size"]) is not int or row["size"] < 0:
                raise ValueError("invalid expected restore seed path or size")
            result["files_considered"] += 1
            try:
                with seed_file(root_fd, relative, seed["device"]) as (stream, info):
                    if info.st_size > row["size"]:
                        result["files_oversize"] += 1
                        continue
                    count, digest = copy_file(stream, info, target / relative, guard)
                    result["files_copied"] += 1; result["bytes_copied"] += count
                    inventory.update(encoded({"path": relative.as_posix(), "bytes": count, "copied_stream_sha256": digest}))
            except MissingSeed:
                result["files_missing"] += 1
    result["copied_streams_sha256"] = inventory.hexdigest()
    return result


def validate_seed_receipt(seed, receipt):
    validate_seed(seed)
    if (not isinstance(receipt, dict) or receipt.get("schema") != SCHEMA or receipt.get("seed") != seed
            or receipt.get("read_only") is not True or receipt.get("untrusted") is not True
            or any(type(receipt.get(key)) is not int or receipt[key] < 0 for key in
                   ("files_considered", "files_copied", "bytes_copied", "files_missing", "files_oversize"))
            or receipt["files_considered"] != sum(receipt[key] for key in ("files_copied", "files_missing", "files_oversize"))
            or not re.fullmatch(r"[a-f0-9]{64}", str(receipt.get("copied_streams_sha256", "")))):
        raise ValueError("restore seed receipt differs from its explicit descriptor")
