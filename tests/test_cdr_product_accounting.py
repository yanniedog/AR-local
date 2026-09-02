from __future__ import annotations

import copy
import hashlib
import json

import pytest

from cdr_contracts import canonical_json_bytes, product_uid, provider_uid
from cdr_product_accounting import (
    build_product_accounting,
    build_product_accounting_bytes,
    validate_product_accounting,
)


def _provider(number: int) -> str:
    uid, _ = provider_uid(
        data_holder_id=f"holder-{number}",
        data_holder_brand_id=f"brand-{number}",
        endpoint_urls=(),
        display_name=f"Bank {number}",
    )
    return uid


P1 = _provider(1)
P2 = _provider(2)
P3 = _provider(3)
P4 = _provider(4)
P5 = _provider(5)
DIGEST = "d" * 64


def _product(
    provider: str,
    product_id: str,
    disposition: str,
    *,
    dataset: str = "Savings",
    reasons: list[str] | None = None,
    core_valid: bool = True,
    details_complete: bool = True,
    legacy_product_key: str | None = None,
) -> dict[str, object]:
    return {
        "provider_uid": provider,
        "cdr_product_id": product_id,
        "dataset": dataset,
        "display_name": f" {product_id}\tAccount ",
        "legacy_product_key": legacy_product_key,
        "disposition": disposition,
        "reason_codes": reasons or [],
        "evidence_ids": [f"attempt:{product_id}"],
        "core_valid": core_valid,
        "details_complete": details_complete,
    }


def _issue(
    code: str,
    *,
    scope: str,
    provider: str | None,
    product: str | None,
    disposition: str | None,
    sections: list[str],
    phase: str,
    occurrences: int = 1,
    first: str = "2026-09-02T00:01:00+10:00",
    last: str = "2026-09-02T00:02:00+10:00",
) -> dict[str, object]:
    return {
        "scope": scope,
        "provider_uid": provider,
        "product_uid": product,
        "affected_sections": sections,
        "phase": phase,
        "code": code,
        "http_status": 503 if "failed" in code else None,
        "occurrence_count": occurrences,
        "first_seen_at": first,
        "last_seen_at": last,
        "evidence_digest": hashlib.sha256(f"{scope}:{code}".encode()).hexdigest(),
        "disposition": disposition,
        "public_safe": True,
    }


def _inputs() -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    full = _product(P1, "full-1", "published_full", legacy_product_key="legacy-full")
    core = _product(
        P1,
        "core-1",
        "published_core_only",
        reasons=["field_omitted_invalid"],
        details_complete=False,
    )
    omitted = _product(
        P2,
        "closed-1",
        "omitted_valid",
        reasons=["product_closed"],
        core_valid=False,
    )
    products = [full, core, omitted]
    core_uid = product_uid(P1, "Savings", "core-1")
    omitted_uid = product_uid(P2, "Savings", "closed-1")
    issues = [
        _issue(
            "field_omitted_invalid",
            scope="product",
            provider=P1,
            product=core_uid,
            disposition="published_core_only",
            sections=["details"],
            phase="validation",
            occurrences=2,
        ),
        _issue(
            "product_closed",
            scope="product",
            provider=P2,
            product=omitted_uid,
            disposition="omitted_valid",
            sections=["rates", "products"],
            phase="normalization",
        ),
        _issue(
            "products_index_failed",
            scope="provider",
            provider=P3,
            product=None,
            disposition=None,
            sections=["products"],
            phase="products_index",
        ),
        _issue(
            "register_failed",
            scope="register",
            provider=P4,
            product=None,
            disposition=None,
            sections=["register"],
            phase="register_discovery",
        ),
    ]
    providers = [
        {
            "provider_uid": P1,
            "brand_name": " Bank\tOne ",
            "datasets": ["Savings"],
            "state": "complete",
            "attempted": True,
            "population_known": True,
        },
        {
            "provider_uid": P2,
            "brand_name": "Bank Two",
            "datasets": ["Savings"],
            "state": "partial",
            "attempted": True,
            "population_known": True,
        },
        {
            "provider_uid": P3,
            "brand_name": "Bank Three",
            "datasets": [],
            "state": "failed",
            "attempted": True,
            "population_known": False,
        },
        {
            "provider_uid": P4,
            "brand_name": "Bank Four",
            "datasets": [],
            "state": "not_attempted",
            "attempted": False,
            "population_known": False,
        },
        {
            "provider_uid": P5,
            "brand_name": "Bank Five",
            "datasets": [],
            "state": "empty",
            "attempted": True,
            "population_known": True,
        },
    ]
    discovered = {P1: 2, P2: 1, P3: 0, P5: 0}
    status = {
        "providers_registered": 5,
        "providers_attempted": 4,
        "provider_states": [
            {
                "provider_uid": provider,
                "brand_name": next(item["brand_name"] for item in providers if item["provider_uid"] == provider),
                "state": next(item["state"] for item in providers if item["provider_uid"] == provider),
                "population_known": next(
                    item["population_known"] for item in providers if item["provider_uid"] == provider
                ),
                "products_discovered": discovered[provider],
            }
            for provider in (P1, P2, P3, P5)
        ],
        "provider_state_counts": {
            "complete": 1,
            "partial": 1,
            "empty": 1,
            "failed": 1,
        },
        "raw_attempt_journal": {
            "schema_version": 1,
            "session_id": "ingest-20260902T000000000000Z-abcdef123456",
            "attempts": 5,
            "head_digest": DIGEST,
            "verified": True,
            "path": "raw-attempts/ignored-but-not-exported",
        },
    }
    return status, providers, products, issues


def _build() -> dict[str, object]:
    status, providers, products, issues = _inputs()
    return build_product_accounting("2026-09-02", status, providers, products, issues)


def test_build_is_canonical_deterministic_and_dataset_bound() -> None:
    status, providers, products, issues = _inputs()
    document = build_product_accounting("2026-09-02", status, providers, products, issues)
    reversed_document = build_product_accounting(
        "2026-09-02", status, reversed(providers), reversed(products), reversed(issues)
    )
    assert document == reversed_document
    encoded = build_product_accounting_bytes(
        "2026-09-02", status, providers, products, issues
    )
    assert encoded == canonical_json_bytes(document)
    assert not encoded.endswith(b"\n")
    assert json.loads(encoded) == document
    product = next(item for item in document["products"] if item["cdr_product_id"] == "full-1")
    assert product["product_uid"] == product_uid(P1, "Savings", "full-1")
    assert product["product_uid"] != product_uid(P1, "Mortgage", "full-1")
    assert product["display_name"] == "full-1 Account"
    assert "details_complete" in product
    assert "details_valid" not in product
    validate_product_accounting(document)


def test_summaries_and_provider_records_reconcile_occurrences_and_sets() -> None:
    document = _build()
    assert document["summary"] == {
        "providers": {
            "registered": 5,
            "attempted": 4,
            "complete": 1,
            "partial": 1,
            "empty": 1,
            "failed": 1,
            "not_attempted": 1,
            "population_unknown": 2,
        },
        "products": {
            "discovered": 3,
            "published_full": 1,
            "published_core_only": 1,
            "omitted_valid": 1,
            "quarantined_invalid": 0,
            "consumer_visible": 2,
        },
        "issues": {
            "total": 5,
            "corrupt": 0,
            "unattributed": 0,
            "affected_providers": 4,
            "affected_products": 2,
            "by_code": {
                "field_omitted_invalid": 2,
                "product_closed": 1,
                "products_index_failed": 1,
                "register_failed": 1,
            },
        },
    }
    provider_one = next(item for item in document["providers"] if item["provider_uid"] == P1)
    assert provider_one["discovered_count"] == 2
    assert provider_one["published_full_count"] == 1
    assert provider_one["published_core_only_count"] == 1
    assert provider_one["issue_count"] == 2
    assert provider_one["affected_sections"] == ["details"]


def test_duplicate_identical_issues_aggregate_without_changing_identity() -> None:
    status, providers, products, issues = _inputs()
    duplicate = copy.deepcopy(issues[0])
    duplicate["occurrence_count"] = 3
    duplicate["first_seen_at"] = "2026-09-01T13:59:00Z"
    duplicate["last_seen_at"] = "2026-09-01T14:03:00Z"
    document = build_product_accounting(
        "2026-09-02", status, providers, products, [*issues, duplicate]
    )
    issue = next(item for item in document["issues"] if item["code"] == "field_omitted_invalid")
    assert issue["occurrence_count"] == 5
    assert issue["first_seen_at"] == "2026-09-01T13:59:00Z"
    assert issue["last_seen_at"] == "2026-09-01T14:03:00Z"
    assert document["summary"]["issues"]["total"] == 8


def test_schema_rejects_unknown_fields_enums_and_details_valid_alias() -> None:
    document = _build()
    document["products"][0]["details_valid"] = document["products"][0].pop("details_complete")
    with pytest.raises(ValueError, match="schema violation"):
        validate_product_accounting(document)

    status, providers, products, issues = _inputs()
    products[0]["unexpected"] = True
    with pytest.raises(ValueError, match="unexpected"):
        build_product_accounting("2026-09-02", status, providers, products, issues)

    status, providers, products, issues = _inputs()
    issues[0]["phase"] = "anything"
    with pytest.raises(ValueError, match="issue phase"):
        build_product_accounting("2026-09-02", status, providers, products, issues)


def test_rejects_unverified_journal_and_ingest_provider_drift() -> None:
    status, providers, products, issues = _inputs()
    status["raw_attempt_journal"]["verified"] = False
    with pytest.raises(ValueError, match="journal must be verified"):
        build_product_accounting("2026-09-02", status, providers, products, issues)

    status, providers, products, issues = _inputs()
    status["provider_states"][0]["products_discovered"] = 99
    with pytest.raises(ValueError, match="product count disagrees"):
        build_product_accounting("2026-09-02", status, providers, products, issues)


def test_rejects_disposition_issue_and_reference_mismatches() -> None:
    status, providers, products, issues = _inputs()
    products[1]["reason_codes"] = ["detail_fetch_failed"]
    with pytest.raises(ValueError, match="reason_codes do not reconcile"):
        build_product_accounting("2026-09-02", status, providers, products, issues)

    status, providers, products, issues = _inputs()
    issues[0]["provider_uid"] = P2
    with pytest.raises(ValueError, match="unknown or foreign product"):
        build_product_accounting("2026-09-02", status, providers, products, issues)

    status, providers, products, issues = _inputs()
    issues[0]["scope"] = "provider"
    with pytest.raises(ValueError, match="requires product scope"):
        build_product_accounting("2026-09-02", status, providers, products, issues)


def test_rejects_duplicate_products_legacy_collisions_and_unsafe_evidence() -> None:
    status, providers, products, issues = _inputs()
    products.append(copy.deepcopy(products[0]))
    with pytest.raises(ValueError, match="product_uid values must be unique"):
        build_product_accounting("2026-09-02", status, providers, products, issues)

    status, providers, products, issues = _inputs()
    products[1]["legacy_product_key"] = "legacy-full"
    with pytest.raises(ValueError, match="legacy_product_key"):
        build_product_accounting("2026-09-02", status, providers, products, issues)

    status, providers, products, issues = _inputs()
    products[0]["evidence_ids"] = ["C:\\secret\\raw.json"]
    with pytest.raises(ValueError, match="invalid identifier"):
        build_product_accounting("2026-09-02", status, providers, products, issues)


def test_rejects_bad_product_uid_timestamp_and_provider_assertions() -> None:
    status, providers, products, issues = _inputs()
    products[0]["product_uid"] = "0" * 64
    with pytest.raises(ValueError, match="does not match provider"):
        build_product_accounting("2026-09-02", status, providers, products, issues)

    status, providers, products, issues = _inputs()
    issues[0]["first_seen_at"] = "2026-09-02T00:00:00"
    with pytest.raises(ValueError, match="include a timezone"):
        build_product_accounting("2026-09-02", status, providers, products, issues)

    status, providers, products, issues = _inputs()
    providers[0]["discovered_count"] = 3
    with pytest.raises(ValueError, match="discovered_count does not reconcile"):
        build_product_accounting("2026-09-02", status, providers, products, issues)


def test_external_validation_detects_noncanonical_order_and_summary_tampering() -> None:
    document = _build()
    document["products"] = list(reversed(document["products"]))
    with pytest.raises(ValueError, match="canonical product_uid order"):
        validate_product_accounting(document)

    document = _build()
    document["summary"]["products"]["consumer_visible"] = 99
    with pytest.raises(ValueError, match="summary does not reconcile"):
        validate_product_accounting(document)

    document = _build()
    document["providers"][0]["attempted"] = False
    with pytest.raises(ValueError, match="attempted flag"):
        validate_product_accounting(document)
