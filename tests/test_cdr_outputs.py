from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import pytest

from cdr_attempt_evidence_promotion import promote_attempt_evidence
from cdr_contracts import provider_uid
from cdr_export_contract import load_contract
from cdr_finalization import finalize_observation, verify_completion_marker
from cdr_ingest_sanity import compare_ladders
from cdr_observation_db import SCHEMA_VERSION, verify_observation_database
from cdr_outputs import build_outputs
from cdr_product_change_runs import previous_finalized_run
from cdr_raw_attempt_journal import RawAttemptJournal


OBSERVED_AT = "2026-09-02T01:02:03Z"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _captured_run(
    tmp_path: Path,
    *,
    run_date: str = "2026-09-02",
    rate: str = "0.05",
    brand_name: str = "Bank One",
) -> Path:
    run = tmp_path / run_date
    observed_at = f"{run_date}T01:02:03Z"
    uid, identity_status = provider_uid(
        data_holder_id="holder-1",
        data_holder_brand_id="brand-1",
        endpoint_urls=(),
        display_name=brand_name,
    )
    leaf = run / "banks" / "Savings" / brand_name / "Everyday Saver" / "save-1__token"
    leaf.mkdir(parents=True)
    (leaf / "product-id.txt").write_text("save-1\n", encoding="utf-8")
    _write_json(
        leaf / "product-detail.json",
        {
            "data": {
                "productId": "save-1",
                "name": "Everyday Saver",
                "productCategory": "TRANS_AND_SAVINGS_ACCOUNTS",
                "depositRates": [{"depositRateType": "VARIABLE", "rate": rate}],
            }
        },
    )
    holder = run / "banks" / "_holders" / brand_name
    _write_json(
        holder / "_register-brand.json",
        {
            "provider_uid": uid,
            "provider_identity_status": identity_status,
            "data_holder_id": "holder-1",
            "data_holder_brand_id": "brand-1",
            "brand_name": brand_name,
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
    session = f"ingest-{run_date.replace('-', '')}T000000Z-test"
    register_body = b'{"data":[{"dataHolderBrandId":"brand-1"}]}'
    journal = RawAttemptJournal(run / "_raw-attempt-journals-v1", session)
    journal.record(
        "register:1",
        request_url="https://register.example/holders",
        status=200,
        outcome="success",
        body=register_body,
        started_at=f"{run_date}T01:02:02Z",
        completed_at=observed_at,
        context={"phase": "register_discovery"},
    )
    journal_summary = journal.summary()
    _write_json(
        run / "banks" / "ingest-status.json",
        {
            "total": 0,
            "corrupt_records": 0,
            "unattributed_records": 0,
            "incomplete": False,
            "providers_registered": 1,
            "providers_attempted": 1,
            "provider_states": [
                {
                    "provider_uid": uid,
                    "brand_name": brand_name,
                    "state": "complete",
                    "population_known": True,
                    "products_discovered": 1,
                    "products_in_scope": 1,
                    "products_indexed": 1,
                }
            ],
            "provider_state_counts": {"complete": 1},
            "register_provenance_complete": True,
            "failure_provenance_complete": True,
            "coverage_evidence_complete": True,
            "register_attempts": [
                {
                    "source_url": "https://register.example/holders",
                    "mode": "plain",
                    "ok": True,
                    "status": 200,
                    "bytes": len(register_body),
                    "sha256": hashlib.sha256(register_body).hexdigest(),
                }
            ],
            "raw_attempt_journal": {
                **journal_summary,
                "path": f"_raw-attempt-journals-v1/{session}",
                "path_resolution": "relative_to_ingest_run_root",
                "retention": "follows_ingest_run_root",
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


def test_malformed_rate_array_member_is_quarantined_not_silently_dropped(
    tmp_path: Path,
) -> None:
    run = _captured_run(tmp_path)
    detail_path = next(run.rglob("product-detail.json"))
    detail = json.loads(detail_path.read_text(encoding="utf-8"))
    detail["data"]["depositRates"].append("malformed")
    _write_json(detail_path, detail)

    result = build_outputs(run)
    observation = json.loads(
        (run / "_exports/observation-v1.json").read_text(encoding="utf-8")
    )
    accounting = json.loads(
        (run / "_exports/product-accounting-v1.json").read_text(encoding="utf-8")
    )

    assert result["banks"]["rates"] == 0
    assert observation["row_counts"]["rates"] == 0
    assert accounting["products"][0]["disposition"] == "quarantined_invalid"
    assert "rate_invalid" in accounting["products"][0]["reason_codes"]


def test_build_outputs_rejects_noncanonical_database_before_writing(tmp_path: Path) -> None:
    run = tmp_path / "2026-09-02"
    output = tmp_path / "exports"
    database = tmp_path / "elsewhere.sqlite"

    with pytest.raises(ValueError, match="canonical database must be"):
        build_outputs(run, output, database)

    assert not output.exists()
    assert not database.exists()


def test_canonical_outputs_finalize_only_with_promoted_verified_evidence(
    tmp_path: Path,
) -> None:
    run = _captured_run(tmp_path)
    result = build_outputs(run)
    exports = run / "_exports"
    promote_attempt_evidence(run, exports)
    state = tmp_path / "state"
    marker = state / f"{run.name}.done.json"

    finalized = finalize_observation(
        exports,
        state,
        marker,
        observation_date=run.name,
        result=result,
    )

    assert verify_completion_marker(finalized, state, run.name)
    contract = load_contract(state / finalized["export_contract_path"])
    assert contract["observed_at"] == OBSERVED_AT
    assert contract["normalization_version"] == "cdr-product-facts-2"
    assert contract["coverage"]["products_discovered"] == 1
    assert contract["coverage"]["products_published"] == 1
    assert contract["coverage"]["reconciliation_status"] == "reconciled"
    tomorrow = tmp_path / "2026-09-03"
    tomorrow.mkdir()
    assert previous_finalized_run(tomorrow, state_dir=state) == run


def test_finalization_reconciles_accounting_with_in_scope_products(tmp_path: Path) -> None:
    run = _captured_run(tmp_path)
    summary_path = run / "banks/_holders/Bank One/_products-index/index-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary.update(
        unique_product_ids=2,
        relevant_products=1,
        out_of_scope_products=1,
    )
    _write_json(summary_path, summary)
    status_path = run / "banks/ingest-status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["provider_states"][0].update(
        products_discovered=2,
        products_in_scope=1,
        products_out_of_scope=1,
    )
    _write_json(status_path, status)

    result = build_outputs(run)
    exports = run / "_exports"
    promote_attempt_evidence(run, exports)
    finalized = finalize_observation(
        exports,
        tmp_path / "state",
        tmp_path / "state/2026-09-02.done.json",
        observation_date="2026-09-02",
        result=result,
    )

    assert finalized["observation_state"] == "complete"


def test_sanity_check_reads_v9_and_flags_large_rate_change(tmp_path: Path) -> None:
    previous = _captured_run(tmp_path, run_date="2026-09-01", rate="0.05")
    current = _captured_run(tmp_path, run_date="2026-09-02", rate="0.08")
    build_outputs(previous)
    build_outputs(current, previous_run_root=previous)

    findings = compare_ladders(
        current / "_exports" / "local-cdr.sqlite",
        previous / "_exports" / "local-cdr.sqlite",
    )

    assert len(findings) == 1
    assert findings[0]["severity"] == "HIGH"
    assert findings[0]["worst_delta_bp"] == 300.0


def test_sanity_matches_canonical_product_across_brand_rename(tmp_path: Path) -> None:
    previous = _captured_run(
        tmp_path, run_date="2026-09-01", rate="0.05", brand_name="Old Brand"
    )
    current = _captured_run(
        tmp_path, run_date="2026-09-02", rate="0.08", brand_name="New Brand"
    )
    build_outputs(previous)
    build_outputs(current)

    findings = compare_ladders(
        current / "_exports/local-cdr.sqlite",
        previous / "_exports/local-cdr.sqlite",
    )

    assert len(findings) == 1
    assert findings[0]["provider"] == "New Brand"
    assert findings[0]["severity"] == "HIGH"


def test_mobile_payload_is_deterministic_and_bound_to_observation(tmp_path: Path) -> None:
    run = _captured_run(tmp_path)
    build_outputs(run)
    first = app_payload.build_payload(run / "_exports", tmp_path / "payload-a")
    second = app_payload.build_payload(run / "_exports", tmp_path / "payload-b")

    assert first == second
    assert first["generated_at"] == OBSERVED_AT
    assert first["schedule"] and "next_due_utc" not in first["schedule"]
    assert first["counts"]["products"] == 1
    assert first["counts"]["rates"] == 1
    assert first["files"]["core"]["sha256"] == second["files"]["core"]["sha256"]
    core_path = tmp_path / "payload-a" / first["files"]["core"]["name"]
    core = json.loads(gzip.decompress(core_path.read_bytes()))
    rate = core["sections"]["Savings"]["rates"][0]
    assert len(rate["provider_uid"]) > 64
    assert len(rate["product_uid"]) == 64
    assert core["coverage"]["observed_at"] == OBSERVED_AT
    assert core["coverage"]["counts"]["products_discovered"] == 1
import app_payload
