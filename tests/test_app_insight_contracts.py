"""Small payload integrity tests that do not duplicate retired pipelines."""

from __future__ import annotations

import json

import app_payload_build
import app_payload_contracts
import cdr_clean_export


def test_official_product_links_preserve_only_allowlisted_https_metadata():
    record = {
        "additionalInformation": {
            "overviewUri": "https://www.amp.com.au/home-loans/interest-rates-fees",
            "termsUri": "https://www.amp.com.au/bankterms",
            "feesAndPricingUri": "https://www.amp.com.au/fees.pdf",
            "applicationUri": "https://www.amp.com.au/apply",
        }
    }
    cleaned = json.loads(cdr_clean_export.detail_json(record))
    assert set(cleaned["additionalInformation"]) == {
        "overviewUri", "termsUri", "feesAndPricingUri",
    }


def test_official_product_links_reject_unsafe_urls():
    record = {
        "additionalInformation": {
            "overviewUri": "http://example.test/product",
            "termsUri": "https://user:secret@example.test/terms",
        }
    }
    assert cdr_clean_export.official_product_links(record) == {}


def test_clean_export_fee_value_supports_cdr_fee_shapes():
    assert cdr_clean_export.bank_detail_item_value(
        "fees", {"feeType": "EVENT", "amount": "80.00"}
    ) == "80.00"
    assert cdr_clean_export.bank_detail_item_value(
        "fees",
        {"feeType": "UPFRONT", "fixedAmount": {"amount": "250"}},
    ) == "250"
    assert cdr_clean_export.bank_detail_item_value(
        "fees",
        {"feeType": "VARIABLE", "variable": {"feeMinimum": "5.00"}},
    ) == "5.00.."
    assert cdr_clean_export.bank_detail_item_value(
        "fees",
        {"feeType": "VARIABLE", "variable": {"feeMaximum": "10.00"}},
    ) == "..10.00"
    assert cdr_clean_export.bank_detail_item_value(
        "fees", {"feeType": "EVENT", "amount": "null", "balanceRate": "0.01"}
    ) == "0.01"


def test_rebuild_timestamp_is_not_in_content_hashed_coverage():
    coverage = {
        "schema_version": 1,
        "observed_on": "2026-08-04",
        "counts": {},
        "sections": {},
        "provider_failures": [],
        "source_generated_at": "2026-08-04T01:00:00Z",
    }
    first = app_payload_build._stable_payload_coverage(
        {"coverage": coverage}, {}, "2026-08-04"
    )
    coverage["source_generated_at"] = "2026-08-04T02:00:00Z"
    second = app_payload_build._stable_payload_coverage(
        {"coverage": coverage}, {}, "2026-08-04"
    )
    assert first == second
    assert "source_generated_at" not in first


def test_coverage_exposes_failure_provenance():
    coverage = cdr_clean_export.coverage_summary(
        {
            "rates": [{
                "dataset": "Mortgage", "provider": "Observed Bank",
                "product_key": "observed|home", "account_class": "standard",
            }],
            "products": [{"provider": "Observed Bank"}],
            "failures": [
                {"bank": "Observed Bank", "phase": "rates", "status": "partial"},
                {"bank": "Failed Bank", "phase": "products", "status": "timeout"},
            ],
            "holder_attempts": ["Observed Bank", "Empty Bank", "Failed Bank"],
        },
        "2026-08-04",
    )
    assert coverage["observed_on"] == "2026-08-04"
    assert coverage["providers_succeeded"] == 2
    assert coverage["providers_attempted"] == 3
    assert coverage["failures"] == coverage["provider_failures"]
    assert coverage["counts"]["providers_partial"] == 1
    assert coverage["counts"]["providers_failed"] == 1
    app_payload_contracts.validate_coverage(coverage)


def test_parse_banks_run_counts_successful_empty_holder_attempts(tmp_path):
    run_root = tmp_path / "2026-08-04"
    (run_root / "banks" / "_holders" / "Observed Bank").mkdir(parents=True)
    (run_root / "banks" / "_holders" / "Empty Bank").mkdir(parents=True)

    banks = cdr_clean_export.parse_banks_run(run_root)
    assert banks["holder_attempts"] == ["Empty Bank", "Observed Bank"]
    coverage = cdr_clean_export.coverage_summary(banks, "2026-08-04")
    assert coverage["providers_attempted"] == 2
    assert coverage["providers_succeeded"] == 2


def test_cdr_decimal_rates_are_never_rescaled_before_export():
    rows = [{"rate": "0.85"}, {"rate": "0.65"}]
    divisor = cdr_clean_export.rate_divisor(rows, "deposit")
    assert divisor == 1
    assert cdr_clean_export.normalized_rate_text("0.85", divisor, "deposit") == "0.85"
