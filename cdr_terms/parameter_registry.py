"""Versioned interpretation vocabulary; recognition never approves executable rules."""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Mapping, Sequence

from .identity import digest

VERSION = "terms-parameters-v4"
ACTIVITY_VERSION = "terms-parameters-v5"
ACTIVITY_STAGING = 'analysis-staging-material-v3'
ACTIVITY_STAGING_SHA = 'cd81ce5794c896eb16d78290fc543a44744aa8fcccea13164cc2714ccc407cf5'
SAVINGS_VERSION = "terms-parameters-v3"
PREVIOUS_VERSION = "terms-parameters-v2"
MATERIAL_STAGING='analysis-staging-material-v1'
MATERIAL_STAGING_SHA='cefd91e370e8d1b6275fee0bf6af1c302d31b01674babd978811440ced28a02c'
MORTGAGE_STAGING='analysis-staging-material-v2'
MORTGAGE_STAGING_SHA='28b383438d485ed6f574745887ffafae4d4bda6b80690e9b18603be56a2b4efe'
MORTGAGE_FIELD_SHA='1c8242e6164bf4a882a45df0f97473f2c0def77e12551d83ca82483c611702f1'
LEGACY_VERSION = "terms-parameters-v1"
_DECIMAL = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
# Retained v1 aliases are preserved byte-for-byte. V2 omits bare leaves:
# cdr_product_facts._path_context shows that their meaning depends on containers.
_TEXT = (
    ("product.name", ("name",)), ("product.description", ("description",)),
    ("product.brand_name", ("brandName",)), ("product.category", ("productCategory",)),
    ("rate.type", ("depositRateType", "lendingRateType")),
    ("loan.repayment", ("repaymentType",)), ("loan.purpose", ("loanPurpose",)),
    ("fee.type", ("feeType",)), ("fee.method", ("feeMethodUType",)),
    ("tier.application_method", ("rateApplicationMethod",)),
)


def registry_contract(version: str = VERSION) -> dict[str, Any]:
    """Return fresh JSON values so callers cannot mutate the process registry."""
    if version not in (ACTIVITY_VERSION, VERSION, SAVINGS_VERSION, PREVIOUS_VERSION, LEGACY_VERSION):
        raise ValueError("Unsupported parameter registry version")
    parameters = [{"key": key, "aliases": list(aliases), "type": "text", "unit": None}
                  for key, aliases in _TEXT]
    parameters.append({"key": "product.tailored", "aliases": ["isTailored"],
                       "type": "boolean", "unit": None})
    for key, alias in (("rate.advertised", "rate"), ("rate.comparison", "comparisonRate")):
        parameters.append({"key": key, "aliases": [alias], "type": "decimal",
                           "unit": "fraction_per_year"})
    for row in parameters:
        if version != LEGACY_VERSION:
            # A leaf has no container identity: even rate can belong to a fee,
            # and nested product attributes are not root product attributes.
            row['aliases'] = []
        row.update(applicability="source_scoped_only", supported_rule_patterns=[])
    if version in (ACTIVITY_VERSION,VERSION,SAVINGS_VERSION):
        parameters.append(dict(key='monetary.savings_base_field_v1',aliases=[],type='structured_material',unit=None,
            applicability='source_scoped_only',supported_rule_patterns=[],
            value_schema_sha256='ca1dc03ba73dffc5430f249a4e7968ea288adb053bfdb8d85b66a2d444286953'))
    if version in (ACTIVITY_VERSION,VERSION):
        parameters.append(dict(key='monetary.mortgage_field_v1',aliases=[],type='structured_material',unit=None,
            applicability='source_scoped_only',supported_rule_patterns=[],value_schema_sha256=MORTGAGE_FIELD_SHA))
    if version == ACTIVITY_VERSION:
        from .executable_v4_contract import INVENTORY_SHA
        parameters.append(dict(key='monetary.savings_activity_field_v1',aliases=[],type='structured_material',unit=None,
            applicability='source_scoped_only',supported_rule_patterns=[],value_schema_inventory_sha256=INVENTORY_SHA))
    body = {"version": version, "parameters": sorted(parameters, key=lambda row: row["key"]),
            "unknown_policy": "Retain unmatched wording as unresolved clauses with a reason; do not invent canonical keys.",
            "qualification_policy": "Preserve source product/tier/package/cohort, conditions, exceptions and dates; recognition is not semantic or executable approval."}
    return {**body, "sha256": digest(body)}


def validate_registry_context(context: Mapping[str, Any], *, new_job: bool = False) -> None:
    if "parameter_registry" not in context:
        if new_job:
            raise ValueError("Current parameter registry required for new jobs")
        return  # Immutable legacy jobs keep their existing interpretation contract.
    supplied = context["parameter_registry"]
    version = supplied.get('version') if isinstance(supplied, dict) else None
    supported = (VERSION,ACTIVITY_VERSION) if new_job else (ACTIVITY_VERSION,VERSION,SAVINGS_VERSION, PREVIOUS_VERSION, LEGACY_VERSION)
    if version not in supported or supplied != registry_contract(version):
        raise ValueError("Unsupported or altered parameter registry context")
    contract=interpretation_contract(version)
    if contract and (context.get('interpretation_contract'),context.get('interpretation_schema_sha256'))!=contract:
        raise ValueError('Material registry interpretation schema binding differs')


def interpretation_contract(version=VERSION):
    return {ACTIVITY_VERSION:(ACTIVITY_STAGING,ACTIVITY_STAGING_SHA),SAVINGS_VERSION:(MATERIAL_STAGING,MATERIAL_STAGING_SHA),
            VERSION:(MORTGAGE_STAGING,MORTGAGE_STAGING_SHA)}.get(version)


def canonical_parameter(value: str) -> str | None:
    """Recognize current canonical identifiers; bare source leaves are ambiguous."""
    for row in registry_contract()["parameters"]:
        if value == row["key"] or value in row["aliases"]:
            return row["key"]
    return None


def validate_parameter_terms(context: Mapping[str, Any], terms: Sequence[Mapping[str, Any]]) -> None:
    validate_registry_context(context)
    if "parameter_registry" not in context:
        return
    definitions = {row["key"]: row for row in context['parameter_registry']["parameters"]}
    for term in terms:
        definition = definitions.get(term["parameter_key"])
        if definition is None:
            raise ValueError("Unknown canonical parameter: retain source as unresolved clauses")
        if term["unit"] != definition["unit"]:
            raise ValueError("Canonical parameter unit mismatch")
        value = term["value"]
        kind = definition["type"]
        if kind == 'structured_material':
            if term['parameter_key']=='monetary.savings_activity_field_v1':
                from .executable_v4_material import validate_field_value
            elif term['parameter_key']=='monetary.mortgage_field_v1':
                from .mortgage_material_fields import validate_field_value
            else:
                from .monetary_material_fields import validate_field_value
            validate_field_value(value)
            valid=True
        elif kind == "boolean":
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
