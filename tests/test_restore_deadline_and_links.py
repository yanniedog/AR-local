"""Filesystem and SQLite controls; no invented financial rows or exports."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

import ar_local_restore_verification as restore
import cdr_observation_db as canonical
import cdr_sqlite_budget as budget
import pi_backup_foundation as backup
from cdr_quality_sqlite import database_files, database_view
from tests.test_ar_local_restore_integrity import _write_current_finalized
from tests.test_pi_backup_foundation import make_policy, valid_snapshot_manifest


LONG_QUERY = "WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<1000000) SELECT sum(x) FROM n"


def _control_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript("CREATE TABLE evidence(id INTEGER PRIMARY KEY, value TEXT); CREATE INDEX evidence_value ON evidence(value);")
        connection.executemany("INSERT INTO evidence VALUES (?, ?)", ((i, str(i)) for i in range(5000)))


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm", "-journal"])
def test_rejects_dangling_database_or_journal_before_open(tmp_path, monkeypatch, suffix):
    database = tmp_path / "preserved.sqlite"
    if suffix:
        _control_database(database)
    linked = Path(f"{database}{suffix}")
    linked.symlink_to(tmp_path / "missing-target")
    source_hash = hashlib.sha256(database.read_bytes()).hexdigest() if suffix else None

    def unexpected_open(*_args, **_kwargs):
        pytest.fail("a rejected source must never open a SQLite connection")

    monkeypatch.setattr(sqlite3, "connect", unexpected_open)
    with pytest.raises(ValueError, match="cannot be linked"):
        with database_view(database):
            pytest.fail("linked database accepted")
    assert linked.is_symlink()
    assert not (tmp_path / "missing-target").exists()
    if suffix:
        assert hashlib.sha256(database.read_bytes()).hexdigest() == source_hash
    report = restore.verify_restored_state(tmp_path)
    assert not report["ok"]
    assert f"sqlite_unreadable:{database}" in report["findings"]


def test_missing_database_does_not_create_an_empty_recovery_copy(tmp_path):
    with pytest.raises(ValueError, match="missing or not a regular file"):
        with database_view(tmp_path / "absent.sqlite"):
            pytest.fail("missing source accepted")
    assert list(tmp_path.iterdir()) == []


def test_non_regular_journal_is_rejected(tmp_path):
    database = tmp_path / "preserved.sqlite"
    _control_database(database)
    Path(f"{database}-wal").mkdir()
    with pytest.raises(ValueError, match="journal is not a regular file"):
        database_files(database)


@pytest.mark.parametrize("phase", ["quick_check", "integrity_check", "foreign_key_check"])
def test_real_sqlite_health_scans_are_interrupted_and_handler_is_removed(tmp_path, monkeypatch, phase):
    database = tmp_path / "control.sqlite"
    _control_database(database)
    with sqlite3.connect(database) as connection:
        connection.executescript("CREATE TABLE child(parent INTEGER REFERENCES evidence(id)); INSERT INTO child SELECT id FROM evidence;")
    before = database.read_bytes()
    clock, queries = [0.0], []
    monkeypatch.setattr(budget.time, "monotonic", lambda: clock[0])

    def trace(sql):
        queries.append(sql)
        if sql == f"PRAGMA {phase}":
            clock[0] = 301.0

    with closing(sqlite3.connect(database)) as connection:
        connection.set_trace_callback(trace)
        with pytest.raises(TimeoutError, match="deadline exceeded"):
            restore._sqlite_health(connection)
        assert f"PRAGMA {phase}" in queries
        # The actual interrupted connection remains usable after the scope.
        assert connection.execute(LONG_QUERY).fetchone()[0] == 500000500000
    assert database.read_bytes() == before
    assert budget.current_deadline() is None


def test_nested_sqlite_health_restores_outer_progress_guard(tmp_path, monkeypatch):
    database = tmp_path / "control.sqlite"
    _control_database(database)
    clock = [0.0]
    monkeypatch.setattr(budget.time, "monotonic", lambda: clock[0])
    with closing(sqlite3.connect(database)) as connection:
        with pytest.raises(TimeoutError):
            with budget.audit_budget(20.0):
                restore._sqlite_health(connection)
                clock[0] = 21.0
                connection.execute(LONG_QUERY).fetchone()
    assert budget.current_deadline() is None


@pytest.mark.parametrize("open_view", ["canonical", "preserved"])
def test_separately_opened_immutable_connections_share_sqlite_deadline(tmp_path, monkeypatch, open_view):
    database = tmp_path / "control.sqlite"
    _control_database(database)
    before = database.read_bytes()
    clock = [0.0]
    monkeypatch.setattr(budget.time, "monotonic", lambda: clock[0])
    with pytest.raises(TimeoutError):
        with budget.audit_budget(20.0):
            context = closing(canonical._connect_immutable(database)) if open_view == "canonical" else database_view(database)
            with context as opened:
                connection = opened if open_view == "canonical" else opened[0]
                clock[0] = 21.0
                connection.execute(LONG_QUERY).fetchone()
    assert database.read_bytes() == before
    assert budget.current_deadline() is None


def test_shared_budget_stops_inventory_before_later_database(tmp_path, monkeypatch):
    for name in ("a", "b", "c"):
        _control_database(tmp_path / f"{name}.sqlite")
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    clock, calls = [0.0], []
    monkeypatch.setattr(budget.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(restore, "RESTORE_BUDGET_SECONDS", 350)
    original = restore._sqlite_health

    def health(connection):
        result = original(connection)
        calls.append(True)
        clock[0] += 200
        return result

    monkeypatch.setattr(restore, "_sqlite_health", health)
    with pytest.raises(TimeoutError):
        restore.verify_restored_state(tmp_path)
    assert len(calls) == 2
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


@pytest.mark.parametrize("phase", ["quick_check", "integrity_check", "foreign_key_check"])
def test_actual_canonical_restore_cannot_pass_after_scan_budget(tmp_path, monkeypatch, phase):
    # Reuse the existing retained real-run fixture and its normal finalizer.
    _write_current_finalized(tmp_path)
    before = {path.relative_to(tmp_path).as_posix(): path.read_bytes()
              for path in tmp_path.rglob("*") if path.is_file()}
    clock, queries = [0.0], []
    original = budget.install_progress_deadline
    monkeypatch.setattr(budget.time, "monotonic", lambda: clock[0])

    def install(connection):
        original(connection)

        def trace(sql):
            queries.append(sql)
            if sql == f"PRAGMA {phase}":
                clock[0] = 301.0

        connection.set_trace_callback(trace)

    monkeypatch.setattr(budget, "install_progress_deadline", install)
    with pytest.raises(TimeoutError):
        restore.verify_restored_state(tmp_path)
    assert f"PRAGMA {phase}" in queries
    assert {path.relative_to(tmp_path).as_posix(): path.read_bytes()
            for path in tmp_path.rglob("*") if path.is_file()} == before
    assert budget.current_deadline() is None


def _snapshot(tmp_path):
    policy = make_policy(tmp_path)
    snapshot = policy.backup_dir / "snapshots/control-snapshot"
    (snapshot / "data").mkdir(parents=True)
    (snapshot / "data/evidence.txt").write_text("filesystem control\n", encoding="utf-8")
    _control_database(snapshot / "data/preserved.sqlite")
    macro = snapshot / "macro/local-macro.sqlite"
    macro.parent.mkdir()
    with sqlite3.connect(macro) as connection:
        connection.executescript("CREATE TABLE series_observations(id INTEGER); CREATE TABLE ingest_runs(id INTEGER);")
    files = [{"path": path.relative_to(snapshot).as_posix(), "size": path.stat().st_size,
              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
             for path in sorted(snapshot.rglob("*")) if path.is_file()]
    (snapshot / "manifest.json").write_text(json.dumps(valid_snapshot_manifest(files)), encoding="utf-8")
    latest = policy.backup_dir / "latest-restore.json"
    latest.write_text('{"result":"PASS","receipt_path":"receipts/previous.json"}\n', encoding="utf-8")
    return policy, snapshot, latest


@pytest.mark.parametrize("expire_during", ["snapshot", "copy", "database", "macro"])
def test_restore_timeout_writes_failure_receipt_cleans_copy_and_keeps_last_pass(tmp_path, monkeypatch, expire_during):
    policy, snapshot, latest = _snapshot(tmp_path)
    before = {path.relative_to(snapshot).as_posix(): path.read_bytes() for path in snapshot.rglob("*") if path.is_file()}
    previous, clock = latest.read_bytes(), [0.0]
    monkeypatch.setattr(budget.time, "monotonic", lambda: clock[0])
    original_verify, original_copy, original_connect = backup.verify_snapshot, backup.shutil.copytree, sqlite3.connect
    if expire_during != "database":
        monkeypatch.setattr(backup, "_verify_restored_state", lambda _root: {"ok": True, "findings": []})

    def verify(*args, **kwargs):
        result = original_verify(*args, **kwargs)
        if expire_during == "snapshot":
            clock[0] = budget.RESTORE_BUDGET_SECONDS + 1
        return result

    def copy(*args, **kwargs):
        result = original_copy(*args, **kwargs)
        if expire_during == "copy":
            clock[0] = budget.RESTORE_BUDGET_SECONDS + 1
        return result

    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        if expire_during in {"database", "macro"}:
            def trace(sql):
                if sql == "PRAGMA quick_check":
                    clock[0] = budget.RESTORE_BUDGET_SECONDS + 1
            connection.set_trace_callback(trace)
        return connection

    monkeypatch.setattr(backup, "verify_snapshot", verify)
    monkeypatch.setattr(backup.shutil, "copytree", copy)
    monkeypatch.setattr(sqlite3, "connect", connect)
    with pytest.raises(RuntimeError, match="receipt="):
        backup.restore_drill(policy, "control-snapshot", tmp_path / "scratch", "pytest", ["restore-drill"])
    receipts = list((policy.backup_dir / "receipts").glob("*.restore.*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["result"] == "FAIL"
    assert receipt["checks"]["findings"] == ["restore_exception:TimeoutError"]
    assert not receipt["scratch_retained"]
    assert latest.read_bytes() == previous
    assert {path.relative_to(snapshot).as_posix(): path.read_bytes() for path in snapshot.rglob("*") if path.is_file()} == before
