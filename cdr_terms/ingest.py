"""No-network finalization hook: preserve full raw responses before RAM cleanup."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Mapping

from cdr_atomic import atomic_write_json
from cdr_clean_export import bank_base_row, inner_record
from cdr_product_facts import NORMALIZATION_VERSION

from .acquisitions_queue import AcquisitionQueue, enqueue_interpretation
from .capture_provenance import begin_capture, source_time
from .identity import byte_digest, digest, utc_now
from .store import EvidenceStore


def registry_context() -> dict[str, Any]:
    return {"document_schema_version": 1, "structured_fact_normalization": NORMALIZATION_VERSION,
            "interpretation_contract": "analysis-staging-v1", "executable_rules": "unapproved"}


def _outside_sources(root: Path, source_roots: list[Path]) -> None:
    for source in source_roots:
        resolved = source.resolve()
        if root == resolved or resolved in root.parents or root in resolved.parents:
            raise ValueError("terms_archive_must_be_separate_from_source_and_ledger_trees")


def _existing_capture(store: EvidenceStore, receipt: Mapping[str, Any], finalized: Mapping[str, Any],
                      run_root: Path) -> dict[str, Any]:
    if receipt["export_contract_digest"] != finalized["export_contract_digest"]:
        raise ValueError("finalized_generation_source_identity_changed")
    for entry in receipt["sources"]:
        store.read_blob(entry["sha256"])
        raw = run_root / entry["relative_path"]
        if raw.exists() and byte_digest(raw.read_bytes()) != entry["sha256"]:
            raise ValueError("raw_source_changed_after_terms_capture")
    return dict(receipt)


def _complete_capture(store: EvidenceStore, path: Path, receipt: Mapping[str, Any]) -> None:
    sha = store.put_blob(path.read_bytes())
    with store.db:
        store.db.execute("INSERT OR IGNORE INTO ingest_captures VALUES (?,?,?,?)",
                         (receipt["generation_id"], sha, utc_now(), receipt["products"]))
        previous = store.db.execute("SELECT receipt_sha256 FROM ingest_captures WHERE ingest_id=?", (receipt["generation_id"],)).fetchone()[0]
        if previous != sha:
            raise ValueError("completed_terms_capture_identity_changed")


def capture_finalized(run_root: Path, finalized: Mapping[str, Any], root: Path, *,
                      forbidden_roots: list[Path], observed_at: str | None = None,
                      state_dir: Path | None = None,
                      max_products: int = 10000, max_total_bytes: int = 512 * 1024 * 1024,
                      max_seconds: float = 120) -> dict[str, Any]:
    """Archive all raw products or fail explicitly; never truncate a capture."""
    root = root.expanduser().resolve()
    run_root = run_root.resolve()
    _outside_sources(root, [run_root, *forbidden_roots])
    if (finalized.get("finalization_schema_version") != 2 or finalized.get("ledger_state") != "finalized"
            or not finalized.get("generation_id") or not finalized.get("export_contract_digest")):
        raise ValueError("terms_capture_requires_a_finalized_source_generation")
    if not 1 <= max_products <= 20000 or not 0 < max_seconds <= 300:
        raise ValueError("invalid_terms_capture_bounds")
    generation = finalized["generation_id"]
    receipt_path = root / "captures" / (digest(generation) + ".json")
    # A configured ingest must verify its finalized clock even on retry. Direct
    # explicit imports reuse an already immutable receipt without redating it.
    timing = source_time(finalized, state_dir=state_dir, observed_at=None) if observed_at is None else None
    with EvidenceStore(root) as store:
        if receipt_path.exists():
            receipt = _existing_capture(store, json.loads(receipt_path.read_text(encoding="utf-8")), finalized, run_root)
            if timing and (receipt["observed_at"] != timing[0] or receipt.get("source_provenance") != timing[1]):
                raise ValueError("source_observation_legacy_capture_requires_explicit_review")
            _complete_capture(store, receipt_path, receipt)
            return receipt
        observation_time, provenance, contract_body = timing or source_time(finalized, state_dir=state_dir, observed_at=observed_at)
        if contract_body is not None:
            store.put_blob(contract_body)
        captured_at = begin_capture(store, generation, observation_time, utc_now(), provenance)
        banks = run_root / "banks"
        if not banks.is_dir():
            raise ValueError("complete_raw_product_source_is_unavailable")
        started = time.monotonic()
        sources: list[dict[str, Any]] = []
        acquisition_ids: set[str] = set()
        analysis_ids: set[str] = set()
        total_bytes = 0
        for path in sorted(banks.rglob("product-detail.json")):
            if (path.is_symlink() or banks.resolve() not in path.resolve().parents
                    or len(sources) >= max_products or time.monotonic() - started > max_seconds):
                raise ValueError("complete_terms_capture_exceeds_safe_bounds")
            size = path.stat().st_size
            if size > 16 * 1024 * 1024 or total_bytes + size > max_total_bytes:
                raise ValueError("complete_terms_capture_exceeds_byte_budget")
            body = path.read_bytes()
            payload = json.loads(body)
            record = inner_record(payload)
            base = bank_base_row(path, banks, record)
            observation_id = store.observe(provider=base["provider"], product_key=base["product_key"],
                                             record=payload, source_bytes=body, observed_at=observation_time, ingest_id=generation)
            acquisition_ids.update(AcquisitionQueue(store).enqueue(observation_id, ingest_id=generation, now=captured_at))
            raw_versions = store.db.execute("SELECT v.document_version_id FROM applicability a JOIN document_versions v USING(document_id) "
                                            "WHERE a.observation_id=? AND a.relation='cdr_source' AND v.content_sha256=?",
                                            (observation_id, byte_digest(body))).fetchall()
            for version in raw_versions:
                analysis_ids.add(enqueue_interpretation(store, version[0], [observation_id], priority=1,
                                                        registry_context=registry_context()))
            total_bytes += len(body)
            sources.append({"relative_path": path.relative_to(run_root).as_posix(), "sha256": byte_digest(body),
                            "observation_id": observation_id, "product_key": base["product_key"]})
        if not sources:
            raise ValueError("complete_terms_capture_has_no_products")
        expected = finalized.get("banks", {}).get("products")
        if expected is not None and len(sources) != expected:
            raise ValueError("terms_source_count_disagrees_with_finalized_products")
        receipt = {"schema_version": 1, "status": "CAPTURED_AND_QUEUED", "generation_id": generation,
                   "export_contract_digest": finalized["export_contract_digest"], "source_run_date": finalized.get("run_date"),
                   "observed_at": observation_time, "captured_at": captured_at, "source_provenance": provenance,
                   "products": len(sources), "source_bytes": total_bytes,
                   "acquisition_requests": len(acquisition_ids), "analysis_jobs": len(analysis_ids),
                   "sources": sources, "network_called": False, "codex_called": False}
        receipt_path.parent.mkdir(exist_ok=True, mode=0o700)
        atomic_write_json(receipt_path, receipt, create_once=True)
        _complete_capture(store, receipt_path, receipt)
        return receipt


def capture_if_configured(run_root: Path, finalized: Mapping[str, Any], *, state_dir: Path,
                           runs_root: Path, export_root: Path) -> dict[str, Any] | None:
    configured = os.environ.get("AR_LOCAL_TERMS_ROOT", "").strip()
    if not configured:
        return None
    try:
        receipt = capture_finalized(run_root, finalized, Path(configured),
                                    forbidden_roots=[state_dir, runs_root, export_root], state_dir=state_dir)
        receipt_path = Path(configured).expanduser().resolve() / "captures" / (digest(finalized["generation_id"]) + ".json")
        return {**{key: value for key, value in receipt.items() if key != "sources"},
                "receipt_path": str(receipt_path), "receipt_sha256": byte_digest(receipt_path.read_bytes())}
    except Exception as error:
        # Rate finalization already succeeded. Preserve raw RAM stage and report
        # this separate failure without changing the immutable completion marker.
        receipt = {"schema_version": 1, "status": "CAPTURE_FAILED", "generation_id": finalized.get("generation_id"),
                   "source_run_date": finalized.get("run_date"), "error_code": type(error).__name__,
                   "reason": str(error), "raw_stage_preserved": True, "network_called": False, "codex_called": False}
        failure_path = state_dir / "terms-capture-receipts" / (digest(receipt) + ".json")
        failure_path.parent.mkdir(parents=True, exist_ok=True)
        if not failure_path.exists():
            atomic_write_json(failure_path, receipt, create_once=True)
        return receipt


def retry_capture_if_configured(marker_path: Path, *, state_dir: Path, runs_root: Path) -> dict[str, Any] | None:
    """Resume a failed derived capture without rerunning a finalized ingest."""
    if not os.environ.get("AR_LOCAL_TERMS_ROOT", "").strip():
        return None
    finalized = json.loads(marker_path.read_text(encoding="utf-8"))
    date = finalized["run_date"]
    export_root = Path(finalized["out_dir"])
    if finalized.get("ram_staged"):
        run_root = Path(finalized["ram_root"]) / "runs" / date
    else:
        primary = runs_root / date / "_exports"
        run_root = runs_root / date if export_root.resolve() == primary.resolve() else export_root.parent / date
    return capture_if_configured(run_root, finalized, state_dir=state_dir, runs_root=runs_root, export_root=export_root)
