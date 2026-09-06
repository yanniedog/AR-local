"""Bounded CDR compatibility decisions, independent of individual data holders.

Unknown fields and enum values remain available to downstream normalization.
Only the response envelope, product identity and list accounting are enforced
here; an error response is never converted into invented product/rate data.
"""

from __future__ import annotations

import math
import re
import threading
from typing import Any, Iterable, NamedTuple, Optional


def _versions(value: str) -> list[int]:
    return sorted({int(x) for x in re.findall(r"(?<!\d)[1-9]\d?(?!\d)", value)}, reverse=True)


def parse_supported_versions(body: str) -> list[int]:
    """Recognize advertised ranges/lists without probing arbitrary version numbers."""
    text = str(body or "")[:65536]
    # Holders use both orders: "max version 5 and min version 4" and
    # "Minimum version supported is 4 and Maximum version supported is 5".
    ranges = []
    for name in (r"min(?:imum)?", r"max(?:imum)?"):
        match = re.search(
            rf"\b{name}(?:\s+versions?)?(?:\s+supported)?\s*(?:is|=|:)?\s*(\d+)\b",
            text, re.I,
        )
        ranges.append(int(match.group(1)) if match else None)
    lo, hi = ranges
    if lo is not None and hi is not None:
        return list(range(hi, lo - 1, -1)) if 1 <= lo <= hi <= 99 else []
    match = re.search(
        r"(?:\bversions?\s+available|\bavailable|\bsupported\s+versions?)"
        r"\s*(?:include|are)?\s*:?\s*\[?([\d,\s]+(?:\band\b[\d,\s]+)?)",
        text, re.I,
    )
    return _versions(match.group(1)) if match else []


class FetchFailure(NamedTuple):
    category: str
    retryable: bool
    negotiate: bool


def classify_fetch_failure(status: Any, text: str = "") -> FetchFailure:
    """Separate a retryable outage from a deterministic rejection using evidence."""
    body = str(text or "")[:65536].lower()
    if isinstance(status, str) and status.isdigit():
        status = int(status)
    if status == "circuit_open":
        return FetchFailure("transient_upstream", True, False)
    if status == "recovery_budget_exhausted":
        return FetchFailure("recovery_budget_exhausted", False, False)
    if status in {495, 596, 597, 598}:
        return FetchFailure("security_policy", False, False)
    if status == 406 or (status in {400, 422} and (
        "unsupportedversion" in body or "unsupported version" in body
        or ("x-v" in body and parse_supported_versions(body))
    )):
        return FetchFailure("incompatible_version", False, True)
    if status in {400, 401, 403} and re.search(r"requires?\s+(?:an?\s+)?api[ _-]?key", body):
        return FetchFailure("public_endpoint_auth_required", False, False)
    if status in {401, 403}:
        return FetchFailure("access_denied", False, False)
    if status in {400, 404, 410} and re.search(r"product\s+is\s+(?:inactive|closed)", body):
        return FetchFailure("product_inactive", False, False)
    if status in {404, 410}:
        return FetchFailure("endpoint_not_found", False, False)
    if status == 400 and "<title>runtime error</title>" in body:
        return FetchFailure("upstream_rejection", False, False)
    if status in {400, 422, 500} and (
        "should have required property" in body or "validation failed with invalid data" in body
    ):
        return FetchFailure("upstream_schema_invalid", False, False)
    if status == 599:
        return FetchFailure("transport", True, False)
    if status in {408, 425, 429}:
        return FetchFailure("transient_upstream", True, False)
    if isinstance(status, int) and 500 <= status <= 595:
        return FetchFailure("transient_upstream", True, True)
    if isinstance(status, int) and 200 <= status < 400:
        return FetchFailure("invalid_response", False, True)
    return FetchFailure("upstream_rejection", False, True)


def response_shape_error(data: Any, *, phase: str, product_id: str = "") -> Optional[str]:
    """Accept additive schema changes; reject empty/wrong data masquerading as success."""
    if not isinstance(data, dict):
        return "response envelope is not an object"
    if phase == "products_index":
        inner = data.get("data")
        products = inner.get("products") if isinstance(inner, dict) else inner
        if not isinstance(products, list):
            return "product index has no products array"
        identities = []
        for row in products:
            pid = row.get("productId", row.get("id")) if isinstance(row, dict) else None
            if not isinstance(pid, str) or not pid.strip():
                return "product index contains a missing or invalid product identity"
            identities.append(pid)
        if len(set(identities)) != len(identities):
            return "product index contains duplicate product identities"
        for name in ("links", "meta"):
            if name in data and not isinstance(data[name], dict):
                return f"product index {name} is not an object"
        if data.get("links", {}).get("next") is not None and not isinstance(data["links"]["next"], str):
            return "product index next link is not a string"
    if phase in {"product_detail", "classification_detail"}:
        inner = data.get("data", data)
        pid = inner.get("productId", inner.get("id")) if isinstance(inner, dict) else None
        if not isinstance(pid, str) or not pid.strip():
            return "product detail has no valid product identity"
        if product_id and pid != product_id:
            return "product detail identity does not match the requested product"
        for name in ("lendingRates", "depositRates"):
            if name in inner and (not isinstance(inner[name], list) or any(
                not isinstance(rate, dict) for rate in inner[name]
            )):
                return f"product detail {name} is not an array of objects"
            for rate in inner.get(name, []):
                value = rate.get("rate")
                try:
                    valid = not isinstance(value, bool) and math.isfinite(float(value))
                except (TypeError, ValueError, OverflowError):
                    valid = False
                if not valid:
                    return f"product detail {name} contains a missing or nonfinite numeric rate"
    return None


def pagination_accounting_error(data: dict, *, pages: int, products: int, has_next: bool) -> Optional[str]:
    """Detect truncation when a holder supplies totals but omits/repeats page links."""
    meta = data.get("meta") or {}
    if not isinstance(meta, dict):
        return "pagination metadata is invalid"
    for name, actual in (("totalPages", pages), ("totalRecords", products)):
        total = meta.get(name)
        if total is None:
            continue
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            return f"pagination {name} is invalid"
        if name == "totalPages" and total == 0 and pages == 1 and products == 0 and not has_next:
            continue
        if actual > total or (not has_next and actual != total):
            return f"pagination {name} does not match the captured index"
    return None


class HolderVersionCache:
    """Ephemeral per-endpoint hint; invalidation never disables fallback negotiation."""

    def __init__(self, versions: Iterable[int]) -> None:
        self._versions = tuple(versions)
        self._preferred: Optional[int] = None
        self._lock = threading.Lock()

    def order(self) -> list[int]:
        with self._lock:
            preferred = self._preferred
        return ([preferred] if preferred is not None else []) + [
            version for version in self._versions if version != preferred
        ]

    def record(self, *, ok: bool, version: Optional[int], attempted: Optional[int]) -> None:
        with self._lock:
            if ok and isinstance(version, int) and not isinstance(version, bool) and 1 <= version <= 99:
                self._preferred = version
            elif not ok and self._preferred == attempted:
                self._preferred = None
