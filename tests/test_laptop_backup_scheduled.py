from __future__ import annotations

import json
import threading
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from argparse import Namespace
from typing import Callable
from zoneinfo import ZoneInfo

import pytest

import laptop_backup_scheduled as scheduled
import laptop_pull_backup as receiver


def test_record_execution_serializes_pointer_lineage_across_threads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "backup"
    args = Namespace(
        plan_git_commit=receiver.PLAN_GIT_COMMIT,
        candidate_code_sha="c" * 40,
        protected_code_sha="9" * 40,
        operator="pytest",
    )
    (target / "catalog").mkdir(parents=True)
    scheduled.record_execution(
        target, args, "PASS", "NO_BACKUP_DATA_WRITE", {"status": "UP_TO_DATE"}
    )
    runs = target / "catalog/scheduled-runs"
    baseline_pointer = json.loads(
        (target / "catalog/latest-scheduled.json").read_text(encoding="utf-8")
    )
    baseline = target / baseline_pointer["record_path"]
    original_create = receiver.atomic_create
    first_inside = threading.Event()
    release_first = threading.Event()
    second_created = threading.Event()
    count_lock = threading.Lock()
    create_count = 0

    def delayed_create(path: Path, payload: bytes) -> None:
        nonlocal create_count
        if path.parent == runs:
            with count_lock:
                create_count += 1
                current = create_count
            if current == 1:
                first_inside.set()
                assert release_first.wait(timeout=5)
            else:
                second_created.set()
        original_create(path, payload)

    monkeypatch.setattr(receiver, "atomic_create", delayed_create)
    errors: list[BaseException] = []

    def writer() -> None:
        try:
            scheduled.record_execution(
                target, args, "PASS", "NO_BACKUP_DATA_WRITE", {"status": "UP_TO_DATE"}
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    first = threading.Thread(target=writer)
    second = threading.Thread(target=writer)
    first.start()
    assert first_inside.wait(timeout=5)
    second.start()
    assert not second_created.wait(timeout=0.2)
    release_first.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not errors
    assert not first.is_alive() and not second.is_alive()
    records = [path for path in runs.glob("*.json") if path != baseline]
    assert len(records) == 2
    values = {
        path.relative_to(target).as_posix(): json.loads(path.read_text(encoding="utf-8"))
        for path in records
    }
    first_record = next(
        relative
        for relative, value in values.items()
        if value["previous_execution"] == {
            "record_path": baseline_pointer["record_path"],
            "record_sha256": baseline_pointer["record_sha256"],
        }
    )
    latest = json.loads(
        (target / "catalog/latest-scheduled.json").read_text(encoding="utf-8")
    )
    assert latest["record_path"] != first_record
    assert values[latest["record_path"]]["previous_execution"] == {
        "record_path": first_record,
        "record_sha256": receiver.sha256_file(target / first_record),
    }


def test_open_transition_gate_accepts_only_live_owner_descendant(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "target"
    root = target / "evidence/A3-LAPTOP-TASK-TRANSITION"
    (target / "catalog").mkdir(parents=True)
    root.mkdir(parents=True)
    transition_id = "controlled-transition"
    (root / "ACTIVE_TRANSITION.json").write_text(
        json.dumps({"state": "OPEN", "transition_id": transition_id}), encoding="utf-8"
    )
    (root / ".transition-runtime.lock").write_text(
        json.dumps({"pid": 12345, "transition_id": transition_id}), encoding="utf-8"
    )
    (target / "catalog/.receiver.lock").write_text(
        json.dumps({"kind": "A3_TRANSITION_GUARD", "transition_id": transition_id}),
        encoding="utf-8",
    )
    args = Namespace(target=target, transition_id=transition_id)
    monkeypatch.setattr(receiver, "process_descends_from", lambda child, owner: True)
    assert scheduled.open_transition_allows_invocation(args) == (True, None)
    monkeypatch.setattr(receiver, "process_descends_from", lambda child, owner: False)
    allowed, reason = scheduled.open_transition_allows_invocation(args)
    assert not allowed
    assert "authenticated A3 transition" in str(reason)
    assert not list((target / "catalog").glob("scheduled-runs/*.json"))


def test_transition_only_predecessor_authority_requires_active_guard(tmp_path: Path) -> None:
    target = tmp_path / "target"
    (target / "catalog").mkdir(parents=True)
    args = Namespace(
        target=target,
        transition_id="spoofed-transition",
        allowed_predecessor_candidate_sha=["d" * 40],
    )

    allowed, reason = scheduled.open_transition_allows_invocation(args)

    assert not allowed
    assert "requires an active A3 transition" in str(reason)


@pytest.mark.parametrize(
    "timer_value",
    ["Sun 2026-08-30 02:00:00 AEST", "Mon 2026-08-31 01:00:00 AEST"],
)
def test_scheduled_gate_rejects_wrong_next_timer_time_or_date(timer_value: str) -> None:
    with pytest.raises(ValueError, match="exact next 01:00"):
        scheduled.validate_next_daily_timer(
            timer_value, datetime.fromisoformat("2026-08-29T20:00:00+10:00")
        )


@pytest.mark.parametrize(
    ("checked_at", "timer_value"),
    [
        ("2027-01-05T00:29:00+11:00", "Tue 2027-01-05 01:00:00 AEDT"),
        ("2027-01-05T01:00:00+11:00", "Wed 2027-01-06 01:00:00 AEDT"),
        ("2026-08-29T00:29:00+10:00", "Sat 2026-08-29 01:00:00 AEST"),
    ],
)
def test_scheduled_gate_accepts_exact_hobart_timer(
    checked_at: str, timer_value: str
) -> None:
    scheduled.validate_next_daily_timer(timer_value, datetime.fromisoformat(checked_at))


@pytest.mark.parametrize(
    ("checked_at", "timer_value"),
    [
        ("2027-01-05T00:29:00+11:00", "Tue 2027-01-05 01:00:00 AEST"),
        ("2026-08-29T20:00:00+10:00", "Sun 2026-08-30 01:00:00 AEDT"),
    ],
)
def test_scheduled_gate_rejects_wrong_hobart_season_zone(
    checked_at: str, timer_value: str
) -> None:
    with pytest.raises(ValueError, match="exact next 01:00"):
        scheduled.validate_next_daily_timer(timer_value, datetime.fromisoformat(checked_at))


CANDIDATE = "c" * 40
PROTECTED = "9" * 40
HOBART = ZoneInfo("Australia/Hobart")


def source_listing() -> dict[str, object]:
    return {
        "ok": True,
        "preflight": {
            "checked_at": "2026-08-29T17:00:00+10:00",
            "production": {
                "clean": True,
                "commit": PROTECTED,
                "dirty_paths": [],
            },
            "daily_service": "inactive",
            "terminal_failure_authorization": None,
            "daily_timer": "enabled",
            "daily_timer_active": "active",
            "daily_timer_next": "Sun 2026-08-30 01:00:00 AEST",
            "ingest_lock_absent": True,
            "dashboard_healthy": True,
            "state_root": "/srv/ar-local/data/state",
        },
        "retained_runs": [
            {"date": "2026-08-28", "status": "completed"},
            {"date": "2026-08-29", "status": "completed"},
        ],
        "completed_dates": ["2026-08-28", "2026-08-29"],
        "component_identities": {
            "control": {"content_revision": "1" * 64, "source_bytes": 1},
            "macro": {"content_revision": "2" * 64, "source_bytes": 1},
            "diagnostics": {},
        },
        "latest_observation": {
            "observation_date": "2026-08-29",
            "completion_marker_sha256": "3" * 64,
            "pointer_sha256": "4" * 64,
        },
    }


InvalidMutation = Callable[[dict[str, object]], None]
INVALID_SOURCE_IDENTITIES: tuple[tuple[InvalidMutation, str], ...] = (
    (lambda value: value.update(ok=False), "did not report success"),
    (lambda value: value.update(preflight={}), "lacks a checked_at"),
    (
        lambda value: value.update(preflight={"checked_at": "2026-08-29T17:00:00"}),
        "not timezone-aware",
    ),
    (
        lambda value: value.update(preflight={"checked_at": "2026-08-29T17:00:00+00:00"}),
        "not Australia/Hobart",
    ),
    (
        lambda value: value.update(preflight={"checked_at": "2026-08-29T17:07:00+10:00"}),
        "checked_at is in the future",
    ),
    (
        lambda value: value["preflight"].update(checked_at="2026-08-29T16:55:00+10:00"),
        "checked_at is stale",
    ),
    (
        lambda value: value["preflight"].update(production={}),
        "production identity is invalid",
    ),
    (
        lambda value: value["preflight"]["production"].update(clean=False),
        "production identity is invalid",
    ),
    (
        lambda value: value["preflight"]["production"].update(commit="8" * 40),
        "production identity is invalid",
    ),
    (
        lambda value: value["preflight"].update(daily_service="active"),
        "daily service identity is invalid",
    ),
    (
        lambda value: value["preflight"].update(
            daily_service="failed", terminal_failure_authorization=None
        ),
        "lacks terminal-failure authorization",
    ),
    (
        lambda value: value["preflight"].update(
            daily_service="failed",
            terminal_failure_authorization={
                "run_date": "2026-08-29",
                "record_path": "/unrelated/2026-08-29/record.FAIL.json",
                "result": "FAIL",
            },
        ),
        "terminal-failure authorization is invalid",
    ),
    (
        lambda value: value["preflight"].update(
            daily_service="failed",
            terminal_failure_authorization={
                "run_date": "2026-08-29",
                "record_path": (
                    "/srv/ar-local/data/state/../state/ingest-executions/"
                    "2026-08-29/record.FAIL.json"
                ),
                "result": "FAIL",
            },
        ),
        "terminal-failure authorization is invalid",
    ),
    (
        lambda value: value["preflight"].update(daily_timer="disabled"),
        "daily timer identity is invalid",
    ),
    (
        lambda value: value["preflight"].update(daily_timer_active="inactive"),
        "active daily timer identity is invalid",
    ),
    (
        lambda value: value["preflight"].update(ingest_lock_absent=False),
        "ingest lock identity is invalid",
    ),
    (
        lambda value: value["preflight"].update(dashboard_healthy=False),
        "dashboard identity is invalid",
    ),
    (
        lambda value: value["component_identities"].update(control={}),
        "control component identity is invalid",
    ),
    (
        lambda value: value["component_identities"].update(macro={}),
        "macro component identity is invalid",
    ),
    (
        lambda value: value["component_identities"]["control"].update(source_bytes=0),
        "control component identity is invalid",
    ),
    (
        lambda value: value["component_identities"]["control"].update(
            content_revision=int("1" * 64)
        ),
        "control component identity is invalid",
    ),
    (
        lambda value: value.update(
            retained_runs=[{"date": "2026-08-29", "status": "diagnostic"}],
            completed_dates=[],
            latest_observation=None,
        ),
        "no completed observation",
    ),
    (
        lambda value: value.update(completed_dates=["2026-08-28"]),
        "completed-date identity is inconsistent",
    ),
    (
        lambda value: value["retained_runs"].insert(
            0, {"date": "2026-08-27", "status": "diagnostic"}
        ),
        "diagnostic identity is inconsistent",
    ),
    (
        lambda value: value["latest_observation"].update(pointer_sha256=None),
        "latest observation identity is incomplete",
    ),
    (
        lambda value: value["latest_observation"].update(
            completion_marker_sha256=int("3" * 64)
        ),
        "latest observation identity is incomplete",
    ),
    (
        lambda value: value["retained_runs"][0].update(date="2026-02-30"),
        "retained-run inventory is invalid",
    ),
    (
        lambda value: value["retained_runs"].append(
            {"date": "2026-08-29", "status": "diagnostic"}
        ),
        "retained-run inventory is invalid",
    ),
    (
        lambda value: value["retained_runs"].append(
            {"date": "2026-08-30", "status": "diagnostic"}
        ),
        "retained-run inventory is invalid",
    ),
    (
        lambda value: value["latest_observation"].update(
            observation_date="2026-08-30"
        ),
        "latest observation date is in the future",
    ),
    (
        lambda value: value["component_identities"]["diagnostics"].update(
            {"2026-08-27": {"content_revision": 5, "source_bytes": 1}}
        ),
        "diagnostic 2026-08-27 component identity is invalid",
    ),
    (
        lambda value: value["component_identities"]["diagnostics"].update(
            {"2026-08-30": {"content_revision": "5" * 64, "source_bytes": 1}}
        ),
        "diagnostic date is in the future",
    ),
)


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
    valid = source_listing()
    reference = datetime(2026, 8, 29, 17, 1, tzinfo=HOBART)

    identities, retained = scheduled.validate_source_listing(
        valid, protected_sha=PROTECTED, now=reference
    )
    assert identities is valid["component_identities"]
    assert retained is valid["retained_runs"]


def test_source_listing_accepts_verified_terminal_failure_identity() -> None:
    valid = source_listing()
    valid["preflight"].update(
        daily_service="failed",
        terminal_failure_authorization={
            "run_date": "2026-08-29",
            "record_path": (
                "/srv/ar-local/data/state/ingest-executions/2026-08-29/"
                "20260829T010000+1000.FAIL.json"
            ),
            "result": "FAIL",
        },
    )

    scheduled.validate_source_listing(
        valid,
        protected_sha=PROTECTED,
        now=datetime(2026, 8, 29, 17, 1, tzinfo=HOBART),
    )


def test_source_listing_rejects_stale_clock_at_quiet_window_boundary() -> None:
    invalid = source_listing()
    invalid["preflight"]["checked_at"] = "2026-08-29T23:29:00+10:00"

    with pytest.raises(ValueError, match="checked_at is stale"):
        scheduled.validate_source_listing(
            invalid,
            protected_sha=PROTECTED,
            now=datetime(2026, 8, 30, 0, 29, tzinfo=HOBART),
        )


@pytest.mark.parametrize(
    ("now_value", "checked_at"),
    (
        (
            datetime(2026, 8, 30, 0, 31, tzinfo=HOBART),
            "2026-08-30T00:27:00+10:00",
        ),
        (
            datetime(2026, 8, 30, 3, 29, tzinfo=HOBART),
            "2026-08-30T03:33:00+10:00",
        ),
    ),
)
def test_source_listing_uses_laptop_clock_for_quiet_window(
    now_value: datetime, checked_at: str
) -> None:
    invalid = source_listing()
    invalid["preflight"]["checked_at"] = checked_at

    with pytest.raises(ValueError, match="Hobart quiet window"):
        scheduled.validate_source_listing(
            invalid, protected_sha=PROTECTED, now=now_value
        )


@pytest.mark.parametrize(
    "record_path",
    (
        "/unrelated/2026-08-29/record.FAIL.json",
        "/srv/ar-local/data/state/../state/ingest-executions/2026-08-29/record.FAIL.json",
    ),
)
def test_source_listing_binds_terminal_failure_to_state_root(record_path: str) -> None:
    invalid = source_listing()
    invalid["preflight"].update(
        daily_service="failed",
        terminal_failure_authorization={
            "run_date": "2026-08-29",
            "record_path": record_path,
            "result": "FAIL",
        },
    )

    with pytest.raises(ValueError, match="terminal-failure authorization is invalid"):
        scheduled.validate_source_listing(
            invalid,
            protected_sha=PROTECTED,
            now=datetime(2026, 8, 29, 17, 1, tzinfo=HOBART),
        )


@pytest.mark.parametrize(
    ("mutation", "match"),
    INVALID_SOURCE_IDENTITIES,
)
def test_source_listing_rejects_incomplete_or_future_identity(
    mutation: InvalidMutation, match: str
) -> None:
    invalid = deepcopy(source_listing())
    mutation(invalid)

    with pytest.raises(ValueError, match=match):
        scheduled.validate_source_listing(
            invalid,
            protected_sha=PROTECTED,
            now=datetime(2026, 8, 29, 17, 1, tzinfo=HOBART),
        )


def test_source_listing_rejects_cross_midnight_future_date() -> None:
    invalid = source_listing()
    invalid["preflight"]["checked_at"] = "2026-08-30T00:02:00+10:00"
    invalid["retained_runs"][-1]["date"] = "2026-08-30"
    invalid["completed_dates"][-1] = "2026-08-30"
    invalid["latest_observation"]["observation_date"] = "2026-08-30"

    with pytest.raises(ValueError, match="future Hobart date"):
        scheduled.validate_source_listing(
            invalid,
            protected_sha=PROTECTED,
            now=datetime(2026, 8, 29, 23, 58, tzinfo=HOBART),
        )


@pytest.mark.parametrize(("mutation", "_match"), INVALID_SOURCE_IDENTITIES)
def test_main_blocks_invalid_source_identity_before_transfer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: InvalidMutation,
    _match: str,
) -> None:
    target = tmp_path / "backup"
    target.mkdir()
    recovery = tmp_path / "recovery.img"
    recovery.write_bytes(b"")
    listing = source_listing()
    listing["target"] = str(target)
    mutation(listing)
    calls: list[str] = []
    records: list[tuple[str, str]] = []

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            fixed = datetime(2026, 8, 29, 17, 1, tzinfo=HOBART)
            return fixed.astimezone(tz) if tz is not None else fixed.replace(tzinfo=None)

    def invoke(_args: object, command: str, _dates: tuple[str, ...] = ()) -> tuple[int, str, str]:
        calls.append(command)
        return 0, json.dumps(listing), ""

    monkeypatch.setattr(scheduled, "datetime", FixedDateTime)
    monkeypatch.setattr(scheduled, "invoke_receiver", invoke)
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

    assert code == 1
    assert calls == ["preflight"]
    assert records == [("BLOCKED", "PREFLIGHT_FAILED")]


@pytest.mark.parametrize(
    ("now_value", "checked_at"),
    (
        (
            datetime(2026, 8, 30, 0, 31, tzinfo=HOBART),
            "2026-08-30T00:27:00+10:00",
        ),
        (
            datetime(2026, 8, 30, 3, 29, tzinfo=HOBART),
            "2026-08-30T03:33:00+10:00",
        ),
    ),
)
def test_main_blocks_quiet_window_clock_skew_before_transfer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    now_value: datetime,
    checked_at: str,
) -> None:
    target = tmp_path / "backup"
    target.mkdir()
    recovery = tmp_path / "recovery.img"
    recovery.write_bytes(b"")
    listing = source_listing()
    listing["target"] = str(target)
    listing["preflight"]["checked_at"] = checked_at
    calls: list[str] = []
    records: list[tuple[str, str]] = []

    class BoundaryDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return (
                now_value.astimezone(tz)
                if tz is not None
                else now_value.replace(tzinfo=None)
            )

    def invoke(
        _args: object, command: str, _dates: tuple[str, ...] = ()
    ) -> tuple[int, str, str]:
        calls.append(command)
        return 0, json.dumps(listing), ""

    monkeypatch.setattr(scheduled, "datetime", BoundaryDateTime)
    monkeypatch.setattr(scheduled, "invoke_receiver", invoke)
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

    assert code == 1
    assert calls == ["preflight"]
    assert records == [("BLOCKED", "PREFLIGHT_FAILED")]


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

    def invoke(
        _args: object,
        command: str,
        include_dates: tuple[str, ...] = (),
        _include_diagnostics: tuple[str, ...] = (),
    ) -> tuple[int, str, str]:
        calls.append((command, tuple(include_dates)))
        return (0, listing if command == "preflight" else "{}", "")

    statuses = iter((initial, {"status": "UP_TO_DATE"}))
    records: list[tuple[str, str, object]] = []
    monkeypatch.setattr(scheduled, "invoke_receiver", invoke)
    monkeypatch.setattr(scheduled, "scheduled_status", lambda *_args: next(statuses))
    monkeypatch.setattr(scheduled, "prepare_execution_lineage", lambda *_args: None)
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


def test_main_rejects_missing_predecessor_before_backup_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "backup"
    runs = target / "catalog/scheduled-runs"
    runs.mkdir(parents=True)
    (runs / "unpointed.json").write_text('{"result":"PASS"}', encoding="utf-8")
    recovery = tmp_path / "recovery.img"
    recovery.write_bytes(b"")
    calls: list[str] = []

    def invoke(_args: object, command: str, *_extra: object) -> tuple[int, str, str]:
        calls.append(command)
        return 0, json.dumps({"target": str(target)}), ""

    monkeypatch.setattr(scheduled, "invoke_receiver", invoke)
    monkeypatch.setattr(scheduled, "scheduled_status", lambda *_args: {
        "status": "STALE", "backup_command": "backup-latest", "backfill_dates": [],
    })

    code = scheduled.main([
        "--target", str(target), "--recovery-image", str(recovery),
        "--candidate-code-sha", CANDIDATE, "--protected-code-sha", PROTECTED,
        "--plan-git-commit", receiver.PLAN_GIT_COMMIT,
    ])

    assert code == 1
    assert calls == ["preflight"]


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


def test_main_records_post_backup_metadata_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "backup"
    target.mkdir()
    recovery = tmp_path / "recovery.img"
    recovery.write_bytes(b"")
    listing = json.dumps({"target": str(target)})
    calls: list[str] = []

    def invoke(
        _args: object,
        command: str,
        _dates: tuple[str, ...] = (),
        _diagnostics: tuple[str, ...] = (),
    ) -> tuple[int, str, str]:
        calls.append(command)
        return (0, listing if command == "preflight" else "{}", "")

    status_calls = 0

    def status(*_args: object) -> dict[str, object]:
        nonlocal status_calls
        status_calls += 1
        if status_calls == 1:
            return {
                "status": "STALE",
                "backup_command": "backup-latest",
                "backfill_dates": [],
            }
        raise ValueError("invalid verification inventory")

    records: list[tuple[str, str, object]] = []
    monkeypatch.setattr(scheduled, "invoke_receiver", invoke)
    monkeypatch.setattr(scheduled, "scheduled_status", status)
    monkeypatch.setattr(scheduled, "prepare_execution_lineage", lambda *_args: None)
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
    ])

    assert code == 1
    assert calls == ["preflight", "backup-latest", "preflight"]
    assert records[0][0:2] == ("FAIL", "POST_BACKUP_VERIFY")
    assert records[0][2]["attempted_action"] == "BACKUP-LATEST"
