from __future__ import annotations

import json
from pathlib import Path

import pytest

import laptop_backup_transition as transition
import laptop_backup_transition_contract as contract
import laptop_pull_backup as receiver
from tests.test_laptop_backup_transition_contract import listing
from tests.test_laptop_backup_transition_flow import config, execution_record


def prepare_backfill(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    candidate: str,
    result: str = "PASS",
    mutation: tuple[str, object] | None = None,
) -> tuple[transition.TransitionConfig, Path]:
    value = config(tmp_path)
    candidates = {
        "old": value.old_candidate_code_sha,
        "new": value.candidate_code_sha,
        "third": "e" * 40,
    }
    record = value.target / "catalog/scheduled-runs/legacy-backfill.json"
    payload = execution_record("BACKFILL")
    payload["candidate_code_sha"] = candidates[candidate]
    payload["result"] = result
    payload.update({
        "plan_version": "1.4",
        "plan_git_commit": "14dd066099bba393cccf61a280243e43162eedc9",
        "plan_sha256": "78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713",
        "plan_raw_sha256": "a5a679297167c37845fbacf0cdf895cad4fb2900c09c1e94e310319d3ae9118d",
        "plan_normalized_raw_sha256": "c8dcc4f1546f9e1f276f5b73f46b07e75ee51c98d5163245137002bbe589afe4",
    })
    if mutation is not None:
        field, replacement = mutation
        if replacement is None:
            payload.pop(field)
        else:
            payload[field] = replacement
    record.write_bytes(contract.canonical_json(payload))
    receiver.atomic_replace(
        value.target / "catalog/latest-scheduled.json",
        contract.canonical_json({
            "record_path": record.relative_to(value.target).as_posix(),
            "record_sha256": contract.sha256_file(record),
            "result": result,
        }),
    )
    monkeypatch.setattr(
        transition.scheduled,
        "latest_status",
        lambda *_a, **_k: {
            "status": "UP_TO_DATE",
            "observation_date": "2026-08-29",
        },
    )
    monkeypatch.setattr(
        transition.scheduled, "component_status", lambda *_a, **_k: {"status": "UP_TO_DATE"}
    )
    monkeypatch.setattr(
        transition.scheduled,
        "inventory_status",
        lambda *_a, **_k: {
            "status": "UP_TO_DATE",
            "missing_completed_dates": [],
            "stale_diagnostics": [],
        },
    )
    receipts = {
        kind: str((value.target / kind / "receipt.json").resolve())
        for kind in contract.EXPECTED_KINDS
    }
    monkeypatch.setattr(
        transition.scheduled,
        "pointer_generation",
        lambda _target, _pointer, kind, **_kwargs: (
            {"checks": {}},
            {},
            {},
            Path(receipts[kind]),
        ),
    )
    monkeypatch.setattr(
        transition.scheduled, "has_component_restore_evidence", lambda *_a: True
    )
    return value, record


def validate_pretransition(value: transition.TransitionConfig) -> dict[str, object]:
    return transition.validate_pretransition_backup_state(value, listing())


def test_pretransition_accepts_authenticated_old_candidate_backfill(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value, record = prepare_backfill(monkeypatch, tmp_path, candidate="old")

    state = validate_pretransition(value)

    assert state["scheduled_record"]["path"] == str(record)


def test_pretransition_selects_exact_historical_backfill(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value, _record = prepare_backfill(monkeypatch, tmp_path, candidate="old")
    source = listing()
    source["retained_runs"] = [
        {"date": "2026-08-28", "status": "completed"},
        {"date": "2026-08-29", "status": "completed"},
    ]
    source["completed_dates"] = ["2026-08-28", "2026-08-29"]
    monkeypatch.setattr(
        transition.scheduled,
        "latest_status",
        lambda *_a, **_k: {"status": "STALE", "observation_date": "2026-08-29"},
    )
    monkeypatch.setattr(
        transition.scheduled,
        "inventory_status",
        lambda *_a, **_k: {
            "status": "STALE",
            "missing_completed_dates": ["2026-08-28", "2026-08-29"],
            "stale_diagnostics": [],
        },
    )

    state = transition.validate_pretransition_backup_state(value, source)

    assert state["required_action"] == "BACKFILL"
    assert state["backfill_dates"] == ["2026-08-28"]
    assert state["expected_jobs"] == [
        ("observation", "2026-08-29"),
        ("control", None),
        ("macro", None),
        ("observation", "2026-08-28"),
    ]


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("schema_version", None),
        ("plan_raw_sha256", None),
        ("plan_normalized_raw_sha256", None),
        ("timestamps", {}),
        ("exact_commands", []),
        ("previous_execution", {"record_path": "../escape", "record_sha256": "f" * 64}),
    ],
)
def test_legacy_backfill_rejects_incomplete_immutable_envelope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    value, _record = prepare_backfill(
        monkeypatch,
        tmp_path,
        candidate="old",
        mutation=(field, replacement),
    )

    with pytest.raises(ValueError, match="preserved scheduled record"):
        validate_pretransition(value)


@pytest.mark.parametrize(
    ("candidate", "result"),
    [
        ("old", "FAIL"),
        ("new", "PASS"),
        ("third", "PASS"),
    ],
)
def test_legacy_backfill_rejects_unauthorised_candidate_flag_or_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    candidate: str,
    result: str,
) -> None:
    value, _record = prepare_backfill(
        monkeypatch, tmp_path, candidate=candidate, result=result
    )

    with pytest.raises(ValueError):
        validate_pretransition(value)


def test_legacy_plan_is_rejected_outside_pretransition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value, record_path = prepare_backfill(monkeypatch, tmp_path, candidate="old")
    record = json.loads(record_path.read_text(encoding="utf-8"))

    with pytest.raises(ValueError, match="plan identity"):
        contract.validate_execution_record(
            record,
            action="BACKFILL",
            candidate_sha=value.old_candidate_code_sha,
            protected_sha=value.protected_code_sha,
            plan_commit=str(record["plan_git_commit"]),
            plan_sha256=str(record["plan_sha256"]),
            operator=value.operator,
            expected_date=value.expected_observation_date,
        )
