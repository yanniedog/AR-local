"""Explicit partial index capture; strict reuse/withdrawal validation stays intact."""
from __future__ import annotations

import hashlib
from typing import Any

from cdr_compatibility import response_shape_error

MAX_PARTIAL_INDEX_ROWS = 8192


def partial_index_evidence(data: Any) -> dict | None:
    """Admit identified rows only when missing identities are the sole defect."""
    if not isinstance(data, dict) or not isinstance(data.get("data"), dict):
        return None
    products = data["data"].get("products")
    if (not isinstance(products, list) or not 1 < len(products) <= MAX_PARTIAL_INDEX_ROWS
            or not all(isinstance(row, dict) for row in products)):
        return None
    omitted, identified = [], []
    for index, row in enumerate(products):
        pid = row.get("productId", row.get("id"))
        if not isinstance(pid, str) or not pid.strip():
            omitted.append(index)
        else:
            identified.append(row)
    if not omitted or not identified:
        return None
    filtered = {**data, "data": {**data["data"], "products": identified}}
    if response_shape_error(filtered, phase="products_index"):
        return None
    return {"raw_records": len(products), "identified_records": len(identified),
            "unidentified_records": len(omitted), "omitted_row_positions": omitted,
            "unique_products": len({row.get("productId", row.get("id")) for row in identified})}


def capture_index_products(products: list, omissions: dict | None):
    """Count all raw rows, but never fetch or fabricate an omitted identity."""
    omitted = set((omissions or {}).get("omitted_row_positions", []))
    return [None if index in omitted else row for index, row in enumerate(products)]


def record_partial_index(result, root, provider, url, page, *, lock=None) -> str | None:
    """Persist one provider-attributable omission, bound to the raw response."""
    from cdr_ingest_support import append_failure
    from cdr_http_policy import sanitize_url
    evidence = result.partial_index
    if not evidence:
        return None
    digest = hashlib.sha256(result.text.encode("utf-8")).hexdigest()
    append_failure(root, {"phase": "products_index", "bank": provider,
        "url": sanitize_url(url), "status": result.status, "failure_category": "invalid_response",
        "retryable": False, "validation_error": "product index contains unidentified rows",
        "page": page, "source_body_sha256": digest,
        "raw_records": evidence["raw_records"], "identified_records": evidence["identified_records"],
        "unidentified_records": evidence["unidentified_records"],
        "omitted_row_positions": evidence["omitted_row_positions"]}, lock=lock)
    return digest


def partial_probe_has_progress(report, request, observation, history) -> bool:
    """An unchanged malformed index gets at most one capture opportunity per day."""
    evidence = report.get("partial_index")
    if not evidence:
        return True
    digest = report["body_sha256"]
    diagnostics = (observation["status"].get("index_diagnostics") or {}).get(request["provider_dir"]) or {}
    if digest in diagnostics.get("partial_index_body_sha256s", []):
        return False  # Already consumed by the selected capture, including out-of-scope rows.
    if any(item.get("request_key") == request["request_key"] and item.get("body_sha256") == digest
           for row in history if row["kind"] == "capture" for item in row.get("proofs", [])):
        return False  # An unchanged response cannot repeatedly spend the capture budget.
    # Selected ingest-status is already contract-bound. Do not hash a large
    # SQLite database inside the bounded probe tick just to compare identities.
    previous = diagnostics.get("unique_products")
    return (type(previous) is int and previous >= 0
            and evidence["unique_products"] > previous)
