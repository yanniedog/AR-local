"""Read-only preservation snapshot boundary tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

import cdr_historical_source as source_module
from cdr_historical_contract import HistoricalContractError
from cdr_historical_source import (
    ensure_output_separate,
    is_sqlite_transient,
    open_verified_snapshot,
)


SNAPSHOT_ID = "20260814T202526AEST-pi5-3dc9b4677"
MANIFEST_NAMES = (
    "capacity-policy-override-20260814.json",
    "pi-critical-source-sha256.txt",
    "pi-critical-verification.json",
    "pi-run-entries.txt",
    "pi-source-ledger-verification.json",
    "pi-source-special-entries.txt",
    "preservation-file-inventory.jsonl",
    "preservation-gate-status-20260814.json",
    "restore-copy-summary.json",
    "snapshot-plan.json",
)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _inventory_row(path: str, payload: bytes) -> dict[str, object]:
    return {
        "path": path,
        "type": "file",
        "bytes": len(payload),
        "mtime_utc": "2026-08-14T00:00:00Z",
        "sha256": _sha(payload),
    }


def make_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    collision: bool = False,
    transient: bool = False,
) -> tuple[Path, Path, dict[str, object]]:
    root = tmp_path / SNAPSHOT_ID
    manifests = root / "manifests"
    source = root / "pi" / "data"
    manifests.mkdir(parents=True)
    source.mkdir(parents=True)
    value = b'{"ok":true}\n'
    (source / "value.json").write_bytes(value)
    database = source / "test.sqlite"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE evidence (value TEXT NOT NULL)")
    connection.execute("INSERT INTO evidence VALUES ('kept')")
    connection.commit()
    connection.close()
    database_bytes = database.read_bytes()
    rows = [
        _inventory_row("pi/data/value.json", value),
        _inventory_row("pi/data/test.sqlite", database_bytes),
    ]
    critical_rows = [
        (_sha(value), "/srv/ar-local/data/value.json"),
        (_sha(database_bytes), "/srv/ar-local/data/test.sqlite"),
    ]
    if transient:
        for suffix, payload in (("-shm", b"transient-shm"), ("-wal", b"transient-wal")):
            path = source / f"test.sqlite{suffix}"
            path.write_bytes(payload)
            relative = f"pi/data/test.sqlite{suffix}"
            rows.append(_inventory_row(relative, payload))
            critical_rows.append((_sha(payload), f"/srv/ar-local/data/test.sqlite{suffix}"))
    if collision:
        rows.append(_inventory_row("PI/Data/VALUE.json", value))
    inventory = b"".join(
        (json.dumps(row, separators=(",", ":")) + "\n").encode() for row in rows
    )
    critical = "".join(
        f"{digest}  {path}\n" for digest, path in critical_rows
    ).encode()
    content = {
        "capacity-policy-override-20260814.json": b"{}\n",
        "pi-critical-source-sha256.txt": critical,
        "pi-critical-verification.json": b'{"ok":true}\n',
        "pi-run-entries.txt": b"2026-05-13\n",
        "pi-source-ledger-verification.json": b'{"checked":3,"findings":[]}\n',
        "pi-source-special-entries.txt": b"none\n",
        "preservation-file-inventory.jsonl": inventory,
        "preservation-gate-status-20260814.json": b'{"ok":true}\n',
        "restore-copy-summary.json": b'{"ok":true}\n',
        "snapshot-plan.json": b'{"ok":true}\n',
    }
    for name, payload in content.items():
        (manifests / name).write_bytes(payload)
    descriptors = [
        {"path": f"manifests/{name}", "bytes": len(content[name]), "sha256": _sha(content[name])}
        for name in MANIFEST_NAMES
    ]
    evidence = {
        "snapshot_id": SNAPSHOT_ID,
        "retrieval": {"inventory_relative_path": "manifests/preservation-file-inventory.jsonl"},
        "manifests": descriptors,
    }
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    corpus = {
        "snapshot_id": SNAPSHOT_ID,
        "critical_population": {
            "files": len(rows),
            "bytes": sum(int(row["bytes"]) for row in rows),
        },
        "retained_dates": 1,
        "legacy_ledger_records": 3,
    }
    monkeypatch.setattr(source_module, "EVIDENCE_PATH", evidence_path)
    monkeypatch.setattr(source_module, "validate_contract_tree", lambda: corpus)
    return root, evidence_path, corpus


def test_snapshot_verifies_all_manifests_then_strict_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, corpus = make_snapshot(tmp_path, monkeypatch)
    snapshot = open_verified_snapshot(root, rehash_critical=True)
    assert snapshot.dates == ("2026-05-13",)
    assert len(snapshot.critical) == corpus["critical_population"]["files"]
    assert snapshot.read_json("pi/data/value.json") == {"ok": True}


def test_manifest_tamper_fails_before_absent_source_is_considered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, _ = make_snapshot(tmp_path, monkeypatch)
    (root / "manifests" / MANIFEST_NAMES[0]).write_bytes(b"tampered")
    (root / "pi" / "data" / "value.json").unlink()
    with pytest.raises(HistoricalContractError, match="manifest byte count mismatch"):
        open_verified_snapshot(root)


def test_inventory_rejects_casefold_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, _ = make_snapshot(tmp_path, monkeypatch, collision=True)
    with pytest.raises(HistoricalContractError, match="case-fold"):
        open_verified_snapshot(root)


def test_sqlite_is_immutable_read_only_query_only_without_sidecars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, _ = make_snapshot(tmp_path, monkeypatch)
    snapshot = open_verified_snapshot(root)
    database = root / "pi" / "data" / "test.sqlite"
    connection = snapshot.connect_sqlite("pi/data/test.sqlite")
    try:
        assert connection.execute("PRAGMA query_only").fetchone() == (1,)
        assert connection.execute("SELECT value FROM evidence").fetchone() == ("kept",)
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("INSERT INTO evidence VALUES ('mutated')")
    finally:
        connection.close()
    assert not database.with_name("test.sqlite-wal").exists()
    assert not database.with_name("test.sqlite-journal").exists()


def test_source_mutation_fails_final_rehash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, _ = make_snapshot(tmp_path, monkeypatch)
    snapshot = open_verified_snapshot(root)
    (root / "pi" / "data" / "value.json").write_bytes(b'{"ok":0}\n')
    with pytest.raises(HistoricalContractError, match="source mutation"):
        snapshot.rehash(["pi/data/value.json"])


def test_rehash_audit_classifies_transient_drift_without_weakening_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, _ = make_snapshot(tmp_path, monkeypatch, transient=True)
    snapshot = open_verified_snapshot(root)
    sidecar = root / "pi" / "data" / "test.sqlite-shm"
    sidecar.write_bytes(b"changed-shm")
    audit = snapshot.audit_rehash(snapshot.critical)
    assert audit.checked_files == 4
    assert audit.verified_files == 3
    assert [item.path for item in audit.findings] == ["pi/data/test.sqlite-shm"]
    assert audit.findings[0].source_role == "sqlite_transient_sidecar"
    with pytest.raises(HistoricalContractError, match="source mutation"):
        snapshot.rehash(snapshot.critical)


def test_only_wal_and_shm_are_transient_sqlite_evidence() -> None:
    assert is_sqlite_transient("pi/data/local-cdr.sqlite-shm")
    assert is_sqlite_transient("pi/data/local-cdr.sqlite-wal")
    assert not is_sqlite_transient("pi/data/local-cdr.sqlite")


def test_source_output_overlap_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "snapshot"
    source.mkdir()
    with pytest.raises(HistoricalContractError, match="overlap"):
        ensure_output_separate(source, source / "derived")
    with pytest.raises(HistoricalContractError, match="overlap"):
        ensure_output_separate(source, tmp_path)


def test_symlink_or_reparse_source_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, _ = make_snapshot(tmp_path, monkeypatch)
    snapshot = open_verified_snapshot(root)
    target = root / "pi" / "data" / "value.json"
    original = tmp_path / "original.json"
    target.replace(original)
    try:
        target.symlink_to(original)
    except OSError:
        pytest.skip("symlink creation is unavailable on this Windows host")
    with pytest.raises(HistoricalContractError, match="reparse/link"):
        snapshot.read_bytes("pi/data/value.json")
