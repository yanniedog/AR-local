"""Reconsider retained finalized captures before spending another network attempt."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import cdr_finalization as finalization
from cdr_atomic import atomic_write_json
from cdr_export_contract import load_contract
from cdr_finalization import repair_observation_pointers, verify_completion_marker
from cdr_ledger_v2 import current_head_digest, verify_event
from cdr_observation_selection import load_pointer_observation, safe_child, selected_observation

MAX_SAVED_EVENTS = 128
MAX_EVENT_BYTES = 64 * 1024
MAX_EVENT_SCAN_BYTES = 8 * 1024 * 1024
RESERVATION_REASON = "reconsidering_finalized_observation"


def _read_metadata(path: Path, limit: int) -> dict:
    if path.stat().st_size > limit:
        raise ValueError("saved selection metadata exceeds its size budget")
    with path.open("rb") as stream:
        body = stream.read(limit + 1)
    if len(body) > limit:
        raise ValueError("saved selection metadata exceeds its size budget")
    result = json.loads(body)
    if not isinstance(result, dict):
        raise ValueError("saved selection metadata must be an object")
    return result


def _pending_head(state: Path, run_date: str, observation: dict) -> dict | None:
    head_path = state / "ledger-v2" / "head.json"
    if not head_path.is_file():
        return None
    head = _read_metadata(head_path, 4096)
    if (head.get("observation_date") != run_date
            or current_head_digest(state) == observation["event"]["event_digest"]):
        return None
    return head


def _pending_events(state: Path, run_date: str, observation: dict, head: dict) -> list[dict]:
    """Require a bounded, verified chain back to the selected same-day event."""
    events, scanned = {}, 0
    for path in (state / "ledger-v2" / "events" / run_date).glob("*.json"):
        scanned += path.stat().st_size
        if len(events) >= MAX_SAVED_EVENTS or scanned > MAX_EVENT_SCAN_BYTES:
            raise ValueError("saved selection ledger scan exceeds its budget")
        event = _read_metadata(path, MAX_EVENT_BYTES)
        verify_event(state, event)
        digest = event["event_digest"]
        if event["observation_date"] != run_date or digest in events:
            raise ValueError("saved selection event identity is ambiguous")
        events[digest] = event
    cursor, selected = head["event_digest"], observation["event"]["event_digest"]
    if cursor not in events or events[cursor]["generation_id"] != head["generation_id"]:
        raise ValueError("saved candidate does not match the ledger head")
    pending, seen = [], set()
    while cursor != selected:
        if cursor not in events or cursor in seen:
            raise ValueError("saved selection ledger chain is incomplete")
        seen.add(cursor)
        pending.append(events[cursor])
        cursor = events[cursor].get("previous_event_digest")
    if selected not in events:
        raise ValueError("selected observation is absent from the ledger chain")
    return list(reversed(pending))


def _candidate(state: Path, run_date: str, event: dict) -> dict:
    contract = load_contract(safe_child(state, event["contract_path"]))
    marker_path = safe_child(state, contract["completion_marker_path"])
    marker = _read_metadata(marker_path, MAX_EVENT_BYTES)
    if (marker.get("generation_id") != event["generation_id"]
            or marker.get("ledger_event_digest") != event["event_digest"]
            or not verify_completion_marker(marker, state, run_date)):
        raise ValueError("saved candidate completion evidence cannot be verified")
    pointer = {
        "schema_version": 2, "observation_date": run_date,
        "generation_id": contract["generation_id"],
        "observation_state": contract["observation_state"],
        "ledger_event_digest": event["event_digest"],
        "marker_path": marker_path.relative_to(state.resolve()).as_posix(),
        "export_path": contract["source_path"],
    }
    return load_pointer_observation(state, pointer)


def _reserve_publication(path: Path, previous: dict, head: dict) -> dict | None:
    previous_digest = previous["event"]["event_digest"]
    if path.is_file():
        pending = _read_metadata(path, MAX_EVENT_BYTES)
        retry = pending.get("selection_retry") or {}
        if (pending.get("reason") != RESERVATION_REASON
                or retry.get("previous_event_digest") != previous_digest):
            return None  # An actual earlier upload must settle first.
        if not pending.get("pointer"):
            # Upgrade an interrupted v5 preparation using the verified current
            # selection; an unapproved candidate must not become an upload.
            pending = {**pending, "run_date": previous["pointer"]["observation_date"],
                       "pointer": previous["pointer"]}
            atomic_write_json(path, pending)
        return pending  # Preserve an interrupted, already-approved target.
    pending = {
        "reason": RESERVATION_REASON, "created_at": datetime.now(timezone.utc).isoformat(),
        "run_date": previous["pointer"]["observation_date"], "pointer": previous["pointer"],
        "selection_retry": {"previous_event_digest": previous_digest,
                            "candidate_event_digest": head["event_digest"], "phase": "prepared"},
    }
    atomic_write_json(path, pending)
    return pending


def _publish_target(path: Path, reservation: dict, candidate: dict) -> dict:
    if _read_metadata(path, MAX_EVENT_BYTES) != reservation:
        raise ValueError("saved selection publication reservation changed")
    pending = {**reservation, "run_date": candidate["pointer"]["observation_date"],
               "pointer": candidate["pointer"], "selection_retry": {
                   **reservation["selection_retry"], "phase": "approved",
                   "candidate_event_digest": candidate["event"]["event_digest"],
               }}
    atomic_write_json(path, pending)
    return pending


def _reconsider_events(state: Path, run_date: str, before: dict, events: list[dict],
                       pending_path: Path, reservation: dict) -> tuple[dict, dict]:
    best = before
    for event in events:
        candidate = _candidate(state, run_date, event)
        # Approve the unchanged selection policy before reserving a candidate as
        # an upload target. Thus a crash either side of pointer advancement has
        # a verified, eligible target; a refused candidate is never published.
        reason = finalization.same_day_selection_reason(state, best["pointer"], candidate["pointer"])
        if not reason:
            reservation = _publish_target(pending_path, reservation, candidate)
        if not repair_observation_pointers(
            candidate["marker"], state, run_date,
            safe_child(state, candidate["pointer"]["marker_path"]), require_selection_evidence=True,
        ):
            raise ValueError("saved candidate completion evidence cannot be verified")
        after = selected_observation(state, run_date)
        expected = best if reason else candidate
        if not after or after["event"]["event_digest"] != expected["event"]["event_digest"]:
            raise ValueError("saved selection changed after eligibility verification")
        best = after
    return best, reservation


def _legacy_selected_reservation(path: Path, observation: dict) -> dict | None:
    if not path.is_file():
        return None
    pending = _read_metadata(path, MAX_EVENT_BYTES)
    if (pending.get("reason") == RESERVATION_REASON and not pending.get("pointer")
            and (pending.get("selection_retry") or {}).get("candidate_event_digest")
            == observation["event"]["event_digest"]):
        return pending
    return None


def reconsider_saved_selection(repo_root: Path, state: Path, run_date: str,
                               observation: dict) -> dict | None:
    # Lazy imports avoid the wrapper/recovery cycle. Hold the same production
    # lease throughout chain verification, selection, and publication intent.
    from pi_daily_sync import (DailyIngestLock, clear_payload_publication_pending,
                               payload_publication_pending_path)
    from pi_cdr_recovery import recovery_block_reason

    pending_path = payload_publication_pending_path(repo_root)
    if (_pending_head(state, run_date, observation) is None
            and _legacy_selected_reservation(pending_path, observation) is None):
        return None
    with DailyIngestLock(state / "daily-ingest.lock"):
        reason = recovery_block_reason(repo_root, include_ingest_lock=False)
        if reason:
            return {"status": reason, "capture_attempted": False}
        before = selected_observation(state, run_date)
        legacy_pending = _legacy_selected_reservation(pending_path, before) if before else None
        if legacy_pending:
            if not verify_completion_marker(before["marker"], state, run_date):
                raise ValueError("selected publication evidence cannot be verified")
            _publish_target(pending_path, legacy_pending, before)
            return {"status": "pending_publication_must_settle", "publication_required": True,
                    "capture_attempted": False}
        head = _pending_head(state, run_date, before) if before else None
        if head is None:
            return None
        reservation = _reserve_publication(pending_path, before, head)
        if reservation is None:
            return {"status": "pending_publication_must_settle", "capture_attempted": False}
        events = _pending_events(state, run_date, before, head)
        after, reservation = _reconsider_events(state, run_date, before, events, pending_path, reservation)
        if after["event"]["event_digest"] != before["event"]["event_digest"]:
            return {"status": "finalized_selection_recovered", "selection_advanced": True,
                    "selected_generation_id": after["contract"]["generation_id"],
                    "publication_required": True, "capture_attempted": False}
        if _read_metadata(pending_path, MAX_EVENT_BYTES) != reservation:
            raise ValueError("saved selection publication reservation changed")
        clear_payload_publication_pending(repo_root)
    return None
