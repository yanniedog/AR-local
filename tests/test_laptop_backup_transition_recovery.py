from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path

import pytest

import laptop_backup_transition as transition
import laptop_backup_transition_contract as contract
import laptop_pull_backup as receiver
from test_laptop_backup_transition_contract import listing, task_snapshot
from test_laptop_backup_transition_flow import FakeOps, config, patch_flow


class ReceiverLockCheckingOps(FakeOps):
    def run_scheduled(
        self,
        config: transition.TransitionConfig,
        *,
        check_only: bool,
        transition_id: str,
    ) -> transition.CommandOutput:
        if not check_only and not self.installed:
            with receiver.ReceiverLock(config.target):
                assert (config.target / "catalog/.receiver.lock").exists()
        return super().run_scheduled(
            config, check_only=check_only, transition_id=transition_id
        )


def test_full_harness_releases_transition_guard_before_real_receiver_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    ops = ReceiverLockCheckingOps(value)
    patch_flow(monkeypatch, value)
    result, _terminal = transition.run_transition(
        value, ops, transition_id="real-receiver-lock"
    )
    assert result == "PASS"
    assert ops.calls.count("scheduled:foreground") == 1


@pytest.mark.parametrize("external_state", ["deleted", "tampered"])
def test_recovery_uses_authenticated_saved_task_xml_when_external_copy_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, external_state: str
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    patch_flow(monkeypatch, value)
    evidence = transition.Evidence(
        value, f"saved-xml-{external_state}", resume=False, commands=["pytest saved xml"]
    )
    snapshot = task_snapshot(transition.task_expectation(value, old=True, enabled=True))
    transition.write_prestate(evidence, value, snapshot, listing())
    evidence.checkpoint("TASK_DISABLE_ATTEMPTED")
    if external_state == "deleted":
        value.old_task_xml.unlink()
    else:
        value.old_task_xml.write_bytes(b"<Task tampered='true' />")
    recovered = transition.recover(value, ops, evidence)
    assert recovered["restored"] == ["task"]
    assert ops.calls.count("task:Restore") == 1


@pytest.mark.parametrize("fail_after", [1, 2, 3])
def test_recovery_pointer_interruption_is_idempotently_resumable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fail_after: int
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    patch_flow(monkeypatch, value)
    evidence = transition.Evidence(
        value, f"pointer-{fail_after}", resume=False, commands=["pytest pointer recovery"]
    )
    evidence.persist_inputs(value, ["pytest pointer recovery"])
    snapshot = task_snapshot(transition.task_expectation(value, old=True, enabled=True))
    transition.write_prestate(evidence, value, snapshot, listing())
    evidence.checkpoint("TASK_DISABLE_ATTEMPTED")
    evidence.checkpoint("FOREGROUND_STARTED")
    for name in contract.COMPONENT_POINTERS:
        receiver.atomic_replace(value.target / "catalog" / name, b"candidate pointer")
    original_replace = receiver.atomic_replace
    calls = 0

    def interrupted(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == fail_after:
            raise OSError("injected pointer interruption")
        original_replace(path, payload)

    monkeypatch.setattr(receiver, "atomic_replace", interrupted)
    with pytest.raises(OSError, match="pointer interruption"):
        transition.recover(value, ops, evidence)
    monkeypatch.setattr(receiver, "atomic_replace", original_replace)
    recovered = transition.recover(value, ops, evidence)
    assert recovered["restored"] == [*contract.COMPONENT_POINTERS, "task"]
    for name in contract.COMPONENT_POINTERS:
        assert (value.target / "catalog" / name).read_bytes() == (
            evidence.path / f"pre-transition-{name}"
        ).read_bytes()


def test_open_transition_guard_blocks_old_receiver_then_allows_foreground(
    tmp_path: Path,
) -> None:
    value = config(tmp_path)
    evidence = transition.Evidence(
        value, "startup-guard", resume=False, commands=["pytest startup guard"]
    )
    with pytest.raises(FileExistsError):
        with receiver.ReceiverLock(value.target):
            pytest.fail("old receiver reached backup mutation")
    evidence.release_transition_guard()
    with receiver.ReceiverLock(value.target):
        assert (value.target / "catalog/.receiver.lock").exists()


def test_crash_between_guard_and_active_pointer_is_adopted_by_exact_resume(
    tmp_path: Path,
) -> None:
    value = config(tmp_path)
    evidence = transition.Evidence(
        value, "guard-adopt", resume=False, commands=["pytest guard adopt"]
    )
    evidence.pointer.unlink()
    resumed = transition.Evidence(value, "guard-adopt", resume=True)
    active = json.loads(resumed.pointer.read_text(encoding="utf-8"))
    assert active["state"] == "OPEN"
    assert active["transition_guard_sha256"] == contract.sha256_file(resumed.guard)


def test_cross_day_recovery_uses_current_pi_safety_without_relabelling_old_freshness(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    real_recovery_gate = transition.recovery_gate
    patch_flow(monkeypatch, value)
    evidence = transition.Evidence(
        value, "cross-day", resume=False, commands=["pytest cross day"]
    )
    snapshot = task_snapshot(transition.task_expectation(value, old=True, enabled=True))
    transition.write_prestate(evidence, value, snapshot, listing())
    evidence.checkpoint("TASK_DISABLE_ATTEMPTED")
    evidence.checkpoint("TASK_DISABLED")
    next_day = copy.deepcopy(listing())
    next_day["preflight"]["checked_at"] = "2026-08-30T06:00:00+10:00"
    next_day["preflight"]["daily_timer_next"] = "Mon 2026-08-31 01:00:00 AEST"
    next_day["retained_runs"].append({"date": "2026-08-30", "status": "completed"})
    next_day["completed_dates"].append("2026-08-30")
    next_day["latest_observation"]["observation_date"] = "2026-08-30"
    ops.source_override = next_day
    ops.now_override = datetime.fromisoformat("2026-08-30T06:00:00+10:00")
    monkeypatch.setattr(transition, "recovery_gate", real_recovery_gate)
    result, terminal = transition.run_transition(
        value, ops, transition_id="cross-day", resume=True
    )
    assert result == "ROLLED_BACK"
    payload = json.loads(terminal.read_text(encoding="utf-8"))
    assert payload["evidence"]["recovery"]["old_candidate_state"]["freshness"] == (
        "MAY_BE_STALE_AFTER_CROSS_DAY_RECOVERY"
    )


@pytest.mark.parametrize("residue", ["stale-lock", "partial", "atomic-temp"])
def test_authenticated_foreground_recovery_preserves_and_reclaims_kill_residue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, residue: str
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    real_recovery_gate = transition.recovery_gate
    patch_flow(monkeypatch, value)
    evidence = transition.Evidence(
        value, f"residue-{residue}", resume=False, commands=["pytest residue"]
    )
    snapshot = task_snapshot(transition.task_expectation(value, old=True, enabled=True))
    transition.write_prestate(evidence, value, snapshot, listing())
    evidence.checkpoint("TASK_DISABLE_ATTEMPTED")
    evidence.checkpoint("TASK_DISABLED")
    evidence.checkpoint("FOREGROUND_STARTED")
    evidence.release_transition_guard()
    if residue == "stale-lock":
        (value.target / "catalog/.receiver.lock").write_text(
            json.dumps({"pid": 99999999, "nonce": "dead", "started_at": "2026-08-29T09:00:00Z"}),
            encoding="utf-8",
        )
    elif residue == "partial":
        partial = value.target / "observations/2026-08-29/deadbeef/.observation.tar.zst.dead.partial"
        partial.parent.mkdir(parents=True)
        partial.write_bytes(b"partial bytes")
    else:
        temporary = value.target / (
            "catalog/.latest-verified.json." + "a" * 32 + ".tmp"
        )
        temporary.write_bytes(b"atomic temp bytes")
    monkeypatch.setattr(transition, "recovery_gate", real_recovery_gate)
    result, _terminal = transition.run_transition(
        value, ops, transition_id=f"residue-{residue}", resume=True
    )
    assert result == "ROLLED_BACK"
    assert not (value.target / "catalog/.receiver.lock").exists()
    assert not list(value.target.rglob("*.partial"))
    assert not any(contract.temporary_paths(value.target))
    if residue == "stale-lock":
        assert list(evidence.path.glob("stale-receiver-lock-*.json"))
    elif residue == "partial":
        assert list((evidence.path / "recovered-partials").iterdir())
    else:
        preserved = list((evidence.path / "recovered-temporaries").iterdir())
        assert len(preserved) == 1
        assert preserved[0].read_bytes() == b"atomic temp bytes"


def test_unknown_temporary_residue_fails_closed(tmp_path: Path) -> None:
    value = config(tmp_path)
    evidence = transition.Evidence(
        value, "unknown-temp", resume=False, commands=["pytest unknown temp"]
    )
    evidence.release_transition_guard()
    (value.target / "catalog/unowned.tmp").write_bytes(b"unknown")
    with pytest.raises(RuntimeError, match="unknown temporary residue"):
        evidence.quarantine_atomic_temporaries(receiver_mutation_started=True)


@pytest.mark.parametrize("external_state", ["deleted", "tampered"])
def test_full_resume_uses_sealed_xml_without_external_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, external_state: str
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    patch_flow(monkeypatch, value)
    evidence = transition.Evidence(
        value, f"resume-saved-{external_state}", resume=False, commands=["pytest resume saved"]
    )
    transition.write_prestate(
        evidence,
        value,
        task_snapshot(transition.task_expectation(value, old=True, enabled=True)),
        listing(),
    )
    evidence.checkpoint("TASK_DISABLE_ATTEMPTED")
    evidence.checkpoint("TASK_DISABLED")
    if external_state == "deleted":
        value.old_task_xml.unlink()
    else:
        value.old_task_xml.write_bytes(b"<Task tampered='true' />")

    def resume_authority(_config: object, **kwargs: object) -> dict[str, str]:
        assert kwargs["verify_external_old_xml"] is False
        return {"authority_commit": value.authority_commit}

    monkeypatch.setattr(transition, "static_preflight", resume_authority)
    result, _terminal = transition.run_transition(
        value, ops, transition_id=f"resume-saved-{external_state}", resume=True
    )
    assert result == "ROLLED_BACK"
    assert ops.calls.count("task:Restore") == 1


@pytest.mark.parametrize("authority_failure", ["dirty receiver", "bad handoff", "wrong candidate"])
def test_resume_authority_failure_performs_zero_recovery_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, authority_failure: str
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    patch_flow(monkeypatch, value)
    evidence = transition.Evidence(
        value, "bad-resume-authority", resume=False, commands=["pytest authority"]
    )
    transition.write_prestate(
        evidence,
        value,
        task_snapshot(transition.task_expectation(value, old=True, enabled=True)),
        listing(),
    )
    evidence.checkpoint("TASK_DISABLE_ATTEMPTED")
    monkeypatch.setattr(
        transition,
        "static_preflight",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError(authority_failure)),
    )
    with pytest.raises(ValueError, match=authority_failure):
        transition.run_transition(
            value, ops, transition_id="bad-resume-authority", resume=True
        )
    assert not any(call.startswith("task:") for call in ops.calls)
    assert evidence.pointer.exists()


def test_tampered_prestate_is_rejected_before_residue_or_task_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    patch_flow(monkeypatch, value)
    evidence = transition.Evidence(
        value, "tampered-prestate", resume=False, commands=["pytest tamper"]
    )
    transition.write_prestate(
        evidence,
        value,
        task_snapshot(transition.task_expectation(value, old=True, enabled=True)),
        listing(),
    )
    evidence.checkpoint("TASK_DISABLE_ATTEMPTED")
    evidence.release_transition_guard()
    stale_lock = value.target / "catalog/.receiver.lock"
    stale_lock.write_text(json.dumps({"pid": 99999999, "nonce": "dead"}), encoding="utf-8")
    saved_xml = evidence.path / "pre-transition-live-task.xml"
    saved_xml.write_bytes(b"<Task attacker='true' />")
    manifest_path = evidence.path / "pre-transition-hashes.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["task_xml_sha256"] = contract.sha256_file(saved_xml)
    manifest_path.write_bytes(contract.canonical_json(manifest))
    with pytest.raises(ValueError, match="not bound"):
        transition.recover(value, ops, evidence)
    assert stale_lock.exists()
    assert not any(call.startswith("task:") for call in ops.calls)


def test_receiver_guard_can_be_reacquired_by_exact_resume_without_pid_binding(
    tmp_path: Path,
) -> None:
    value = config(tmp_path)
    evidence = transition.Evidence(
        value, "renewable-guard", resume=False, commands=["pytest guard"]
    )
    original_sha = evidence.owned_guard_sha256()
    assert "pid" not in json.loads(evidence.guard.read_text(encoding="utf-8"))
    evidence.release_transition_guard()
    resumed = transition.Evidence(value, "renewable-guard", resume=True)
    resumed.acquire_transition_guard()
    assert resumed.owned_guard_sha256() == original_sha


def test_recovery_rechecks_budget_after_delayed_source_before_pointer_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    patch_flow(monkeypatch, value)
    evidence = transition.Evidence(
        value, "delayed-recovery", resume=False, commands=["pytest delayed"]
    )
    transition.write_prestate(
        evidence,
        value,
        task_snapshot(transition.task_expectation(value, old=True, enabled=True)),
        listing(),
    )
    evidence.checkpoint("TASK_DISABLE_ATTEMPTED")
    evidence.checkpoint("FOREGROUND_STARTED")
    before = {
        name: (value.target / "catalog" / name).read_bytes()
        for name in contract.COMPONENT_POINTERS
    }
    times = iter([
        datetime.fromisoformat("2026-08-29T21:30:00+10:00"),
        datetime.fromisoformat("2026-08-29T21:59:00+10:00"),
        datetime.fromisoformat("2026-08-29T21:59:00+10:00"),
    ])
    monkeypatch.setattr(ops, "now", lambda: next(times))
    monkeypatch.setattr(transition, "recovery_gate", transition.recovery_gate)
    monkeypatch.setattr(contract, "validate_recovery_source_listing", lambda *_a, **_k: None)
    with pytest.raises(ValueError, match="insufficient time"):
        transition.recover(value, ops, evidence)
    for name, payload in before.items():
        assert (value.target / "catalog" / name).read_bytes() == payload
    assert not any(call.startswith("task:Restore") for call in ops.calls)


def test_resume_recovery_failure_is_not_retried_in_same_invocation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    patch_flow(monkeypatch, value)
    evidence = transition.Evidence(
        value, "single-recovery-attempt", resume=False, commands=["pytest once"]
    )
    transition.write_prestate(
        evidence,
        value,
        task_snapshot(transition.task_expectation(value, old=True, enabled=True)),
        listing(),
    )
    evidence.checkpoint("TASK_DISABLE_ATTEMPTED")
    ops.fail_action = "Restore"
    with pytest.raises(transition.RecoveryDeferred, match="remains incomplete"):
        transition.run_transition(
            value, ops, transition_id="single-recovery-attempt", resume=True
        )
    assert ops.calls.count("task:Restore") == 1
    assert json.loads(evidence.pointer.read_text(encoding="utf-8"))["state"] == "OPEN"

    retry_ops = FakeOps(value)
    patch_flow(monkeypatch, value)
    result, terminal = transition.run_transition(
        value, retry_ops, transition_id="single-recovery-attempt", resume=True
    )
    assert result == "ROLLED_BACK"
    payload = json.loads(terminal.read_text(encoding="utf-8"))
    assert len(payload["evidence"]["attempt_records"]) == 2
    assert payload["exact_commands"].count("task:Restore") == 2


def test_resume_rejects_deleted_attempt_chain_tail(tmp_path: Path) -> None:
    value = config(tmp_path)
    evidence = transition.Evidence(
        value, "attempt-tail-deletion", resume=False, commands=["pytest attempt anchor"]
    )
    tail = evidence.persist_attempt_log("RECOVERY_DEFERRED", ["task:Restore"])
    tail.unlink()

    with pytest.raises(ValueError, match="attempt chain does not match"):
        transition.Evidence(value, "attempt-tail-deletion", resume=True)


def test_resume_rejects_truncated_attempt_chain_tail(tmp_path: Path) -> None:
    value = config(tmp_path)
    evidence = transition.Evidence(
        value, "attempt-tail-truncation", resume=False, commands=["pytest attempt anchor"]
    )
    tail = evidence.persist_attempt_log("RECOVERY_DEFERRED", ["task:Restore"])
    tail.write_bytes(b"")

    with pytest.raises((ValueError, json.JSONDecodeError)):
        transition.Evidence(value, "attempt-tail-truncation", resume=True)


def test_resume_rolls_forward_one_valid_unanchored_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    evidence = transition.Evidence(
        value, "attempt-tail-roll-forward", resume=False, commands=["pytest attempt anchor"]
    )
    original_replace = receiver.atomic_replace
    crashed = False

    def fail_anchor_once(path: Path, payload: bytes) -> None:
        nonlocal crashed
        if path == evidence.pointer and b'"attempt_count":1' in payload and not crashed:
            crashed = True
            raise OSError("injected crash after durable attempt create")
        original_replace(path, payload)

    monkeypatch.setattr(receiver, "atomic_replace", fail_anchor_once)
    with pytest.raises(OSError, match="injected crash"):
        evidence.persist_attempt_log("RECOVERY_DEFERRED", ["task:Restore"])
    monkeypatch.setattr(receiver, "atomic_replace", original_replace)
    pointer_temporary = evidence.root / (
        ".ACTIVE_TRANSITION.json." + "a" * 32 + ".tmp"
    )
    second_pointer_temporary = evidence.root / (
        ".ACTIVE_TRANSITION.json." + "b" * 32 + ".tmp"
    )
    pointer_temporary.write_bytes(b"interrupted pointer payload")
    second_pointer_temporary.write_bytes(b"interrupted pointer payload")
    pointer_digest = contract.sha256_bytes(b"interrupted pointer payload")
    second_identity = contract.sha256_bytes(second_pointer_temporary.name.encode("utf-8"))
    second_destination = (
        evidence.path
        / "recovered-temporaries"
        / (
            f"attempt-anchor-{second_identity}-{pointer_digest}-"
            f"{second_pointer_temporary.name}.preserved"
        )
    )
    evidence.create(
        f"pointer-temporary-recovery/{second_identity}.json",
        contract.canonical_json({
            "source": str(second_pointer_temporary),
            "preserved": str(second_destination),
            "sha256": pointer_digest,
        }),
    )

    resumed = transition.Evidence(value, "attempt-tail-roll-forward", resume=True)
    active = json.loads(resumed.pointer.read_text(encoding="utf-8"))
    assert active["attempt_count"] == 1
    assert active["attempt_head_sha256"] == contract.sha256_file(
        resumed.path / "attempts/001.json"
    )
    commands, records = resumed.aggregate_attempt_logs()
    assert commands == ["task:Restore"]
    assert len(records) == 1
    assert not pointer_temporary.exists()
    assert not second_pointer_temporary.exists()
    adoption = json.loads(
        (resumed.path / "attempt-adoptions/001.json").read_text(encoding="utf-8")
    )
    assert adoption["attempt_sha256"] == active["attempt_head_sha256"]
    recovery_records = sorted((resumed.path / "pointer-temporary-recovery").glob("*.json"))
    assert len(recovery_records) == 2
    assert {
        json.loads(path.read_text(encoding="utf-8"))["sha256"]
        for path in recovery_records
    } == {pointer_digest}


def test_resume_rejects_multiple_unanchored_attempts(tmp_path: Path) -> None:
    value = config(tmp_path)
    evidence = transition.Evidence(
        value, "attempt-multiple-unanchored", resume=False, commands=["pytest attempt anchor"]
    )
    first = contract.canonical_json({
        "sequence": 1,
        "status": "RECOVERY_DEFERRED",
        "commands": ["task:Restore"],
        "error": None,
        "previous_sha256": None,
    })
    first_path = evidence.create("attempts/001.json", first)
    evidence.create("attempts/002.json", contract.canonical_json({
        "sequence": 2,
        "status": "RECOVERY_DEFERRED",
        "commands": ["task:Restore"],
        "error": None,
        "previous_sha256": contract.sha256_file(first_path),
    }))

    with pytest.raises(ValueError, match="attempt chain does not match"):
        transition.Evidence(value, "attempt-multiple-unanchored", resume=True)
