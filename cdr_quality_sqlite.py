"""Read retained SQLite journals through a private copy, never source recovery writes."""
from __future__ import annotations

import sqlite3
import tempfile
from contextlib import ExitStack, closing, contextmanager
from pathlib import Path

from ar_local_restore_io import copy_stream, database_copy, pinned_reader, regular_identity
from cdr_sqlite_budget import install_progress_deadline


def database_files(path: Path) -> list[Path]:
    """Inventory regular evidence, including sidecars without an optional primary."""
    candidates = [path, *(Path(str(path) + s) for s in ("-wal", "-shm", "-journal"))]
    if any(p.is_symlink() for p in candidates):
        raise ValueError("SQLite source cannot be linked")
    if path.exists() and not path.is_file():
        raise ValueError("SQLite source database is missing or not a regular file")
    if any(p.exists() and not p.is_file() for p in candidates):
        raise ValueError("SQLite source journal is not a regular file")
    return [p for p in candidates if p.is_file()]


def identities(path: Path) -> dict:
    return {p.name: regular_identity(p)
            for p in database_files(path)}


@contextmanager
def database_view(path: Path, *, validate_copy=None):
    """Recover retained journals only in a verified copy, after optional policy checks."""
    files = database_files(path)
    if path not in files:
        raise ValueError("SQLite source database is missing or not a regular file")
    if any(p.is_symlink() for p in files):
        raise ValueError("SQLite source cannot be linked")
    before = identities(path)
    # SQLite reopens pathnames itself. Never let it re-resolve a preserved
    # source after a precheck: pin every inventoried inode and copy from those
    # descriptors, including the no-journal case.
    with ExitStack() as held:
        readers = {source: held.enter_context(pinned_reader(source, expected=before[source.name]))
                   for source in files}
        with tempfile.TemporaryDirectory(prefix="cdr-audit-sqlite-") as temp:
            root = Path(temp)
            hashes = {}
            for source in files:
                target = root / source.name
                hashes[source.name] = copy_stream(*readers[source], target)
            if identities(path) != before:
                raise ValueError("SQLite journal inventory changed while copying")
            if validate_copy is not None:
                validate_copy(root / path.name)
            # Opening this writable private copy allows SQLite to apply a
            # retained WAL or roll back a hot rollback journal safely.
            with database_copy(path, root / path.name), closing(sqlite3.connect(root / path.name)) as db:
                install_progress_deadline(db)
                mode = "no_retained_journal" if len(files) == 1 else "private_copy_recovery"
                yield db, {"source_sha256": hashes[path.name], "journal_mode": mode,
                           "source_files": hashes}
    if identities(path) != before:
        raise ValueError("SQLite source changed during audit")
