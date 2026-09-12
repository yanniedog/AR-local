"""Pi Drive backup safety and failure semantics, using real temporary SQLite."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import pi_drive_backup as backup
import pi_drive_backup_source as source
import pi_drive_backup_enroll as enroll
from ar_local_operation_lock import production_lock


@pytest.fixture
def layout(tmp_path: Path):
    data = tmp_path / "data"
    (data / "runs/2026-09-10/_exports").mkdir(parents=True)
    (data / "state").mkdir()
    db = data / "runs/2026-09-10/_exports/local-cdr.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE capture (id INTEGER PRIMARY KEY, observed_at TEXT NOT NULL)")
        conn.execute("INSERT INTO capture VALUES (1, '2026-09-10T01:00:00+10:00')")
    (data / "state/2026-09-10.done.json").write_text('{"date":"2026-09-10"}')
    (data / "state/publication-manifest.json").write_text('{"generation_id":"recorded-test-generation"}')
    spool = tmp_path / "spool"
    spool.mkdir()
    password = spool / "password"
    password.write_text("temporary-test-password")
    remote = spool / "rclone.conf"
    remote.write_text('[ar_local_drive]\ntype = drive\nscope = drive.file\ntoken = {"refresh_token":"test-transport-token"}\n')
    password.chmod(0o600)
    remote.chmod(0o600)
    return backup.Config(data.resolve(), spool.resolve(), "rclone:ar_local_drive:test-backup/restic",
                         password.resolve(), remote.resolve(), [], min_free_bytes=0)


def test_snapshot_reads_committed_wal_and_does_not_modify_source(layout):
    database = layout.data / "state/live.sqlite"
    live = sqlite3.connect(database)
    try:
        live.execute("PRAGMA journal_mode=WAL")
        live.execute("CREATE TABLE observations (id INTEGER PRIMARY KEY)")
        live.execute("INSERT INTO observations VALUES (17)")
        live.commit()
        before = source.digest(database)
        stage = layout.spool / "stage"
        stage.mkdir()
        manifest = source.freeze(layout.data, stage, controls=[], guard=lambda: None)
        row = next(row for row in manifest["files"] if row["logical_path"].endswith("live.sqlite"))
        assert row["direct"] is False
        with sqlite3.connect(row["backup_path"]) as restored:
            assert restored.execute("SELECT id FROM observations").fetchone() == (17,)
        assert source.digest(database) == before
        assert not any(row["logical_path"].endswith("-shm") for row in manifest["files"])
        originals = [row for row in manifest["files"] if row.get("sqlite_original")]
        assert any(row["logical_path"].endswith("-wal") for row in originals)
        original_db = next(row for row in originals if row["source_path"] == database.as_posix())
        assert original_db["sha256"] == before
    finally:
        live.close()


def test_immutable_db_keeps_exact_bytes_and_mutable_control_is_frozen(layout):
    stage = layout.spool / "stage"
    stage.mkdir()
    manifest = source.freeze(layout.data, stage, controls=[], guard=lambda: None)
    database = next(row for row in manifest["files"] if row["sqlite"])
    control = next(row for row in manifest["files"] if row["logical_path"].endswith("done.json"))
    assert database["direct"] is True
    assert Path(database["backup_path"]) == Path(database["source_path"])
    Path(control["source_path"]).write_text('{"date":"changed-after-freeze"}')
    assert Path(control["backup_path"]).read_text() == '{"date":"2026-09-10"}'
    assert not (layout.data / "state/daily-ingest.lock").exists()


def test_active_ingest_blocks_freeze(layout):
    with production_lock(layout.data / "state/daily-ingest.lock", "test-ingest"):
        with pytest.raises(RuntimeError, match="production lock is active"):
            source.freeze(layout.data, layout.spool / "stage", controls=[], guard=lambda: None)


def test_direct_source_change_rejects_acceptance(layout):
    manifest = source.freeze(layout.data, layout.spool / "stage", controls=[], guard=lambda: None)
    direct = next(row for row in manifest["files"] if row["direct"])
    with Path(direct["source_path"]).open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(RuntimeError, match="immutable source changed"):
        source.verify_direct_sources(manifest)


def test_missing_unknown_and_recursive_sources_fail_closed(layout):
    with pytest.raises(ValueError, match="separate"):
        source.validate_layout(layout.data, layout.data / "backup", [])
    unknown = layout.data / "new-unclassified-store"
    unknown.mkdir()
    with pytest.raises(ValueError, match="unclassified"):
        source.freeze(layout.data, layout.spool / "stage", controls=[], guard=lambda: None)


def test_credentials_and_telemetry_are_excluded(layout):
    (layout.data / "netdata").mkdir()
    (layout.data / "netdata/credential-token").write_text("secret")
    (layout.data / "state/provider.env").write_text("secret")
    manifest = source.freeze(layout.data, layout.spool / "stage", controls=[], guard=lambda: None)
    assert "state/provider.env" in manifest["excluded"]
    assert not any("netdata" in row["logical_path"] for row in manifest["files"])
    assert all("secret" not in Path(row["backup_path"]).read_bytes().decode(errors="ignore")
               for row in manifest["files"])


def test_symlinks_rejected(layout):
    linked = layout.data / "state/linked.json"
    try:
        linked.symlink_to(layout.data / "state/2026-09-10.done.json")
    except OSError:
        pytest.skip("host does not permit ordinary-user symlinks")
    with pytest.raises(ValueError, match="symlink"):
        source.freeze(layout.data, layout.spool / "stage", controls=[], guard=lambda: None)


def test_restore_hash_and_sqlite_integrity(layout):
    manifest = source.freeze(layout.data, layout.spool / "stage", controls=[], guard=lambda: None)
    target = layout.spool / "restored"
    for row in manifest["files"]:
        path = target / source.restore_relative(row["backup_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(row["backup_path"], path)
    result = source.verify_restore(target, manifest["files"])
    assert result["result"] == "PASS"
    assert result["sqlite"][0]["integrity_check"] == "ok"
    first = target / source.restore_relative(manifest["files"][0]["backup_path"])
    first.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="restored bytes differ"):
        source.verify_restore(target, manifest["files"])


def test_foreign_key_violation_is_not_restore_success(tmp_path):
    database = tmp_path / "bad.sqlite"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE child (parent_id INTEGER REFERENCES parent(id))")
        conn.execute("INSERT INTO child VALUES (99)")
    with pytest.raises(ValueError, match="SQLite restore integrity"):
        source.sqlite_checks(database)


def test_readiness_never_initializes_or_logs_credentials(layout, monkeypatch):
    monkeypatch.setattr(backup.shutil, "which", lambda _value: "/test/executable")
    result = backup.readiness(layout)
    assert result["result"] == "PASS"
    assert result["remote_checked"] is False
    layout.rclone_config.write_text('[ar_local_drive]\ntype = drive\nscope = drive\ntoken = {"refresh_token":"SECRET_TOKEN"}\n')
    result = backup.readiness(layout)
    assert result["result"] == "BLOCKED"
    assert "SECRET_TOKEN" not in json.dumps(result)
    assert "drive.file" in result["reasons"][0]


def test_missing_credentials_are_blocked(layout, monkeypatch):
    monkeypatch.setattr(backup.shutil, "which", lambda _value: "/test/executable")
    layout.password.unlink()
    with pytest.raises(backup.Blocked, match="password"):
        backup.run_backup(layout)
    assert not (layout.spool / "latest-verified.json").exists()


def test_queued_requests_are_unique_and_disabled_unconfigured(layout, monkeypatch):
    monkeypatch.delenv("AR_LOCAL_DRIVE_BACKUP_SPOOL", raising=False)
    assert backup.request_backup("terminal") is None
    first = backup.request_backup("terminal", spool=layout.spool)
    second = backup.request_backup("repair", spool=layout.spool)
    assert first != second and first.exists() and second.exists()


class FakeRestic:
    """Transport fault injector, not a substitute for a real Drive restore proof."""
    def __init__(self, config):
        self.config = config
        self.saved = {}
        self.calls = []
        self.fail = None
        self.after_backup = None

    def run(self, *args):
        self.calls.append(args)
        assert not (self.config.data / "state/daily-ingest.lock").exists()
        if args[0] == self.fail:
            raise RuntimeError("injected transport failure")
        if args[0] == "backup":
            raw = Path(args[args.index("--files-from-raw") + 1]).read_bytes()
            self.saved = {path.decode(): Path(path.decode()).read_bytes() for path in raw.split(b"\x00") if path}
            if self.after_backup:
                self.after_backup()
            return json.dumps({"message_type": "summary", "snapshot_id": "a" * 64, "data_added_packed": 100})
        if args[0] == "stats":
            return '{"total_size":100}'
        if args[0] == "restore":
            target = Path(args[args.index("--target") + 1])
            for path, value in self.saved.items():
                dst = target / source.restore_relative(path)
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(value)
        return "{}"


@pytest.fixture
def transport(layout, monkeypatch):
    client = FakeRestic(layout)
    monkeypatch.setattr(backup, "Restic", lambda _config: client)
    monkeypatch.setattr(backup.shutil, "which", lambda _value: "/test/executable")
    monkeypatch.setattr(backup, "now", lambda: datetime(2026, 9, 11, 4, 0, tzinfo=backup.TZ))
    return client


def test_initial_restore_then_unchanged_and_control_only_update(layout, transport):
    first = backup.run_backup(layout, force=True)
    assert first["result"] == "PASS"
    assert first["restore"]["full"] is True
    assert first["restore"]["published_identity_files"]
    assert first["uploaded_bytes"] == 100
    second = backup.run_backup(layout, force=True)
    assert second["action"] == "UNCHANGED"
    assert second["uploaded_bytes"] == 0
    assert len([call for call in transport.calls if call[0] == "backup"]) == 1
    (layout.data / "state/publication-manifest.json").write_text('{"generation_id":"corrected"}')
    third = backup.run_backup(layout, force=True)
    assert third["action"] == "BACKUP"
    assert third["content_sha256"] != first["content_sha256"]


@pytest.mark.parametrize("phase", ["backup", "check", "restore"])
def test_failure_does_not_advance_receipt_or_ack_queue(layout, transport, phase):
    request = backup.request_backup("terminal", spool=layout.spool)
    transport.fail = phase
    with pytest.raises(RuntimeError, match="injected transport"):
        backup.run_backup(layout, force=True)
    assert request.exists()
    assert not (layout.spool / "latest-verified.json").exists()
    assert len(list((layout.spool / "receipts").glob("*.FAIL.json"))) == 1
    assert not list(layout.spool.glob("freeze-*"))


def test_request_arriving_during_transfer_survives_acknowledgement(layout, transport):
    original = backup.request_backup("terminal", spool=layout.spool)
    transport.after_backup = lambda: backup.request_backup("new-repair", spool=layout.spool)
    backup.run_backup(layout, force=True)
    assert not original.exists()
    assert len(list((layout.spool / "requests").glob("*.json"))) == 1


def test_weekly_restore_and_history_rotation(layout, transport, monkeypatch):
    first = backup.run_backup(layout, force=True)
    monkeypatch.setattr(backup, "now", lambda: datetime(2026, 9, 18, 4, 0, tzinfo=backup.TZ))
    second = backup.run_backup(layout, force=True)
    assert second["restore"]["result"] == "PASS"
    assert second["restore"]["full"] is False
    assert second["restore_rotation"] == first["restore_rotation"] + 1


@pytest.mark.parametrize("hour,minute,blocked", [(0,29,False),(0,30,True),(1,0,True),(3,29,True),(3,30,False)])
def test_quiet_window_blocks_even_persistent_catchup(monkeypatch, hour, minute, blocked):
    monkeypatch.setattr(backup, "now", lambda: datetime(2026, 10, 4, hour, minute, tzinfo=backup.TZ))
    if blocked:
        with pytest.raises(backup.Blocked):
            backup.guard_window()
    else:
        backup.guard_window()


def test_atomic_receipt_refuses_history_overwrite(tmp_path):
    receipt = tmp_path / "receipt.json"
    backup.atomic_json(receipt, {"result": "PASS"}, immutable=True)
    with pytest.raises(ValueError, match="immutable"):
        backup.atomic_json(receipt, {"result": "FAIL"}, immutable=True)
    assert json.loads(receipt.read_text())["result"] == "PASS"
    assert not list(tmp_path.glob("*.partial-*"))


def test_legacy_wal_without_shared_memory_is_preserved_without_source_writes(layout):
    live_path = layout.spool / "writer.sqlite"
    live = sqlite3.connect(live_path)
    try:
        live.execute("PRAGMA journal_mode=WAL")
        live.execute("CREATE TABLE observations (id INTEGER PRIMARY KEY)")
        live.execute("INSERT INTO observations VALUES (71)")
        live.commit()
        legacy = layout.data / "runs/2026-09-10/_exports/legacy.sqlite"
        shutil.copy2(live_path, legacy)
        shutil.copy2(Path(str(live_path) + "-wal"), Path(str(legacy) + "-wal"))
        before = {path.name: source.digest(path) for path in legacy.parent.glob("legacy.sqlite*")}
        manifest = source.freeze(layout.data, layout.spool / "stage", controls=[], guard=lambda: None)
        after = {path.name: source.digest(path) for path in legacy.parent.glob("legacy.sqlite*")}
        assert before == after
        row = next(row for row in manifest["files"] if row["source_path"] == legacy.as_posix() and row["sqlite"])
        assert row["direct"] is False
        with sqlite3.connect(row["backup_path"]) as snapshot:
            assert snapshot.execute("SELECT id FROM observations").fetchone() == (71,)
        originals = [row for row in manifest["files"] if row.get("sqlite_original")]
        assert {Path(row["source_path"]).name: row["sha256"] for row in originals} == before
    finally:
        live.close()


@pytest.mark.parametrize("line", ['token = {"refresh_token":"SECRET"}', "https://provider.example/?access_token=SECRET",
                                  "http://127.0.0.1:53682/?code=SECRET"])
def test_enrollment_filter_withholds_provider_and_token_lines(line):
    assert enroll.filtered_url(line) is None


def test_enrollment_filter_emits_only_loopback_authorization_url():
    assert enroll.filtered_url("NOTICE: Go to http://127.0.0.1:53682/auth?state=safe-state_12 for consent") == (
        "http://127.0.0.1:53682/auth?state=safe-state_12")


def test_access_token_without_refresh_token_is_blocked(layout, monkeypatch):
    monkeypatch.setattr(backup.shutil, "which", lambda _: "/test/executable")
    layout.rclone_config.write_text('[ar_local_drive]\ntype = drive\nscope = drive.file\ntoken = {"access_token":"SECRET"}\n')
    result = backup.readiness(layout)
    assert result["result"] == "BLOCKED"
    assert "SECRET" not in json.dumps(result)


def test_empty_retained_wal_preserves_exact_direct_database_bytes(layout):
    db = layout.data / "runs/2026-09-10/_exports/local-cdr.sqlite"
    wal = Path(str(db) + "-wal")
    wal.write_bytes(b"")
    manifest = source.freeze(layout.data, layout.spool / "stage", controls=[], guard=lambda: None)
    try:
        row = next(row for row in manifest["files"] if row["sqlite"])
        assert row["direct"] is True
        assert row["sha256"] == source.digest(db)
        original = next(row for row in manifest["files"] if row.get("sqlite_original"))
        assert original["backup_path"] == wal.as_posix()
        assert original["size"] == 0 and original["direct"] is True
        wal.write_bytes(b"journal changed after freeze")
        with pytest.raises(RuntimeError, match="journal changed|immutable source changed"):
            source.verify_direct_sources(manifest)
    finally:
        backup.close_manifest(manifest)


def test_old_merged_snapshot_digest_is_not_reused_for_new_direct_input(layout):
    from pi_drive_backup_manifest import close_manifest

    db = layout.data / "runs/2026-09-10/_exports/local-cdr.sqlite"
    prior = {"files": [{"logical_path": "data/runs/2026-09-10/_exports/local-cdr.sqlite",
                         "direct": False, "source_identity": source.fingerprint(db), "sha256": "0" * 64}]}
    manifest = source.freeze(layout.data, layout.spool / "stage", controls=[], guard=lambda: None, prior=prior)
    try:
        row = next(row for row in manifest["files"] if row["sqlite"])
        assert row["sha256"] == source.digest(db)
    finally:
        close_manifest(manifest)


def test_full_restore_has_no_per_file_filter_and_weekly_filters_use_namespaces(layout, transport):
    backup.run_backup(layout, force=True)
    full = next(call for call in transport.calls if call[0] == "restore")
    assert "--include-file" not in full
    rows = [{"logical_path": f"data/runs/2026-09-10/_exports/file-{n}.json",
             "backup_path": f"/srv/ar-local/data/runs/2026-09-10/_exports/file-{n}.json"}
            for n in range(1000)]
    assert backup.restore_includes(rows) == ["/srv/ar-local/data/runs/2026-09-10"]


def test_streamed_manifest_preserves_wire_bytes_and_bounds_memory_at_scale(tmp_path):
    import tracemalloc
    from pi_drive_backup_manifest import ManifestIndex, close_manifest, content_digest, load_manifest

    tracemalloc.start()
    index = ManifestIndex(tmp_path / "manifest-index.sqlite")
    document = {"schema": source.SCHEMA, "files": index.rows(), "excluded": index.rows("excluded")}
    loaded = {}
    try:
        for number in range(20000):
            logical = f"data/runs/2026-09-10/retained-provider/product-{number:06d}/product-detail.json"
            physical = "/srv/ar-local/" + logical
            index.append({"logical_path": logical, "backup_path": physical, "source_path": physical,
                          "source_identity": [number, 1720000000000000000, 1720000000000000001, number, 1],
                          "size": number, "sha256": "0" * 64, "direct": True, "sqlite": False,
                          "mode": "0o644", "uid": 1000, "gid": 1000})
        index.exclude("state/temporary.lock")
        index.db.commit()
        document["content_sha256"] = content_digest(document["files"])
        target = tmp_path / "manifest.json"
        backup.atomic_json(target, document, immutable=True)
        loaded = load_manifest(target, tmp_path / "read-index.sqlite")
        assert len(loaded["files"]) == 20000
        assert loaded["files"].get(document["files"][123]["logical_path"]) == document["files"][123]
        assert loaded["content_sha256"] == content_digest(loaded["files"])
        assert list(loaded["excluded"]) == ["state/temporary.lock"]
        assert target.stat().st_size > 10 * 1024 * 1024
        _, peak = tracemalloc.get_traced_memory()
        # Old lists plus json.dumps/decode scale with every row. The index cache
        # is separately capped at 2 MiB and Python handles one decoded row.
        assert peak < 12 * 1024 * 1024
    finally:
        close_manifest(document)
        close_manifest(loaded)
        tracemalloc.stop()


def test_disk_manifest_rejects_case_collisions_and_truncated_wire_json(tmp_path):
    from pi_drive_backup_manifest import ManifestIndex, load_manifest

    index = ManifestIndex(tmp_path / "manifest-index.sqlite")
    try:
        index.append({"logical_path": "data/state/Marker.json"})
        with pytest.raises(ValueError, match="case-insensitive"):
            index.append({"logical_path": "data/state/marker.json"})
    finally:
        index.close()
    wire = tmp_path / "bad.json"
    wire.write_text('{"files":[{"logical_path":"data/state/marker.json"}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_manifest(wire, tmp_path / "broken-index.sqlite")


def test_streamed_json_and_content_digest_match_existing_wire_format(tmp_path):
    from pi_drive_backup_manifest import ManifestIndex, close_manifest, content_digest

    index = ManifestIndex(tmp_path / "manifest-index.sqlite")
    rows = [{"logical_path": "data/state/first.json", "sha256": "0" * 64, "size": 1},
            {"logical_path": "data/state/second.json", "sha256": "1" * 64, "size": 2}]
    document = {"schema": source.SCHEMA, "files": index.rows(), "excluded": index.rows("excluded")}
    try:
        for row in reversed(rows):
            index.append(row)
        index.exclude("state/temporary.lock")
        index.db.commit()
        document["content_sha256"] = content_digest(document["files"])
        expected = {**document, "files": rows, "excluded": ["state/temporary.lock"]}
        assert document["content_sha256"] == source.hashlib.sha256(source.canonical_json_bytes(rows)).hexdigest()
        target = tmp_path / "manifest.json"
        backup.atomic_json(target, document)
        assert target.read_bytes() == source.canonical_json_bytes(expected)
    finally:
        close_manifest(document)


def test_disk_index_failure_is_recorded_without_acknowledging_backup(layout, transport, monkeypatch):
    queued = backup.request_backup("terminal", spool=layout.spool)

    def unavailable_index(*args, **kwargs):
        raise sqlite3.OperationalError("injected unavailable index")

    monkeypatch.setattr(backup, "freeze", unavailable_index)
    with pytest.raises(sqlite3.Error, match="unavailable index"):
        backup.run_backup(layout, force=True)
    assert queued.exists()
    assert len(list((layout.spool / "receipts").glob("*.FAIL.json"))) == 1
    assert not (layout.spool / "latest-verified.json").exists()


@pytest.mark.parametrize("fault", ["missing_manifest", "null_manifest", "traversal", "failed", "changed_manifest"])
def test_bad_accepted_receipt_cannot_become_no_work_success(layout, transport, fault):
    backup.run_backup(layout, force=True)
    accepted = layout.spool / "latest-verified.json"
    value = json.loads(accepted.read_text())
    if fault == "missing_manifest":
        value.pop("manifest_path")
    elif fault == "null_manifest":
        value["manifest_path"] = None
    elif fault == "traversal":
        value["manifest_path"] = "../outside.json"
    elif fault == "failed":
        value["result"] = "FAIL"
    else:
        (layout.spool / value["manifest_path"]).write_text("{}")
    accepted.write_text(json.dumps(value))
    before, calls = accepted.read_bytes(), len(transport.calls)
    # Same-day empty queue would previously return PASS/NO_WORK without checking
    # that this is still a valid accepted receipt. The fault must stay visible.
    with pytest.raises(ValueError, match="accepted"):
        backup.run_backup(layout)
    assert accepted.read_bytes() == before
    assert len(transport.calls) == calls
