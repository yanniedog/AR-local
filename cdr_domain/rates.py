"""Typed rate parsing without magnitude-based unit guessing."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional

from .models import EvidenceStatus, RateBasis, RateMetric, RateUnit, TypedRate


def decimal_text(value: Any) -> str:
    if value in (None, "") or isinstance(value, bool):
        raise ValueError("rate value is missing")
    try:
        number = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError(f"invalid decimal value: {value!r}") from error
    if not number.is_finite():
        raise ValueError("rate value must be finite")
    rendered = format(number, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in {"", "-0"} else rendered


def _product_metric(rate_type: str) -> tuple[RateMetric, RateBasis]:
    normalized = rate_type.upper()
    if normalized == "BASE":
        return RateMetric.BASE_INTEREST, RateBasis.BASE
    if normalized in {"BONUS", "BUNDLE", "TOTAL"}:
        return RateMetric.CONDITIONAL_INTEREST, RateBasis.CONDITIONAL
    if normalized in {"INTRODUCTORY", "INTRO"}:
        return RateMetric.INTRODUCTORY_INTEREST, RateBasis.INTRODUCTORY
    return RateMetric.ADVERTISED_INTEREST, RateBasis.ADVERTISED


def product_rate(
    raw: Any,
    *,
    rate_type: str,
    evidence_id: str,
    status: EvidenceStatus = EvidenceStatus.PUBLISHED,
) -> TypedRate:
    value = decimal_text(raw)
    number = Decimal(value)
    if number < 0 or number > 1:
        raise ValueError("product rates must be fractions per annum between 0 and 1")
    metric, basis = _product_metric(rate_type)
    return TypedRate(
        value=value,
        unit=RateUnit.FRACTION_PER_ANNUM,
        metric=metric,
        basis=basis,
        evidence_status=status,
        evidence_ids=(evidence_id,),
    )


def comparison_rate(raw: Any, *, evidence_id: str) -> TypedRate:
    value = decimal_text(raw)
    number = Decimal(value)
    if number < 0 or number > 1:
        raise ValueError("comparison rates must be fractions per annum between 0 and 1")
    return TypedRate(
        value=value,
        unit=RateUnit.FRACTION_PER_ANNUM,
        metric=RateMetric.COMPARISON_INTEREST,
        basis=RateBasis.COMPARISON,
        evidence_status=EvidenceStatus.PUBLISHED,
        evidence_ids=(evidence_id,),
    )


def explicit_reversion_rate(raw: Any, *, evidence_id: str) -> TypedRate:
    value = decimal_text(raw)
    number = Decimal(value)
    if number < 0 or number > 1:
        raise ValueError("reversion rates must be fractions per annum between 0 and 1")
    return TypedRate(
        value=value,
        unit=RateUnit.FRACTION_PER_ANNUM,
        metric=RateMetric.PUBLISHED_REVERSION_INTEREST,
        basis=RateBasis.PUBLISHED_REVERSION,
        evidence_status=EvidenceStatus.PUBLISHED,
        evidence_ids=(evidence_id,),
    )


def rba_cash_rate(raw: Any, *, evidence_id: str) -> TypedRate:
    return TypedRate(
        value=decimal_text(raw),
        unit=RateUnit.PERCENTAGE_POINTS,
        metric=RateMetric.RBA_CASH_RATE,
        basis=RateBasis.OFFICIAL,
        evidence_status=EvidenceStatus.VERIFIED,
        evidence_ids=(evidence_id,),
    )


def basis_point_change(raw: Any, *, evidence_id: str) -> TypedRate:
    return TypedRate(
        value=decimal_text(raw),
        unit=RateUnit.BASIS_POINTS,
        metric=RateMetric.RATE_CHANGE,
        basis=RateBasis.OBSERVED,
        evidence_status=EvidenceStatus.OBSERVED,
        evidence_ids=(evidence_id,),
    )


def rate_from_record(
    rate: Mapping[str, Any], family: str, evidence_id: str
) -> tuple[TypedRate, Optional[TypedRate]]:
    type_key = "lendingRateType" if family == "lending" else "depositRateType"
    advertised = product_rate(
        rate.get("rate"),
        rate_type=str(rate.get(type_key) or "OTHER"),
        evidence_id=evidence_id,
    )
    comparison = None
    if rate.get("comparisonRate") not in (None, ""):
        comparison = comparison_rate(rate["comparisonRate"], evidence_id=evidence_id)
    return advertised, comparison
