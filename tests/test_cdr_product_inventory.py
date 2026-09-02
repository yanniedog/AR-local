from __future__ import annotations

import json
from pathlib import Path

import pytest

from cdr_contracts import canonical_json_bytes
from cdr_contracts import product_uid, provider_uid
from cdr_observation import (
    build_observation,
    build_projections,
    write_observation,
)
from cdr_observation_db import build_observation_database
from cdr_product_inventory import ProductInventoryError, build_product_inventory


OBSERVED_AT = "2026-09-02T01:02:03Z"


def _provider(number: int) -> str:
    return provider_uid(
        data_holder_id=f"holder-{number}",
        data_holder_brand_id=f"brand-{number}",
        endpoint_urls=(),
        display_name=f"Bank {number}",
    )[0]


P1, P2 = _provider(1), _provider(2)


def _captured_product(root: Path, dataset: str, bank: str, name: str, product_id: str, *, detail: bool) -> Path:
    leaf = root / "banks" / dataset / bank / name / f"{product_id}__token"
    leaf.mkdir(parents=True)
    (leaf / "product-id.txt").write_text(product_id + "\n", encoding="utf-8")
    if detail:
        (leaf / "product-detail.json").write_text("{}", encoding="utf-8")
    else:
        (leaf / "product-detail.error.txt").write_text("unavailable", encoding="utf-8")
    return leaf


def _inputs(tmp_path: Path) -> tuple[Path, dict, dict]:
    root = tmp_path / "2026-09-02"
    _captured_product(root, "Savings", "Bank One", "Everyday Saver", "save-1", detail=True)
    _captured_product(root, "Mortgage", "Bank Two", "Home Loan", "home-1", detail=False)
    failure = {"phase": "product_detail", "bank": "Bank Two", "product_id": "home-1", "status": 503}
    (root / "banks" / "failures.jsonl").write_text(json.dumps(failure) + "\n", encoding="utf-8")
    populations = {
        "Bank One": {"schema_version": 1, "provider_uid": P1, "state": "complete", "population_known": True, "population_errors": [], "duplicate_conflicts": []},
        "Bank Two": {"schema_version": 1, "provider_uid": P2, "state": "partial", "population_known": True, "population_errors": [], "duplicate_conflicts": []},
    }
    banks = {
        "provider_observations": [
            {"provider_dir": "Bank One", "provider_uid": P1, "brand_name": "Bank One", "population": populations["Bank One"]},
            {"provider_dir": "Bank Two", "provider_uid": P2, "brand_name": "Bank Two", "population": populations["Bank Two"]},
        ],
        "products": [{
            "provider_uid": P1,
            "product_uid": product_uid(P1, "Savings", "save-1"),
            "product_id": "save-1",
            "product_name": "Everyday Saver",
            "dataset": "Savings",
            "legacy_product_key": "Bank One|save-1|TRANS_AND_SAVINGS_ACCOUNTS|Everyday Saver",
            "evidence_id": "a" * 64,
            "effective_to": "",
        }],
        "rates": [{
            "product_uid": product_uid(P1, "Savings", "save-1"),
            "rate_index": 1,
            "rate": "0.05",
            "comparison_rate": "",
        }],
        "fees": [],
        "features": [],
        "eligibility": [],
        "constraints": [],
        "product_facts": [],
        "product_changes": [],
        "quarantines": [],
    }
    status = {
        "providers_registered": 2,
        "providers_attempted": 2,
        "provider_states": [
            {"provider_uid": P1, "brand_name": "Bank One", "state": "complete", "population_known": True, "products_discovered": 1},
            {"provider_uid": P2, "brand_name": "Bank Two", "state": "partial", "population_known": True, "products_discovered": 1},
        ],
        "provider_state_counts": {"complete": 1, "partial": 1, "empty": 0, "failed": 0},
        "register_provenance_complete": True,
        "failure_provenance_complete": True,
        "coverage_evidence_complete": True,
        "register_attempts": [],
        "raw_attempt_journal": {
            "schema_version": 1,
            "session_id": "ingest-20260902T000000Z-test",
            "attempts": 3,
            "head_digest": "d" * 64,
            "verified": True,
        },
    }
    return root, banks, status


def test_every_selected_product_is_published_or_quarantined(tmp_path: Path) -> None:
    root, banks, status = _inputs(tmp_path)
    accounting, observed_at, blockers = build_product_inventory(
        root, banks, status=status, observed_at=OBSERVED_AT
    )
    dispositions = {
        row["cdr_product_id"]: row["disposition"] for row in accounting["products"]
    }
    assert dispositions == {"save-1": "published_full", "home-1": "quarantined_invalid"}
    assert accounting["summary"]["products"] == {
        "discovered": 2,
        "published_full": 1,
        "published_core_only": 0,
        "omitted_valid": 0,
        "quarantined_invalid": 1,
        "consumer_visible": 1,
    }
    issue = next(item for item in accounting["issues"] if item["product_uid"] == product_uid(P2, "Mortgage", "home-1"))
    assert issue["code"] == "cdr_error"
    assert issue["http_status"] == 503
    assert observed_at == OBSERVED_AT
    assert blockers == []


def test_valid_product_without_a_current_rate_is_explicitly_omitted(tmp_path: Path) -> None:
    root, banks, status = _inputs(tmp_path)
    banks["rates"] = []
    accounting, _, _ = build_product_inventory(root, banks, status=status, observed_at=OBSERVED_AT)
    saver = next(row for row in accounting["products"] if row["cdr_product_id"] == "save-1")
    assert saver["disposition"] == "omitted_valid"
    assert saver["reason_codes"] == ["no_current_rate"]


def test_detail_array_quarantine_reason_round_trips_exactly(tmp_path: Path) -> None:
    root, banks, status = _inputs(tmp_path)
    banks["quarantines"] = [
        {
            "bank": "Bank One",
            "product_id": "save-1",
            "status": "detail_array_invalid",
            "evidence_digest": "b" * 64,
        }
    ]
    accounting, observed_at, _ = build_product_inventory(
        root, banks, status=status, observed_at=OBSERVED_AT
    )
    saver = next(
        row for row in accounting["products"] if row["cdr_product_id"] == "save-1"
    )
    assert saver["disposition"] == "quarantined_invalid"
    assert saver["reason_codes"] == ["detail_array_invalid"]
    result = build_observation_database(
        tmp_path / "detail-array.sqlite",
        accounting=accounting,
        projections=build_projections(banks, accounting),
        generated_at=observed_at,
        normalization_version="cdr-product-facts-v1",
    )
    assert result.verification.sidecar_bytes == canonical_json_bytes(accounting)


def test_corrupt_or_unattributed_failure_is_recorded_and_blocks_publication(tmp_path: Path) -> None:
    root, banks, status = _inputs(tmp_path)
    with (root / "banks" / "failures.jsonl").open("ab") as stream:
        stream.write(b"not-json\n")
        stream.write(json.dumps({"phase": "holder", "status": "boom"}).encode() + b"\n")
    status["failure_provenance_complete"] = False
    accounting, _, blockers = build_product_inventory(root, banks, status=status, observed_at=OBSERVED_AT)
    assert {"failure_record_corrupt", "failure_unattributed"} <= set(blockers)
    assert {item["code"] for item in accounting["issues"]} >= {
        "failure_record_corrupt", "failure_unattributed"
    }


def test_provider_population_count_mismatch_fails_closed(tmp_path: Path) -> None:
    root, banks, status = _inputs(tmp_path)
    status["provider_states"][0]["products_discovered"] = 2
    with pytest.raises(ValueError, match="product count disagrees"):
        build_product_inventory(root, banks, status=status, observed_at=OBSERVED_AT)


def test_unknown_provider_identity_fails_closed(tmp_path: Path) -> None:
    root, banks, status = _inputs(tmp_path)
    banks["provider_observations"].pop()
    with pytest.raises(ProductInventoryError, match="registered provider population"):
        build_product_inventory(root, banks, status=status, observed_at=OBSERVED_AT)


def test_removed_provider_change_round_trips_prior_canonical_identity(
    tmp_path: Path,
) -> None:
    root, banks, status = _inputs(tmp_path)
    accounting, observed_at, _ = build_product_inventory(
        root, banks, status=status, observed_at=OBSERVED_AT
    )
    removed_provider = _provider(3)
    old_product = product_uid(removed_provider, "Savings", "old-1")
    banks["product_changes"] = [
        {
            "event_id": "a" * 20,
            "provider": "Removed Bank",
            "dataset": "Savings",
            "product_id": "old-1",
            "event_type": "product_removed",
            "before": {
                "provider_uid": removed_provider,
                "product_uid": old_product,
            },
            "after": None,
        }
    ]

    projections = build_projections(banks, accounting)
    rows = projections["product_changes"]
    result = build_observation_database(
        tmp_path / "removed.sqlite",
        accounting=accounting,
        projections=projections,
        generated_at=observed_at,
        normalization_version="cdr-product-facts-v1",
    )

    assert rows[0]["provider_uid"] == removed_provider
    assert rows[0]["product_uid"] == old_product
    assert result.verification.counts["bank_product_changes"] == 1


def test_observation_and_sqlite_contain_only_publishable_products(tmp_path: Path) -> None:
    root, banks, status = _inputs(tmp_path)
    accounting, observed_at, blockers = build_product_inventory(
        root, banks, status=status, observed_at=OBSERVED_AT
    )
    projections = build_projections(banks, accounting)
    observation = build_observation(
        accounting=accounting,
        projections=projections,
        observed_at=observed_at,
        normalization_version="cdr-product-facts-v1",
        blockers=blockers,
    )
    assert observation["state"] == "degraded"
    assert observation["row_counts"] == {
        "products": 1, "rates": 1, "items": 0,
        "product_facts": 0, "product_changes": 0,
    }
    assert {row["cdr_product_id"] for row in observation["products"]} == {"save-1"}
    out = tmp_path / "exports"
    write_observation(out, observation, accounting)
    assert (out / "observation-v1.json").read_bytes() == canonical_json_bytes(observation)
    result = build_observation_database(
        out / "local-cdr.sqlite",
        accounting=accounting,
        projections=projections,
        generated_at=observed_at,
        normalization_version="cdr-product-facts-v1",
    )
    assert result.verification.counts["bank_products"] == 1
    assert len(accounting["products"]) == 2


def test_aggregated_issue_counts_round_trip_through_sqlite(tmp_path: Path) -> None:
    root, banks, status = _inputs(tmp_path)
    failure = (root / "banks" / "failures.jsonl").read_bytes()
    (root / "banks" / "failures.jsonl").write_bytes(failure + failure)
    accounting, observed_at, blockers = build_product_inventory(
        root, banks, status=status, observed_at=OBSERVED_AT
    )
    issue = next(item for item in accounting["issues"] if item["code"] == "cdr_error")
    assert issue["occurrence_count"] == 2
    provider = next(item for item in accounting["providers"] if item["provider_uid"] == P2)
    assert provider["issue_count"] == 2
    projections = build_projections(banks, accounting)
    result = build_observation_database(
        tmp_path / "aggregate.sqlite", accounting=accounting, projections=projections,
        generated_at=observed_at, normalization_version="cdr-product-facts-v1",
    )
    assert result.verification.sidecar_bytes == canonical_json_bytes(accounting)
