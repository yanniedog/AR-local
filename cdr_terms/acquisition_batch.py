"""Sequential current-document collection inside the existing supervised child."""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

from .acquisition import FetchPolicy, acquire_document
from .acquisitions_queue import AcquisitionQueue
from .acquisition_processing import ProcessingQueue
from .identity import canonical_json, digest, utc_now
from .store import EvidenceStore

MAX_ATTEMPTS = 32
MAX_BYTES = 64 * 1024**2
ADMISSION_SECONDS = 105
RECEIPT_RESERVE_SECONDS = 15
MAX_MAINTENANCE = 128
MAX_BATCH_RECEIPT_BYTES = 64 * 1024


@dataclass(frozen=True)
class BatchLimits:
    attempts: int = MAX_ATTEMPTS
    body_bytes: int = MAX_BYTES
    maintenance: int = MAX_MAINTENANCE

    def __post_init__(self):
        for value, ceiling in ((self.attempts, MAX_ATTEMPTS), (self.body_bytes, MAX_BYTES), (self.maintenance, MAX_MAINTENANCE)):
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError("Batch limits must stay inside reviewed bounds")


def request_scope(store: EvidenceStore, request: dict) -> tuple[list[str], frozenset[str], dict]:
    from .graph import DocumentGraph, current_observations
    from .observation_checks import current_observation
    observations = current_observations(store, request["request_id"])
    hosts = set(DocumentGraph(store).request_hosts(request["request_id"]))
    for observation in observations:
        hosts.update(urlsplit(row[0]).hostname for row in store.db.execute(
            "SELECT d.source_url FROM applicability a JOIN documents d USING(document_id) "
            "WHERE a.observation_id=? AND a.relation!='cdr_source'", (observation,)))
    if observations or hosts:
        return observations, frozenset(hosts), {}
    old = store.db.execute("SELECT o.* FROM acquisition_bindings b JOIN observations o USING(observation_id) "
                           "WHERE b.request_id=? ORDER BY o.observation_id", (request["request_id"],)).fetchall()
    replacements = []
    for observation in old:
        try:
            current = current_observation(store, observation["product_key"])
        except ValueError:
            break
        capture = store.db.execute("SELECT * FROM ingest_captures WHERE ingest_id=?", (current["ingest_id"],)).fetchone()
        if not capture or current["observed_at"] <= observation["observed_at"]:
            break
        replacements.append({"previous_observation_id": observation["observation_id"],
                             "replacement_observation_id": current["observation_id"],
                             "replacement_ingest_id": current["ingest_id"],
                             "replacement_capture_sha256": capture["receipt_sha256"]})
    obsolete = bool(old) and len(replacements) == len(old) and request["priority"] != 2
    return [], frozenset(), {"reason": "obsolete_current_observations" if obsolete else "source_scope_unresolved",
                             "obsolete": obsolete, "replacements": replacements if obsolete else [],
                             "prior_observation_ids": [row["observation_id"] for row in old],
                             "legal_completeness": "unknown"}


def dispose_unrunnable(store: EvidenceStore, request: dict, proof: dict) -> bool:
    """CAS before any lease/network. Neither unknown nor obsolete means removed."""
    with store.db:
        store.db.execute("BEGIN IMMEDIATE")
        event = store.db.execute("SELECT * FROM acquisition_events WHERE request_id=? ORDER BY sequence DESC LIMIT 1",
                                  (request["request_id"],)).fetchone()
        if not event or event["status"] not in {"queued", "retry_wait"}:
            return False
        observations, hosts, checked = request_scope(store, request)
        if observations or hosts or canonical_json(checked) != canonical_json(proof):
            return False
        observed = utc_now()
        store.db.execute("INSERT OR IGNORE INTO acquisition_dispositions VALUES (?,?,?,?)",
                          (request["request_id"], observed, proof["reason"], canonical_json(proof)))
        AcquisitionQueue(store)._event(request["request_id"], "blocked", observed, error_code=proof["reason"])
    return True


def pending_counts(store: EvidenceStore) -> dict:
    rows = store.db.execute("SELECT status,COUNT(*) count FROM acquisition_events e WHERE sequence="
                            "(SELECT MAX(sequence) FROM acquisition_events WHERE request_id=e.request_id) GROUP BY status")
    counts = {row["status"]: row["count"] for row in rows}
    counts["due"] = store.db.execute("SELECT COUNT(*) FROM acquisition_requests r JOIN acquisition_events e ON "
        "e.sequence=(SELECT MAX(sequence) FROM acquisition_events WHERE request_id=r.request_id) "
        "WHERE (e.status='queued' OR (e.status='retry_wait' AND e.retry_after<=?)) AND EXISTS "
        "(SELECT 1 FROM ingest_captures c WHERE c.ingest_id=r.ingest_id)", (utc_now(),)).fetchone()[0]
    counts["processing_pending"] = store.db.execute("SELECT COUNT(*) FROM acquisition_processing_events e WHERE sequence="
        "(SELECT MAX(sequence) FROM acquisition_processing_events WHERE processing_id=e.processing_id) "
        "AND status IN ('queued','running','retry_wait')").fetchone()[0]
    counts["processing_schedule_migration_complete"] = not ProcessingQueue(store).schedule_incomplete()
    return counts


def has_work(store: EvidenceStore) -> bool:
    return bool(AcquisitionQueue(store).next_due() or ProcessingQueue(store).has_work() or store.db.execute(
        "SELECT 1 FROM acquisition_events e WHERE sequence=(SELECT MAX(sequence) FROM acquisition_events "
        "WHERE request_id=e.request_id) AND status='running' AND lease_expires_at<=? LIMIT 1", (utc_now(),)).fetchone())


def run_batch(store: EvidenceStore, *, registry_context: dict, deadline: float,
              guard: Callable[[], str | None], limits: BatchLimits = BatchLimits()) -> dict:
    started = time.monotonic()
    if not math.isfinite(deadline) or deadline - started > ADMISSION_SECONDS + 0.01:
        raise ValueError("Collector deadline exceeds the unchanged admission budget")
    state = {"items": [], "dispositions": [], "charged_bytes": 0, "actual_body_bytes": 0,
             "processing": None, "stop_reason": "no_due_work"}
    work = has_work(store)
    reason = _guard_reason(guard) if work else None
    if reason:
        state["stop_reason"] = reason
    elif work and time.monotonic() < deadline:
        # Lease is committed before parsing. A crash cannot reset its attempts.
        state["processing"] = ProcessingQueue(store).process_one(registry_context)
        _collect(store, registry_context, deadline, guard, limits, state)
        if state["stop_reason"] == "no_due_work" and ProcessingQueue(store).has_work():
            state["stop_reason"] = "processing_pending"
    elif work:
        state["stop_reason"] = "admission_deadline"
    progress = bool(state["items"] or state["dispositions"] or state["processing"])
    result = {"result": "INCOMPLETE" if progress or state["stop_reason"] != "no_due_work" else "NO_WORK",
              **state, "network_called": bool(state["items"]), "codex_called": False,
              "attempts": len(state["items"]), "remaining": pending_counts(store),
              "elapsed_ms": max(0, round((time.monotonic() - started) * 1000)),
              "limits": {"attempts": limits.attempts, "body_bytes": limits.body_bytes, "maintenance": limits.maintenance,
                         "admission_seconds": ADMISSION_SECONDS, "receipt_reserve_seconds": RECEIPT_RESERVE_SECONDS},
              "legal_completeness": "unknown", "publication": "NOT_ATTEMPTED"}
    return {**result, "batch_sha256": digest(result)}


def _guard_reason(guard: Callable[[], str | None]) -> str | None:
    try:
        return guard()
    except Exception:
        return "operational_guard_unavailable"


def _collect(store, registry_context, deadline, guard, limits, state):
    queue = AcquisitionQueue(store)
    while len(state["items"]) < limits.attempts:
        remaining = deadline - time.monotonic()
        if remaining < 1 or state["charged_bytes"] >= limits.body_bytes:
            state["stop_reason"] = "admission_deadline" if remaining < 1 else "body_byte_budget"
            return
        reason = _guard_reason(guard)
        if reason:
            state["stop_reason"] = reason
            return
        candidate = queue.next_due(fair=True)
        if candidate:
            observations, hosts, proof = request_scope(store, candidate)
            if not observations and not hosts:
                if len(state["dispositions"]) >= limits.maintenance:
                    state["stop_reason"] = "maintenance_budget"
                    return
                if dispose_unrunnable(store, candidate, proof):
                    state["dispositions"].append({"request_id": candidate["request_id"], "reason": proof["reason"],
                                                   "disposition_sha256": digest(proof)})
                continue
        request = queue.claim(fair=True)
        if request is None:
            return
        item = _fetch_one(store, queue, request, deadline, guard, limits.body_bytes - state["charged_bytes"])
        state["items"].append(item)
        state["charged_bytes"] += item["charged_bytes"]
        state["actual_body_bytes"] += item["actual_body_bytes"]
        if item["error"] == "dns_deadline" or (item["error"] or "").startswith("operational_guard:"):
            state["stop_reason"] = item["error"]
            return
    state["stop_reason"] = "attempt_budget"


def _fetch_one(store, queue, request, deadline, guard, byte_allowance):
    observations, hosts, _ = request_scope(store, request)
    maximum = min(16 * 1024**2, byte_allowance)
    policy = FetchPolicy(max_bytes=maximum, timeout_seconds=min(30, max(0.001, deadline - time.monotonic())),
                         allowed_hosts=hosts or frozenset({"unresolved-scope.invalid"}),
                         request_guard=guard, deadline_monotonic=deadline)
    check_id = digest([request["request_id"], request["lease_id"]])
    check = acquire_document(store, request["document_id"], check_id=check_id, policy=policy)
    queue.finish(request, check_id, defer_processing=True)
    actual = 0
    if check["status"] == "fetched":
        actual = store.db.execute("SELECT byte_size FROM document_versions WHERE document_version_id=?",
                                   (check["document_version_id"],)).fetchone()[0]
    charged = actual if check["status"] == "fetched" else 0 if check["status"] == "unchanged" else maximum
    return {"request_id": request["request_id"], "check_id": check_id, "status": check["status"],
            "document_version_id": check["document_version_id"], "error": check["error_code"],
            "actual_body_bytes": actual, "charged_bytes": charged,
            "byte_accounting": "exact_body" if check["status"] in {"fetched", "unchanged"} else "reserved_unknown_partial_transfer",
            "extraction_status": "pending" if check["status"] in {"fetched", "unchanged"} else "unavailable"}


def validate_batch_receipt(receipt: dict) -> None:
    try:
        _validate_batch_receipt(receipt)
    except (TypeError, KeyError, AttributeError) as error:
        raise ValueError("Invalid bounded acquisition batch receipt") from error


def _validate_batch_receipt(receipt: dict) -> None:
    body = {key: value for key, value in receipt.items() if key not in {"schema_version", "input_sha256", "batch_sha256"}}
    limits = body["limits"]
    BatchLimits(limits["attempts"], limits["body_bytes"], limits["maintenance"])
    items = body["items"]
    if (len(canonical_json(receipt).encode('utf-8')) > MAX_BATCH_RECEIPT_BYTES
            or digest(body) != receipt.get("batch_sha256") or body["codex_called"] is not False
            or body["publication"] != "NOT_ATTEMPTED" or body["legal_completeness"] != "unknown"
            or limits["admission_seconds"] != ADMISSION_SECONDS or limits["receipt_reserve_seconds"] != RECEIPT_RESERVE_SECONDS
            or type(body["attempts"]) is not int or body["attempts"] != len(items) or len(items) > limits["attempts"]
            or len(body["dispositions"]) > limits["maintenance"] or body["network_called"] is not bool(items)
            or body["charged_bytes"] != sum(item["charged_bytes"] for item in items)
            or body["actual_body_bytes"] != sum(item["actual_body_bytes"] for item in items)
            or not 0 <= body["actual_body_bytes"] <= body["charged_bytes"] <= limits["body_bytes"]
            or any(type(item["charged_bytes"]) is not int or not 0 <= item["actual_body_bytes"] <= item["charged_bytes"] for item in items)):
        raise ValueError("Invalid bounded acquisition batch receipt")


def validate_batch_evidence(store: EvidenceStore, receipt: dict) -> None:
    """Controller readback checks the artifact against durable source-bound work."""
    seen = set()
    for item in receipt["items"]:
        row = store.db.execute(
            "SELECT c.* FROM acquisition_checks c JOIN acquisition_requests r ON r.document_id=c.document_id "
            "JOIN acquisition_events e ON e.request_id=r.request_id AND e.check_id=c.check_id "
            "JOIN acquisition_events lease ON lease.request_id=r.request_id AND lease.lease_id=e.lease_id "
            "WHERE r.request_id=? AND c.check_id=? AND e.status IN ('complete','retry_wait','blocked') "
            "AND lease.status='running' AND lease.sequence<e.sequence AND c.checked_at>=lease.observed_at "
            "AND c.checked_at<=e.observed_at AND e.observed_at<lease.lease_expires_at LIMIT 1",
            (item["request_id"], item["check_id"])).fetchone()
        if (not row or item["check_id"] in seen or row["status"] != item["status"]
                or row["document_version_id"] != item["document_version_id"] or row["error_code"] != item["error"]):
            raise ValueError("Batch item does not bind an accepted acquisition")
        seen.add(item["check_id"])
        size = store.db.execute("SELECT byte_size FROM document_versions WHERE document_version_id=?", (row["document_version_id"],)).fetchone()
        expected = size[0] if row["status"] == "fetched" else 0
        if item["actual_body_bytes"] != expected:
            raise ValueError("Batch body count does not bind retained bytes")
    for item in receipt["dispositions"]:
        row = store.db.execute("SELECT * FROM acquisition_dispositions WHERE request_id=?", (item["request_id"],)).fetchone()
        if not row or row["reason"] != item["reason"] or digest(json.loads(row["evidence_json"])) != item["disposition_sha256"]:
            raise ValueError("Batch disposition does not bind its complete proof")
    processing = receipt.get("processing")
    if processing:
        ProcessingQueue(store).validate_receipt(processing)
