"""Each ingest schedules a fresh document check, independent of CDR lastUpdated."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta
from typing import Any, Mapping

from .acquisition import FetchPolicy, acquire_document
from .extraction import extract_version
from .identity import digest, timestamp, utc_now
from .queue import TermsQueue
from .store import EvidenceStore


def _after(now: str, seconds: int) -> str:
    return timestamp((datetime.fromisoformat(now.replace("Z", "+00:00")) + timedelta(seconds=seconds)).isoformat())


class AcquisitionQueue:
    def __init__(self, store: EvidenceStore):
        self.store = store

    def enqueue(self, observation_id: str, *, ingest_id: str, now: str,
                priority: int = 1) -> list[str]:
        observed = timestamp(now)
        if not ingest_id or priority not in (0, 1, 2):
            raise ValueError("Acquisition requires an ingest identity and valid priority")
        observation = self.store.db.execute("SELECT ingest_id FROM observations WHERE observation_id=?", (observation_id,)).fetchone()
        if not observation or observation[0] != ingest_id:
            raise ValueError("Acquisition request must bind its actual source ingest")
        ids = []
        with self.store.db:
            for row in self.store.db.execute("SELECT DISTINCT document_id FROM applicability "
                                             "WHERE observation_id=? AND relation!='cdr_source' ORDER BY document_id", (observation_id,)):
                identity = digest([ingest_id, row[0]])
                self.store.db.execute("INSERT OR IGNORE INTO acquisition_requests VALUES (?,?,?,?,?)",
                                      (identity, row[0], ingest_id, observed, priority))
                self.store.db.execute("INSERT OR IGNORE INTO acquisition_bindings VALUES (?,?)", (identity, observation_id))
                if not self.store.db.execute("SELECT 1 FROM acquisition_events WHERE request_id=?", (identity,)).fetchone():
                    self._event(identity, "queued", observed)
                ids.append(identity)
        return ids

    def _event(self, request_id: str, status: str, now: str, *, retry_after: str | None = None,
               lease_id: str | None = None, expiry: str | None = None,
               check_id: str | None = None, error_code: str | None = None) -> None:
        values = (request_id, status, now, retry_after, lease_id, expiry, check_id, error_code)
        self.store.db.execute("INSERT OR IGNORE INTO acquisition_events "
                              "(event_id,request_id,status,observed_at,retry_after,lease_id,lease_expires_at,check_id,error_code) "
                              "VALUES (?,?,?,?,?,?,?,?,?)", (digest(values), *values))

    def next_due(self, now: str | None = None) -> dict[str, Any] | None:
        row = self.store.db.execute(
            "SELECT r.*,e.status,e.retry_after FROM acquisition_requests r JOIN acquisition_events e ON "
            "e.sequence=(SELECT MAX(sequence) FROM acquisition_events WHERE request_id=r.request_id) "
            "WHERE (e.status='queued' OR (e.status='retry_wait' AND e.retry_after<=?)) "
            "AND EXISTS (SELECT 1 FROM ingest_captures c WHERE c.ingest_id=r.ingest_id) "
            "ORDER BY r.priority,r.created_at,r.request_id LIMIT 1", (timestamp(now or utc_now()),)).fetchone()
        return dict(row) if row else None

    def claim(self, now: str | None = None, *, lease_seconds: int = 180) -> dict[str, Any] | None:
        if not 1 <= lease_seconds <= 900:
            raise ValueError("Acquisition lease must be between one second and 15 minutes")
        observed = timestamp(now or utc_now())
        with self.store.db:
            self.store.db.execute("BEGIN IMMEDIATE")
            expired = self.store.db.execute(
                "SELECT e.* FROM acquisition_events e WHERE e.sequence=(SELECT MAX(sequence) FROM acquisition_events WHERE request_id=e.request_id) "
                "AND e.status='running' AND e.lease_expires_at<=?", (observed,)).fetchall()
            for row in expired:
                self._event(row["request_id"], "retry_wait", observed, retry_after=observed, error_code="acquisition_lease_expired")
            request = self.next_due(observed)
            if request is None:
                return None
            lease_id = secrets.token_hex(32)
            expiry = _after(observed, lease_seconds)
            self._event(request["request_id"], "running", observed, lease_id=lease_id, expiry=expiry)
            return {**request, "status": "running", "lease_id": lease_id, "lease_expires_at": expiry}

    def finish(self, request: Mapping[str, Any], check_id: str, *, now: str | None = None,
               processing_error: str | None = None) -> None:
        observed = timestamp(now or utc_now())
        with self.store.db:
            self.store.db.execute("BEGIN IMMEDIATE")
            latest = self.store.db.execute("SELECT * FROM acquisition_events WHERE request_id=? ORDER BY sequence DESC LIMIT 1",
                                           (request["request_id"],)).fetchone()
            if (not latest or latest["status"] != "running" or latest["lease_id"] != request["lease_id"]
                    or latest["lease_expires_at"] <= observed):
                raise ValueError("Acquisition lease expired or replaced; stale completion rejected")
            check = self.store.db.execute("SELECT * FROM acquisition_checks WHERE check_id=? AND document_id=?",
                                          (check_id, request["document_id"])).fetchone()
            if not check:
                raise ValueError("Acquisition result does not bind this document")
            successful = check["status"] in {"fetched", "unchanged"} and not processing_error
            attempts = self.store.db.execute("SELECT COUNT(*) FROM acquisition_events WHERE request_id=? AND status='running'",
                                             (request["request_id"],)).fetchone()[0]
            status = "complete" if successful else "blocked" if attempts >= 4 else "retry_wait"
            self._event(request["request_id"], status, observed, lease_id=request["lease_id"], check_id=check_id,
                        retry_after=_after(observed, min(3600, 300 * 2 ** (attempts - 1))) if status == "retry_wait" else None,
                        error_code=processing_error or check["error_code"])


def enqueue_interpretation(store: EvidenceStore, version_id: str, observation_ids: list[str], *,
                           priority: int, registry_context: Mapping[str, Any]) -> str:
    extraction = extract_version(store, version_id)
    row = store.db.execute("SELECT * FROM extractions WHERE extraction_id=?", (extraction,)).fetchone()
    if row["status"] == "failed" or not store.read_blob(row["text_sha256"]):
        raise ValueError("document_extraction_requires_review_or_supported_extractor")
    products: dict[str, str] = {}
    for observation_id in observation_ids:
        observation = store.db.execute("SELECT product_key,source_sha256 FROM observations WHERE observation_id=?", (observation_id,)).fetchone()
        if not observation:
            raise ValueError("Document request references a missing source observation")
        if observation[0] in products and products[observation[0]] != observation[1]:
            raise ValueError("Ambiguous product source context requires review")
        products[observation[0]] = observation[1]
    context = {**registry_context, "product_keys": sorted(products), "source_product_sha256": products}
    return TermsQueue(store).enqueue(extraction, context, priority=priority)


def process_next_acquisition(store: EvidenceStore, *, registry_context: Mapping[str, Any],
                              policy: FetchPolicy | None = None) -> dict[str, Any]:
    """One bounded document, no model call. Runtime admission belongs to caller."""
    queue = AcquisitionQueue(store)
    request = queue.claim()
    if request is None:
        return {"result": "NO_WORK", "network_called": False, "codex_called": False}
    previous = store.last_success(request["document_id"])
    check_id = digest([request["request_id"], request["lease_id"]])
    check = acquire_document(store, request["document_id"], check_id=check_id, policy=policy)
    processing_error = None
    job_id = None
    if check["status"] in {"fetched", "unchanged"}:
        observations = [row[0] for row in store.db.execute("SELECT observation_id FROM acquisition_bindings WHERE request_id=? ORDER BY observation_id",
                                                          (request["request_id"],))]
        changed = previous is None or previous["document_version_id"] != check["document_version_id"]
        try:
            job_id = enqueue_interpretation(store, check["document_version_id"], observations,
                                            priority=2 if request["priority"] == 2 else 0 if changed else 1,
                                            registry_context=registry_context)
        except ValueError as exc:
            processing_error = str(exc)
    queue.finish(request, check_id, processing_error=processing_error)
    return {"result": "QUEUED_ANALYSIS" if job_id else "INCOMPLETE", "request_id": request["request_id"],
            "check_id": check_id, "analysis_job_id": job_id, "error": processing_error or check["error_code"],
            "network_called": True, "codex_called": False}
