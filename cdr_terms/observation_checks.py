"""Acquisition coverage belongs to an exact observed product snapshot."""
from __future__ import annotations

from typing import Any, Mapping

from .identity import digest
from .store import EvidenceStore


def current_observation(store: EvidenceStore, product_key: str) -> dict[str, Any]:
    """Unfinished capture writes are evidence, not current source authority."""
    rows = store.db.execute(
        "SELECT o.* FROM observations o WHERE product_key=? AND (EXISTS "
        "(SELECT 1 FROM ingest_captures c WHERE c.ingest_id=o.ingest_id) OR (NOT EXISTS "
        "(SELECT 1 FROM ingest_capture_attempts a WHERE a.ingest_id=o.ingest_id) AND NOT EXISTS "
        "(SELECT 1 FROM acquisition_requests r WHERE r.ingest_id=o.ingest_id))) "
        "ORDER BY observed_at DESC, observation_id DESC LIMIT 2", (product_key,)).fetchall()
    if not rows:
        raise ValueError("Product has no retained source inventory")
    if len(rows) > 1 and rows[0]["observed_at"] == rows[1]["observed_at"]:
        raise ValueError("Product has ambiguous current source observations")
    return dict(rows[0])


def bind_manual_check(store: EvidenceStore, observation_id: str, check_id: str) -> None:
    """Only the explicit observation fetch controller calls this after acquisition."""
    row = store.db.execute(
        "SELECT c.checked_at,o.observed_at FROM acquisition_checks c JOIN applicability a USING(document_id) "
        "JOIN observations o USING(observation_id) WHERE c.check_id=? AND o.observation_id=?",
        (check_id, observation_id)).fetchone()
    if not row or row["checked_at"] < row["observed_at"]:
        raise ValueError("Acquisition check does not bind the selected observation time and document")
    with store.db:
        store.db.execute("INSERT OR IGNORE INTO observation_acquisitions VALUES (?,?)", (observation_id, check_id))


def selected_check(store: EvidenceStore, observation: Mapping[str, Any], document_id: str, *,
                   successful_only: bool = False) -> dict[str, Any] | None:
    """Ignore orphan writes and other ingests; retain accepted acquisition even if extraction failed."""
    observation_id = observation["observation_id"]
    candidates = store.db.execute(
        "SELECT DISTINCT c.* FROM acquisition_checks c JOIN acquisition_events e USING(check_id) "
        "JOIN acquisition_requests r USING(request_id) JOIN acquisition_bindings b USING(request_id) "
        "WHERE b.observation_id=? AND r.ingest_id=? AND r.document_id=? AND c.document_id=r.document_id "
        "AND e.status IN ('complete','retry_wait','blocked') AND e.lease_id IS NOT NULL "
        "AND c.checked_at>=? AND EXISTS (SELECT 1 FROM acquisition_events lease WHERE lease.request_id=r.request_id "
        "AND lease.status='running' AND lease.lease_id=e.lease_id AND lease.sequence<e.sequence "
        "AND c.checked_at>=lease.observed_at AND c.checked_at<=e.observed_at AND e.observed_at<lease.lease_expires_at) "
        "UNION SELECT c.* FROM acquisition_checks c JOIN observation_acquisitions b USING(check_id) "
        "WHERE b.observation_id=? AND c.document_id=? AND c.checked_at>=?",
        (observation_id, observation["ingest_id"], document_id, observation["observed_at"],
         observation_id, document_id, observation["observed_at"])).fetchall()
    # The complete raw CDR response is captured by this exact observation, even
    # if another observation has since seen this same endpoint or byte version.
    raw = store.db.execute(
        "SELECT c.* FROM acquisition_checks c JOIN document_versions v USING(document_version_id) "
        "JOIN applicability a ON a.document_id=c.document_id WHERE a.observation_id=? AND a.relation='cdr_source' "
        "AND c.check_id=? AND c.document_id=? AND v.content_sha256=? AND c.checked_at=?",
        (observation_id, digest([observation_id, "source_response"]), document_id,
         observation["source_sha256"], observation["observed_at"])).fetchone()
    if raw:
        candidates.append(raw)
    if successful_only:
        candidates = [row for row in candidates if row["status"] in {"fetched", "unchanged"}]
    return dict(max(candidates, key=lambda row: (row["checked_at"], row["sequence"]))) if candidates else None


def context_document_state(store: EvidenceStore, document_id: str, version_id: str,
                           context: Mapping[str, Any]) -> str:
    """One current job must match every product's admitted source and document.

    Old failed checks cannot prove a replacement. Orphan writes and incomplete
    captures remain archived but never supersede an accepted current source.
    Historical jobs use their separately validated immutable target instead.
    """
    keys = context.get("product_keys")
    sources = context.get("source_product_sha256")
    if (not isinstance(keys, list) or not keys or len(set(keys)) != len(keys)
            or not isinstance(sources, dict) or any(not isinstance(sources.get(key), str) for key in keys)):
        # Legacy/unbound analysis can remain private staging; revision admission
        # independently rejects it. Do not invent a product binding for it.
        latest = store.last_success(document_id)
        return "current" if latest and latest["document_version_id"] == version_id else "superseded"
    pending = False
    for key in keys:
        try:
            observation = current_observation(store, key)
        except ValueError:
            observation = None
        if not observation or sources[key] != observation["source_sha256"]:
            waiting = store.db.execute(
                "SELECT 1 FROM observations o JOIN ingest_capture_attempts a USING(ingest_id) "
                "WHERE o.product_key=? AND o.source_sha256=? AND o.observed_at>=? "
                "AND NOT EXISTS (SELECT 1 FROM ingest_captures c WHERE c.ingest_id=o.ingest_id) LIMIT 1",
                (key, sources[key], observation["observed_at"] if observation else "")).fetchone()
            if not waiting:
                return "superseded"
            pending = True
            continue
        check = selected_check(store, observation, document_id, successful_only=True)
        if not check:
            pending = True
        elif check["document_version_id"] != version_id:
            candidate = store.db.execute(
                "SELECT checked_at,sequence FROM acquisition_checks WHERE document_id=? AND document_version_id=? "
                "AND status IN ('fetched','unchanged') ORDER BY checked_at DESC,sequence DESC LIMIT 1",
                (document_id, version_id)).fetchone()
            if candidate and (candidate["checked_at"], candidate["sequence"]) > (check["checked_at"], check["sequence"]):
                # A newer candidate may have queued analysis just before its
                # acquisition lease completes. Waiting never grants authority.
                pending = True
            else:
                return "superseded"
    return "pending" if pending else "current"
