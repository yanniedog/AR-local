"""Read-only migration of legacy failure evidence into the daytime probe queue."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cdr_atomic import atomic_write_json
from cdr_compatibility import response_shape_error
from cdr_ingest_support import DATASET_TO_FOLDER, detail_inner_record, has_cdr_errors, infer_cdr_dataset
from cdr_observation_selection import captured_identities, read_bound_bytes, safe_child

MAX_LEGACY_EVENTS = 20000
MAX_LEGACY_METADATA_BYTES = 64 * 1024 * 1024
LEGACY_QUEUE_SCHEMA_VERSION = 2


def terminal_index_failure(status: dict, provider: str) -> bool:
    """Read terminal local validation separately from individual HTTP outcomes.

    The caller supplies contract-bound ingest status. Provider-level detail
    failures and absent diagnostics do not establish an index failure.
    """
    diagnostic = (status.get("index_diagnostics") or {}).get(provider) or {}
    conflicts = diagnostic.get("conflicting_duplicate_records")
    return diagnostic.get("pagination_complete") is False or (
        isinstance(conflicts, int) and not isinstance(conflicts, bool) and conflicts > 0
    )


def _bound_events(observation: dict, providers: dict) -> list[dict]:
    status, contract = observation["status"], observation["contract"]
    pointer = status.get("raw_attempt_journal") or {}
    session = pointer.get("session_id")
    journal_path = str(pointer.get("path") or "")
    if journal_path != f"attempt-evidence/raw-attempt-journals-v1/{session}":
        raise ValueError("legacy recovery requires a retained promoted journal")
    entries = [row for row in contract["artifacts"] if row["path"].startswith(journal_path + "/events/")]
    if not entries or len(entries) > MAX_LEGACY_EVENTS or sum(row["bytes"] for row in entries) > MAX_LEGACY_METADATA_BYTES:
        raise ValueError("legacy recovery journal metadata exceeds its scan budget")
    selected = []
    affected = status.get("by_provider") or {}
    for entry in sorted(entries, key=lambda row: row["path"]):
        if entry["bytes"] > 64 * 1024:
            raise ValueError("legacy recovery event exceeds its metadata budget")
        body = safe_child(observation["export_root"], entry["path"]).read_bytes()
        if len(body) != entry["bytes"] or hashlib.sha256(body).hexdigest() != entry["sha256"]:
            raise ValueError("legacy recovery journal differs from its export contract")
        event = json.loads(body)
        context = event.get("context") or {}
        provider = context.get("provider")
        if provider in providers and affected.get(provider) and context.get("phase") in {
                "products_index", "product_detail", "classification_detail"}:
            selected.append(event)
    return selected


def _still_missing(observation: dict, event: dict, present: set[tuple[str, str]]) -> bool:
    context, response = event["context"], event["response"]
    provider, pid = str(context["provider"]), str(context.get("product_id") or "")
    phase = str(context["phase"])
    if phase != "products_index" and (not pid or (provider, pid) in present):
        return False
    if response.get("status") != 200 or response.get("outcome") != "success":
        return True
    journal_path = observation["status"]["raw_attempt_journal"]["path"]
    body = read_bound_bytes(observation["export_root"], observation["contract"],
                            f"{journal_path}/{event['body_path']}", max_bytes=32 * 1024 * 1024)
    try:
        parsed = json.loads(body)
    except (ValueError, UnicodeError):
        return True  # An invalid 200 envelope can recover later, like a 5xx.
    if has_cdr_errors(parsed) or response_shape_error(parsed, phase=phase, product_id=pid):
        return True
    if phase == "products_index":
        return terminal_index_failure(observation["status"], provider)
    inner = detail_inner_record(parsed)
    return bool(inner and infer_cdr_dataset(inner, allow_name_fallback=True) in DATASET_TO_FOLDER)


def legacy_recovery_requests(observation: dict, providers: dict, cache_root: Path) -> list[dict]:
    """Cache only derived request metadata; source generations remain immutable."""
    binding = {
        "generation_id": observation["contract"]["generation_id"],
        "contract_digest": observation["contract"]["contract_digest"],
        "event_digest": observation["event"]["event_digest"],
    }
    # Earlier derivations discarded successful pages despite terminal local
    # index failures. Keep those immutable caches and derive corrected metadata
    # under a new version, including when the old request list was empty.
    cache = cache_root / f"legacy-queue-v{LEGACY_QUEUE_SCHEMA_VERSION}-{binding['event_digest']}.json"
    if cache.is_file():
        if cache.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("legacy recovery queue cache exceeds its budget")
        saved = json.loads(cache.read_bytes())
        if (saved.get("schema_version") != LEGACY_QUEUE_SCHEMA_VERSION
                or saved.get("source") != binding or not isinstance(saved.get("requests"), list)):
            raise ValueError("legacy recovery queue cache source mismatch")
        return saved["requests"]
    present = captured_identities(observation)
    if present is None:
        raise ValueError("legacy recovery requires its normalized observation database")
    latest = {}
    for event in _bound_events(observation, providers):
        context = event["context"]
        key = (context["provider"], context["phase"], context.get("product_id"), context.get("page"))
        latest[key] = event
    requests, counts = [], {}
    for event in latest.values():
        context = event["context"]
        provider = context["provider"]
        if counts.get(provider, 0) >= 128 or len(requests) >= 8192:
            continue
        if _still_missing(observation, event, present):
            counts[provider] = counts.get(provider, 0) + 1
            requests.append({
                "provider_dir": provider, "provider_uid": providers[provider].get("provider_uid"),
                "phase": context["phase"], "product_id": context.get("product_id") or "",
                "url": event["request"]["url"], "status": event["response"].get("status"),
                "failure_category": "legacy_unresolved_request",
                "source_attempt_event_digest": event["event_digest"],
            })
    atomic_write_json(cache, {"schema_version": LEGACY_QUEUE_SCHEMA_VERSION, "source": binding, "requests": requests,
                             "queue_is_complete_failure_inventory": False}, create_once=True)
    return requests
