"""Off-device ledger replication + restore verification (audit Phase 0A)."""

import json
import shutil

import cdr_ledger_integrity as li
import cdr_ledger_replicate as rep

EPOCH = "2026-05-13"
TODAY = "2026-05-16"  # 13, 14 (gap), 15, 16
GAPS = ("2026-05-14",)


def _make_partition(runs, date, rates=5):
    export_root = runs / date / "_exports"
    export_root.mkdir(parents=True, exist_ok=True)
    (export_root / "local-cdr.sqlite").write_bytes(b"db-" + date.encode())
    cache = export_root / "dashboard-cache"
    cache.mkdir(exist_ok=True)
    (cache / "latest.json").write_text(
        json.dumps({"run_date": date, "banks_counts": {"rates": rates}}), encoding="utf-8"
    )


def _write_marker(state, date, rates=5):
    state.mkdir(parents=True, exist_ok=True)
    (state / f"{date}.done.json").write_text(
        json.dumps({"run_date": date, "banks_counts": {"rates": rates}}), encoding="utf-8"
    )


def _seed(tmp_path):
    runs = tmp_path / "runs"
    state = tmp_path / "state"
    for d in ("2026-05-13", "2026-05-15", "2026-05-16"):
        _make_partition(runs, d)
        _write_marker(state, d)
    li.build_chain(runs, state, EPOCH, TODAY, GAPS)  # baseline integrity manifests (+ gap 14)
    return runs, state


def test_replicate_then_verify_is_clean(tmp_path):
    runs, state = _seed(tmp_path)
    dest = tmp_path / "backup"
    s = rep.replicate(runs, state, dest, epoch=EPOCH, today=TODAY)
    assert set(s["copied"]) == {"2026-05-13", "2026-05-15", "2026-05-16"}
    assert s["gaps"] == ["2026-05-14"]  # the gap day has no partition to replicate
    assert s["missing_source"] == []
    assert (dest / "2026-05-15" / "_exports" / "local-cdr.sqlite").is_file()

    v = rep.verify_replica(runs, state, dest, epoch=EPOCH, today=TODAY)
    assert v["ok"] is True and v["checked"] == 3


def test_replicate_is_idempotent(tmp_path):
    runs, state = _seed(tmp_path)
    dest = tmp_path / "backup"
    rep.replicate(runs, state, dest, epoch=EPOCH, today=TODAY)
    again = rep.replicate(runs, state, dest, epoch=EPOCH, today=TODAY)
    assert again["copied"] == []
    assert set(again["skipped"]) == {"2026-05-13", "2026-05-15", "2026-05-16"}


def test_verify_detects_missing_and_changed_replicas(tmp_path):
    runs, state = _seed(tmp_path)
    dest = tmp_path / "backup"
    rep.replicate(runs, state, dest, epoch=EPOCH, today=TODAY)
    (dest / "2026-05-15" / "_exports" / "local-cdr.sqlite").write_bytes(b"tampered")
    shutil.rmtree(dest / "2026-05-16")
    v = rep.verify_replica(runs, state, dest, epoch=EPOCH, today=TODAY)
    issues = {(f["date"], f["issue"]) for f in v["findings"]}
    assert ("2026-05-15", "REPLICA_CHANGED") in issues
    assert ("2026-05-16", "MISSING_REPLICA") in issues
    assert v["ok"] is False


def test_replicate_flags_missing_source_partition(tmp_path):
    runs, state = _seed(tmp_path)
    dest = tmp_path / "backup"
    shutil.rmtree(runs / "2026-05-15")  # baselined, but the source partition vanished
    s = rep.replicate(runs, state, dest, epoch=EPOCH, today=TODAY)
    assert "2026-05-15" in s["missing_source"]
    assert "2026-05-15" not in s["copied"]
