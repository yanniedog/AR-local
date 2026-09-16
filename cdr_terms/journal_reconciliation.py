"""Reconcile original journal details with a contract-bound legacy export."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from cdr_clean_export import clean_value, inner_record, official_product_links

from .journal_preflight import product_identity_index
from .journal_sources import JournalSource


def reconcile_export(contract: Mapping[str, Any], sources: tuple[JournalSource, ...],
                     export_path: Path, *, artifact_path: str) -> dict[str, Any]:
    """Compare selected products; this does not establish unavailable populations.

    Raw bytes remain authoritative. The legacy projection intentionally omits
    some source content, so it must never be imported as an original response.
    """
    if contract.get("normalization_version") != "legacy-v1":
        raise ValueError("journal_export_normalization_unsupported")
    matching = [a for a in contract["artifacts"] if a["path"] == artifact_path]
    if len(matching) != 1 or not 0 < matching[0]["bytes"] <= 128 * 1024 * 1024:
        raise ValueError("journal_export_artifact_invalid")
    expected = matching[0]
    with export_path.open("rb") as stream:
        raw = stream.read(expected["bytes"] + 1)
    if len(raw) != expected["bytes"] or hashlib.sha256(raw).hexdigest() != expected["sha256"]:
        raise ValueError("journal_export_integrity_mismatch")
    document = json.loads(raw)
    if document.get("run_date") != contract["observation_date"]:
        raise ValueError("journal_export_date_mismatch")
    products = document.get("products")
    if not isinstance(products, list) or len(products) != len(sources):
        raise ValueError("journal_export_product_count_mismatch")
    identities = product_identity_index(contract, sources)
    by_key = {(s.provider, s.product_id): s for s in sources}
    export_keys = {(row["provider"], row["product_id"]): row["product_key"] for row in identities}
    seen = set()
    for product in products:
        key = (product.get("provider"), product.get("product_id"))
        if key in seen or key not in by_key or product.get("product_key") != export_keys[key]:
            raise ValueError("journal_export_product_identity_mismatch")
        seen.add(key)
        record = inner_record(json.loads(by_key[key].body))
        projected = clean_value(record)
        links = official_product_links(record)
        if links:
            projected["additionalInformation"] = links
        if json.loads(product["details_json"]) != projected:
            raise ValueError("journal_export_detail_projection_mismatch")
    if seen != by_key.keys():
        raise ValueError("journal_export_product_set_mismatch")
    return {"status": "SELECTED_PRODUCT_EXPORT_RECONCILED", "products": len(sources),
            "artifact_path": artifact_path, "artifact_sha256": expected["sha256"],
            "projection": "legacy-v1-clean-value-with-official-product-links",
            "observation_state": contract["observation_state"],
            "full_population_accounting": False, "original_response_bytes_required": True}
