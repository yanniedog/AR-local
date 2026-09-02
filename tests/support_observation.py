from __future__ import annotations

from pathlib import Path

from cdr_observation import build_observation, write_observation
from cdr_observation_db import build_observation_database


def write_verified_observation(
    exports: Path,
    *,
    observation_date: str = "2026-09-02",
    observed_at: str | None = None,
    raw_attempt_journal_digest: str = "0" * 64,
    product_evidence_id: str | None = None,
) -> dict:
    from tests.test_cdr_observation_db import observation as observation_inputs

    observed_at = observed_at or f"{observation_date}T05:01:02Z"
    accounting, projections = observation_inputs()
    accounting["observation_date"] = observation_date
    accounting["accounting_id"] = f"test-{observation_date}"
    accounting["raw_attempt_journal_digest"] = raw_attempt_journal_digest
    if product_evidence_id is not None:
        accounting["products"][0]["evidence_ids"] = [product_evidence_id]
    observation = build_observation(
        accounting=accounting,
        projections=projections,
        observed_at=observed_at,
        normalization_version="test-v1",
    )
    exports.mkdir(parents=True, exist_ok=True)
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
