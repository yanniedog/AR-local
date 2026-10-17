"""Restore acceptance must retain referential health and current observation support."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from ar_local_restore_verification import _restore_database_view, verify_restored_state
from cdr_finalization import finalize_observation
from tests.support_observation import write_verified_observation
from tests.support_legacy_export import write_legacy_export
from tests.test_pi_backup_foundation import _write_finalized_observation


def _file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def _write_current_finalized(data_root: Path) -> Path:
    date = "2026-09-03"
    exports = data_root / "runs" / date / "_exports"
    observation = write_verified_observation(exports, observation_date=date)
    counts = observation["row_counts"]
    (exports / "dashboard-cache").mkdir()
    (exports / "dashboard-cache/latest.json").write_text(
        json.dumps({"run_date": date, "banks_counts": counts}), encoding="utf-8"
    )
    finalize_observation(
        exports, data_root / "state", data_root / "state" / f"{date}.done.json",
        observation_date=date, result={"run_date": date, "banks_counts": counts},
    )
    return exports


def test_restore_accepts_current_canonical_selected_observation_without_writes(tmp_path: Path):
    _write_current_finalized(tmp_path)
    before = _file_hashes(tmp_path)

    report = verify_restored_state(tmp_path)

    assert report["ok"], report["findings"]
    selected = report["selected_observation"]
    # The fixture's honest partial business coverage remains partial. Restore
    # acceptance proves preserved evidence, not complete lender coverage.
    assert selected["observation_state"] == "partial"
    record = next(item for item in report["sqlite"] if item["path"] == selected["database_path"])
    assert record["export_reconciliation"]["schema_version"] == "11"
    assert record["export_reconciliation"]["validation_mode"] == "canonical_observation_and_immutable_sqlite_v11"
    assert record["integrity_check"] == "ok"
    assert record["foreign_key_check"] == "ok"
    assert _file_hashes(tmp_path) == before


@pytest.mark.parametrize("version", ["6", "7", "8"])
def test_restore_preserves_exact_known_legacy_contracts(tmp_path: Path, version: str):
    data_root = tmp_path / "data"
    _write_finalized_observation(data_root)
    exports = write_legacy_export(tmp_path / "history-source", "2026-08-23", schema_version=version)
    historical = data_root / "runs/2026-08-23/_exports"
    shutil.copytree(exports, historical)
    before = _file_hashes(data_root)

    report = verify_restored_state(data_root)

    assert report["ok"], report["findings"]
    record = next(item for item in report["sqlite"] if item["path"].startswith("runs/2026-08-23/"))
    assert record["export_reconciliation"]["schema_version"] == version
    assert _file_hashes(data_root) == before


@pytest.mark.parametrize("version", ["6", "7", "8", "99", "broken", None, sqlite3.Binary(b"7")])
def test_restore_rejects_unknown_or_malformed_declared_legacy_schema(tmp_path: Path, version):
    _write_finalized_observation(tmp_path)
    database = tmp_path / "runs/2026-08-23/_exports/local-cdr.sqlite"
    database.parent.mkdir(parents=True)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE schema_meta(key TEXT, value TEXT)")
        connection.execute("INSERT INTO schema_meta VALUES ('version', ?)", (version,))
        connection.commit()

    report = verify_restored_state(tmp_path)

    assert not report["ok"]
    assert any(item.startswith("daily_export_mismatch:") for item in report["findings"])


@pytest.mark.parametrize("missing", ["observation-v1.json", "product-accounting-v1.json", "ingest-status.json"])
def test_restore_rejects_incomplete_current_evidence(tmp_path: Path, missing: str):
    exports = _write_current_finalized(tmp_path)
    (exports / missing).unlink()

    report = verify_restored_state(tmp_path)

    assert not report["ok"]
    assert any(item.startswith("daily_export_mismatch:") for item in report["findings"])


@pytest.mark.parametrize("suffix", ["-wal", "-journal"])
def test_canonical_database_rejects_retained_journal_instead_of_ignoring_it(tmp_path: Path, suffix: str):
    exports = _write_current_finalized(tmp_path)
    (exports / f"local-cdr.sqlite{suffix}").write_bytes(b"unresolved journal")
    before = _file_hashes(tmp_path)

    report = verify_restored_state(tmp_path)

    assert not report["ok"]
    assert _file_hashes(tmp_path) == before


def test_restore_detects_index_corruption_missed_by_quick_check(tmp_path: Path):
    _write_finalized_observation(tmp_path)
    database = tmp_path / "state/secondary.sqlite"
    with closing(sqlite3.connect(database)) as connection:
        connection.executescript(
            "CREATE TABLE evidence(a INTEGER,b INTEGER);"
            "CREATE INDEX evidence_idx ON evidence(a);"
            "INSERT INTO evidence VALUES (1,2);"
            "PRAGMA writable_schema=ON;"
        )
        connection.execute("UPDATE sqlite_master SET sql='CREATE INDEX evidence_idx ON evidence(b)' WHERE name='evidence_idx'")
        connection.execute("PRAGMA schema_version=99")
        connection.commit()
        assert connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        assert connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]
    before = _file_hashes(tmp_path)

    report = verify_restored_state(tmp_path)

    assert not report["ok"]
    assert any(item.startswith("sqlite_integrity_check:") for item in report["findings"])
    assert _file_hashes(tmp_path) == before


@pytest.mark.parametrize("orphan", [False, True])
@pytest.mark.parametrize("wal_state", ["fresh", "reused", "uncommitted_tail"])
def test_restore_reads_retained_wal_only_in_private_copy(tmp_path: Path, orphan: bool, wal_state: str):
    _write_finalized_observation(tmp_path)
    database = tmp_path / "state/secondary.sqlite"
    with closing(sqlite3.connect(database)) as writer:
        writer.executescript("CREATE TABLE parent(id INTEGER PRIMARY KEY); CREATE TABLE child(parent_id INTEGER REFERENCES parent(id));")
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO parent VALUES (1)")
        writer.execute("INSERT INTO child VALUES (?)", (99 if orphan else 1,))
        writer.commit()
        if wal_state == "reused":
            writer.execute("CREATE TABLE filler(value BLOB)")
            writer.executemany("INSERT INTO filler VALUES (zeroblob(1024))", [()] * 100)
            writer.commit()
            writer.execute("PRAGMA wal_checkpoint(RESTART)")
            writer.execute("INSERT INTO parent VALUES (2)")
            writer.commit()
        if wal_state == "uncommitted_tail":
            writer.execute("PRAGMA cache_size=1")
            writer.executemany("INSERT INTO child VALUES (99)", [()] * 1000)
        assert Path(f"{database}-wal").stat().st_size > 0
        # Capture the retained DB/WAL pair before SQLite's close/checkpoint.
        # An active Windows write lock makes SHM unreadable; historical capture
        # does not require that transient lock map to recover committed state.
        retained = {path: path.read_bytes() for path in (database, Path(f"{database}-wal"))}
    for path, content in retained.items():
        path.write_bytes(content)
    before = _file_hashes(tmp_path)

    report = verify_restored_state(tmp_path)

    assert report["ok"] is (not orphan), report["findings"]
    if orphan:
        assert any(item.startswith("sqlite_foreign_key_check:") for item in report["findings"])
    record = next(item for item in report["sqlite"] if item["path"] == "state/secondary.sqlite")
    assert record["source_sqlite"]["recovery_policy"] == "sqlite_native_committed_view"
    assert _file_hashes(tmp_path) == before


@pytest.mark.parametrize("legacy_daily", [False, True])
@pytest.mark.parametrize("suffix", ["-wal", "-journal"])
def test_restore_rejects_malformed_retained_journal_headers(tmp_path: Path, legacy_daily: bool, suffix: str):
    data_root = tmp_path / "data"
    _write_finalized_observation(data_root)
    if legacy_daily:
        exports = write_legacy_export(tmp_path / "history-source", "2026-08-23")
        historical = data_root / "runs/2026-08-23/_exports"
        shutil.copytree(exports, historical)
        database = historical / "local-cdr.sqlite"
    else:
        database = data_root / "state/secondary.sqlite"
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("CREATE TABLE evidence(value INTEGER)")
    Path(f"{database}{suffix}").write_bytes(b"malformed retained journal")
    before = _file_hashes(data_root)

    report = verify_restored_state(data_root)

    assert not report["ok"]
    assert any(item.startswith("sqlite_unreadable:") for item in report["findings"])
    assert _file_hashes(data_root) == before


def test_restore_preserves_legitimate_non_hot_rollback_remnant(tmp_path: Path):
    _write_finalized_observation(tmp_path)
    database = tmp_path / "state/secondary.sqlite"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA journal_mode=PERSIST")
        connection.execute("CREATE TABLE evidence(value INTEGER)")
        connection.execute("INSERT INTO evidence VALUES (1)")
        connection.commit()
    journal = Path(f"{database}-journal")
    assert journal.stat().st_size > 28 and journal.read_bytes()[:8] == bytes(8)
    before = _file_hashes(tmp_path)

    report = verify_restored_state(tmp_path)

    assert report["ok"], report["findings"]
    record = next(item for item in report["sqlite"] if item["path"] == "state/secondary.sqlite")
    assert record["source_sqlite"]["retained_journals"]["rollback"] == "non_hot_zero_header_preserved"
    assert _file_hashes(tmp_path) == before


def test_restore_recovers_hot_rollback_journal_only_in_private_copy(tmp_path: Path):
    database = tmp_path / "secondary.sqlite"
    journal = Path(f"{database}-journal")
    with closing(sqlite3.connect(database)) as writer:
        writer.execute("CREATE TABLE evidence(value BLOB)")
        writer.executemany("INSERT INTO evidence VALUES (?)", [(b"a" * 1024,)] * 100)
        writer.commit()
        writer.execute("PRAGMA cache_size=1")
        writer.execute("UPDATE evidence SET value = zeroblob(1024)")
        retained = {path: path.read_bytes() for path in (database, journal)}
        assert retained[journal][:8] == bytes.fromhex("d9d505f920a163d7")
    for path, content in retained.items():
        path.write_bytes(content)
    before = _file_hashes(tmp_path)

    with _restore_database_view(database) as (connection, snapshot):
        assert connection.execute("SELECT value FROM evidence LIMIT 1").fetchone()[0] == b"a" * 1024
        assert snapshot["retained_journals"]["rollback"] == "sqlite_native_committed_view"
    assert _file_hashes(tmp_path) == before


def test_restore_blocks_external_super_journal_before_writable_copy_open(tmp_path: Path, monkeypatch):
    database = tmp_path / "secondary.sqlite"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE evidence(value INTEGER)")
    sentinel = tmp_path / "external-super-journal"
    sentinel.write_bytes(b"must remain unchanged")
    name = str(sentinel.resolve()).encode("utf-8")
    magic = bytes.fromhex("d9d505f920a163d7")
    Path(f"{database}-journal").write_bytes(
        bytes(512) + name + len(name).to_bytes(4, "big") + sum(name).to_bytes(4, "big") + magic
    )
    before = _file_hashes(tmp_path)
    native_connect = sqlite3.connect

    def connect(source, *args, **kwargs):
        assert "mode=ro&immutable=1" in str(source), "journal policy must run before writable recovery"
        return native_connect(source, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    with pytest.raises(ValueError, match="super-journal"):
        with _restore_database_view(database):
            pytest.fail("external journal reference must not open")
    assert _file_hashes(tmp_path) == before


@pytest.mark.parametrize("historical_daily", [False, True])
def test_restore_rejects_orphan_foreign_keys_in_every_preserved_database(tmp_path: Path, historical_daily: bool):
    _write_finalized_observation(tmp_path)
    if historical_daily:
        database = tmp_path / "runs/2026-08-23/_exports/local-cdr.sqlite"
    else:
        database = tmp_path / "state/secondary.sqlite"
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as connection:
        connection.executescript(
            "CREATE TABLE schema_meta(key TEXT, value TEXT);"
            "INSERT INTO schema_meta VALUES ('version', '7');"
            "CREATE TABLE parent(id INTEGER PRIMARY KEY);"
            "CREATE TABLE child(id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id));"
            "INSERT INTO child VALUES (1, 99);"
        )
        connection.commit()
        assert connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall()
    before = _file_hashes(tmp_path)

    report = verify_restored_state(tmp_path)

    assert not report["ok"]
    assert any(finding.startswith("sqlite_foreign_key_check:") for finding in report["findings"])
    assert _file_hashes(tmp_path) == before
