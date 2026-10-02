"""Fresh, identity-bound evidence reads; digest reuse is local to one snapshot."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

BLOCK_BYTES = 4 * 1024 * 1024


def _identity(info) -> tuple:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _linked(info) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _ancestors(path: Path, root: Path) -> tuple:
    if not root.is_absolute() or path == root or root not in path.parents or path.resolve() != path:
        raise ValueError("evidence must be a canonical contained path")
    result = []
    for parent in reversed(path.parents):
        info = parent.lstat()
        if _linked(info) or not stat.S_ISDIR(info.st_mode):
            raise ValueError("evidence ancestor must be an unlinked directory")
        # Do not depend on unrelated writes to /tmp, /srv or other outer parents.
        identity = (info.st_dev, info.st_ino, info.st_mode)
        if parent == root or root in parent.parents:
            identity += (info.st_mtime_ns, info.st_ctime_ns)
        result.append((parent, identity))
    return tuple(result)


def _file_state(path: Path, root: Path) -> tuple:
    ancestors = _ancestors(path, root)
    info = path.lstat()
    if _linked(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("evidence must be a canonical, unique regular file")
    return _identity(info), ancestors


def _hash_stream(stream, size: int, capture: bool) -> tuple[str, bytes | None]:
    digest, blocks, remaining = hashlib.sha256(), [], size
    while remaining:
        block = stream.read(min(BLOCK_BYTES, remaining))
        if not block:
            raise ValueError("evidence size changed during read")
        remaining -= len(block)
        digest.update(block)
        if capture:
            blocks.append(block)
    if stream.read(1):
        raise ValueError("evidence size changed during read")
    return digest.hexdigest(), b"".join(blocks) if capture else None


@dataclass(frozen=True)
class FileDigest:
    sha256: str
    size: int
    identity: tuple
    ancestors: tuple

    def recheck(self, path: Path, root: Path) -> None:
        if _file_state(path, root) != (self.identity, self.ancestors):
            raise ValueError("evidence identity changed during snapshot")


def read_digest(path: Path, *, root: Path | None = None, capture: bool = False,
                max_bytes: int | None = None) -> tuple[FileDigest, bytes | None]:
    """Bind the digest to one no-follow descriptor and unchanged path identity.

    O_NONBLOCK prevents a raced FIFO replacement from blocking before fstat.
    Platforms without O_NOFOLLOW still require matching pre/open/post identities
    and reject linked/reparse paths on both pathname observations.
    """
    root = root or path.parent
    identity, ancestors = _file_state(path, root)
    size = identity[4]
    if max_bytes is not None and size > max_bytes:
        raise ValueError("evidence JSON exceeds 64 MiB")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags)
    try:
        if _identity(os.fstat(descriptor)) != identity:
            raise ValueError("evidence descriptor differs from its pathname")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            digest, body = _hash_stream(stream, size, capture)
        if _identity(os.fstat(descriptor)) != identity:
            raise ValueError("evidence changed during descriptor read")
        result = FileDigest(digest, size, identity, ancestors)
        result.recheck(path, root)
        return result, body
    finally:
        os.close(descriptor)


class DigestSnapshot:
    """A single call owns these entries; no state is retained across calls."""
    def __init__(self, root: Path):
        self.root = root
        self.files: dict[Path, FileDigest] = {}
        self.directories: dict[Path, tuple] = {}

    def digest(self, path: Path, descriptor: dict | None = None) -> str:
        if path not in self.files:
            self.files[path] = read_digest(path, root=self.root)[0]
        entry = self.files[path]
        entry.recheck(path, self.root)
        if descriptor is not None and (entry.sha256 != descriptor["sha256"] or entry.size != descriptor["bytes"]):
            raise ValueError("current source artifact differs from its immutable contract")
        return entry.sha256

    def read(self, path: Path) -> dict:
        # Controls are parsed from the same bytes that establish their digest.
        if path in self.files:
            raise ValueError("control evidence must be read once per snapshot")
        entry, body = read_digest(path, root=self.root, capture=True, max_bytes=64 * 1024 * 1024)
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError("evidence must be a JSON object")
        self.files[path] = entry
        return value

    def directory(self, path: Path) -> None:
        # A synthetic child checks the directory itself without following it.
        observed = _ancestors(path / ".snapshot-child", self.root)
        previous = self.directories.setdefault(path, observed)
        if observed != previous:
            raise ValueError("evidence directory changed during snapshot")

    def finish(self) -> dict[str, str]:
        for path in self.directories:
            self.directory(path)
        for path, entry in self.files.items():
            entry.recheck(path, self.root)
        return {path.relative_to(self.root).as_posix(): self.files[path].sha256 for path in sorted(self.files)}
