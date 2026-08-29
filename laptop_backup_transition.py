"""Controlled, crash-recoverable Windows laptop-backup task transition."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping, Protocol, Sequence
from zoneinfo import ZoneInfo

import laptop_backup_scheduled as scheduled
import laptop_backup_transition_contract as contract
from laptop_backup_transition_authority import (
    static_preflight as authority_static_preflight,
    validate_evidence_target,
)
from laptop_backup_transition_evidence import (
    Evidence,
    authenticate_saved,
    evidence_root,
    runtime_lease,
)
from laptop_backup_transition_windows import CommandOutput, WindowsOps
import laptop_pull_backup as receiver


HOBART = ZoneInfo("Australia/Hobart")
MUTATION_STAGES = {"TASK_DISABLE_ATTEMPTED", "FOREGROUND_STARTED", "INSTALL_ATTEMPTED"}
@dataclass(frozen=True)
class TransitionConfig:
    target: Path
    recovery_image: Path
    receiver: Path
    old_receiver: Path
    old_task_xml: Path
    candidate_code_sha: str
    old_candidate_code_sha: str
    protected_code_sha: str
    plan_git_commit: str
    plan_sha256: str
    authority_repo: Path
    authority_commit: str
    handoff_sha256: str
    expected_observation_date: str
    operator: str
    principal: str
    python_path: Path
    old_python_path: Path
    task_name: str
    deadline: datetime
    host: str
    accepted_old_xml_sha256: str

    def public_record(self) -> dict[str, object]:
        result = asdict(self)
        for key, value in tuple(result.items()):
            if isinstance(value, Path):
                result[key] = str(value)
            elif isinstance(value, datetime):
                result[key] = value.isoformat()
        return result


class TransitionOps(Protocol):
    def task(
        self,
        action: str,
        config: TransitionConfig,
        old_xml: Path | None = None,
        transition_id: str | None = None,
    ) -> Mapping[str, object]: ...
    def source_listing(self, config: TransitionConfig) -> Mapping[str, object]: ...
    def run_scheduled(
        self, config: TransitionConfig, *, check_only: bool, transition_id: str
    ) -> CommandOutput: ...
    def active_backup_processes(self) -> Sequence[Mapping[str, object]]: ...
    def installer_output(self) -> str: ...
    def command_log(self) -> Sequence[str]: ...
    def planned_commands(self, config: TransitionConfig, transition_id: str) -> Sequence[str]: ...
    def now(self) -> datetime: ...


class RecoveryDeferred(RuntimeError):
    """Recovery was deliberately deferred because D-006 makes mutation unsafe."""


def task_arguments(
    receiver_root: Path,
    python_path: Path,
    config: TransitionConfig,
    candidate_sha: str,
) -> str:
    values = (
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        f'"{receiver_root / "run_laptop_backup_task.ps1"}"',
        "-PythonPath",
        f'"{python_path}"',
        "-ScriptPath",
        f'"{receiver_root / "laptop_backup_scheduled.py"}"',
        "-Target",
        f'"{config.target}"',
        "-RecoveryImage",
        f'"{config.recovery_image}"',
        "-CandidateCodeSha",
        candidate_sha,
        "-ProtectedCodeSha",
        config.protected_code_sha,
        "-PlanGitCommit",
        config.plan_git_commit,
        "-Operator",
        f'"{config.operator}"',
    )
    return " ".join(values)


def task_expectation(config: TransitionConfig, *, old: bool, enabled: bool) -> contract.TaskExpectation:
    receiver_root = config.old_receiver if old else config.receiver
    python_path = config.old_python_path if old else config.python_path
    candidate = config.old_candidate_code_sha if old else config.candidate_code_sha
    system_root = Path(os.environ.get("SystemRoot", r"C:\WINDOWS"))
    return contract.TaskExpectation(
        executable=str(system_root / "System32/WindowsPowerShell/v1.0/powershell.exe"),
        arguments=task_arguments(receiver_root, python_path, config, candidate),
        working_directory=str(receiver_root),
        principal=config.principal.lower(),
        receiver_sha=candidate,
        enabled=enabled,
    )


partial_paths = contract.partial_paths


def write_prestate(
    evidence: Evidence,
    config: TransitionConfig,
    snapshot: Mapping[str, object],
    listing: Mapping[str, object],
) -> dict[str, object]:
    xml = contract.decode_task_xml(snapshot)
    evidence.create("pre-transition-live-task.xml", xml)
    evidence.create("pre-transition-task.json", contract.canonical_json(snapshot))
    evidence.create("pre-transition-source.json", contract.canonical_json(listing))
    evidence.create(
        "pre-transition-scheduled-inventory.json",
        contract.canonical_json(contract.scheduled_inventory(config.target)),
    )
    catalog = config.target / "catalog/generations.jsonl"
    evidence.create("pre-transition-generations.jsonl", catalog.read_bytes())
    saved: dict[str, str] = {}
    for name in contract.ALL_POINTERS:
        path = contract.safe_file(config.target, f"catalog/{name}")
        output = evidence.create(f"pre-transition-{name}", path.read_bytes())
        saved[name] = contract.sha256_file(output)
    manifest = {
        "task_xml_sha256": contract.sha256_bytes(xml),
        "task_json_sha256": contract.sha256_file(evidence.path / "pre-transition-task.json"),
        "source_json_sha256": contract.sha256_file(evidence.path / "pre-transition-source.json"),
        "scheduled_inventory_sha256": contract.sha256_file(
            evidence.path / "pre-transition-scheduled-inventory.json"
        ),
        "accepted_old_xml_path": str(config.old_task_xml),
        "accepted_old_xml_sha256": contract.sha256_file(config.old_task_xml),
        "catalog_prefix_sha256": contract.sha256_file(evidence.path / "pre-transition-generations.jsonl"),
        "pointers": saved,
    }
    evidence.create("pre-transition-hashes.json", contract.canonical_json(manifest))
    evidence.bind_prestate()
    return manifest


def validate_backup_state(
    config: TransitionConfig,
    listing: Mapping[str, object],
    *,
    candidate_sha: str,
    require_scheduled: bool,
    scheduled_candidates: Sequence[str] | None = None,
) -> dict[str, object]:
    latest = scheduled.latest_status(
        config.target,
        listing.get("latest_observation") if isinstance(listing.get("latest_observation"), Mapping) else None,
        candidate_sha=candidate_sha,
        protected_sha=config.protected_code_sha,
        plan_commit=config.plan_git_commit,
    )
    identities = listing.get("component_identities")
    retained = listing.get("retained_runs")
    if not isinstance(identities, Mapping) or not isinstance(retained, list):
        raise ValueError("Pi source identities are incomplete")
    control = scheduled.component_status(
        config.target, identities, "control",
        candidate_sha=candidate_sha,
        protected_sha=config.protected_code_sha,
        plan_commit=config.plan_git_commit,
    )
    macro = scheduled.component_status(
        config.target, identities, "macro",
        candidate_sha=candidate_sha,
        protected_sha=config.protected_code_sha,
        plan_commit=config.plan_git_commit,
    )
    inventory = scheduled.inventory_status(
        config.target, retained, identities,
        protected_sha=config.protected_code_sha,
        plan_commit=config.plan_git_commit,
    )
    for label, value in (("observation", latest), ("control", control), ("macro", macro), ("inventory", inventory)):
        if value.get("status") != "UP_TO_DATE":
            raise ValueError(f"{label} backup state is not verified current: {value.get('reason', 'unknown')}")
    receipt_paths = contract.validate_receipts(
        config.target,
        candidate_sha=candidate_sha,
        protected_sha=config.protected_code_sha,
        plan_commit=config.plan_git_commit,
        expected_date=config.expected_observation_date,
    )
    receiver.catalog_entries(config.target / "catalog/generations.jsonl")
    scheduled_record: dict[str, object] | None = None
    if require_scheduled:
        path = contract.scheduled_record_path(config.target)
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, Mapping) or value.get("action") not in {"BACKUP-LATEST", "NO_BACKUP_DATA_WRITE"}:
            raise ValueError("current scheduled record action is invalid")
        record_candidate = value.get("candidate_code_sha")
        allowed_candidates = set(scheduled_candidates or (candidate_sha,))
        if not isinstance(record_candidate, str) or record_candidate not in allowed_candidates:
            raise ValueError("current scheduled record candidate is not an authorised preserved candidate")
        contract.validate_execution_record(
            value,
            action=str(value["action"]),
            candidate_sha=record_candidate,
            protected_sha=config.protected_code_sha,
            plan_commit=config.plan_git_commit,
            plan_sha256=config.plan_sha256,
            operator=config.operator,
            expected_date=config.expected_observation_date,
        )
        scheduled_record = {"path": str(path), "sha256": contract.sha256_file(path)}
    return {
        "observation": latest,
        "control": control,
        "macro": macro,
        "inventory": inventory,
        "receipts": contract.receipt_evidence(receipt_paths),
        "scheduled_record": scheduled_record,
    }


def static_preflight(
    config: TransitionConfig,
    *,
    require_current_main: bool = True,
    verify_external_old_xml: bool = True,
    command_log: list[str] | None = None,
) -> dict[str, str]:
    return authority_static_preflight(
        config,
        executing_root=Path(__file__).resolve().parent,
        require_current_main=require_current_main,
        verify_external_old_xml=verify_external_old_xml,
        command_log=command_log,
    )


def runtime_preflight(
    config: TransitionConfig, ops: TransitionOps
) -> tuple[Mapping[str, object], Mapping[str, object], dict[str, object]]:
    if shutil.disk_usage(config.target).free < contract.FREE_FLOOR:
        raise ValueError("less than 50 GiB is free")
    if (config.target / "catalog/.receiver.lock").exists():
        raise ValueError("receiver lock exists")
    if partial_paths(config.target):
        raise ValueError("partial backup artifact exists")
    if any(contract.temporary_paths(config.target)):
        raise ValueError("temporary backup artifact exists")
    if ops.active_backup_processes():
        raise ValueError("backup helper or overlap is active")
    snapshot = ops.task("Snapshot", config)
    contract.validate_accepted_task_snapshot(
        snapshot,
        task_expectation(config, old=True, enabled=True),
        accepted_xml=config.old_task_xml.read_bytes(),
        accepted_sha256=config.accepted_old_xml_sha256,
    )
    listing = ops.source_listing(config)
    contract.validate_source_listing(
        listing,
        protected_sha=config.protected_code_sha,
        expected_observation_date=config.expected_observation_date,
        now=ops.now(),
    )
    contract.validate_deadline(ops.now(), config.deadline, timedelta(hours=2))
    old_state = validate_backup_state(
        config,
        listing,
        candidate_sha=config.old_candidate_code_sha,
        require_scheduled=True,
        scheduled_candidates=(config.old_candidate_code_sha, config.candidate_code_sha),
    )
    return snapshot, listing, old_state


def recovery_gate(
    config: TransitionConfig, ops: TransitionOps, evidence: Evidence
) -> Mapping[str, object]:
    contract.validate_recovery_window(ops.now())
    if ops.active_backup_processes():
        raise RecoveryDeferred("backup helper is active; recovery deferred")
    evidence.quarantine_atomic_temporaries(
        receiver_mutation_started="FOREGROUND_STARTED" in evidence.stages()
    )
    lock = config.target / "catalog/.receiver.lock"
    if lock.exists():
        raw = lock.read_bytes()
        value = json.loads(raw)
        is_transition_guard = (
            isinstance(value, Mapping)
            and value.get("kind") == "A3_TRANSITION_GUARD"
            and value.get("transition_id") == evidence.transition_id
            and value.get("evidence_root") == str(evidence.path.resolve())
        )
        if not is_transition_guard:
            pid = value.get("pid") if isinstance(value, Mapping) else None
            if (
                "FOREGROUND_STARTED" not in evidence.stages()
                or type(pid) is not int
                or contract.pid_alive(pid)
            ):
                raise RecoveryDeferred("receiver lock is not an authenticated stale foreground lock")
            digest = contract.sha256_bytes(raw)
            evidence.create_or_verify(f"stale-receiver-lock-{digest}.json", raw)
            lock.unlink()
            evidence.checkpoint("STALE_RECEIVER_LOCK_RECLAIMED", {"sha256": digest})
    quarantined: list[dict[str, str]] = []
    for raw_path in partial_paths(config.target):
        if "FOREGROUND_STARTED" not in evidence.stages():
            raise RecoveryDeferred("partial exists before an authorised foreground boundary")
        path = contract.require_descendant(Path(raw_path), config.target, "recovery partial")
        relative = path.relative_to(config.target.resolve(strict=True))
        if (
            not relative.parts
            or relative.parts[0] not in {"observations", "diagnostic-runs", "control", "macro"}
            or not path.name.startswith(".")
        ):
            raise RecoveryDeferred("partial path is not an authorised receiver generation artifact")
        digest = contract.sha256_file(path)
        destination = evidence.path / "recovered-partials" / f"{digest}-{path.name}.preserved"
        destination.parent.mkdir(exist_ok=True)
        if destination.exists():
            raise RecoveryDeferred("recovery partial quarantine collision")
        path.replace(destination)
        quarantined.append({"source": str(path), "preserved": str(destination), "sha256": digest})
    if quarantined:
        evidence.checkpoint("PARTIALS_QUARANTINED", {"files": quarantined})
    listing = ops.source_listing(config)
    contract.validate_recovery_source_listing(
        listing,
        protected_sha=config.protected_code_sha,
        now=ops.now(),
    )
    return listing
def validate_scheduled_result(
    config: TransitionConfig,
    action: str,
    *,
    output: str,
    previous_path: Path | None,
) -> tuple[Path, Mapping[str, object], Mapping[str, object]]:
    path = contract.scheduled_record_path(config.target)
    if previous_path is not None and path.resolve(strict=True) == previous_path.resolve(strict=True):
        raise ValueError("scheduled execution did not create a new immutable record")
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, Mapping):
        raise ValueError("scheduled execution record is not an object")
    contract.validate_execution_record(
        record,
        action=action,
        candidate_sha=config.candidate_code_sha,
        protected_sha=config.protected_code_sha,
        plan_commit=config.plan_git_commit,
        plan_sha256=config.plan_sha256,
        operator=config.operator,
        expected_date=config.expected_observation_date,
    )
    bound = contract.bind_execution_output(
        output,
        target=config.target,
        expected_action=action,
        record_path=path,
    )
    return path, record, bound
def scheduled_recovery_plan(
    config: TransitionConfig, evidence: Evidence
) -> tuple[bytes, Mapping[str, str], dict[str, object]]:
    """Authenticate the live scheduled pointer and its complete append set read-only."""
    baseline = json.loads(
        (evidence.path / "pre-transition-scheduled-inventory.json").read_text(encoding="utf-8")
    )
    if not isinstance(baseline, Mapping) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in baseline.items()
    ):
        raise ValueError("saved scheduled inventory is invalid")
    live_pointer = (config.target / "catalog/latest-scheduled.json").read_bytes()
    appended = contract.validate_scheduled_inventory(
        config.target, baseline, expected_new=None
    )
    contract.validate_preserved_scheduled_records(
        config.target,
        appended,
        candidate_shas=(config.old_candidate_code_sha, config.candidate_code_sha),
        protected_sha=config.protected_code_sha,
        plan_commit=config.plan_git_commit,
        plan_sha256=config.plan_sha256,
        operator=config.operator,
    )
    plan = contract.reconcile_scheduled_pointer(
        config.target,
        (evidence.path / "pre-transition-latest-scheduled.json").read_bytes(),
        live_pointer,
        appended,
        old_candidate_sha=config.old_candidate_code_sha,
        apply=False,
    )
    return live_pointer, appended, plan


def recover(config: TransitionConfig, ops: TransitionOps, evidence: Evidence) -> dict[str, object]:
    saved = authenticate_saved(evidence)
    if saved.get("task_xml_sha256") != config.accepted_old_xml_sha256:
        raise ValueError("saved task XML is not the immutable accepted rollback artifact")
    live_scheduled_pointer, appended_scheduled, scheduled_plan = scheduled_recovery_plan(
        config, evidence
    )
    listing = recovery_gate(config, ops, evidence)
    if scheduled_recovery_plan(config, evidence) != (
        live_scheduled_pointer,
        appended_scheduled,
        scheduled_plan,
    ):
        raise ValueError("scheduled execution state changed during recovery preflight")
    evidence.acquire_transition_guard()
    stages = evidence.stages()
    restored: list[str] = []
    snapshot: Mapping[str, object] | None = None
    contract.validate_recovery_window(ops.now(), timedelta(minutes=15))
    snapshot = ops.task(
        "RestoreDisabled", config, evidence.path / "pre-transition-live-task.xml"
    )
    contract.validate_task_snapshot(
        snapshot,
        task_expectation(config, old=True, enabled=False),
        last_result_zero=True,
    )
    restored.append("task")
    if ops.active_backup_processes():
        raise RecoveryDeferred(
            "backup helper remained active after restoring the disabled task"
        )
    if any(stage in {"FOREGROUND_STARTED", "INSTALL_ATTEMPTED"} for stage in stages):
        for name in contract.COMPONENT_POINTERS:
            contract.validate_recovery_window(ops.now(), timedelta(minutes=20))
            receiver.atomic_replace(
                config.target / "catalog" / name,
                (evidence.path / f"pre-transition-{name}").read_bytes(),
            )
            restored.append(name)
    contract.validate_recovery_window(ops.now(), timedelta(minutes=5))
    final_listing = ops.source_listing(config)
    contract.validate_recovery_source_listing(
        final_listing, protected_sha=config.protected_code_sha, now=ops.now()
    )
    contract.validate_recovery_window(ops.now(), timedelta(minutes=2))
    baseline = (evidence.path / "pre-transition-generations.jsonl").read_bytes()
    catalog_path = config.target / "catalog/generations.jsonl"
    current = catalog_path.read_bytes()
    if not current.startswith(baseline):
        raise ValueError("catalog prefix was not preserved during recovery")
    entries = receiver.catalog_entries(catalog_path)
    appended = entries[len(baseline.splitlines()):]
    contract.validate_preserved_catalog_entries(
        config.target,
        appended,
        candidate_sha=config.candidate_code_sha,
        protected_sha=config.protected_code_sha,
        plan_commit=config.plan_git_commit,
    )
    final_pointer, final_appended, final_plan = scheduled_recovery_plan(config, evidence)
    if (final_pointer, final_appended, final_plan) != (
        live_scheduled_pointer,
        appended_scheduled,
        scheduled_plan,
    ):
        raise ValueError("scheduled execution state changed before pointer reconciliation")
    scheduled_reconciliation = contract.reconcile_scheduled_pointer(
        config.target,
        (evidence.path / "pre-transition-latest-scheduled.json").read_bytes(),
        final_pointer,
        final_appended,
        old_candidate_sha=config.old_candidate_code_sha,
    )
    scheduled_path = contract.scheduled_record_path(config.target)
    receipt_paths = contract.validate_receipts(
        config.target,
        candidate_sha=config.old_candidate_code_sha,
        protected_sha=config.protected_code_sha,
        plan_commit=config.plan_git_commit,
        expected_date=config.expected_observation_date,
    )
    if "task" in restored:
        contract.validate_recovery_window(ops.now(), timedelta(minutes=1))
        snapshot = ops.task("Enable", config)
        contract.validate_accepted_task_snapshot(
            snapshot,
            task_expectation(config, old=True, enabled=True),
            accepted_xml=(evidence.path / "pre-transition-live-task.xml").read_bytes(),
            accepted_sha256=str(saved["task_xml_sha256"]),
        )
        post_enable_pointer, post_enable_appended, _ = scheduled_recovery_plan(
            config, evidence
        )
        post_enable_identity = contract.scheduled_pointer_identity(
            config.target, post_enable_pointer
        )
        if post_enable_appended != final_appended or post_enable_identity != {
            "record_path": scheduled_reconciliation["latest_record"],
            "record_sha256": scheduled_reconciliation["latest_record_sha256"],
            "result": scheduled_reconciliation["result"],
        }:
            raise RecoveryDeferred(
                "scheduled execution changed while restoring the old task; recovery deferred"
            )
    readback = evidence.persist_recovery_readback(snapshot, final_listing)
    old_state = {
        "receipts": contract.receipt_evidence(receipt_paths),
        "source_latest_observation": listing.get("latest_observation"),
        "source_component_identities": listing.get("component_identities"),
        "freshness": "MAY_BE_STALE_AFTER_CROSS_DAY_RECOVERY",
    }
    return {
        "restored": restored,
        "appended_catalog_entries": appended,
        "catalog_sha256": contract.sha256_file(catalog_path),
        "latest_scheduled_path": str(scheduled_path),
        "latest_scheduled_sha256": contract.sha256_file(scheduled_path),
        "appended_scheduled_records": appended_scheduled,
        "scheduled_reconciliation": scheduled_reconciliation,
        "old_candidate_state": old_state,
        "post_recovery_readback": readback,
        "hygiene": contract.validate_hygiene(
            config.target,
            ops.active_backup_processes(),
            allowed_receiver_guard_sha256=evidence.owned_guard_sha256(),
        ),
    }
def run_transition(
    config: TransitionConfig,
    ops: TransitionOps,
    *,
    transition_id: str | None = None,
    resume: bool = False,
) -> tuple[str, Path]:
    started_at = ops.now().isoformat()
    if transition_id is None:
        transition_id = datetime.now(HOBART).strftime("%Y%m%dT%H%M%S%z") + "-" + uuid.uuid4().hex
    validate_evidence_target(config)
    root = evidence_root(config)
    with runtime_lease(root, transition_id, resume=resume):
        main_command = subprocess.list2cmdline([sys.executable, *sys.argv])
        authority_commands: list[str] = []
        authorized_commands = [main_command, *ops.planned_commands(config, transition_id)]
        collected: dict[str, object] = {
            "authorized_commands": authorized_commands,
            "exact_commands": [],
        }
        preflight_error: Exception | None = None
        preflight_bundle: tuple[
            Mapping[str, object], Mapping[str, object], dict[str, object]
        ] | None = None
        if not resume:
            try:
                collected["authority"] = static_preflight(
                    config, command_log=authority_commands
                )
                preflight_bundle = runtime_preflight(config, ops)
            except Exception as exc:
                preflight_error = exc
        evidence = Evidence(
            config,
            transition_id,
            resume=resume,
            commands=None if resume else authorized_commands,
            guard_required=preflight_error is None,
        )
        if resume and evidence.closed_terminal is not None:
            evidence.release_transition_guard()
            return evidence.closed_terminal
        if resume:
            try:
                collected["authority"] = static_preflight(
                    config,
                    require_current_main=False,
                    verify_external_old_xml=False,
                    command_log=authority_commands,
                )
            except Exception as exc:
                commands = [main_command, *authority_commands, *ops.command_log()]
                evidence.persist_attempt_log("AUTHORITY_BLOCKED", commands, str(exc))
                raise
        mutated = False
        error: str | None = None
        if not resume:
            collected["input_hashes"] = evidence.persist_inputs(
                config, authorized_commands
            )
        try:
            if resume:
                prior_terminal = evidence.path / "transition-result.json"
                if prior_terminal.exists():
                    if prior_terminal.is_symlink():
                        raise ValueError("unsealed terminal result is linked")
                    digest = contract.sha256_file(prior_terminal)
                    quarantined = evidence.path / f"unsealed-transition-result-{digest}.json"
                    if quarantined.exists():
                        raise ValueError("unsealed terminal quarantine already exists")
                    prior_terminal.replace(quarantined)
                    evidence.checkpoint("UNSEALED_TERMINAL_QUARANTINED", {
                        "path": str(quarantined),
                        "sha256": digest,
                    })
                if (
                    not (evidence.path / "pre-transition-hashes.json").exists()
                    and not any(stage in MUTATION_STAGES for stage in evidence.stages())
                ):
                    evidence.release_transition_guard()
                    collected["recovery"] = {"restored": [], "reason": "NO_MUTATION_STARTED"}
                    result = "BLOCKED"
                else:
                    recovery = recover(config, ops, evidence)
                    collected["recovery"] = recovery
                    result = "ROLLED_BACK"
            else:
                if preflight_error is not None:
                    raise preflight_error
                if preflight_bundle is None:
                    raise RuntimeError("transition preflight did not produce a verified bundle")
                snapshot, listing, old_state = preflight_bundle
                collected["old_candidate_state"] = old_state
                collected["prestate"] = write_prestate(evidence, config, snapshot, listing)
                collected["prestate_manifest_sha256"] = evidence.bind_prestate()
                evidence.checkpoint("PREFLIGHT_PASS")

                contract.validate_deadline(ops.now(), config.deadline, timedelta(minutes=100))
                evidence.checkpoint("TASK_DISABLE_ATTEMPTED")
                mutated = True
                disabled = ops.task("Disable", config)
                contract.validate_task_snapshot(
                    disabled,
                    task_expectation(config, old=True, enabled=False),
                    last_result_zero=True,
                )
                evidence.checkpoint("TASK_DISABLED")
                evidence.release_transition_guard()
                evidence.checkpoint("TRANSITION_GUARD_RELEASED")

                contract.validate_deadline(ops.now(), config.deadline, timedelta(minutes=90))
                evidence.checkpoint("FOREGROUND_STARTED")
                try:
                    foreground = ops.run_scheduled(
                        config, check_only=False, transition_id=transition_id
                    )
                finally:
                    evidence.acquire_transition_guard()
                evidence.create("foreground.stdout.txt", foreground.stdout.encode())
                evidence.create("foreground.stderr.txt", foreground.stderr.encode())
                old_scheduled = contract.scheduled_record_path_from_pointer_bytes(
                    config.target,
                    (evidence.path / "pre-transition-latest-scheduled.json").read_bytes(),
                )
                foreground_path, foreground_record, foreground_output = validate_scheduled_result(
                    config,
                    "BACKUP-LATEST",
                    output=foreground.stdout,
                    previous_path=old_scheduled,
                )
                evidence.checkpoint("FOREGROUND_PASS", {"record": str(foreground_path)})
                receipts = contract.validate_receipts(
                    config.target,
                    candidate_sha=config.candidate_code_sha,
                    protected_sha=config.protected_code_sha,
                    plan_commit=config.plan_git_commit,
                    expected_date=config.expected_observation_date,
                )
                baseline = (evidence.path / "pre-transition-generations.jsonl").read_bytes()
                appended = contract.validate_catalog_delta(
                    baseline,
                    config.target / "catalog/generations.jsonl",
                    receipt_paths=receipts,
                )
                collected["foreground_record"] = {
                    "path": str(foreground_path),
                    "sha256": contract.sha256_file(foreground_path),
                    "record": foreground_record,
                    "command_result": foreground_output,
                }
                collected["receipts"] = contract.receipt_evidence(receipts)
                collected["appended_catalog_entries"] = list(appended)

                listing_after = ops.source_listing(config)
                contract.validate_source_listing(
                    listing_after,
                    protected_sha=config.protected_code_sha,
                    expected_observation_date=config.expected_observation_date,
                    now=ops.now(),
                )
                collected["post_foreground_state"] = validate_backup_state(
                    config,
                    listing_after,
                    candidate_sha=config.candidate_code_sha,
                    require_scheduled=True,
                )
                contract.validate_deadline(ops.now(), config.deadline, timedelta(minutes=20))
                evidence.checkpoint("INSTALL_ATTEMPTED")
                installed = ops.task("Install", config, transition_id=transition_id)
                contract.validate_task_snapshot(
                    installed,
                    task_expectation(config, old=False, enabled=True),
                    last_result_zero=True,
                )
                installer_output = ops.installer_output()
                evidence.create("installer.stdout.txt", installer_output.encode())
                installer_path, installer_record, installer_result = validate_scheduled_result(
                    config,
                    "NO_BACKUP_DATA_WRITE",
                    output=installer_output,
                    previous_path=foreground_path,
                )
                collected["installer_gate_record"] = {
                    "path": str(installer_path),
                    "sha256": contract.sha256_file(installer_path),
                    "record": installer_record,
                    "command_result": installer_result,
                }
                evidence.checkpoint("INSTALL_PASS")

                check = ops.run_scheduled(
                    config, check_only=True, transition_id=transition_id
                )
                evidence.create("check-only.stdout.txt", check.stdout.encode())
                evidence.create("check-only.stderr.txt", check.stderr.encode())
                check_path, check_record, check_output = validate_scheduled_result(
                    config,
                    "NO_BACKUP_DATA_WRITE",
                    output=check.stdout,
                    previous_path=installer_path,
                )
                evidence.checkpoint("CHECK_ONLY_PASS", {"record": str(check_path)})
                collected["check_only_record"] = {
                    "path": str(check_path),
                    "sha256": contract.sha256_file(check_path),
                    "record": check_record,
                    "command_result": check_output,
                }
                baseline_scheduled = json.loads(
                    (evidence.path / "pre-transition-scheduled-inventory.json").read_text(
                        encoding="utf-8"
                    )
                )
                if not isinstance(baseline_scheduled, Mapping):
                    raise ValueError("saved scheduled inventory is invalid")
                collected["scheduled_append_set"] = contract.validate_scheduled_inventory(
                    config.target,
                    baseline_scheduled,
                    expected_new=(foreground_path, installer_path, check_path),
                )
                contract.validate_receipts(
                    config.target,
                    candidate_sha=config.candidate_code_sha,
                    protected_sha=config.protected_code_sha,
                    plan_commit=config.plan_git_commit,
                    expected_date=config.expected_observation_date,
                )
                contract.validate_catalog_delta(
                    baseline,
                    config.target / "catalog/generations.jsonl",
                    receipt_paths=receipts,
                )
                listing_final = ops.source_listing(config)
                contract.validate_source_listing(
                    listing_final,
                    protected_sha=config.protected_code_sha,
                    expected_observation_date=config.expected_observation_date,
                    now=ops.now(),
                )
                collected["final_backup_state"] = validate_backup_state(
                    config,
                    listing_final,
                    candidate_sha=config.candidate_code_sha,
                    require_scheduled=True,
                )
                collected["hygiene"] = contract.validate_hygiene(
                    config.target,
                    ops.active_backup_processes(),
                    allowed_receiver_guard_sha256=evidence.owned_guard_sha256(),
                )
                final_task = ops.task("Snapshot", config)
                contract.validate_task_snapshot(
                    final_task,
                    task_expectation(config, old=False, enabled=True),
                    last_result_zero=True,
                )
                final_xml = contract.decode_task_xml(final_task)
                evidence.create("final-live-task.xml", final_xml)
                evidence.create("final-task.json", contract.canonical_json(final_task))
                evidence.create("final-source.json", contract.canonical_json(listing_final))
                collected["installed_task"] = {
                    "snapshot": final_task,
                    "xml_sha256": contract.sha256_bytes(final_xml),
                    "canonical_xml_sha256": contract.canonical_task_xml_sha256(final_xml),
                }
                collected["final_hashes"] = {
                    "catalog": contract.sha256_file(config.target / "catalog/generations.jsonl"),
                    "pointers": {
                        name: contract.sha256_file(config.target / "catalog" / name)
                        for name in contract.ALL_POINTERS
                    },
                    "source": contract.sha256_file(evidence.path / "final-source.json"),
                    "task": contract.sha256_file(evidence.path / "final-task.json"),
                }
                contract.validate_deadline(ops.now(), config.deadline, timedelta(0))
                result = "PASS"
        except RecoveryDeferred:
            commands = [main_command, *authority_commands, *ops.command_log()]
            evidence.persist_attempt_log("RECOVERY_DEFERRED", commands)
            evidence.checkpoint("RECOVERY_DEFERRED", {"reason": "D-006 or runtime safety gate"})
            raise
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            if resume:
                commands = [main_command, *authority_commands, *ops.command_log()]
                evidence.persist_attempt_log("RECOVERY_FAILED", commands, error)
                evidence.checkpoint("RECOVERY_FAILED", {"recovery_error": error})
                raise RecoveryDeferred(
                    f"authenticated recovery remains incomplete: {error}"
                ) from exc
            if mutated or any(stage in MUTATION_STAGES for stage in evidence.stages()):
                try:
                    collected["recovery"] = recover(config, ops, evidence)
                    result = "ROLLED_BACK"
                except RecoveryDeferred:
                    commands = [main_command, *authority_commands, *ops.command_log()]
                    evidence.persist_attempt_log("RECOVERY_DEFERRED", commands, error)
                    evidence.checkpoint("RECOVERY_DEFERRED", {"error": error})
                    raise
                except Exception as recovery_exc:
                    collected["recovery_error"] = f"{type(recovery_exc).__name__}: {recovery_exc}"
                    evidence.checkpoint("RECOVERY_FAILED", {
                        "transition_error": error,
                        "recovery_error": collected["recovery_error"],
                    })
                    commands = [main_command, *authority_commands, *ops.command_log()]
                    evidence.persist_attempt_log(
                        "RECOVERY_FAILED", commands, collected["recovery_error"]
                    )
                    raise RecoveryDeferred(
                        f"authenticated recovery remains incomplete: {collected['recovery_error']}"
                    ) from recovery_exc
            else:
                result = "BLOCKED"
        if result == "ROLLED_BACK":
            contract.validate_recovery_window(ops.now(), timedelta(minutes=1))
        commands = [main_command, *authority_commands, *ops.command_log()]
        evidence.persist_attempt_log(result, commands, error)
        collected["exact_commands"], collected["attempt_records"] = (
            evidence.aggregate_attempt_logs()
        )
        evidence.checkpoint("COMMAND_LOG", {"commands": collected["exact_commands"]})
        terminal = contract.terminal_payload(
            transition_id=transition_id,
            result=result,
            config=config.public_record(),
            evidence=collected,
            error=error,
            started_at=started_at,
            completed_at=ops.now().isoformat(),
        )
        terminal_path = evidence.close(terminal)
        return result, terminal_path
def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--target", type=Path, required=True)
    value.add_argument("--recovery-image", type=Path, required=True)
    value.add_argument("--receiver", type=Path, required=True)
    value.add_argument("--old-receiver", type=Path, required=True)
    value.add_argument("--old-task-xml", type=Path, required=True)
    value.add_argument("--candidate-code-sha", required=True)
    value.add_argument("--old-candidate-code-sha", required=True)
    value.add_argument("--protected-code-sha", required=True)
    value.add_argument("--plan-git-commit", required=True)
    value.add_argument("--plan-sha256", required=True)
    value.add_argument("--authority-repo", type=Path, required=True)
    value.add_argument("--authority-commit", required=True)
    value.add_argument("--handoff-sha256", required=True)
    value.add_argument("--expected-observation-date", required=True)
    value.add_argument("--operator", default="jkoka")
    value.add_argument("--principal", default=r"yanniedog\jkoka")
    value.add_argument("--python-path", type=Path, default=Path(sys.executable))
    value.add_argument("--old-python-path", type=Path, required=True)
    value.add_argument("--task-name", default="AR-local laptop backup")
    value.add_argument("--deadline", required=True)
    value.add_argument("--host", default="ar-local-pi5-lan")
    value.add_argument("--accepted-old-xml-sha256", required=True)
    value.add_argument("--resume-transition-id")
    return value
def config_from_args(args: argparse.Namespace) -> TransitionConfig:
    deadline = datetime.fromisoformat(args.deadline)
    return TransitionConfig(
        target=contract.lexical_absolute(args.target),
        recovery_image=contract.lexical_absolute(args.recovery_image),
        receiver=contract.lexical_absolute(args.receiver),
        old_receiver=contract.lexical_absolute(args.old_receiver),
        old_task_xml=contract.lexical_absolute(args.old_task_xml),
        candidate_code_sha=args.candidate_code_sha,
        old_candidate_code_sha=args.old_candidate_code_sha,
        protected_code_sha=args.protected_code_sha,
        plan_git_commit=args.plan_git_commit,
        plan_sha256=args.plan_sha256,
        authority_repo=contract.lexical_absolute(args.authority_repo),
        authority_commit=args.authority_commit,
        handoff_sha256=args.handoff_sha256,
        expected_observation_date=args.expected_observation_date,
        operator=args.operator,
        principal=args.principal,
        python_path=contract.lexical_absolute(args.python_path),
        old_python_path=contract.lexical_absolute(args.old_python_path),
        task_name=args.task_name,
        deadline=deadline,
        host=args.host,
        accepted_old_xml_sha256=args.accepted_old_xml_sha256,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    config = config_from_args(args)
    transition_id = args.resume_transition_id
    try:
        result, path = run_transition(
            config,
            WindowsOps(),
            transition_id=transition_id,
            resume=transition_id is not None,
        )
        print(json.dumps({"result": result, "transition_record": str(path)}, indent=2))
        return 0 if result == "PASS" else 1
    except Exception as exc:
        print(json.dumps({"result": "BLOCKED", "error": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
