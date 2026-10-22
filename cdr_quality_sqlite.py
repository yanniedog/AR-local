"""Read retained SQLite journals through a private copy, never source recovery writes."""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
from contextlib import closing, contextmanager
from pathlib import Path

from cdr_export_contract import hash_file
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
    return {p.name: [p.stat().st_size, p.stat().st_mtime_ns, p.stat().st_ctime_ns, p.stat().st_ino]
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
    if len(files) == 1:
        if validate_copy is not None:
            validate_copy(path)
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            install_progress_deadline(db)
            yield db, {"source_sha256": hash_file(path), "journal_mode": "no_retained_journal"}
    else:
        with tempfile.TemporaryDirectory(prefix="cdr-audit-sqlite-") as temp:
            root = Path(temp)
            hashes = {}
            for source in files:
                target = root / source.name
                shutil.copyfile(source, target)
                hashes[source.name] = hash_file(target)
                if hash_file(source) != hashes[source.name]:
                    raise ValueError("SQLite source changed while copying")
            if identities(path) != before:
                raise ValueError("SQLite journal inventory changed while copying")
            if validate_copy is not None:
                validate_copy(root / path.name)
            # Opening this writable private copy allows SQLite to apply a
            # retained WAL or roll back a hot rollback journal safely.
            with closing(sqlite3.connect(root / path.name)) as db:
                install_progress_deadline(db)
                yield db, {"source_sha256": hashes[path.name], "journal_mode": "private_copy_recovery",
                           "source_files": hashes}
    if identities(path) != before:
        raise ValueError("SQLite source changed during audit")
