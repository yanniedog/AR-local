"""Public financial scope metadata directly retained from structured CDR fields."""
from __future__ import annotations

from cdr_public_rates_conditions import duration_days, duration_months


def rate_metadata(rate):
    kind = str(rate.get("lendingRateType") or rate.get("depositRateType") or "")
    structure = "fixed" if kind == "FIXED" else "introductory" if kind == "INTRODUCTORY" else (
        "conditional" if "BONUS" in kind or "DISCOUNT" in kind else "variable")
    result = {"rateStructure": structure}
    months = duration_months(rate.get("additionalValue"))
    days = duration_days(rate.get("additionalValue"))
    if months:
        result["quotedTerm"] = {"value": months, "unit": "month"}
    elif days:
        result["quotedTerm"] = {"value": days, "unit": "day"}
    application = rate.get("applicationType")
    if application == "MATURITY":
        result["interestPayment"] = {"type": "maturity"}
    elif application == "PERIODIC":
        result["interestPayment"] = {"type": "periodic"}
        if rate.get("applicationFrequency"):
            result["interestPayment"]["frequency"] = str(rate["applicationFrequency"])
    methods = {tier.get("rateApplicationMethod") for tier in rate.get("tiers", []) if isinstance(tier, dict)}
    if len(methods) == 1 and next(iter(methods)) in {"WHOLE_BALANCE", "PER_TIER"}:
        result["tierApplication"] = next(iter(methods)).lower()
    return result
