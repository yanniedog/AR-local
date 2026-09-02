"""Transactional observation finalization over export-contract and ledger v2."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Optional

from ar_local_pi_runtime import load_exports_manifest, manifest_banks_rate_count
from cdr_atomic import ImmutablePathError, atomic_write_json
from cdr_contracts import canonical_json_bytes
from cdr_export_contract import artifact_records, build_contract, load_contract, write_contract
from cdr_ledger_v2 import (
    append_contract_event_locked,
    current_head_digest,
    find_contract_event_locked,
    ledger_root,
    verify_event,
    verify_event_artifacts,
)
from cdr_file_lock import FileLock
from cdr_observation import validate_observation
from cdr_observation_db import verify_observation_database
from cdr_raw_attempt_journal import RawAttemptJournal


_PROJECTION_GROUPS = ("products", "rates", "items", "product_facts", "product_changes")


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
        raise ValueError("cannot finalize without a valid observation")
    if manifest.get("contract") == "observation-v1":
        return _observation_coverage(export_root)
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


def _read_canonical_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is unreadable") from error
    if not isinstance(value, dict) or raw != canonical_json_bytes(value):
        raise ValueError(f"{label} is not canonical")
    return value, raw


def _verified_promoted_journal(
    export_root: Path, status: Mapping[str, Any], expected_digest: str
) -> None:
    pointer = status.get("raw_attempt_journal")
    if not isinstance(pointer, Mapping):
        raise ValueError("promoted ingest evidence pointer is absent")
    relative = PurePosixPath(str(pointer.get("path") or ""))
    session = str(pointer.get("session_id") or "")
    if (
        pointer.get("verified") is not True
        or pointer.get("path_resolution") != "relative_to_finalized_export_root"
        or pointer.get("retention") != "hash_bound_finalized_artifact"
        or pointer.get("head_digest") != expected_digest
        or not session
        or relative.is_absolute()
        or "\\" in str(relative)
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.parts
        != ("attempt-evidence", "raw-attempt-journals-v1", session)
    ):
        raise ValueError("promoted ingest evidence pointer is invalid")
    journal_root = export_root.joinpath(*relative.parts)
    summary = RawAttemptJournal(journal_root.parent, session).summary(recover=False)
    for field in ("schema_version", "session_id", "attempts", "head_digest", "verified"):
        if pointer.get(field) != summary.get(field):
            raise ValueError("promoted ingest journal does not match its pointer")
    manifest_relative = PurePosixPath(str(pointer.get("promotion_manifest_path") or ""))
    if (
        manifest_relative.is_absolute()
        or "\\" in str(manifest_relative)
        or any(part in {"", ".", ".."} for part in manifest_relative.parts)
        or manifest_relative.parent != relative
    ):
        raise ValueError("promoted ingest manifest path is invalid")
    manifest = export_root.joinpath(*manifest_relative.parts)
    try:
        digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    except OSError as error:
        raise ValueError("promoted ingest manifest is unreadable") from error
    if digest != pointer.get("promotion_manifest_sha256"):
        raise ValueError("promoted ingest manifest digest does not match")


def _observation_coverage(
    export_root: Path,
) -> tuple[str, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    observation, _ = _read_canonical_object(
        export_root / "observation-v1.json", "observation"
    )
    accounting, accounting_bytes = _read_canonical_object(
        export_root / "product-accounting-v1.json", "product accounting"
    )
    validate_observation(observation, accounting)
    projections = {group: observation[group] for group in _PROJECTION_GROUPS}
    verify_observation_database(
        export_root / "local-cdr.sqlite",
        expected_sidecar_bytes=accounting_bytes,
        expected_projections=projections,
        expected_normalization_version=observation["normalization_version"],
        expected_generated_at=observation["observed_at"],
    )
    status = _ingest_status(export_root)
    _verified_promoted_journal(
        export_root, status, accounting["raw_attempt_journal_digest"]
    )
    register_attempts = [
        dict(item)
        for item in (status.get("register_attempts") or [])
        if isinstance(item, Mapping)
        and isinstance(item.get("sha256"), str)
        and len(str(item["sha256"])) == 64
    ]
    register_complete = (
        status.get("register_provenance_complete") is True
        and bool(register_attempts)
        and all(item.get("ok") is True for item in register_attempts)
    )
    provider_states = [
        {
            "provider_uid": provider["provider_uid"],
            "state": provider["state"],
            "failure_records": provider["issue_count"],
        }
        for provider in accounting["providers"]
    ]
    provider_summary = accounting["summary"]["providers"]
    status_states = {
        str(item.get("provider_uid") or ""): item
        for item in (status.get("provider_states") or [])
        if isinstance(item, Mapping)
    }
    providers_reconcile = (
        status.get("providers_registered") == provider_summary["registered"]
        and status.get("providers_attempted") == provider_summary["attempted"]
        and set(status_states) == {item["provider_uid"] for item in provider_states}
        and all(
            status_states[item["provider_uid"]].get("state") == item["state"]
            for item in provider_states
        )
    )
    provenance_complete = (
        status.get("failure_provenance_complete") is True
        and status.get("coverage_evidence_complete") is True
        and register_complete
        and providers_reconcile
    )
    if not provenance_complete:
        raise ValueError("promoted ingest provenance is incomplete")
    products = accounting["summary"]["products"]
    issues = accounting["summary"]["issues"]
    rows = observation["row_counts"]
    item_counts = {
        group: sum(item["item_group"] == group for item in observation["items"])
        for group in ("fees", "features", "eligibility", "constraints")
    }
    coverage = {
        "products_discovered": products["discovered"],
        "products_published": products["consumer_visible"],
        "products_omitted": products["omitted_valid"],
        "products_quarantined": products["quarantined_invalid"],
        "eligible_rate_rows": rows["rates"],
        "fee_rows": item_counts["fees"],
        "feature_rows": item_counts["features"],
        "eligibility_rows": item_counts["eligibility"],
        "constraint_rows": item_counts["constraints"],
        "providers_registered": provider_summary["registered"],
        "providers_attempted": provider_summary["attempted"],
        "providers_complete": provider_summary["complete"],
        "providers_partial": provider_summary["partial"],
        "providers_failed": provider_summary["failed"],
        "failure_records": int(status.get("total") or 0),
        "corrupt_failure_records": issues["corrupt"],
        "unattributed_failure_records": issues["unattributed"],
        "register_sources_attempted": len(register_attempts),
        "register_sources_complete": len(register_attempts),
        "register_provenance_complete": True,
        "failure_provenance_complete": True,
        "reconciliation_status": "reconciled",
        "unavailable_populations": [],
    }
    state = "complete" if observation["state"] == "complete" else "partial"
    return state, coverage, provider_states, register_attempts


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
    manifest = load_exports_manifest(export_root)
    if manifest is None:
        raise ValueError("cannot finalize without a valid observation")
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
            observed_at=manifest.get("observed_at"),
            normalization_version=str(
                manifest.get("normalization_version") or "legacy-v1"
            ),
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
    _advance_pointer(pointers / "latest-observation.json", pointer, state_dir)
    if observation_state == "complete":
        _advance_pointer(pointers / "latest-complete.json", pointer, state_dir)
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
    _advance_pointer(pointers / "latest-observation.json", pointer, state_dir)
    if contract["observation_state"] == "complete":
        _advance_pointer(pointers / "latest-complete.json", pointer, state_dir)
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
    """Recover the unique global event chain, returning this date's marker."""

    state_dir = state_dir.expanduser().resolve()
    root = ledger_root(state_dir)
    if not (root / "events").is_dir():
        if (root / "head.json").is_file():
            if _current_head_digest(state_dir) is not None:
                raise ValueError("ledger head references a missing events directory")
        return None
    requested_marker: Optional[Path] = None
    with FileLock(root / ".append.lock"):
        while True:
            head_digest = _current_head_digest(state_dir)
            head_candidate, pending = _recovery_candidates(
                state_dir, root, head_digest
            )
            if head_digest is not None and head_candidate is None:
                raise ValueError("ledger head references a missing event")
            if len(pending) > 1:
                raise ValueError("multiple ledger events compete for the current head")
            if head_candidate is None and not pending:
                break
            # Repair the current head before advancing its successor.  A crash
            # after the next head write must not strand this observation's
            # complete pointer permanently behind the new head.
            selected = head_candidate or pending[0]
            completion, marker_path = _finish_recovery(
                state_dir, *selected, head_digest
            )
            event_date = str(selected[0]["observation_date"])
            if not repair_observation_pointers(
                completion, state_dir, event_date, marker_path
            ):
                raise ValueError("cannot repair recovered observation pointers")
            if event_date == observation_date:
                requested_marker = marker_path
            if not pending:
                break
            if head_candidate is None:
                continue

            event, contract, contract_path = pending[0]
            completion, marker_path = _finish_recovery(
                state_dir, event, contract, contract_path, head_digest
            )
            event_date = str(event["observation_date"])
            if not repair_observation_pointers(
                completion, state_dir, event_date, marker_path
            ):
                raise ValueError("cannot repair recovered observation pointers")
            if event_date == observation_date:
                requested_marker = marker_path
    return requested_marker


def _recovery_candidates(
    state_dir: Path, root: Path, head_digest: Optional[str]
) -> tuple[
    Optional[tuple[dict[str, Any], dict[str, Any], Path]],
    list[tuple[dict[str, Any], dict[str, Any], Path]],
]:
    head_candidates = []
    pending = []
    for event_path in sorted((root / "events").glob("*/*.json")):
        event = json.loads(event_path.read_text(encoding="utf-8"))
        if not isinstance(event, Mapping):
            raise ValueError(f"ledger event must be an object: {event_path}")
        is_head = event.get("event_digest") == head_digest
        is_pending = event.get("previous_event_digest") == head_digest
        if not is_head and not is_pending:
            continue
        verify_event_artifacts(state_dir, event)
        contract_path = _safe_state_path(state_dir, event.get("contract_path"))
        if contract_path is None:
            raise ValueError("ledger event contract path escapes the state root")
        item = (dict(event), load_contract(contract_path), contract_path)
        (head_candidates if is_head else pending).append(item)
    if len(head_candidates) > 1:
        raise ValueError("multiple ledger events claim the current head")
    return (head_candidates[0] if head_candidates else None), pending


def _finish_recovery(
    state_dir: Path,
    event: dict[str, Any],
    contract: dict[str, Any],
    contract_path: Path,
    head_digest: Optional[str],
) -> tuple[dict[str, Any], Path]:
    marker_path = _safe_state_path(state_dir, contract.get("completion_marker_path"))
    if marker_path is None:
        raise ValueError("contract completion marker path escapes the state root")
    if event.get("event_digest") != head_digest:
        event = append_contract_event_locked(
            state_dir,
            contract_path,
            parent_generation_id=event.get("parent_generation_id"),
        )
        if _current_head_digest(state_dir) != event.get("event_digest"):
            raise ValueError("pending ledger event did not advance the head")
    event_date = str(event["observation_date"])
    try:
        existing_marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        existing_marker = None
    if isinstance(existing_marker, Mapping) and verify_completion_marker(
        existing_marker, state_dir, event_date
    ):
        return dict(existing_marker), marker_path
    source_root = _source_root_for_contract(state_dir, contract)
    manifest = load_exports_manifest(source_root)
    if manifest is None or str(manifest.get("run_date") or "") != event_date:
        raise ValueError("cannot reconstruct completion marker from export manifest")
    completion = {
        "run_date": event_date,
        "banks_counts": dict(manifest.get("banks_counts") or {}),
        "finalization_schema_version": 2,
        "generation_id": contract["generation_id"],
        "observation_state": contract["observation_state"],
        "ledger_state": "finalized",
        "export_contract_path": contract_path.relative_to(state_dir).as_posix(),
        "export_contract_digest": contract["contract_digest"],
        "ledger_event_digest": event["event_digest"],
    }
    atomic_write_json(marker_path, completion, create_once=True)
    return completion, marker_path


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


def _ledger_precedence(
    state_dir: Path, current_digest: str, incoming_digest: str
) -> Optional[int]:
    """Return 1 when incoming is newer, -1 when older, 0 when equal."""

    if current_digest == incoming_digest:
        return 0
    events: dict[str, Optional[str]] = {}
    for event_path in sorted((ledger_root(state_dir) / "events").glob("*/*.json")):
        try:
            event = json.loads(event_path.read_text(encoding="utf-8"))
            verify_event(state_dir, event)
        except (KeyError, OSError, ValueError, json.JSONDecodeError):
            continue
        events[str(event["event_digest"])] = event.get("previous_event_digest")
    if incoming_digest not in events:
        return None
    if current_digest not in events:
        return 1

    cursor: Optional[str] = incoming_digest
    seen: set[str] = set()
    while cursor is not None and cursor not in seen:
        if cursor == current_digest:
            return 1
        seen.add(cursor)
        cursor = events.get(cursor)

    cursor = current_digest
    seen.clear()
    while cursor is not None and cursor not in seen:
        if cursor == incoming_digest:
            return -1
        seen.add(cursor)
        cursor = events.get(cursor)
    return None


def _advance_pointer(
    path: Path, incoming: Mapping[str, Any], state_dir: Path
) -> None:
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
            if current_date == incoming_date:
                precedence = _ledger_precedence(
                    state_dir,
                    str(current.get("ledger_event_digest") or ""),
                    str(incoming.get("ledger_event_digest") or ""),
                )
                if precedence != 1:
                    return
        atomic_write_json(path, incoming)


def _current_head_digest(state_dir: Path) -> Optional[str]:
    return current_head_digest(state_dir)


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
