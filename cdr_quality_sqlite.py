"""Read retained SQLite journals through a private copy, never source recovery writes."""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
from contextlib import closing, contextmanager
from pathlib import Path

from cdr_export_contract import hash_file


def database_files(path: Path) -> list[Path]:
    return [p for p in [path, *(Path(str(path) + s) for s in ("-wal", "-shm", "-journal"))] if p.is_file()]


def identities(path: Path) -> dict:
    return {p.name: [p.stat().st_size, p.stat().st_mtime_ns, p.stat().st_ctime_ns, p.stat().st_ino]
            for p in database_files(path)}


@contextmanager
def database_view(path: Path):
    """Legacy finalized partitions may retain WAL. Recover only a verified copy."""
    files = database_files(path)
    if any(p.is_symlink() for p in files):
        raise ValueError("SQLite source cannot be linked")
    before = identities(path)
    if len(files) == 1:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
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
            # Opening this writable private copy allows SQLite to apply a
            # retained WAL or roll back a hot rollback journal safely.
            with closing(sqlite3.connect(root / path.name)) as db:
                yield db, {"source_sha256": hashes[path.name], "journal_mode": "private_copy_recovery",
                           "source_files": hashes}
    if identities(path) != before:
        raise ValueError("SQLite source changed during audit")
