from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from cdr_atomic import ImmutablePathError, atomic_write_json
from cdr_export_contract import load_contract
from cdr_finalization import finalize_observation, verify_completion_marker
from cdr_ledger_v2 import verify_ledger
from cdr_run_journal import (
    InvalidJournalTransition,
    RunJournal,
    RunStage,
    StageState,
)


DATE = "2026-08-14"
ROOT = Path(__file__).resolve().parents[1]


def schema(name):
    payload = json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(payload)
    return Draft202012Validator(payload)


def make_export(root, *, failures=0, provenance_complete=True):
    cache = root / "dashboard-cache"
    cache.mkdir(parents=True)
    (cache / "latest.json").write_text(
        json.dumps(
            {
                "run_date": DATE,
                "banks_counts": {
                    "products": 4,
                    "rates": 7,
                    "fees": 3,
                    "features": 2,
                    "eligibility": 1,
                    "constraints": 1,
                    "failures": failures,
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "banks.json").write_text('{"rates":[]}', encoding="utf-8")
    (root / "ingest-status.json").write_text(
        json.dumps(
            {
                "total": failures,
                "corrupt_records": 0,
                "failure_provenance_complete": provenance_complete,
                "incomplete": failures > 0,
                "by_phase": {},
                "by_status": {},
                "by_provider": {"provider-a": failures} if failures else {},
                "providers_registered": 1,
                "providers_attempted": 1,
                "provider_states": [
                    {
                        "provider_uid": "provider-a",
                        "state": "partial" if failures else "complete",
                        "failure_records": failures,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_atomic_create_once_is_idempotent_but_never_overwrites(tmp_path):
    path = tmp_path / "immutable.json"
    assert atomic_write_json(path, {"value": 1}, create_once=True)
    assert not atomic_write_json(path, {"value": 1}, create_once=True)
    with pytest.raises(ImmutablePathError):
        atomic_write_json(path, {"value": 2}, create_once=True)
    assert json.loads(path.read_text()) == {"value": 1}


def test_finalization_binds_contract_event_marker_and_pointers(tmp_path):
    export = tmp_path / "runs" / DATE / "_exports"
    make_export(export)
    state = tmp_path / "state"
    marker = state / f"{DATE}.done.json"
    result = {"run_date": DATE, "banks_counts": {"rates": 7}}

    completion = finalize_observation(
        export,
        state,
        marker,
        observation_date=DATE,
        result=result,
    )

    assert completion["observation_state"] == "complete"
    assert completion["ledger_state"] == "finalized"
    assert verify_completion_marker(completion, state, DATE)
    contract = load_contract(state / completion["export_contract_path"])
    schema("export-contract-v2.schema.json").validate(contract)
    assert contract["coverage"]["eligible_rate_rows"] == 7
    assert contract["coverage"]["failure_provenance_complete"] is True
    assert (state / "ledger-v2" / "head.json").is_file()
    assert (state / "observation-pointers-v2" / "latest-observation.json").is_file()
    assert (state / "observation-pointers-v2" / "latest-complete.json").is_file()
    event_path = next((state / "ledger-v2" / "events" / DATE).glob("*.json"))
    schema("ledger-event-v2.schema.json").validate(json.loads(event_path.read_text()))
    assert verify_ledger(state)["ok"] is True


def test_finalization_retry_reuses_generation_after_ledger_head_advances(tmp_path):
    export = tmp_path / "runs" / DATE / "_exports"
    make_export(export)
    state = tmp_path / "state"
    marker = state / f"{DATE}.done.json"
    result = {"run_date": DATE, "banks_counts": {"rates": 7}}

    first = finalize_observation(
        export,
        state,
        marker,
        observation_date=DATE,
        result=result,
    )
    second = finalize_observation(
        export,
        state,
        marker,
        observation_date=DATE,
        result=result,
    )

    assert second == first
    assert len(list((state / "export-contracts-v2" / DATE).glob("*.json"))) == 1
    assert len(list((state / "ledger-v2" / "events" / DATE).glob("*.json"))) == 1
    assert verify_ledger(state)["ok"] is True


def test_ledger_verifier_detects_changed_source_bytes(tmp_path):
    export = tmp_path / "runs" / DATE / "_exports"
    make_export(export)
    state = tmp_path / "state"
    finalize_observation(
        export,
        state,
        state / f"{DATE}.done.json",
        observation_date=DATE,
        result={"run_date": DATE, "banks_counts": {"rates": 7}},
    )
    (export / "banks.json").write_text('{"rates":["changed"]}', encoding="utf-8")
    report = verify_ledger(state)
    assert report["ok"] is False
    assert any(item["issue"] == "ARTIFACT_MISMATCH" for item in report["findings"])


def test_partial_observation_advances_observation_but_not_complete_pointer(tmp_path):
    export = tmp_path / "runs" / DATE / "_exports"
    make_export(export, failures=2)
    state = tmp_path / "state"
    completion = finalize_observation(
        export,
        state,
        state / f"{DATE}.done.json",
        observation_date=DATE,
        result={"run_date": DATE, "banks_counts": {"rates": 7}},
    )
    assert completion["observation_state"] == "partial"
    assert (state / "observation-pointers-v2" / "latest-observation.json").is_file()
    assert not (state / "observation-pointers-v2" / "latest-complete.json").exists()


def test_missing_failure_provenance_can_never_finalize_complete(tmp_path):
    export = tmp_path / "runs" / DATE / "_exports"
    make_export(export, provenance_complete=False)
    state = tmp_path / "state"
    completion = finalize_observation(
        export,
        state,
        state / f"{DATE}.done.json",
        observation_date=DATE,
        result={"run_date": DATE, "banks_counts": {"rates": 7}},
    )
    assert completion["observation_state"] == "partial"


def test_run_journal_is_append_only_and_rejects_terminal_rewrite(tmp_path):
    journal = RunJournal(tmp_path / "journals", "generation-1")
    started = journal.transition(RunStage.REGISTER, StageState.RUNNING)
    finished = journal.transition(
        RunStage.REGISTER,
        StageState.COMPLETE,
        remote_digest="a" * 64,
    )
    assert started["sequence"] == 1
    assert finished["sequence"] == 2
    assert len(list((journal.events).glob("*.json"))) == 2
    schema("run-journal-v1.schema.json").validate(journal.read())
    with pytest.raises(InvalidJournalTransition):
        journal.transition(RunStage.REGISTER, StageState.RUNNING)
