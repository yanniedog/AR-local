"""Retained real product evidence plus structural cache/concurrency fault tests."""
from __future__ import annotations

import json
import os
import zlib
from pathlib import Path

import pytest

import cdr_outputs
from cdr_quality_accounting import product_rows_digest
from cdr_quality_logs import audit_logs, log_paths
from cdr_quality_sources import AUDIT_VERSION, AuditIndex, audit_source, source_files, stat_fingerprint, stat_identity

FIXTURES = Path(__file__).parent / "fixtures"


def retained_product():
    rows = json.loads((FIXTURES / "canonical_domain_real_observations.json").read_text(encoding="utf-8"))["observations"]
    source = rows["bank_of_melbourne_before_rename"]
    raw = source["record"]
    product = {"dataset": source["dataset"], "provider": source["provider"],
               "product_id": raw["productId"], "product_key": f"{source['provider']}|{raw['productId']}",
               "product_name": raw["name"], "category": raw.get("productCategory"),
               "last_updated": raw.get("lastUpdated"), "details_json": json.dumps(raw, indent=2),
               "source_file": source["source_path"]}
    return source["observed_at"][:10], product, rows


def retained_partition(tmp_path):
    day, product, _ = retained_product()
    root = tmp_path / "runs" / day / "_exports"
    root.mkdir(parents=True)
    banks = {"products": [product], **{key: [] for key in (
        "rates", "fees", "features", "eligibility", "constraints", "product_facts", "failures")}}
    cdr_outputs.rebuild_run_db(root / "local-cdr.sqlite", day, banks)
    export = root / "dashboard-cache" / day / "banks.json"
    export.parent.mkdir(parents=True)
    export.write_text(json.dumps({"run_date": day, **banks}), encoding="utf-8")
    source = {"root": root, "key": root.relative_to(tmp_path).as_posix(), "run_date": day, "contract": None}
    return source, export


def test_real_shared_product_details_reconcile_independent_of_json_spacing(tmp_path):
    source, export = retained_partition(tmp_path)
    body = json.loads(export.read_bytes())
    body["products"][0]["details_json"] = json.dumps(
        json.loads(body["products"][0]["details_json"]), sort_keys=True, separators=(",", ":"))
    export.write_text(json.dumps(body), encoding="utf-8")
    before = (source["root"] / "local-cdr.sqlite").read_bytes()
    result = audit_source(tmp_path, source)
    assert result["sqlite_to_export"]["status"] == "PASS"
    assert result["accounting"]["source_products"] == 1
    assert (source["root"] / "local-cdr.sqlite").read_bytes() == before


def test_same_count_and_product_key_cannot_conceal_different_real_details(tmp_path):
    source, export = retained_partition(tmp_path)
    _, product, observations = retained_product()
    other = observations["bank_of_melbourne_after_rename"]["record"]
    body = json.loads(export.read_bytes())
    body["products"][0]["details_json"] = json.dumps(other)
    assert body["products"][0]["product_key"] == product["product_key"]
    assert product_rows_digest([product]) != product_rows_digest(body["products"])
    export.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(ValueError, match="do not reconcile"):
        audit_source(tmp_path, source)


def test_old_audit_version_cannot_supply_new_detail_equality_proof(tmp_path):
    index = AuditIndex(tmp_path / "audit/index.sqlite")
    result = {"key": "retained", "run_date": "2026-05-25", "fingerprint": "unchanged"}
    try:
        index.db.execute("INSERT INTO audits VALUES(?,?,?,?,?)", (
            result["key"], result["run_date"], result["fingerprint"], 2,
            zlib.compress(json.dumps(result).encode())))
        index.db.commit()
        assert AUDIT_VERSION == 3
        assert index.get("retained", "unchanged") is None
        index.put(result)
        assert index.get("retained", "unchanged") == result
    finally:
        index.close()


def test_corrupt_derived_cache_requests_fresh_source_audit(tmp_path):
    index = AuditIndex(tmp_path / "audit/index.sqlite")
    try:
        index.db.execute("INSERT INTO audits VALUES(?,?,?,?,?)", (
            "retained", "2026-05-25", "same", AUDIT_VERSION, b"incomplete compressed cache"))
        index.db.commit()
        assert index.get("retained", "same") is None
    finally:
        index.close()


def test_same_size_mtime_file_replacement_invalidates_source_fingerprint(tmp_path):
    source, export = retained_partition(tmp_path)
    original_stat = export.stat()
    before = stat_fingerprint(source)
    replacement = export.with_suffix(".replacement")
    replacement.write_bytes(export.read_bytes())
    os.utime(replacement, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    replacement.replace(export)
    assert export.stat().st_size == original_stat.st_size
    assert export.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert stat_identity(export.stat()) != stat_identity(original_stat)
    assert stat_fingerprint(source) != before


def test_unbound_publication_json_or_journal_cannot_inherit_contract_proof(tmp_path):
    from cdr_export_contract import artifact_records

    source, export = retained_partition(tmp_path)
    records = artifact_records(source["root"])
    source["contract"] = {"artifacts": [row for row in records if not row["path"].endswith("banks.json")]}
    with pytest.raises(ValueError, match="not bound.*banks.json"):
        source_files(source)
    source["contract"] = {"artifacts": records}
    journal = source["root"] / "local-cdr.sqlite-wal"
    journal.write_bytes(b"unbound transport fault")
    with pytest.raises(ValueError, match="not bound.*sqlite-wal"):
        source_files(source)
    journal.write_bytes(b"")
    assert journal in {path for path, _ in source_files(source)}


def test_terminal_success_json_is_included_and_replacement_invalidates_log_cache(tmp_path):
    root = tmp_path / "state/ingest-terminal"
    root.mkdir(parents=True)
    path = root / "2026-05-25.json"
    # A completion marker is operational metadata, not simulated CDR data.
    path.write_text('{"status":"completed"}', encoding="utf-8")
    assert path in log_paths(tmp_path)
    index = AuditIndex(tmp_path / "audit/index.sqlite")
    try:
        assert audit_logs(tmp_path, index)["cached_files"] == 0
        assert audit_logs(tmp_path, index)["cached_files"] == 1
        previous = path.stat()
        alternate = path.with_suffix(".replacement")
        alternate.write_bytes(path.read_bytes())
        os.utime(alternate, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        alternate.replace(path)
        assert audit_logs(tmp_path, index)["cached_files"] == 0
    finally:
        index.close()


def test_concurrent_audit_uses_dedicated_lock_and_never_takes_production_lock(tmp_path, monkeypatch):
    import cdr_quality_audit
    from ar_local_operation_lock import production_lock

    (tmp_path / "runs").mkdir()
    (tmp_path / "state").mkdir()
    calls = []

    def audit_while_ingest_is_active(data_root, day, **kwargs):
        calls.append(kwargs["output"])
        assert (kwargs["output"] / ".audit.lock").exists()
        with pytest.raises(RuntimeError, match="lock is active"):
            cdr_quality_audit.audit(data_root, day, public=False)
        return {"status": "BLOCKED", "reason": "source-only test"}

    monkeypatch.setattr(cdr_quality_audit, "_audit_locked", audit_while_ingest_is_active)
    active_ingest = tmp_path / "state/production-operation.lock"
    with production_lock(active_ingest, "ingest"):
        report = cdr_quality_audit.audit(tmp_path, "2026-05-25", public=False)
        assert active_ingest.exists()
    assert report["status"] == "BLOCKED"
    assert calls == [tmp_path / "state/quality-audit"]
    assert not (calls[0] / ".audit.lock").exists()


def test_direct_audit_rejects_noncanonical_date_before_writing(tmp_path):
    from cdr_quality_audit import audit

    with pytest.raises(ValueError):
        audit(tmp_path, "20260525")
    assert not list(tmp_path.iterdir())
