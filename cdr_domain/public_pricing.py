"""Public pricing primitives sharing the canonical domain's explicit rate units.

This module accepts public programmes and local scenario numbers separately.
Neither scenario input nor a resolved customer estimate is ingest evidence.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
from enum import Enum
from fractions import Fraction
from typing import Any, Mapping

from .models import RateUnit

VERSION = "public-pricing-v1"
DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]{0,39})(?:\.[0-9]{1,24})?\Z")
MAX_AGE = timedelta(hours=48)
NUMERICAL_FIELDS = {'amount', 'balance', 'lvr', 'termMonths', 'termDays', 'monthlyDeposit', 'withdrawals', 'balanceGrowth', 'cardTransactions'}


class ComponentRole(str, Enum):
    PAYABLE = "payable"
    REFERENCE = "reference"
    DISCOUNT = "discount"
    MARGIN = "margin"
    BONUS = "bonus"
    COMPARISON = "comparison"
    REVERSION = "reversion"


class ConditionState(str, Enum):
    MET = "met"
    UNMET = "unmet"
    UNKNOWN = "unknown"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def semantic_id(kind: str, value: Any) -> str:
    """Do not include prices, source positions, or collection dates in value."""
    return f"{kind}:public-v1:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def decimal_value(raw: Any) -> Decimal:
    if not isinstance(raw, str) or not DECIMAL.fullmatch(raw):
        raise ValueError("expected a bounded explicit decimal string")
    return Decimal(raw)


def fraction_value(value: str, unit: str) -> Fraction:
    number = Fraction(decimal_value(value))
    divisors = {RateUnit.FRACTION_PER_ANNUM.value: 1,
                RateUnit.PERCENTAGE_POINTS.value: 100,
                RateUnit.BASIS_POINTS.value: 10000}
    if unit not in divisors:
        raise ValueError("unsupported rate unit")
    return number / divisors[unit]


def fraction_text(value: Fraction) -> tuple[str, bool]:
    denominator = value.denominator
    for prime in (2, 5):
        while denominator % prime == 0:
            denominator //= prime
    with localcontext() as context:
        context.prec = 100
        decimal = Decimal(value.numerator) / Decimal(value.denominator)
        rounded = denominator != 1 or max(0, -decimal.as_tuple().exponent) > 24
        if rounded:
            decimal = decimal.quantize(Decimal("1e-24"), rounding=ROUND_HALF_UP)
        text = format(decimal, "f")
    text = text.rstrip("0").rstrip(".") if "." in text else text
    return ("0" if text in {"", "-0"} else text), rounded


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        if len(value) == 10:
            return parsed.replace(tzinfo=timezone.utc)
        raise ValueError("timestamp requires an explicit timezone")
    return parsed.astimezone(timezone.utc)


def freshness_as_of(freshness: Mapping[str, Any], as_of: str) -> dict[str, Any]:
    result = dict(freshness)
    result["reasonCodes"] = list(freshness.get("reasonCodes", []))
    try:
        age = timestamp(as_of) - timestamp(str(result["lastSuccessAt"]))
        if age < timedelta(0):
            result["state"] = "unknown"
            result["reasonCodes"].append("future_source_check")
        elif age > MAX_AGE:
            result["state"] = "stale"
            result["reasonCodes"].append("source_check_older_than_48_hours")
    except (KeyError, TypeError, ValueError):
        result["state"] = "unknown"
        result["reasonCodes"].append("successful_source_check_unavailable")
    return result


def condition_state(condition: Mapping[str, Any], scenario: Mapping[str, Any]) -> str:
    field = str(condition.get("field", ""))
    key = str(condition.get("value", "")) if field in {"custom", "qualification"} else field
    actual = scenario.get(key)
    if actual is None or actual == "":
        return ConditionState.UNKNOWN.value
    operation = condition.get("operator")
    if field in {"custom", "qualification"}:
        return "met" if actual is True else "unmet" if actual is False else "unknown"
    if operation == "known":
        return ConditionState.MET.value
    if operation == "eq":
        if field in NUMERICAL_FIELDS:
            try:
                return 'met' if decimal_value(actual) == decimal_value(condition.get('value')) else 'unmet'
            except (ValueError, TypeError):
                return 'unknown'
        return "met" if actual == condition.get("value") else "unmet"
    if operation == "in":
        if field in NUMERICAL_FIELDS:
            try:
                return 'met' if decimal_value(actual) in [decimal_value(item) for item in condition.get('values', [])] else 'unmet'
            except (ValueError, TypeError):
                return 'unknown'
        return "met" if actual in condition.get("values", []) else "unmet"
    if operation != "bounds":
        return "unknown"
    try:
        value = decimal_value(actual)
        for bound, inclusive, direction in (("minimum", "minimumInclusive", -1),
                                             ("maximum", "maximumInclusive", 1)):
            if bound not in condition:
                continue
            edge = decimal_value(condition[bound])
            if direction == -1 and value < edge or direction == 1 and value > edge:
                return "unmet"
            if value == edge and condition.get(inclusive, True) is False:
                return "unmet"
        return "met"
    except (TypeError, ValueError):
        return "unknown"


def partition_conditions(conditions: list[dict], scenario: Mapping[str, Any]) -> dict[str, list]:
    result: dict[str, list] = {"met": [], "unmet": [], "unknown": []}
    seen = set()
    for condition in conditions:
        identity = condition["conditionId"]
        if identity not in seen:
            result[condition_state(condition, scenario)].append(condition)
            seen.add(identity)
    return result
