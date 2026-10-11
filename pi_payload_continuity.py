"""Recover orphaned finalized publication intent without recapturing past dates.

Only control metadata is inspected here. The ordinary publisher re-verifies all
source bytes before building/uploading, under the same production lock.
"""
from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app_payload_observation_gate import publication_allowed
from app_payload_source_verification import publication_source, reconciled_failure_statuses
from ar_local_operation_lock import production_lock
from ar_local_pi_runtime import data_runs_root, data_state_root
from cdr_atomic import atomic_write_json
from cdr_observation_selection import load_pointer_observation, safe_child
from pi_daily_sync import (mark_payload_publication_pending, payload_publication_pending_path,
                           read_payload_publication_pending)
from pi_payload_retry_policy import (payload_retry_window_reason, publication_retry_candidates,
                                     publication_source_key)
from pi_payload_freshness import MAX_CALENDAR_DAYS, _valid_date

RECONCILIATION_FILE = "app-payload-continuity.json"
MAX_DATES_PER_PASS = 7
SOURCE_RECHECK_HOURS = 6


def retained_pointer(repo_root: Path, day: str) -> tuple[dict | None, str]:
    """Respect historical selection decisions and reject unbound metadata."""
    state = data_state_root(repo_root)
    contract, exports = publication_source(state, day, data_runs_root(repo_root) / day / "_exports")
    allowed, reason = publication_allowed(contract)
    if not allowed:
        return None, reason
    marker = json.loads(safe_child(state, contract["completion_marker_path"]).read_bytes())
    pointer = {
        "schema_version": 2, "observation_date": day,
        "generation_id": contract["generation_id"],
        "observation_state": contract["observation_state"],
        "ledger_event_digest": marker["ledger_event_digest"],
        "marker_path": contract["completion_marker_path"], "export_path": contract["source_path"],
    }
    observed = load_pointer_observation(state, pointer)
    if observed["contract"] != contract or observed["export_root"] != exports.resolve():
        raise ValueError("historical source binding differs")
    if contract["observation_state"] == "partial" and not reconciled_failure_statuses(exports, contract):
        return None, "unverified_failure_accounting"
    return pointer, reason


def _records(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as stream:
        raw = stream.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("continuity record exceeds size limit")
    document = json.loads(raw)
    if document.get("schema_version") != 1 or not isinstance(document.get("dates"), dict):
        raise ValueError("invalid continuity record")
    for day, record in document["dates"].items():
        if not _valid_date(day) or not isinstance(record, dict):
            raise ValueError("invalid continuity date record")
        stamp = datetime.fromisoformat(record["checked_at"])
        if stamp.tzinfo is None:
            raise ValueError("continuity timestamp has no timezone")
    return document["dates"]


def _reconcile(repo_root: Path, dates: list[str], expected: str, now: datetime,
               dry_run: bool) -> dict:
    path = data_state_root(repo_root) / RECONCILIATION_FILE
    prior = _records(path)
    pending = read_payload_publication_pending(repo_root)
    queued_pointers = pending.get("queued_pointers", [])
    if (payload_publication_pending_path(repo_root).exists()
            and (not isinstance(pending.get("pointer"), dict) or not pending["pointer"]
                 or not isinstance(queued_pointers, list)
                 or not all(isinstance(item, dict) and item for item in queued_pointers))):
        return {"status": "deferred", "reason": "pending_publication_source_unreadable"}
    candidates = publication_retry_candidates(pending)
    pending_keys = {publication_source_key(item) for item in candidates}
    records, queued, inspected = {}, [], 0
    # Current-day publication stays ahead of historical repair. Old source gaps
    # receive a cooldown so they cannot starve later recoverable dates.
    for day in sorted(dates, key=lambda value: (value != expected, value)):
        record = prior.get(day)
        if record and record.get("source_key") in pending_keys:
            records[day] = record
            continue
        if record and now < datetime.fromisoformat(record["checked_at"]) + timedelta(hours=SOURCE_RECHECK_HOURS):
            records[day] = record
            continue
        if inspected >= MAX_DATES_PER_PASS:
            if record:
                records[day] = record
            continue
        inspected += 1
        record = {"checked_at": now.isoformat()}
        try:
            pointer, reason = retained_pointer(repo_root, day)
            record.update(status="source_unavailable", reason=reason)
            if pointer:
                key = publication_source_key({"pointer": pointer})
                record.update(status="publication_pending", source_key=key)
                if not dry_run and key not in pending_keys:
                    mark_payload_publication_pending(repo_root, "missing_public_date", pointer)
                if key not in pending_keys:
                    queued.append(day)
        except (OSError, ValueError, KeyError, TypeError) as error:
            record.update(status="source_unverified", reason=type(error).__name__)
        records[day] = record
    if not dry_run:
        atomic_write_json(path, {"schema_version": 1, "checked_at": now.isoformat(),
                                "missing_dates": dates, "dates": records})
    return {"status": "dry_run" if dry_run else "checked", "queued_dates": queued,
            "inspected_dates": inspected, "dates": records,
            "unchecked_dates": [day for day in dates if day not in records]}


def reconcile_missing_publication(repo_root: Path, publication: dict, expected: str,
                                  *, now_utc: datetime, dry_run: bool = False) -> dict:
    """Bound queue repair to verified index gaps, outside the ingest window."""
    if publication.get("dates_index_error") or not publication.get("dates_index_first_date"):
        return {"status": "deferred", "reason": "public_index_unavailable"}
    missing = publication.get("missing_dates", [])
    if (not _valid_date(expected) or not isinstance(missing, list)
            or len(missing) > MAX_CALENDAR_DAYS or not all(_valid_date(day) for day in missing)):
        return {"status": "deferred", "reason": "invalid_publication_dates"}
    dates = sorted({day for day in missing if day <= expected})
    if not dates:
        return {"status": "not_due"}
    if reason := payload_retry_window_reason(now_utc):
        return {"status": "deferred", "reason": reason}
    lock = data_state_root(repo_root) / "daily-ingest.lock"
    if lock.exists():
        return {"status": "deferred", "reason": "production_busy"}
    try:
        with nullcontext() if dry_run else production_lock(lock, "payload-continuity"):
            if reason := payload_retry_window_reason():
                return {"status": "deferred", "reason": reason}
            return _reconcile(repo_root, dates, expected, now_utc, dry_run)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as error:
        return {"status": "deferred", "reason": "continuity_state_unavailable", "error": type(error).__name__}
