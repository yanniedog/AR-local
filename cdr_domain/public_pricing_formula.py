"""Bounded declarative public-rate arithmetic; source code is never evaluated."""
from __future__ import annotations

from fractions import Fraction
from typing import Any, Mapping

from .public_pricing import condition_state, decimal_value, fraction_value


class FormulaError(ValueError):
    pass


class FormulaEvaluator:
    def __init__(self, components: list[dict], scenario: Mapping[str, Any], offer_id: str | None = None):
        self.components = {item["componentId"]: item for item in components}
        if len(self.components) != len(components):
            raise FormulaError("duplicate_component_identity")
        self.scenario = scenario
        self.applied: dict[str, dict] = {}
        self.nodes = 0
        self.offer_id = offer_id
        self.conditions: list[dict] = []
        self.visited: list[str] = []

    def evaluate(self, formula: Mapping[str, Any], depth: int = 0) -> tuple[str, Fraction, Fraction]:
        self.nodes += 1
        if depth > 16 or self.nodes > 256:
            raise FormulaError("formula_budget_exceeded")
        op = formula.get("op")
        child = lambda node: self.evaluate(node, depth + 1)
        if op == "component":
            return self._component(str(formula.get("componentId", "")))
        if op in {"add", "subtract"}:
            return self._arithmetic(op, formula.get("operands", []), child)
        if op == "from":
            _, low, _ = child(formula["formula"])
            return "from", low, low
        if op == "range":
            _, low, _ = child(formula["minimum"])
            _, high, _ = child(formula["maximum"])
            if low > high:
                raise FormulaError("invalid_published_range")
            return "range", low, high
        if op == "cap":
            status, low, high = child(formula["formula"])
            cap = Fraction(decimal_value(formula["value"]))
            lower = min(low, cap)
            upper = cap if status == 'from' else min(high, cap)
            return ('exact' if lower == upper else 'range'), lower, upper
        if op == "alternatives":
            return self._alternatives(formula.get("choices", []), child)
        if op == "tiered":
            return self._tiered(formula, child)
        raise FormulaError("unsupported_formula_operation")

    def _component(self, identity: str) -> tuple[str, Fraction, Fraction]:
        component = self.components.get(identity)
        if component is None or "value" not in component:
            raise FormulaError("component_value_unavailable")
        if component["role"] == "comparison":
            raise FormulaError("comparison_rate_not_payable")
        if self.offer_id is not None and component['scopeId'] != self.offer_id:
            raise FormulaError('component_scope_mismatch')
        self.conditions.extend(component.get('conditions', []))
        states = [condition_state(item, self.scenario) for item in component.get("conditions", [])]
        if "unmet" in states:
            raise FormulaError("component_condition_unmet")
        if "unknown" in states:
            raise FormulaError("component_condition_unknown")
        self.applied[identity] = component
        self.visited.append(identity)
        value = fraction_value(component["value"], component["unit"])
        return "exact", value, value

    def _arithmetic(self, operation, operands, evaluate):
        if not isinstance(operands, list) or not 2 <= len(operands) <= 32:
            raise FormulaError("invalid_formula_operands")
        values, operand_ids = [], []
        for item in operands:
            start = len(self.visited)
            values.append(evaluate(item))
            operand_ids.extend(set(self.visited[start:]))
        if len(operand_ids) != len(set(operand_ids)):
            raise FormulaError('component_applied_more_than_once')
        components = list(self.applied.values())
        if any(c.get('includedInPayable') for c in components):
            raise FormulaError('adjustment_already_in_payable')
        if any(c['role'] == 'payable' for c in components) and any(c['role'] in {'discount', 'bonus', 'margin'} for c in components):
            raise FormulaError('net_rate_adjustment_double_count')
        if len({c["scopeId"] for c in components}) > 1:
            raise FormulaError("component_scope_mismatch")
        if operation == 'subtract' and any(status == 'from' for status, _, _ in values):
            raise FormulaError('unbounded_range_arithmetic')
        low, high = values[0][1:]
        for _, minimum, maximum in values[1:]:
            low = low + minimum if operation == 'add' else low - maximum
            high = high + maximum if operation == 'add' else high - minimum
        status = 'from' if any(kind == 'from' for kind, _, _ in values) else 'exact' if low == high else 'range'
        return status, low, high

    def _alternatives(self, choices, evaluate):
        candidates, unknown = [], False
        for choice in choices:
            self.conditions.extend(choice.get('conditions', []))
            states = [condition_state(item, self.scenario) for item in choice.get("conditions", [])]
            if "unmet" not in states:
                if "unknown" in states:
                    unknown = True
                else:
                    candidates.append(choice)
        if unknown:
            raise FormulaError("alternative_condition_unknown")
        if len(candidates) != 1:
            raise FormulaError("ambiguous_alternatives" if candidates else "no_applicable_alternative")
        return evaluate(candidates[0]["formula"])

    def _tiered(self, formula, evaluate):
        field = formula.get("field")
        try:
            amount = Fraction(decimal_value(self.scenario[field]))
        except (KeyError, TypeError, ValueError):
            raise FormulaError("tier_scenario_unknown") from None
        tiers = formula.get("tiers", [])
        if formula.get("method") == "whole_balance":
            applicable = [tier for tier in tiers if self._inside(amount, tier)]
            if len(applicable) != 1:
                raise FormulaError("ambiguous_tiers" if applicable else "tier_not_covered")
            return evaluate(applicable[0]["formula"])
        if formula.get("method") != "per_tier" or field not in {"amount", "balance"} or amount <= 0:
            raise FormulaError("unsupported_tier_application")
        coverage, total, maximum_total = Fraction(0), Fraction(0), Fraction(0)
        kinds = []
        ordered = sorted(tiers, key=lambda t: Fraction(decimal_value(t.get("minimum", "0"))))
        for tier in ordered:
            lower = Fraction(decimal_value(tier.get("minimum", "0")))
            upper = Fraction(decimal_value(tier["maximum"])) if "maximum" in tier else amount
            if lower >= amount:
                continue
            if lower != coverage or upper <= lower:
                raise FormulaError("tier_gap_or_overlap")
            width = min(upper, amount) - lower
            status, rate, maximum = evaluate(tier["formula"])
            kinds.append(status)
            total += width * rate
            maximum_total += width * maximum
            coverage += width
        if coverage != amount:
            raise FormulaError("tier_not_covered")
        status = 'from' if 'from' in kinds else 'exact' if total == maximum_total else 'range'
        return status, total / amount, maximum_total / amount

    @staticmethod
    def _inside(value: Fraction, tier: Mapping[str, Any]) -> bool:
        for bound, inclusive, direction in (("minimum", "minimumInclusive", -1),
                                             ("maximum", "maximumInclusive", 1)):
            if bound not in tier:
                continue
            edge = Fraction(decimal_value(tier[bound]))
            if direction == -1 and value < edge or direction == 1 and value > edge:
                return False
            if value == edge and tier.get(inclusive, True) is False:
                return False
        return True
