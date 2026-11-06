"""One producer resolver matching the app's public pricing wire contract."""
from __future__ import annotations

from typing import Any, Mapping

from .public_pricing import (
    condition_state, fraction_text, fraction_value, freshness_as_of, partition_conditions, timestamp,
)
from .public_pricing_formula import FormulaError, FormulaEvaluator


def _effective(programme, as_of):
    try:
        now = timestamp(as_of)
    except (TypeError, ValueError):
        return 'invalid_resolution_date'
    if programme.get("effectiveFrom") and now < timestamp(programme["effectiveFrom"]):
        return "programme_not_yet_effective"
    if programme.get("effectiveTo") and now >= timestamp(programme["effectiveTo"]):
        return "programme_expired"
    return None


def _numeric(result, status, low, high):
    if low < 0 or low > 1 or high < low or high > 1:
        raise FormulaError('payable_rate_out_of_bounds')
    minimum, rounded_low = fraction_text(low)
    maximum, rounded_high = fraction_text(high)
    if low != 0 and minimum == '0' or high != 0 and maximum == '0':
        raise FormulaError('rate_precision_unsupported')
    if status == "exact":
        result["payableRate"] = minimum
    else:
        result["minimumRate"] = minimum
        if status == "range":
            result["maximumRate"] = maximum
    if rounded_low or rounded_high:
        result["reasonCodes"].append("exact_rate_rational_rounded")


def resolve_public_rate(programme: Mapping[str, Any], scenario: Mapping[str, Any], as_of: str) -> dict:
    """Resolve public evidence. User numbers never enter the programme object."""
    from .public_pricing_validation import validate_programme
    validate_programme(programme)
    if scenario.get('effectiveDate') is None:
        scenario = {**scenario, 'effectiveDate': as_of[:10]}
    freshness = freshness_as_of(programme["freshness"], as_of)
    partitions = partition_conditions(list(programme["conditions"]), scenario)
    result = {"status": "unresolved", "appliedComponents": [], "phases": [],
              "conditions": partitions, "reasonCodes": list(programme["reasonCodes"]),
              "evidenceIds": list(programme["evidenceIds"]), "freshness": freshness,
              "verifiedCurrent": False, "origin": "published"}
    for field in ("effectiveFrom", "effectiveTo"):
        if field in programme:
            result[field] = programme[field]
    reason = _effective(programme, as_of)
    if reason:
        result["reasonCodes"].append(reason)
        return result
    if freshness["state"] != "current" and scenario.get("allowHistorical") is not True:
        result["reasonCodes"].append("source_not_verified_current")
        return result
    if partitions["unmet"]:
        result["reasonCodes"].append("programme_condition_unmet")
        return result
    formula = programme.get("formula")
    if formula is None:
        result["reasonCodes"].append("pricing_formula_unavailable")
        return result
    assessed_range = formula.get("op") in {"from", "range"} and "lender_assessment_required" in result["reasonCodes"]
    if partitions["unknown"] and not (assessed_range and all(
            c["field"] == "customerCategory" and c["operator"] == "known" for c in partitions["unknown"])):
        result["reasonCodes"].append("programme_condition_unknown")
        return result
    evaluator = FormulaEvaluator(list(programme["components"]), scenario, programme['offerId'])
    try:
        status, low, high = evaluator.evaluate(formula)
        if not any(c["role"] in {"payable", "reference", "reversion"} for c in evaluator.applied.values()):
            raise FormulaError("adjustment_without_base")
        if not programme['evidenceIds'] or any(not c['evidenceIds'] for c in evaluator.applied.values()):
            raise FormulaError('pricing_evidence_unbound')
        _numeric(result, status, low, high)
        result["status"] = status
    except (FormulaError, KeyError, TypeError, ValueError) as error:
        result["reasonCodes"].append(str(error))
        result['conditions'] = partition_conditions(list(programme['conditions']) + evaluator.conditions, scenario)
        return result
    result["appliedComponents"] = list(evaluator.applied.values())
    result['conditions'] = partition_conditions(list(programme['conditions']) + evaluator.conditions, scenario)
    result["origin"] = ('published' if formula.get('op') in {'component', 'from', 'range'}
                        and all(component['role'] == 'payable' for component in evaluator.applied.values())
                        else 'publicly_calculated')
    result["verifiedCurrent"] = freshness["state"] == "current" and not partitions["unknown"]
    comparisons = [c for c in programme["components"] if c["role"] == "comparison" and "value" in c
                   and c['scopeId'] == programme['offerId']
                   and all(condition_state(item, scenario) == 'met' for item in c['conditions'])]
    if len(comparisons) == 1:
        result["comparisonRate"] = fraction_text(fraction_value(comparisons[0]["value"], comparisons[0]["unit"]))[0]
    if len(comparisons) > 1:
        result['reasonCodes'].append('comparison_rate_conflicting')
    if freshness['state'] != 'current':
        result['reasonCodes'].append('historical_scenario_selected')
    for phase in programme.get("phases", []):
        resolved, observed_conditions = _resolve_phase(phase, programme["components"], scenario, programme['offerId'])
        result["phases"].append(resolved)
        result['conditions'] = partition_conditions(sum(result['conditions'].values(), []) + observed_conditions, scenario)
    result["reasonCodes"] = sorted(set(result["reasonCodes"] + freshness.get("reasonCodes", [])))
    return result


def _resolve_phase(phase, components, scenario, offer_id):
    result = {"phaseId": phase["phaseId"], "startMonth": phase["startMonth"],
              "status": "unresolved", "reasonCodes": [], "evidenceIds": phase["evidenceIds"]}
    if "endMonth" in phase:
        result["endMonth"] = phase["endMonth"]
    conditions = partition_conditions(phase["conditions"], scenario)
    if conditions["unmet"] or conditions["unknown"]:
        result["reasonCodes"].append("phase_condition_unmet" if conditions['unmet'] else 'phase_condition_unknown')
        return result, phase['conditions']
    evaluator = FormulaEvaluator(components, scenario, offer_id)
    try:
        status, low, high = evaluator.evaluate(phase["formula"])
        _numeric(result, status, low, high)
        result["status"] = status
    except (FormulaError, KeyError, TypeError, ValueError) as error:
        result["reasonCodes"].append(str(error))
    return result, phase['conditions'] + evaluator.conditions


# Interface spelling is kept identical in Python and TypeScript acceptance code.
resolvePublicRate = resolve_public_rate
