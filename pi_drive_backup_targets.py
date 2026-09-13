"""Compact Restic targets without broadening the frozen manifest's file set.

Only a completely selected directory can replace its descendants. The private
SQLite index bounds Python memory independently of the retained file count.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import stat
import time

from pi_drive_backup_source import canonical_directory, regular


def directory_identity(path: Path) -> list[int]:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or path.is_symlink():
        raise ValueError("backup target directory is not a real directory")
    return [info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns]


def boundary(row: dict, stage: Path, data: Path) -> Path:
    path = Path(row["backup_path"])
    if not path.is_absolute() or "\x00" in str(path) or path != path.resolve(strict=True):
        raise ValueError("noncanonical manifest backup target")
    if row.get("direct") is True:
        if row.get("source_path") != path.as_posix():
            raise ValueError("direct backup target differs from source")
        for name in ("runs", "runs-archive"):
            root = data / name
            if root in path.parents:
                return root
    elif stage in path.parents and path.relative_to(stage).parts[0] in {"data", "control", "sqlite-original"}:
        return stage
    raise ValueError("manifest target is outside immutable or private source scope")


class Targets:
    def __init__(self, stage: Path, guard):
        self.guard = guard
        self.path = stage / "files.raw"
        index = stage / "targets.sqlite"
        # The index is exclusive, private work; no existing database is opened.
        with index.open("xb"):
            pass
        self.db = sqlite3.connect(index)
        self.db.execute("PRAGMA cache_size=-2048")
        self.db.execute("PRAGMA temp_store=FILE")
        self.db.execute("""CREATE TABLE nodes (
            path TEXT PRIMARY KEY, parent TEXT NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('file','dir')),
            complete INTEGER NOT NULL CHECK(complete IN (0,1)), identity TEXT
        ) WITHOUT ROWID""")
        # Child membership and missing-child counts are the hot lookup paths.
        self.db.execute("CREATE INDEX nodes_parent ON nodes(parent)")
        self.file_count = self.source_bytes = self.target_count = 0

    def add(self, row: dict, stage: Path, data: Path) -> None:
        path = Path(row["backup_path"])
        root = boundary(row, stage, data)
        regular(path)
        self.db.execute("INSERT INTO nodes VALUES(?,?,'file',1,NULL)",
                        (path.as_posix(), path.parent.as_posix()))
        parent = path.parent
        while parent != root:
            inserted = self.db.execute("INSERT OR IGNORE INTO nodes VALUES(?,?,'dir',0,NULL)",
                                      (parent.as_posix(), parent.parent.as_posix()))
            if not inserted.rowcount:
                kind = self.db.execute("SELECT kind FROM nodes WHERE path=?", (parent.as_posix(),)).fetchone()
                if kind != ("dir",):
                    raise ValueError("manifest file/directory collision")
                break
            parent = parent.parent
        self.file_count += 1
        self.source_bytes += row["size"]
        if self.file_count % 256 == 0:
            self.guard()
            self.db.commit()

    def classify(self, path: Path) -> None:
        self.guard()
        before = directory_identity(path)
        complete, found = True, 0
        with os.scandir(path) as entries:
            for entry in entries:
                self.guard()
                name = Path(entry.path).as_posix()
                expected = self.db.execute("SELECT kind,complete FROM nodes WHERE path=?", (name,)).fetchone()
                if expected is None:
                    # Do not inspect/traverse unselected or secret namespaces.
                    complete = False
                    continue
                found += 1
                if entry.is_symlink():
                    raise ValueError("symlink replaced a selected backup target")
                if expected[0] == "file":
                    regular(Path(entry.path))
                elif not entry.is_dir(follow_symlinks=False):
                    raise ValueError("selected backup directory changed type")
                complete = complete and bool(expected[1])
        count = self.db.execute("SELECT count(*) FROM nodes WHERE parent=?", (path.as_posix(),)).fetchone()[0]
        if found != count or before != directory_identity(path):
            raise RuntimeError("backup directory membership changed during planning")
        self.db.execute("UPDATE nodes SET complete=?,identity=? WHERE path=?",
                        (int(complete), json.dumps(before), path.as_posix()))

    def prepare(self, manifest: dict, stage: Path, data: Path, manifest_path: Path) -> None:
        started, guard = time.monotonic(), self.guard
        def planning_guard():
            guard()
            if time.monotonic() - started > 1200:
                raise RuntimeError("backup target planning deadline exceeded")
        self.guard = planning_guard
        canonical_directory(stage)
        canonical_directory(data)
        for row in manifest["files"]:
            self.add(row, stage, data)
        self.db.commit()
        # Children precede parents; the ordering is performed by SQLite on disk.
        for (name,) in self.db.execute("SELECT path FROM nodes WHERE kind='dir' ORDER BY length(path) DESC"):
            self.classify(Path(name))
        self.db.commit()
        with self.path.open("xb") as output:
            for (name,) in self.db.execute("""SELECT n.path FROM nodes n
                LEFT JOIN nodes p ON p.path=n.parent
                WHERE n.complete=1 AND coalesce(p.complete,0)=0 ORDER BY n.path"""):
                self.guard()
                output.write(name.encode("utf-8") + b"\x00")
                self.target_count += 1
            regular(manifest_path)
            output.write(manifest_path.as_posix().encode("utf-8") + b"\x00")
        self.file_count += 1
        self.source_bytes += manifest_path.stat().st_size
        self.target_count += 1
        self.verify()
        self.guard = guard

    def verify(self) -> None:
        for name, identity in self.db.execute("SELECT path,identity FROM nodes WHERE kind='dir' AND complete=1"):
            self.guard()
            if directory_identity(Path(name)) != json.loads(identity):
                raise RuntimeError("selected backup directory membership changed")

    def check_summary(self, summary: dict) -> None:
        if (type(summary.get("total_files_processed")) is not int
                or type(summary.get("total_bytes_processed")) is not int
                or summary["total_files_processed"] != self.file_count
                or summary["total_bytes_processed"] != self.source_bytes):
            raise ValueError("Restic file/byte totals differ from the frozen manifest")


@contextmanager
def backup_targets(manifest: dict, stage: Path, data: Path, manifest_path: Path, guard):
    targets = Targets(stage, guard)
    try:
        targets.prepare(manifest, stage, data, manifest_path)
        yield targets
    finally:
        targets.db.close()
