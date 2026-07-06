"""Per-product detail extraction for the mobile-app payload."""
from __future__ import annotations

import json
from typing import Any, Dict, List

from app_payload_common import compact

def _detail_items(record: Dict[str, Any], key: str, type_key: str) -> List[Dict[str, Any]]:
    items = record.get(key)
    if not isinstance(items, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out.append(
            compact(
                {
                    "label": item.get(type_key) or item.get("name"),
                    "name": item.get("name"),
                    "value": item.get("additionalValue") or item.get("amount"),
                    "info": item.get("additionalInfo"),
                }
            )
        )
    return out


def _detail_links(record: Dict[str, Any]) -> Dict[str, str]:
    """Authoritative lender document URIs from CDR additionalInformation.

    These are the single best source of accurate, complete, up-to-date spec
    detail (overview / eligibility / fees / terms), so the app can link straight
    to the lender's own pages — especially the eligibility page, which carries
    staff/occupation/membership criteria that the structured eligibility array
    frequently omits.
    """
    info = record.get("additionalInformation")
    if not isinstance(info, dict):
        return {}
    return compact(
        {
            "overview": info.get("overviewUri"),
            "eligibility": info.get("eligibilityUri"),
            "fees": info.get("feesAndPricingUri"),
            "terms": info.get("termsUri"),
            "bundle": info.get("bundleUri"),
        }
    )


def build_details(products: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    details: Dict[str, Dict[str, Any]] = {}
    for product in products:
        key = product.get("product_key")
        if not key:
            continue
        raw = product.get("details_json") or "{}"
        try:
            record = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (ValueError, TypeError):
            record = {}
        if not isinstance(record, dict):
            record = {}
        entry = compact(
            {
                "description": product.get("description") or record.get("description"),
                "last_updated": product.get("last_updated"),
                "fees": _detail_items(record, "fees", "feeType"),
                "features": _detail_items(record, "features", "featureType"),
                "eligibility": _detail_items(record, "eligibility", "eligibilityType"),
                "constraints": _detail_items(record, "constraints", "constraintType"),
                "links": _detail_links(record),
            }
        )
        details[key] = entry
    return details
