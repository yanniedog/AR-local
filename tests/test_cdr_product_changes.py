from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

import cdr_product_changes as changes


def fact(
    fact_id: str,
    text: str,
    *,
    provider: str = "Example Bank",
    product_id: str = "P1",
    dataset: str = "Mortgage",
    product_name: str = "Clear Home Loan",
    **extra: object,
) -> dict[str, object]:
    return {
        "provider": provider,
        "productId": product_id,
        "dataset": dataset,
        "productName": product_name,
        "factId": fact_id,
        "factType": "CONDITION",
        "label": fact_id,
        "text": text,
        **extra,
    }


def of_type(payload: dict[str, object], change_type: str) -> list[dict[str, object]]:
    return [row for row in payload["changes"] if row["change_type"] == change_type]


@pytest.mark.parametrize(
    ("before", "after", "slot"),
    [
        ("Customers can redraw.", "Customers cannot redraw.", "negation"),
        ("Customers may redraw.", "Customers must redraw.", "modality"),
        ("Customers may redraw.", "Only customers may redraw.", "applicability_scope"),
        ("Available for loans.", "Available for savings accounts.", "applicability_scope"),
        ("Available to customers.", "Available to customers except businesses.", "exceptions"),
    ],
)
def test_semantic_condition_slot_changes_are_material_and_non_equivalent(
    before: str,
    after: str,
    slot: str,
) -> None:
    payload = changes.diff_normalized_product_facts([fact("access", before)], [fact("access", after)])

    condition = of_type(payload, "condition_changed")[0]
    assert condition["materiality"] == "material"
    assert condition["equivalence"] == "non_equivalent"
    assert condition["review_required"] is False
    assert f"semantic_slot_changed:{slot}" in condition["reasons"]
    assert condition["before"]["text"] == before
    assert condition["after"]["text"] == after


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (
            "Balance must be less than $10,000.",
            "Balance must be greater than $10,000.",
            [{"operator": "<", "value": "10000", "unit": "AUD"}, {"operator": ">", "value": "10000", "unit": "AUD"}],
        ),
        (
            "You must deposit at least 200 dollars.",
            "You must deposit at least 300 dollars.",
            [{"operator": ">=", "value": "200", "unit": "AUD"}, {"operator": ">=", "value": "300", "unit": "AUD"}],
        ),
    ],
)
def test_threshold_operator_or_number_change_is_a_material_range_change(
    before: str,
    after: str,
    expected: list[dict[str, str]],
) -> None:
    before_signature = changes.semantic_clause_signature(before)
    after_signature = changes.semantic_clause_signature(after)
    assert before_signature["thresholds"] == [expected[0]]
    assert after_signature["thresholds"] == [expected[1]]

    payload = changes.diff_normalized_product_facts([fact("threshold", before)], [fact("threshold", after)])
    change = of_type(payload, "range_changed")[0]
    assert change["materiality"] == "material"
    assert change["equivalence"] == "non_equivalent"


def test_cadence_change_is_material_and_exact_evidence_is_retained() -> None:
    before = fact("deposit", "Customers must deposit $200 monthly.")
    after = fact("deposit", "Customers must deposit $200 annually.")

    payload = changes.build_product_changes(
        [before], [after], previous_run_date="2026-08-12", current_run_date="2026-08-13",
    )

    cadence = of_type(payload, "cadence_changed")[0]
    assert cadence["before"] == before
    assert cadence["after"] == after
    assert cadence["materiality"] == "material"
    assert cadence["equivalence"] == "non_equivalent"
    assert payload["previous_run_date"] == "2026-08-12"
    assert payload["current_run_date"] == "2026-08-13"


def test_structured_rate_cadence_change_matches_the_same_entity() -> None:
    common = {
        "provider": "Example Bank", "product_id": "P1", "dataset": "Mortgage",
        "product_name": "Clear Home Loan", "kind": "rate", "canonical_key": "rate.application_frequency",
        "value_type": "duration", "unit": "duration", "source_path": "lendingRates[0].applicationFrequency",
        "source_pattern": "lendingRates[].applicationFrequency",
    }
    before = {**common, "value_text": "P1M", "value_json": '"P1M"', "source_value_json": '"P1M"',
              "qualifiers": {"lendingRateType": "VARIABLE", "applicationFrequency": "P1M"}}
    after = {**common, "value_text": "P1Y", "value_json": '"P1Y"', "source_value_json": '"P1Y"',
             "qualifiers": {"lendingRateType": "VARIABLE", "applicationFrequency": "P1Y"}}
    payload = changes.diff_normalized_product_facts([before], [after])
    assert [event["event_type"] for event in payload["events"]] == ["cadence_changed"]


def test_only_whitespace_case_and_punctuation_is_cosmetic_equivalent() -> None:
    before = fact("redraw", "Customers may redraw, monthly.")
    after = fact("redraw", "  customers MAY redraw monthly!!! ")

    payload = changes.diff_normalized_product_facts([before], [after])

    assert [row["change_type"] for row in payload["changes"]] == ["wording_changed"]
    wording = payload["changes"][0]
    assert wording["materiality"] == "cosmetic"
    assert wording["equivalence"] == "equivalent"
    assert wording["review_required"] is False
    assert wording["before"]["text"] == before["text"]
    assert wording["after"]["text"] == after["text"]


def test_new_content_words_with_same_slots_are_unknown_and_require_review() -> None:
    before = fact("access", "Customers may access accounts monthly.")
    after = fact("access", "Customers may manage accounts monthly.")

    payload = changes.diff_normalized_product_facts([before], [after])

    wording = of_type(payload, "wording_changed")[0]
    assert wording["materiality"] == "review"
    assert wording["equivalence"] == "unknown"
    assert wording["review_required"] is True
    assert wording["reasons"] == ["content_words_changed_with_same_semantic_slots"]


@pytest.mark.parametrize(
    ("before", "after", "slot"),
    [
        ("A fixed rate applies.", "A variable rate applies.", "rate_structure"),
        ("For owner-occupied loans.", "For investment loans.", "occupancy"),
        ("Principal and interest repayments.", "Interest-only repayments.", "repayment_structure"),
        ("Available to new customers.", "Available to existing customers.", "customer_status"),
        ("Australian citizens may apply.", "Permanent residents may apply.", "residency"),
        ("Permanent residents may apply.", "Temporary residents may apply.", "residency"),
        ("Temporary residents may apply.", "Non-residents may apply.", "residency"),
        ("Available to employed applicants.", "Available to self-employed applicants.", "employment"),
        ("Available to individuals.", "Available to businesses and trusts.", "legal_entity"),
        ("Apply online.", "Apply in a branch.", "channel"),
        ("Loan comes with an offset.", "Loan comes without an offset.", "offset_access"),
        ("Interest is calculated before the period.", "Interest is calculated after the period.", "period_timing"),
        ("Interest is calculated after the period.", "Interest is calculated at the end of the period.", "period_timing"),
    ],
)
def test_common_banking_distinctions_are_material_non_equivalent(
    before: str,
    after: str,
    slot: str,
) -> None:
    payload = changes.diff_normalized_product_facts([fact("banking-clause", before)], [fact("banking-clause", after)])

    condition = of_type(payload, "condition_changed")[0]
    assert condition["materiality"] == "material"
    assert condition["equivalence"] == "non_equivalent"
    assert f"semantic_slot_changed:{slot}" in condition["reasons"]
    assert condition["before"]["text"] == before
    assert condition["after"]["text"] == after


def test_structured_value_range_cadence_and_metadata_changes_are_classified() -> None:
    before = fact(
        "fee", "Monthly account fee", value="10", minimum="1", maximum="10",
        frequency="P1M", source_document="old.pdf",
    )
    after = fact(
        "fee", "Monthly account fee", value="12", minimum="2", maximum="12",
        frequency="P1Y", source_document="new.pdf",
    )

    payload = changes.diff_normalized_product_facts([before], [after])

    assert {row["change_type"] for row in payload["changes"]} == {
        "value_changed", "range_changed", "cadence_changed", "metadata_changed",
    }
    for change_type in ("value_changed", "range_changed", "cadence_changed"):
        row = of_type(payload, change_type)[0]
        assert row["materiality"] == "material"
        assert row["equivalence"] == "non_equivalent"
    metadata = of_type(payload, "metadata_changed")[0]
    assert metadata["materiality"] == "review"
    assert metadata["equivalence"] == "unknown"
    assert metadata["review_required"] is True


def test_plain_numeric_rate_change_is_not_duplicated_as_range_change() -> None:
    before = fact(
        "rate", "Advertised rate", fact_type="rate", canonical_key="rate.advertised",
        value_type="rate", value_number=0.05, source_value_json="0.05",
    )
    after = fact(
        "rate", "Advertised rate", fact_type="rate", canonical_key="rate.advertised",
        value_type="rate", value_number=0.06, source_value_json="0.06",
    )
    payload = changes.diff_normalized_product_facts([before], [after])
    assert [event["event_type"] for event in payload["events"]] == ["value_changed"]


def test_stable_provider_product_id_dataset_join_detects_product_rename() -> None:
    before = fact("rate", "Advertised rate", product_name="Clear Home Loan", value="0.06")
    after = fact("rate", "Advertised rate", product_name="Clearer Home Loan", value="0.06")

    payload = changes.diff_normalized_product_facts([before], [after])

    rename = of_type(payload, "product_renamed")[0]
    assert rename["product"] == {
        "provider": "Example Bank", "product_id": "P1", "dataset": "Mortgage",
    }
    assert rename["before"] == {"product_name": "Clear Home Loan"}
    assert rename["after"] == {"product_name": "Clearer Home Loan"}
    assert rename["materiality"] == "review"
    assert rename["equivalence"] == "unknown"
    assert rename["review_required"] is True
    assert not of_type(payload, "product_added")
    assert not of_type(payload, "product_removed")


def test_cosmetic_product_rename_is_equivalent() -> None:
    before = fact("rate", "Advertised rate", product_name="Clear Home-Loan", value="0.06")
    after = fact("rate", "Advertised rate", product_name="clear home loan!", value="0.06")

    rename = of_type(changes.diff_normalized_product_facts([before], [after]), "product_renamed")[0]

    assert rename["materiality"] == "cosmetic"
    assert rename["equivalence"] == "equivalent"
    assert rename["review_required"] is False


def test_product_and_fact_add_remove_records_are_deterministic() -> None:
    old = fact("old", "Old condition", product_id="OLD")
    retained = fact("retained", "Unchanged")
    removed_fact = fact("removed", "Removed")
    new = fact("new", "New condition", product_id="NEW")
    added_fact = fact("added", "Added")

    payload = changes.diff_normalized_product_facts(
        [old, retained, removed_fact],
        [new, deepcopy(retained), added_fact],
    )

    change_types = [row["change_type"] for row in payload["changes"]]
    assert change_types.count("product_added") == 1
    assert change_types.count("product_removed") == 1
    assert change_types.count("fact_added") == 2
    assert change_types.count("fact_removed") == 2
    assert payload["products"] == {"previous": 2, "current": 2, "joined": 1}
    assert payload == changes.diff_normalized_product_facts(
        [old, retained, removed_fact],
        [new, deepcopy(retained), added_fact],
    )


def test_missing_identity_fails_closed_and_ambiguous_duplicates_require_review() -> None:
    missing = fact("x", "Text")
    missing.pop("provider")
    with pytest.raises(ValueError, match="provider"):
        changes.diff_normalized_product_facts([missing], [])

    payload = changes.diff_normalized_product_facts(
        [fact("x", "Customers may redraw."), fact("x", "Customers may offset.")],
        [fact("x", "Customers must redraw."), fact("x", "Customers must offset.")],
    )
    ambiguous = of_type(payload, "ambiguous_match")
    assert len(ambiguous) == 1
    assert ambiguous[0]["materiality"] == "review"
    assert ambiguous[0]["equivalence"] == "unknown"
    assert ambiguous[0]["review_required"] is True
    assert "ambiguous_duplicate_facts" in ambiguous[0]["reasons"]
    assert len(ambiguous[0]["before"]["candidates"]) == 2
    assert len(ambiguous[0]["after"]["candidates"]) == 2


def rate_tier(index: int, minimum: float, maximum: float, rate: float) -> list[dict[str, object]]:
    common = {
        "provider": "Example Bank",
        "product_id": "P1",
        "dataset": "Mortgage",
        "product_name": "Clear Home Loan",
        "qualifiers": {
            "lendingRateType": "VARIABLE",
            "loanPurpose": "OWNER_OCCUPIED",
            "repaymentType": "PRINCIPAL_AND_INTEREST",
        },
    }
    base = f"lendingRates[0].tiers[{index}]"
    return [
        {
            **common,
            "fact_id": f"rate-{index}",
            "kind": "rate",
            "canonical_key": "rate.advertised",
            "value_type": "rate",
            "value": rate,
            "unit": "fraction",
            "source_path": f"{base}.rate",
            "source_pattern": "lendingRates[].tiers[].rate",
            "source_value_json": str(rate),
        },
        {
            **common,
            "fact_id": f"range-{index}",
            "kind": "tier",
            "canonical_key": "range.value",
            "value_type": "range",
            "value": None,
            "min_value": minimum,
            "max_value": maximum,
            "unit": "fraction",
            "source_path": base,
            "source_pattern": "lendingRates[].tiers[]",
            "source_value_json": f'{{"maximumValue": {maximum}, "minimumValue": {minimum}, "rate": {rate}}}',
        },
    ]


def test_reordering_repeated_rate_entities_produces_no_change() -> None:
    previous = [*rate_tier(0, 0.0, 0.6, 0.057), *rate_tier(1, 0.6001, 0.8, 0.059)]
    current = [*rate_tier(1, 0.0, 0.6, 0.057), *rate_tier(0, 0.6001, 0.8, 0.059)]

    payload = changes.diff_normalized_product_facts(previous, current)

    assert payload["events"] == []
    assert payload["change_count"] == 0


def test_inserting_rate_among_repeated_rates_only_adds_inserted_entity_facts() -> None:
    previous = [*rate_tier(0, 0.0, 0.6, 0.057), *rate_tier(1, 0.8001, 0.9, 0.061)]
    current = [
        *rate_tier(0, 0.0, 0.6, 0.057),
        *rate_tier(1, 0.6001, 0.8, 0.059),
        *rate_tier(2, 0.8001, 0.9, 0.061),
    ]

    payload = changes.diff_normalized_product_facts(previous, current)

    assert [row["change_type"] for row in payload["events"]] == ["fact_added", "fact_added"]
    assert {row["after"]["source_value_json"] for row in payload["events"]} == {
        "0.059", '{"maximumValue": 0.8, "minimumValue": 0.6001, "rate": 0.059}',
    }
    assert not of_type(payload, "value_changed")
    assert not of_type(payload, "range_changed")
    assert not of_type(payload, "ambiguous_match")


def write_finalized_export(root: Path, rows: list[dict[str, object]]) -> None:
    export = root / "_exports"
    export.mkdir(parents=True)
    (export / f"banks-{root.name}.json").write_text(
        json.dumps({"run_date": root.name, "product_facts": rows}), encoding="utf-8",
    )


def test_run_integration_reads_finalized_normalized_fact_exports(tmp_path: Path) -> None:
    previous = tmp_path / "2026-08-12"
    current = tmp_path / "2026-08-13"
    write_finalized_export(previous, [fact("access", "Customers may access accounts.")])
    write_finalized_export(current, [fact("access", "Customers must access accounts.")])

    report = changes.compare_runs(previous, current / "_exports")

    assert report["previous_run_date"] == "2026-08-12"
    assert report["current_run_date"] == "2026-08-13"
    assert of_type(report, "condition_changed")[0]["equivalence"] == "non_equivalent"


def test_raw_fallback_and_finalized_export_use_the_same_normalized_shape(tmp_path: Path) -> None:
    previous = tmp_path / "2026-08-12"
    detail = previous / "banks" / "Mortgage" / "Example Bank" / "Clear Home Loan" / "P1"
    detail.mkdir(parents=True)
    record = {
        "productId": "P1", "name": "Clear Home Loan", "description": "Customers may redraw.",
        "features": [], "eligibility": [], "constraints": [], "fees": [], "lendingRates": [],
    }
    (detail / "product-detail.json").write_text(json.dumps({"data": record}), encoding="utf-8")
    fallback_rows = changes.load_run_facts(previous)
    current = tmp_path / "2026-08-13"
    write_finalized_export(current, fallback_rows)
    report = changes.compare_runs(previous, current)
    assert report["events"] == []
    assert report["change_count"] == 0


def test_previous_finalized_run_ignores_partial_sibling(tmp_path: Path) -> None:
    finalized = tmp_path / "2026-08-11"
    partial = tmp_path / "2026-08-12"
    current = tmp_path / "2026-08-13"
    write_finalized_export(finalized, [fact("access", "Text")])
    (partial / "banks").mkdir(parents=True)
    current.mkdir()

    assert changes.previous_finalized_run(current) == finalized


def test_previous_finalized_run_skips_legacy_export_without_facts(tmp_path: Path) -> None:
    legacy = tmp_path / "2026-08-11"
    legacy_export = legacy / "_exports"
    legacy_export.mkdir(parents=True)
    (legacy_export / "banks-2026-08-11.json").write_text(json.dumps({"products": []}), encoding="utf-8")
    compatible = tmp_path / "2026-08-12"
    write_finalized_export(compatible, [fact("access", "Text")])
    current = tmp_path / "2026-08-13"
    current.mkdir()
    assert changes.previous_finalized_run(current) == compatible
