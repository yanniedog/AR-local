from __future__ import annotations

from pathlib import Path

from cdr_attempt_evidence_promotion import promote_attempt_evidence
from cdr_contracts import canonical_json_bytes
from cdr_observation import build_observation, write_observation
from cdr_observation_db import build_observation_database
from cdr_raw_attempt_journal import RawAttemptJournal


def _write_promoted_test_evidence(
    exports: Path,
    observation_date: str,
    observed_at: str,
    *,
    provider_uid: str,
    provider_name: str,
    product_id: str,
) -> tuple[str, str, str]:
    session = f"test-{observation_date}"
    source = exports.parent / f".{exports.name}-{session}-source"
    journal = RawAttemptJournal(source / "_raw-attempt-journals-v1", session)
    body = canonical_json_bytes(
        {
            "data": {
                "products": [
                    {
                        "productId": product_id,
                        "productCategory": "TRANS_AND_SAVINGS_ACCOUNTS",
                    }
                ]
            }
        }
    )
    event = journal.record(
        "products:index:1",
        request_url="https://bank.example/cds-au/v1/banking/products",
        status=200,
        outcome="success",
        body=body,
        started_at=observed_at,
        completed_at=observed_at,
        context={"phase": "products_index", "provider": provider_name, "page": 1},
    )
    journal.record(
        "product:unrelated",
        request_url="https://bank.example/cds-au/v1/banking/products/unrelated",
        status=200,
        outcome="success",
        body=b'{"data":{"product":{"productId":"unrelated"}}}',
        started_at=observed_at,
        completed_at=observed_at,
        context={
            "phase": "product_detail",
            "provider": provider_name,
            "product_id": "unrelated",
        },
    )
    summary = journal.summary(recover=False)
    status = {
        "providers_registered": 1,
        "providers_attempted": 1,
        "provider_states": [
            {
                "provider_uid": provider_uid,
                "provider_dir": provider_name,
                "brand_name": provider_name,
                "legal_entity_name": "",
                "endpoint_url": "https://bank.example/cds-au/v1/banking/products",
                "state": "complete",
                "population_known": True,
                "products_in_scope": 1,
            }
        ],
        "raw_attempt_journal": {
            **summary,
            "path": f"_raw-attempt-journals-v1/{session}",
            "path_resolution": "relative_to_ingest_run_root",
            "retention": "follows_ingest_run_root",
        },
    }
    (source / "banks").mkdir(parents=True, exist_ok=True)
    (source / "banks" / "ingest-status.json").write_bytes(canonical_json_bytes(status))
    promote_attempt_evidence(source, exports)
    return session, str(summary["head_digest"]), str(event["response"]["body_sha256"])


def write_verified_observation(
    exports: Path,
    *,
    observation_date: str = "2026-09-02",
    observed_at: str | None = None,
    raw_attempt_journal_digest: str | None = None,
    product_evidence_id: str | None = None,
    accounting_id: str | None = None,
) -> dict:
    from tests.test_cdr_observation_db import observation as observation_inputs

    observed_at = observed_at or f"{observation_date}T05:01:02Z"
    exports.mkdir(parents=True, exist_ok=True)
    accounting_id = accounting_id or f"test-{observation_date}"
    accounting, projections = observation_inputs()
    if raw_attempt_journal_digest is None and product_evidence_id is None:
        accounting_id, raw_attempt_journal_digest, product_evidence_id = (
            _write_promoted_test_evidence(
                exports,
                observation_date,
                observed_at,
                provider_uid=accounting["providers"][0]["provider_uid"],
                provider_name=accounting["providers"][0]["brand_name"],
                product_id=accounting["products"][0]["cdr_product_id"],
            )
        )
    raw_attempt_journal_digest = raw_attempt_journal_digest or "0" * 64
    accounting["observation_date"] = observation_date
    accounting["accounting_id"] = accounting_id
    accounting["raw_attempt_journal_digest"] = raw_attempt_journal_digest
    if product_evidence_id is not None:
        accounting["products"][0]["evidence_ids"] = [product_evidence_id]
        for rows in projections.values():
            for row in rows:
                row["document"]["evidence_id"] = product_evidence_id
    observation = build_observation(
        accounting=accounting,
        projections=projections,
        observed_at=observed_at,
        normalization_version="test-v1",
    )
    build_observation_database(
        exports / "local-cdr.sqlite",
        accounting=accounting,
        projections=projections,
        generated_at=observed_at,
        normalization_version="test-v1",
    )
    write_observation(exports, observation, accounting)
    return observation


def write_finalized_observation(
    data_root: Path, *, observation_date: str = "2026-09-02"
) -> dict:
    """Build the normal producer artifacts and bind them to the finalized ledger."""

    from cdr_attempt_evidence_promotion import promote_attempt_evidence
    from cdr_finalization import finalize_observation
    from cdr_observation import load_verified_observation
    from cdr_outputs import build_outputs
    from tests.test_cdr_outputs import _captured_run

    run = _captured_run(data_root / "runs", run_date=observation_date)
    result = build_outputs(run)
    exports = run / "_exports"
    promote_attempt_evidence(run, exports)
    finalize_observation(
        exports,
        data_root / "state",
        data_root / "state" / f"{observation_date}.done.json",
        observation_date=observation_date,
        result=result,
    )
    observation, _ = load_verified_observation(exports)
    return observation
