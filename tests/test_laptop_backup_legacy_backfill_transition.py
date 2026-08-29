from __future__ import annotations

from pathlib import Path

import pytest

import laptop_backup_transition as transition
import laptop_backup_transition_contract as contract
import laptop_pull_backup as receiver
from test_laptop_backup_transition_contract import listing
from test_laptop_backup_transition_flow import config, execution_record


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
        transition.scheduled, "latest_status", lambda *_a, **_k: {"status": "UP_TO_DATE"}
    )
    monkeypatch.setattr(
        transition.scheduled, "component_status", lambda *_a, **_k: {"status": "UP_TO_DATE"}
    )
    monkeypatch.setattr(
        transition.scheduled, "inventory_status", lambda *_a, **_k: {"status": "UP_TO_DATE"}
    )
    receipts = {
        kind: str((value.target / kind / "receipt.json").resolve())
        for kind in contract.EXPECTED_KINDS
    }
    monkeypatch.setattr(contract, "validate_receipts", lambda *_a, **_k: receipts)
    return value, record


def validate_pretransition(
    value: transition.TransitionConfig, *, allow: bool = True
) -> dict[str, object]:
    return transition.validate_backup_state(
        value,
        listing(),
        candidate_sha=value.old_candidate_code_sha,
        require_scheduled=True,
        scheduled_candidates=(value.old_candidate_code_sha, value.candidate_code_sha),
        allow_legacy_backfill=allow,
    )


def test_pretransition_accepts_authenticated_old_candidate_backfill(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value, record = prepare_backfill(monkeypatch, tmp_path, candidate="old")

    state = validate_pretransition(value)

    assert state["scheduled_record"]["path"] == str(record)


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
    ("candidate", "allow", "result"),
    [
        ("old", False, "PASS"),
        ("old", True, "FAIL"),
        ("new", True, "PASS"),
        ("third", True, "PASS"),
    ],
)
def test_legacy_backfill_rejects_unauthorised_candidate_flag_or_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    candidate: str,
    allow: bool,
    result: str,
) -> None:
    value, _record = prepare_backfill(
        monkeypatch, tmp_path, candidate=candidate, result=result
    )

    with pytest.raises(ValueError):
        validate_pretransition(value, allow=allow)
