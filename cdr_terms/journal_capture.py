"""Explicit offline capture of reconciled, retained original journal responses."""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from cdr_atomic import atomic_write_json
from cdr_export_contract import load_contract

from .acquisitions_queue import AcquisitionQueue, enqueue_interpretation
from .capture_provenance import begin_capture
from .identity import byte_digest, canonical_json, digest, timestamp, utc_now
from .ingest import _outside_sources, registry_context
from .journal_preflight import product_identity_index, verify_finalization
from .journal_reconciliation import reconcile_export
from .journal_sources import _read_detail_sources
from .store import EvidenceStore


def _complete_verified_receipt(store: EvidenceStore, path: Path, receipt: dict) -> None:
    with path.open("rb") as stream:
        raw = stream.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024 or json.loads(raw) != receipt:
        raise ValueError("journal_capture_receipt_changed_before_completion")
    sha = store.put_blob(raw)
    with store.db:
        store.db.execute("INSERT OR IGNORE INTO ingest_captures VALUES (?,?,?,?)",
                         (receipt["generation_id"], sha, utc_now(), receipt["products"]))
        previous = store.db.execute("SELECT receipt_sha256 FROM ingest_captures WHERE ingest_id=?",
                                    (receipt["generation_id"],)).fetchone()[0]
        if previous != sha:
            raise ValueError("completed_terms_capture_identity_changed")


def capture_journal(archive: Path, contract_path: Path, marker_path: Path, event_path: Path,
                    export_path: Path, root: Path, *, artifact_path: str,
                    forbidden_roots: list[Path], max_seconds: float = 120) -> dict:
    """No network or model calls; a failed operation never issues a receipt.

    Captures the finalized selected product set, not missing provider populations.
    Existing banks-based capture paths and immutable source files are untouched.
    """
    if not 0 < max_seconds <= 300:
        raise ValueError("journal_capture_invalid_time_bound")
    started = time.monotonic()
    root = root.expanduser().resolve()
    _outside_sources(root, [p.resolve().parent for p in (archive, contract_path, marker_path, event_path, export_path)] + forbidden_roots)
    contract = load_contract(contract_path)
    def bounded_json(path):
        with path.open("rb") as stream:
            body = stream.read(4 * 1024 * 1024 + 1)
        if len(body) > 4 * 1024 * 1024:
            raise ValueError("journal_capture_metadata_bound")
        return json.loads(body)
    marker, event = bounded_json(marker_path), bounded_json(event_path)
    sources = _read_detail_sources(archive, contract)
    finalization = verify_finalization(contract, marker, event, detail_products=len(sources))
    reconciliation = reconcile_export(contract, sources, export_path, artifact_path=artifact_path)
    identities = product_identity_index(contract, sources)
    instant = timestamp(contract["observed_at"])
    day = datetime.fromisoformat(instant.replace("Z", "+00:00")).astimezone(ZoneInfo(contract["timezone"])).date().isoformat()
    if day != contract["observation_date"]:
        raise ValueError("journal_capture_source_calendar_mismatch")
    contract_body = (canonical_json(contract) + "\n").encode("utf-8")
    provenance = {"basis": "finalized_source_generation", "timezone": contract["timezone"],
                  "contract_sha256": byte_digest(contract_body), "contract_digest": contract["contract_digest"]}
    generation = contract["generation_id"]
    receipt_path = root / "captures" / (digest(generation) + ".json")
    if time.monotonic() - started > max_seconds:
        raise ValueError("journal_capture_time_bound")
    with EvidenceStore(root) as store:
        if receipt_path.exists():
            receipt = bounded_json(receipt_path)
            expected_members = [{"relative_path": s.relative_path, "event_path": s.event_path,
                                 "sha256": s.sha256, "product_key": i["product_key"],
                                 "observation_id": digest([generation, s.provider, i["product_key"], instant, s.sha256])}
                                for s, i in zip(sources, identities, strict=True)]
            if (receipt.get("source_provenance") != provenance or receipt.get("journal_reconciliation") != reconciliation
                    or receipt.get("journal_finalization") != finalization
                    or receipt.get("sources") != expected_members or receipt.get("products") != len(sources)
                    or receipt.get("generation_id") != generation or receipt.get("observed_at") != instant
                    or receipt.get("source_run_date") != contract["observation_date"]
                    or receipt.get("export_contract_digest") != contract["contract_digest"]
                    or receipt.get("observation_state") != contract["observation_state"]
                    or receipt.get("full_population_accounting") is not False
                    or receipt.get("status") != "CAPTURED_AND_QUEUED"):
                raise ValueError("journal_capture_existing_identity_mismatch")
            for source in receipt["sources"]:
                store.read_blob(source["sha256"])
            _complete_verified_receipt(store, receipt_path, receipt)
            return receipt
        store.put_blob(contract_body)
        captured_at = begin_capture(store, generation, instant, utc_now(), provenance)
        members = []; acquisition_ids = set(); analysis_ids = set()
        context = registry_context()
        for source, identity in zip(sources, identities, strict=True):
            if time.monotonic() - started > max_seconds:
                raise ValueError("journal_capture_time_bound")
            observation = store.observe(provider=source.provider, product_key=identity["product_key"],
                                        record=json.loads(source.body), source_bytes=source.body,
                                        observed_at=instant, ingest_id=generation)
            acquisition_ids.update(AcquisitionQueue(store).enqueue(observation, ingest_id=generation, now=captured_at))
            versions = store.db.execute("SELECT v.document_version_id FROM applicability a JOIN document_versions v USING(document_id) "
                                       "WHERE a.observation_id=? AND a.relation='cdr_source' AND v.content_sha256=?",
                                       (observation, source.sha256)).fetchall()
            for version in versions:
                analysis_ids.add(enqueue_interpretation(store, version[0], [observation], priority=1, registry_context=context))
            members.append({"relative_path": source.relative_path, "event_path": source.event_path,
                            "sha256": source.sha256, "observation_id": observation, "product_key": identity["product_key"]})
        receipt = {"schema_version": 1, "status": "CAPTURED_AND_QUEUED", "generation_id": generation,
                   "export_contract_digest": contract["contract_digest"], "source_run_date": contract["observation_date"],
                   "observed_at": instant, "captured_at": captured_at, "source_provenance": provenance,
                   "products": len(members), "source_bytes": sum(len(s.body) for s in sources), "sources": members,
                   "acquisition_requests": len(acquisition_ids), "analysis_jobs": len(analysis_ids),
                   "journal_finalization": finalization, "journal_reconciliation": reconciliation,
                   "observation_state": contract["observation_state"], "full_population_accounting": False,
                   "network_called": False, "codex_called": False}
        if time.monotonic() - started > max_seconds:
            raise ValueError("journal_capture_time_bound")
        receipt_path.parent.mkdir(exist_ok=True, mode=0o700)
        atomic_write_json(receipt_path, receipt, create_once=True)
        _complete_verified_receipt(store, receipt_path, receipt)
        return receipt
