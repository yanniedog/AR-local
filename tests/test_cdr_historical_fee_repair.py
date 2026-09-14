"""Replay existing serializers against retained source fixtures, not invented fees."""
from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path

import pytest

from app_payload_build import build_payload
from app_payload_details import _detail_items, _fee_items
from cdr_clean_export import clean_value
from cdr_historical_fee_repair import enrich_fee, exact_zero, prepare, retained_record, sha
from cdr_outputs import build_outputs

ROOT = Path(__file__).resolve().parents[1]
FEE_FIXTURE = ROOT / "tests/fixtures/greater_bank_fee_details_2026-05-19.json"
RAW_FIXTURE = ROOT / "tests/fixtures/cdr-canary-2026-09-07/Greater Bank Limited-null-detail.json"


@pytest.fixture
def fee_record():
    return json.loads(FEE_FIXTURE.read_text(encoding="utf-8"))["record"]


@pytest.fixture
def replay(tmp_path):
    """Generate genuine exports from the retained raw CDR response, then replay
    the documented legacy four-field fee serializer on that same source.
    """
    run = tmp_path / "retained" / "2026-09-07"
    raw = json.loads(RAW_FIXTURE.read_bytes())
    record = raw["data"]
    raw_path = run / "banks" / "Mortgage" / record["brand"] / record["name"] / record["productId"] / "product-detail.json"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(RAW_FIXTURE.read_bytes())
    build_outputs(run)
    generated = tmp_path / "generated"
    manifest = build_payload(run / "_exports", generated, tag="app-payload-2026-09-07")
    released = tmp_path / "audited-release"
    released.mkdir()
    for kind in ("core", "details"):
        body = (generated / manifest["files"][kind]["name"]).read_bytes()
        if kind == "details":
            details = json.loads(gzip.decompress(body))
            for detail in details["products"].values():
                detail["fees"] = _detail_items(clean_value(record), "fees", "feeType")
            body = gzip.compress(json.dumps(details, ensure_ascii=False, separators=(",", ":")).encode(), mtime=0)
            manifest["files"][kind]["sha256"] = sha(body)
            manifest["files"][kind]["bytes"] = len(body)
        (released / (kind + ".json.gz")).write_bytes(body)
    (released / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    source = json.loads((run / "_exports/banks-2026-09-07.json").read_text(encoding="utf-8"))
    return run, released, tmp_path / "candidate", source["products"][0], raw_path


def test_adds_fixed_fee_amount_and_disclosures_without_changing_legacy_values(fee_record):
    raw = fee_record["fees"][0]
    old = _detail_items(fee_record, "fees", "feeType")[0]
    enriched, conflict = enrich_fee(old, raw)
    assert conflict is None
    assert all(enriched[key] == value for key, value in old.items())
    assert enriched["amount"] == raw["amount"] == "80.00"
    assert enriched["amountStatus"] == "fixed"


def test_variable_zero_placeholder_loses_only_misleading_display_value(fee_record):
    raw = next(item for item in fee_record["fees"] if item["feeType"] == "VARIABLE")
    old = _detail_items({"fees": [raw]}, "fees", "feeType")[0]
    assert old["value"] == "0.00"
    enriched, conflict = enrich_fee(old, raw)
    assert conflict is None
    assert set(old) - set(enriched) == {"value"}
    assert "value" not in enriched
    assert enriched["amount"] == raw["amount"] == "0.00"
    assert enriched["amountStatus"] == "variable"
    assert all(enriched[key] == value for key, value in old.items() if key != "value")
    assert enriched["info"] == raw["additionalInfo"]
    assert enrich_fee(enriched, raw) == (enriched, None), "Correction must be idempotent"


@pytest.mark.parametrize("fault", [{"info": "integrity-fault"}, {"value": "395.00"}])
def test_variable_zero_rule_holds_any_other_published_conflict(fee_record, fault):
    raw = next(item for item in fee_record["fees"] if item["feeType"] == "VARIABLE")
    old = {**_detail_items({"fees": [raw]}, "fees", "feeType")[0], **fault}
    enriched, conflict = enrich_fee(old, raw)
    assert enriched == old and conflict == "published_fee_conflicts_with_retained_projection"


@pytest.mark.parametrize("value", [True, False, None, "NaN", "Infinity", float("nan"), float("inf"), "395.00", "0.0001"])
def test_variable_zero_rule_requires_finite_exact_zero(value):
    assert exact_zero(value) is False


def test_retained_export_is_compared_using_its_existing_cleaner(replay):
    run, _, _, product, raw_path = replay
    record, proof = retained_record(product, run)
    assert record == json.loads(raw_path.read_bytes())["data"]
    assert proof["raw_sha256"] == sha(raw_path.read_bytes())


def test_unchanged_cleaned_text_does_not_block_additive_fee_fields(replay):
    _, _, _, product, raw_path = replay
    raw_fees = json.loads(raw_path.read_bytes())["data"]["fees"]
    old_fees = _detail_items(json.loads(product["details_json"]), "fees", "feeType")
    checked = 0
    for old, raw in zip(old_fees, raw_fees):
        canonical = clean_value(_fee_items({"fees": [raw]})[0])
        if old.get("info") != raw.get("additionalInfo") and all(key in canonical and canonical[key] == value for key, value in old.items()):
            enriched, conflict = enrich_fee(old, raw)
            assert conflict is None
            assert all(enriched[key] == value for key, value in old.items())
            checked += 1
    assert checked > 0, "Retained fixture must actually exercise source text cleaning"


def test_candidate_preserves_every_core_byte_and_all_original_inputs(replay):
    run, released, output, _, raw_path = replay
    inputs = [raw_path, run / "_exports/banks-2026-09-07.json", *released.iterdir()]
    before = {path: (sha(path.read_bytes()), path.stat().st_mtime_ns) for path in inputs}
    receipt = prepare(run, released, output)
    assert (output / "core.json.gz").read_bytes() == (released / "core.json.gz").read_bytes()
    assert receipt["publication"] == "NOT_ATTEMPTED" and receipt["fees_with_additions"] > 0
    assert {path: (sha(path.read_bytes()), path.stat().st_mtime_ns) for path in inputs} == before
    changes = json.loads((output / "changes.json").read_text())
    assert all(change["legal_amendment"] is False for change in changes)


@pytest.mark.parametrize("kind", ["core", "details"])
def test_rejects_cross_dated_body_even_when_outer_manifest_hash_matches(replay, kind):
    run, released, output, _, _ = replay
    path = released / (kind + ".json.gz")
    body = json.loads(gzip.decompress(path.read_bytes()))
    body["run_date"] = "2026-09-08"  # Deliberate integrity fault, not acceptance data.
    encoded = gzip.compress(json.dumps(body).encode(), mtime=0)
    path.write_bytes(encoded)
    manifest_path = released / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][kind]["sha256"] = sha(encoded)
    manifest["files"][kind]["bytes"] = len(encoded)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="date|schema|identity"):
        prepare(run, released, output)
    assert not output.exists()


def test_conflicting_retained_amount_is_held_before_candidate_generation(replay):
    run, _, _, product, _ = replay
    corrupted = copy.deepcopy(product)
    detail = json.loads(corrupted["details_json"])
    detail["fees"][0]["amount"] = "integrity-fault"
    corrupted["details_json"] = json.dumps(detail)
    with pytest.raises(ValueError, match="conflict"):
        retained_record(corrupted, run)
