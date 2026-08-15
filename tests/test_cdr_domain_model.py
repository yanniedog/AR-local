import json
import hashlib
import os
import re
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from cdr_domain import (
    Availability,
    ClassificationStatus,
    ConsumerSection,
    DisclosureStatus,
    FeeRateUnit,
    IdentityStatus,
    ProductKind,
    RateUnit,
    PricingStatus,
    canonical_json_bytes,
    classify_product,
    normalize_product,
    provider_uid,
    to_primitive,
    validate_contract,
    validate_canonical_product,
)
from cdr_domain.rates import basis_point_change, product_rate, rba_cash_rate
from cdr_domain.evidence import product_evidence, published_https_urls
from cdr_domain.rates import decimal_text


FIXTURE = Path(__file__).parent / "fixtures" / "canonical_domain_real_observations.json"
FIXTURE_SHA256 = "d8fecece5e5eedd1c250ee1672f069660236bdbdd12d5b8e68f6977ba5e41f2a"


def captured(name):
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]


def normalized(name, *, record=None):
    item = captured(name)
    provider = item["provider"]
    return normalize_product(
        record or item["record"],
        dataset=item["dataset"],
        provider_display_name=provider,
        register_holder_id=None,
        authority=f"legacy-export:{provider.casefold()}",
        observed_at=item["observed_at"],
        source_path="tests/fixtures/canonical_domain_real_observations.json",
        source_locator=f"/observations/{name}/record",
        source_sha256=hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
        source_kind="preserved_cdr_fixture_projection",
        legacy_aliases=(
            f"{item['dataset']}|{provider}|{item['record']['productId']}",
        ),
    )


def test_real_product_rename_preserves_product_identity():
    before = normalized("bank_of_melbourne_before_rename")
    after = normalized("bank_of_melbourne_after_rename")

    assert before.display_name == "Investment Cash Account"
    assert after.display_name == "Investment Cash Accounts"
    assert before.identity.product_uid == after.identity.product_uid
    assert before.identity.provider_uid == after.identity.provider_uid
    assert before.identity.provider_identity_status is IdentityStatus.FALLBACK
    assert before.identity.legacy_aliases == (
        "Savings|Bank of Melbourne|BOMInvestmentCashAccounts",
    )
    assert before.classification.classification_status is ClassificationStatus.CONFIRMED
    assert after.classification.classification_status is ClassificationStatus.CONFIRMED


def test_fixture_slices_are_hash_bound_and_reextract_from_preserved_exports_when_available():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == FIXTURE_SHA256
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"]
    for name, item in fixture.items():
        encoded = json.dumps(
            item["record"], ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        assert hashlib.sha256(encoded).hexdigest() == item["fixture_record_sha256"]
        evidence = normalized(name).evidence_refs[0]
        assert evidence.source_sha256 == FIXTURE_SHA256
        assert evidence.source_locator == f"/observations/{name}/record"
        assert evidence.source_record_sha256 == item["fixture_record_sha256"]

    snapshot = os.environ.get("AR_PRESERVATION_SNAPSHOT")
    if not snapshot:
        pytest.skip("set AR_PRESERVATION_SNAPSHOT for preserved-byte provenance proof")
    root = Path(snapshot) / "pi" / "data"

    def subset(expected, actual):
        if isinstance(expected, dict):
            return isinstance(actual, dict) and all(
                key in actual and subset(value, actual[key])
                for key, value in expected.items()
            )
        if isinstance(expected, list):
            return isinstance(actual, list) and all(
                any(subset(value, candidate) for candidate in actual)
                for value in expected
            )
        return expected == actual

    for item in fixture.values():
        source = root / item["source_path"]
        source_bytes = source.read_bytes()
        assert hashlib.sha256(source_bytes).hexdigest() == item["source_sha256"]
        payload = json.loads(source_bytes)
        match = re.fullmatch(r"products\[([0-9]+)\]\.details_json", item["source_locator"])
        assert match is not None
        source_record = json.loads(payload["products"][int(match.group(1))]["details_json"])
        source_record_bytes = json.dumps(
            source_record, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        assert hashlib.sha256(source_record_bytes).hexdigest() == item["source_record_sha256"]
        assert subset(item["record"], source_record)


def test_real_mortgage_offset_is_quarantined_from_savings_and_zero_is_not_a_savings_signal():
    product = normalized("afg_mortgage_offset")

    assert product.classification.product_kind is ProductKind.MORTGAGE_OFFSET
    assert product.classification.classification_status is ClassificationStatus.QUARANTINED
    assert product.classification.consumer_section is None
    assert product.classification.quarantine_reason == "mortgage_linked_offset"
    assert product.evidence.availability is Availability.LINKED
    assert product.rates[0].advertised.value == "0"


def test_real_interest_bearing_transaction_account_is_not_relabelled_as_savings():
    product = normalized("amp_transaction_account_with_interest")

    assert product.rates[0].advertised.value == "0.045"
    assert product.classification.product_kind is ProductKind.TRANSACTION_ACCOUNT
    assert product.classification.classification_status is ClassificationStatus.QUARANTINED
    assert product.classification.consumer_section is None
    assert product.classification.quarantine_reason == "transaction_account"


def test_decimal_canonicalization_preserves_significant_trailing_zeroes():
    assert decimal_text("350.00") == "350"
    assert decimal_text("250000") == "250000"
    product = normalized("amp_transaction_account_with_interest")
    assert product.rates[0].semantic_tier["tiers"][0]["maximum"] == "250000"


@pytest.mark.parametrize(
    "description",
    (
        "This loan cannot be used for business purposes.",
        "You do not need to own commercial property.",
        "Interest is processed on the first business day.",
    ),
)
def test_negated_or_incidental_business_words_do_not_quarantine_personal_mortgages(description):
    record = deepcopy(captured("move_bank_ambiguous_rates")["record"])
    record["description"] = description
    result = classify_product(record, "mortgage")
    assert result.classification_status is ClassificationStatus.CONFIRMED
    assert result.consumer_section is ConsumerSection.MORTGAGE


def test_actual_business_product_is_quarantined():
    record = deepcopy(captured("move_bank_ambiguous_rates")["record"])
    record["name"] = "Business Home Loan"
    result = classify_product(record, "Mortgage")
    assert result.classification_status is ClassificationStatus.QUARANTINED
    assert result.quarantine_reason == "business_product"


def test_holder_without_official_brand_identity_remains_fallback():
    uid, status = provider_uid(
        register_holder_id="holder-1",
        authority="legacy-export:test-bank",
        display_name="Test Bank",
    )
    assert uid.startswith("provider-fallback:v1:")
    assert status is IdentityStatus.FALLBACK


def test_real_variable_zero_fee_remains_unknown_and_percentage_fee_is_not_annual_interest():
    product = normalized("afg_mortgage_offset")
    fees = {str(fee.semantic_fee["name"]): fee for fee in product.fees}

    assert fees["Bendigo Bank ATM Deposit"].fixed_amount == "0"
    assert fees["Bendigo Bank ATM Deposit"].disclosure_status is DisclosureStatus.PARTIAL
    assert fees["Bendigo Bank ATM Enquiry"].fixed_amount is None
    assert fees["Bendigo Bank ATM Enquiry"].disclosure_status is DisclosureStatus.UNKNOWN
    transaction_rate = fees["International Transaction Fee"].rate
    assert transaction_rate is not None
    assert transaction_rate.value == "0.03"
    assert transaction_rate.unit is FeeRateUnit.FRACTION_OF_AMOUNT
    assert product.evidence.fee_disclosure_status is DisclosureStatus.PARTIAL


def test_real_ambiguous_move_bank_tiers_cannot_power_exact_alerts():
    product = normalized("move_bank_ambiguous_rates")

    assert len(product.rates) == 3
    assert len({rate.identity.rate_uid for rate in product.rates}) == 1
    assert all(
        rate.identity.rate_identity_status is IdentityStatus.AMBIGUOUS
        for rate in product.rates
    )
    assert not any(rate.exact_alert_eligible for rate in product.rates)
    assert {rate.advertised.value for rate in product.rates} == {
        "0.0639",
        "0.0629",
        "0.0609",
    }


def test_applicability_text_changes_rate_identity():
    before = normalized("afg_mortgage_offset")
    changed_record = deepcopy(captured("afg_mortgage_offset")["record"])
    changed_record["depositRates"][0]["additionalInfo"] = "No linked loan is required."
    after = normalized("afg_mortgage_offset", record=changed_record)
    assert before.rates[0].identity.rate_uid != after.rates[0].identity.rate_uid


def test_real_rate_identities_are_independent_of_source_array_order():
    item = captured("move_bank_ambiguous_rates")
    reversed_record = deepcopy(item["record"])
    reversed_record["lendingRates"].reverse()

    before = normalized("move_bank_ambiguous_rates")
    after = normalized("move_bank_ambiguous_rates", record=reversed_record)

    signature = lambda rate: (rate.advertised.value, rate.identity.rate_uid)
    assert sorted(map(signature, before.rates)) == sorted(map(signature, after.rates))


def test_real_td_without_structured_duration_stays_null():
    product = normalized("bank_of_china_td_without_structured_term")

    assert product.classification.product_kind is ProductKind.TERM_DEPOSIT
    assert product.classification.consumer_section is ConsumerSection.TERM_DEPOSIT
    assert product.rates[0].semantic_tier["duration"] is None
    assert "P1Y" not in json.dumps(to_primitive(product))


def test_product_rba_and_change_units_are_explicit_and_mixed_product_units_fail_closed():
    product = product_rate("0.054", rate_type="VARIABLE", evidence_id="evidence:test")
    rba = rba_cash_rate("4.35", evidence_id="evidence:test")
    change = basis_point_change("25", evidence_id="evidence:test")

    assert product.unit is RateUnit.FRACTION_PER_ANNUM
    assert rba.unit is RateUnit.PERCENTAGE_POINTS
    assert change.unit is RateUnit.BASIS_POINTS
    with pytest.raises(ValueError, match="fractions per annum"):
        product_rate("5.4", rate_type="VARIABLE", evidence_id="evidence:test")


def test_runtime_validation_rejects_a_corrupted_metric_unit_pair():
    product = normalized("move_bank_ambiguous_rates")
    rate = product.rates[0]
    corrupted = replace(
        product,
        rates=(
            replace(rate, advertised=replace(rate.advertised, unit=RateUnit.BASIS_POINTS)),
            *product.rates[1:],
        ),
    )

    with pytest.raises(ValueError, match="metric/unit/basis mismatch"):
        validate_canonical_product(corrupted)

    primitive = to_primitive(product)
    primitive["rates"][0]["advertised"]["unit"] = "basis_points"
    with pytest.raises(ValueError, match="canonical-core-v3"):
        validate_contract(
            "canonical-core-v3.schema.json",
            {
                "schema_version": 3,
                "normalization_version": product.normalization_version,
                "observation_date": "2026-08-14",
                "products": [primitive],
            },
        )


def test_product_rate_slots_reject_non_product_metrics():
    product = normalized("move_bank_ambiguous_rates")
    rate = product.rates[0]
    rba_rate = rba_cash_rate(
        "4.35", evidence_id=product.evidence_refs[0].evidence_id
    )

    corrupt = replace(product, rates=(replace(rate, advertised=rba_rate),))
    with pytest.raises(ValueError, match="product-interest metric"):
        validate_canonical_product(corrupt)
    primitive = to_primitive(corrupt)
    with pytest.raises(ValueError, match="canonical-core-v3"):
        validate_contract(
            "canonical-core-v3.schema.json",
            {
                "schema_version": 3,
                "normalization_version": product.normalization_version,
                "observation_date": "2026-08-14",
                "products": [primitive],
            },
        )

    corrupt = replace(product, rates=(replace(rate, comparison=rba_rate),))
    with pytest.raises(ValueError, match="comparison_interest"):
        validate_canonical_product(corrupt)
    primitive = to_primitive(corrupt)
    with pytest.raises(ValueError, match="canonical-core-v3"):
        validate_contract(
            "canonical-core-v3.schema.json",
            {
                "schema_version": 3,
                "normalization_version": product.normalization_version,
                "observation_date": "2026-08-14",
                "products": [primitive],
            },
        )


def test_unknown_nested_evidence_and_contradictory_fees_fail_closed():
    product = normalized("afg_mortgage_offset")
    corrupted = replace(
        product,
        evidence=replace(product.evidence, evidence_ids=("evidence:v1:" + "f" * 64,)),
    )
    with pytest.raises(ValueError, match="unknown evidence"):
        validate_canonical_product(corrupted)

    source_ref = product.evidence_refs[0]
    corrupted = replace(
        product,
        evidence_refs=(
            replace(
                source_ref,
                source_locator=source_ref.source_locator + "/tampered",
                source_record_sha256="0" * 64,
            ),
        ),
    )
    with pytest.raises(ValueError, match="canonical derivation"):
        validate_canonical_product(corrupted)

    fake_product_uid = "product:v1:" + "f" * 64
    corrupted = replace(
        product,
        identity=replace(product.identity, product_uid=fake_product_uid),
        rates=tuple(
            replace(rate, identity=replace(rate.identity, product_uid=fake_product_uid))
            for rate in product.rates
        ),
    )
    with pytest.raises(ValueError, match="product_uid.*canonical derivation"):
        validate_canonical_product(corrupted)

    corrupted = replace(
        product,
        rates=(
            replace(
                product.rates[0],
                identity=replace(
                    product.rates[0].identity, rate_uid="rate:v1:" + "f" * 64
                ),
            ),
        ),
    )
    with pytest.raises(ValueError, match="rate_uid.*canonical derivation"):
        validate_canonical_product(corrupted)

    corrupted = replace(
        product,
        fees=(replace(product.fees[0], fee_uid="fee:v1:" + "f" * 64),),
    )
    with pytest.raises(ValueError, match="fee_uid.*canonical derivation"):
        validate_canonical_product(corrupted)

    corrupted = replace(
        product,
        fees=(
            replace(
                product.fees[0],
                semantic_fee={**product.fees[0].semantic_fee, "name": "Tampered"},
            ),
        ),
    )
    with pytest.raises(ValueError, match="fee_uid.*canonical derivation"):
        validate_canonical_product(corrupted)

    record = deepcopy(captured("afg_mortgage_offset")["record"])
    record["fees"] = [
        {
            "name": "Contradictory fee",
            "feeType": "TRANSACTION",
            "amount": "10",
            "rateBased": {"rate": "0.03"},
        }
    ]
    with pytest.raises(ValueError, match="contradictory pricing methods"):
        normalized("afg_mortgage_offset", record=record)

    record["fees"] = [
        {
            "name": "Invalid range fee",
            "feeType": "VARIABLE",
            "variable": {"feeMinimum": "99", "feeMaximum": "11"},
        }
    ]
    with pytest.raises(ValueError, match="minimum amount cannot exceed"):
        normalized("afg_mortgage_offset", record=record)


def test_empty_rates_are_unpriced_and_private_literal_source_urls_are_excluded():
    record = {
        "productId": "empty",
        "name": "Empty Saver",
        "productCategory": "SAVINGS_ACCOUNTS",
        "depositRates": [],
        "additionalInformation": [
            {"url": "https://127.0.0.1/private"},
            {"url": "https://192.168.1.1/private"},
            {"url": "https://example.com/public"},
        ],
    }
    classification = classify_product(record, "savings")
    evidence = product_evidence(
        record,
        classification,
        evidence_id="evidence:v1:" + "a" * 64,
        observed_at="2026-08-14T00:00:00+10:00",
    )
    assert evidence.pricing_status is PricingStatus.UNPRICED
    assert published_https_urls(record) == ("https://example.com/public",)


def test_effective_date_and_source_update_timestamp_remain_distinct():
    record = deepcopy(captured("move_bank_ambiguous_rates")["record"])
    record["effectiveFrom"] = "2026-07-31T04:00:00Z"
    record["lastUpdated"] = "2026-07-30T10:14:48.510573Z"
    product = normalized("move_bank_ambiguous_rates", record=record)
    assert product.evidence.effective_date == "2026-07-31T04:00:00Z"
    assert product.evidence.source_updated_at == "2026-07-30T10:14:48.510573Z"
    assert product.evidence_refs[0].effective_date == product.evidence.effective_date
    assert product.evidence_refs[0].source_updated_at == product.evidence.source_updated_at

    invalid = replace(
        product,
        evidence=replace(product.evidence, effective_date="not-a-date"),
        evidence_refs=(replace(product.evidence_refs[0], effective_date="not-a-date"),),
    )
    with pytest.raises(ValueError, match="RFC3339"):
        validate_canonical_product(invalid)

    invalid = replace(
        product,
        evidence_refs=(
            replace(
                product.evidence_refs[0],
                effective_date="2026-08-01T00:00:00Z",
            ),
        ),
    )
    with pytest.raises(ValueError, match="lineage timestamps disagree"):
        validate_canonical_product(invalid)


def test_nonzero_fixed_fee_without_currency_is_partial_not_complete():
    record = deepcopy(captured("afg_mortgage_offset")["record"])
    record["fees"] = [
        {"name": "Published amount without unit", "feeType": "TRANSACTION", "amount": "10"}
    ]
    product = normalized("afg_mortgage_offset", record=record)
    assert product.fees[0].currency is None
    assert product.fees[0].fixed_amount == "10"
    assert product.fees[0].disclosure_status is DisclosureStatus.PARTIAL
    assert product.evidence.fee_disclosure_status is DisclosureStatus.UNKNOWN


def test_canonical_serialization_is_deterministic_and_float_free():
    product = normalized("afg_mortgage_offset")

    first = canonical_json_bytes(product)
    second = canonical_json_bytes(product)
    assert first == second
    assert json.loads(first)["schema_version"] == 3
    with pytest.raises(TypeError, match="binary floating-point"):
        canonical_json_bytes({"rate": 0.05})


def test_real_normalized_products_satisfy_the_canonical_core_schema():
    products = [
        to_primitive(normalized(name))
        for name in (
            "bank_of_melbourne_before_rename",
            "afg_mortgage_offset",
            "move_bank_ambiguous_rates",
            "amp_transaction_account_with_interest",
            "bank_of_china_td_without_structured_term",
        )
    ]
    validate_contract(
        "canonical-core-v3.schema.json",
        {
            "schema_version": 3,
            "normalization_version": "canonical-v3-domain-v1",
            "observation_date": "2026-08-14",
            "products": products,
        },
    )


def test_app_facing_schema_rejects_corrupt_rate_fee_and_evidence_values():
    product = to_primitive(normalized("afg_mortgage_offset"))

    corrupt = deepcopy(product)
    corrupt["rates"][0]["advertised"]["value"] = "5.4"
    with pytest.raises(ValueError, match="canonical-core-v3"):
        validate_contract(
            "canonical-core-v3.schema.json",
            {
                "schema_version": 3,
                "normalization_version": "canonical-v3-domain-v1",
                "observation_date": "2026-08-14",
                "products": [corrupt],
            },
        )

    corrupt = deepcopy(product)
    corrupt["fees"][0]["fixed_amount"] = "-1"
    with pytest.raises(ValueError, match="canonical-core-v3"):
        validate_contract(
            "canonical-core-v3.schema.json",
            {
                "schema_version": 3,
                "normalization_version": "canonical-v3-domain-v1",
                "observation_date": "2026-08-14",
                "products": [corrupt],
            },
        )

    corrupt = deepcopy(product)
    corrupt["fees"][0]["evidence_ids"] = ["invented"]
    with pytest.raises(ValueError, match="canonical-core-v3"):
        validate_contract(
            "canonical-core-v3.schema.json",
            {
                "schema_version": 3,
                "normalization_version": "canonical-v3-domain-v1",
                "observation_date": "2026-08-14",
                "products": [corrupt],
            },
        )

    corrupt = deepcopy(product)
    corrupt["evidence"]["effective_date"] = "not-a-date"
    with pytest.raises(ValueError, match="canonical-core-v3"):
        validate_contract(
            "canonical-core-v3.schema.json",
            {
                "schema_version": 3,
                "normalization_version": "canonical-v3-domain-v1",
                "observation_date": "2026-08-14",
                "products": [corrupt],
            },
        )
