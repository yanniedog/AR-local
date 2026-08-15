"""Availability and disclosure evidence; missing values never become zero."""

from __future__ import annotations

import ipaddress
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional
from urllib.parse import urlparse

from .models import (
    Availability,
    ClassificationStatus,
    DisclosureStatus,
    PricingStatus,
    ProductClassification,
    ProductEvidence,
)


def published_https_urls(record: Mapping[str, Any]) -> tuple[str, ...]:
    """Return source-published HTTPS links; consumers must still confirm the host."""
    urls: set[str] = set()
    value = record.get("additionalInformation") or record.get("links") or []
    if isinstance(value, Mapping):
        items = value.values()
    elif isinstance(value, list):
        items = value
    else:
        items = []
    for item in items:
        if isinstance(item, str):
            raw = item.strip()
        elif isinstance(item, Mapping):
            raw = str(item.get("uri") or item.get("url") or "").strip()
        else:
            continue
        parsed = urlparse(raw)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            continue
        try:
            literal = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            literal = None
        if literal is not None and not literal.is_global:
            continue
        urls.add(raw)
    return tuple(sorted(urls))


def _fee_status(record: Mapping[str, Any]) -> DisclosureStatus:
    if "fees" not in record:
        return DisclosureStatus.UNKNOWN
    fees = record.get("fees")
    if not isinstance(fees, list):
        return DisclosureStatus.UNKNOWN
    unknown = 0
    for fee in fees:
        if not isinstance(fee, Mapping):
            unknown += 1
            continue
        method = str(fee.get("feeMethodUType") or "").lower()
        fee_type = str(fee.get("feeType") or "").upper()
        fixed = fee.get("fixedAmount") if isinstance(fee.get("fixedAmount"), Mapping) else {}
        variable = fee.get("variable") if isinstance(fee.get("variable"), Mapping) else {}
        raw_amount = fee.get("amount") if fee.get("amount") not in (None, "") else fixed.get("amount")
        known_range = variable.get("feeMinimum") not in (None, "") or variable.get("feeMaximum") not in (None, "")
        known_rate = (
            isinstance(fee.get("rateBased"), Mapping)
            and fee["rateBased"].get("rate") not in (None, "")
        ) or any(fee.get(key) not in (None, "") for key in ("transactionRate", "balanceRate", "accruedRate"))
        variable_unknown = method == "variable" or fee_type == "VARIABLE"
        monetary_values = [
            value
            for value in (
                raw_amount if not variable_unknown else None,
                variable.get("feeMinimum"),
                variable.get("feeMaximum"),
            )
            if value not in (None, "")
        ]
        missing_currency = bool(
            monetary_values and fee.get("currency") in (None, "")
        )
        if (
            variable_unknown and not known_range and not known_rate
        ) or (raw_amount in (None, "") and not known_range and not known_rate) or missing_currency:
            unknown += 1
    if not fees or unknown == 0:
        return DisclosureStatus.COMPLETE
    return DisclosureStatus.UNKNOWN if unknown == len(fees) else DisclosureStatus.PARTIAL


def _eligibility_status(record: Mapping[str, Any]) -> DisclosureStatus:
    if "eligibility" not in record:
        return DisclosureStatus.UNKNOWN
    value = record.get("eligibility")
    return DisclosureStatus.COMPLETE if isinstance(value, list) else DisclosureStatus.UNKNOWN


def _pricing_status(record: Mapping[str, Any]) -> PricingStatus:
    rate_fields = [key for key in ("depositRates", "lendingRates") if key in record]
    if rate_fields and all(record.get(key) == [] for key in rate_fields):
        return PricingStatus.UNPRICED
    present = 0
    invalid = 0
    for key in ("depositRates", "lendingRates"):
        value = record.get(key)
        if not isinstance(value, list):
            continue
        for rate in value:
            if not isinstance(rate, Mapping) or rate.get("rate") in (None, ""):
                invalid += 1
                continue
            present += 1
            try:
                number = Decimal(str(rate["rate"]))
                if not number.is_finite() or number < 0 or number > 1:
                    invalid += 1
            except InvalidOperation:
                invalid += 1
    if present == 0:
        return PricingStatus.UNKNOWN
    return PricingStatus.PARTIAL if invalid else PricingStatus.COMPLETE


def _availability(classification: ProductClassification) -> Availability:
    reason = classification.quarantine_reason
    if reason == "mortgage_linked_offset":
        return Availability.LINKED
    if reason == "business_product":
        return Availability.BUSINESS
    if reason == "restricted_eligibility":
        return Availability.RESTRICTED
    if classification.classification_status is ClassificationStatus.CONFIRMED:
        return Availability.PUBLIC
    return Availability.UNKNOWN


def product_evidence(
    record: Mapping[str, Any],
    classification: ProductClassification,
    *,
    evidence_id: str,
    observed_at: str,
) -> ProductEvidence:
    effective = record.get("effectiveFrom")
    source_updated = record.get("lastUpdated")
    return ProductEvidence(
        availability=_availability(classification),
        fee_disclosure_status=_fee_status(record),
        eligibility_disclosure_status=_eligibility_status(record),
        pricing_status=_pricing_status(record),
        evidence_ids=(evidence_id,),
        observed_at=observed_at,
        effective_date=str(effective) if effective not in (None, "") else None,
        source_updated_at=(
            str(source_updated) if source_updated not in (None, "") else None
        ),
        source_urls=published_https_urls(record),
    )
