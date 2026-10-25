"""Sequential unencrypted per-day CDR archives to Google Drive.

Create highly compressed tar.zst for one Hobart calendar day, upload to the
dedicated Drive subdirectory, verify by re-download+sha256, then delete ONLY the
local compressed artifacts. Source CDR trees are never deleted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import zstandard

from ar_local_ingest_schedule import DAILY_INGEST_TZ
from cdr_file_lock import FileLock
from pi_drive_backup_hold import Blocked, require_writes_allowed
from pi_daily_cdr_day_archive_scope import (
    FIRST_DAY,
    KNOWN_GAPS,
    SCHEMA as SCOPE_SCHEMA,
    JOURNAL_CLASSIFIER,
    build_day_inventory,
    collect_control_files,
    file_row,
    gap_record,
    hobart_today,
    iter_backfill_days,
    require_day,
)
from pi_daily_cdr_day_archive_transport import (
    FOLDER_NAME,
    DayArchiveRclone,
    DayArchiveTransportError,
    sha256_file,
    verify_uploaded_archive,
)

SCHEMA = "ar-local-daily-cdr-raw-record-v1"
SERIES = FOLDER_NAME
COMPRESSION = "zstd-lossless-no-encryption-level-19"
DEFAULT_DATA_ROOT = Path("/srv/ar-local/data")
DEFAULT_SPOOL = Path("/var/lib/ar-local-day-archives")
DEFAULT_DRIVE_BACKUP_SPOOL = Path("/var/lib/ar-local-drive-backup")
DEFAULT_RCLONE = Path(
    "/var/lib/ar-local-drive-backup/credentials/dedicated-20260913-ready3/rclone-verified-ready3.conf"
)
DEFAULT_REMOTE = (
    "ar_local_drive_dedicated_20260913:"
    "AR-local Pi Backups Dedicated 20260913-326040d72fbc405ea2e9b2dacea6b412/"
    + FOLDER_NAME
)
QUIET_START = (0, 30)
QUIET_END = (2, 0)


class DayArchiveError(RuntimeError):
    """Abort the day; do not advance progress or unlink archives."""


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f"{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def require_day_archive_writes_allowed(spool: Path) -> None:
    """Honor the global Drive write hold for direct CLI and service invocations."""
    try:
        require_writes_allowed(Path(spool))
        backup_spool = Path(
            os.environ.get("AR_LOCAL_DRIVE_BACKUP_SPOOL", str(DEFAULT_DRIVE_BACKUP_SPOOL))
        )
        if backup_spool.resolve() != Path(spool).resolve():
            require_writes_allowed(backup_spool)
    except Blocked as error:
        raise DayArchiveError(str(error)) from error


def _append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def in_quiet_window(now: datetime | None = None) -> bool:
    current = now or datetime.now(tz=DAILY_INGEST_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=DAILY_INGEST_TZ)
    local = current.astimezone(DAILY_INGEST_TZ)
    minutes = local.hour * 60 + local.minute
    start = QUIET_START[0] * 60 + QUIET_START[1]
    end = QUIET_END[0] * 60 + QUIET_END[1]
    return start <= minutes < end


def quiet_window_guard() -> None:
    """Abort mid-job if the Hobart quiet window begins after admission."""
    if in_quiet_window():
        raise DayArchiveError(
            "day-archive work entered 00:30–02:00 Australia/Hobart quiet window"
        )


def progress_dir(spool: Path) -> Path:
    """App-writable child under a root-owned spool parent."""
    return Path(spool) / "meta"


def progress_path(spool: Path) -> Path:
    """New-series ledger. Legacy progress.jsonl PASS rows are a different Drive folder."""
    return progress_dir(spool) / "raw-progress.jsonl"


def load_progress(spool: Path) -> dict[str, dict]:
    result: dict[str, dict] = {}
    path = progress_path(spool)
    if not path.is_file():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        day = row.get("date")
        if isinstance(day, str):
            result[day] = row
    return result


def record_progress(spool: Path, row: dict) -> None:
    meta = progress_dir(spool)
    meta.mkdir(parents=True, exist_ok=True)
    _append_jsonl(progress_path(spool), row)
    _atomic_json(meta / "raw-latest.json", row)


def request_day_archive(day: str, *, spool: Path | None = None, reason: str = "post-ingest") -> Path:
    """Durable enqueue used after successful daily finalize."""
    day = require_day(day)
    root = Path(spool or os.environ.get("AR_LOCAL_DAY_ARCHIVE_SPOOL", DEFAULT_SPOOL))
    requests = root / "requests"
    requests.mkdir(parents=True, exist_ok=True)
    marker = requests / f"{day}.json"
    if marker.exists():
        return marker
    payload = {
        "schema": SCHEMA,
        "date": day,
        "requested_at": datetime.now(tz=DAILY_INGEST_TZ).isoformat(),
        "reason": reason[:200],
    }
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, marker)
    return marker


class _InventoryHashReader:
    """Stream file bytes into tar while verifying size and inventoried SHA-256."""

    def __init__(self, handle, *, expected_size: int, expected_sha256: str, source: Path):
        self._handle = handle
        self._expected_size = expected_size
        self._expected_sha256 = expected_sha256
        self._source = source
        self._hasher = hashlib.sha256()
        self._remaining = expected_size
        self.verified = False

    def read(self, size: int = -1) -> bytes:
        if self.verified:
            return b""
        if size < 0 or size > self._remaining:
            size = self._remaining
        chunk = self._handle.read(size) if size else b""
        if len(chunk) != size:
            raise DayArchiveError(
                f"archive member truncated since inventory: {self._source}"
            )
        if chunk:
            self._hasher.update(chunk)
            self._remaining -= len(chunk)
        if self._remaining == 0 and not self.verified:
            self.verified = True
            digest = self._hasher.hexdigest()
            if digest != self._expected_sha256:
                raise DayArchiveError(
                    f"archive member changed since inventory: {self._source}"
                )
        return chunk


def _build_tar_zst(archive: Path, rows: list[dict], manifest: dict, guard: Callable[[], None]) -> str:
    if archive.exists():
        raise DayArchiveError(f"archive already exists: {archive}")
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with archive.open("xb") as output:
        compressor = zstandard.ZstdCompressor(
            level=19, threads=0, write_checksum=True, write_content_size=False
        )
        with compressor.stream_writer(output, closefd=False) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as tar:
                info = tarfile.TarInfo("MANIFEST.json")
                info.size = len(manifest_bytes)
                info.mode = 0o600
                info.mtime = int(time.time())
                tar.addfile(info, fileobj=__import__("io").BytesIO(manifest_bytes))
                for row in rows:
                    guard()
                    source = Path(row["source_path"])
                    if not source.is_file() or source.is_symlink():
                        raise DayArchiveError(f"missing archive member: {source}")
                    size = int(row["size"])
                    if source.stat().st_size != size:
                        raise DayArchiveError(
                            f"archive member size changed since inventory: {source}"
                        )
                    member = tarfile.TarInfo(row["logical_path"])
                    member.size = size
                    member.mode = int(row["mode"], 8)
                    member.uid = row["uid"]
                    member.gid = row["gid"]
                    ns = row["mtime_ns"]
                    member.mtime = ns // 10**9
                    magnitude = abs(ns)
                    member.pax_headers = {
                        "mtime": f'{"-" if ns < 0 else ""}{magnitude // 10**9}.{magnitude % 10**9:09d}'
                    }
                    expected_sha = str(row["sha256"])
                    if size == 0:
                        if hashlib.sha256().hexdigest() != expected_sha:
                            raise DayArchiveError(
                                f"archive member changed since inventory: {source}"
                            )
                        tar.addfile(member, __import__("io").BytesIO(b""))
                    else:
                        with source.open("rb") as handle:
                            reader = _InventoryHashReader(
                                handle,
                                expected_size=size,
                                expected_sha256=expected_sha,
                                source=source,
                            )
                            tar.addfile(member, reader)
                            if not reader.verified:
                                raise DayArchiveError(
                                    f"archive member not fully verified: {source}"
                                )
    return sha256_file(archive, guard)


def build_day_archive(
    data_root: Path,
    day: str,
    work: Path,
    *,
    guard: Callable[[], None] = lambda: None,
    include_journals: bool = True,
) -> dict:
    day = require_day(day)
    work.mkdir(parents=True, exist_ok=True)
    if day in KNOWN_GAPS:
        gap = gap_record(day)
        gap["series"] = SERIES
        gap_path = work / f"{day}.GAP.json"
        gap_path.write_text(json.dumps(gap, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        digest = sha256_file(gap_path, guard)
        return {
            "schema": SCHEMA,
            "series": SERIES,
            "date": day,
            "kind": "gap",
            "coverage": "gap",
            "journal_status": gap.get("journal_status"),
            "journals_absent": gap.get("journals_absent"),
            "raw_banks_absent": gap.get("raw_banks_absent"),
            "local_path": str(gap_path),
            "remote_name": f"{day}.GAP.json",
            "sha256": digest,
            "bytes": gap_path.stat().st_size,
            "manifest": gap,
        }

    journal_dir = work / "journal-exports" if include_journals else None
    inventory = build_day_inventory(data_root, day, journal_dir=journal_dir, guard=guard)
    rows = list(inventory["files"])
    primary_rows = [row for row in rows if not str(row["logical_path"]).startswith("journal/")]
    if not primary_rows:
        raise DayArchiveError(
            f"no recoverable primary files found for {day} (journal exports alone are insufficient)"
        )
    manifest = {
        "schema": SCHEMA,
        "series": SERIES,
        "scope_schema": SCOPE_SCHEMA,
        "date": day,
        "coverage": inventory["coverage"],
        "journal_status": inventory.get("journal_status", "unavailable"),
        "journals_absent": bool(inventory.get("journals_absent", True)),
        "raw_banks_absent": bool(inventory.get("raw_banks_absent", True)),
        "journal_units": inventory.get("journal_units", []),
        "compression": COMPRESSION,
        "include_journals": bool(include_journals),
        "journal_classifier": inventory.get("journal_classifier", JOURNAL_CLASSIFIER),
        "file_count": inventory["file_count"],
        "total_bytes": inventory["total_bytes"],
        "files": [
            {k: row[k] for k in ("logical_path", "sha256", "size", "mode", "uid", "gid", "mtime_ns")}
            for row in rows
        ],
    }
    archive = work / f"{day}.tar.zst"
    digest = _build_tar_zst(archive, rows, manifest, guard)
    manifest_path = work / f"{day}.manifest.json"
    sidecars = {
        "archive_sha256": digest,
        "archive_bytes": archive.stat().st_size,
        **manifest,
    }
    manifest_path.write_text(json.dumps(sidecars, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sha_path = work / f"{day}.sha256"
    sha_path.write_text(f"{digest}  {day}.tar.zst\n", encoding="utf-8")
    return {
        "schema": SCHEMA,
        "series": SERIES,
        "date": day,
        "kind": "day",
        "coverage": inventory["coverage"],
        "journal_status": manifest["journal_status"],
        "journals_absent": manifest["journals_absent"],
        "raw_banks_absent": manifest["raw_banks_absent"],
        "local_path": str(archive),
        "remote_name": f"{day}.tar.zst",
        "sha256": digest,
        "bytes": archive.stat().st_size,
        "manifest_path": str(manifest_path),
        "sha_path": str(sha_path),
        "manifest": sidecars,
    }


def build_control_archive(
    data_root: Path,
    work: Path,
    *,
    guard: Callable[[], None] = lambda: None,
) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    rows = [file_row(data_root, path, guard) for path in collect_control_files(data_root)]
    if not rows:
        raise DayArchiveError("no control binding files found under state/")
    manifest = {
        "schema": SCHEMA,
        "kind": "control",
        "compression": COMPRESSION,
        "file_count": len(rows),
        "total_bytes": sum(row["size"] for row in rows),
        "files": [
            {k: row[k] for k in ("logical_path", "sha256", "size", "mode", "uid", "gid", "mtime_ns")}
            for row in rows
        ],
    }
    archive = work / "CONTROL.tar.zst"
    digest = _build_tar_zst(archive, rows, manifest, guard)
    manifest_path = work / "CONTROL.manifest.json"
    sidecars = {
        "archive_sha256": digest,
        "archive_bytes": archive.stat().st_size,
        **manifest,
    }
    manifest_path.write_text(json.dumps(sidecars, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sha_path = work / "CONTROL.sha256"
    sha_path.write_text(f"{digest}  CONTROL.tar.zst\n", encoding="utf-8")
    return {
        "schema": SCHEMA,
        "kind": "control",
        "local_path": str(archive),
        "remote_name": "CONTROL.tar.zst",
        "sha256": digest,
        "bytes": archive.stat().st_size,
        "manifest_path": str(manifest_path),
        "sha_path": str(sha_path),
        "manifest": sidecars,
    }


def ensure_sidecars_uploaded(transport: DayArchiveRclone, built: dict) -> None:
    """Upload manifest/sha256 sidecars (idempotent via rclone --ignore-existing)."""
    if built.get("manifest_path"):
        transport.upload(Path(built["manifest_path"]).name, Path(built["manifest_path"]))
    if built.get("sha_path"):
        transport.upload(Path(built["sha_path"]).name, Path(built["sha_path"]))


def upload_and_verify(
    transport: DayArchiveRclone,
    built: dict,
    scratch: Path,
    *,
    guard: Callable[[], None] = lambda: None,
) -> None:
    local = Path(built["local_path"])
    remote_name = built["remote_name"]
    transport.upload(remote_name, local)
    verify_uploaded_archive(transport, remote_name, local, built["sha256"], scratch, guard)
    # Sidecar sha256/manifest are small; archive verify is the hard gate.
    ensure_sidecars_uploaded(transport, built)


def unlink_local_archive_only(built: dict) -> None:
    """Remove compressed workspace artifacts only — never source CDR trees."""
    for key in ("local_path", "manifest_path", "sha_path"):
        value = built.get(key)
        if not value:
            continue
        path = Path(value)
        if path.is_file() and (
            path.name.endswith(".tar.zst")
            or path.name.endswith(".sha256")
            or path.name.endswith(".manifest.json")
            or path.name.endswith(".GAP.json")
        ):
            path.unlink(missing_ok=True)


def process_day(
    *,
    data_root: Path,
    day: str,
    spool: Path,
    transport: DayArchiveRclone | None,
    dry_run: bool,
    include_journals: bool,
    guard: Callable[[], None] = lambda: None,
) -> dict:
    day = require_day(day)
    spool = Path(spool)
    lock_path = spool / "locks" / f"{day}.lock"
    with FileLock(lock_path):
        return _process_day_locked(
            data_root=data_root,
            day=day,
            spool=spool,
            transport=transport,
            dry_run=dry_run,
            include_journals=include_journals,
            guard=guard,
        )


def _process_day_locked(
    *,
    data_root: Path,
    day: str,
    spool: Path,
    transport: DayArchiveRclone | None,
    dry_run: bool,
    include_journals: bool,
    guard: Callable[[], None],
) -> dict:
    if in_quiet_window():
        raise DayArchiveError("refusing day-archive work inside 00:30–02:00 Australia/Hobart quiet window")
    prior = load_progress(spool).get(day)
    if prior and prior.get("result") == "PASS":
        request = spool / "requests" / f"{day}.json"
        request.unlink(missing_ok=True)
        return prior
    # Same-day archives stay pending until Hobart midnight so journals cover the full day.
    if day == hobart_today().isoformat() and not dry_run:
        return {
            "schema": SCHEMA,
            "date": day,
            "result": "DEFERRED",
            "reason": "same-day archives wait until the Hobart calendar day ends",
            "recorded_at": datetime.now(tz=DAILY_INGEST_TZ).isoformat(),
        }
    # Dry-run uses a separate workspace so it cannot destroy retained upload retry bytes.
    work = spool / "work" / "dry-run" / day if dry_run else spool / "work" / day
    work.mkdir(parents=True, exist_ok=True)
    combined_guard: Callable[[], None] = lambda: (quiet_window_guard(), guard())
    # Dry-run skips journalctl; never reuse those bytes for a journals-enabled upload.
    build_journals = bool(include_journals) and not dry_run

    def _reuse_or_build() -> dict:
        existing = work / f"{day}.tar.zst"
        existing_gap = work / f"{day}.GAP.json"
        sha_path = work / f"{day}.sha256"
        manifest_path = work / f"{day}.manifest.json"
        if day in KNOWN_GAPS and existing_gap.is_file():
            gap = gap_record(day)
            gap["series"] = SERIES
            existing_gap.write_text(
                json.dumps(gap, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            digest = sha256_file(existing_gap, combined_guard)
            return {
                "schema": SCHEMA,
                "series": SERIES,
                "date": day,
                "kind": "gap",
                "coverage": "gap",
                "journal_status": gap.get("journal_status"),
                "journals_absent": gap.get("journals_absent"),
                "raw_banks_absent": gap.get("raw_banks_absent"),
                "local_path": str(existing_gap),
                "remote_name": f"{day}.GAP.json",
                "sha256": digest,
                "bytes": existing_gap.stat().st_size,
                "manifest": gap,
            }
        if existing.is_file() and sha_path.is_file() and manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            digest = sha_path.read_text(encoding="utf-8").split()[0]
            journals_match = bool(manifest.get("include_journals")) == build_journals
            series_match = (not build_journals) or (
                manifest.get("series") == SERIES
                and manifest.get("journal_classifier") == JOURNAL_CLASSIFIER
            )
            if (
                journals_match
                and series_match
                and len(digest) == 64
                and sha256_file(existing, combined_guard) == digest
            ):
                return {
                    "schema": SCHEMA,
                    "series": SERIES,
                    "date": day,
                    "kind": "day",
                    "coverage": manifest.get("coverage"),
                    "journal_status": manifest.get("journal_status"),
                    "journals_absent": manifest.get("journals_absent"),
                    "raw_banks_absent": manifest.get("raw_banks_absent"),
                    "local_path": str(existing),
                    "remote_name": f"{day}.tar.zst",
                    "sha256": digest,
                    "bytes": existing.stat().st_size,
                    "manifest_path": str(manifest_path),
                    "sha_path": str(sha_path),
                    "manifest": manifest,
                }
        # Fresh build only when no reusable verified-local artifact exists.
        for path in work.iterdir():
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
        return build_day_archive(
            data_root,
            day,
            work,
            guard=combined_guard,
            include_journals=build_journals,
        )

    try:
        built = _reuse_or_build()
        if dry_run:
            row = {
                "schema": SCHEMA,
                "series": SERIES,
                "date": day,
                "result": "DRY_RUN",
                "coverage": built.get("coverage"),
                "journal_status": built.get("journal_status"),
                "journals_absent": built.get("journals_absent"),
                "raw_banks_absent": built.get("raw_banks_absent"),
                "kind": built.get("kind"),
                "bytes": built.get("bytes"),
                "sha256": built.get("sha256"),
                "recorded_at": datetime.now(tz=DAILY_INGEST_TZ).isoformat(),
            }
            record_progress(spool, row)
            # Remove only the dry-run workspace; leave spool/work/<day> retry artifacts intact.
            if work.exists():
                shutil.rmtree(work)
            return row
        if transport is None:
            raise DayArchiveError("transport required unless --dry-run")
        quiet_window_guard()
        require_day_archive_writes_allowed(spool)
        transport.ensure_folder()
        if transport.remote_exists(built["remote_name"]):
            # Idempotent: verify existing remote against local archive bytes,
            # then reconcile sidecars that may have failed on a prior attempt.
            verify_uploaded_archive(
                transport,
                built["remote_name"],
                Path(built["local_path"]),
                built["sha256"],
                spool / "verify",
                combined_guard,
            )
            ensure_sidecars_uploaded(transport, built)
        else:
            upload_and_verify(transport, built, spool / "verify", guard=combined_guard)
        row = {
            "schema": SCHEMA,
            "series": SERIES,
            "date": day,
            "result": "PASS",
            "coverage": built.get("coverage"),
            "journal_status": built.get("journal_status"),
            "journals_absent": built.get("journals_absent"),
            "raw_banks_absent": built.get("raw_banks_absent"),
            "kind": built.get("kind"),
            "bytes": built.get("bytes"),
            "sha256": built.get("sha256"),
            "remote_name": built["remote_name"],
            "recorded_at": datetime.now(tz=DAILY_INGEST_TZ).isoformat(),
        }
        # Durable PASS before unlink so a crash still leaves retryable local bytes.
        record_progress(spool, row)
        try:
            unlink_local_archive_only(built)
            request = spool / "requests" / f"{day}.json"
            request.unlink(missing_ok=True)
        except Exception as cleanup_error:  # noqa: BLE001 — PASS already durable
            # Do not rewrite PASS as FAIL; leftover local bytes are safe to clean later.
            row = {
                **row,
                "cleanup_warning": str(cleanup_error)[:300],
            }
            record_progress(spool, row)
        return row
    except Exception as error:
        row = {
            "schema": SCHEMA,
            "date": day,
            "result": "FAIL",
            "error": str(error)[:500],
            "recorded_at": datetime.now(tz=DAILY_INGEST_TZ).isoformat(),
        }
        record_progress(spool, row)
        raise


def process_control(
    *,
    data_root: Path,
    spool: Path,
    transport: DayArchiveRclone,
    dry_run: bool,
    guard: Callable[[], None] = lambda: None,
) -> dict:
    spool = Path(spool)
    with FileLock(spool / "locks" / "CONTROL.lock"):
        return _process_control_locked(
            data_root=data_root,
            spool=spool,
            transport=transport,
            dry_run=dry_run,
            guard=guard,
        )


def _process_control_locked(
    *,
    data_root: Path,
    spool: Path,
    transport: DayArchiveRclone,
    dry_run: bool,
    guard: Callable[[], None],
) -> dict:
    if in_quiet_window():
        raise DayArchiveError("refusing control-archive work inside quiet window")
    prior = load_progress(spool).get("CONTROL")
    if prior and prior.get("result") == "PASS" and not dry_run:
        return prior
    # Dry-run must not rmtree retained CONTROL retry artifacts under work/CONTROL.
    work = spool / "work" / "dry-run" / "CONTROL" if dry_run else spool / "work" / "CONTROL"
    work.mkdir(parents=True, exist_ok=True)

    def _reuse_or_build_control() -> dict:
        existing = work / "CONTROL.tar.zst"
        sha_path = work / "CONTROL.sha256"
        manifest_path = work / "CONTROL.manifest.json"
        if existing.is_file() and sha_path.is_file() and manifest_path.is_file():
            digest = sha_path.read_text(encoding="utf-8").split()[0]
            if len(digest) == 64 and sha256_file(existing, guard) == digest:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                return {
                    "schema": SCHEMA,
                    "kind": "control",
                    "local_path": str(existing),
                    "remote_name": "CONTROL.tar.zst",
                    "sha256": digest,
                    "bytes": existing.stat().st_size,
                    "manifest_path": str(manifest_path),
                    "sha_path": str(sha_path),
                    "manifest": manifest,
                }
        for path in work.iterdir():
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
        return build_control_archive(data_root, work, guard=guard)

    built = _reuse_or_build_control()
    if dry_run:
        if work.exists():
            shutil.rmtree(work)
        return {"result": "DRY_RUN", **{k: built[k] for k in ("sha256", "bytes", "remote_name")}}
    require_day_archive_writes_allowed(spool)
    transport.ensure_folder()
    if transport.remote_exists(built["remote_name"]):
        verify_uploaded_archive(
            transport,
            built["remote_name"],
            Path(built["local_path"]),
            built["sha256"],
            spool / "verify",
            guard,
        )
        ensure_sidecars_uploaded(transport, built)
    else:
        upload_and_verify(transport, built, spool / "verify", guard=guard)
    row = {
        "schema": SCHEMA,
        "date": "CONTROL",
        "result": "PASS",
        "kind": "control",
        "bytes": built["bytes"],
        "sha256": built["sha256"],
        "remote_name": built["remote_name"],
        "recorded_at": datetime.now(tz=DAILY_INGEST_TZ).isoformat(),
    }
    # Durable PASS before unlink so CONTROL retries retain matching local bytes.
    record_progress(spool, row)
    try:
        unlink_local_archive_only(built)
    except Exception as cleanup_error:  # noqa: BLE001 — PASS already durable
        row = {**row, "cleanup_warning": str(cleanup_error)[:300]}
        record_progress(spool, row)
    return row


def make_transport(args: argparse.Namespace) -> DayArchiveRclone:
    remote = args.rclone_remote
    if ":" not in remote:
        raise SystemExit("rclone remote must look like ar_local_drive:AR-local Pi Backups")
    return DayArchiveRclone(args.rclone_config, remote, args.drive_root_folder_id)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Per-day unencrypted CDR archives to Google Drive")
    parser.add_argument("--data-root", type=Path, default=Path(os.environ.get("AR_LOCAL_DATA_ROOT", DEFAULT_DATA_ROOT)))
    parser.add_argument("--spool", type=Path, default=Path(os.environ.get("AR_LOCAL_DAY_ARCHIVE_SPOOL", DEFAULT_SPOOL)))
    parser.add_argument(
        "--rclone-config",
        type=Path,
        default=Path(os.environ.get("RCLONE_CONFIG", DEFAULT_RCLONE)),
    )
    parser.add_argument(
        "--rclone-remote",
        default=os.environ.get("AR_LOCAL_DAY_ARCHIVE_REMOTE", DEFAULT_REMOTE),
    )
    parser.add_argument(
        "--drive-root-folder-id",
        default=os.environ.get("AR_LOCAL_DRIVE_ROOT_FOLDER_ID", ""),
        help="Pinned drive.file root folder ID",
    )
    parser.add_argument("--date", help="Process a single YYYY-MM-DD")
    parser.add_argument("--backfill", action="store_true", help="Sequential from first day through yesterday")
    parser.add_argument("--once-pending", action="store_true", help="Process one queued request if present")
    parser.add_argument("--control", action="store_true", help="Upload CONTROL binding archive")
    parser.add_argument("--request", metavar="DATE", help="Enqueue a day without processing")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--skip-journals",
        action="store_true",
        help="Rejected. Raw records always capture systemd journals.",
    )
    parser.add_argument("--max-days", type=int, default=0, help="Limit backfill days this invocation")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.skip_journals:
        raise SystemExit(
            "--skip-journals is rejected for daily-cdr-raw-records; "
            "systemd journals are part of each raw record"
        )
    spool = args.spool
    spool.mkdir(parents=True, exist_ok=True)
    if args.request:
        path = request_day_archive(args.request, spool=spool, reason="cli-request")
        print(json.dumps({"requested": args.request, "path": str(path)}, indent=2))
        return 0

    transport = None
    if not args.dry_run:
        transport = make_transport(args)

    if args.control:
        result = process_control(
            data_root=args.data_root.resolve(),
            spool=spool,
            transport=transport,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("result") in ("PASS", "DRY_RUN") else 1

    days: list[str] = []
    if args.date:
        days = [require_day(args.date)]
    elif args.once_pending:
        requests_dir = spool / "requests"
        pending = sorted(requests_dir.glob("*.json")) if requests_dir.is_dir() else []
        today = hobart_today().isoformat()
        # Skip same-day requests; leave them queued until the next Hobart day.
        eligible = []
        for marker in pending:
            try:
                requested = require_day(json.loads(marker.read_text(encoding="utf-8"))["date"])
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue
            if requested == today:
                continue
            eligible.append(requested)
        if not eligible:
            print(
                json.dumps(
                    {
                        "result": "IDLE",
                        "reason": "no eligible pending requests (same-day deferred)",
                    },
                    indent=2,
                )
            )
            return 0
        days = [eligible[0]]
    elif args.backfill:
        done = load_progress(spool)
        for day in iter_backfill_days():
            prior = done.get(day)
            if prior and prior.get("result") == "PASS":
                continue
            days.append(day)
            if args.max_days and len(days) >= args.max_days:
                break
    else:
        raise SystemExit("specify --date, --backfill, --once-pending, --control, or --request")

    results = []
    for day in days:
        result = process_day(
            data_root=args.data_root.resolve(),
            day=day,
            spool=spool,
            transport=transport,
            dry_run=args.dry_run,
            include_journals=True,
        )
        results.append(result)
        if result.get("result") == "FAIL":
            print(json.dumps({"results": results}, indent=2, sort_keys=True))
            return 1
        if result.get("result") == "DEFERRED" and args.date:
            # Explicit --date for today is not yet eligible.
            print(json.dumps({"results": results}, indent=2, sort_keys=True))
            return 1
    print(json.dumps({"results": results}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
