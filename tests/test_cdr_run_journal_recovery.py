from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import cdr_run_journal
from cdr_run_journal import (
    InvalidJournalTransition,
    RunJournal,
    RunStage,
    StageState,
)


ROOT = Path(__file__).resolve().parents[1]


def schema(name):
    payload = json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(payload)
    return Draft202012Validator(payload)


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
    assert len(list(journal.events.glob("*.json"))) == 2
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


def test_run_journal_recovers_missing_current_before_a_different_stage(
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

    next_event = journal.transition(RunStage.HOLDERS, StageState.RUNNING)
    assert next_event["sequence"] == 2
    assert [
        json.loads(path.read_text(encoding="utf-8"))["sequence"]
        for path in sorted(journal.events.glob("*.json"))
    ] == [1, 2]
    current = journal.read()
    assert current["stages"][RunStage.REGISTER.value]["state"] == "running"
    assert current["stages"][RunStage.HOLDERS.value]["state"] == "running"


@pytest.mark.parametrize("corrupt_current", [b"{broken", b"[]", b"null"])
def test_run_journal_rebuilds_corrupt_current_from_immutable_events(
    tmp_path, corrupt_current
):
    journal = RunJournal(tmp_path / "journals", "generation-1")
    journal.transition(RunStage.REGISTER, StageState.RUNNING)
    journal.current_path.write_bytes(corrupt_current)

    event = journal.transition(RunStage.HOLDERS, StageState.RUNNING)

    assert event["sequence"] == 2
    assert journal.read()["sequence"] == 2
    assert len(list(journal.events.glob("*.json"))) == 2


def test_run_journal_rejects_current_ahead_of_immutable_events(tmp_path):
    journal = RunJournal(tmp_path / "journals", "generation-1")
    journal.transition(RunStage.REGISTER, StageState.RUNNING)
    journal.transition(RunStage.REGISTER, StageState.COMPLETE)
    missing_event = journal.events / "000002-register_discovery-complete.json"
    missing_event.unlink()
    current_bytes = journal.current_path.read_bytes()

    with pytest.raises(InvalidJournalTransition, match="ahead of immutable event"):
        journal.transition(RunStage.HOLDERS, StageState.RUNNING)

    assert journal.current_path.read_bytes() == current_bytes
    assert not (journal.events / "000002-holders-running.json").exists()


def test_run_journal_rejects_multiple_immutable_events_for_one_sequence(tmp_path):
    journal = RunJournal(tmp_path / "journals", "generation-1")
    first = journal.transition(RunStage.REGISTER, StageState.RUNNING)
    duplicate = dict(first)
    duplicate["stage"] = RunStage.HOLDERS.value
    (journal.events / "000001-holders-running.json").write_text(
        json.dumps(duplicate), encoding="utf-8"
    )
    journal.current_path.unlink()

    with pytest.raises(InvalidJournalTransition, match="multiple immutable events"):
        journal.transition(RunStage.EXPORT, StageState.RUNNING)
    assert len(list(journal.events.glob("*.json"))) == 2


@pytest.mark.parametrize(
    "sequence", [1.5, "1", True], ids=["float", "numeric-string", "boolean"]
)
def test_run_journal_rejects_non_integer_immutable_sequence(tmp_path, sequence):
    journal = RunJournal(tmp_path / "journals", "generation-1")
    event = journal.transition(RunStage.REGISTER, StageState.RUNNING)
    event["sequence"] = sequence
    event_path = journal.events / "000001-register_discovery-running.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    journal.current_path.unlink()

    with pytest.raises(InvalidJournalTransition, match="invalid journal event"):
        journal.transition(RunStage.HOLDERS, StageState.RUNNING)


def test_run_journal_concurrent_stage_changes_keep_contiguous_sequences(tmp_path):
    journal = RunJournal(tmp_path / "journals", "generation-1")

    def start(stage):
        return journal.transition(stage, StageState.RUNNING)

    with ThreadPoolExecutor(max_workers=2) as pool:
        events = list(pool.map(start, (RunStage.REGISTER, RunStage.HOLDERS)))

    assert sorted(event["sequence"] for event in events) == [1, 2]
    assert journal.read()["sequence"] == 2
    assert len(list(journal.events.glob("*.json"))) == 2
