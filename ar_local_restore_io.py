"""Pin preserved input reads and check cooperative restore deadlines between I/O.

Descriptors bind regular source inodes; SQLite only opens private copies. A
filesystem or kernel call that does not return is not a hard timed boundary.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path
import stat

from cdr_sqlite_budget import check_deadline, current_deadline

CHUNK_BYTES = 1024 * 1024
_database_paths = ContextVar('restore_pinned_database_paths', default=None)


def checkpoint(**_charges) -> None:
    deadline = current_deadline()
    if deadline is not None:
        check_deadline(deadline)


def read_budget():
    return checkpoint if current_deadline() is not None else None


@contextmanager
def database_copy(source: Path, private: Path):
    paths = dict(_database_paths.get() or {})
    paths[source.absolute()] = private
    token = _database_paths.set(paths)
    try:
        yield
    finally:
        _database_paths.reset(token)


def database_path(source: Path) -> Path:
    paths = _database_paths.get()
    if paths is None:
        return source
    if source.absolute() not in paths:
        raise ValueError('restore SQLite input was not pinned')
    return paths[source.absolute()]


def identity(value) -> tuple:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


def regular_identity(path: Path) -> tuple:
    checkpoint()
    value = path.lstat()
    if not stat.S_ISREG(value.st_mode):
        raise ValueError("preserved source must be a regular unlinked file")
    return identity(value)


@contextmanager
def pinned_reader(path: Path, *, expected=None):
    before = regular_identity(path)
    if expected is not None and before != tuple(expected):
        raise ValueError("preserved source changed before opening")
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(path, flags)
    try:
        if identity(os.fstat(descriptor)) != before:
            raise ValueError("preserved source changed while opening")
        stream = os.fdopen(descriptor, 'rb')
    except BaseException:
        os.close(descriptor)
        raise
    with stream:
        yield stream, before
        checkpoint()
        if identity(os.fstat(stream.fileno())) != before or regular_identity(path) != before:
            raise ValueError("preserved source changed while reading")


def chunks(stream, size):
    remaining = size
    while remaining:
        checkpoint()
        block = stream.read(min(CHUNK_BYTES, remaining))
        checkpoint()
        if not block:
            raise ValueError("preserved source was truncated while reading")
        remaining -= len(block)
        yield block
    checkpoint()


def read_bytes(path: Path) -> bytes:
    with pinned_reader(path) as (stream, source):
        return b''.join(chunks(stream, source[3]))


def read_json(path: Path):
    payload = json.loads(read_bytes(path).decode('utf-8'))
    checkpoint()
    return payload


def optional_read_bytes(path: Path):
    return read_bytes(path) if current_deadline() is not None else path.read_bytes()


def optional_read_json(path: Path):
    return read_json(path) if current_deadline() is not None else json.loads(path.read_text(encoding='utf-8'))


def glob_paths(root: Path, pattern: str):
    if current_deadline() is None:
        return list(root.glob(pattern))
    paths = []
    checkpoint()
    with os.scandir(root) as entries:
        for entry in entries:
            checkpoint()
            if Path(entry.name).match(pattern):
                paths.append(root / entry.name)
    return paths


def hash_file(path: Path, *, expected=None) -> str:
    digest = hashlib.sha256()
    with pinned_reader(path, expected=expected) as (stream, source):
        for block in chunks(stream, source[3]):
            digest.update(block)
    return digest.hexdigest()


def copy_stream(stream, source, target: Path) -> str:
    digest = hashlib.sha256()
    with target.open('xb') as destination:
        for block in chunks(stream, source[3]):
            destination.write(block)
            digest.update(block)
        checkpoint()
    return digest.hexdigest()


def copy_file(source, target, *, expected=None):
    source, target = Path(source), Path(target)
    with pinned_reader(source, expected=expected) as (stream, before):
        copy_stream(stream, before, target)
    return str(target)


def walk(root: Path):
    """Do not follow linked directories; checkpoint during discovery, not after."""
    checkpoint()
    with os.scandir(root) as entries:
        children = []
        for entry in entries:
            checkpoint()
            children.append(Path(entry.path))
    for path in sorted(children):
        checkpoint()
        yield path
        if stat.S_ISDIR(path.lstat().st_mode):
            yield from walk(path)


def copy_tree(source: Path, target: Path, *, expected: dict):
    checkpoint()
    source_identity = source.lstat()
    if not stat.S_ISDIR(source_identity.st_mode):
        raise ValueError("preserved source root must be an unlinked directory")
    target.mkdir()
    for path in walk(source):
        relative = path.relative_to(source)
        destination = target / relative
        value = path.lstat()
        if stat.S_ISDIR(value.st_mode):
            destination.mkdir()
        elif stat.S_ISREG(value.st_mode):
            key = path.relative_to(source.parent).as_posix()
            if key not in expected:
                raise ValueError("copy source was not verified in snapshot")
            copy_file(path, destination, expected=expected[key])
        else:
            raise ValueError("preserved copy source must be regular and unlinked")
    checkpoint()
    if identity(source.lstat()) != identity(source_identity):
        raise ValueError('preserved source directory changed while copying')
