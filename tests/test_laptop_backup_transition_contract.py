from __future__ import annotations

import base64
import argparse
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import laptop_backup_transition as transition
import laptop_backup_transition_authority as authority
import laptop_backup_transition_contract as contract
import laptop_pull_backup as receiver


CANDIDATE = "c" * 40
OLD_CANDIDATE = "d" * 40
PROTECTED = "9" * 40
PLAN = receiver.PLAN_GIT_COMMIT
PLAN_SHA = receiver.PLAN_SHA256
HOBART_NOW = datetime.fromisoformat("2026-08-29T19:00:00+10:00")


def listing() -> dict[str, object]:
    return {
        "ok": True,
        "preflight": {
            "checked_at": "2026-08-29T19:00:00+10:00",
            "production": {"clean": True, "commit": PROTECTED, "dirty_paths": []},
            "daily_service": "inactive",
            "terminal_failure_authorization": None,
            "daily_timer": "enabled",
            "daily_timer_active": "active",
            "daily_timer_next": "Sun 2026-08-30 01:00:00 AEST",
            "ingest_lock_absent": True,
            "dashboard_healthy": True,
            "state_root": "/srv/ar-local/data/state",
        },
        "retained_runs": [{"date": "2026-08-29", "status": "completed"}],
        "completed_dates": ["2026-08-29"],
        "latest_observation": {
            "observation_date": "2026-08-29",
            "completion_marker_sha256": "3" * 64,
            "pointer_sha256": "4" * 64,
        },
        "component_identities": {
            "control": {"content_revision": "1" * 64, "source_bytes": 1},
            "macro": {"content_revision": "2" * 64, "source_bytes": 1},
            "diagnostics": {},
        },
    }


def task_snapshot(expectation: contract.TaskExpectation, *, last: int = 0) -> dict[str, object]:
    return {
        "state": "Ready" if expectation.enabled else "Disabled",
        "enabled": expectation.enabled,
        "last_task_result": last,
        "actions": [{
            "execute": expectation.executable,
            "arguments": expectation.arguments,
            "working_directory": expectation.working_directory,
        }],
        "triggers": [
            {"kind": "daily", "at": "05:00:00", "delay": ""},
            {"kind": "boot", "at": "", "delay": "PT5M"},
        ],
        "principal": {
            "user_id": expectation.principal,
            "logon_type": "S4U",
            "run_level": "Limited",
        },
        "settings": {
            "enabled": expectation.enabled,
            "multiple_instances": "IgnoreNew",
            "restart_count": 3,
            "restart_interval": "PT30M",
            "execution_time_limit": "PT6H",
            "start_when_available": True,
        },
        "receiver_sha": expectation.receiver_sha,
        "xml_base64": base64.b64encode(b"<Task />").decode(),
    }


def test_source_requires_exact_next_timer_and_observation() -> None:
    contract.validate_source_listing(
        listing(),
        protected_sha=PROTECTED,
        expected_observation_date="2026-08-29",
        now=HOBART_NOW,
    )
    wrong = listing()
    wrong["preflight"]["daily_timer_next"] = "Sun 2026-08-30 02:00:00 AEST"
    with pytest.raises(ValueError, match="exact next 01:00"):
        contract.validate_source_listing(
            wrong,
            protected_sha=PROTECTED,
            expected_observation_date="2026-08-29",
            now=HOBART_NOW,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda value: value.update(state="Running"), "state"),
        (lambda value: value.update(last_task_result=1), "last result"),
        (lambda value: value["actions"][0].update(arguments="wrong"), "action"),
        (lambda value: value["triggers"][0].update(at="06:00:00"), "triggers"),
        (lambda value: value["principal"].update(user_id="other\\user"), "principal"),
        (lambda value: value["settings"].update(restart_count=2), "settings"),
        (lambda value: value.update(receiver_sha="e" * 40), "receiver SHA"),
    ),
)
def test_task_snapshot_fails_closed(mutation: object, message: str) -> None:
    expectation = contract.TaskExpectation("powershell.exe", "args", "repo", r"yanniedog\jkoka", OLD_CANDIDATE, True)
    value = task_snapshot(expectation)
    mutation(value)
    with pytest.raises(ValueError, match=message):
        contract.validate_task_snapshot(value, expectation, last_result_zero=True)


def valid_execution(action: str) -> dict[str, object]:
    detail = {
        "status": "UP_TO_DATE",
        "backfill_required": False,
        "observation": {"status": "UP_TO_DATE", "observation_date": "2026-08-29"},
        "control": {"status": "UP_TO_DATE"},
        "macro": {"status": "UP_TO_DATE"},
        "inventory": {"status": "UP_TO_DATE", "missing_completed_dates": [], "stale_diagnostics": []},
    }
    if action == "BACKUP-LATEST":
        detail = {
            "before": {"status": "STALE", "backup_command": "backup-latest", "backfill_required": False},
            "after": detail,
        }
    return {
        "plan_document_id": receiver.PLAN_DOCUMENT_ID,
        "plan_version": receiver.PLAN_VERSION,
        "plan_git_commit": PLAN,
        "plan_sha256": PLAN_SHA,
        "candidate_code_sha": CANDIDATE,
        "protected_code_sha": PROTECTED,
        "operator": "jkoka",
        "action": action,
        "result": "PASS",
        "detail": detail,
        "deviations": [],
        "deviation_authorization": None,
    }


def test_execution_validation_is_one_structural_record() -> None:
    value = valid_execution("BACKUP-LATEST")
    contract.validate_execution_record(
        value,
        action="BACKUP-LATEST",
        candidate_sha=CANDIDATE,
        protected_sha=PROTECTED,
        plan_commit=PLAN,
        plan_sha256=PLAN_SHA,
        operator="jkoka",
        expected_date="2026-08-29",
    )
    value["detail"]["before"]["backup_command"] = "backfill"
    with pytest.raises(ValueError, match="before state"):
        contract.validate_execution_record(
            value,
            action="BACKUP-LATEST",
            candidate_sha=CANDIDATE,
            protected_sha=PROTECTED,
            plan_commit=PLAN,
            plan_sha256=PLAN_SHA,
            operator="jkoka",
            expected_date="2026-08-29",
        )


@pytest.mark.parametrize(
    ("key", "bad"),
    (
        ("candidate_code_sha", "e" * 40),
        ("protected_code_sha", "e" * 40),
        ("plan_git_commit", "e" * 40),
        ("plan_sha256", "e" * 64),
        ("operator", "other"),
        ("result", "FAIL"),
    ),
)
def test_execution_record_rejects_identity_drift(key: str, bad: str) -> None:
    value = valid_execution("NO_BACKUP_DATA_WRITE")
    value[key] = bad
    with pytest.raises(ValueError):
        contract.validate_execution_record(
            value,
            action="NO_BACKUP_DATA_WRITE",
            candidate_sha=CANDIDATE,
            protected_sha=PROTECTED,
            plan_commit=PLAN,
            plan_sha256=PLAN_SHA,
            operator="jkoka",
            expected_date="2026-08-29",
        )


def test_execution_record_rejects_wrong_date_and_backfill() -> None:
    value = valid_execution("NO_BACKUP_DATA_WRITE")
    value["detail"]["observation"]["observation_date"] = "2026-08-28"
    with pytest.raises(ValueError, match="date"):
        contract.validate_execution_record(
            value,
            action="NO_BACKUP_DATA_WRITE",
            candidate_sha=CANDIDATE,
            protected_sha=PROTECTED,
            plan_commit=PLAN,
            plan_sha256=PLAN_SHA,
            operator="jkoka",
            expected_date="2026-08-29",
        )
    with pytest.raises(ValueError, match="action"):
        contract.validate_execution_record(
            valid_execution("NO_BACKUP_DATA_WRITE"),
            action="BACKFILL",
            candidate_sha=CANDIDATE,
            protected_sha=PROTECTED,
            plan_commit=PLAN,
            plan_sha256=PLAN_SHA,
            operator="jkoka",
            expected_date="2026-08-29",
        )


def test_deadline_requires_bounded_daylight_window() -> None:
    contract.validate_deadline(HOBART_NOW, HOBART_NOW.replace(hour=22), timedelta(hours=2))
    with pytest.raises(ValueError, match="insufficient time"):
        contract.validate_deadline(
            HOBART_NOW.replace(hour=21, minute=30),
            HOBART_NOW.replace(hour=22),
            timedelta(hours=1),
        )

    with pytest.raises(ValueError, match="insufficient time"):
        contract.validate_recovery_window(
            datetime.fromisoformat("2026-08-29T21:31:00+10:00")
        )
    with pytest.raises(ValueError, match="today's Hobart date"):
        contract.validate_deadline(
            HOBART_NOW,
            HOBART_NOW.replace(day=30, hour=22),
            timedelta(hours=2),
        )
    for hour, minute in ((0, 0), (0, 29), (0, 30), (3, 29)):
        with pytest.raises(ValueError, match="quiet window"):
            contract.validate_deadline(
                HOBART_NOW.replace(hour=hour, minute=minute),
                HOBART_NOW.replace(hour=22),
                timedelta(0),
            )


def test_source_rejects_yesterdays_authorised_observation() -> None:
    with pytest.raises(ValueError, match="today's Hobart date"):
        contract.validate_source_listing(
            listing(),
            protected_sha=PROTECTED,
            expected_observation_date="2026-08-28",
            now=HOBART_NOW,
        )


def test_task_snapshot_rejects_unparsed_extra_trigger() -> None:
    expectation = contract.TaskExpectation(
        "powershell.exe", "args", "repo", r"yanniedog\jkoka", OLD_CANDIDATE, True
    )
    value = task_snapshot(expectation)
    value["triggers"].append("UNPARSED_EXTRA")
    with pytest.raises(ValueError, match="triggers"):
        contract.validate_task_snapshot(value, expectation, last_result_zero=True)


def test_task_xml_hash_is_encoding_aware_but_raw_evidence_stays_distinct() -> None:
    text = "<?xml version='1.0'?><Task />"
    utf8 = text.encode("utf-8")
    utf16 = b"\xff\xfe" + text.encode("utf-16-le")
    assert contract.canonical_task_xml_sha256(utf8) == contract.canonical_task_xml_sha256(utf16)
    assert contract.sha256_bytes(utf8) != contract.sha256_bytes(utf16)


def test_handoff_transition_authorization_requires_one_canonical_object() -> None:
    payload = (
        "prefix\n"
        + contract.AUTH_BEGIN
        + "\n{\"schema_version\":1,\"candidate_code_sha\":\""
        + CANDIDATE
        + "\"}\n"
        + contract.AUTH_END
        + "\nsuffix\n"
    ).encode()
    assert contract.parse_transition_authorization(payload)["candidate_code_sha"] == CANDIDATE
    with pytest.raises(ValueError, match="lacks one"):
        contract.parse_transition_authorization(b"no authorization")
    with pytest.raises(ValueError, match="lacks one"):
        contract.parse_transition_authorization(payload + payload)


def test_execution_output_rejects_conflicts_and_path_escape(tmp_path: Path) -> None:
    target = tmp_path / "target"
    record = target / "catalog/scheduled-runs/one.json"
    record.parent.mkdir(parents=True)
    record.write_text("{}", encoding="utf-8")
    valid = json.dumps({
        "ok": True,
        "result": "PASS",
        "action": "NO_BACKUP_DATA_WRITE",
        "execution_record": str(record.resolve()),
    })
    assert contract.bind_execution_output(
        valid,
        target=target.resolve(),
        expected_action="NO_BACKUP_DATA_WRITE",
        record_path=record.resolve(),
    )["ok"] is True
    with pytest.raises(ValueError, match="exactly one"):
        contract.execution_document(valid + "\n" + valid)
    escaped = json.dumps({
        "ok": True,
        "result": "PASS",
        "action": "NO_BACKUP_DATA_WRITE",
        "execution_record": str((tmp_path / "escape.json").resolve()),
    })
    (tmp_path / "escape.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="escapes"):
        contract.bind_execution_output(
            escaped,
            target=target.resolve(),
            expected_action="NO_BACKUP_DATA_WRITE",
            record_path=record.resolve(),
        )


def test_cli_path_is_not_resolved_before_reparse_validation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = argparse.Namespace(
        target=tmp_path / "linked-target",
        recovery_image=tmp_path / "image",
        receiver=tmp_path / "receiver",
        old_receiver=tmp_path / "old-receiver",
        old_task_xml=tmp_path / "old.xml",
        candidate_code_sha=CANDIDATE,
        old_candidate_code_sha=OLD_CANDIDATE,
        protected_code_sha=PROTECTED,
        plan_git_commit=PLAN,
        plan_sha256=PLAN_SHA,
        authority_repo=tmp_path / "authority",
        authority_commit="a" * 40,
        handoff_sha256="b" * 64,
        expected_observation_date="2026-08-29",
        operator="jkoka",
        principal=r"yanniedog\jkoka",
        python_path=tmp_path / "python.exe",
        old_python_path=tmp_path / "old-python.exe",
        task_name="AR-local laptop backup",
        deadline="2026-08-29T22:00:00+10:00",
        host="ar-local-pi5-lan",
        accepted_old_xml_sha256="e" * 64,
    )
    parsed = transition.config_from_args(value)
    assert parsed.target.name == "linked-target"
    parsed.target.mkdir()
    monkeypatch.setattr(
        contract,
        "is_link_or_reparse",
        lambda path: path.name == "linked-target",
    )
    with pytest.raises(ValueError, match="traverses a link"):
        authority.validate_config(parsed)


def test_runtime_lease_allows_exact_stale_resume_only(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    with transition.runtime_lease(root, "one", resume=False):
        with pytest.raises(RuntimeError, match="active"):
            with transition.runtime_lease(root, "two", resume=False):
                pass
    lock = root / ".transition-runtime.lock"
    lock.write_text(json.dumps({"pid": 99999999, "transition_id": "one"}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="active"):
        with transition.runtime_lease(root, "two", resume=False):
            pass
    (root / "one").mkdir()
    (root / "ACTIVE_TRANSITION.json").write_text(
        json.dumps({
            "state": "OPEN",
            "transition_id": "one",
            "evidence_root": str((root / "one").resolve()),
        }), encoding="utf-8"
    )
    with transition.runtime_lease(root, "one", resume=True):
        assert lock.exists()


@pytest.mark.parametrize(
    "transition_id",
    ["../outside", "..", "a/b", "a\\b", "C:\\outside", ".hidden"],
)
def test_runtime_lease_rejects_unsafe_transition_id_before_writes(
    tmp_path: Path, transition_id: str
) -> None:
    root = tmp_path / "evidence"
    outside = tmp_path / "outside"

    with pytest.raises(ValueError, match="unsafe path characters"):
        with transition.runtime_lease(root, transition_id, resume=True):
            pass

    assert not outside.exists()
    assert not root.exists()


def test_runtime_lease_rejects_dead_lease_for_different_transition(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    evidence = root / "one"
    evidence.mkdir(parents=True)
    (root / "ACTIVE_TRANSITION.json").write_text(json.dumps({
        "state": "OPEN",
        "transition_id": "one",
        "evidence_root": str(evidence.resolve()),
    }), encoding="utf-8")
    lock = root / ".transition-runtime.lock"
    lock.write_text(
        json.dumps({"pid": 99999999, "transition_id": "different"}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="active"):
        with transition.runtime_lease(root, "one", resume=True):
            pass
    assert json.loads(lock.read_text(encoding="utf-8"))["transition_id"] == "different"


@pytest.mark.parametrize("damaged", [b"", b"{\"pid\":"])
def test_runtime_lease_preserves_and_reclaims_malformed_exact_resume(
    tmp_path: Path, damaged: bytes
) -> None:
    root = tmp_path / "evidence"
    (root / "one").mkdir(parents=True)
    (root / "ACTIVE_TRANSITION.json").write_text(
        json.dumps({
            "state": "OPEN",
            "transition_id": "one",
            "evidence_root": str((root / "one").resolve()),
        }), encoding="utf-8"
    )
    lock = root / ".transition-runtime.lock"
    lock.write_bytes(damaged)
    with transition.runtime_lease(root, "one", resume=True):
        assert json.loads(lock.read_text(encoding="utf-8"))["transition_id"] == "one"
    preserved = list((root / "one").glob("runtime-stale-*.preserved"))
    assert len(preserved) == 1
    assert preserved[0].read_bytes() == damaged


@pytest.mark.parametrize("pointer_state", ["PRE_POINTER", "CLOSED"])
def test_runtime_lease_reclaims_dead_crash_at_initialization_or_closed_boundary(
    tmp_path: Path, pointer_state: str
) -> None:
    root = tmp_path / "evidence"
    evidence = root / "one"
    evidence.mkdir(parents=True)
    if pointer_state == "CLOSED":
        terminal = evidence / "transition-result.json"
        terminal.write_text(json.dumps({"result": "PASS"}), encoding="utf-8")
        (root / "ACTIVE_TRANSITION.json").write_text(
            json.dumps({
                "state": "CLOSED",
                "transition_id": "one",
                "evidence_root": str(evidence.resolve()),
                "terminal_path": str(terminal.resolve()),
                "terminal_sha256": contract.sha256_file(terminal),
            }),
            encoding="utf-8",
        )
    lock = root / ".transition-runtime.lock"
    lock.write_text(json.dumps({"pid": 99999999, "transition_id": "one"}), encoding="utf-8")
    with transition.runtime_lease(root, "one", resume=True):
        assert json.loads(lock.read_text(encoding="utf-8"))["transition_id"] == "one"
    assert list(evidence.glob("runtime-stale-*.preserved"))


def test_two_exact_resume_contenders_cannot_both_reclaim_dead_lease(
    tmp_path: Path,
) -> None:
    root = tmp_path / "evidence"
    evidence = root / "one"
    evidence.mkdir(parents=True)
    (root / "ACTIVE_TRANSITION.json").write_text(json.dumps({
        "state": "OPEN",
        "transition_id": "one",
        "evidence_root": str(evidence.resolve()),
    }), encoding="utf-8")
    (root / ".transition-runtime.lock").write_text(
        json.dumps({"pid": 99999999, "transition_id": "one"}), encoding="utf-8"
    )
    start = threading.Barrier(2)
    release = threading.Event()
    entered: list[str] = []
    errors: list[str] = []

    def contender(name: str) -> None:
        start.wait()
        try:
            with transition.runtime_lease(root, "one", resume=True):
                entered.append(name)
                release.wait(5)
        except RuntimeError as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=contender, args=(name,)) for name in ("A", "B")]
    for thread in threads:
        thread.start()
    while not entered and any(thread.is_alive() for thread in threads):
        threading.Event().wait(0.01)
    for _ in range(200):
        if errors:
            break
        threading.Event().wait(0.01)
    assert len(errors) == 1
    release.set()
    for thread in threads:
        thread.join(timeout=10)
    assert len(entered) == 1


def test_active_transition_requires_resume_and_authenticates_closure(tmp_path: Path) -> None:
    (tmp_path / "catalog").mkdir()
    record = {
        "candidate_code_sha": CANDIDATE,
        "protected_code_sha": PROTECTED,
        "plan_git_commit": PLAN,
        "plan_sha256": PLAN_SHA,
        "operator": "jkoka",
    }
    config = type(
        "Config",
        (),
        {"target": tmp_path, "public_record": lambda _self: record},
    )()
    first = transition.Evidence(config, "first", resume=False, commands=["pytest"])
    with pytest.raises(RuntimeError, match="unterminated"):
        transition.Evidence(config, "second", resume=False, commands=["pytest"])
    terminal = contract.terminal_payload(
        transition_id="first",
        result="BLOCKED",
        config=record,
        evidence={"exact_commands": ["pytest"]},
        error="test",
        started_at=HOBART_NOW.isoformat(),
        completed_at=HOBART_NOW.isoformat(),
    )
    result = first.close(terminal)
    active = json.loads(first.pointer.read_text(encoding="utf-8"))
    assert active["terminal_sha256"] == contract.sha256_file(result)
    second = transition.Evidence(config, "second", resume=False, commands=["pytest"])
    assert second.transition_id == "second"


def test_catalog_delta_rejects_diagnostic_or_reordered_append(tmp_path: Path) -> None:
    catalog = tmp_path / "generations.jsonl"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    baseline = b""
    prior = None
    for sequence, kind in enumerate(("observation", "diagnostic", "control", "macro"), start=1):
        material = {
            "schema_version": 1,
            "sequence": sequence,
            "created_at": "2026-08-29T09:00:00Z",
            "previous_entry_sha256": prior,
            "kind": kind,
            "observation_date": "2026-08-29" if kind == "observation" else None,
            "run_date": "2026-08-20" if kind == "diagnostic" else None,
            "source_manifest_sha256": str(sequence) * 64,
            "archive_sha256": str(sequence) * 64,
            "receipt_path": f"{kind}/receipt.json",
            "receipt_sha256": str(sequence) * 64,
            "result": "PASS",
        }
        digest = contract.sha256_bytes(receiver.canonical_json_bytes(material))
        prior = digest
        with catalog.open("ab") as stream:
            stream.write(receiver.canonical_json_bytes({**material, "entry_sha256": digest}))
    with pytest.raises(ValueError, match="unexpected generation kinds"):
        contract.validate_catalog_delta(
            baseline,
            catalog,
            receipt_paths={kind: str((tmp_path / kind / "receipt.json").resolve()) for kind in contract.EXPECTED_KINDS},
        )
