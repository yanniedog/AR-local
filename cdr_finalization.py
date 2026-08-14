"""Transactional observation finalization over export-contract and ledger v2."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Optional

from ar_local_pi_runtime import load_exports_manifest, manifest_banks_rate_count
from cdr_atomic import ImmutablePathError, atomic_write_json, canonical_json_bytes
from cdr_export_contract import artifact_records, build_contract, load_contract, write_contract
from cdr_ledger_v2 import (
    append_contract_event_locked,
    find_contract_event_locked,
    ledger_root,
    verify_event_artifacts,
)
from cdr_file_lock import FileLock


def _ingest_status(export_root: Path) -> dict[str, Any]:
    path = export_root / "ingest-status.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "total": 0,
            "incomplete": True,
            "corrupt_records": 0,
            "failure_provenance_complete": False,
        }
    if not isinstance(payload, dict):
        return {
            "total": 0,
            "incomplete": True,
            "corrupt_records": 1,
            "failure_provenance_complete": False,
        }
    return payload


def _coverage(
    export_root: Path,
) -> tuple[
    str,
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    manifest = load_exports_manifest(export_root)
    if manifest is None:
        raise ValueError("cannot finalize without dashboard-cache/latest.json")
    counts = manifest.get("banks_counts")
    counts = counts if isinstance(counts, Mapping) else {}
    status = _ingest_status(export_root)
    failures = int(status.get("total") or 0)
    corrupt = int(status.get("corrupt_records") or 0)
    unattributed = int(status.get("unattributed_records") or 0)
    provider_states = [
        dict(item)
        for item in (status.get("provider_states") or [])
        if isinstance(item, Mapping)
    ]
    register_attempts = [
        dict(item)
        for item in (status.get("register_attempts") or [])
        if isinstance(item, Mapping)
        and isinstance(item.get("sha256"), str)
        and len(str(item["sha256"])) == 64
    ]
    register_provenance_complete = (
        status.get("register_provenance_complete") is True
        and bool(register_attempts)
        and all(item.get("ok") is True for item in register_attempts)
    )
    registered = int(status.get("providers_registered") or 0)
    attempted = int(status.get("providers_attempted") or 0)
    providers_reconcile = (
        bool(provider_states)
        and attempted == len(provider_states)
        and registered == attempted
    )
    provenance_complete = (
        status.get("failure_provenance_complete") is True
        and providers_reconcile
        and register_provenance_complete
    )
    incomplete = (
        status.get("incomplete") is not False
        or failures > 0
        or corrupt > 0
        or not provenance_complete
        or any(item.get("state") in {"partial", "failed"} for item in provider_states)
    )
    observation_state = "partial" if incomplete or not provenance_complete else "complete"
    coverage = {
        "products_discovered": int(counts.get("products") or 0),
        "eligible_rate_rows": int(counts.get("rates") or 0),
        "fee_rows": int(counts.get("fees") or 0),
        "feature_rows": int(counts.get("features") or 0),
        "eligibility_rows": int(counts.get("eligibility") or 0),
        "constraint_rows": int(counts.get("constraints") or 0),
        "providers_registered": registered,
        "providers_attempted": attempted,
        "providers_complete": sum(item.get("state") == "complete" for item in provider_states),
        "providers_partial": sum(item.get("state") == "partial" for item in provider_states),
        "providers_failed": sum(item.get("state") == "failed" for item in provider_states),
        "failure_records": failures,
        "corrupt_failure_records": corrupt,
        "unattributed_failure_records": unattributed,
        "register_sources_attempted": len(register_attempts),
        "register_sources_complete": sum(
            item.get("ok") is True for item in register_attempts
        ),
        "register_provenance_complete": register_provenance_complete,
        "failure_provenance_complete": provenance_complete,
        "reconciliation_status": "partial" if observation_state == "partial" else "reconciled",
        "unavailable_populations": [
            "consumer_eligible_products",
            "priced_products",
            "rate_tiers_by_classification",
        ],
    }
    return observation_state, coverage, provider_states, register_attempts


def legacy_parent_generation_id(export_root: Path) -> str:
    material = artifact_records(export_root)
    digest = hashlib.sha256(canonical_json_bytes({"artifacts": material})).hexdigest()
    return f"legacy-export-{digest[:24]}"


def validate_finalization_layout(export_root: Path, state_dir: Path) -> str:
    """Reject non-portable export/state layouts before a live ingest begins."""

    relative = _portable_export_path(
        export_root.expanduser().resolve(), state_dir.expanduser().resolve()
    )
    if relative is None:
        raise ValueError("export root must be inside the portable data root")
    return relative


def finalize_observation(
    export_root: Path,
    state_dir: Path,
    marker_path: Path,
    *,
    observation_date: str,
    result: Mapping[str, Any],
    parent_generation_id: Optional[str] = None,
) -> dict[str, Any]:
    export_root = export_root.expanduser().resolve(strict=True)
    state_dir = state_dir.expanduser().resolve()
    marker_path = marker_path.expanduser().resolve()
    try:
        marker_relative = marker_path.relative_to(state_dir).as_posix()
    except ValueError as error:
        raise ValueError("completion marker must be inside the state root") from error
    observation_state, coverage, provider_states, register_hashes = _coverage(
        export_root
    )
    source_path = validate_finalization_layout(export_root, state_dir)
    artifacts = artifact_records(export_root)
    append_lock = ledger_root(state_dir) / ".append.lock"
    with FileLock(append_lock):
        candidate_contract = build_contract(
            export_root,
            observation_date=observation_date,
            observation_state=observation_state,
            source_path=source_path,
            completion_marker_path=marker_relative,
            coverage=coverage,
            provider_states=provider_states,
            register_hashes=register_hashes,
            prior_ledger_head=_current_head_digest(state_dir),
            artifacts=artifacts,
        )
        finalized = find_contract_event_locked(
            state_dir,
            observation_date,
            candidate_contract["source_generation_digest"],
            parent_generation_id,
        )
        if finalized is not None:
            contract_path, contract, event = finalized
        else:
            contract_path = (
                state_dir
                / "export-contracts-v2"
                / observation_date
                / f"{candidate_contract['generation_id']}.json"
            )
            if contract_path.is_file():
                contract = load_contract(contract_path)
                if (
                    contract["source_generation_digest"]
                    != candidate_contract["source_generation_digest"]
                ):
                    raise ValueError(
                        "generation id collision with different source semantics"
                    )
            else:
                contract = candidate_contract
                try:
                    contract_path = write_contract(state_dir, contract)
                except ImmutablePathError:
                    contract = load_contract(contract_path)
                    if (
                        contract["source_generation_digest"]
                        != candidate_contract["source_generation_digest"]
                    ):
                        raise ValueError(
                            "generation id collision with different source semantics"
                        )
            event = append_contract_event_locked(
                state_dir,
                contract_path,
                parent_generation_id=parent_generation_id,
            )
    completion = dict(result)
    completion.update(
        {
            "finalization_schema_version": 2,
            "generation_id": contract["generation_id"],
            "observation_state": observation_state,
            "ledger_state": "finalized",
            "export_contract_path": contract_path.relative_to(state_dir).as_posix(),
            "export_contract_digest": contract["contract_digest"],
            "ledger_event_digest": event["event_digest"],
        }
    )
    atomic_write_json(marker_path, completion, create_once=True)
    pointer = {
        "schema_version": 2,
        "observation_date": observation_date,
        "generation_id": contract["generation_id"],
        "observation_state": observation_state,
        "ledger_event_digest": event["event_digest"],
        "marker_path": marker_relative,
        "export_path": str(contract["source_path"]),
    }
    pointers = state_dir / "observation-pointers-v2"
    _advance_pointer(pointers / "latest-observation.json", pointer)
    if observation_state == "complete":
        _advance_pointer(pointers / "latest-complete.json", pointer)
    return completion


def repair_observation_pointers(
    marker: Mapping[str, Any],
    state_dir: Path,
    observation_date: str,
    marker_path: Path,
) -> bool:
    """Idempotently rebuild observation pointers from a verified marker."""

    state_dir = state_dir.expanduser().resolve()
    marker_path = marker_path.expanduser().resolve()
    try:
        marker_relative = marker_path.relative_to(state_dir).as_posix()
    except ValueError:
        return False
    if not verify_completion_marker(marker, state_dir, observation_date):
        return False
    contract_path = _safe_state_path(state_dir, marker.get("export_contract_path"))
    if contract_path is None:
        return False
    contract = load_contract(contract_path)
    if contract.get("completion_marker_path") != marker_relative:
        return False
    pointer = {
        "schema_version": 2,
        "observation_date": observation_date,
        "generation_id": contract["generation_id"],
        "observation_state": contract["observation_state"],
        "ledger_event_digest": marker["ledger_event_digest"],
        "marker_path": marker_relative,
        "export_path": contract["source_path"],
    }
    pointers = state_dir / "observation-pointers-v2"
    _advance_pointer(pointers / "latest-observation.json", pointer)
    if contract["observation_state"] == "complete":
        _advance_pointer(pointers / "latest-complete.json", pointer)
    return True


def verified_pointer_marker_for_date(
    state_dir: Path, observation_date: str
) -> Optional[Path]:
    """Return the exact verified marker selected for one observation date."""

    state_dir = state_dir.expanduser().resolve()
    pointer_path = state_dir / "observation-pointers-v2" / "latest-observation.json"
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(pointer, Mapping)
        or pointer.get("observation_date") != observation_date
    ):
        return None
    marker_path = _safe_state_path(state_dir, pointer.get("marker_path"))
    if marker_path is None:
        return None
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(marker, Mapping):
        return None
    return (
        marker_path
        if repair_observation_pointers(
            marker, state_dir, observation_date, marker_path
        )
        else None
    )


def recover_pending_finalization(
    state_dir: Path, observation_date: str
) -> Optional[Path]:
    """Finish a landed ledger event after a crash at head/marker/pointer steps."""

    state_dir = state_dir.expanduser().resolve()
    root = ledger_root(state_dir)
    if not (root / "events" / observation_date).is_dir():
        return None
    with FileLock(root / ".append.lock"):
        head_digest = _current_head_digest(state_dir)
        head_candidate: Optional[tuple[dict[str, Any], dict[str, Any], Path]] = None
        pending: list[tuple[dict[str, Any], dict[str, Any], Path]] = []
        for event_path in sorted((root / "events" / observation_date).glob("*.json")):
            event = json.loads(event_path.read_text(encoding="utf-8"))
            verify_event_artifacts(state_dir, event)
            contract_path = _safe_state_path(state_dir, event.get("contract_path"))
            if contract_path is None:
                raise ValueError("ledger event contract path escapes the state root")
            contract = load_contract(contract_path)
            item = (event, contract, contract_path)
            if event.get("event_digest") == head_digest:
                head_candidate = item
            elif event.get("previous_event_digest") == head_digest:
                pending.append(item)
        if len(pending) > 1:
            raise ValueError("multiple ledger events compete for the current head")
        selected = pending[0] if pending else head_candidate
        if selected is None:
            return None
        event, contract, contract_path = selected
        marker_path = _safe_state_path(
            state_dir, contract.get("completion_marker_path")
        )
        if marker_path is None:
            raise ValueError("contract completion marker path escapes the state root")
        event = append_contract_event_locked(
            state_dir,
            contract_path,
            parent_generation_id=event.get("parent_generation_id"),
        )
        try:
            existing_marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing_marker = None
        if isinstance(existing_marker, Mapping) and verify_completion_marker(
            existing_marker, state_dir, observation_date
        ):
            completion = dict(existing_marker)
        else:
            source_root = _source_root_for_contract(state_dir, contract)
            manifest = load_exports_manifest(source_root)
            if (
                manifest is None
                or str(manifest.get("run_date") or "") != observation_date
            ):
                raise ValueError(
                    "cannot reconstruct completion marker from export manifest"
                )
            completion = {
                "run_date": observation_date,
                "banks_counts": dict(manifest.get("banks_counts") or {}),
                "finalization_schema_version": 2,
                "generation_id": contract["generation_id"],
                "observation_state": contract["observation_state"],
                "ledger_state": "finalized",
                "export_contract_path": contract_path.relative_to(
                    state_dir
                ).as_posix(),
                "export_contract_digest": contract["contract_digest"],
                "ledger_event_digest": event["event_digest"],
            }
            atomic_write_json(marker_path, completion, create_once=True)
    return (
        marker_path
        if repair_observation_pointers(
            completion, state_dir, observation_date, marker_path
        )
        else None
    )


def _portable_export_path(export_root: Path, state_dir: Path) -> Optional[str]:
    try:
        return export_root.relative_to(state_dir.parent).as_posix()
    except ValueError:
        return None


def _safe_state_path(state_dir: Path, relative: Any) -> Optional[Path]:
    part = Path(str(relative or ""))
    if not str(relative or "") or part.is_absolute() or ".." in part.parts:
        return None
    candidate = (state_dir / part).resolve()
    try:
        candidate.relative_to(state_dir)
    except ValueError:
        return None
    return candidate


def _source_root_for_contract(
    state_dir: Path, contract: Mapping[str, Any]
) -> Path:
    data_root = state_dir.parent.resolve()
    candidate = (data_root / str(contract["source_path"])).resolve()
    try:
        candidate.relative_to(data_root)
    except ValueError as error:
        raise ValueError("contract source path escapes the data root") from error
    return candidate


def _advance_pointer(path: Path, incoming: Mapping[str, Any]) -> None:
    with FileLock(path.parent / ".pointer.lock"):
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = None
        if isinstance(current, Mapping):
            current_date = str(current.get("observation_date") or "")
            incoming_date = str(incoming.get("observation_date") or "")
            if current_date > incoming_date:
                return
            if (
                current_date == incoming_date
                and current.get("ledger_event_digest") == incoming.get("ledger_event_digest")
            ):
                return
        atomic_write_json(path, incoming)


def _current_head_digest(state_dir: Path) -> Optional[str]:
    path = ledger_root(state_dir) / "head.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return str(payload.get("event_digest") or "") or None


def verify_completion_marker(marker: Mapping[str, Any], state_dir: Path, date: str) -> bool:
    try:
        if marker.get("finalization_schema_version") != 2:
            return False
        if marker.get("ledger_state") != "finalized":
            return False
        if str(marker.get("run_date") or "") != date:
            return False
        if manifest_banks_rate_count(marker) <= 0:
            return False
        state_dir = state_dir.expanduser().resolve()
        contract_path = _safe_state_path(state_dir, marker.get("export_contract_path"))
        if contract_path is None:
            return False
        contract = load_contract(contract_path)
        if contract["generation_id"] != marker.get("generation_id"):
            return False
        if contract["observation_date"] != date:
            return False
        if contract["observation_state"] != marker.get("observation_state"):
            return False
        if contract["contract_digest"] != marker.get("export_contract_digest"):
            return False
        event_path = (
            ledger_root(state_dir)
            / "events"
            / date
            / f"{contract['generation_id']}.json"
        )
        event = json.loads(event_path.read_text(encoding="utf-8"))
        verify_event_artifacts(state_dir, event)
        return event["event_digest"] == marker.get("ledger_event_digest")
    except (KeyError, OSError, ValueError, json.JSONDecodeError):
        return False
