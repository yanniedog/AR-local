"""Re-export retained September 12 term contracts; no invented rate fixtures."""
from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path

import pytest

from app_payload_build import build_payload
from app_payload_common import section_filter
from cdr_clean_export import parse_banks_run
from cdr_outputs import write_dashboard_cache
from cdr_product_classification import (
    category_excludes_section, has_savings_term_deposit_evidence, infer_cdr_dataset,
)
from cdr_quality_accounting import payload_accounting

FIXTURE = Path(__file__).parent / "fixtures/cdr_term_classification_real_2026-09-12.json"


@pytest.fixture(scope="module")
def evidence():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["products"]


@pytest.fixture
def reexport(tmp_path, evidence):
    run = tmp_path / "2026-09-12"
    for item in evidence:
        product = item["product"]
        leaf = run / "banks" / product["dataset"] / product["provider"] / product["product_id"]
        leaf.mkdir(parents=True)
        (leaf / "product-detail.json").write_text(product["details_json"], encoding="utf-8")
    return run, parse_banks_run(run)


def test_all_real_term_contracts_are_classified_without_mutating_source(evidence):
    for item in evidence:
        product = json.loads(item["product"]["details_json"])
        before = copy.deepcopy(product)
        expected = item["expected_dataset"] == "TD"
        assert has_savings_term_deposit_evidence(product) is expected
        assert infer_cdr_dataset(product, allow_name_fallback=False) == (
            "term_deposits" if expected else "savings"
        )
        assert product == before


def test_real_reexport_recovers_all_25_rows_with_source_rates_unchanged(reexport, evidence):
    _, banks = reexport
    originals = {item["product"]["product_key"]: item for item in evidence}
    td = [row for row in banks["rates"] if row["dataset"] == "TD"]
    assert len(td) == 25
    assert len({row["product_key"] for row in td}) == 13
    for product in banks["products"]:
        original = originals[product["product_key"]]
        assert product["dataset"] == original["expected_dataset"]
        assert product["category"] == original["product"]["category"]
        assert json.loads(product["details_json"]) == json.loads(original["product"]["details_json"])
    for row in banks["rates"]:
        original = originals[row["product_key"]]["rates"][row["rate_index"] - 1]
        for field in ("rate", "rate_type", "application_type", "application_frequency", "term", "category"):
            assert row[field] == original[field]
        assert section_filter(row["dataset"], row)
        if row["dataset"] == "TD":
            assert row["taxonomy_path"].startswith("TERM_DEPOSIT.")
            assert not category_excludes_section(row["category"], "TD", row=row)
            assert category_excludes_section(row["category"], "TD")
    southern = [row for row in td if row["provider"] == "Great Southern Bank Business+"]
    assert {row["rate_type"] for row in southern} == {"VARIABLE"}
    assert {row["application_type"] for row in southern} == {"MATURITY"}
    assert {row["term_months"] for row in southern} == {str(n) for n in range(1, 13)}
    accounting = payload_accounting(banks["products"], banks["rates"])
    assert accounting["sections"]["TD"]["published_rates"] == 25
    assert accounting["sections"]["TD"]["published_products"] == 13
    assert accounting["excluded_rates"] == 0


def test_actual_reexport_builds_25_td_payload_rows(reexport, monkeypatch):
    run, banks = reexport
    # External logo/macro fetches are irrelevant to rate classification. The
    # source product/rate records and shipping export/payload code remain real.
    monkeypatch.setattr("cdr_brand_logos.fetch_register_logos", lambda **kwargs: {})
    monkeypatch.setenv("AR_LOCAL_RBA_OFFICIAL_FETCH", "0")
    exports, output = run / "_exports", run / "payload"
    write_dashboard_cache(exports, "2026-09-12", banks)
    manifest = build_payload(exports, output, tag="app-payload-2026-09-12")
    core = json.loads(gzip.decompress((output / manifest["files"]["core"]["name"]).read_bytes()))
    assert len(core["sections"]["TD"]["rates"]) == 25
    assert len(core["sections"]["Savings"]["rates"]) == 4
    assert all(row["taxonomy_path"].startswith("TERM_DEPOSIT.") for row in core["sections"]["TD"]["rates"])


@pytest.mark.parametrize("damage", ["index_only", "no_term", "no_fixed", "lending", "business_category", "malformed_rate"])
def test_incomplete_or_conflicting_evidence_never_gets_override(evidence, damage):
    product = json.loads(next(item["product"]["details_json"] for item in evidence
                             if item["product"]["provider"] == "MoveBank"))
    if damage == "index_only":
        product.pop("depositRates")
    elif damage == "no_term":
        product["depositRates"][0].pop("additionalValue")
    elif damage == "no_fixed":
        product["depositRates"][0].pop("depositRateType")
    elif damage == "lending":
        product["lendingRates"] = [{}]
    elif damage == "business_category":
        product["productCategory"] = "BUSINESS_LOANS"
    else:
        product["depositRates"].append(None)
    assert not has_savings_term_deposit_evidence(product)


def test_maturity_or_name_alone_does_not_override_real_savings(evidence):
    savings = [item for item in evidence if item["expected_dataset"] == "Savings"]
    assert any(row["application_type"] == "MATURITY" for item in savings for row in item["rates"])
    for item in savings:
        record = json.loads(item["product"]["details_json"])
        assert not has_savings_term_deposit_evidence(record)
    term = json.loads(next(item["product"]["details_json"] for item in evidence
                          if item["product"]["provider"] == "Great Southern Bank Business+"))
    term["depositRates"][0].pop("applicationType")
    assert not has_savings_term_deposit_evidence(term)
