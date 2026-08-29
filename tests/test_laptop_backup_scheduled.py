from __future__ import annotations

import json
from pathlib import Path

import pytest

import laptop_backup_scheduled as scheduled
import laptop_pull_backup as receiver


CANDIDATE = "c" * 40
PROTECTED = "9" * 40


@pytest.mark.parametrize(
    ("latest", "missing", "expected_command", "expected_dates"),
    (
        ("2026-08-29", ["2026-08-29"], "backup-latest", ()),
        ("2026-08-29", ["2026-08-28"], "backfill", ("2026-08-28",)),
        (
            "2026-08-29",
            ["2026-08-28", "2026-08-29"],
            "backfill",
            ("2026-08-28",),
        ),
        ("2026-08-29", [], "backup-latest", ()),
    ),
)
def test_request_distinguishes_latest_from_historical_gaps(
    latest: str, missing: list[str], expected_command: str, expected_dates: tuple[str, ...]
) -> None:
    command, dates = scheduled.select_backup_request(
        {"status": "STALE", "observation_date": latest},
        {"status": "STALE", "missing_completed_dates": missing},
    )

    assert command == expected_command
    assert dates == expected_dates


def test_request_uses_latest_backup_for_non_observation_staleness() -> None:
    command, dates = scheduled.select_backup_request(
        {"status": "UP_TO_DATE", "observation_date": "2026-08-29"},
        {"status": "UP_TO_DATE", "missing_completed_dates": []},
    )

    assert command == "backup-latest"
    assert dates == ()


@pytest.mark.parametrize(
    "inventory",
    (
        {},
        {"missing_completed_dates": None},
        {"missing_completed_dates": ["not-a-date"]},
        {"missing_completed_dates": ["2026-08-29", "2026-08-28"]},
        {"missing_completed_dates": ["2026-08-29", "2026-08-29"]},
    ),
)
def test_request_blocks_invalid_inventory(inventory: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="backup inventory"):
        scheduled.select_backup_request(
            {"status": "STALE", "observation_date": "2026-08-29"}, inventory
        )


def test_request_blocks_missing_dates_without_consistent_latest() -> None:
    for latest, match in (
        (None, "without a latest observation"),
        ("2026-08-28", "after the latest observation"),
    ):
        with pytest.raises(ValueError, match=match):
            scheduled.select_backup_request(
                {"status": "STALE", "observation_date": latest},
                {"status": "STALE", "missing_completed_dates": ["2026-08-29"]},
            )


@pytest.mark.parametrize("latest", ("not-a-date", 20260829))
def test_request_blocks_invalid_latest_identity(latest: object) -> None:
    with pytest.raises(ValueError, match="invalid latest date"):
        scheduled.select_backup_request(
            {"status": "STALE", "observation_date": latest},
            {"status": "STALE", "missing_completed_dates": ["2026-08-29"]},
        )


def test_source_listing_requires_complete_consistent_identity() -> None:
    valid = {
        "ok": True,
        "retained_runs": [
            {"date": "2026-08-28", "status": "completed"},
            {"date": "2026-08-29", "status": "completed"},
        ],
        "component_identities": {"control": {}, "macro": {}, "diagnostics": {}},
        "latest_observation": {"observation_date": "2026-08-29"},
    }

    identities, retained = scheduled.validate_source_listing(valid)
    assert identities is valid["component_identities"]
    assert retained is valid["retained_runs"]
    for invalid in (
        {**valid, "component_identities": None},
        {**valid, "component_identities": {"control": {}, "macro": {}}},
        {**valid, "latest_observation": None},
        {**valid, "latest_observation": {"observation_date": "2026-08-28"}},
        {**valid, "latest_observation": {"observation_date": "2026-08-30"}},
    ):
        with pytest.raises(ValueError):
            scheduled.validate_source_listing(invalid)


@pytest.mark.parametrize(
    ("initial", "expected_command", "expected_dates", "expected_action"),
    (
        (
            {
                "status": "STALE",
                "backup_command": "backup-latest",
                "backfill_dates": [],
            },
            "backup-latest",
            (),
            "BACKUP-LATEST",
        ),
        (
            {
                "status": "STALE",
                "backup_command": "backfill",
                "backfill_dates": ["2026-08-28"],
            },
            "backfill",
            ("2026-08-28",),
            "BACKFILL",
        ),
    ),
)
def test_main_invokes_and_records_selected_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    initial: dict[str, object],
    expected_command: str,
    expected_dates: tuple[str, ...],
    expected_action: str,
) -> None:
    target = tmp_path / "backup"
    target.mkdir()
    recovery = tmp_path / "recovery.img"
    recovery.write_bytes(b"")
    listing = json.dumps({"target": str(target)})
    calls: list[tuple[str, tuple[str, ...]]] = []

    def invoke(_args: object, command: str, include_dates: tuple[str, ...] = ()) -> tuple[int, str, str]:
        calls.append((command, tuple(include_dates)))
        return (0, listing if command == "preflight" else "{}", "")

    statuses = iter((initial, {"status": "UP_TO_DATE"}))
    records: list[tuple[str, str, object]] = []
    monkeypatch.setattr(scheduled, "invoke_receiver", invoke)
    monkeypatch.setattr(scheduled, "scheduled_status", lambda *_args: next(statuses))
    monkeypatch.setattr(
        scheduled,
        "record_execution",
        lambda _target, _args, result, action, detail: (
            records.append((result, action, detail)) or target / "record.json"
        ),
    )

    code = scheduled.main([
        "--target", str(target),
        "--recovery-image", str(recovery),
        "--candidate-code-sha", CANDIDATE,
        "--protected-code-sha", PROTECTED,
        "--plan-git-commit", receiver.PLAN_GIT_COMMIT,
        "--operator", "pytest",
    ])

    assert code == 0
    assert calls == [("preflight", ()), (expected_command, expected_dates), ("preflight", ())]
    assert records[0][:2] == ("PASS", expected_action)
    assert f'"action": "{expected_action}"' in capsys.readouterr().out


def test_main_current_state_records_no_write_without_backup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "backup"
    target.mkdir()
    recovery = tmp_path / "recovery.img"
    recovery.write_bytes(b"")
    calls: list[str] = []
    records: list[tuple[str, str]] = []
    monkeypatch.setattr(
        scheduled,
        "invoke_receiver",
        lambda _args, command, _dates=(): (
            calls.append(command) or 0,
            json.dumps({"target": str(target)}),
            "",
        ),
    )
    monkeypatch.setattr(
        scheduled, "scheduled_status", lambda *_args: {"status": "UP_TO_DATE"}
    )
    monkeypatch.setattr(
        scheduled,
        "record_execution",
        lambda _target, _args, result, action, _detail: (
            records.append((result, action)) or target / "record.json"
        ),
    )

    code = scheduled.main([
        "--target", str(target),
        "--recovery-image", str(recovery),
        "--candidate-code-sha", CANDIDATE,
        "--protected-code-sha", PROTECTED,
        "--plan-git-commit", receiver.PLAN_GIT_COMMIT,
    ])

    assert code == 0
    assert calls == ["preflight"]
    assert records == [("PASS", "NO_BACKUP_DATA_WRITE")]
