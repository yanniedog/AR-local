"""Versioned interpretation vocabulary; recognition never approves executable rules."""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Mapping, Sequence

from .identity import digest

VERSION = "terms-parameters-v1"
_DECIMAL = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
# Aliases are exact CDR field names from cdr_product_facts._CANONICAL_LEAF,
# not speculative natural-language synonyms. Ambiguous amount/value fields
# deliberately have no global mapping.
_TEXT = (
    ("product.name", ("name",)), ("product.description", ("description",)),
    ("product.brand_name", ("brandName",)), ("product.category", ("productCategory",)),
    ("rate.type", ("depositRateType", "lendingRateType")),
    ("loan.repayment", ("repaymentType",)), ("loan.purpose", ("loanPurpose",)),
    ("fee.type", ("feeType",)), ("fee.method", ("feeMethodUType",)),
    ("tier.application_method", ("rateApplicationMethod",)),
)


def registry_contract() -> dict[str, Any]:
    """Return fresh JSON values so callers cannot mutate the process registry."""
    parameters = [{"key": key, "aliases": list(aliases), "type": "text", "unit": None}
                  for key, aliases in _TEXT]
    parameters.append({"key": "product.tailored", "aliases": ["isTailored"],
                       "type": "boolean", "unit": None})
    for key, alias in (("rate.advertised", "rate"), ("rate.comparison", "comparisonRate")):
        parameters.append({"key": key, "aliases": [alias], "type": "decimal",
                           "unit": "fraction_per_year"})
    for row in parameters:
        row.update(applicability="source_scoped_only", supported_rule_patterns=[])
    body = {"version": VERSION, "parameters": sorted(parameters, key=lambda row: row["key"]),
            "unknown_policy": "Retain unmatched wording as unresolved clauses with a reason; do not invent canonical keys.",
            "qualification_policy": "Preserve source product/tier/package/cohort, conditions, exceptions and dates; recognition is not semantic or executable approval."}
    return {**body, "sha256": digest(body)}


def validate_registry_context(context: Mapping[str, Any]) -> None:
    if "parameter_registry" not in context:
        return  # Immutable legacy jobs keep their existing interpretation contract.
    supplied = context["parameter_registry"]
    if not isinstance(supplied, dict) or supplied != registry_contract():
        raise ValueError("Unsupported or altered parameter registry context")


def canonical_parameter(value: str) -> str | None:
    """Exact aliases assist interpretation; staged output must use the canonical key."""
    for row in registry_contract()["parameters"]:
        if value == row["key"] or value in row["aliases"]:
            return row["key"]
    return None


def validate_parameter_terms(context: Mapping[str, Any], terms: Sequence[Mapping[str, Any]]) -> None:
    validate_registry_context(context)
    if "parameter_registry" not in context:
        return
    definitions = {row["key"]: row for row in registry_contract()["parameters"]}
    for term in terms:
        definition = definitions.get(term["parameter_key"])
        if definition is None:
            raise ValueError("Unknown canonical parameter: retain source as unresolved clauses")
        if term["unit"] != definition["unit"]:
            raise ValueError("Canonical parameter unit mismatch")
        value = term["value"]
        kind = definition["type"]
        if kind == "boolean":
            valid = isinstance(value, bool)
        elif kind == "text":
            valid = isinstance(value, str) and bool(value.strip()) and len(value) <= 10000
        else:
            valid = (isinstance(value, str) and len(value) <= 72 and bool(_DECIMAL.fullmatch(value))
                     and Decimal("-1") <= Decimal(value) <= Decimal("1"))
        if not valid:
            raise ValueError("Canonical parameter value type or range mismatch")
        if term["rule_pattern"] not in definition["supported_rule_patterns"] and term["rule_pattern"] is not None:
            raise ValueError("Unreviewed rule pattern: retain source as unresolved clauses")
