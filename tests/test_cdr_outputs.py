from __future__ import annotations

import json
from pathlib import Path

from cdr_contracts import provider_uid
from cdr_observation_db import SCHEMA_VERSION, verify_observation_database
from cdr_outputs import build_outputs


OBSERVED_AT = "2026-09-02T01:02:03Z"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _captured_run(tmp_path: Path) -> Path:
    run = tmp_path / "2026-09-02"
    uid, identity_status = provider_uid(
        data_holder_id="holder-1",
        data_holder_brand_id="brand-1",
        endpoint_urls=(),
        display_name="Bank One",
    )
    leaf = run / "banks" / "Savings" / "Bank One" / "Everyday Saver" / "save-1__token"
    leaf.mkdir(parents=True)
    (leaf / "product-id.txt").write_text("save-1\n", encoding="utf-8")
    _write_json(
        leaf / "product-detail.json",
        {
            "data": {
                "productId": "save-1",
                "name": "Everyday Saver",
                "productCategory": "TRANS_AND_SAVINGS_ACCOUNTS",
                "depositRates": [{"depositRateType": "VARIABLE", "rate": "0.05"}],
            }
        },
    )
    holder = run / "banks" / "_holders" / "Bank One"
    _write_json(
        holder / "_register-brand.json",
        {
            "provider_uid": uid,
            "provider_identity_status": identity_status,
            "data_holder_id": "holder-1",
            "data_holder_brand_id": "brand-1",
            "brand_name": "Bank One",
        },
    )
    _write_json(
        holder / "_products-index" / "index-summary.json",
        {
            "schema_version": 1,
            "provider_uid": uid,
            "identity_status": identity_status,
            "state": "complete",
            "population_known": True,
            "pages_attempted": 1,
            "pages_fetched": 1,
            "terminal_page_reached": True,
            "declared_total_records": 1,
            "product_records_observed": 1,
            "unique_product_ids": 1,
            "duplicate_product_ids": [],
            "duplicate_conflicts": [],
            "malformed_products": 0,
            "population_errors": [],
            "relevant_products": 1,
            "details_present": 1,
            "resumed_details": 0,
            "terminal_detail_failures": [],
        },
    )
    failures = run / "banks" / "failures.jsonl"
    failures.parent.mkdir(parents=True, exist_ok=True)
    failures.write_bytes(b"")
    session = "ingest-20260902T000000Z-test"
    digest = "d" * 64
    journal = run / "banks" / "_raw-attempt-journals-v1" / session
    _write_json(
        journal / "current.json",
        {
            "schema_version": 1,
            "session_id": session,
            "sequence": 1,
            "head_digest": digest,
            "updated_at": OBSERVED_AT,
        },
    )
    _write_json(
        run / "banks" / "ingest-status.json",
        {
            "providers_registered": 1,
            "providers_attempted": 1,
            "provider_states": [
                {
                    "provider_uid": uid,
                    "brand_name": "Bank One",
                    "state": "complete",
                    "population_known": True,
                    "products_discovered": 1,
                    "products_indexed": 1,
                }
            ],
            "provider_state_counts": {"complete": 1},
            "register_provenance_complete": True,
            "failure_provenance_complete": True,
            "coverage_evidence_complete": True,
            "register_attempts": [],
            "raw_attempt_journal": {
                "schema_version": 1,
                "path": f"banks/_raw-attempt-journals-v1/{session}",
                "session_id": session,
                "attempts": 1,
                "head_digest": digest,
                "verified": True,
            },
        },
    )
    return run


def test_build_outputs_is_minimal_deterministic_and_verified(tmp_path: Path) -> None:
    run = _captured_run(tmp_path)

    first = build_outputs(run)
    exports = run / "_exports"
    first_observation = (exports / "observation-v1.json").read_bytes()
    second = build_outputs(run)

    assert {path.name for path in exports.iterdir()} == {
        "local-cdr.sqlite",
        "observation-v1.json",
        "product-accounting-v1.json",
    }
    assert first == second
    assert (exports / "observation-v1.json").read_bytes() == first_observation
    observation = json.loads(first_observation)
    assert observation["observed_at"] == OBSERVED_AT
    assert observation["state"] == "complete"
    assert observation["row_counts"]["products"] == 1
    assert observation["row_counts"]["rates"] == 1
    verification = verify_observation_database(exports / "local-cdr.sqlite")
    assert verification.counts["bank_products"] == 1
    assert SCHEMA_VERSION == 9
    assert not list(exports.glob("*-wal"))
    assert not list(exports.glob("*-shm"))
    assert not (exports / "dashboard-cache").exists()

