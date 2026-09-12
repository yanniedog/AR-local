"""Consistent, explicitly scoped source inventory for Pi-owned Drive backups."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import time
from contextlib import closing
from pathlib import Path
from typing import Callable

from ar_local_backup_scope import build_data_scope
from ar_local_operation_lock import production_lock
from pi_laptop_backup_source import canonical_json_bytes, validate_archive_path

SCHEMA = "ar-local-drive-backup-v1"
DB_SUFFIXES = {".sqlite", ".sqlite3", ".db"}
EXCLUDED_NAMES = {".git", ".ssh", "__pycache__", "node_modules", "netdata", "rclone.conf"}


def digest(path: Path, guard: Callable[[], None] = lambda: None) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            guard()
            value.update(block)
    return value.hexdigest()


def regular(path: Path) -> os.stat_result:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_nlink != 1:
        raise ValueError(f"unsafe backup source: {path}")
    return info


def fingerprint(path: Path) -> list[int]:
    info = regular(path)
    return [info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino, info.st_dev]


def excluded(path: Path) -> bool:
    for name in path.parts:
        low = name.lower()
        if (low in EXCLUDED_NAMES or low.startswith(".env") or low.endswith((".env", ".key", ".pem", ".img"))
                or any(word in low for word in ("credential", "password", "oauth", "bearer_token"))):
            return True
    return path.name.endswith((".lock", ".tmp", ".partial", "-wal", "-shm", "-journal"))


def canonical_directory(path: Path) -> Path:
    if not path.is_absolute() or path.is_symlink() or path != path.resolve(strict=True) or not path.is_dir():
        raise ValueError(f"expected canonical real directory: {path}")
    return path


def validate_layout(data: Path, spool: Path, controls: list[Path]) -> None:
    canonical_directory(data)
    if not spool.is_absolute() or spool.is_symlink() or spool != spool.resolve():
        raise ValueError("spool must be an absolute canonical path")
    if spool == data or data in spool.parents or spool in data.parents:
        raise ValueError("backup spool must be separate from source data")
    for control in controls:
        if control != control.resolve(strict=True) or excluded(control) or not control.is_file():
            raise ValueError("control source must be an explicit non-secret regular file")
        regular(control)
        if control == spool or spool in control.parents:
            raise ValueError("control source cannot be inside spool")


def sqlite_checks(path: Path) -> dict:
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        integrity = [row[0] for row in db.execute("PRAGMA integrity_check")]
        foreign_keys = db.execute("PRAGMA foreign_key_check").fetchmany(1)
        tables = sorted(row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    if integrity != ["ok"] or foreign_keys:
        raise ValueError(f"SQLite restore integrity failed: {path.name}")
    return {"integrity_check": "ok", "foreign_key_check": "ok", "tables": tables}


def sqlite_snapshot(source: Path, target: Path, guard: Callable[[], None],
                    originals: Path | None = None) -> list[tuple[Path, Path]]:
    regular(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Even a mode=ro SQLite connection may create a missing shared-memory file
    # beside a WAL database. Open only a frozen private copy, so legacy retained
    # WAL files are incorporated without writing anywhere in production runs.
    components = [source, *[Path(str(source) + suffix) for suffix in ("-wal", "-journal")
                           if Path(str(source) + suffix).exists()]]
    identities = {path: fingerprint(path) for path in components}
    retained = []
    if originals is not None:
        for component in components:
            original = originals.parent / component.name
            _copy(component, original, guard)
            retained.append((component, original))
    with tempfile.TemporaryDirectory(prefix="sqlite-input-", dir=target.parent) as scratch:
        private = Path(scratch) / source.name
        for component in components:
            _copy(component, Path(scratch) / component.name, guard)
        if any(fingerprint(path) != identity for path, identity in identities.items()):
            raise RuntimeError("SQLite components changed during freeze")
        present = {Path(str(source) + suffix) for suffix in ("-wal", "-journal")
                   if Path(str(source) + suffix).exists()}
        if present != set(components[1:]):
            raise RuntimeError("SQLite journal membership changed during freeze")
        with closing(sqlite3.connect(private.as_uri() + "?mode=rw", uri=True, timeout=5)) as src:
            with closing(sqlite3.connect(target)) as dst:
                src.backup(dst, pages=256, progress=lambda *_: guard(), sleep=0.05)
    with closing(sqlite3.connect(target.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("SQLite snapshot failed quick_check")
    return retained


def _copy(source: Path, target: Path, guard: Callable[[], None]) -> None:
    before = fingerprint(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, target.open("xb") as dst:
        while block := src.read(1024 * 1024):
            guard()
            dst.write(block)
        dst.flush()
        os.fsync(dst.fileno())
    shutil.copystat(source, target)
    if before != fingerprint(source) or digest(source, guard) != digest(target, guard):
        raise RuntimeError(f"source changed during freeze: {source}")


def _is_database(path: Path) -> bool:
    if path.suffix.lower() in DB_SUFFIXES:
        return True
    with path.open("rb") as stream:
        return stream.read(16) == b"SQLite format 3\x00"


def _direct_run_file(relative: Path, source: Path) -> bool:
    # Finalized run namespaces are immutable by producer contract. Restic gets
    # their original bytes; state, logs and predeploy are frozen private copies.
    return (relative.parts[0] in {"runs", "runs-archive"}
            and not any(Path(str(source) + suffix).exists() for suffix in ("-wal", "-journal")))


def freeze(data: Path, stage: Path, *, controls: list[Path], guard: Callable[[], None],
           prior: dict | None = None, max_freeze_seconds: int = 1200) -> dict:
    """Freeze mutable bytes under ingest lock; immutable files remain direct inputs.

    Cached hashes require the complete POSIX file identity, including ctime.
    Restore proofs re-hash actual downloaded bytes. Initial hashes read every file.
    """
    started = time.monotonic()
    def check() -> None:
        guard()
        if time.monotonic() - started > max_freeze_seconds:
            raise RuntimeError("source freeze deadline exceeded")
    previous = {row["logical_path"]: row for row in (prior or {}).get("files", [])}
    seen: dict[str, str] = {}
    result = {"schema": SCHEMA, "files": [], "excluded": []}
    with production_lock(data / "state/daily-ingest.lock", "drive-backup-freeze"):
        check()
        scope = build_data_scope(data)
        result["scope"] = scope.manifest()
        sources = []
        for root in scope.included:
            for path in sorted(root.rglob("*")):
                check()
                if path.is_symlink():
                    raise ValueError(f"symlink in backup scope: {path}")
                if path.is_dir():
                    continue
                regular(path)
                relative = path.relative_to(data)
                if excluded(relative):
                    result["excluded"].append(relative.as_posix())
                    continue
                sources.append((path, "data/" + relative.as_posix(), relative))
        for index, path in enumerate(controls):
            sources.append((path, f"control/{index:03d}-{path.name}", Path("control") / path.name))
        for source, logical, relative in sources:
            check()
            validate_archive_path(logical, seen)
            database = _is_database(source)
            direct = _direct_run_file(relative, source)
            target = source if direct else stage / logical
            source_identity = fingerprint(source)
            if not direct:
                if database:
                    original_root = stage / "sqlite-original" / logical
                    originals = sqlite_snapshot(source, target, check, original_root)
                    for component, original in originals:
                        original_logical = "sqlite-original/" + logical + component.name[len(source.name):]
                        validate_archive_path(original_logical, seen)
                        result["files"].append({"logical_path": original_logical,
                            "backup_path": original.as_posix(), "source_path": component.as_posix(),
                            "source_identity": fingerprint(component), "size": original.stat().st_size,
                            "sha256": digest(original, check), "direct": False, "sqlite": False,
                            "sqlite_original": True, "mode": oct(stat.S_IMODE(component.stat().st_mode)),
                            "uid": component.stat().st_uid, "gid": component.stat().st_gid})
                else:
                    _copy(source, target, check)
            cached = previous.get(logical, {})
            reusable = (direct and os.name == "posix" and cached.get("source_identity") == source_identity)
            sha = cached["sha256"] if reusable else digest(target, check)
            if direct and source_identity != fingerprint(source):
                raise RuntimeError(f"immutable source changed during inventory: {source}")
            result["files"].append({"logical_path": logical, "backup_path": target.as_posix(),
                                    "source_path": source.as_posix(), "source_identity": source_identity,
                                    "size": target.stat().st_size, "sha256": sha,
                                    "direct": direct, "sqlite": database,
                                    "mode": oct(stat.S_IMODE(source.stat().st_mode)),
                                    "uid": source.stat().st_uid, "gid": source.stat().st_gid})
    result["files"].sort(key=lambda row: row["logical_path"])
    identity = [{key: row[key] for key in ("logical_path", "sha256", "size")} for row in result["files"]]
    result["content_sha256"] = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    return result


def verify_direct_sources(manifest: dict) -> None:
    for row in manifest["files"]:
        if row["direct"] and fingerprint(Path(row["source_path"])) != row["source_identity"]:
            raise RuntimeError("immutable source changed during upload; snapshot is not accepted")


def restore_relative(path: str) -> Path:
    # Restic stores absolute Unix paths without the first slash on restore.
    # Windows drive roots are stored as /C/... by Restic.
    value = path.replace("\\", "/")
    if len(value) > 2 and value[1] == ":":
        value = value[0] + value[2:]
    parts = Path(value.lstrip("/"))
    if ".." in parts.parts or parts.is_absolute() or "\n" in value or "\r" in value:
        raise ValueError("unsafe restore path")
    return parts


def verify_restore(root: Path, rows: list[dict]) -> dict:
    checks = []
    for row in rows:
        path = root / restore_relative(row["backup_path"])
        regular(path)
        if path.resolve() != path or path.stat().st_size != row["size"] or digest(path) != row["sha256"]:
            raise ValueError(f"restored bytes differ: {row['logical_path']}")
        if row["sqlite"]:
            checks.append({"path": row["logical_path"], **sqlite_checks(path)})
    return {"result": "PASS", "files_verified": len(rows), "sqlite": checks,
            "published_identity_files": [row["logical_path"] for row in rows
                if any(word in row["logical_path"] for word in ("manifest", "pointer", "publication", "ledger"))]}
