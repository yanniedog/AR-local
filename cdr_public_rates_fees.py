"""Evidence-bound public fees; unsupported charges never become free."""
from __future__ import annotations

from typing import Mapping

from cdr_domain.identity import fee_semantics
from cdr_domain.public_pricing import decimal_value, semantic_id
from cdr_domain.rates import decimal_text
from cdr_public_rates_conditions import condition, duration_months


def compile_fees(record, *, product_id, offer_id, source_sha256, source_url, pointer, checked_at):
    evidence, fees, reasons = [], [], []
    raw_fees = record.get("fees")
    if not isinstance(raw_fees, list):
        return [], {"status": "unknown", "reasonCodes": ["fee_disclosure_unavailable"], "evidenceIds": []}, []
    for index, raw in enumerate(raw_fees):
        if not isinstance(raw, Mapping):
            reasons.append("fee_record_unsupported")
            continue
        locator = f"{pointer}/fees/{index}"
        eid = semantic_id("evidence", [source_sha256, locator])
        item = {"evidenceId": eid, "url": source_url, "sha256": source_sha256,
                "locator": locator, "extractionVersion": "structured-cdr-public-fees-v1"}
        if checked_at:
            item["checkedAt"] = checked_at
        evidence.append(item)
        fee, gaps = _fee(raw, product_id, locator, eid)
        fees.append(fee)
        reasons.extend(gaps)
    return fees, {"status": "partial" if reasons else "complete", "reasonCodes": sorted(set(reasons)),
                  "evidenceIds": [item["evidenceId"] for item in evidence]}, evidence


def _fee(raw, offer_id, pointer, evidence_id):
    kind = str(raw.get("feeType") or "UNKNOWN")
    name = str(raw.get("name") or kind)
    role = {"UPFRONT": "upfront", "PERIODIC": "recurring", "EVENT": "event"}.get(kind, "event")
    if kind == "EVENT" and any(word in name.casefold() for word in ("discharge", "closure", "exit fee")):
        role = "switching"
    if "package" in name.casefold():
        role = "package"
    fee = {"feeId": semantic_id("fee", [offer_id, fee_semantics(raw)]), "scopeId": offer_id,
           "name": name, "role": role, "conditions": [], "evidenceIds": [evidence_id],
           "source": {"rawType": kind, "pointer": pointer}}
    reasons = []
    if raw.get("currency"):
        fee["currency"] = str(raw["currency"])
    else:
        reasons.append("fee_currency_unknown")
    method = str(raw.get("feeMethodUType") or "").casefold()
    fixed = raw.get("fixedAmount") if isinstance(raw.get("fixedAmount"), Mapping) else {}
    amount = raw.get("amount") if raw.get("amount") is not None else fixed.get("amount")
    if amount is not None:
        fee["source"]["rawValue"] = str(amount)
    try:
        if method not in {"", "fixedamount"} or amount is None:
            raise ValueError("unsupported fee method")
        value = decimal_text(amount)
        if decimal_value(value) < 0:
            raise ValueError("negative fee requires a rebate adapter")
        fee["amount"] = value
    except (ValueError, TypeError):
        reasons.append("fee_amount_or_method_unknown")
    if role in {"recurring", "package"}:
        months = duration_months(raw.get("additionalValue"))
        if months and int(months) > 0:
            fee["frequencyMonths"] = int(months)
        else:
            reasons.append("fee_frequency_unknown")
    if role in {"event", "switching"}:
        fee["event"] = name
        reasons.append("fee_event_applicability_required")
    if raw.get("discounts") or raw.get("feeDiscounts"):
        reasons.append("fee_discount_rule_unsupported")
    info = str(raw.get("additionalInfo") or "")
    if info and any(word in info.casefold() for word in (" if ", "waiv", "depending", "subject to", "only")):
        key = semantic_id("fee-qualification", [offer_id, fee_semantics(raw)])
        fee["conditions"].append(condition("qualification", "known", evidence_id, value=key, description=info[:4096]))
        reasons.append("fee_condition_requires_assumption")
    return fee, reasons
