"""Bounded control-metadata retention; financial parity uses retained real evidence."""
from __future__ import annotations

import gc
import hashlib
import json
import os
import tracemalloc
import weakref
from types import SimpleNamespace

import pytest

import cdr_quality_audit as audit
import cdr_quality_sources as sources
from cdr_export_contract import build_contract
from cdr_ledger_v2 import append_contract_event
from cdr_quality_cache import VerifiedAuditCache
from tests.test_cdr_quality_sources import retained_partition


def coverage():
    counts = ("products_discovered eligible_rate_rows providers_registered providers_attempted "
              "providers_complete providers_partial providers_failed failure_records "
              "corrupt_failure_records unattributed_failure_records register_sources_attempted "
              "register_sources_complete").split()
    return {**dict.fromkeys(counts, 0), "register_provenance_complete": False,
            "failure_provenance_complete": False, "reconciliation_status": "partial",
            "unavailable_populations": []}


def make_contract(data, ordinal=1, count=1, *, source=None):
    """Synthetic descriptors are control metadata only, never financial acceptance."""
    day = source["run_date"] if source else f"2026-06-{ordinal:02d}"
    key = source["key"] if source else f"runs/{day}/_exports"
    root = data / key
    root.mkdir(parents=True, exist_ok=True)
    records = None if source else [
        {"path": f"control/{i:06d}.json", "bytes": 1,
         "sha256": hashlib.sha256(b"0").hexdigest()} for i in range(count)]
    contract = build_contract(root, observation_date=day, observed_at=f"{day}T01:00:00Z",
                              observation_state="partial", source_path=key,
                              completion_marker_path=f"runs/{day}/complete.json",
                              coverage=coverage(), artifacts=records)
    path = data / "state/export-contracts-v2" / day / f"{contract['generation_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(contract), encoding="utf-8")
    return path, contract


def bound_real_source(data):
    source, _ = retained_partition(data)
    (source["root"] / "control-proof.txt").write_bytes(b"additional artifact bytes")
    path, contract = make_contract(data, source=source)
    # The contract is already written; append real ledger evidence through its normal API.
    append_contract_event(data / "state", path)
    return path, {**source, "contract": contract}


def test_real_results_and_every_artifact_remain_equivalent(tmp_path, monkeypatch):
    _, full = bound_real_source(tmp_path)
    expected = sources.audit_source(tmp_path, full)
    seen = set()
    original_hash = sources.hash_file

    def tracked_hash(path, **kwargs):
        seen.add(path)
        return original_hash(path, **kwargs)

    monkeypatch.setattr(sources, "hash_file", tracked_hash)
    index = sources.AuditIndex(tmp_path / "index.sqlite")
    try:
        results, issues, cached = audit.collect_sources(tmp_path, index, full["run_date"], True)
    finally:
        index.close()
    assert not [item for item in issues if item["code"] == "SOURCE_AUDIT_FAILED"]
    assert cached == 0 and len(results) == 1
    results[0].pop("verified_at")
    assert results == [expected]
    assert {full["root"] / record["path"] for record in full["contract"]["artifacts"]} <= seen


@pytest.mark.parametrize("helper", ["source_files", "stat_fingerprint", "verify_source", "audit_source", "cache"])
def test_unloaded_reference_never_falls_back_to_legacy(tmp_path, helper):
    make_contract(tmp_path)
    entry = sources.inventory(tmp_path)[0][0]
    entry["contract"] = None  # Even an accidental legacy-shaped input must fail closed.
    with pytest.raises(ValueError, match="explicitly materialized"):
        if helper == "cache":
            object.__new__(VerifiedAuditCache).get(tmp_path, entry, "2026-06-01")
        elif helper in {"verify_source", "audit_source"}:
            getattr(sources, helper)(tmp_path, entry)
        else:
            getattr(sources, helper)(entry)


@pytest.mark.parametrize("change", ["delete", "replace", "bytes", "route"])
def test_between_phase_contract_changes_are_rejected(tmp_path, change):
    path, _ = make_contract(tmp_path)
    entry = sources.inventory(tmp_path)[0][0]
    original = path.read_bytes()
    before = path.stat()
    if change == "delete":
        path.unlink()
    elif change == "replace":
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(original)
        os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
        os.replace(replacement, path)
    elif change == "bytes":
        path.write_bytes(original.replace(b'"partial"', b'"failed "', 1))
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    else:
        entry["key"] = "runs/2026-06-02/_exports"
    with pytest.raises((ValueError, OSError)):
        sources.materialize_source(tmp_path, entry)


def test_contract_change_during_full_validation_is_rejected(tmp_path, monkeypatch):
    path, _ = make_contract(tmp_path)
    original = sources.load_contract

    def changing_load(value):
        contract = original(value)
        path.write_bytes(path.read_bytes() + b" ")
        return contract

    monkeypatch.setattr(sources, "load_contract", changing_load)
    entries, errors = sources.inventory(tmp_path)
    assert errors[0]["code"] == "INVALID_CONTRACT"
    assert all("contract_ref" not in entry for entry in entries)


@pytest.mark.parametrize("cached", ["fresh", "index", "verified"])
def test_in_audit_or_cache_hit_tamper_cannot_reach_index(tmp_path, monkeypatch, cached):
    path, full = bound_real_source(tmp_path)
    index = sources.AuditIndex(tmp_path / "index.sqlite")

    def changing_result(*args):
        path.write_bytes(path.read_bytes() + b" ")
        # Structural fault injection: no result may be accepted after this edit.
        return {"key": full["key"]}

    cache = None
    if cached == "index":
        monkeypatch.setattr(index, "get", changing_result)
    elif cached == "verified":
        cache = SimpleNamespace(get=changing_result, manifest={"entries": {}})
    else:
        monkeypatch.setattr(audit, "audit_source", changing_result)
    try:
        results, issues, count = audit.collect_sources(tmp_path, index, "2026-11-01",
                                                      cached == "fresh", cache)
        assert results == [] and count == 0
        assert issues[-1]["code"] == "SOURCE_AUDIT_FAILED"
        assert index.db.execute("SELECT COUNT(*) FROM audits").fetchone()[0] == 0
    finally:
        index.close()


def test_full_artifact_binding_is_identical_after_materialization(tmp_path):
    _, full = bound_real_source(tmp_path)
    entry = sources.inventory(tmp_path)[0][0]
    actual = sources.materialize_source(tmp_path, entry)
    assert sources.source_files(actual) == sources.source_files(full)
    assert sources.verify_source(tmp_path, actual) == sources.verify_source(tmp_path, full)


def test_raw_contract_hash_catches_change_even_with_identity_masked(tmp_path, monkeypatch):
    path, _ = make_contract(tmp_path)
    entry = sources.inventory(tmp_path)[0][0]
    original_identity = sources._contract_identity
    original = path.read_bytes()
    # Whitespace edit is semantically identical JSON, but not the pinned input bytes.
    path.write_bytes(original.replace(b'"schema_version": 2', b'"schema_version" :2'))
    monkeypatch.setattr(sources, "_contract_identity",
                        lambda root, relative: (original_identity(root, relative)[0],
                                                entry["contract_ref"]["identity"]))
    with pytest.raises(ValueError, match="identity or bytes changed"):
        sources.materialize_source(tmp_path, entry)


def test_artifact_tamper_still_requires_full_byte_proof(tmp_path):
    _, full = bound_real_source(tmp_path)
    entry = sources.inventory(tmp_path)[0][0]
    (full["root"] / "control-proof.txt").write_bytes(b"changed artifact bytes")
    with pytest.raises(ValueError, match="artifact binding mismatch"):
        sources.verify_source(tmp_path, sources.materialize_source(tmp_path, entry))


class TrackedContract(dict):
    pass


@pytest.mark.parametrize("mode", ["fresh", "cache", "failure", "load_failure"])
def test_contract_lifetime_ends_before_next_load(tmp_path, monkeypatch, mode):
    for ordinal in range(1, 4):
        make_contract(tmp_path, ordinal)
    references = []
    original = sources.load_contract

    def tracked_load(path):
        assert all(reference() is None for reference in references)
        value = TrackedContract(original(path))
        references.append(weakref.ref(value))
        return value

    monkeypatch.setattr(sources, "load_contract", tracked_load)
    entries, errors = sources.inventory(tmp_path)
    assert not errors and all(reference() is None for reference in references)
    monkeypatch.setattr(audit, "inventory", lambda root: (entries, []))
    monkeypatch.setattr(audit, "stat_fingerprint", lambda source: "control-only")
    monkeypatch.setattr(audit, "source_issues", lambda result: [])
    if mode == "load_failure":
        # Fail after full load, exercising release of the helper's exception frame.
        entries[0]["contract_ref"]["generation_id"] = "mismatch"

    def result_for(*args):
        if mode == "failure":
            raise ValueError("structural fault injection")
        return {"key": "control", "run_date": "2026-06-01", "fingerprint": "control-only"}

    monkeypatch.setattr(audit, "audit_source", result_for)
    index = sources.AuditIndex(tmp_path / "index.sqlite")
    monkeypatch.setattr(index, "get", result_for if mode == "cache" else lambda *args: None)
    monkeypatch.setattr(index, "put", lambda result: None)
    try:
        results, issues, _ = audit.collect_sources(tmp_path, index, "2026-11-01", False)
    finally:
        index.close()
    expected_failures = 3 if mode == "failure" else 1 if mode == "load_failure" else 0
    assert len(issues) == expected_failures and len(results) == 3 - expected_failures
    assert all(reference() is None for reference in references)


def test_inventory_allocation_scales_with_one_contract_not_aggregate(tmp_path, record_property):
    single, many = tmp_path / "single", tmp_path / "many"
    make_contract(single, count=1536)
    for ordinal in range(1, 9):
        make_contract(many, ordinal, count=1536)

    def measured(root):
        gc.collect()
        tracemalloc.start()
        try:
            entries, errors = sources.inventory(root)
            retained, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert not errors
        assert all("contract" not in entry and "contract_ref" in entry for entry in entries)
        return len(entries), retained, peak

    one, eight = measured(single), measured(many)
    record_property("allocation_single", json.dumps(one))
    record_property("allocation_eight", json.dumps(eight))
    print(f"contract allocation bytes single={one} eight={eight}")
    assert one[0] == 1 and eight[0] == 8
    assert eight[1] < 1024**2
    assert eight[2] < one[2] * 2 + 1024**2
