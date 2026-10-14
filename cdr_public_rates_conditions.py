"""Reviewed structured CDR applicability interpretation, without prose guessing."""
from __future__ import annotations

import re
from typing import Any, Mapping

from cdr_domain.public_pricing import decimal_value, semantic_id
from cdr_domain.rates import decimal_text

NO_CONDITION = {"", "n/a", "not applicable", "none", "na"}


def condition(field, operation, evidence_id, **values):
    semantics = {"field": field, "operator": operation, **values}
    return {"conditionId": semantic_id("condition", semantics), **semantics,
            "evidenceIds": [evidence_id]}


def duration_months(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"P(?:(\d+)Y)?(?:(\d+)M)?", value.strip())
    if match and any(match.groups()):
        return str(int(match[1] or 0) * 12 + int(match[2] or 0))
    return None


def duration_days(value: Any) -> str | None:
    match = re.fullmatch(r"P(\d+)D", value) if isinstance(value, str) else None
    return str(int(match[1])) if match else None


def unknown_condition(item, evidence_id):
    text = str(item.get("additionalInfo") or item.get("additionalValue") or "Undisclosed pricing condition").strip()
    semantic = {"type": item.get("rateApplicabilityType"), "value": item.get("additionalValue"), "description": text}
    key = semantic_id("qualification", semantic)
    return condition("qualification", "known", evidence_id, value=key, description=text[:4096])


def applicability_conditions(items, evidence_id):
    result = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, Mapping):
            result.append(unknown_condition({}, evidence_id))
            continue
        kind = str(item.get("rateApplicabilityType") or "").upper()
        info = str(item.get("additionalInfo") or "").strip()
        raw = item.get("additionalValue")
        if kind == "OTHER" and info.casefold() in NO_CONDITION and str(raw or "").casefold() in NO_CONDITION:
            continue
        if kind in {"MIN_BALANCE", "MAX_BALANCE", "MIN_DEPOSIT", "MAX_DEPOSIT", "MIN_AMOUNT", "MAX_AMOUNT"}:
            field = "balance" if "BALANCE" in kind else "amount"
            try:
                value = decimal_text(raw)
                decimal_value(value)
                result.append(condition(field, "bounds", evidence_id,
                                        **{"minimum" if kind.startswith("MIN") else "maximum": value}))
                continue
            except (ValueError, TypeError):
                pass
        if kind in {"MIN_DEPOSIT_AMOUNT", "MAX_WITHDRAWALS", "MIN_BALANCE_GROWTH", "MIN_CARD_TRANSACTIONS"}:
            fields = {"MIN_DEPOSIT_AMOUNT": "monthlyDeposit", "MAX_WITHDRAWALS": "withdrawals",
                      "MIN_BALANCE_GROWTH": "balanceGrowth", "MIN_CARD_TRANSACTIONS": "cardTransactions"}
            try:
                value = decimal_text(raw)
                decimal_value(value)
                result.append(condition(fields[kind], "bounds", evidence_id,
                                        **{"maximum" if kind.startswith("MAX") else "minimum": value}))
                continue
            except (ValueError, TypeError):
                pass
        result.append(unknown_condition(item, evidence_id))
    return result


def product_constraints(record, section, evidence_id):
    result = []
    for item in record.get("constraints", []):
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("constraintType", "")).upper()
        mapping = {"MIN_LIMIT": ("amount", "minimum"), "MAX_LIMIT": ("amount", "maximum"),
                   "MIN_BALANCE": ("balance", "minimum"), "MAX_BALANCE": ("balance", "maximum"),
                   "MAX_LVR": ("lvr", "maximum")}
        if kind not in mapping:
            continue
        field, bound = mapping[kind]
        if section != "Mortgage" and field == "amount":
            field = "balance"
        try:
            value = decimal_text(item.get("additionalValue"))
            decimal_value(value)
            result.append(condition(field, "bounds", evidence_id, **{bound: value}))
        except (ValueError, TypeError):
            result.append(unknown_condition(item, evidence_id))
    return result


def structured_rate_conditions(rate, section, evidence_id):
    result = []
    for source, field in (("loanPurpose", "purpose"), ("repaymentType", "repayment")):
        if rate.get(source):
            result.append(condition(field, "eq", evidence_id, value=str(rate[source])))
    kind = str(rate.get("lendingRateType") or rate.get("depositRateType") or "")
    if kind.startswith("BUNDLE_"):
        if rate.get("additionalValue"):
            result.append(condition("package", "eq", evidence_id, value=str(rate["additionalValue"])))
        else:
            result.append(unknown_condition({"additionalInfo": "Package eligibility is not disclosed"}, evidence_id))
    if kind == "FIXED":
        months = duration_months(rate.get("additionalValue"))
        if months:
            result.append(condition("termMonths", "eq", evidence_id, value=months))
        elif duration_days(rate.get("additionalValue")):
            result.append(condition("termDays", "eq", evidence_id, value=duration_days(rate["additionalValue"])))
        elif rate.get("additionalValue"):
            result.append(unknown_condition({"additionalInfo": "Quoted term " + str(rate["additionalValue"])}, evidence_id))
    result.extend(applicability_conditions(rate.get("applicabilityConditions"), evidence_id))
    if kind == "BONUS":
        info = str(rate.get("additionalInfo") or "").casefold()
        if "no withdrawals, fees or charges" in info:
            result.append(condition("qualification", "known", evidence_id, value="noFeesOrCharges",
                                    description="No fees or charges are processed in the public bonus qualification period"))
        if "last business day" in info:
            result.append(condition("qualification", "known", evidence_id, value="qualificationPeriodSatisfied",
                                    description="Deposits and withdrawals satisfy the lender's stated business-day qualification period"))
    return result


def tier_bounds(tier, section):
    unit = str(tier.get("unitOfMeasure", "")).upper()
    if unit == "PERCENT" and section == "Mortgage":
        field = "lvr"
    elif unit == "DOLLAR":
        field = "amount" if section == "Mortgage" else "balance"
    elif unit == "MONTH":
        field = "termMonths"
    elif unit == "DAY":
        field = "termDays"
    else:
        raise ValueError("unsupported_tier_unit")
    bounds = {}
    for source, target in (("minimumValue", "minimum"), ("maximumValue", "maximum")):
        if tier.get(source) is not None:
            bounds[target] = decimal_text(tier[source])
            decimal_value(bounds[target])
    if not bounds:
        raise ValueError("tier_bounds_unavailable")
    method = str(tier.get("rateApplicationMethod", "")).upper()
    if method not in {"WHOLE_BALANCE", "PER_TIER"}:
        raise ValueError("unsupported_tier_application")
    return field, method.lower(), bounds
