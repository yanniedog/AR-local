from __future__ import annotations

import json
import copy
import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping

import pytest

import laptop_backup_transition as transition
import laptop_backup_transition_contract as contract
import laptop_pull_backup as receiver
from test_laptop_backup_transition_contract import HOBART_NOW, listing, task_snapshot


class FakeOps:
    def __init__(self, config: transition.TransitionConfig) -> None:
        self.config = config
        self.calls: list[str] = []
        self.disabled = False
        self.installed = False
        self.fail_action: str | None = None
        self._installer_output = ""
        self.serial = 0
        self.final_snapshot_drift = False
        self.malformed_installer_output = False
        self.partial_disable = False
        self.task_snapshot_override: Mapping[str, object] | None = None
        self.source_override: Mapping[str, object] | None = None
        self.process_override: list[Mapping[str, object]] = []
        self.malformed_check_output = False
        self.now_override: datetime | None = None

    def _record(self, action: str) -> str:
        self.serial += 1
        record = execution_record(action)
        previous_pointer = json.loads(
            (self.config.target / "catalog/latest-scheduled.json").read_text(
                encoding="utf-8"
            )
        )
        record["previous_execution"] = {
            "record_path": previous_pointer["record_path"],
            "record_sha256": previous_pointer["record_sha256"],
        }
        path = self.config.target / f"catalog/scheduled-runs/{self.serial:03d}-{action}.json"
        path.write_bytes(contract.canonical_json(record))
        pointer = {
            "record_path": path.relative_to(self.config.target).as_posix(),
            "record_sha256": contract.sha256_file(path),
            "result": "PASS",
        }
        receiver.atomic_replace(
            self.config.target / "catalog/latest-scheduled.json",
            contract.canonical_json(pointer),
        )
        return json.dumps({
            "ok": True,
            "result": "PASS",
            "action": action,
            "execution_record": str(path.resolve()),
        })

    def task(
        self,
        action: str,
        config: transition.TransitionConfig,
        old_xml: Path | None = None,
        transition_id: str | None = None,
    ) -> Mapping[str, object]:
        del old_xml
        if action == "Install":
            assert transition_id
        self.calls.append(f"task:{action}")
        if self.fail_action == action:
            if action == "Disable" and self.partial_disable:
                self.disabled = True
            raise RuntimeError(f"injected {action} failure")
        if action == "Disable":
            self.disabled = True
            return task_snapshot(transition.task_expectation(config, old=True, enabled=False))
        if action == "Snapshot" and not self.installed and self.task_snapshot_override is not None:
            return self.task_snapshot_override
        if action == "Install":
            self.installed = True
            self.disabled = False
            self._installer_output = self._record("NO_BACKUP_DATA_WRITE")
            if self.malformed_installer_output:
                self._installer_output += "\nnot-json"
            return task_snapshot(transition.task_expectation(config, old=False, enabled=True))
        if action == "RestoreDisabled":
            self.installed = False
            self.disabled = True
            return task_snapshot(transition.task_expectation(config, old=True, enabled=False))
        if action == "Enable":
            self.disabled = False
            return task_snapshot(transition.task_expectation(config, old=True, enabled=True))
        snapshot = task_snapshot(
            transition.task_expectation(
                config,
                old=not self.installed,
                enabled=not self.disabled,
            )
        )
        if action == "Snapshot" and self.installed and self.final_snapshot_drift:
            snapshot["triggers"][0]["at"] = "06:00:00"
        return snapshot

    def source_listing(self, _config: transition.TransitionConfig) -> Mapping[str, object]:
        self.calls.append("source")
        return self.source_override or listing()

    def run_scheduled(
        self,
        _config: transition.TransitionConfig,
        *,
        check_only: bool,
        transition_id: str,
    ) -> transition.CommandOutput:
        assert transition_id
        self.calls.append("scheduled:check" if check_only else "scheduled:foreground")
        if self.fail_action == ("Check" if check_only else "Foreground"):
            raise RuntimeError("injected scheduled failure")
        action = "NO_BACKUP_DATA_WRITE" if check_only else "BACKUP-LATEST"
        output = self._record(action)
        if check_only and self.malformed_check_output:
            output += "\nnot-json"
        return transition.CommandOutput(("python",), 0, output, "")

    def active_backup_processes(self) -> list[Mapping[str, object]]:
        self.calls.append("processes")
        return self.process_override

    def installer_output(self) -> str:
        return self._installer_output

    def command_log(self) -> list[str]:
        return list(self.calls)

    def planned_commands(
        self, _config: transition.TransitionConfig, transition_id: str
    ) -> list[str]:
        assert transition_id
        return [
            "snapshot",
            "disable",
            "foreground",
            "install",
            "check-only",
            "restore-disabled",
            "enable",
        ]

    def now(self) -> datetime:
        return self.now_override or HOBART_NOW


def config(tmp_path: Path) -> transition.TransitionConfig:
    target = tmp_path / "target"
    (target / "catalog/scheduled-runs").mkdir(parents=True)
    (target / "restore-drills").mkdir()
    (target / "catalog/generations.jsonl").write_bytes(b"")
    record = target / "catalog/scheduled-runs/existing.json"
    record.write_text(json.dumps({"result": "PASS"}), encoding="utf-8")
    (target / "catalog/latest-scheduled.json").write_text(json.dumps({
        "record_path": "catalog/scheduled-runs/existing.json",
        "record_sha256": contract.sha256_file(record),
        "result": "PASS",
    }), encoding="utf-8")
    for name in contract.COMPONENT_POINTERS:
        (target / "catalog" / name).write_text(json.dumps({"name": name}), encoding="utf-8")
    for kind in contract.EXPECTED_KINDS:
        receipt = target / kind / "receipt.json"
        receipt.parent.mkdir()
        receipt.write_text("{}", encoding="utf-8")
    receiver_root = tmp_path / "receiver"
    old_receiver = tmp_path / "old-receiver"
    authority = tmp_path / "authority"
    for path in (receiver_root, old_receiver, authority):
        path.mkdir()
    image = tmp_path / "image.bin"
    image.write_bytes(b"image")
    old_xml = tmp_path / "old-task.xml"
    old_xml.write_bytes(b"<Task />")
    python = tmp_path / "python.exe"
    python.write_bytes(b"")
    old_python = tmp_path / "python.bat"
    old_python.write_bytes(b"")
    return transition.TransitionConfig(
        target=target.resolve(),
        recovery_image=image.resolve(),
        receiver=receiver_root.resolve(),
        old_receiver=old_receiver.resolve(),
        old_task_xml=old_xml.resolve(),
        candidate_code_sha="c" * 40,
        old_candidate_code_sha="d" * 40,
        protected_code_sha="9" * 40,
        plan_git_commit=receiver.PLAN_GIT_COMMIT,
        plan_sha256=receiver.PLAN_SHA256,
        authority_repo=authority.resolve(),
        authority_commit="a" * 40,
        handoff_sha256="b" * 64,
        expected_observation_date="2026-08-29",
        operator="jkoka",
        principal=r"yanniedog\jkoka",
        python_path=python.resolve(),
        old_python_path=old_python.resolve(),
        task_name="AR-local laptop backup",
        deadline=datetime.fromisoformat("2026-08-29T22:00:00+10:00"),
        host="ar-local-pi5-lan",
        accepted_old_xml_sha256=contract.sha256_file(old_xml),
    )


def execution_record(action: str) -> dict[str, object]:
    state = {
        "status": "UP_TO_DATE",
        "backfill_required": False,
        "observation": {"status": "UP_TO_DATE", "observation_date": "2026-08-29"},
        "control": {"status": "UP_TO_DATE"},
        "macro": {"status": "UP_TO_DATE"},
        "inventory": {"status": "UP_TO_DATE", "missing_completed_dates": [], "stale_diagnostics": []},
    }
    detail: object = state
    if action == "BACKUP-LATEST":
        detail = {
            "before": {"status": "STALE", "backup_command": "backup-latest", "backfill_required": False},
            "after": state,
        }
    return {
        "schema_version": 1,
        "plan_document_id": receiver.PLAN_DOCUMENT_ID,
        "plan_version": receiver.PLAN_VERSION,
        "plan_git_commit": receiver.PLAN_GIT_COMMIT,
        "plan_sha256": receiver.PLAN_SHA256,
        "plan_raw_sha256": receiver.PLAN_NORMALIZED_RAW_SHA256,
        "plan_normalized_raw_sha256": receiver.PLAN_NORMALIZED_RAW_SHA256,
        "candidate_code_sha": "c" * 40,
        "protected_code_sha": "9" * 40,
        "operator": "jkoka",
        "timestamps": {"completed_at": "2026-08-29T09:00:00Z"},
        "exact_commands": ["python laptop_backup_scheduled.py --check-only"],
        "action": action,
        "result": "PASS",
        "detail": detail,
        "deviations": [],
        "deviation_authorization": None,
        "previous_execution": None,
    }


def patch_flow(monkeypatch: pytest.MonkeyPatch, value: transition.TransitionConfig) -> None:
    snapshot = task_snapshot(transition.task_expectation(value, old=True, enabled=True))
    monkeypatch.setattr(
        transition,
        "static_preflight",
        lambda _config, **_kwargs: {"authority_commit": value.authority_commit},
    )
    monkeypatch.setattr(transition, "validate_evidence_target", lambda _config: None)
    monkeypatch.setattr(
        transition,
        "runtime_preflight",
        lambda _config, _ops: (snapshot, listing(), {"status": "UP_TO_DATE"}),
    )
    monkeypatch.setattr(transition, "recovery_gate", lambda *_args: listing())
    monkeypatch.setattr(
        transition,
        "validate_backup_state",
        lambda *_args, **_kwargs: {"status": "UP_TO_DATE"},
    )
    receipts = {
        "observation": str((value.target / "observation/receipt.json").resolve()),
        "control": str((value.target / "control/receipt.json").resolve()),
        "macro": str((value.target / "macro/receipt.json").resolve()),
    }
    monkeypatch.setattr(contract, "validate_receipts", lambda *_args, **_kwargs: receipts)
    monkeypatch.setattr(contract, "validate_catalog_delta", lambda *_args, **_kwargs: [])


def test_success_calls_foreground_once_and_never_restores(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    patch_flow(monkeypatch, value)
    result, terminal = transition.run_transition(value, ops, transition_id="success")
    assert result == "PASS"
    assert ops.calls.count("scheduled:foreground") == 1
    assert ops.calls.count("scheduled:check") == 1
    payload = json.loads(terminal.read_text(encoding="utf-8"))
    assert "restore-disabled" in payload["evidence"]["authorized_commands"]
    assert "enable" in payload["evidence"]["authorized_commands"]
    assert payload["exact_commands"][1:] == ops.calls
    assert "task:RestoreDisabled" not in payload["exact_commands"]
    assert ops.calls.count("task:Install") == 1
    assert "task:RestoreDisabled" not in ops.calls
    assert payload["result"] == "PASS"


def test_run_transition_rejects_supplied_empty_id_before_writes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    patch_flow(monkeypatch, value)

    with pytest.raises(ValueError, match="unsafe path characters"):
        transition.run_transition(value, ops, transition_id="")

    assert not (value.target / "evidence/A3-LAPTOP-TASK-TRANSITION").exists()
    assert not ops.calls


def test_invalid_preflight_invokes_no_backup_installer_or_task_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    monkeypatch.setattr(
        transition,
        "static_preflight",
        lambda _config, **_kwargs: {"authority_commit": value.authority_commit},
    )
    monkeypatch.setattr(transition, "validate_evidence_target", lambda _config: None)
    monkeypatch.setattr(
        transition,
        "runtime_preflight",
        lambda *_args: (_ for _ in ()).throw(ValueError("invalid preflight")),
    )
    result, terminal = transition.run_transition(value, ops, transition_id="blocked")
    assert result == "BLOCKED"
    assert json.loads(terminal.read_text(encoding="utf-8"))["result"] == "BLOCKED"
    assert ops.calls == []


def test_invalid_static_authority_gets_immutable_blocked_terminal_without_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    monkeypatch.setattr(transition, "validate_evidence_target", lambda _config: None)
    monkeypatch.setattr(
        transition,
        "static_preflight",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("tampered authority")),
    )
    result, terminal = transition.run_transition(value, ops, transition_id="bad-authority")
    assert result == "BLOCKED"
    payload = json.loads(terminal.read_text(encoding="utf-8"))
    assert payload["result"] == "BLOCKED"
    assert "tampered authority" in payload["error"]
    assert ops.calls == []
    assert not (value.target / "catalog/.receiver.lock").exists()


def test_blocked_preflight_preserves_unowned_receiver_lock_and_still_terminalizes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    lock = value.target / "catalog/.receiver.lock"
    lock.write_text(json.dumps({"pid": 123, "nonce": "other"}), encoding="utf-8")
    monkeypatch.setattr(transition, "validate_evidence_target", lambda _config: None)
    monkeypatch.setattr(
        transition,
        "static_preflight",
        lambda *_args, **_kwargs: {"authority_commit": value.authority_commit},
    )
    monkeypatch.setattr(
        transition,
        "runtime_preflight",
        lambda *_args: (_ for _ in ()).throw(ValueError("receiver lock exists")),
    )
    result, terminal = transition.run_transition(value, ops, transition_id="blocked-lock")
    assert result == "BLOCKED"
    assert json.loads(terminal.read_text(encoding="utf-8"))["result"] == "BLOCKED"
    assert json.loads(lock.read_text(encoding="utf-8"))["nonce"] == "other"


def test_closed_pointer_crash_before_guard_release_is_idempotently_cleaned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = config(tmp_path)
    evidence = transition.Evidence(
        value, "closed-guard", resume=False, commands=["pytest closed guard"]
    )
    terminal = contract.terminal_payload(
        transition_id="closed-guard",
        result="BLOCKED",
        config=value.public_record(),
        evidence={"exact_commands": ["pytest"]},
        error="test",
        started_at=HOBART_NOW.isoformat(),
        completed_at=HOBART_NOW.isoformat(),
    )
    original_release = evidence.release_transition_guard
    monkeypatch.setattr(
        evidence,
        "release_transition_guard",
        lambda: (_ for _ in ()).throw(OSError("injected close crash")),
    )
    with pytest.raises(OSError, match="close crash"):
        evidence.close(terminal)
    assert json.loads(evidence.pointer.read_text(encoding="utf-8"))["state"] == "CLOSED"
    assert evidence.guard.exists()
    resumed = transition.Evidence(value, "closed-guard", resume=True)
    assert resumed.closed_terminal is not None
    resumed.release_transition_guard()
    assert not evidence.guard.exists()
    monkeypatch.setattr(evidence, "release_transition_guard", original_release)


def test_post_rollback_preflight_accepts_newest_candidate_scheduled_record_separately(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    record = value.target / "catalog/scheduled-runs/post-rollback.json"
    record.write_bytes(contract.canonical_json(execution_record("NO_BACKUP_DATA_WRITE")))
    receiver.atomic_replace(
        value.target / "catalog/latest-scheduled.json",
        contract.canonical_json({
            "record_path": record.relative_to(value.target).as_posix(),
            "record_sha256": contract.sha256_file(record),
            "result": "PASS",
        }),
    )
    monkeypatch.setattr(
        transition.scheduled,
        "latest_status",
        lambda *_args, **_kwargs: {"status": "UP_TO_DATE"},
    )
    monkeypatch.setattr(
        transition.scheduled,
        "component_status",
        lambda *_args, **_kwargs: {"status": "UP_TO_DATE"},
    )
    monkeypatch.setattr(
        transition.scheduled,
        "inventory_status",
        lambda *_args, **_kwargs: {"status": "UP_TO_DATE"},
    )
    receipts = {
        kind: str((value.target / kind / "receipt.json").resolve())
        for kind in contract.EXPECTED_KINDS
    }
    monkeypatch.setattr(contract, "validate_receipts", lambda *_args, **_kwargs: receipts)
    state = transition.validate_backup_state(
        value,
        listing(),
        candidate_sha=value.old_candidate_code_sha,
        require_scheduled=True,
        scheduled_candidates=(value.old_candidate_code_sha, value.candidate_code_sha),
    )
    assert state["scheduled_record"]["path"] == str(record)


def test_foreground_rejection_never_installs_and_restores_old_task(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    patch_flow(monkeypatch, value)
    monkeypatch.setattr(
        transition,
        "validate_scheduled_result",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("conflicting JSON")),
    )
    result, terminal = transition.run_transition(value, ops, transition_id="reject")
    assert result == "ROLLED_BACK"
    assert ops.calls.count("scheduled:foreground") == 1
    assert "task:Install" not in ops.calls
    assert ops.calls.count("task:RestoreDisabled") == 1
    payload = json.loads(terminal.read_text(encoding="utf-8"))
    assert payload["exact_commands"][1:] == ops.calls
    assert payload["evidence"]["recovery"]["post_recovery_readback"]["files"]
    assert json.loads(terminal.read_text(encoding="utf-8"))["result"] == "ROLLED_BACK"


def test_disable_failure_enters_recovery_without_backup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    ops.fail_action = "Disable"
    patch_flow(monkeypatch, value)
    result, _terminal = transition.run_transition(value, ops, transition_id="disable-fail")
    assert result == "ROLLED_BACK"
    assert "scheduled:foreground" not in ops.calls
    assert ops.calls.count("task:RestoreDisabled") == 1


def test_installer_failure_restores_component_pointers_and_old_task(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    ops.fail_action = "Install"
    patch_flow(monkeypatch, value)
    original = {
        name: (value.target / "catalog" / name).read_bytes()
        for name in contract.COMPONENT_POINTERS
    }

    changed = False

    def change_pointers(*_args: object, **_kwargs: object) -> dict[str, str]:
        nonlocal changed
        if not changed:
            for name in contract.COMPONENT_POINTERS:
                receiver.atomic_replace(value.target / "catalog" / name, b"new candidate")
            changed = True
        return {
            "observation": str((value.target / "observation/receipt.json").resolve()),
            "control": str((value.target / "control/receipt.json").resolve()),
            "macro": str((value.target / "macro/receipt.json").resolve()),
        }

    monkeypatch.setattr(contract, "validate_receipts", change_pointers)
    result, _terminal = transition.run_transition(value, ops, transition_id="install-fail")
    assert result == "ROLLED_BACK"
    assert ops.calls.count("task:RestoreDisabled") == 1
    for name, payload in original.items():
        assert (value.target / "catalog" / name).read_bytes() == payload
    latest = json.loads((value.target / "catalog/latest-scheduled.json").read_text(encoding="utf-8"))
    assert latest["record_path"].endswith("001-BACKUP-LATEST.json")


def test_crash_after_disable_resumes_recovery_without_new_backup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    patch_flow(monkeypatch, value)
    evidence = transition.Evidence(value, "crashed", resume=False, commands=["pytest resume"])
    evidence.persist_inputs(value, ["pytest resume"])
    snapshot = task_snapshot(transition.task_expectation(value, old=True, enabled=True))
    transition.write_prestate(evidence, value, snapshot, listing())
    evidence.checkpoint("TASK_DISABLE_ATTEMPTED")
    evidence.checkpoint("TASK_DISABLED")
    ops.disabled = True
    result, terminal = transition.run_transition(
        value, ops, transition_id="crashed", resume=True
    )
    assert result == "ROLLED_BACK"
    assert "scheduled:foreground" not in ops.calls
    assert "task:Install" not in ops.calls
    assert ops.calls.count("task:RestoreDisabled") == 1
    assert json.loads(terminal.read_text(encoding="utf-8"))["result"] == "ROLLED_BACK"


def test_resume_during_quiet_window_defers_all_mutation_and_keeps_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    patch_flow(monkeypatch, value)
    evidence = transition.Evidence(value, "quiet", resume=False, commands=["pytest quiet"])
    evidence.persist_inputs(value, ["pytest quiet"])
    snapshot = task_snapshot(transition.task_expectation(value, old=True, enabled=True))
    transition.write_prestate(evidence, value, snapshot, listing())
    evidence.checkpoint("TASK_DISABLE_ATTEMPTED")
    monkeypatch.setattr(
        transition,
        "recovery_gate",
        lambda *_args: (_ for _ in ()).throw(transition.RecoveryDeferred("quiet")),
    )
    with pytest.raises(transition.RecoveryDeferred, match="quiet"):
        transition.run_transition(value, ops, transition_id="quiet", resume=True)
    assert not any(call.startswith("task:") for call in ops.calls)
    active = json.loads(evidence.pointer.read_text(encoding="utf-8"))
    assert active["state"] == "OPEN"


def test_tampered_unsealed_terminal_is_never_sealed_as_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    patch_flow(monkeypatch, value)
    evidence = transition.Evidence(value, "tampered", resume=False, commands=["pytest terminal"])
    evidence.persist_inputs(value, ["pytest terminal"])
    evidence.create("transition-result.json", contract.canonical_json({
        "transition_id": "tampered",
        "result": "PASS",
        "config": {"candidate_code_sha": "wrong"},
    }))
    result, terminal = transition.run_transition(value, ops, transition_id="tampered", resume=True)
    assert result == "BLOCKED"
    assert json.loads(terminal.read_text(encoding="utf-8"))["result"] == "BLOCKED"
    assert list(evidence.path.glob("unsealed-transition-result-*.json"))


def test_final_task_drift_rolls_back_instead_of_passing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    ops.final_snapshot_drift = True
    patch_flow(monkeypatch, value)
    result, terminal = transition.run_transition(value, ops, transition_id="final-drift")
    assert result == "ROLLED_BACK"
    assert ops.calls.count("task:RestoreDisabled") == 1
    assert json.loads(terminal.read_text(encoding="utf-8"))["result"] == "ROLLED_BACK"


def test_final_deadline_overrun_rolls_back_instead_of_passing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    patch_flow(monkeypatch, value)
    original = contract.validate_deadline

    def deadline(now: datetime, end: datetime, remaining: object) -> None:
        if getattr(remaining, "total_seconds")() == 0:
            raise ValueError("hard deadline expired")
        original(now, end, remaining)

    monkeypatch.setattr(contract, "validate_deadline", deadline)
    result, _terminal = transition.run_transition(value, ops, transition_id="deadline-overrun")
    assert result == "ROLLED_BACK"
    assert ops.calls.count("task:RestoreDisabled") == 1


def test_malformed_installer_internal_gate_rolls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    ops.malformed_installer_output = True
    patch_flow(monkeypatch, value)
    result, _terminal = transition.run_transition(value, ops, transition_id="bad-installer-output")
    assert result == "ROLLED_BACK"
    assert "scheduled:check" not in ops.calls
    assert ops.calls.count("task:RestoreDisabled") == 1


@pytest.mark.parametrize("completed_components", [1, 2, 3])
def test_failure_after_each_component_boundary_restores_all_candidate_pointers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    completed_components: int,
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    patch_flow(monkeypatch, value)
    originals = {
        name: (value.target / "catalog" / name).read_bytes()
        for name in contract.COMPONENT_POINTERS
    }
    first = True
    receipts = {
        kind: str((value.target / kind / "receipt.json").resolve())
        for kind in contract.EXPECTED_KINDS
    }

    def boundary(*_args: object, **_kwargs: object) -> dict[str, str]:
        nonlocal first
        if first:
            first = False
            for name in contract.COMPONENT_POINTERS[:completed_components]:
                receiver.atomic_replace(value.target / "catalog" / name, b"candidate pointer")
            raise ValueError(f"injected component boundary {completed_components}")
        return receipts

    monkeypatch.setattr(contract, "validate_receipts", boundary)
    result, _terminal = transition.run_transition(
        value, ops, transition_id=f"component-{completed_components}"
    )
    assert result == "ROLLED_BACK"
    assert "task:Install" not in ops.calls
    for name, payload in originals.items():
        assert (value.target / "catalog" / name).read_bytes() == payload


def test_partial_disable_failure_restores_exact_old_task_without_backup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    ops.fail_action = "Disable"
    ops.partial_disable = True
    patch_flow(monkeypatch, value)
    result, _terminal = transition.run_transition(value, ops, transition_id="partial-disable")
    assert result == "ROLLED_BACK"
    assert "scheduled:foreground" not in ops.calls
    assert ops.calls.count("task:RestoreDisabled") == 1


def test_interrupted_recovery_keeps_lock_open_then_exact_resume_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    patch_flow(monkeypatch, value)
    evidence = transition.Evidence(value, "recovery-retry", resume=False, commands=["pytest recovery"])
    evidence.persist_inputs(value, ["pytest recovery"])
    snapshot = task_snapshot(transition.task_expectation(value, old=True, enabled=True))
    transition.write_prestate(evidence, value, snapshot, listing())
    evidence.checkpoint("TASK_DISABLE_ATTEMPTED")
    evidence.checkpoint("TASK_DISABLED")
    ops.disabled = True
    ops.fail_action = "RestoreDisabled"
    with pytest.raises(transition.RecoveryDeferred, match="incomplete"):
        transition.run_transition(value, ops, transition_id="recovery-retry", resume=True)
    assert json.loads(evidence.pointer.read_text(encoding="utf-8"))["state"] == "OPEN"
    ops.fail_action = None
    result, terminal = transition.run_transition(
        value, ops, transition_id="recovery-retry", resume=True
    )
    assert result == "ROLLED_BACK"
    assert json.loads(terminal.read_text(encoding="utf-8"))["result"] == "ROLLED_BACK"


def test_tampered_saved_pointer_blocks_recovery_before_task_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    patch_flow(monkeypatch, value)
    evidence = transition.Evidence(value, "bad-saved", resume=False, commands=["pytest saved"])
    evidence.persist_inputs(value, ["pytest saved"])
    snapshot = task_snapshot(transition.task_expectation(value, old=True, enabled=True))
    transition.write_prestate(evidence, value, snapshot, listing())
    evidence.checkpoint("TASK_DISABLE_ATTEMPTED")
    (evidence.path / "pre-transition-latest-verified.json").write_text("tampered", encoding="utf-8")
    with pytest.raises(transition.RecoveryDeferred, match="incomplete"):
        transition.run_transition(value, ops, transition_id="bad-saved", resume=True)
    assert not any(call in {"task:RestoreDisabled", "task:Install"} for call in ops.calls)
    assert json.loads(evidence.pointer.read_text(encoding="utf-8"))["state"] == "OPEN"


def test_two_concurrent_contenders_allow_one_owner(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    entered = threading.Event()
    release = threading.Event()
    outcomes: list[str] = []

    def owner() -> None:
        with transition.runtime_lease(root, "owner", resume=False):
            outcomes.append("owner")
            entered.set()
            release.wait(timeout=5)

    thread = threading.Thread(target=owner)
    thread.start()
    assert entered.wait(timeout=5)
    with pytest.raises(RuntimeError, match="active"):
        with transition.runtime_lease(root, "contender", resume=False):
            outcomes.append("contender")
    release.set()
    thread.join(timeout=5)
    assert outcomes == ["owner"]


def test_two_full_harness_contenders_allow_only_owner_to_reach_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    owner_ops = FakeOps(value)
    loser_ops = FakeOps(value)
    patch_flow(monkeypatch, value)
    entered = threading.Event()
    release = threading.Event()
    results: dict[str, object] = {}

    def authority(_config: transition.TransitionConfig, **_kwargs: object) -> dict[str, str]:
        entered.set()
        release.wait(timeout=5)
        return {"authority_commit": value.authority_commit}

    monkeypatch.setattr(transition, "static_preflight", authority)

    def invoke(label: str, ops: FakeOps) -> None:
        try:
            results[label] = transition.run_transition(value, ops, transition_id=label)
        except Exception as exc:  # expected for the losing atomic contender
            results[label] = exc

    owner = threading.Thread(target=invoke, args=("owner-full", owner_ops))
    owner.start()
    assert entered.wait(timeout=5)
    loser = threading.Thread(target=invoke, args=("loser-full", loser_ops))
    loser.start()
    loser.join(timeout=5)
    release.set()
    owner.join(timeout=10)
    assert results["owner-full"][0] == "PASS"
    assert isinstance(results["loser-full"], RuntimeError)
    assert "active" in str(results["loser-full"])
    assert owner_ops.calls.count("scheduled:foreground") == 1
    assert not any(call.startswith("task:") or call.startswith("scheduled:") for call in loser_ops.calls)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(state="Running"),
        lambda value: value.update(state="Disabled", enabled=False),
        lambda value: value.update(last_task_result=1),
        lambda value: value["actions"][0].update(arguments="drifted"),
        lambda value: value["triggers"][0].update(at="06:00:00"),
        lambda value: value["settings"].update(restart_count=0),
    ],
)
def test_runtime_preflight_task_failures_have_zero_mutating_calls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: object,
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    snapshot = task_snapshot(transition.task_expectation(value, old=True, enabled=True))
    mutation(snapshot)
    ops.task_snapshot_override = snapshot
    monkeypatch.setattr(
        transition, "validate_backup_state", lambda *_args, **_kwargs: {"status": "UP_TO_DATE"}
    )
    with pytest.raises(ValueError):
        transition.runtime_preflight(value, ops)
    assert not any(call in {"task:Disable", "task:Install", "task:RestoreDisabled"} for call in ops.calls)
    assert not any(call.startswith("scheduled:") for call in ops.calls)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["preflight"]["production"].update(clean=False),
        lambda value: value["preflight"]["production"].update(commit="0" * 40),
        lambda value: value["preflight"].update(daily_service="active"),
        lambda value: value["preflight"].update(daily_timer="disabled"),
        lambda value: value["preflight"].update(daily_timer_active="inactive"),
        lambda value: value["preflight"].update(ingest_lock_absent=False),
        lambda value: value["preflight"].update(dashboard_healthy=False),
        lambda value: value["preflight"].update(daily_timer_next="Sun 2026-08-30 02:00:00 AEST"),
        lambda value: value["latest_observation"].update(observation_date="2026-08-28"),
    ],
)
def test_runtime_preflight_pi_failures_have_zero_mutating_calls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: object,
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    source = copy.deepcopy(listing())
    mutation(source)
    ops.source_override = source
    monkeypatch.setattr(
        transition, "validate_backup_state", lambda *_args, **_kwargs: {"status": "UP_TO_DATE"}
    )
    with pytest.raises(ValueError):
        transition.runtime_preflight(value, ops)
    assert not any(call in {"task:Disable", "task:Install", "task:RestoreDisabled"} for call in ops.calls)
    assert not any(call.startswith("scheduled:") for call in ops.calls)


@pytest.mark.parametrize("condition", ["lock", "partial", "helper", "disk"])
def test_runtime_preflight_local_safety_failures_have_zero_task_or_backup_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    condition: str,
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    if condition == "lock":
        (value.target / "catalog/.receiver.lock").write_text("locked", encoding="utf-8")
    elif condition == "partial":
        (value.target / "orphan.partial").write_text("partial", encoding="utf-8")
    elif condition == "helper":
        ops.process_override = [{"pid": 123, "command_line": "laptop_backup_scheduled.py"}]
    else:
        monkeypatch.setattr(
            transition.shutil,
            "disk_usage",
            lambda _path: SimpleNamespace(free=contract.FREE_FLOOR - 1),
        )
    monkeypatch.setattr(
        transition, "validate_backup_state", lambda *_args, **_kwargs: {"status": "UP_TO_DATE"}
    )
    with pytest.raises(ValueError):
        transition.runtime_preflight(value, ops)
    assert not any(call.startswith("task:") for call in ops.calls)
    assert not any(call.startswith("scheduled:") for call in ops.calls)


def test_live_task_xml_byte_drift_blocks_before_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    snapshot = task_snapshot(transition.task_expectation(value, old=True, enabled=True))
    snapshot["xml_base64"] = __import__("base64").b64encode(b"<Task drift='1' />").decode()
    ops.task_snapshot_override = snapshot
    monkeypatch.setattr(
        transition, "validate_backup_state", lambda *_args, **_kwargs: {"status": "UP_TO_DATE"}
    )
    with pytest.raises(ValueError, match="XML bytes"):
        transition.runtime_preflight(value, ops)
    assert "task:Disable" not in ops.calls


def test_malformed_standalone_check_rolls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    ops.malformed_check_output = True
    patch_flow(monkeypatch, value)
    result, _terminal = transition.run_transition(value, ops, transition_id="bad-check-output")
    assert result == "ROLLED_BACK"
    assert ops.calls.count("scheduled:check") == 1
    assert ops.calls.count("task:RestoreDisabled") == 1


@pytest.mark.parametrize(
    "stages",
    [
        ["TASK_DISABLE_ATTEMPTED"],
        ["TASK_DISABLE_ATTEMPTED", "TASK_DISABLED", "FOREGROUND_STARTED"],
        [
            "TASK_DISABLE_ATTEMPTED",
            "TASK_DISABLED",
            "FOREGROUND_STARTED",
            "FOREGROUND_PASS",
            "INSTALL_ATTEMPTED",
        ],
    ],
)
def test_authenticated_restart_at_each_mutation_stage_never_runs_new_backup_or_installer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stages: list[str],
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    patch_flow(monkeypatch, value)
    evidence = transition.Evidence(value, "stage-restart", resume=False, commands=["pytest stage restart"])
    evidence.persist_inputs(value, ["pytest stage restart"])
    snapshot = task_snapshot(transition.task_expectation(value, old=True, enabled=True))
    transition.write_prestate(evidence, value, snapshot, listing())
    for stage in stages:
        evidence.checkpoint(stage)
    if "FOREGROUND_STARTED" in stages:
        for name in contract.COMPONENT_POINTERS:
            receiver.atomic_replace(value.target / "catalog" / name, b"candidate pointer")
    result, terminal = transition.run_transition(
        value, ops, transition_id="stage-restart", resume=True
    )
    assert result == "ROLLED_BACK"
    assert "scheduled:foreground" not in ops.calls
    assert "scheduled:check" not in ops.calls
    assert "task:Install" not in ops.calls
    assert ops.calls.count("task:RestoreDisabled") == 1
    assert json.loads(terminal.read_text(encoding="utf-8"))["result"] == "ROLLED_BACK"
