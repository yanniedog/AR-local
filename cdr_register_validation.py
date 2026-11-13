"""Conservative completeness checks for the unfiltered public register summary."""
from __future__ import annotations

from typing import Any, Optional


def register_summary_error(payload: Any) -> Optional[str]:
    """Flag changed/truncated envelopes without discarding usable provider rows.

    The current summary is a single array, without required pagination totals.
    If the service starts advertising pages, do not claim the first is complete.
    Unknown fields and valid new industry names remain compatible.
    """
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        return "register has no valid brand array"
    for row in rows:
        if "industries" in row:
            industries = row["industries"]
            if (not isinstance(industries, list) or not industries or
                    any(not isinstance(value, str) or not value.strip() for value in industries)):
                return "register contains an unclassified brand"
    if not isinstance(payload, dict):
        return None  # Legacy bare-array envelopes remain readable.
    for key in ("links", "meta"):
        if key in payload and not isinstance(payload[key], dict):
            return f"register {key} is not an object"
    if payload.get("links", {}).get("next") not in (None, ""):
        return "register advertises an uncaptured next page"
    meta = payload.get("meta", {})
    for key, actual in (("totalRecords", len(rows)), ("totalPages", 1)):
        if key not in meta:
            continue
        declared = meta[key]
        if type(declared) is not int or declared < 0:
            return f"register {key} is invalid"
        if key == "totalPages" and declared == 0 and not rows:
            continue
        if declared != actual:
            return f"register {key} does not match captured brands"
    return None
