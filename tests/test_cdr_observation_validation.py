from __future__ import annotations

import pytest

from cdr_contracts import parse_rate_string, provider_uid
from cdr_observation import (
    ObservationError,
    _fact_projections,
    build_observation,
    validate_observation,
)
from cdr_observation_db import ObservationDatabaseError
from tests.test_cdr_observation_db import observation as valid_observation_inputs


def _empty_accounting() -> dict:
    return {
        "schema_version": 1,
        "observation_date": "2026-09-03",
        "accounting_id": "test-observation-validation",
        "raw_attempt_journal_digest": "0" * 64,
        "providers": [],
        "products": [],
        "issues": [],
        "summary": {
            "providers": {
                "registered": 0, "attempted": 0, "complete": 0, "partial": 0,
                "empty": 0, "failed": 0, "not_attempted": 0, "population_unknown": 0,
            },
            "products": {
                "discovered": 0, "published_full": 0, "published_core_only": 0,
                "omitted_valid": 0, "quarantined_invalid": 0, "consumer_visible": 0,
            },
            "issues": {
                "total": 0, "corrupt": 0, "unattributed": 0,
                "affected_providers": 0, "affected_products": 0, "by_code": {},
            },
        },
    }


def test_observed_at_must_resolve_to_observation_date_in_hobart() -> None:
    accounting, projections = valid_observation_inputs()
    with pytest.raises(ObservationError, match="observation date"):
        build_observation(
            accounting=accounting,
            projections=projections,
            observed_at="2027-05-25T00:00:00Z",
            normalization_version="test-v1",
        )
    built = build_observation(
        accounting=accounting,
        projections=projections,
        observed_at="2026-05-24T15:00:00Z",
        normalization_version="test-v1",
    )
    assert built["observed_at"] == "2026-05-24T15:00:00Z"


def test_observation_requires_a_provider_and_publishable_product() -> None:
    projections = {
        group: []
        for group in (
            "products", "rates", "items", "product_facts", "product_changes"
        )
    }
    with pytest.raises(ObservationError, match="no_registered_providers"):
        build_observation(
            accounting=_empty_accounting(),
            projections=projections,
            observed_at="2026-09-02T15:00:00Z",
            normalization_version="test-v1",
        )


def test_rate_fact_projection_rejects_percentage_scaled_value() -> None:
    with pytest.raises(ObservationError, match="rate fact"):
        _fact_projections(
            [
                {
                    "product_uid": "a" * 64,
                    "fact_id": "rate-fact",
                    "kind": "rate",
                    "canonical_key": "rate.advertised",
                    "value_type": "rate",
                    "value_boolean": None,
                    "value_number": 100.0,
                    "value_text": None,
                    "min_value": None,
                    "max_value": None,
                    "evidence_id": "e" * 64,
                }
            ],
            {"a" * 64},
            evidence_by_uid={"a" * 64: "e" * 64},
            observation_date="2026-09-03",
        )


@pytest.mark.parametrize("value", ["-0", "-0.00"])
def test_rate_parser_rejects_signed_zero(value: str) -> None:
    with pytest.raises(ValueError):
        parse_rate_string(value)


@pytest.mark.parametrize(
    "value_type,values",
    [
        ("text", {"value_number": 1.0}),
        ("boolean", {}),
        ("range", {"value_text": "1..2"}),
    ],
)
def test_fact_projection_requires_value_type_shape(value_type, values) -> None:
    row = {
        "product_uid": "a" * 64,
        "fact_id": "typed-fact",
        "kind": "attribute",
        "canonical_key": "product.example",
        "value_type": value_type,
        "value_boolean": None,
        "value_number": None,
        "value_text": None,
        "min_value": None,
        "max_value": None,
        "evidence_id": "e" * 64,
        **values,
    }
    with pytest.raises(ObservationError, match="value_type"):
        _fact_projections(
            [row], {"a" * 64},
            evidence_by_uid={"a" * 64: "e" * 64},
            observation_date="2026-09-03"
        )


def test_fact_projection_rejects_reversed_range() -> None:
    with pytest.raises(ObservationError, match="range bounds are reversed"):
        _fact_projections(
            [
                {
                    "product_uid": "a" * 64,
                    "fact_id": "range-fact",
                    "kind": "tier",
                    "canonical_key": "tier.balance",
                    "value_type": "range",
                    "value_boolean": None,
                    "value_number": None,
                    "value_text": None,
                    "min_value": 2,
                    "max_value": 1,
                    "evidence_id": "e" * 64,
                }
            ],
            {"a" * 64},
            evidence_by_uid={"a" * 64: "e" * 64},
            observation_date="2026-09-03",
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("last_updated", "not-a-date"),
    ],
)
def test_public_source_dates_are_parseable_and_bounded(field, value) -> None:
    accounting, projections = valid_observation_inputs()
    projections["products"][0]["document"][field] = value
    with pytest.raises(ObservationDatabaseError, match="public"):
        build_observation(
            accounting=accounting,
            projections=projections,
            observed_at="2026-05-24T15:00:00Z",
            normalization_version="test-v1",
        )


def test_future_effective_dates_are_valid_when_ordered() -> None:
    accounting, projections = valid_observation_inputs()
    product = projections["products"][0]["document"]
    product["effective_from"] = "2026-05-27"
    product["effective_to"] = "2026-05-28T00:00:01+10:00"

    build_observation(
        accounting=accounting,
        projections=projections,
        observed_at="2026-05-24T15:00:00Z",
        normalization_version="test-v1",
    )


def test_reversed_effective_dates_are_rejected() -> None:
    accounting, projections = valid_observation_inputs()
    product = projections["products"][0]["document"]
    product["effective_from"] = "2026-05-28"
    product["effective_to"] = "2026-05-27"

    with pytest.raises(ObservationDatabaseError, match="effective"):
        build_observation(
            accounting=accounting,
            projections=projections,
            observed_at="2026-05-24T15:00:00Z",
            normalization_version="test-v1",
        )


def test_global_accounting_failure_blocks_publication() -> None:
    accounting = _empty_accounting()
    uid = provider_uid(
        data_holder_id="holder-1",
        data_holder_brand_id="brand-1",
        endpoint_urls=(),
        display_name="Bank One",
    )[0]
    accounting["providers"] = [
        {
            "provider_uid": uid,
            "brand_name": "Bank One",
            "datasets": [],
            "affected_sections": [],
            "state": "not_attempted",
            "attempted": False,
            "population_known": False,
            "discovered_count": 0,
            "published_full_count": 0,
            "published_core_only_count": 0,
            "omitted_valid_count": 0,
            "quarantined_invalid_count": 0,
            "issue_count": 0,
            "issue_ids": [],
        }
    ]
    accounting["summary"]["providers"].update(
        registered=1, not_attempted=1, population_unknown=1
    )
    projections = {
        group: []
        for group in (
            "products", "rates", "items", "product_facts", "product_changes"
        )
    }
    with pytest.raises(ObservationError, match="provider_not_attempted"):
        build_observation(
            accounting=accounting,
            projections=projections,
            observed_at="2026-09-02T15:00:00Z",
            normalization_version="test-v1",
        )


def test_observation_state_is_recomputed_during_validation() -> None:
    accounting, projections = valid_observation_inputs()
    observation = build_observation(
        accounting=accounting,
        projections=projections,
        observed_at="2026-05-24T15:00:00Z",
        normalization_version="test-v1",
    )
    observation["state"] = "degraded"
    with pytest.raises(ObservationError, match="state disagrees"):
        validate_observation(observation, accounting)
