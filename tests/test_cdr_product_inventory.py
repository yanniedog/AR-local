from __future__ import annotations

import hashlib
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
from cdr_raw_attempt_journal import RawAttemptJournal


OBSERVED_AT = "2026-09-02T01:02:03Z"
DETAIL_EVIDENCE = hashlib.sha256(b"{}").hexdigest()


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
    def provider_observation(number: int, name: str) -> dict[str, object]:
        return {
            "provider_dir": name,
            "provider_uid": _provider(number),
            "provider_identity_status": "official",
            "provider_identity_held": False,
            "brand_name": name,
            "legal_entity_name": "",
            "endpoint_url": f"https://bank-{number}.example/cds-au/v1/banking/products",
            "data_holder_id": f"holder-{number}",
            "data_holder_brand_id": f"brand-{number}",
            "interim_id": "",
            "identity_authority": f"bank-{number}.example",
            "population": populations[name],
        }
    banks = {
        "provider_observations": [
            provider_observation(1, "Bank One"),
            provider_observation(2, "Bank Two"),
        ],
        "products": [{
            "provider_uid": P1,
            "product_uid": product_uid(P1, "Savings", "save-1"),
            "product_id": "save-1",
            "product_name": "Everyday Saver",
            "dataset": "Savings",
            "legacy_product_key": "Bank One|save-1|TRANS_AND_SAVINGS_ACCOUNTS|Everyday Saver",
            "evidence_id": DETAIL_EVIDENCE,
            "effective_to": "",
        }],
        "rates": [{
            "product_uid": product_uid(P1, "Savings", "save-1"),
            "rate_index": 1,
            "rate": "0.05",
            "comparison_rate": "",
            "evidence_id": DETAIL_EVIDENCE,
        }],
        "fees": [],
        "features": [],
        "eligibility": [],
        "constraints": [],
        "product_facts": [],
        "product_changes": [],
        "quarantines": [],
    }
    session_id = "ingest-20260902T000000Z-test"
    journal = RawAttemptJournal(root / "_raw-attempt-journals-v1", session_id)
    register = {
        "data": [
            {
                "dataHolderId": f"holder-{number}",
                "dataHolderBrandId": f"brand-{number}",
                "brandName": f"Bank {name}",
                "publicBaseUri": f"https://bank-{number}.example/cds-au/v1/banking/products",
            }
            for number, name in ((1, "One"), (2, "Two"))
        ]
    }
    journal.record(
        "register-1",
        request_url="https://register.example/holders",
        status=200,
        outcome="success",
        body=json.dumps(register).encode(),
        context={"phase": "register_discovery"},
    )
    for index, (provider, product_id_value, product_category) in enumerate(
        (
            ("Bank One", "save-1", "TRANS_AND_SAVINGS_ACCOUNTS"),
            ("Bank Two", "home-1", "RESIDENTIAL_MORTGAGES"),
        ),
        1,
    ):
        body = json.dumps(
            {
                "data": {
                    "products": [
                        {
                            "productId": product_id_value,
                            "productCategory": product_category,
                        }
                    ]
                }
            }
        ).encode()
        journal.record(
            f"index-{index}",
            request_url=f"https://bank-{index}.example/products",
            status=200,
            outcome="success",
            body=body,
            context={"phase": "products_index", "provider": provider, "page": 1},
        )
    journal.record(
        "detail-save-1",
        request_url="https://bank-1.example/products/save-1",
        status=200,
        outcome="success",
        body=b"{}",
        context={
            "phase": "product_detail",
            "provider": "Bank One",
            "product_id": "save-1",
        },
    )
    journal_summary = journal.summary(recover=False)
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
            **journal_summary,
            "path": f"_raw-attempt-journals-v1/{session_id}",
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


def test_optional_detail_rejection_publishes_only_valid_core(tmp_path: Path) -> None:
    root, banks, status = _inputs(tmp_path)
    banks["products"][0]["details_complete"] = True
    banks["quarantines"] = [
        {
            "bank": "Bank One",
            "product_id": "save-1",
            "status": "field_omitted_invalid",
            "affected_sections": ["fees"],
            "evidence_digest": "b" * 64,
        }
    ]
    accounting, observed_at, _ = build_product_inventory(
        root, banks, status=status, observed_at=OBSERVED_AT
    )
    saver = next(
        row for row in accounting["products"] if row["cdr_product_id"] == "save-1"
    )
    assert saver["disposition"] == "published_core_only"
    assert saver["reason_codes"] == ["field_omitted_invalid"]
    projections = build_projections(banks, accounting)
    assert projections["products"][0]["document"]["details_complete"] is False
    result = build_observation_database(
        tmp_path / "detail-array.sqlite",
        accounting=accounting,
        projections=projections,
        generated_at=observed_at,
        normalization_version="cdr-product-facts-v1",
    )
    assert result.verification.sidecar_bytes == canonical_json_bytes(accounting)


def test_trust_critical_field_rejection_quarantines_product(tmp_path: Path) -> None:
    root, banks, status = _inputs(tmp_path)
    banks["quarantines"] = [
        {
            "bank": "Bank One",
            "product_id": "save-1",
            "status": "field_omitted_invalid",
            "affected_sections": ["rates"],
            "evidence_digest": "b" * 64,
        }
    ]
    accounting, _, _ = build_product_inventory(
        root, banks, status=status, observed_at=OBSERVED_AT
    )
    saver = next(
        row for row in accounting["products"] if row["cdr_product_id"] == "save-1"
    )
    assert saver["disposition"] == "quarantined_invalid"


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


def test_changed_product_detail_fails_journal_binding(tmp_path: Path) -> None:
    root, banks, status = _inputs(tmp_path)
    detail = next(root.rglob("product-detail.json"))
    detail.write_text('{"data":{"productId":"save-1","name":"forged"}}', encoding="utf-8")
    with pytest.raises(ProductInventoryError, match="disagrees with current journal"):
        build_product_inventory(root, banks, status=status, observed_at=OBSERVED_AT)


def test_path_derived_dataset_must_match_journal_classification(tmp_path: Path) -> None:
    root, banks, status = _inputs(tmp_path)
    source = next((root / "banks/Savings/Bank One").rglob("product-id.txt")).parent
    destination = root / "banks/TD/Bank One/Everyday Saver" / source.name
    destination.parent.mkdir(parents=True)
    source.rename(destination)
    moved_uid = product_uid(P1, "TD", "save-1")
    banks["products"][0].update(
        dataset="TD",
        product_uid=moved_uid,
        legacy_product_key="Bank One|save-1|TERM_DEPOSITS|Everyday Saver",
    )
    banks["rates"][0]["product_uid"] = moved_uid

    with pytest.raises(ValueError, match="dataset does not match"):
        build_product_inventory(root, banks, status=status, observed_at=OBSERVED_AT)


def test_staged_provider_identity_must_match_register_journal(tmp_path: Path) -> None:
    root, banks, status = _inputs(tmp_path)
    banks["provider_observations"][0]["data_holder_brand_id"] = "substituted-brand"

    with pytest.raises(ProductInventoryError, match="register journal"):
        build_product_inventory(root, banks, status=status, observed_at=OBSERVED_AT)


def test_removed_provider_change_preserves_historical_identity_and_evidence(
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
            "historical_evidence_id": "f" * 64,
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

    assert len(rows) == 1
    assert rows[0]["provider_uid"] == removed_provider
    assert rows[0]["product_uid"] == old_product
    assert rows[0]["document"]["historical_evidence_id"] == "f" * 64
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


def test_duplicate_rows_for_a_quarantined_product_do_not_block_valid_products(
    tmp_path: Path,
) -> None:
    root, banks, status = _inputs(tmp_path)
    home_uid = product_uid(P2, "Mortgage", "home-1")
    duplicate = {
        "provider_uid": P2,
        "product_uid": home_uid,
        "product_id": "home-1",
        "product_name": "Home Loan",
        "dataset": "Mortgage",
        "legacy_product_key": "Bank Two|home-1|RESIDENTIAL_MORTGAGES|Home Loan",
        "evidence_id": "f" * 64,
        "effective_to": "",
    }
    banks["products"].extend([duplicate, dict(duplicate)])
    accounting, _, _ = build_product_inventory(
        root, banks, status=status, observed_at=OBSERVED_AT
    )

    assert next(
        row["disposition"]
        for row in accounting["products"]
        if row["product_uid"] == home_uid
    ) == "quarantined_invalid"
    projections = build_projections(banks, accounting)
    assert {row["cdr_product_id"] for row in projections["products"]} == {"save-1"}


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
