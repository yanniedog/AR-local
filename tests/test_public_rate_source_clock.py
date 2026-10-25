"""Filesystem/archive clocks cannot impersonate successful public source checks."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path

import pytest

from cdr_domain.public_pricing_resolver import resolve_public_rate
from cdr_domain.public_pricing_validation import validate_wire
from cdr_public_rates_cdr import capture_pricing_source, compile_export_products, compile_record
from cdr_public_rates_collector import _compile_pending, _pending_product, compiled_generation, write_candidate
from cdr_public_rates_source_capture import pricing_capture_for_path
from cdr_terms.public_rates_store import PublicRateStore
from cdr_terms.store import EvidenceStore

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/public_rates/anz-progress-saver-cdr-20261014.json"


@pytest.fixture
def retained():
    case = next(case for case in json.loads((ROOT / "contracts/public_rates/fixtures/resolver-golden-v1.json").read_bytes())["cases"]
                if case["programme"]["section"] == "Savings")
    source = FIXTURE.read_bytes()
    assert hashlib.sha256(source).hexdigest() == case["publicSource"]["sha256"]
    return source, json.loads(source)["data"], case


def copied_source(tmp_path, retained, instant):
    source, record, case = retained
    banks = tmp_path / "run/banks"
    path = banks / "Savings/ANZ/product/product-detail.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(source)  # Same byte-copy behavior as same-day recovery seeding.
    stamp = datetime.fromisoformat(instant.replace("Z", "+00:00")).timestamp()
    os.utime(path, (stamp, stamp))
    metadata = banks / "_holders/ANZ/_register-brand.json"
    metadata.parent.mkdir(parents=True)
    metadata.write_text(json.dumps({"endpoint_url": case["publicSource"]["url"].rsplit("/", 1)[0]}))
    base = {"provider": "ANZ", "product_id": record["productId"]}
    return path, json.loads(pricing_capture_for_path(source, path, banks, base))


@pytest.mark.parametrize("instant", ["2026-10-14T12:30:00Z", "2026-10-16T15:30:00Z"])
def test_copied_or_touched_source_does_not_acquire_a_success_clock(tmp_path, retained, instant):
    source, record, _ = retained
    path, capture = copied_source(tmp_path, retained, instant)
    assert capture["checkedAt"] == ""
    assert capture["sourceSha256"] == hashlib.sha256(source).hexdigest()
    assert capture["record"]["productId"] == record["productId"]
    assert path.read_bytes() == source
    before = dict(capture)
    os.utime(path, (path.stat().st_mtime + 86400, path.stat().st_mtime + 86400))
    assert json.loads(pricing_capture_for_path(source, path, tmp_path / "run/banks", {
        "provider": "ANZ", "product_id": record["productId"]})) == before


def test_missing_clock_preserves_fees_and_leaves_current_pricing_unverified(retained):
    source, record, case = retained
    compiled = compile_record(record, provider_name="ANZ", section="Savings",
                              source_url=case["publicSource"]["url"], source_sha256=hashlib.sha256(source).hexdigest())
    assert compiled["product"]["freshness"]["state"] == "unknown"
    assert all("checkedAt" not in item and "lastSuccessAt" not in item for item in [
        compiled["product"]["freshness"], *compiled["evidence"]])
    assert any(programme["fees"] for programme in compiled["programmes"])
    programme = next(p for p in compiled["programmes"] if p["programmeId"] == case["programme"]["programmeId"])
    result = resolve_public_rate(programme, case["scenario"], case["asOf"])
    assert result["status"] == "unresolved" and result["verifiedCurrent"] is False
    assert "source_not_verified_current" in result["reasonCodes"]


@pytest.mark.parametrize("legacy_claim", [False, True])
def test_pending_product_without_a_check_receipt_omits_missing_times(tmp_path, retained, legacy_claim):
    source, record, case = retained
    _, context = copied_source(tmp_path, retained, case["asOf"])
    context["checkedAt"] = case["asOf"] if legacy_claim else ""
    context.update(productId=case["programme"]["productId"], productKey="ANZ|" + record["productId"],
                   providerName="ANZ", section="Savings", name=record["name"])
    pending = _pending_product(context)
    validate_wire(pending, "Product")
    assert pending["freshness"]["state"] == "unknown"
    assert "checkedAt" not in pending["freshness"] and "lastSuccessAt" not in pending["freshness"]
    assert "checkedAt" not in pending["sourceEvidence"]


def test_queued_legacy_context_cannot_grant_verification_on_replay(tmp_path, retained):
    source, record, case = retained
    _, context = copied_source(tmp_path, retained, case["asOf"])
    context.update(checkedAt=case["asOf"], productId=case["programme"]["productId"],
                   productKey="ANZ|" + record["productId"], providerName="ANZ", section="Savings", name=record["name"])
    with EvidenceStore(tmp_path / "evidence") as store:
        observation = store.observe(provider="ANZ", product_key=context["productKey"], record=json.loads(source),
                                    source_bytes=source, observed_at=case["asOf"], ingest_id="legacy-queued")
        original = json.dumps(context, sort_keys=True)
        with store.db:
            store.db.execute("INSERT INTO ingest_capture_attempts VALUES (?,?,?,?)",
                             ("legacy-queued", case["asOf"], case["asOf"], "{}"))
            store.db.execute("INSERT INTO public_rate_compile_inputs VALUES (?,?,?)", (observation, "legacy-queued", original))
        _compile_pending(store, "legacy-queued", lambda: None)
        stored = json.loads(store.db.execute("SELECT discovery_json FROM public_rate_product_versions").fetchone()[0])
        assert stored["freshness"]["state"] == "unknown" and "lastSuccessAt" not in stored["freshness"]
        assert store.db.execute("SELECT context_json FROM public_rate_compile_inputs").fetchone()[0] == original


def legacy_compiled(store):
    from tests.test_public_rate_evidence_store import CDF, WHEN, retained_product
    observation, compiled, inventory = retained_product(store)
    # Explicit lower-level source evidence remains supported without collector context.
    assert compiled_generation(store, "retained-public-fixture")["products"][0]["freshness"]["state"] == "current"
    context = json.loads(capture_pricing_source(CDF.read_bytes(), checked_at=WHEN,
        source_url=compiled["product"]["sourceEvidence"]["url"], provider_id=compiled["product"]["providerId"]))
    context.update(productId=compiled["product"]["productId"], productKey=compiled["product"]["productKey"],
                   providerName="NAB", name=compiled["product"]["name"], section="Mortgage")
    with store.db:
        store.db.execute("INSERT INTO public_rate_compile_inputs VALUES (?,?,?)",
                         (observation, "retained-public-fixture", json.dumps(context, sort_keys=True)))
    return compiled, inventory


@pytest.mark.parametrize("historical", [False, True])
def test_existing_collector_versions_project_unknown_without_rewriting_evidence(tmp_path, historical):
    with EvidenceStore(tmp_path / "evidence") as store:
        original, _ = legacy_compiled(store)
        before = tuple(store.db.execute("SELECT discovery_json FROM public_rate_product_versions").fetchone())
        generation = "retained-public-fixture"
        if historical:
            generation = "later-selected"
            with store.db:
                store.db.execute("INSERT INTO ingest_capture_attempts VALUES (?,?,?,?)",
                    (generation, "2026-10-16T00:00:00Z", "2026-10-16T00:00:00Z", "{}"))
        projection = compiled_generation(store, generation)
        product = projection["products"][0]
        assert product["productId"] == original["product"]["productId"]
        for item in [product, *projection["programmes"]]:
            assert item["freshness"]["state"] == "unknown"
            assert "checkedAt" not in item["freshness"] and "lastSuccessAt" not in item["freshness"]
        assert "checkedAt" not in product["sourceEvidence"]
        assert all("checkedAt" not in item for item in projection["evidence"])
        assert tuple(store.db.execute("SELECT discovery_json FROM public_rate_product_versions").fetchone()) == before


def test_candidate_stream_cannot_republish_legacy_collector_success_times(tmp_path):
    from cdr_public_rates_candidate import programme_ids, read_candidate, selected_evidence, selected_programmes
    from tests.test_public_rate_evidence_store import WHEN
    with EvidenceStore(tmp_path / "evidence") as store:
        _, inventory = legacy_compiled(store)
        register = PublicRateStore(store).register(inventory, observed_at=WHEN)
        result = write_candidate(store, generation="retained-public-fixture", run_date="2026-10-14", register_id=register, as_of=WHEN)
        candidate = read_candidate(Path(result["file"]))
        assert candidate["products"][0]["freshness"]["state"] == "unknown"
        assert "checkedAt" not in candidate["products"][0]["sourceEvidence"]
        programmes = selected_programmes(candidate, programme_ids(candidate))
        assert programmes and all(p["freshness"]["state"] == "unknown" for p in programmes)
        evidence_ids = {identity for chunk in candidate["evidenceChunks"] for identity in chunk["evidenceIds"]}
        assert evidence_ids and all("checkedAt" not in item for item in selected_evidence(candidate, evidence_ids))
        assert candidate["enabledProgrammeIds"] == []


def test_explicit_retained_check_time_is_preserved_without_using_file_metadata(retained):
    source, record, case = retained
    instant = case["programme"]["freshness"]["lastSuccessAt"]
    capture = capture_pricing_source(source, source_url=case["publicSource"]["url"], checked_at=instant)
    row = {"dataset": "Savings", "provider": "ANZ", "product_id": record["productId"],
           "product_name": record["name"], "product_key": "ANZ|" + record["productId"],
           "public_pricing_source_json": capture}
    compiled = compile_export_products([row])
    programme = next(p for p in compiled["programmes"] if p["programmeId"] == case["programme"]["programmeId"])
    assert programme["freshness"]["lastSuccessAt"] == instant
    assert resolve_public_rate(programme, case["scenario"], case["asOf"])["payableRate"] == case["expected"]["payableRate"]
