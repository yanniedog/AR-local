from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from cdr_atomic import ImmutablePathError, atomic_write_json
import cdr_atomic
import cdr_run_journal
from cdr_export_contract import build_contract, load_contract, validate_contract, write_contract
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


def test_atomic_idempotent_replay_syncs_parent_directory(tmp_path, monkeypatch):
    path = tmp_path / "immutable.json"
    atomic_write_json(path, {"value": 1}, create_once=True)
    synced = []
    monkeypatch.setattr(cdr_atomic, "_fsync_directory", lambda parent: synced.append(parent))
    assert not atomic_write_json(path, {"value": 1}, create_once=True)
    assert synced == [path.parent.resolve()]


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


def test_contract_runtime_validator_matches_required_schema(tmp_path):
    export = tmp_path / "runs" / DATE / "_exports"
    make_export(export)
    state = tmp_path / "state"
    completion = finalize_observation(
        export,
        state,
        state / f"{DATE}.done.json",
        observation_date=DATE,
        result={"run_date": DATE, "banks_counts": {"rates": 7}},
    )
    contract = load_contract(state / completion["export_contract_path"])

    missing_counter = deepcopy(contract)
    del missing_counter["coverage"]["products_discovered"]
    with pytest.raises(ValueError, match="schema violation"):
        validate_contract(missing_counter)

    invalid_register_hash = deepcopy(contract)
    invalid_register_hash["register_hashes"] = [{"sha256": "not-a-digest"}]
    with pytest.raises(ValueError, match="schema violation"):
        validate_contract(invalid_register_hash)

    invalid_timestamp = deepcopy(contract)
    invalid_timestamp["observed_at"] = "not-a-timestamp"
    with pytest.raises(ValueError, match="observed_at"):
        validate_contract(invalid_timestamp)


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
    completion = finalize_observation(
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
    assert verify_completion_marker(completion, state, DATE) is False


def test_ledger_verifier_reports_corrupt_head_instead_of_raising(tmp_path):
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
    (state / "ledger-v2" / "head.json").write_text("{truncated", encoding="utf-8")
    report = verify_ledger(state)
    assert report["ok"] is False
    assert any(item["issue"] == "INVALID_HEAD" for item in report["findings"])


def test_orphan_candidate_rebases_safely_after_another_event_advances_head(tmp_path):
    first_export = tmp_path / "runs" / DATE / "first"
    second_export = tmp_path / "runs" / DATE / "second"
    make_export(first_export)
    make_export(second_export)
    (second_export / "banks.json").write_text('{"rates":["second"]}', encoding="utf-8")
    state = tmp_path / "state"
    coverage = {
        "products_discovered": 4,
        "eligible_rate_rows": 7,
        "providers_registered": 1,
        "providers_attempted": 1,
        "providers_complete": 1,
        "providers_partial": 0,
        "providers_failed": 0,
        "failure_records": 0,
        "corrupt_failure_records": 0,
        "unattributed_failure_records": 0,
        "failure_provenance_complete": True,
        "reconciliation_status": "reconciled",
        "unavailable_populations": [],
    }
    orphan = build_contract(
        first_export,
        observation_date=DATE,
        observed_at="2026-08-14T00:00:00Z",
        observation_state="complete",
        source_path=f"runs/{DATE}/first",
        coverage=coverage,
        provider_states=[{"provider_uid": "provider-a", "state": "complete"}],
        prior_ledger_head=None,
    )
    orphan_path = write_contract(state, orphan)

    finalize_observation(
        second_export,
        state,
        state / "second.done.json",
        observation_date=DATE,
        result={"run_date": DATE, "banks_counts": {"rates": 7}},
    )
    recovered = finalize_observation(
        first_export,
        state,
        state / "first.done.json",
        observation_date=DATE,
        result={"run_date": DATE, "banks_counts": {"rates": 7}},
    )

    assert (state / recovered["export_contract_path"]) != orphan_path
    assert orphan_path.is_file()
    assert verify_ledger(state)["ok"] is True


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


def test_external_completion_marker_is_rejected_before_ledger_write(tmp_path):
    export = tmp_path / "runs" / DATE / "_exports"
    make_export(export)
    state = tmp_path / "state"
    with pytest.raises(ValueError, match="inside the state root"):
        finalize_observation(
            export,
            state,
            tmp_path / "outside.done.json",
            observation_date=DATE,
            result={"run_date": DATE, "banks_counts": {"rates": 7}},
        )
    assert not (state / "ledger-v2").exists()


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


def test_run_journal_recovers_event_written_before_current_pointer(
    tmp_path, monkeypatch
):
    journal = RunJournal(tmp_path / "journals", "generation-1")
    real_write = cdr_run_journal.atomic_write_json

    def crash_before_current(path, value, **kwargs):
        if path == journal.current_path:
            raise RuntimeError("simulated power loss")
        return real_write(path, value, **kwargs)

    monkeypatch.setattr(cdr_run_journal, "atomic_write_json", crash_before_current)
    with pytest.raises(RuntimeError, match="power loss"):
        journal.transition(RunStage.REGISTER, StageState.RUNNING)
    monkeypatch.setattr(cdr_run_journal, "atomic_write_json", real_write)

    recovered = journal.transition(RunStage.REGISTER, StageState.RUNNING)
    assert recovered["sequence"] == 1
    assert journal.read()["stages"][RunStage.REGISTER.value]["state"] == "running"
    assert len(list(journal.events.glob("*.json"))) == 1
