"""Per-product detail extraction for the mobile-app payload."""
from __future__ import annotations

import json
from typing import Any, Dict, List

from app_payload_common import compact
from cdr_clean_export import official_product_links
from cdr_product_facts import compact_facts

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


def _present(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _fee_amount_status(item: Dict[str, Any]) -> str:
    """Describe how a CDR fee is priced without treating variable $0 as free.

    Both the older Banking schema (top-level ``amount``/rate fields) and the
    newer fee-method union are present in retained real runs.  In particular,
    several banks publish ``feeType=VARIABLE, amount=0.00`` as a placeholder.
    That is an unpublished amount, not a zero-dollar fee.
    """
    method = str(item.get("feeMethodUType") or "").strip().lower()
    fee_type = str(item.get("feeType") or "").strip().upper()
    if method == "variable" or fee_type == "VARIABLE":
        return "variable"
    if method == "ratebased" or any(
        _present(item.get(key)) for key in ("balanceRate", "transactionRate", "accruedRate")
    ):
        return "rate"
    fixed = item.get("fixedAmount")
    if method == "fixedamount" or _present(item.get("amount")) or (
        isinstance(fixed, dict) and _present(fixed.get("amount"))
    ):
        return "fixed"
    return "unpublished"


def _legacy_fee_value(item: Dict[str, Any], amount_status: str) -> Any:
    """Keep old app clients useful while richer fee fields roll out."""
    if _present(item.get("additionalValue")):
        return item.get("additionalValue")
    if amount_status == "variable":
        # A source placeholder such as 0.00 must never be presented as "free".
        return None
    if _present(item.get("amount")):
        return item.get("amount")
    fixed = item.get("fixedAmount")
    if isinstance(fixed, dict) and _present(fixed.get("amount")):
        return fixed.get("amount")
    return None


def _fee_items(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the complete structured fee evidence needed by mobile clients.

    Do not collapse the CDR fee-method union to a single display string.  The
    structured amount, rate, cadence, cap, range and discount fields are used
    for transparent display and switching-cost calculations.
    """
    items = record.get("fees")
    if not isinstance(items, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        amount_status = _fee_amount_status(item)
        out.append(
            compact(
                {
                    "label": item.get("feeType") or item.get("name"),
                    "name": item.get("name"),
                    "value": _legacy_fee_value(item, amount_status),
                    "info": item.get("additionalInfo"),
                    "amountStatus": amount_status,
                    "amount": item.get("amount"),
                    "currency": item.get("currency"),
                    "additionalValue": item.get("additionalValue"),
                    "balanceRate": item.get("balanceRate"),
                    "transactionRate": item.get("transactionRate"),
                    "accruedRate": item.get("accruedRate"),
                    "accrualFrequency": item.get("accrualFrequency"),
                    "feeCap": item.get("feeCap"),
                    "feeCapPeriod": item.get("feeCapPeriod"),
                    "feeMethodUType": item.get("feeMethodUType"),
                    "fixedAmount": item.get("fixedAmount"),
                    "variable": item.get("variable"),
                    "rateBased": item.get("rateBased"),
                    "discounts": item.get("discounts"),
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
    info = official_product_links(record)
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
                "fees": _fee_items(record),
                "features": _detail_items(record, "features", "featureType"),
                "eligibility": _detail_items(record, "eligibility", "eligibilityType"),
                "constraints": _detail_items(record, "constraints", "constraintType"),
                "links": _detail_links(record),
                "facts": compact_facts(
                    record,
                    "|".join(str(product.get(field) or "") for field in ("dataset", "provider", "product_id")),
                ),
            }
        )
        details[key] = entry
    return details
