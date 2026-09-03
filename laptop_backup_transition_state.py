"""Authenticated backup-state checks used by the controlled task transition."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Protocol, Sequence

import laptop_backup_scheduled as scheduled
import laptop_backup_transition_contract as contract
import laptop_pull_backup as receiver


class BackupConfig(Protocol):
    target: Path
    candidate_code_sha: str
    old_candidate_code_sha: str
    protected_code_sha: str
    plan_git_commit: str
    plan_sha256: str
    expected_observation_date: str
    operator: str


def component_states(
    config: BackupConfig,
    listing: Mapping[str, object],
    *,
    candidate_sha: str,
) -> dict[str, object]:
    identities = listing.get("component_identities")
    retained = listing.get("retained_runs")
    if not isinstance(identities, Mapping) or not isinstance(retained, list):
        raise ValueError("Pi source identities are incomplete")
    return {
        "observation": scheduled.latest_status(
            config.target,
            listing.get("latest_observation")
            if isinstance(listing.get("latest_observation"), Mapping)
            else None,
            candidate_sha=candidate_sha,
            protected_sha=config.protected_code_sha,
            plan_commit=config.plan_git_commit,
        ),
        "control": scheduled.component_status(
            config.target,
            identities,
            "control",
            candidate_sha=candidate_sha,
            protected_sha=config.protected_code_sha,
            plan_commit=config.plan_git_commit,
        ),
        "macro": scheduled.component_status(
            config.target,
            identities,
            "macro",
            candidate_sha=candidate_sha,
            protected_sha=config.protected_code_sha,
            plan_commit=config.plan_git_commit,
        ),
        "inventory": scheduled.inventory_status(
            config.target,
            retained,
            identities,
            protected_sha=config.protected_code_sha,
            plan_commit=config.plan_git_commit,
        ),
    }


def validate_backup_state(
    config: BackupConfig,
    listing: Mapping[str, object],
    *,
    candidate_sha: str,
) -> dict[str, object]:
    components = component_states(config, listing, candidate_sha=candidate_sha)
    for label, value in components.items():
        if value.get("status") != "UP_TO_DATE":
            reason = value.get("reason", "unknown")
            raise ValueError(f"{label} backup state is not verified current: {reason}")
    receipt_paths = contract.validate_receipts(
        config.target,
        candidate_sha=candidate_sha,
        protected_sha=config.protected_code_sha,
        plan_commit=config.plan_git_commit,
        expected_date=config.expected_observation_date,
    )
    receiver.catalog_entries(config.target / "catalog/generations.jsonl")
    path = contract.scheduled_record_path(config.target)
    value = json.loads(path.read_text(encoding="utf-8"))
    action = value.get("action") if isinstance(value, Mapping) else None
    if not isinstance(value, Mapping) or action not in {
        "BACKUP-LATEST",
        "BACKFILL",
        "NO_BACKUP_DATA_WRITE",
    }:
        raise ValueError("current scheduled record action is invalid")
    contract.validate_execution_record(
        value,
        action=str(action),
        candidate_sha=candidate_sha,
        protected_sha=config.protected_code_sha,
        plan_commit=config.plan_git_commit,
        plan_sha256=config.plan_sha256,
        operator=config.operator,
        expected_date=config.expected_observation_date,
    )
    return {
        "status": "UP_TO_DATE",
        **components,
        "receipts": contract.receipt_evidence(receipt_paths),
        "scheduled_record": {"path": str(path), "sha256": contract.sha256_file(path)},
    }


def _record_observation_date(record: Mapping[str, object]) -> str:
    detail = record.get("detail")
    action = record.get("action")
    if not isinstance(detail, Mapping):
        raise ValueError("current scheduled record detail is invalid")
    state = detail.get("after") if action in {"BACKUP-LATEST", "BACKFILL"} else detail
    observation = state.get("observation") if isinstance(state, Mapping) else None
    observed = observation.get("observation_date") if isinstance(observation, Mapping) else None
    if not isinstance(observed, str) or not receiver.DATE_RE.fullmatch(observed):
        raise ValueError("current scheduled record observation date is invalid")
    return observed


def validate_pretransition_backup_state(
    config: BackupConfig, listing: Mapping[str, object]
) -> dict[str, object]:
    """Authenticate the legacy baseline and calculate the exact required write set."""
    components = component_states(
        config, listing, candidate_sha=config.old_candidate_code_sha
    )
    receipt_paths: dict[str, str] = {}
    for kind, pointer in (
        ("observation", "latest-verified.json"),
        ("control", "latest-control.json"),
        ("macro", "latest-macro.json"),
    ):
        receipt, _manifest, _entry, path = scheduled.pointer_generation(
            config.target,
            pointer,
            kind,
            candidate_sha=config.old_candidate_code_sha,
            protected_sha=config.protected_code_sha,
            plan_commit=config.plan_git_commit,
        )
        if not scheduled.has_component_restore_evidence(receipt.get("checks"), kind):
            raise ValueError(f"legacy {kind} receipt restore evidence is invalid")
        receipt_paths[kind] = str(path)
    receiver.catalog_entries(config.target / "catalog/generations.jsonl")

    pointer_bytes = (config.target / "catalog/latest-scheduled.json").read_bytes()
    contract.scheduled_pointer_identity(config.target, pointer_bytes)
    record_path = contract.scheduled_record_path_from_pointer_bytes(
        config.target, pointer_bytes
    )
    record = json.loads(record_path.read_text(encoding="utf-8"))
    action = record.get("action") if isinstance(record, Mapping) else None
    if (
        not isinstance(record, Mapping)
        or record.get("candidate_code_sha") != config.old_candidate_code_sha
        or action not in {"BACKUP-LATEST", "BACKFILL", "NO_BACKUP_DATA_WRITE"}
    ):
        raise ValueError("current scheduled predecessor is invalid")
    contract.validate_execution_record(
        record,
        action=str(action),
        candidate_sha=config.old_candidate_code_sha,
        protected_sha=config.protected_code_sha,
        plan_commit=str(record.get("plan_git_commit") or ""),
        plan_sha256=str(record.get("plan_sha256") or ""),
        operator=config.operator,
        expected_date=_record_observation_date(record),
        allow_legacy_plan=True,
    )

    status = (
        "UP_TO_DATE"
        if all(value.get("status") == "UP_TO_DATE" for value in components.values())
        else "STALE"
    )
    command, backfill_dates = scheduled.select_backup_request(
        components["observation"], components["inventory"]
    )
    retained = listing.get("retained_runs")
    if not isinstance(retained, list):
        raise ValueError("Pi retained-run inventory is invalid")
    expected_jobs: Sequence[tuple[str, str | None]] = ()
    if status == "STALE":
        _latest, expected_jobs = receiver.backup_jobs(
            retained,
            command,
            "2026-05-21",
            backfill_dates,
            components["inventory"].get("stale_diagnostics", []),
        )
    return {
        "status": status,
        "required_action": (
            "NO_BACKUP_DATA_WRITE" if status == "UP_TO_DATE" else command.upper()
        ),
        "expected_jobs": list(expected_jobs),
        "backfill_dates": list(backfill_dates),
        **components,
        "receipts": contract.receipt_evidence(receipt_paths),
        "scheduled_record": {
            "path": str(record_path),
            "sha256": contract.sha256_file(record_path),
        },
    }
