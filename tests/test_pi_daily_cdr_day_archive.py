"""Unit tests for per-day unencrypted CDR Drive archives."""
from __future__ import annotations

import json
import os
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
    assert not transport.OBJECT_RE.fullmatch("../escape.tar.zst")


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
