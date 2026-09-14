"""Pinned historical interpretation inputs; no term review or promotion API."""
from __future__ import annotations

from typing import Any, Mapping

from .identity import digest, exact_value
from .store import EvidenceStore


def build_historical_target(store: EvidenceStore, extraction_id: str,
                            observation_ids: list[str]) -> dict[str, Any]:
    """Pin observed evidence, never infer when its clauses legally applied."""
    if (not isinstance(observation_ids, list) or not 1 <= len(observation_ids) <= 1000
            or any(not isinstance(item, str) for item in observation_ids)
            or len(set(observation_ids)) != len(observation_ids)):
        raise ValueError("Historical target requires 1-1000 unique observation identities")
    source = store.db.execute(
        "SELECT x.*,v.document_id,v.content_sha256,v.observed_at AS document_observed_at "
        "FROM extractions x JOIN document_versions v USING(document_version_id) WHERE extraction_id=?",
        (extraction_id,)).fetchone()
    if not source or source["status"] not in {"partial", "complete"}:
        raise ValueError("Historical target requires a retained usable extraction")
    store.read_blob(source["content_sha256"])
    if not store.read_blob(source["text_sha256"]):
        raise ValueError("Historical extraction has no retained text")
    observations = []
    for identity in sorted(observation_ids):
        row = store.db.execute("SELECT * FROM observations WHERE observation_id=?", (identity,)).fetchone()
        relations = store.db.execute("SELECT relation FROM applicability WHERE observation_id=? AND document_id=?",
                                     (identity, source["document_id"])).fetchall()
        if not row or not relations:
            raise ValueError("Historical observation does not reference its pinned document")
        if all(item[0] == "cdr_source" for item in relations) and row["source_sha256"] != source["content_sha256"]:
            raise ValueError("Historical CDR version differs from the pinned raw snapshot")
        store.read_blob(row["source_sha256"])
        observations.append({key: row[key] for key in (
            "observation_id", "product_key", "source_sha256", "observed_at", "ingest_id")})
        observations[-1]["observation_date_utc"] = row["observed_at"][:10]
    target = {"schema_version": 1, "scope": "historical_only",
              "document_version_id": source["document_version_id"],
              "document_content_sha256": source["content_sha256"],
              "document_observed_at": source["document_observed_at"],
              "extraction_id": extraction_id, "extraction_text_sha256": source["text_sha256"],
              "extractor_version": source["extractor_version"], "observations": observations}
    target["target_sha256"] = digest(target)
    return target


def validate_historical_target(store: EvidenceStore, extraction_id: str,
                               context: Mapping[str, Any]) -> dict[str, Any]:
    target = context.get("historical_target")
    if not isinstance(target, dict) or not isinstance(target.get("observations"), list):
        raise ValueError("Historical target is missing its immutable snapshot")
    exact_value(target)
    try:
        expected = build_historical_target(store, extraction_id,
                                            [row["observation_id"] for row in target["observations"]])
    except (KeyError, TypeError) as exc:
        raise ValueError("Historical observation pin is malformed") from exc
    declared = target.get("target_sha256")
    if (declared != digest({key: value for key, value in target.items() if key != "target_sha256"})
            or digest(target) != digest(expected)):
        raise ValueError("Historical target differs from its immutable evidence pin")
    products: dict[str, str] = {}
    for row in expected["observations"]:
        if row["product_key"] in products and products[row["product_key"]] != row["source_sha256"]:
            raise ValueError("Historical job mixes different snapshots of the same product")
        products[row["product_key"]] = row["source_sha256"]
    if context.get("product_keys") != sorted(products) or context.get("source_product_sha256") != products:
        raise ValueError("Historical product scope differs from its pinned observations")
    return expected


def historical_scope(target: Mapping[str, Any]) -> dict[str, Any]:
    """Required on both staged model output and the controller's receipt."""
    return {"scope": "historical_only", "target_sha256": target["target_sha256"],
            "document_version_id": target["document_version_id"], "extraction_id": target["extraction_id"],
            "observation_dates_utc": sorted({row["observation_date_utc"] for row in target["observations"]})}
