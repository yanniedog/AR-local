"""Legacy payable-rate safety using original types and source disclosures."""
from __future__ import annotations

import json
from decimal import Decimal

from cdr_domain.public_pricing import decimal_value
from cdr_domain.rates import decimal_text

ABSOLUTE = {"lending": {"VARIABLE", "FIXED"}, "deposit": {"VARIABLE", "FIXED", "BASE"}}
ADJUSTMENTS = {"DISCOUNT", "BUNDLE_DISCOUNT_FIXED", "BUNDLE_DISCOUNT_VARIABLE", "BONUS", "BUNDLE_BONUS", "INTRODUCTORY"}


def legacy_disposition(rate, family, normalized_value=None):
    kind = str(rate.get("lendingRateType") or rate.get("depositRateType") or "")
    if kind in ADJUSTMENTS:
        return "adjustment"
    if kind not in ABSOLUTE.get(family, set()):
        return "unsupported"
    info = str(rate.get("additionalInfo") or "").casefold()
    if "rate displayed is the minimum" in info:
        return "from"
    if "rate displayed is the maximum" in info:
        return "range"
    try:
        if not isinstance(rate.get('rate'), str):
            return 'unsupported'
        raw = decimal_text(rate.get("rate"))
        if not 0 <= decimal_value(raw) <= 1:
            return 'unsupported'
        if normalized_value is not None and Decimal(str(normalized_value)) != Decimal(raw):
            return "unsupported"
    except (ValueError, TypeError, ArithmeticError):
        return "unsupported"
    return "absolute"


def annotate_legacy_rates(products, rates):
    """Add a producer guard to old exports without changing retained source data."""
    sources = {}
    for product in products:
        capture = json.loads(product.get("public_pricing_source_json") or "{}")
        record = capture.get("record")
        if not isinstance(record, dict):
            record = json.loads(product.get("details_json") or "{}")
        sources[product.get("product_key")] = record if isinstance(record, dict) else {}
    for row in rates:
        if row.get("public_rate_disposition"):
            continue
        family = str(row.get("rate_family") or "")
        key = "lendingRates" if family == "lending" else "depositRates"
        original = [item for item in sources.get(row.get("product_key"), {}).get(key, []) if isinstance(item, dict)]
        try:
            index = int(row.get("rate_index")) - 1
        except (ValueError, TypeError):
            index = -1
        if 0 <= index < len(original):
            row["public_rate_disposition"] = legacy_disposition(original[index], family, row.get("rate"))


def legacy_row_is_absolute(row):
    disposition = row.get("public_rate_disposition")
    if disposition:
        return disposition == "absolute"
    # Older editions remain readable. Unknown source types never enter the
    # modern legacy list merely because they contain a numeric value.
    return str(row.get("rate_type") or "") in ABSOLUTE.get(str(row.get("rate_family") or ""), set())
