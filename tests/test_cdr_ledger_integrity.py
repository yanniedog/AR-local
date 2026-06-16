"""Tamper-evidence + continuity verification for the permanent CDR ledger.

Exercises cdr_ledger_integrity over synthetic daily partitions: a clean chain
verifies, and every corruption mode (changed bytes, missing manifest, broken
chain link, fabricated gap) is detected.
"""

import json

import pytest

import cdr_ledger_integrity as li

EPOCH = "2026-05-13"
TODAY = "2026-05-16"  # dates: 13, 14 (gap), 15, 16
GAPS = ("2026-05-14",)


def make_partition(runs_root, date, rates=5, sqlite_bytes=b"db-bytes"):
    export_root = runs_root / date / "_exports"
    export_root.mkdir(parents=True, exist_ok=True)
    (export_root / "local-cdr.sqlite").write_bytes(sqlite_bytes)
    cache = export_root / "dashboard-cache"
    cache.mkdir(exist_ok=True)
    (cache / "latest.json").write_text(
        json.dumps({"run_date": date, "banks_counts": {"rates": rates}}), encoding="utf-8"
    )
    return export_root


def seed_ledger(tmp_path):
    runs = tmp_path / "runs"
    state = tmp_path / "state"
    for date in ("2026-05-13", "2026-05-15", "2026-05-16"):
        make_partition(runs, date)
    # 2026-05-14 is a known gap: deliberately no partition.
    return runs, state


def test_iter_ledger_dates_inclusive():
    assert list(li.iter_ledger_dates("2026-05-13", "2026-05-16")) == [
        "2026-05-13", "2026-05-14", "2026-05-15", "2026-05-16",
    ]


def test_build_then_verify_is_clean(tmp_path):
    runs, state = seed_ledger(tmp_path)
    summary = li.build_chain(runs, state, EPOCH, TODAY, GAPS)
    assert summary["written"] == ["2026-05-13", "2026-05-15", "2026-05-16"]
    assert summary["gaps"] == ["2026-05-14"]
    report = li.verify_chain(runs, state, EPOCH, TODAY, GAPS)
    assert report["ok"] is True, report["findings"]
    assert report["checked"] == 4
    # The gap got an explicit gap manifest, not fabricated content.
    gap_manifest = json.loads(li.manifest_path(state, "2026-05-14").read_text())
    assert gap_manifest["gap"] is True and gap_manifest["files"] == []


def test_detects_changed_partition_bytes(tmp_path):
    runs, state = seed_ledger(tmp_path)
    li.build_chain(runs, state, EPOCH, TODAY, GAPS)
    # Mutate a finalized partition after the baseline was taken.
    (runs / "2026-05-15" / "_exports" / "local-cdr.sqlite").write_bytes(b"tampered")
    report = li.verify_chain(runs, state, EPOCH, TODAY, GAPS)
    assert report["ok"] is False
    assert {"date": "2026-05-15", "issue": "CHANGED"} in report["findings"]


def test_detects_missing_manifest(tmp_path):
    runs, state = seed_ledger(tmp_path)
    li.build_chain(runs, state, EPOCH, TODAY, GAPS)
    li.manifest_path(state, "2026-05-15").unlink()
    report = li.verify_chain(runs, state, EPOCH, TODAY, GAPS)
    issues = {(f["date"], f["issue"]) for f in report["findings"]}
    assert ("2026-05-15", "MISSING_MANIFEST") in issues
    assert report["ok"] is False


def test_detects_broken_chain_link(tmp_path):
    runs, state = seed_ledger(tmp_path)
    li.build_chain(runs, state, EPOCH, TODAY, GAPS)
    path = li.manifest_path(state, "2026-05-15")
    record = json.loads(path.read_text())
    record["prev_sha"] = "deadbeef"
    path.write_text(json.dumps(record), encoding="utf-8")
    report = li.verify_chain(runs, state, EPOCH, TODAY, GAPS)
    issues = {(f["date"], f["issue"]) for f in report["findings"]}
    assert ("2026-05-15", "BROKEN_CHAIN") in issues


def test_detects_fabricated_gap(tmp_path):
    runs, state = seed_ledger(tmp_path)
    li.build_chain(runs, state, EPOCH, TODAY, GAPS)
    # Someone drops current data under the 2026-05-14 gap.
    make_partition(runs, "2026-05-14")
    report = li.verify_chain(runs, state, EPOCH, TODAY, GAPS)
    issues = {(f["date"], f["issue"]) for f in report["findings"]}
    assert ("2026-05-14", "GAP_FABRICATED") in issues
    assert report["ok"] is False


def test_detects_unreadable_manifest(tmp_path):
    runs, state = seed_ledger(tmp_path)
    li.build_chain(runs, state, EPOCH, TODAY, GAPS)
    li.manifest_path(state, "2026-05-15").write_text("{not-json", encoding="utf-8")
    report = li.verify_chain(runs, state, EPOCH, TODAY, GAPS)
    assert {"date": "2026-05-15", "issue": "UNREADABLE", "detail": "manifest"} in report["findings"]


def test_detects_unreadable_partition(tmp_path, monkeypatch):
    runs, state = seed_ledger(tmp_path)
    li.build_chain(runs, state, EPOCH, TODAY, GAPS)

    def boom(_root):
        raise OSError("cannot read partition")

    monkeypatch.setattr(li, "hash_export_root", boom)
    report = li.verify_chain(runs, state, EPOCH, TODAY, GAPS)
    assert {"date": "2026-05-15", "issue": "UNREADABLE", "detail": "partition"} in report["findings"]


def test_detects_interior_missing_day(tmp_path):
    # 2026-05-15 has neither content nor a manifest and is not a known gap, but a
    # later day (2026-05-16) is finalized, so the hole is a genuine interior gap.
    runs = tmp_path / "runs"
    state = tmp_path / "state"
    make_partition(runs, "2026-05-13")
    make_partition(runs, "2026-05-16")  # 14 is a known gap; 15 is the missing hole
    li.build_chain(runs, state, EPOCH, TODAY, GAPS)
    report = li.verify_chain(runs, state, EPOCH, TODAY, GAPS)
    issues = {(f["date"], f["issue"]) for f in report["findings"]}
    assert ("2026-05-15", "MISSING_DAY") in issues
    assert report["ok"] is False


def test_trailing_unfinalized_day_is_not_flagged(tmp_path):
    # An in-progress day after the latest finalized one must NOT fail verify.
    runs, state = seed_ledger(tmp_path)  # finalized through 2026-05-16
    li.build_chain(runs, state, EPOCH, TODAY, GAPS)
    report = li.verify_chain(runs, state, EPOCH, "2026-05-17", GAPS)
    assert report["ok"] is True, report["findings"]


def test_inverted_range_raises(tmp_path):
    runs, state = seed_ledger(tmp_path)
    with pytest.raises(ValueError, match="inverted"):
        li.build_chain(runs, state, "2026-05-16", "2026-05-13", GAPS)


def test_rebuild_is_idempotent(tmp_path):
    runs, state = seed_ledger(tmp_path)
    first = li.build_chain(runs, state, EPOCH, TODAY, GAPS)["head_sha"]
    second = li.build_chain(runs, state, EPOCH, TODAY, GAPS)["head_sha"]
    assert first == second
    assert li.verify_chain(runs, state, EPOCH, TODAY, GAPS)["ok"] is True


def test_append_day_manifest_matches_build_chain(tmp_path):
    # Appending each present day incrementally (the daily-ingest path) must yield
    # the same verified chain as a full build_chain.
    runs, state = seed_ledger(tmp_path)
    for date in ("2026-05-13", "2026-05-14", "2026-05-15", "2026-05-16"):
        li.append_day_manifest(runs, state, date, EPOCH, GAPS)
    assert li.verify_chain(runs, state, EPOCH, TODAY, GAPS)["ok"] is True
    incremental_head = li.chain_sha(json.loads(li.manifest_path(state, "2026-05-16").read_text()))
    built_head = li.build_chain(runs, tmp_path / "state2", EPOCH, TODAY, GAPS)["head_sha"]
    assert incremental_head == built_head


def test_append_day_manifest_links_to_prior_head(tmp_path):
    runs, state = seed_ledger(tmp_path)
    li.append_day_manifest(runs, state, "2026-05-13", EPOCH, GAPS)
    # 2026-05-14 is a gap with no manifest yet, so 2026-05-15's prior head is 13's.
    prev = li.latest_manifest_sha_before(state, EPOCH, "2026-05-15")
    assert prev == li.chain_sha(json.loads(li.manifest_path(state, "2026-05-13").read_text()))
    rec = li.append_day_manifest(runs, state, "2026-05-15", EPOCH, GAPS)
    assert rec["prev_sha"] == prev


def test_append_day_manifest_first_day_prev_sha_none(tmp_path):
    runs, state = seed_ledger(tmp_path)
    rec = li.append_day_manifest(runs, state, "2026-05-13", EPOCH, GAPS)
    assert rec["prev_sha"] is None  # no prior manifest exists
    assert li.manifest_path(state, "2026-05-13").is_file()
