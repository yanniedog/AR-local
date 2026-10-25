"""Unit tests for per-day unencrypted CDR Drive archives."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import pi_daily_cdr_day_archive as archive
import pi_daily_cdr_day_archive_scope as scope
import pi_daily_cdr_day_archive_transport as transport


HOBART = ZoneInfo("Australia/Hobart")


def _write(path: Path, text: str = "payload") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_require_day_and_gaps():
    assert scope.require_day("2026-05-13") == "2026-05-13"
    with pytest.raises(ValueError):
        scope.require_day("2026-05-12")
    gap = scope.gap_record("2026-05-14")
    assert gap["coverage"] == "gap"
    assert gap["status"] == "known_gap"
    assert scope.gap_record("2026-06-26")["status"] == "unclassified_gap"


def test_iter_backfill_includes_gaps_and_stops_yesterday(monkeypatch):
    monkeypatch.setattr(
        scope,
        "hobart_today",
        lambda now=None: date(2026, 5, 16),
    )
    days = list(scope.iter_backfill_days())
    assert days[0] == "2026-05-13"
    assert "2026-05-14" in days
    assert days[-1] == "2026-05-15"


def test_day_inventory_excludes_app_payload_and_classifies(tmp_path: Path):
    data = tmp_path / "data"
    day = "2026-05-13"
    _write(data / "runs" / day / "_exports" / "local-cdr.sqlite", "sqlite-bytes")
    _write(data / "runs" / day / "_exports" / "app-payload" / "manifest.json", "skip-me")
    _write(data / "runs" / day / "_exports" / "app-payload-latest" / "manifest.json", "z")
    _write(data / "runs" / day / "_exports" / "dashboard-cache" / "x.json", "skip-me")
    _write(
        data / "runs" / day / "_exports" / "attempt-evidence" / "raw-attempt-journals-v1" / "s" / "bodies" / "a.body",
        "wire",
    )
    _write(data / "state" / f"{day}.done.json", '{"ok":true}')
    inventory = scope.build_day_inventory(data, day, journal_dir=None)
    paths = {row["logical_path"] for row in inventory["files"]}
    assert any(path.endswith("local-cdr.sqlite") for path in paths)
    assert not any("app-payload" in path for path in paths)
    assert not any("dashboard-cache" in path for path in paths)
    assert inventory["coverage"] == "wire_raw"
    assert inventory["raw_banks_absent"] is True
    assert inventory["journal_status"] == "unavailable"
    assert inventory["journals_absent"] is True


def test_exports_only_coverage(tmp_path: Path):
    data = tmp_path / "data"
    day = "2026-05-15"
    _write(data / "runs" / day / "_exports" / "banks.json", "{}")
    inventory = scope.build_day_inventory(data, day, journal_dir=None)
    assert inventory["coverage"] == "exports_only"


def test_build_day_archive_gap_and_verify_before_unlink(tmp_path: Path, monkeypatch):
    spool = tmp_path / "spool"
    work = spool / "work" / "2026-05-14"
    built = archive.build_day_archive(tmp_path / "data", "2026-05-14", work, include_journals=False)
    assert built["kind"] == "gap"
    assert Path(built["local_path"]).is_file()

    uploaded: list[str] = []

    class FakeTransport:
        def ensure_folder(self):
            return None

        def remote_exists(self, relative):
            return False

        def upload(self, relative, source):
            uploaded.append(relative)
            Path(source).read_bytes()

        def download(self, relative, destination):
            source = work / relative
            destination.write_bytes(source.read_bytes())
            return True

    monkeypatch.setattr(archive, "in_quiet_window", lambda now=None: False)
    monkeypatch.setattr(archive, "require_day_archive_writes_allowed", lambda spool: None)
    monkeypatch.setattr(
        archive,
        "verify_uploaded_archive",
        lambda transport, relative, local_archive, expected_sha256, scratch, guard=lambda: None: None,
    )
    result = archive.process_day(
        data_root=tmp_path / "data",
        day="2026-05-14",
        spool=spool,
        transport=FakeTransport(),
        dry_run=False,
        include_journals=False,
    )
    assert result["result"] == "PASS"
    assert not Path(built["local_path"]).exists()
    assert uploaded == ["2026-05-14.GAP.json"]


def test_process_day_refuses_quiet_window(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(archive, "in_quiet_window", lambda now=None: True)
    with pytest.raises(archive.DayArchiveError, match="quiet window"):
        archive.process_day(
            data_root=tmp_path,
            day="2026-05-13",
            spool=tmp_path / "spool",
            transport=None,
            dry_run=True,
            include_journals=False,
        )


def test_request_day_archive_idempotent(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AR_LOCAL_DAY_ARCHIVE_SPOOL", str(tmp_path / "spool"))
    first = archive.request_day_archive("2026-10-01", spool=tmp_path / "spool")
    second = archive.request_day_archive("2026-10-01", spool=tmp_path / "spool")
    assert first == second
    assert json.loads(first.read_text(encoding="utf-8"))["date"] == "2026-10-01"


def test_unlink_never_touches_source(tmp_path: Path):
    source = tmp_path / "data" / "runs" / "2026-05-13" / "_exports" / "x.json"
    _write(source, "keep")
    archive_path = tmp_path / "2026-05-13.tar.zst"
    archive_path.write_bytes(b"zst")
    archive.unlink_local_archive_only(
        {"local_path": str(archive_path), "manifest_path": None, "sha_path": None}
    )
    assert not archive_path.exists()
    assert source.read_text(encoding="utf-8") == "keep"


def test_object_path_validation():
    assert transport.OBJECT_RE.fullmatch("2026-05-13.tar.zst")
    assert transport.OBJECT_RE.fullmatch("2026-05-14.GAP.json")
    assert transport.OBJECT_RE.fullmatch("CONTROL.tar.zst")
    generation = "2026-10-25.obs-2026-10-25-0123456789abcdef"
    assert transport.OBJECT_RE.fullmatch(f"{generation}.tar.zst")
    assert transport.OBJECT_RE.fullmatch(f"{generation}.sha256")
    assert transport.OBJECT_RE.fullmatch(f"{generation}.manifest.json")
    assert not transport.OBJECT_RE.fullmatch("2026-10-25.not-a-generation.tar.zst")
    assert not transport.OBJECT_RE.fullmatch("../escape.tar.zst")
    assert transport.PureName("2026-05-13.manifest.json") == "2026-05-13.manifest.json"
    with pytest.raises(ValueError):
        transport.PureName("../2026-05-13.tar.zst")
    with pytest.raises(ValueError):
        transport.PureName("daily-cdr-day-archives/2026-05-13.tar.zst")


def test_resolve_archive_remote_pins_raw_records_folder():
    parent = (
        "ar_local_drive_dedicated_20260913:"
        "AR-local Pi Backups Dedicated 20260913-326040d72fbc405ea2e9b2dacea6b412"
    )
    resolved = transport.resolve_archive_remote(parent)
    assert resolved.endswith("/daily-cdr-raw-records")
    assert "daily-cdr-day-archives" not in resolved
    assert transport.resolve_archive_remote(resolved) == resolved
    with pytest.raises(ValueError, match="daily-cdr-day-archives"):
        transport.resolve_archive_remote(parent + "/daily-cdr-day-archives")


def test_build_compressed_day_archive_roundtrip_sha(tmp_path: Path):
    data = tmp_path / "data"
    day = "2026-05-13"
    _write(data / "runs" / day / "_exports" / "local-cdr.sqlite", "abc123")
    _write(data / "state" / f"{day}.done.json", '{"ok":true}')
    work = tmp_path / "work"
    built = archive.build_day_archive(data, day, work, include_journals=False)
    assert built["kind"] == "day"
    assert Path(built["local_path"]).stat().st_size > 0
    assert len(built["sha256"]) == 64
    assert Path(built["sha_path"]).read_text(encoding="utf-8").startswith(built["sha256"])


def test_journals_alone_are_not_primary(tmp_path: Path, monkeypatch):
    data = tmp_path / "data"
    day = "2026-05-15"
    work = tmp_path / "work"
    monkeypatch.setattr(
        archive,
        "build_day_inventory",
        lambda *args, **kwargs: {
            "schema": "x",
            "date": day,
            "coverage": "partial",
            "file_count": 1,
            "total_bytes": 3,
            "files": [
                {
                    "logical_path": f"journal/unit-{day}.log",
                    "source_path": str(tmp_path / "j.log"),
                    "sha256": "a" * 64,
                    "size": 3,
                    "mode": "0o600",
                    "uid": 0,
                    "gid": 0,
                    "mtime_ns": 0,
                }
            ],
        },
    )
    (tmp_path / "j.log").write_text("log", encoding="utf-8")
    with pytest.raises(archive.DayArchiveError, match="journal exports alone"):
        archive.build_day_archive(data, day, work, include_journals=True)


def test_pass_clears_pending_request(tmp_path: Path, monkeypatch):
    spool = tmp_path / "spool"
    day = "2026-05-14"
    request = archive.request_day_archive(day, spool=spool)
    assert request.is_file()
    archive.record_progress(
        spool,
        {
            "schema": archive.SCHEMA,
            "date": day,
            "result": "PASS",
            "kind": "gap",
            "recorded_at": "now",
        },
    )
    monkeypatch.setattr(archive, "in_quiet_window", lambda now=None: False)
    result = archive.process_day(
        data_root=tmp_path / "data",
        day=day,
        spool=spool,
        transport=None,
        dry_run=True,
        include_journals=False,
    )
    assert result["result"] == "PASS"
    assert not request.exists()


def test_existing_remote_retries_sidecars(tmp_path: Path, monkeypatch):
    spool = tmp_path / "spool"
    day = "2026-05-14"
    uploaded: list[str] = []

    class FakeTransport:
        def ensure_folder(self):
            return None

        def remote_exists(self, relative):
            return relative == f"{day}.GAP.json"

        def upload(self, relative, source):
            uploaded.append(relative)
            Path(source).read_bytes()

        def download(self, relative, destination):
            raise AssertionError("verify stubbed")

    monkeypatch.setattr(archive, "in_quiet_window", lambda now=None: False)
    monkeypatch.setattr(archive, "require_day_archive_writes_allowed", lambda spool: None)
    monkeypatch.setattr(
        archive,
        "verify_uploaded_archive",
        lambda *args, **kwargs: None,
    )
    # Seed a reusable local gap artifact so the existing-remote branch is taken.
    work = spool / "work" / day
    work.mkdir(parents=True)
    gap_path = work / f"{day}.GAP.json"
    gap_path.write_text(json.dumps(scope.gap_record(day)), encoding="utf-8")
    result = archive.process_day(
        data_root=tmp_path / "data",
        day=day,
        spool=spool,
        transport=FakeTransport(),
        dry_run=False,
        include_journals=False,
    )
    assert result["result"] == "PASS"
    # Gap archives have no sidecars; existing-remote path must still complete.
    assert uploaded == []


def test_existing_remote_day_uploads_missing_sidecars(tmp_path: Path, monkeypatch):
    spool = tmp_path / "spool"
    data = tmp_path / "data"
    day = "2026-05-13"
    _write(data / "runs" / day / "_exports" / "local-cdr.sqlite", "abc")
    _write(data / "state" / f"{day}.done.json", '{"ok":true}')
    monkeypatch.setattr(archive, "in_quiet_window", lambda now=None: False)
    monkeypatch.setattr(archive, "require_day_archive_writes_allowed", lambda spool: None)
    monkeypatch.setattr(archive, "verify_uploaded_archive", lambda *a, **k: None)
    work = spool / "work" / day
    built = archive.build_day_archive(data, day, work, include_journals=False)
    uploaded: list[str] = []

    class FakeTransport:
        def ensure_folder(self):
            return None

        def remote_exists(self, relative):
            return relative == built["remote_name"]

        def upload(self, relative, source):
            uploaded.append(relative)

        def download(self, relative, destination):
            raise AssertionError("verify stubbed")

    result = archive.process_day(
        data_root=data,
        day=day,
        spool=spool,
        transport=FakeTransport(),
        dry_run=False,
        include_journals=False,
    )
    assert result["result"] == "PASS"
    assert f"{day}.manifest.json" in uploaded
    assert f"{day}.sha256" in uploaded


def test_dry_run_does_not_leave_reusable_workspace(tmp_path: Path, monkeypatch):
    spool = tmp_path / "spool"
    data = tmp_path / "data"
    day = "2026-05-13"
    _write(data / "runs" / day / "_exports" / "local-cdr.sqlite", "abc")
    _write(data / "state" / f"{day}.done.json", '{"ok":true}')
    monkeypatch.setattr(archive, "in_quiet_window", lambda now=None: False)
    dry = archive.process_day(
        data_root=data,
        day=day,
        spool=spool,
        transport=None,
        dry_run=True,
        include_journals=True,
    )
    assert dry["result"] == "DRY_RUN"
    assert not (spool / "work" / "dry-run" / day).exists()
    assert not (spool / "work" / day).exists()


def test_dry_run_preserves_retained_upload_workspace(tmp_path: Path, monkeypatch):
    spool = tmp_path / "spool"
    data = tmp_path / "data"
    day = "2026-05-13"
    _write(data / "runs" / day / "_exports" / "local-cdr.sqlite", "abc")
    _write(data / "state" / f"{day}.done.json", '{"ok":true}')
    real_work = spool / "work" / day
    built = archive.build_day_archive(data, day, real_work, include_journals=False)
    retained = Path(built["local_path"])
    assert retained.is_file()
    monkeypatch.setattr(archive, "in_quiet_window", lambda now=None: False)
    dry = archive.process_day(
        data_root=data,
        day=day,
        spool=spool,
        transport=None,
        dry_run=True,
        include_journals=True,
    )
    assert dry["result"] == "DRY_RUN"
    assert retained.is_file()
    assert (real_work / f"{day}.sha256").is_file()
    assert not (spool / "work" / "dry-run" / day).exists()


def test_build_rejects_mutated_member_bytes(tmp_path: Path, monkeypatch):
    data = tmp_path / "data"
    day = "2026-05-13"
    source = data / "runs" / day / "_exports" / "local-cdr.sqlite"
    _write(source, "abc")
    _write(data / "state" / f"{day}.done.json", '{"ok":true}')
    work = tmp_path / "work"
    original = archive.build_day_inventory

    def mutate_then_inventory(*args, **kwargs):
        inventory = original(*args, **kwargs)
        source.write_text("XYZ", encoding="utf-8")  # same size, different bytes
        return inventory

    monkeypatch.setattr(archive, "build_day_inventory", mutate_then_inventory)
    with pytest.raises(archive.DayArchiveError, match="changed since inventory"):
        archive.build_day_archive(data, day, work, include_journals=False)


def test_reuse_rejects_mismatched_journal_option(tmp_path: Path, monkeypatch):
    spool = tmp_path / "spool"
    data = tmp_path / "data"
    day = "2026-05-13"
    _write(data / "runs" / day / "_exports" / "local-cdr.sqlite", "abc")
    _write(data / "state" / f"{day}.done.json", '{"ok":true}')
    work = spool / "work" / day
    archive.build_day_archive(data, day, work, include_journals=False)
    rebuilt: list[bool] = []
    original_build = archive.build_day_archive

    def tracking_build(*args, **kwargs):
        rebuilt.append(bool(kwargs.get("include_journals")))
        return original_build(*args, **kwargs)

    monkeypatch.setattr(archive, "build_day_archive", tracking_build)
    monkeypatch.setattr(archive, "in_quiet_window", lambda now=None: False)
    monkeypatch.setattr(archive, "require_day_archive_writes_allowed", lambda spool: None)
    monkeypatch.setattr(archive, "verify_uploaded_archive", lambda *a, **k: None)
    monkeypatch.setattr(
        scope,
        "export_journals",
        lambda day, dest, units=scope.JOURNAL_UNITS: {
            "paths": [],
            "journal_status": "unavailable",
            "units": [],
        },
    )

    class FakeTransport:
        def ensure_folder(self):
            return None

        def remote_exists(self, relative):
            return False

        def upload(self, relative, source):
            return None

        def download(self, relative, destination):
            raise AssertionError("unused")

    # Journals requested but workspace holds a no-journals archive → rebuild.
    result = archive.process_day(
        data_root=data,
        day=day,
        spool=spool,
        transport=FakeTransport(),
        dry_run=False,
        include_journals=True,
    )
    assert result["result"] == "PASS"
    assert rebuilt == [True]


def test_process_day_holds_per_day_lock(tmp_path: Path, monkeypatch):
    spool = tmp_path / "spool"
    day = "2026-05-14"
    seen: list[Path] = []

    class RecordingLock:
        def __init__(self, path: Path):
            seen.append(path)
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(archive, "FileLock", RecordingLock)
    monkeypatch.setattr(archive, "in_quiet_window", lambda now=None: False)
    archive.record_progress(
        spool,
        {
            "schema": archive.SCHEMA,
            "date": day,
            "result": "PASS",
            "kind": "gap",
            "recorded_at": "now",
        },
    )
    archive.process_day(
        data_root=tmp_path / "data",
        day=day,
        spool=spool,
        transport=None,
        dry_run=True,
        include_journals=False,
    )
    assert seen == [spool / "locks" / f"{day}.lock"]


def test_hold_blocks_upload(tmp_path: Path, monkeypatch):
    spool = tmp_path / "spool"
    day = "2026-05-14"
    monkeypatch.setattr(archive, "in_quiet_window", lambda now=None: False)
    monkeypatch.setattr(
        archive,
        "require_day_archive_writes_allowed",
        lambda path: (_ for _ in ()).throw(archive.DayArchiveError("held")),
    )

    class FakeTransport:
        def ensure_folder(self):
            raise AssertionError("must not reach transport under hold")

        def remote_exists(self, relative):
            raise AssertionError("must not reach transport under hold")

    with pytest.raises(archive.DayArchiveError, match="held"):
        archive.process_day(
            data_root=tmp_path / "data",
            day=day,
            spool=spool,
            transport=FakeTransport(),
            dry_run=False,
            include_journals=False,
        )


def test_atomic_json_uses_unique_temp(tmp_path: Path):
    target = tmp_path / "latest.json"
    archive._atomic_json(target, {"a": 1})
    archive._atomic_json(target, {"a": 2})
    assert json.loads(target.read_text(encoding="utf-8"))["a"] == 2
    assert list(tmp_path.glob("latest.json.*.tmp")) == []


def test_control_reuses_local_artifact(tmp_path: Path, monkeypatch):
    spool = tmp_path / "spool"
    data = tmp_path / "data"
    _write(data / "state" / "control.json", '{"ok":true}')
    monkeypatch.setattr(archive, "in_quiet_window", lambda now=None: False)
    monkeypatch.setattr(archive, "require_day_archive_writes_allowed", lambda spool: None)
    monkeypatch.setattr(archive, "verify_uploaded_archive", lambda *a, **k: None)
    monkeypatch.setattr(
        archive,
        "collect_control_files",
        lambda root: [data / "state" / "control.json"],
    )
    work = spool / "work" / "CONTROL"
    first = archive.build_control_archive(data, work)
    first_sha = first["sha256"]
    rebuilt: list[bool] = []
    original = archive.build_control_archive

    def tracking(*args, **kwargs):
        rebuilt.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(archive, "build_control_archive", tracking)

    class FakeTransport:
        def ensure_folder(self):
            return None

        def remote_exists(self, relative):
            return True

        def upload(self, relative, source):
            return None

    result = archive.process_control(
        data_root=data,
        spool=spool,
        transport=FakeTransport(),
        dry_run=False,
    )
    assert result["result"] == "PASS"
    assert result["sha256"] == first_sha
    assert rebuilt == []


def test_journalctl_nonzero_exit_is_unavailable(tmp_path: Path, monkeypatch):
    class FakeCompleted:
        returncode = 1
        stderr = "Failed to open journal"

    monkeypatch.setattr(
        scope.subprocess,
        "run",
        lambda *args, **kwargs: FakeCompleted(),
    )
    result = scope.export_journals("2026-05-13", tmp_path / "journals", units=["ar-local-daily.service"])
    assert result["journal_status"] == "unavailable"
    assert result["paths"] == []
    assert list((tmp_path / "journals").glob("*.log")) == []


def test_journalctl_empty_range_is_kept(tmp_path: Path, monkeypatch):
    class FakeCompleted:
        returncode = 0
        stderr = ""

    monkeypatch.setattr(scope.subprocess, "run", lambda *args, **kwargs: FakeCompleted())
    result = scope.export_journals("2026-05-13", tmp_path / "journals", units=["ar-local-daily.service"])
    assert result["journal_status"] == "empty"
    assert result["paths"][0].read_text(encoding="utf-8") == ""
    assert result["units"][0]["status"] == "empty"


def test_journalctl_output_is_captured(tmp_path: Path, monkeypatch):
    class FakeCompleted:
        returncode = 0
        stderr = ""

    def _run(*args, **kwargs):
        kwargs["stdout"].write("j")
        return FakeCompleted()

    monkeypatch.setattr(scope.subprocess, "run", _run)
    result = scope.export_journals("2026-05-13", tmp_path / "journals", units=["ar-local-daily.service"])
    assert result["journal_status"] == "captured"
    assert result["paths"][0].read_text(encoding="utf-8") == "j"


def test_journalctl_no_entries_marker_is_empty(tmp_path: Path, monkeypatch):
    class FakeCompleted:
        returncode = 0
        stderr = ""

    def _run(*args, **kwargs):
        kwargs["stdout"].write("-- No entries --\n")
        return FakeCompleted()

    monkeypatch.setattr(scope.subprocess, "run", _run)
    result = scope.export_journals("2026-05-13", tmp_path / "journals", units=["ar-local-daily.service"])
    assert result["journal_status"] == "empty"
    assert result["units"][0]["status"] == "empty"


def test_reconstruction_exports_are_not_wire_raw(tmp_path: Path):
    data = tmp_path / "data"
    day = "2026-07-07"
    _write(data / "runs" / day / "_exports" / "local-cdr.sqlite", "s")
    _write(data / "runs" / day / "_exports" / f"banks-{day}.json", "j")
    _write(data / "runs" / day / "_exports" / f"banks-{day}.xlsx", "x")
    _write(data / "runs" / day / "_exports" / "app-payload-latest" / "manifest.json", "d")
    inventory = scope.build_day_inventory(data, day, journal_dir=None)
    paths = {row["logical_path"] for row in inventory["files"]}
    assert any(path.endswith(f"banks-{day}.json") for path in paths)
    assert any(path.endswith("local-cdr.sqlite") for path in paths)
    assert not any("app-payload" in path for path in paths)
    assert inventory["coverage"] == "exports_only"
    assert inventory["raw_banks_absent"] is True
    assert inventory["journals_absent"] is True


def test_banks_product_detail_is_wire_raw(tmp_path: Path):
    data = tmp_path / "data"
    day = "2026-08-01"
    _write(data / "runs" / day / "banks" / "a" / "b" / "product-detail.json", "p")
    _write(data / "runs" / day / "banks" / "a" / "b" / "product-id.txt", "q")
    _write(data / "runs" / day / "holders" / "h.txt", "h")
    _write(data / "runs" / day / "_revisions" / "r" / "m.txt", "m")
    _write(data / "runs" / day / "_exports" / f"banks-{day}.json", "j")
    _write(data / "runs" / day / "_exports" / "local-cdr.sqlite", "s")
    inventory = scope.build_day_inventory(data, day, journal_dir=None)
    paths = {row["logical_path"] for row in inventory["files"]}
    assert any(path.endswith("product-detail.json") for path in paths)
    assert any("/holders/" in path for path in paths)
    assert any("/_revisions/" in path for path in paths)
    assert inventory["coverage"] == "wire_raw"
    assert inventory["raw_banks_absent"] is False


def test_legacy_pass_rows_are_not_raw_progress(tmp_path: Path):
    spool = tmp_path / "spool"
    meta = spool / "meta"
    meta.mkdir(parents=True)
    legacy = json.dumps({"date": "2026-05-13", "result": "PASS", "coverage": "exports_only"}) + "\n"
    (spool / "progress.jsonl").write_text(legacy, encoding="utf-8")
    (meta / "progress.jsonl").write_text(legacy, encoding="utf-8")
    assert archive.load_progress(spool) == {}
    archive.record_progress(spool, {"date": "2026-05-15", "result": "PASS"})
    assert set(archive.load_progress(spool)) == {"2026-05-15"}
    assert (meta / "raw-progress.jsonl").is_file()
    assert "2026-05-15" not in (meta / "progress.jsonl").read_text(encoding="utf-8")


def test_migrate_env_rewrites_only_legacy_remote():
    legacy = (
        'AR_LOCAL_DATA_ROOT=/srv/ar-local/data\n'
        'AR_LOCAL_DAY_ARCHIVE_REMOTE="name:Parent/daily-cdr-day-archives"\n'
    )
    updated = transport.migrate_day_archive_env(legacy)
    assert "daily-cdr-day-archives" not in updated
    assert updated.endswith('AR_LOCAL_DAY_ARCHIVE_REMOTE="name:Parent/daily-cdr-raw-records"\n')
    assert transport.migrate_day_archive_env(updated) == updated
    with pytest.raises(ValueError):
        transport.migrate_day_archive_env('AR_LOCAL_DAY_ARCHIVE_REMOTE="name:other-folder"\n')


def _installer_migration_source() -> str:
    script = (
        Path(__file__).resolve().parents[1] / "deploy/pi/install-day-archive.sh"
    ).read_text(encoding="utf-8")
    assert "pi_daily_cdr_day_archive_transport" not in script
    assert "PYTHONPATH" not in script
    assert "/usr/bin/python3 -I -S - /etc/ar-local/day-archive.env" in script
    start = script.index("<< 'PY'\n") + len("<< 'PY'\n")
    return script[start:script.index("\nPY\n", start)]


def _run_installer_migration(source: str, env_file: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-S", "-", str(env_file)],
        input=source,
        text=True,
        capture_output=True,
        check=False,
    )


def test_install_migration_is_isolated_stdlib(tmp_path: Path):
    source = _installer_migration_source()
    legacy = 'AR_LOCAL_DAY_ARCHIVE_REMOTE="name:Parent/daily-cdr-day-archives"\n'
    env_file = tmp_path / "day-archive.env"
    env_file.write_text(legacy, encoding="utf-8")
    migrated = _run_installer_migration(source, env_file)
    assert migrated.returncode == 0, migrated.stderr
    assert migrated.stdout.strip() == (
        "migrated AR_LOCAL_DAY_ARCHIVE_REMOTE to daily-cdr-raw-records"
    )
    assert env_file.read_text(encoding="utf-8") == transport.migrate_day_archive_env(legacy)
    again = _run_installer_migration(source, env_file)
    assert again.returncode == 0, again.stderr
    assert again.stdout == ""
    original = 'AR_LOCAL_DAY_ARCHIVE_REMOTE="name:other-folder"\n'
    bad = tmp_path / "bad.env"
    bad.write_text(original, encoding="utf-8")
    rejected = _run_installer_migration(source, bad)
    assert rejected.returncode != 0
    assert bad.read_text(encoding="utf-8") == original


def test_journalctl_command_is_quiet(tmp_path: Path, monkeypatch):
    class FakeCompleted:
        returncode = 0
        stderr = ""

    seen: dict[str, list[str]] = {}

    def _run(command, **kwargs):
        seen["command"] = list(command)
        return FakeCompleted()

    monkeypatch.setattr(scope.subprocess, "run", _run)
    result = scope.export_journals("2026-05-13", tmp_path / "journals", units=["ar-local-daily.service"])
    assert "--quiet" in seen["command"]
    assert result["journal_status"] == "empty"


def test_stale_gap_marker_is_rewritten_before_upload(tmp_path: Path, monkeypatch):
    spool = tmp_path / "spool"
    day = "2026-05-14"
    work = spool / "work" / day
    work.mkdir(parents=True)
    gap_path = work / f"{day}.GAP.json"
    gap_path.write_text("{}\n", encoding="utf-8")
    uploaded: dict[str, str] = {}

    class FakeTransport:
        def ensure_folder(self):
            return None

        def remote_exists(self, relative):
            return False

        def upload(self, relative, source):
            uploaded[relative] = Path(source).read_text(encoding="utf-8")

        def download(self, relative, destination):
            raise AssertionError("verify stubbed")

    monkeypatch.setattr(archive, "in_quiet_window", lambda now=None: False)
    monkeypatch.setattr(archive, "require_day_archive_writes_allowed", lambda spool: None)
    monkeypatch.setattr(archive, "verify_uploaded_archive", lambda *args, **kwargs: None)
    result = archive.process_day(
        data_root=tmp_path / "data",
        day=day,
        spool=spool,
        transport=FakeTransport(),
        dry_run=False,
        include_journals=False,
    )
    body = json.loads(uploaded[f"{day}.GAP.json"])
    assert result["result"] == "PASS"
    assert body["series"] == "daily-cdr-raw-records"
    assert body["coverage"] == "gap"
    assert body["raw_banks_absent"] is True
    assert "{}" not in uploaded[f"{day}.GAP.json"]


def test_skip_journals_is_rejected():
    with pytest.raises(SystemExit, match="skip-journals"):
        archive.main(["--skip-journals", "--dry-run", "--date", "2026-05-13"])


def test_walk_propagates_unreadable_directory(tmp_path: Path, monkeypatch):
    root = tmp_path / "run"
    root.mkdir()
    (root / "ok.txt").write_text("x", encoding="utf-8")

    def boom(error):
        raise error

    real_walk = scope.os.walk

    def walk_with_error(*args, **kwargs):
        onerror = kwargs.get("onerror")
        if onerror:
            onerror(PermissionError("denied: secret"))
        return real_walk(*args, **kwargs)

    monkeypatch.setattr(scope.os, "walk", walk_with_error)
    with pytest.raises(RuntimeError, match="unreadable archive source"):
        list(scope._walk_files(root))


def test_same_day_upload_is_opt_in_and_keeps_wire_bodies(tmp_path: Path, monkeypatch):
    day = archive.hobart_today().isoformat()
    data = tmp_path / "data"
    leaf = data / "runs" / day / "banks" / "leaf"
    leaf.mkdir(parents=True)
    (leaf / "product-detail.json").write_bytes(b"opaque-wire-body")
    (leaf / "product-detail.error.txt").write_bytes(b"opaque-error-body")
    uploaded: list[str] = []

    class FakeTransport:
        def ensure_folder(self):
            return None

        def remote_exists(self, relative):
            return False

        def upload(self, relative, source):
            uploaded.append(relative)
            Path(source).read_bytes()

    monkeypatch.setattr(archive, "in_quiet_window", lambda now=None: False)
    monkeypatch.setattr(archive, "require_day_archive_writes_allowed", lambda spool: None)
    monkeypatch.setattr(
        archive,
        "verify_uploaded_archive",
        lambda *args, **kwargs: None,
    )
    spool = tmp_path / "spool"
    deferred = archive.process_day(
        data_root=data,
        day=day,
        spool=spool,
        transport=FakeTransport(),
        dry_run=False,
        include_journals=False,
    )
    assert deferred["result"] == "DEFERRED"
    assert uploaded == []
    result = archive.process_day(
        data_root=data,
        day=day,
        spool=spool,
        transport=FakeTransport(),
        dry_run=False,
        include_journals=False,
        allow_same_day=True,
    )
    assert result["result"] == "PASS"
    assert result["raw_banks_absent"] is False
    assert result["coverage"] == "wire_raw"
    assert uploaded[0] == f"{day}.tar.zst"
    assert (leaf / "product-detail.json").read_bytes() == b"opaque-wire-body"
    assert (leaf / "product-detail.error.txt").read_bytes() == b"opaque-error-body"


def test_archive_observation_day_is_synchronous_same_day_with_journals(tmp_path: Path, monkeypatch):
    seen = {}

    def fake_process_day(**kwargs):
        seen.update(kwargs)
        return {"result": "PASS", "date": kwargs["day"]}

    monkeypatch.setattr(archive, "process_day", fake_process_day)
    result = archive.archive_observation_day(
        "2026-10-24",
        data_root=tmp_path,
        spool=tmp_path / "spool",
        transport=object(),
    )
    assert result == {"result": "PASS", "date": "2026-10-24"}
    assert seen["allow_same_day"] is True
    assert seen["include_journals"] is True
    assert seen["dry_run"] is False
    assert seen["day"] == "2026-10-24"
