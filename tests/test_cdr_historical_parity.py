"""Row-multiset and conservative semantic-repair tests."""

from __future__ import annotations

from copy import deepcopy

from cdr_historical_parity import (
    absence_evidence,
    canonical_rows,
    classify_savings_product,
    compare_row_multisets,
    duplicate_rows,
    raw_semantic_collisions,
    semantic_rate_collisions,
    td_fallback_evidence,
    td_fallback_strata,
    typed_rate_value,
)


def test_cross_format_parity_uses_multisets_not_lossy_identity_maps() -> None:
    left = [
        {"product_id": "same", "rate": 0.05},
        {"product_id": "same", "rate": 0.05},
        {"product_id": "same", "rate": 0.06},
    ]
    right = list(reversed(left))
    result = compare_row_multisets(left, right)
    assert result.equal
    assert result.left_count == result.right_count == 3
    assert [row.original_index for row in canonical_rows(left)] == [0, 1, 2]
    assert duplicate_rows(left) == ((0, 1),)


def test_cross_format_parity_preserves_duplicate_population() -> None:
    left = [{"product_id": "AMP_LAND_HL", "rate": 0.1}] * 2
    right = left[:1]
    result = compare_row_multisets(left, right)
    assert not result.equal
    assert result.missing == 1
    assert result.extra == 0


def test_semantic_rate_collision_excludes_index_but_not_distinct_applicability() -> None:
    base = {
        "dataset": "SAVINGS",
        "provider": "Example",
        "product_id": "one",
        "product_key": "one",
        "rate_family": "deposit",
        "rate_type": "VARIABLE",
        "application_type": "MINIMUM",
        "term": "",
    }
    rows = [
        {**base, "rate_index": 0, "rate": 0.04, "comparison_rate": None},
        {**base, "rate_index": 1, "rate": 0.05, "comparison_rate": None},
        {**base, "rate_index": 2, "rate": 0.05, "comparison_rate": None, "term": "P1Y"},
    ]
    groups, count, indices = semantic_rate_collisions(rows)
    assert (groups, count, indices) == (1, 2, ((0, 1),))


def test_raw_collision_maps_one_based_indices_to_every_flattened_expansion() -> None:
    products = [
        {
            "product_key": "bank|product",
            "provider": "bank",
            "product_id": "product",
            "details_json": (
                '{"depositRates":['
                '{"rate":"0.04","comparisonRate":"0.04","calculationFrequency":"P1D","tiers":[{"name":"all"}]},'
                '{"rate":"0.05","comparisonRate":"0.055","calculationFrequency":"P1D","tiers":[{"name":"all"}]},'
                '{"rate":"0.06","calculationFrequency":"P1M","tiers":[{"name":"all"}]}'
                "]}"
            ),
        }
    ]
    flattened = [
        {"product_key": "bank|product", "rate_family": "deposit", "rate_index": 1},
        {"product_key": "bank|product", "rate_family": "deposit", "rate_index": 2},
        {"product_key": "bank|product", "rate_family": "deposit", "rate_index": 2},
        {"product_key": "bank|product", "rate_family": "deposit", "rate_index": 3},
    ]
    for row in flattened:
        row.update(provider="bank", product_id="product")
    summary = raw_semantic_collisions(products, flattened)
    assert (
        summary.conflicting_groups,
        summary.conflicting_rows,
        summary.duplicate_same_value_groups,
        summary.duplicate_same_value_rows,
        summary.nonunique_rows,
    ) == (1, 3, 0, 0, 3)
    assert summary.records[0]["raw_rate_indices"] == [1, 2, 2]


def test_raw_collision_keeps_same_value_duplicates_out_of_conflicts() -> None:
    products = [{
        "provider": "bank", "product_id": "product", "product_key": "bank|product",
        "details_json": '{"depositRates":[{"rate":"0.04","calculationFrequency":"P1D"}]}'
    }]
    row = {
        "provider": "bank", "product_id": "product", "product_key": "bank|product",
        "rate_family": "deposit", "rate_index": 1,
    }
    summary = raw_semantic_collisions(products, [row, dict(row)])
    assert (summary.conflicting_groups, summary.conflicting_rows) == (0, 0)
    assert (summary.duplicate_same_value_groups, summary.duplicate_same_value_rows) == (1, 2)
    assert summary.nonunique_rows == 2


def test_td_fallback_evidence_strata_and_no_evidence_null_contract() -> None:
    rows = [
        {"term_months": "12", "term": "P1Y6M", "product_name": "Deposit"},
        {"term_months": "12", "term": "P6M/P8M", "product_name": "Deposit"},
        {"term_months": "12", "term": "", "product_name": "18 month saver"},
        {"term_months": "12", "term": "", "product_name": "Deposit"},
        {"term_months": "12", "term": "P7D", "product_name": "Deposit"},
        {"term_months": "12", "term": "P12M", "product_name": "Deposit"},
    ]
    assert td_fallback_strata(rows) == {
        "exact_iso": 1,
        "structured_range": 1,
        "text_derived": 1,
        "no_evidence": 1,
        "submonth_iso_quarantine": 1,
    }
    assert td_fallback_evidence(rows[3]) == "no_evidence"
    assert td_fallback_evidence(rows[5]) is None


def test_frequency_fields_are_not_misread_as_td_term_evidence() -> None:
    row = {
        "term_months": "12",
        "term": "",
        "product_name": "Deposit",
        "details_json": '{"applicationFrequency":"P1M","calculationFrequency":"P1D"}',
    }
    assert td_fallback_evidence(row) == "no_evidence"


def test_mixed_rate_units_fail_closed_and_product_rates_are_not_rba_units() -> None:
    assert typed_rate_value({"rate": 0.0435}) == {
        "legacy_raw_value": 0.0435,
        "legacy_normalized_value": 0.0435,
        "typed_value": 0.0435,
        "typed_unit": "fraction",
        "unit_basis": "magnitude_proven",
        "unit_status": "derived",
        "normalization_version": "historical-unit-v1",
    }
    mixed = typed_rate_value({"rate": 0.719}, mixed_scale=True)
    assert mixed["typed_value"] is None
    assert mixed["unit_status"] == "quarantined_mixed_scale"
    ambiguous = typed_rate_value({"rate": 0.35})
    assert ambiguous["typed_value"] is None
    assert ambiguous["typed_unit"] is None


def test_taxonomy_never_confirms_nonordinary_or_legacy_bucket_as_savings() -> None:
    cases = [
        ({"dataset": "TD", "product_name": "Term Deposit"}, "confirmed_exclusion"),
        ({"dataset": "SAVINGS", "category": "TRANS_AND_SAVINGS_ACCOUNTS", "product_name": "Mortgage Offset"}, "quarantined"),
        ({"dataset": "BUSINESS_LOANS", "product_name": "Business Loan"}, "confirmed_exclusion"),
        ({"dataset": "SAVINGS", "category": "TRANS_AND_SAVINGS_ACCOUNTS", "product_name": "Saver"}, "ambiguous"),
        ({"dataset": "SAVINGS", "product_name": "Restricted staff only"}, "quarantined"),
        ({"dataset": "UNKNOWN", "product_name": "Mystery"}, "quarantined"),
    ]
    for row, expected in cases:
        assert classify_savings_product(row)["status"] == expected


def test_absent_fee_and_eligibility_evidence_is_unknown_not_zero_or_unrestricted() -> None:
    for kind in ("fees", "eligibility"):
        value = absence_evidence([], kind)
        assert value["state"] == "unavailable"
        assert value["value"] is None
        assert "zero" in value["reason"] or "unrestricted" in value["reason"]


def test_details_json_is_compared_structurally_without_erasing_duplicates() -> None:
    left = [{"id": "a", "details_json": '{"b":2,"a":1}'}, {"id": "a", "details_json": '{"a":1,"b":2}'}]
    right = deepcopy(left)
    right.reverse()
    assert compare_row_multisets(left, right).equal
    assert duplicate_rows(left) == ((0, 1),)
