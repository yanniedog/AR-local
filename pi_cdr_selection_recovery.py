"""Reconsider a retained finalized capture before spending another network attempt."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from cdr_atomic import atomic_write_json
from cdr_export_contract import load_contract
from cdr_finalization import repair_observation_pointers
from cdr_ledger_v2 import current_head_digest, verify_event
from cdr_observation_selection import safe_child, selected_observation


def _pending_head(state: Path, run_date: str, observation: dict) -> dict | None:
    head_path = state / "ledger-v2" / "head.json"
    if not head_path.is_file():
        return None
    if head_path.stat().st_size > 4096:
        raise ValueError("ledger head exceeds its metadata budget")
    head = json.loads(head_path.read_bytes())
    if (head.get("observation_date") != run_date
            or current_head_digest(state) == observation["event"]["event_digest"]):
        return None
    return head


def _reserve_publication(path: Path, previous: dict, head: dict) -> bool:
    reason = "reconsidering_finalized_observation"
    previous_digest = previous["event"]["event_digest"]
    if path.is_file():
        if path.stat().st_size > 64 * 1024:
            raise ValueError("publication reservation exceeds its metadata budget")
        pending = json.loads(path.read_bytes())
        retry = pending.get("selection_retry") or {}
        if pending.get("reason") != reason or retry.get("previous_event_digest") != previous_digest:
            return False  # An actual earlier upload must settle first.
    # An interrupted pre-selection reservation may re-enter while its old
    # pointer remains selected. After advancement it instead protects upload.
    atomic_write_json(path, {
        "reason": reason, "created_at": datetime.now(timezone.utc).isoformat(),
        "selection_retry": {"previous_event_digest": previous_digest,
                            "candidate_event_digest": head["event_digest"]},
    })
    return True


def reconsider_saved_selection(repo_root: Path, state: Path, run_date: str,
                               observation: dict) -> dict | None:
    if _pending_head(state, run_date, observation) is None:
        return None
    # Lazy imports avoid the wrapper/recovery cycle. Use the same lease as ingest
    # and backup; a finalized marker does not grant permission to race either.
    from pi_daily_sync import (DailyIngestLock, clear_payload_publication_pending,
                               payload_publication_pending_path)
    from pi_cdr_recovery import recovery_block_reason

    with DailyIngestLock(state / "daily-ingest.lock"):
        reason = recovery_block_reason(repo_root, include_ingest_lock=False)
        if reason:
            return {"status": reason, "capture_attempted": False}
        before = selected_observation(state, run_date)
        head = _pending_head(state, run_date, before) if before else None
        if head is None:
            return None
        event = json.loads(safe_child(state, f"ledger-v2/events/{run_date}/{head['generation_id']}.json").read_bytes())
        verify_event(state, event)
        if event["event_digest"] != head["event_digest"]:
            raise ValueError("saved candidate does not match the ledger head")
        contract = load_contract(safe_child(state, event["contract_path"]))
        marker_path = safe_child(state, contract["completion_marker_path"])
        marker = json.loads(marker_path.read_bytes())
        # Reserve publication before changing the pointer, including a crash
        # between pointer selection and the watchdog's publication step.
        if not _reserve_publication(payload_publication_pending_path(repo_root), before, head):
            return {"status": "pending_publication_must_settle", "capture_attempted": False}
        if not repair_observation_pointers(
            marker, state, run_date, marker_path, require_selection_evidence=True,
        ):
            raise ValueError("saved candidate completion evidence cannot be verified")
        after = selected_observation(state, run_date)
        if after and after["event"]["event_digest"] != before["event"]["event_digest"]:
            return {"status": "finalized_selection_recovered", "selection_advanced": True,
                    "selected_generation_id": after["contract"]["generation_id"],
                    "publication_required": True, "capture_attempted": False}
        clear_payload_publication_pending(repo_root)
    return None
