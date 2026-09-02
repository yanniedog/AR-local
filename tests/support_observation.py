from __future__ import annotations

import hashlib
from pathlib import Path

from cdr_contracts import canonical_json_bytes
from cdr_observation import build_observation, write_observation
from cdr_observation_db import build_observation_database
from cdr_raw_attempt_journal import RawAttemptJournal


def _write_promoted_test_evidence(
    exports: Path, observation_date: str, observed_at: str
) -> tuple[str, str, str]:
    session = f"test-{observation_date}"
    relative = Path("attempt-evidence/raw-attempt-journals-v1") / session
    journal = RawAttemptJournal(exports / relative.parent, session)
    event = journal.record(
        "product:test",
        request_url="https://bank.example/cds-au/v1/banking/products/test",
        status=200,
        outcome="success",
        body=b'{"product":"test"}',
        started_at=observed_at,
        completed_at=observed_at,
        context={"phase": "product_detail", "product_id": "test"},
    )
    summary = journal.summary(recover=False)
    manifest = journal.root / "promotion-manifest.json"
    manifest.write_bytes(
        canonical_json_bytes(
            {
                "schema_version": 1,
                "artifact_path": relative.as_posix(),
                "journal": summary,
            }
        )
    )
    pointer = {
        **summary,
        "path": relative.as_posix(),
        "path_resolution": "relative_to_finalized_export_root",
        "retention": "hash_bound_finalized_artifact",
        "promotion_manifest_path": (relative / manifest.name).as_posix(),
        "promotion_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
    }
    (exports / "ingest-status.json").write_bytes(
        canonical_json_bytes({"raw_attempt_journal": pointer})
    )
    return session, str(summary["head_digest"]), str(event["response"]["body_sha256"])


def write_verified_observation(
    exports: Path,
    *,
    observation_date: str = "2026-09-02",
    observed_at: str | None = None,
    raw_attempt_journal_digest: str | None = None,
    product_evidence_id: str | None = None,
) -> dict:
    from tests.test_cdr_observation_db import observation as observation_inputs

    observed_at = observed_at or f"{observation_date}T05:01:02Z"
    exports.mkdir(parents=True, exist_ok=True)
    accounting_id = f"test-{observation_date}"
    if raw_attempt_journal_digest is None and product_evidence_id is None:
        accounting_id, raw_attempt_journal_digest, product_evidence_id = (
            _write_promoted_test_evidence(exports, observation_date, observed_at)
        )
    raw_attempt_journal_digest = raw_attempt_journal_digest or "0" * 64
    accounting, projections = observation_inputs()
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
