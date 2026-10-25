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
    ".git", ".ssh", "__pycache__", "node_modules", "app-payload", "app-payload-latest",
    "dashboard-cache", "netdata",
})
# Derived publication/serving trees. Exact "app-payload" does not match "app-payload-latest".
_DERIVED_DIR_PREFIXES = ("app-payload-",)
EXCLUDE_FILE_NAMES = frozenset({".env", "rclone.conf", "restic.password"})
JOURNAL_UNITS = (
    "ar-local-daily.service",
    "ar-local-ingest-now.service",
    "ar-local-daily-watchdog.service",
    "ar-local-drive-backup.service",
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
        "journal_status": "unavailable",
        "journals_absent": True,
        "raw_banks_absent": True,
        "reason": "permanent ingest gap; no fabricated observation archive",
    }


def _skip_dir(name: str) -> bool:
    if name in EXCLUDE_DIR_NAMES or name.startswith(".env"):
        return True
    return any(name.startswith(prefix) for prefix in _DERIVED_DIR_PREFIXES)


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


# journalctl writes this exact placeholder when the range has no entries.
_JOURNAL_EMPTY_MARKERS = (b"-- No entries --",)
JOURNAL_CLASSIFIER = 3


def _journal_file_status(path: Path) -> str:
    size = path.stat().st_size
    if size == 0:
        return "empty"
    if size > 4096:
        return "captured"
    data = path.read_bytes().strip()
    if not data or data in _JOURNAL_EMPTY_MARKERS:
        return "empty"
    return "captured"


def _overall_journal_status(unit_rows: list[dict]) -> str:
    if not unit_rows or any(row["status"] == "unavailable" for row in unit_rows):
        return "unavailable"
    if any(row["status"] == "captured" for row in unit_rows):
        return "captured"
    return "empty"


def _export_one_journal(unit: str, day: str, destination: Path, start: datetime, end: datetime) -> tuple[Path | None, dict]:
    safe = unit.replace(".", "_")
    path = destination / f"{safe}-{day}.log"
    if path.exists():
        raise ValueError(f"journal export destination already exists: {path}")
    command = [
        "journalctl",
        "--no-pager",
        "--quiet",
        "--output=short-iso-precise",
        f"--unit={unit}",
        f"--since={start.isoformat()}",
        f"--until={end.isoformat()}",
    ]
    try:
        with path.open("x", encoding="utf-8", newline="") as handle:
            completed = subprocess.run(
                command,
                stdout=handle,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
    except OSError as error:
        path.unlink(missing_ok=True)
        return None, {
            "unit": unit,
            "status": "unavailable",
            "bytes": 0,
            "error": str(error)[:200],
        }
    if completed.returncode != 0:
        path.unlink(missing_ok=True)
        detail = (completed.stderr or "").strip().replace("\n", " ")[:200]
        return None, {
            "unit": unit,
            "status": "unavailable",
            "bytes": 0,
            "error": f"exit {completed.returncode}: {detail}",
        }
    status = _journal_file_status(path)
    return path, {"unit": unit, "status": status, "bytes": path.stat().st_size}


def export_journals(day: str, destination: Path, *, units: Iterable[str] = JOURNAL_UNITS) -> dict:
    """Capture Hobart-day journalctl output. Empty ranges stay; failures are unavailable."""
    day = require_day(day)
    destination.mkdir(parents=True, exist_ok=True)
    start = datetime.fromisoformat(f"{day}T00:00:00").replace(tzinfo=DAILY_INGEST_TZ)
    end = start + timedelta(days=1)
    written: list[Path] = []
    unit_rows: list[dict] = []
    for unit in units:
        path, row = _export_one_journal(unit, day, destination, start, end)
        unit_rows.append(row)
        if path is not None:
            written.append(path)
    return {
        "paths": written,
        "journal_status": _overall_journal_status(unit_rows),
        "units": unit_rows,
    }


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


_RECONSTRUCTION_EXPORT_RE = re.compile(r"^banks-\d{4}-\d{2}-\d{2}\.(?:json|xlsx|csv)$")
_SQLITE_NAMES = frozenset({"local-cdr.sqlite", "local-cdr.sqlite-wal", "local-cdr.sqlite-shm"})
_WIRE_BASENAMES = frozenset({
    "product-detail.json",
    "product-id.txt",
    "product-detail.error.txt",
})
_WIRE_DIR_TOKENS = ("_raw-attempt-journals", "attempt-evidence", "_failed_attempts")


def _logical_parts(logical: str) -> list[str]:
    return [part for part in logical.split("/") if part]


def _is_raw_banks_logical_path(logical: str, day: str) -> bool:
    """True for runs/<day>/banks/... files. banks-YYYY-MM-DD.json is not that tree."""
    parts = _logical_parts(logical)
    for index, part in enumerate(parts[:-1]):
        if part == "banks" and index > 0 and parts[index - 1] == day:
            return True
    return False


def _is_wire_logical_path(logical: str, day: str) -> bool:
    """Wire bodies and attempt logs. SQLite and banks-YYYY-MM-DD exports are reconstructions."""
    parts = _logical_parts(logical)
    if not parts:
        return False
    name = parts[-1]
    if name in _SQLITE_NAMES or _RECONSTRUCTION_EXPORT_RE.fullmatch(name):
        return False
    if any(token in part for part in parts for token in _WIRE_DIR_TOKENS):
        return True
    return _is_raw_banks_logical_path(logical, day) and name in _WIRE_BASENAMES


def classify_coverage(day: str, rows: list[dict]) -> str:
    if day in KNOWN_GAPS:
        return "gap"
    paths = [str(row["logical_path"]) for row in rows if not str(row["logical_path"]).startswith("journal/")]
    if any(_is_wire_logical_path(path, day) for path in paths):
        return "wire_raw"
    if any("/_exports/" in path for path in paths):
        return "exports_only"
    return "partial"


def raw_banks_absent(day: str, rows: list[dict]) -> bool:
    return not any(_is_raw_banks_logical_path(str(row["logical_path"]), day) for row in rows)


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
    journal_status = "unavailable"
    journal_units: list[dict] = []
    journal_rows: list[dict] = []
    if journal_dir is not None:
        exported = export_journals(day, journal_dir)
        journal_status = str(exported["journal_status"])
        journal_units = list(exported["units"])
        for path in exported["paths"]:
            row = file_row(data_root, path, guard)
            row["logical_path"] = f"journal/{path.name}"
            journal_rows.append(row)
    rows = [file_row(data_root, path, guard) for path in members]
    rows.extend(journal_rows)
    rows.sort(key=lambda row: row["logical_path"])
    banks_absent = raw_banks_absent(day, rows)
    journals_absent = journal_status == "unavailable" and not journal_rows
    return {
        "schema": SCHEMA,
        "date": day,
        "coverage": classify_coverage(day, rows),
        "journal_status": journal_status,
        "journal_classifier": JOURNAL_CLASSIFIER,
        "journals_absent": journals_absent,
        "raw_banks_absent": banks_absent,
        "journal_units": journal_units,
        "file_count": len(rows),
        "total_bytes": sum(row["size"] for row in rows),
        "files": rows,
    }
