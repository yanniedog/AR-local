"""Read verified observation metadata and retain the best same-day selection.

Every attempt remains in the immutable ledger. Selection is independent: a
failed recovery must not replace the observation used by publishers/backups.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from cdr_export_contract import hash_file, load_contract
from cdr_atomic import canonical_json_bytes
from cdr_compatibility import pagination_accounting_error, response_shape_error
from cdr_http_policy import sanitize_url
from cdr_ingest_support import allocate_bank_dir, extract_products, has_cdr_errors, next_link
from cdr_ledger_v2 import verify_event

MAX_STATUS_BYTES = 4 * 1024 * 1024


def safe_child(root: Path, relative: Any) -> Path:
    value = str(relative or "")
    part = Path(value)
    if not value or part.is_absolute() or ".." in part.parts or "\\" in value:
        raise ValueError("observation path must be relative and contained")
    result = (root / part).resolve(strict=True)
    result.relative_to(root.resolve())
    return result


def read_bound_bytes(root: Path, contract: Mapping[str, Any], relative: str,
                     *, max_bytes: int = MAX_STATUS_BYTES) -> bytes:
    records = [row for row in contract["artifacts"] if row["path"] == relative]
    if len(records) != 1:
        raise ValueError("observation metadata is not bound to its contract")
    path = safe_child(root, relative)
    if path.stat().st_size > max_bytes:
        raise ValueError("observation metadata exceeds its size budget")
    with path.open("rb") as stream:
        body = stream.read(max_bytes + 1)
    record = records[0]
    if len(body) != record["bytes"] or hashlib.sha256(body).hexdigest() != record["sha256"]:
        raise ValueError("observation metadata changed after finalization")
    return body


def read_bound_json(root: Path, contract: Mapping[str, Any], relative: str,
                    *, max_bytes: int = MAX_STATUS_BYTES) -> dict:
    body = read_bound_bytes(root, contract, relative, max_bytes=max_bytes)
    result = json.loads(body)
    if not isinstance(result, dict):
        raise ValueError("observation metadata is not an object")
    return result


def load_pointer_observation(state: Path, pointer: Mapping[str, Any]) -> dict:
    """Validate marker/event/contract identity and hash the small status artifact.

    A live recovery verifies all retained source artifacts again before seeding.
    Monitoring does not re-hash gigabytes of immutable exports each probe tick.
    """
    state = state.resolve()
    marker = json.loads(safe_child(state, pointer.get("marker_path")).read_bytes())
    contract_path = safe_child(state, marker.get("export_contract_path"))
    contract = load_contract(contract_path)
    event = json.loads(safe_child(
        state, f"ledger-v2/events/{contract['observation_date']}/{contract['generation_id']}.json"
    ).read_bytes())
    verify_event(state, event)
    for name in ("generation_id", "observation_state"):
        if pointer.get(name) != contract[name] or marker.get(name) != contract[name]:
            raise ValueError("observation pointer identity mismatch")
    if (
        pointer.get("observation_date") != contract["observation_date"]
        or marker.get("run_date") != contract["observation_date"]
        or marker.get("ledger_state") != "finalized"
        or marker.get("finalization_schema_version") != 2
        or pointer.get("ledger_event_digest") != event["event_digest"]
        or marker.get("ledger_event_digest") != event["event_digest"]
        or marker.get("export_contract_digest") != contract["contract_digest"]
        or pointer.get("export_path") != contract["source_path"]
        or pointer.get("marker_path") != contract["completion_marker_path"]
    ):
        raise ValueError("observation pointer binding mismatch")
    root = safe_child(state.parent, contract["source_path"])
    return {
        "pointer": dict(pointer), "marker": marker, "contract": contract,
        "event": event, "export_root": root,
        "status": read_bound_json(root, contract, "ingest-status.json"),
    }


def selected_observation(state: Path, run_date: str) -> dict | None:
    path = state / "observation-pointers-v2" / "latest-observation.json"
    if not path.is_file():
        return None
    pointer = json.loads(path.read_bytes())
    if not isinstance(pointer, dict) or pointer.get("observation_date") != run_date:
        return None
    return load_pointer_observation(state, pointer)


def provider_directories(status: Mapping[str, Any]) -> dict[str, dict]:
    seen: set[str] = set()
    providers = {}
    for raw in status.get("provider_states") or []:
        if not isinstance(raw, dict):
            raise ValueError("invalid provider state")
        derived = allocate_bank_dir(
            str(raw.get("brand_name") or ""), str(raw.get("legal_entity_name") or ""),
            str(raw.get("endpoint_url") or ""), seen,
        )
        directory = str(raw.get("provider_dir") or derived)
        if directory != derived or directory in providers:
            raise ValueError("ambiguous provider directory")
        providers[directory] = dict(raw, provider_dir=directory)
    return providers


def captured_identities(observation: Mapping[str, Any]) -> set[tuple[str, str]] | None:
    contract = observation["contract"]
    names = {"local-cdr.sqlite", f"banks-{contract['observation_date']}.sqlite"}
    records = [row for row in contract["artifacts"] if row["path"] in names]
    if not records:
        return None  # Historical/test generations without a normalized SQLite export.
    if len(records) != 1:
        raise ValueError("ambiguous observation database")
    record = records[0]
    path = safe_child(observation["export_root"], record["path"])
    if path.stat().st_size != record["bytes"] or hash_file(path) != record["sha256"]:
        raise ValueError("observation database changed after finalization")
    try:
        with sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
            db.execute("PRAGMA query_only=ON")
            rows = db.execute(
                "SELECT provider, product_id FROM bank_products WHERE run_date=?",
                (contract["observation_date"],),
            )
            return {(str(provider), str(product_id)) for provider, product_id in rows}
    except sqlite3.Error as error:
        raise ValueError("observation identity database is unreadable") from error


def _verified_withdrawal_index(observation: Mapping, provider: str, proof: dict) -> set[str]:
    status, root, contract = observation["status"], observation["export_root"], observation["contract"]
    diagnostic = (status.get("index_diagnostics") or {}).get(provider) or {}
    if proof.get("complete") is not True or diagnostic.get("pagination_complete") is not True:
        raise ValueError("withdrawal index is incomplete")
    pages = proof.get("pages") or []
    journal = status.get("raw_attempt_journal") or {}
    journal_path, session = str(journal.get("path") or ""), journal.get("session_id")
    if (not 1 <= len(pages) <= 1000 or len(pages) != diagnostic.get("pages")
            or journal_path != f"attempt-evidence/raw-attempt-journals-v1/{session}"):
        raise ValueError("withdrawal index journal is invalid")
    expected_digest = hashlib.sha256(canonical_json_bytes({
        "page_body_sha256": [row["body_sha256"] for row in pages]
    })).hexdigest()
    if proof.get("fresh_index_sha256") != expected_digest:
        raise ValueError("withdrawal index digest mismatch")
    observed: set[str] = set()
    expected_url = provider_directories(status)[provider]["endpoint_url"]
    for number, row in enumerate(pages, start=1):
        prefix = f"{journal_path}/events/{int(row['event_seq']):08d}-"
        matches = [entry["path"] for entry in contract["artifacts"] if entry["path"].startswith(prefix)]
        if len(matches) != 1 or row.get("journal_session_id") != session:
            raise ValueError("withdrawal page event is not contract bound")
        event = read_bound_json(root, contract, matches[0])
        context, response = event.get("context") or {}, event.get("response") or {}
        if (event.get("event_digest") != row["event_digest"] or context.get("provider") != provider
                or context.get("phase") != "products_index" or context.get("page") != number
                or event.get("sequence") != row["event_seq"] or event.get("session_id") != session
                or response.get("status") != 200 or response.get("outcome") != "success"
                or response.get("body_sha256") != row["body_sha256"]):
            raise ValueError("withdrawal page evidence has the wrong identity")
        started = datetime.fromisoformat(str(event["request"]["started_at"]).replace("Z", "+00:00"))
        completed = datetime.fromisoformat(str(response["completed_at"]).replace("Z", "+00:00"))
        if (started.tzinfo is None or completed.tzinfo is None or completed < started
                or any(stamp.astimezone(ZoneInfo("Australia/Hobart")).date().isoformat()
                       != contract["observation_date"] for stamp in (started, completed))):
            raise ValueError("withdrawal proof is not a fresh same-day capture")
        body_path = f"{journal_path}/bodies/{row['body_sha256']}.body"
        parsed = read_bound_json(root, contract, body_path, max_bytes=32 * 1024 * 1024)
        if has_cdr_errors(parsed) or response_shape_error(parsed, phase="products_index"):
            raise ValueError("withdrawal index body is invalid")
        url = event["request"]["url"]
        if sanitize_url(url) != sanitize_url(expected_url):
            raise ValueError("withdrawal index pagination is discontinuous")
        expected_url = next_link(parsed, url)
        for product in extract_products(parsed):
            pid = str(product.get("productId") or product.get("id") or "")
            if not pid or pid in observed:
                raise ValueError("withdrawal index identity is ambiguous")
            observed.add(pid)
        meta = parsed.get("meta") or {}
        if (meta.get("totalRecords") != diagnostic.get("raw_records")
                or meta.get("totalPages") != diagnostic.get("declared_total_pages")
                or not isinstance(meta.get("totalRecords"), int)
                or not isinstance(meta.get("totalPages"), int)
                or bool(expected_url) != (number < len(pages))
                or pagination_accounting_error(parsed, pages=number, products=len(observed), has_next=bool(expected_url))):
            raise ValueError("withdrawal index totals do not reconcile")
    if not observed:
        raise ValueError("empty index cannot prove withdrawal of captured products")
    if observed != set(proof.get("observed_product_ids") or []):
        raise ValueError("withdrawal membership does not match captured page bodies")
    return observed


def _withdrawals(observation: Mapping[str, Any], source: Mapping[str, Any]) -> set[tuple[str, str]]:
    status = observation["status"]
    reuse = status.get("same_day_reuse") or {}
    origin = reuse.get("baseline") or {}
    if (
        origin.get("generation_id") != source["contract"]["generation_id"]
        or origin.get("ledger_event_digest") != source["event"]["event_digest"]
        or origin.get("export_contract_digest") != source["contract"]["contract_digest"]
    ):
        return set()
    result = set()
    verified_indexes = {}
    for row in reuse.get("withdrawals") or []:
        provider = str(row.get("provider_dir") or "")
        proof = (reuse.get("withdrawal_indexes") or {}).get(provider) or {}
        if row.get("fresh_index_sha256") != proof.get("fresh_index_sha256"):
            raise ValueError("withdrawal does not reference its fresh index")
        if provider not in verified_indexes:
            verified_indexes[provider] = _verified_withdrawal_index(observation, provider, proof)
        if not row.get("product_id") or row["product_id"] in verified_indexes[provider]:
            raise ValueError("withdrawal is contradicted by its fresh index")
        result.add((provider, str(row["product_id"])))
    return result


def same_day_selection_reason(state: Path, current: Mapping, incoming: Mapping,
                              reconciliation: dict | None = None) -> str:
    """Return an explicit refusal reason, or empty string when selection is safe."""
    old = load_pointer_observation(state, current)
    new = load_pointer_observation(state, incoming)
    old_coverage, new_coverage = old["contract"]["coverage"], new["contract"]["coverage"]
    if (old_coverage.get("failure_provenance_complete") is True
            and new_coverage.get("failure_provenance_complete") is not True):
        return "failure_provenance_regressed"
    reused = new["status"].get("same_day_reuse")
    if reused and new["event"].get("parent_generation_id") != current["generation_id"]:
        return "recovery_source_is_not_selected_generation"
    before, after = captured_identities(old), captured_identities(new)
    withdrawals = _withdrawals(new, old)
    excluded_rates = 0
    if before is not None and after is not None:
        from cdr_observation_scope import add_excluded_rate_counts, verified_scope_exclusions

        missing = before - after - withdrawals
        exclusions = verified_scope_exclusions(new, old, missing)
        removed_withdrawals = [{"provider": provider, "product_id": pid}
                               for provider, pid in sorted((before - after) & withdrawals)]
        # Only actually removed identities earn an allowance. The exclusion
        # list is disjoint because verified withdrawals were removed above.
        removed_rates = add_excluded_rate_counts(
            old, exclusions + removed_withdrawals if exclusions else [])
        excluded_rates = sum(row["previous_rate_rows"] for row in exclusions)
        withdrawn_rates = removed_rates - excluded_rates
        unexplained = missing - {(row["provider"], row["product_id"]) for row in exclusions}
        if exclusions and reconciliation is not None:
            reconciliation.update(
                schema_version=1, policy="verified_explicit_cdr_scope_exclusions",
                previous_products=len(before), candidate_products=len(after),
                previous_rate_rows=int(old_coverage.get("eligible_rate_rows") or 0),
                candidate_rate_rows=int(new_coverage.get("eligible_rate_rows") or 0),
                scope_exclusions=exclusions, scope_excluded_rate_rows=excluded_rates,
                removed_withdrawals=removed_withdrawals, withdrawn_rate_rows=withdrawn_rates,
                unexplained_missing_products=[list(key) for key in sorted(unexplained)],
                rate_delta_after_scope_exclusions=(int(new_coverage.get("eligible_rate_rows") or 0)
                    - int(old_coverage.get("eligible_rate_rows") or 0) + excluded_rates),
                rate_delta_after_verified_removals=(int(new_coverage.get("eligible_rate_rows") or 0)
                    - int(old_coverage.get("eligible_rate_rows") or 0) + removed_rates),
            )
        if unexplained:
            return "previously_captured_products_missing_without_fresh_withdrawal"
        if (exclusions and int(new_coverage.get("eligible_rate_rows") or 0)
                < int(old_coverage.get("eligible_rate_rows") or 0) - removed_rates):
            return "in_scope_rate_coverage_regressed"
        improved = bool(after - before)
    else:
        if int(new_coverage.get("products_discovered") or 0) < int(old_coverage.get("products_discovered") or 0):
            return "product_coverage_regressed"
        improved = int(new_coverage.get("products_discovered") or 0) > int(old_coverage.get("products_discovered") or 0)
    if not improved and not withdrawals:
        if int(new_coverage.get("failure_records") or 0) > int(old_coverage.get("failure_records") or 0):
            return "unresolved_failures_increased_without_coverage_gain"
        if (reused and int(new_coverage.get("eligible_rate_rows") or 0)
                < int(old_coverage.get("eligible_rate_rows") or 0) - excluded_rates):
            return "retained_rate_coverage_regressed"
    return ""
