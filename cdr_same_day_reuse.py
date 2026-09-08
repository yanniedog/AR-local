"""Seed same-day repairs from verified wire captures, preserving their provenance.

SQLite is a comparison target only. Every seeded business record is copied byte
for byte from a successful, hash-bound HTTP response in the selected generation
or one of its same-day revision ancestors. Reuse never adds HTTP attempt events.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

from cdr_atomic import atomic_write_bytes, atomic_write_json, canonical_json_bytes
from cdr_attempt_evidence_promotion import verify_promoted_attempt_evidence
from cdr_clean_export import bank_base_row, detail_json, inner_record
from cdr_compatibility import pagination_accounting_error, response_shape_error
from cdr_export_contract import hash_file, load_contract
from cdr_http_policy import DEFAULT_HTTP_POLICY, sanitize_url
from cdr_ingest_support import (
    append_failure, extract_products, filesystem_product_id_directory, has_cdr_errors,
    next_link, pick_text, sanitize_path_component, summarize_failures,
)
from cdr_ledger_v2 import verify_reachable_generation
from cdr_observation_selection import provider_directories, selected_observation
from cdr_raw_attempt_journal import RawAttemptJournal
from cdr_reuse_identity import captured_provider_directories, endpoint_transition, provider_identity

MANIFEST_PATH = Path("_same-day-reuse") / "manifest.json"
MAX_MANIFEST_BYTES = 3 * 1024 * 1024
MAX_PRODUCTS = 10000
MAX_ANCESTORS = 256
HOBART = ZoneInfo("Australia/Hobart")


def _digest(value: dict) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _safe_path(root: Path, relative: Any) -> Path:
    text = str(relative or "")
    part = Path(text)
    if not text or part.is_absolute() or ".." in part.parts or "\\" in text:
        raise ValueError("reuse evidence path must be relative and contained")
    root = root.resolve(strict=True)
    current = root
    for component in part.parts:
        current = current / component
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("reuse evidence cannot follow symlinks or reparse points")
    current.resolve(strict=True).relative_to(root)
    return current


def _read_json(path: Path, limit: int = MAX_MANIFEST_BYTES) -> dict:
    if path.stat().st_size > limit:
        raise ValueError("reuse evidence exceeds its metadata budget")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("reuse evidence must be an object")
    return value


def _descriptor(state: Path, event: dict, contract: dict) -> dict:
    return {
        "run_date": contract["observation_date"],
        "generation_id": contract["generation_id"],
        "export_contract_path": event["contract_path"],
        "export_contract_sha256": hash_file(_safe_path(state, event["contract_path"])),
        "export_contract_digest": contract["contract_digest"],
        "ledger_event_digest": event["event_digest"],
        "exports_path": contract["source_path"],
    }


def _bound_transitions(state: Path, event: dict, status: dict) -> list[dict]:
    """Re-derive saved transitions from the actual bound parent/current snapshots."""
    reuse = status.get("same_day_reuse") or {}
    saved = reuse.get("endpoint_transitions") or {}
    if not saved:
        return []
    date, parent_id = event["observation_date"], event.get("parent_generation_id")
    parent = _read_json(_safe_path(state, f"ledger-v2/events/{date}/{parent_id}.json"))
    contract = load_contract(_safe_path(state, parent["contract_path"]))
    root = _safe_path(state.parent, contract["source_path"])
    previous = _read_json(_safe_path(root, "ingest-status.json"), 4 * 1024 * 1024)
    if (parent["event_digest"] != event.get("parent_event_digest")
            or reuse.get("baseline") != _descriptor(state, parent, contract)):
        raise ValueError("endpoint transition does not bind the selected parent")
    old = captured_provider_directories(previous, provider_directories(previous))
    current = provider_directories(status)
    if (previous.get("register_provenance_complete") is not True
            or status.get("register_provenance_complete") is not True):
        raise ValueError("endpoint transition register provenance is incomplete")
    verified = []
    for provider, value in saved.items():
        expected = endpoint_transition(old, current, provider)
        if expected is None:
            raise ValueError("endpoint transition is ambiguous or changes legal identity")
        expected.update(baseline_register_evidence=previous.get("register_attempts"),
                        current_register_evidence=status.get("register_attempts"))
        if value != expected:
            raise ValueError("endpoint transition evidence differs from its bound snapshots")
        verified.append(value)
    return verified


def _identity_reaches(provider: str, origin: dict, target: dict, transitions: dict) -> bool:
    identity, seen = provider_identity(origin), set()
    while identity != provider_identity(target):
        uid = identity.get("provider_uid")
        if uid in seen:
            return False
        seen.add(uid)
        transition = transitions.get((provider, uid))
        if transition is None or transition["from"] != identity:
            return False
        identity = transition["to"]
    return True


def _database_rows(export: Path, contract: dict, date: str) -> dict[tuple[str, str], dict]:
    # This is the normal daily export. Custom external --db paths are unsuitable
    # because they are not immutable artifacts of this observation contract.
    names = {row["path"] for row in contract["artifacts"]}
    if "local-cdr.sqlite" not in names:
        raise ValueError("same-day reuse requires a contract-bound local-cdr.sqlite")
    path = _safe_path(export, "local-cdr.sqlite")
    if any(sidecar.exists() and sidecar.stat().st_size > 0
           for sidecar in (Path(str(path) + suffix) for suffix in ("-wal", "-journal"))):
        raise ValueError("same-day reuse refuses a database with pending writes")
    products = {}
    with sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        rows = db.execute("SELECT run_date,dataset,provider,product_id,details_json,product_name,product_key FROM bank_products")
        for row_date, dataset, provider, pid, details, name, product_key in rows:
            key = (provider, pid)
            if (row_date != date or dataset not in {"Mortgage", "Savings", "TD"}
                    or not isinstance(provider, str) or not provider
                    or not isinstance(pid, str) or not pid or key in products):
                raise ValueError("baseline has an invalid or ambiguous product identity")
            normalized = json.loads(details)
            if not isinstance(normalized, dict) or normalized.get("productId", normalized.get("id")) != pid:
                raise ValueError("baseline SQLite product identity does not match details_json")
            products[key] = {"dataset": dataset, "details": normalized, "name": name, "product_key": product_key}
            if len(products) > MAX_PRODUCTS:
                raise ValueError("same-day reuse product budget exceeded")
    if not products:
        raise ValueError("same-day reuse requires captured baseline products")
    return products


def _journal_events(journal: RawAttemptJournal) -> list[dict]:
    # The caller verifies the entire immutable journal first. Reading the full
    # verified events preserves capture times, which evidence_records omits.
    return [_read_json(path) for path in sorted(journal.events.glob("*.json"))]


def _successful_body(journal: RawAttemptJournal, event: dict, phase: str, pid: str = ""):
    response = event.get("response") or {}
    if response.get("status") != 200 or response.get("outcome") != "success":
        return None
    path = _safe_path(journal.root, event.get("body_path"))
    if path.stat().st_size > DEFAULT_HTTP_POLICY.max_body_bytes:
        raise ValueError("reuse response exceeds the body budget")
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != response.get("body_sha256"):
        raise ValueError("reuse response body digest changed")
    try:
        parsed = json.loads(body)
    except (ValueError, UnicodeError):
        return None
    if (not isinstance(parsed, dict) or has_cdr_errors(parsed)
            or response_shape_error(parsed, phase=phase, product_id=pid)):
        return None
    return path, parsed


def _request_identity(event: dict, endpoint: str, pid: str) -> bool:
    request = urlsplit(str((event.get("request") or {}).get("url") or ""))
    holder = urlsplit(endpoint)
    return bool(
        request.scheme == holder.scheme == "https"
        and not request.username and not request.password
        and request.netloc.lower() == holder.netloc.lower()
        and unquote(request.path) == unquote(holder.path).rstrip("/") + "/" + pid
    )


@dataclass(frozen=True)
class ReusePlan:
    manifest: dict
    bodies: tuple[tuple[Path, dict], ...]
    protected_roots: tuple[Path, ...]


def prepare_same_day_reuse(state: Path, date: str) -> ReusePlan:
    """Fully verify the selected parent and every seed before performing writes."""
    state = state.resolve(strict=True)
    observation = selected_observation(state, date)
    if observation is None:
        raise ValueError("same-day reuse requires a verified selected observation for today")
    event = verify_reachable_generation(state, date, observation["contract"]["generation_id"])
    baseline = _descriptor(state, event, observation["contract"])
    products = _database_rows(observation["export_root"], observation["contract"], date)
    baseline_providers = captured_provider_directories(observation["status"], provider_directories(observation["status"]))
    if any(not (baseline_providers.get(provider) or {}).get("provider_uid") for provider, _ in products):
        raise ValueError("baseline product provider has no unambiguous registered identity")
    remaining = set(products)
    bodies = []
    sources = {}
    visited = set()
    transitions = {}
    protected_roots = {state, observation["export_root"]}
    while remaining:
        generation = event["generation_id"]
        if generation in visited or len(visited) >= MAX_ANCESTORS:
            raise ValueError("same-day reuse ancestry is cyclic or exceeds its budget")
        visited.add(generation)
        contract = load_contract(_safe_path(state, event["contract_path"]))
        export = _safe_path(state.parent, contract["source_path"])
        protected_roots.add(export)
        status = _read_json(_safe_path(export, "ingest-status.json"), 4 * 1024 * 1024)
        for transition in _bound_transitions(state, event, status):
            transitions.setdefault((transition["provider_dir"], transition["from"]["provider_uid"]), transition)
        providers = provider_directories(status)
        journal = verify_promoted_attempt_evidence(export, status["raw_attempt_journal"])
        for attempt in reversed(_journal_events(journal)):
            context = attempt.get("context") or {}
            provider, pid = context.get("provider"), context.get("product_id")
            key = (provider, pid)
            if key not in remaining or context.get("phase") not in {"product_detail", "classification_detail"}:
                continue
            identity = providers.get(provider) or {}
            if (not _identity_reaches(provider, identity, baseline_providers[provider], transitions)
                    or not _request_identity(attempt, str(identity.get("endpoint_url") or ""), pid)):
                continue
            captured = str((attempt.get("response") or {}).get("completed_at") or "")
            timestamp = datetime.fromisoformat(captured.replace("Z", "+00:00"))
            if timestamp.tzinfo is None or timestamp.astimezone(HOBART).date().isoformat() != date:
                continue
            response = _successful_body(journal, attempt, "product_detail", pid)
            if response is None:
                continue
            path, parsed = response
            if json.loads(detail_json(inner_record(parsed))) != products[key]["details"]:
                continue
            entry = {
                "provider_dir": provider, "product_id": pid, "dataset": products[key]["dataset"],
                "body_sha256": attempt["response"]["body_sha256"], "captured_at_utc": captured,
                "source_generation_id": generation, "source_event_seq": attempt["sequence"],
                "source_event_digest": attempt["event_digest"],
                "source_journal_session_id": journal.session_id,
            }
            record = inner_record(parsed)
            if not (record.get("name") or record.get("productName")):
                entry["fallback_product_name"] = products[key]["name"]
            predicted = bank_base_row(_leaf(Path("banks"), entry) / "product-detail.json", Path("banks"), record)
            if predicted["product_key"] != products[key]["product_key"]:
                raise ValueError("reused detail cannot preserve the baseline product key")
            sources[generation] = _descriptor(state, event, contract)
            bodies.append((path, entry))
            remaining.remove(key)
        if not remaining:
            break
        parent = event.get("parent_generation_id")
        if not parent or not event.get("parent_event_digest"):
            raise ValueError(f"no matching successful same-day raw capture for {len(remaining)} baseline products")
        previous = _read_json(_safe_path(state, f"ledger-v2/events/{date}/{parent}.json"))
        if previous.get("event_digest") != event["parent_event_digest"] or previous.get("observation_date") != date:
            raise ValueError("reuse ancestor is not bound to the selected same-day parent")
        event = previous
    bodies.sort(key=lambda item: (item[1]["provider_dir"], item[1]["product_id"]))
    manifest = {
        "schema_version": 1, "baseline": baseline, "sources": sources,
        "providers": {name: provider_identity(value) for name, value in baseline_providers.items()},
        "baseline_register_evidence": observation["status"].get("register_attempts"),
        "baseline_register_provenance_complete": observation["status"].get("register_provenance_complete"),
        "reused": [row for _, row in bodies], "withdrawals": [], "withdrawal_indexes": {},
        "unconfirmed": [], "endpoint_transitions": {}, "identity_blocks": {}, "directory_blocks": {}, "reconciled": False,
    }
    if len(canonical_json_bytes(manifest)) > MAX_MANIFEST_BYTES:
        raise ValueError("same-day reuse manifest budget exceeded")
    return ReusePlan(manifest, tuple(bodies), tuple(protected_roots))


def _leaf(banks: Path, entry: dict) -> Path:
    provider = str(entry["provider_dir"])
    if Path(provider).name != provider or provider in {".", ".."} or "\\" in provider:
        raise ValueError("unsafe reused provider directory")
    name = sanitize_path_component(entry.get("fallback_product_name") or "_same_day")
    return banks / entry["dataset"] / provider / name / filesystem_product_id_directory(entry["product_id"])


def validate_reuse_destination(plan: ReusePlan, path: Path) -> None:
    """A custom scratch/export path cannot nest inside finalized source evidence."""
    target = path.resolve()
    for protected in plan.protected_roots:
        if target == protected or protected in target.parents:
            raise ValueError("same-day reuse destination overlaps preserved source evidence")


def seed_same_day_reuse(plan: ReusePlan, run_root: Path) -> None:
    """Copy untouched wire bodies to a new, empty revision scratch tree."""
    validate_reuse_destination(plan, run_root)
    if run_root.exists() and (not run_root.is_dir() or any(run_root.iterdir())):
        raise ValueError("same-day reuse requires an empty isolated scratch directory")
    leaves = [_leaf(run_root / "banks", entry) for _, entry in plan.bodies]
    if len({str(path).casefold() for path in leaves}) != len(leaves):
        raise ValueError("reused product filesystem identities collide")
    # Check all body hashes before installing any seed. Recheck on each copy too.
    if any(hash_file(path) != entry["body_sha256"] for path, entry in plan.bodies):
        raise ValueError("raw capture changed after same-day reuse verification")
    for (source, entry), leaf in zip(plan.bodies, leaves):
        body = source.read_bytes()
        if hashlib.sha256(body).hexdigest() != entry["body_sha256"]:
            raise ValueError("raw capture changed during same-day reuse seeding")
        atomic_write_bytes(leaf / "product-detail.json", body, create_once=True)
        atomic_write_bytes(leaf / "product-id.txt", (entry["product_id"] + "\n").encode("utf-8"), create_once=True)
    atomic_write_json(run_root / "banks" / MANIFEST_PATH, plan.manifest, create_once=True)


def attach_same_day_reuse_status(run_root: Path) -> None:
    """Embed reuse provenance before create-once attempt-evidence promotion."""
    banks = run_root / "banks"
    manifest_path = banks / MANIFEST_PATH
    status_path = banks / "ingest-status.json"
    if not manifest_path.exists() or not status_path.exists():
        return
    manifest = _read_json(manifest_path)
    manifest["manifest_sha256"] = _digest(manifest)
    status = _read_json(status_path, 4 * 1024 * 1024)
    status["same_day_reuse"] = manifest
    if not manifest.get("reconciled") or manifest.get("unconfirmed"):
        status["incomplete"] = True
    atomic_write_json(status_path, status)


def _fresh_index(banks: Path, provider: str, diagnostic: dict, journal: RawAttemptJournal,
                 events: list[dict], endpoint: str):
    """Prove a whole current listing independently before removing a cached ID."""
    if (diagnostic.get("pagination_complete") is not True
            or diagnostic.get("conflicting_duplicate_records") != 0
            or diagnostic.get("declared_total_records") != diagnostic.get("raw_records")):
        return None
    count = diagnostic.get("pages")
    if not isinstance(count, int) or not 1 <= count <= DEFAULT_HTTP_POLICY.max_pages:
        return None
    by_page = {}
    for event in events:
        context = event.get("context") or {}
        if context.get("phase") == "products_index" and context.get("provider") == provider:
            by_page[context.get("page")] = event
    products, page_evidence, raw_count = {}, [], 0
    expected_url = None
    for page in range(1, count + 1):
        event = by_page.get(page)
        if event is None:
            return None
        response = _successful_body(journal, event, "products_index")
        if response is None:
            return None
        _, parsed = response
        captured = _read_json(banks / "_holders" / provider / "_products-index" / f"page-{page:04d}.json",
                              DEFAULT_HTTP_POLICY.max_body_bytes)
        if captured != parsed:
            return None
        url = event["request"]["url"]
        if url != sanitize_url(endpoint if page == 1 else expected_url or ""):
            return None
        expected_url = next_link(parsed, url)
        for product in extract_products(parsed):
            pid = pick_text(product, ["productId", "id"])
            if not pid:
                return None
            raw_count += 1
            if pid in products and products[pid] != product:
                return None
            products[pid] = product
        meta = parsed.get("meta") or {}
        if (meta.get("totalRecords") != diagnostic["raw_records"]
                or meta.get("totalPages") != diagnostic["declared_total_pages"]
                or pagination_accounting_error(parsed, pages=page, products=raw_count, has_next=bool(expected_url))):
            return None
        if bool(expected_url) != (page < count):
            return None
        page_evidence.append({
            "body_sha256": event["response"]["body_sha256"], "event_digest": event["event_digest"],
            "event_seq": event["sequence"], "journal_session_id": journal.session_id,
        })
    return {
        "complete": raw_count == len(products), "pages": page_evidence,
        "observed_product_ids": sorted(products),
        "fresh_index_sha256": _digest({"page_body_sha256": [row["body_sha256"] for row in page_evidence]}),
    }


def reconcile_same_day_reuse(run_root: Path) -> None:
    """Keep cached captures unless a complete new index proves their omission."""
    banks = run_root / "banks"
    manifest_path = banks / MANIFEST_PATH
    if not manifest_path.exists():
        return
    manifest = _read_json(manifest_path)
    if manifest.get("reconciled"):
        return
    status = _read_json(banks / "ingest-status.json", 4 * 1024 * 1024)
    pointer = status["raw_attempt_journal"]
    journal_root = _safe_path(run_root, pointer["path"])
    if journal_root.parent.name != "_raw-attempt-journals-v1" or journal_root.name != pointer["session_id"]:
        raise ValueError("fresh reuse reconciliation requires the current ingest journal")
    journal = RawAttemptJournal(journal_root.parent, journal_root.name)
    summary = journal.summary(recover=False)
    if any(pointer.get(key) != value for key, value in summary.items()):
        raise ValueError("fresh reuse reconciliation journal differs from terminal status")
    events = _journal_events(journal)
    for event in events:
        captured = datetime.fromisoformat(event["response"]["completed_at"].replace("Z", "+00:00"))
        if captured.tzinfo is None or captured.astimezone(HOBART).date().isoformat() != manifest["baseline"]["run_date"]:
            raise ValueError("same-day recovery crossed the observation date boundary")
    providers = provider_directories(status)
    diagnostics = status.get("index_diagnostics") or {}
    _block_duplicate_provider_directories(banks, manifest, providers)
    provider_ids = sorted({row["provider_dir"] for row in manifest["reused"]})
    retained = []
    for provider in provider_ids:
        identity = manifest["providers"][provider]
        fresh = providers.get(provider)
        identity_blocked = False
        if fresh and provider_identity(fresh) != identity:
            transition = endpoint_transition(manifest["providers"], providers, provider) if (
                manifest.get("baseline_register_provenance_complete") is True
                and status.get("register_provenance_complete") is True) else None
            if transition:
                transition.update(baseline_register_evidence=manifest.get("baseline_register_evidence"),
                                  current_register_evidence=status.get("register_attempts"))
                manifest["endpoint_transitions"][provider] = transition
            else:
                identity_blocked = True
                manifest["identity_blocks"][provider] = {"previous": identity, "current": provider_identity(fresh)}
                _quarantine_new_provider_details(banks, provider, manifest["reused"])
                append_failure(banks, {"phase": "products_index", "bank": provider,
                    "status": "provider_identity_migration_blocked", "failure_category": "invalid_response", "retryable": False})
        if fresh is None or identity_blocked:
            retained.append({**identity, "retained_from_generation_id": manifest["baseline"]["generation_id"]})
        proof = None if fresh is None or identity_blocked else _fresh_index(
            banks, provider, diagnostics.get(provider) or {}, journal, events, str(fresh["endpoint_url"]))
        # A provider can transiently return a valid empty catalogue (including
        # during version fallback). That cannot withdraw an already captured
        # population. Keep its original bodies and queue reconfirmation.
        if proof and not proof["observed_product_ids"]:
            proof = None
        seen = set(proof["observed_product_ids"]) if proof else set()
        if proof and proof["complete"]:
            manifest["withdrawal_indexes"][provider] = proof
        unconfirmed = False
        for row in (row for row in manifest["reused"] if row["provider_dir"] == provider):
            leaf = _leaf(banks, row)
            if hash_file(leaf / "product-detail.json") != row["body_sha256"]:
                raise ValueError("same-day reused raw capture changed during ingest")
            if proof and proof["complete"] and row["product_id"] not in seen:
                manifest["withdrawals"].append({
                    "provider_dir": provider, "product_id": row["product_id"],
                    "fresh_index_sha256": proof["fresh_index_sha256"],
                })
                # Keep these source bytes, but remove the parser's business-file
                # name from isolated scratch. The original generation is untouched.
                (leaf / "product-detail.json").rename(leaf / "withdrawn-product-detail.body")
            elif row["product_id"] not in seen:
                manifest["unconfirmed"].append({"provider_dir": provider, "product_id": row["product_id"]})
                unconfirmed = True
        if unconfirmed and not identity_blocked and not (status.get("by_provider") or {}).get(provider):
            append_failure(banks, {
                "phase": "products_index", "bank": provider,
                "status": "same_day_index_unconfirmed", "failure_category": "invalid_response",
                "retryable": False,
            })
    manifest["reconciled"] = True
    if len(canonical_json_bytes(manifest)) > MAX_MANIFEST_BYTES:
        raise ValueError("reconciled same-day reuse manifest budget exceeded")
    rollup = summarize_failures(banks)
    rollup["incomplete"] = bool(status.get("incomplete") or rollup["incomplete"] or manifest["unconfirmed"])
    rollup["failure_provenance_complete"] &= status.get("failure_provenance_complete") is True
    status.update(rollup)
    for provider, value in providers.items():
        value["failure_records"] = int((status.get("by_provider") or {}).get(provider) or 0)
        value["failure_categories"] = status["by_provider_failure_category"].get(provider, {})
        if value["failure_records"]:
            value["state"] = "partial"
    status["provider_states"] = list(providers.values())
    status["retained_provider_states"] = retained
    status["same_day_reuse"] = {**manifest, "manifest_sha256": _digest(manifest)}
    from cdr_recovery_queue import add_recovery_requests

    queue_providers = dict(providers)
    queue_providers.update({value["provider_dir"]: value for value in retained})
    add_recovery_requests(status, banks, [(value, name) for name, value in queue_providers.items()])
    atomic_write_json(manifest_path, manifest)
    atomic_write_json(banks / "ingest-status.json", status)
    attach_same_day_reuse_status(run_root)


def _quarantine_new_provider_details(banks: Path, provider: str, reused: list[dict]) -> None:
    retained_paths = {_leaf(banks, row) / "product-detail.json" for row in reused if row["provider_dir"] == provider}
    for dataset in ("Mortgage", "Savings", "TD"):
        for path in (banks / dataset / provider).glob("*/*/product-detail.json"):
            if path not in retained_paths:
                path.rename(path.with_name("identity-blocked-product-detail.body"))


def _block_duplicate_provider_directories(banks: Path, manifest: dict, current: dict[str, dict]) -> None:
    """Register ordering must not turn retained records into duplicate providers."""
    captured = {row["provider_dir"] for row in manifest["reused"]}
    previous = {value["provider_uid"]: name for name, value in manifest["providers"].items() if name in captured}
    for provider, identity in current.items():
        original = previous.get(identity.get("provider_uid"))
        if original and original != provider:
            manifest["directory_blocks"][provider] = {
                "retained_provider_dir": original, "provider_uid": identity["provider_uid"],
            }
            _quarantine_new_provider_details(banks, provider, manifest["reused"])
            append_failure(banks, {
                "phase": "products_index", "bank": provider,
                "status": "provider_directory_migration_blocked", "failure_category": "invalid_response",
                "retryable": False,
            })
