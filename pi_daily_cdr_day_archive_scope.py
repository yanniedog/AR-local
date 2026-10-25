"""Day membership for unencrypted per-calendar-day CDR recovery archives."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Iterator
from zoneinfo import ZoneInfo

from ar_local_ingest_schedule import DAILY_INGEST_TZ

SCHEMA = "ar-local-daily-cdr-day-archive-scope-v1"
FIRST_DAY = date(2026, 5, 13)
KNOWN_GAPS = frozenset({"2026-05-14", "2026-06-26"})
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EXCLUDE_DIR_NAMES = frozenset({
    ".git", ".ssh", "__pycache__", "node_modules", "app-payload", "dashboard-cache", "netdata",
})
EXCLUDE_FILE_NAMES = frozenset({".env", "rclone.conf", "restic.password"})
JOURNAL_UNITS = (
    "ar-local-daily.service",
    "ar-local-ingest-now.service",
    "ar-local-daily-watchdog.service",
    "ar-local-drive-backup.service",
    "ar-local-drive-backup-queue.service",
)
STATE_DAY_SUFFIXES = (".done.json", ".integrity.json")
OPTIONAL_TOP = ("logs", "predeploy", "runs-archive", ".daily-raw-stage")


def require_day(value: str) -> str:
    if not DAY_RE.fullmatch(value):
        raise ValueError(f"observation date must be YYYY-MM-DD: {value}")
    parsed = date.fromisoformat(value)
    if parsed < FIRST_DAY:
        raise ValueError(f"date {value} is before first retained ingest day {FIRST_DAY.isoformat()}")
    return value


def hobart_today(now: datetime | None = None) -> date:
    current = now or datetime.now(tz=DAILY_INGEST_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=DAILY_INGEST_TZ)
    return current.astimezone(DAILY_INGEST_TZ).date()


def iter_backfill_days(*, through: date | None = None) -> Iterator[str]:
    end = through or (hobart_today() - timedelta(days=1))
    if end < FIRST_DAY:
        return
    cursor = FIRST_DAY
    while cursor <= end:
        yield cursor.isoformat()
        cursor += timedelta(days=1)


def gap_record(day: str) -> dict:
    day = require_day(day)
    if day not in KNOWN_GAPS:
        raise ValueError(f"{day} is not a registered permanent gap")
    status = "known_gap" if day == "2026-05-14" else "unclassified_gap"
    return {
        "schema": SCHEMA,
        "date": day,
        "status": status,
        "coverage": "gap",
        "reason": "permanent ingest gap; no fabricated observation archive",
    }


def _skip_dir(name: str) -> bool:
    return name in EXCLUDE_DIR_NAMES or name.startswith(".env")


def _skip_file(name: str) -> bool:
    return name in EXCLUDE_FILE_NAMES or name.startswith(".env")


def _walk_files(root: Path) -> Iterator[Path]:
    if not root.exists():
        return
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"included root is not a real directory: {root}")

    def _onerror(error: OSError) -> None:
        raise RuntimeError(f"unreadable archive source during walk: {error}") from error

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=_onerror):
        dirnames[:] = sorted(name for name in dirnames if not _skip_dir(name))
        base = Path(dirpath)
        if base.is_symlink():
            continue
        for name in sorted(filenames):
            if _skip_file(name):
                continue
            path = base / name
            if path.is_symlink():
                continue
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                continue
            yield path


def _day_in_name(path: Path, day: str) -> bool:
    text = path.as_posix()
    return day in text


def collect_run_files(data_root: Path, day: str) -> list[Path]:
    run = data_root / "runs" / day
    return list(_walk_files(run))


def collect_state_files(data_root: Path, day: str) -> list[Path]:
    state = data_root / "state"
    if not state.is_dir() or state.is_symlink():
        return []
    found: list[Path] = []
    for suffix in STATE_DAY_SUFFIXES:
        path = state / f"{day}{suffix}"
        if path.is_file() and not path.is_symlink():
            found.append(path)
    for relative in (
        PurePosixPath("export-contracts-v2") / day,
        PurePosixPath("ledger-v2") / "events" / day,
        PurePosixPath("observation-selections-v1") / day,
    ):
        found.extend(_walk_files(state / relative))
    # Revision / repair markers keyed by date prefix.
    for path in state.iterdir():
        if path.is_symlink() or not path.is_file():
            continue
        name = path.name
        if name.startswith(f"{day}.") and name.endswith(".json"):
            found.append(path)
    return sorted(set(found), key=lambda item: item.as_posix())


def collect_optional_day_files(data_root: Path, day: str) -> list[Path]:
    found: list[Path] = []
    for name in OPTIONAL_TOP:
        root = data_root / name
        if not root.exists():
            continue
        if root.is_symlink() or not root.is_dir():
            raise ValueError(f"optional data path is not a real directory: {root}")
        if name == "runs-archive":
            direct = root / day
            if direct.exists():
                found.extend(_walk_files(direct))
            for path in _walk_files(root):
                if _day_in_name(path.relative_to(root), day):
                    found.append(path)
            continue
        if name == "logs":
            for path in _walk_files(root):
                if day in path.name or day in path.as_posix():
                    found.append(path)
            continue
        # predeploy / .daily-raw-stage: keep day-attributable paths only
        for path in _walk_files(root):
            if _day_in_name(path.relative_to(root), day):
                found.append(path)
    return sorted(set(found), key=lambda item: item.as_posix())


def collect_control_files(data_root: Path) -> list[Path]:
    """Global binding pointers needed beside per-day archives."""
    state = data_root / "state"
    if not state.is_dir() or state.is_symlink():
        return []
    candidates = [
        state / "ledger-v2" / "head.json",
        state / "observation-pointers-v2" / "latest-observation.json",
        state / "ingest-status.json",
    ]
    found = [path for path in candidates if path.is_file() and not path.is_symlink()]
    pointers = state / "observation-pointers-v2"
    if pointers.is_dir() and not pointers.is_symlink():
        found.extend(_walk_files(pointers))
    return sorted(set(found), key=lambda item: item.as_posix())


def export_journals(day: str, destination: Path, *, units: Iterable[str] = JOURNAL_UNITS) -> list[Path]:
    """Capture journalctl for AR-local units covering the Hobart calendar day."""
    day = require_day(day)
    destination.mkdir(parents=True, exist_ok=True)
    start = datetime.fromisoformat(f"{day}T00:00:00").replace(tzinfo=DAILY_INGEST_TZ)
    end = start + timedelta(days=1)
    written: list[Path] = []
    for unit in units:
        safe = unit.replace(".", "_")
        path = destination / f"{safe}-{day}.log"
        if path.exists():
            raise ValueError(f"journal export destination already exists: {path}")
        command = [
            "journalctl",
            "--no-pager",
            "--output=short-iso-precise",
            f"--unit={unit}",
            f"--since={start.isoformat()}",
            f"--until={end.isoformat()}",
        ]
        with path.open("xb") as handle:
            completed = subprocess.run(
                command,
                stdout=handle,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        if completed.returncode != 0:
            # journalctl returns 0 on success (including empty ranges). Nonzero means
            # failure (permissions, missing journal, etc.) — never archive that as PASS.
            path.unlink(missing_ok=True)
            raise RuntimeError(
                f"journalctl failed for {unit} on {day}: exit {completed.returncode}: {completed.stderr[:500]}"
            )
        written.append(path)
    return written


def logical_path(data_root: Path, path: Path) -> str:
    try:
        relative = path.resolve().relative_to(data_root.resolve())
        return (PurePosixPath("data") / PurePosixPath(relative.as_posix())).as_posix()
    except ValueError:
        # Journal exports staged outside data root.
        return (PurePosixPath("journal") / path.name).as_posix()


def file_row(data_root: Path, path: Path, guard: Callable[[], None] = lambda: None) -> dict:
    guard()
    info = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            guard()
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return {
        "logical_path": logical_path(data_root, path),
        "source_path": str(path),
        "sha256": digest.hexdigest(),
        "size": info.st_size,
        "mode": oct(stat.S_IMODE(info.st_mode)),
        "uid": info.st_uid,
        "gid": info.st_gid,
        "mtime_ns": info.st_mtime_ns,
    }


def classify_coverage(day: str, rows: list[dict]) -> str:
    if day in KNOWN_GAPS:
        return "gap"
    paths = {row["logical_path"] for row in rows}
    has_exports = any("/_exports/" in path or path.endswith("/_exports") for path in paths)
    has_wire = any(
        "attempt-evidence" in path or "raw-attempt-journals" in path or "/_raw-attempt-journals" in path
        for path in paths
    )
    has_banks = any("/banks/" in path for path in paths)
    if has_wire and (has_exports or has_banks):
        return "wire_raw"
    if has_exports:
        return "exports_only"
    if paths:
        return "partial"
    return "partial"


def build_day_inventory(
    data_root: Path,
    day: str,
    *,
    journal_dir: Path | None = None,
    guard: Callable[[], None] = lambda: None,
) -> dict:
    day = require_day(day)
    if day in KNOWN_GAPS:
        return gap_record(day)
    members = collect_run_files(data_root, day)
    members.extend(collect_state_files(data_root, day))
    members.extend(collect_optional_day_files(data_root, day))
    journal_rows: list[dict] = []
    if journal_dir is not None:
        for path in export_journals(day, journal_dir):
            row = file_row(data_root, path, guard)
            row["logical_path"] = f"journal/{path.name}"
            journal_rows.append(row)
    rows = [file_row(data_root, path, guard) for path in members]
    rows.extend(journal_rows)
    rows.sort(key=lambda row: row["logical_path"])
    coverage = classify_coverage(day, rows)
    return {
        "schema": SCHEMA,
        "date": day,
        "coverage": coverage,
        "file_count": len(rows),
        "total_bytes": sum(row["size"] for row in rows),
        "files": rows,
    }
