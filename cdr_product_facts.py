"""Universal, evidence-preserving facts for retained Banking CDR product details."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

SCHEMA_VERSION = 1
NORMALIZATION_VERSION = "cdr-product-facts-1"
_DURATION = re.compile(r"^P(?:[0-9.]+[YMWD])+(?:T(?:[0-9.]+[HMS])+)?$", re.I)
_URL = re.compile(r"^https?://", re.I)
_INDEX = re.compile(r"\[\d+\]")
_NON_KEY = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class TextRule:
    key: str
    value: Any
    patterns: Tuple[str, ...]


# Reviewed, deliberately narrow taxonomy. Add synonyms only with a real fixture.
TEXT_TAXONOMY: Tuple[TextRule, ...] = (
    TextRule("feature.offset", False, (r"\bno offset(?: account| facility)?\b", r"\bdoes not (?:include|offer) (?:an? )?offset\b")),
    TextRule("feature.offset", True, (r"\boffset (?:account|facility) (?:is )?available\b", r"\buse .{0,40} as offsets?\b")),
    TextRule("fee.package", False, (r"\bno (?:annual )?package fee\b", r"\bwithout (?:an? )?(?:annual )?package fee\b")),
    TextRule("fee.package", True, (r"\bannual package fee (?:of|is|applies)\b",)),
    TextRule("feature.redraw", False, (r"\bno redraw(?: facility)?\b", r"\bredraw (?:is )?not available\b", r"\bcannot redraw\b")),
    TextRule("feature.redraw", True, (r"\bredraw facility (?:is )?(?:available|included)\b", r"\baccess to (?:a )?redraw facility\b", r"\bredraws are (?:available|limited)\b")),
    TextRule("feature.extra_repayments", False, (r"\bextra repayments? (?:are )?not (?:allowed|available)\b", r"\bno extra repayments?\b", r"\bcannot make (?:unlimited )?extra repayments?\b")),
    TextRule("feature.extra_repayments", True, (r"\bextra repayments? are (?:allowed|unlimited)\b", r"\bmake (?:unlimited )?extra repayments?\b")),
    TextRule("customer.cohort", "new", (r"\bnew customers? only\b", r"\bnew to bank customers?\b", r"\bnew accounts? only\b")),
    TextRule("customer.cohort", "existing", (r"\bexisting customers? only\b", r"\bexisting customer rate\b")),
    TextRule("loan.purpose", "owner_occupied", (r"\bowner[ -]occup(?:ied|ier)\b",)),
    TextRule("loan.purpose", "investment", (r"\binvest(?:ment|or) (?:home )?loans?\b",)),
    TextRule("loan.repayment", "principal_and_interest", (r"\bprincipal and interest repayments?\b",)),
    TextRule("loan.repayment", "interest_only", (r"\binterest[ -]only repayments?\b",)),
)

_ROOT_KIND = {
    "fees": "fee", "depositRates": "rate", "lendingRates": "rate",
    "features": "feature", "eligibility": "eligibility", "constraints": "constraint",
    "bundles": "bundle", "cardArt": "attribute", "additionalInformation": "attribute",
}
_TYPE_KEYS = {
    "featureType": "feature", "eligibilityType": "eligibility",
    "constraintType": "constraint", "feeType": "fee",
    "rateApplicabilityType": "condition", "discountEligibilityType": "condition",
}
_CANONICAL_LEAVES = {
    "productId": "product.id", "name": "product.name", "brand": "product.brand",
    "brandName": "product.brand_name", "productCategory": "product.category",
    "description": "product.description", "isTailored": "product.tailored",
    "lastUpdated": "product.last_updated", "effectiveFrom": "product.effective_from",
    "effectiveTo": "product.effective_to", "rate": "rate.advertised",
    "comparisonRate": "rate.comparison", "depositRateType": "rate.type",
    "lendingRateType": "rate.type", "applicationType": "rate.application_type",
    "applicationFrequency": "rate.application_frequency",
    "calculationFrequency": "rate.calculation_frequency",
    "interestPaymentDue": "rate.interest_payment_due", "repaymentType": "loan.repayment",
    "loanPurpose": "loan.purpose", "featureType": "feature.type",
    "eligibilityType": "eligibility.type", "constraintType": "constraint.type",
    "feeType": "fee.type", "feeMethodUType": "fee.method", "currency": "currency",
    "feeCap": "fee.cap", "feeCapPeriod": "fee.cap_period", "balanceRate": "fee.balance_rate",
    "transactionRate": "fee.transaction_rate", "accruedRate": "fee.accrued_rate",
    "accrualFrequency": "fee.accrual_frequency", "amount": "amount",
    "minimumValue": "range.minimum", "maximumValue": "range.maximum",
    "unitOfMeasure": "range.unit", "rateApplicationMethod": "tier.application_method",
    "additionalInfo": "condition.text", "additionalValue": "value",
}
_RANGE_PAIRS = (("minimumValue", "maximumValue"), ("feeMinimum", "feeMaximum"), ("discountMinimum", "discountMaximum"))


def source_pattern(path: str) -> str:
    return _INDEX.sub("[]", path)


def _slug(value: str) -> str:
    return _NON_KEY.sub("_", value.lower()).strip("_") or "value"


def _number(value: Any) -> Optional[Decimal]:
    if isinstance(value, bool) or value in (None, "", "null"):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _fraction(value: Any) -> Any:
    number = _number(value)
    if number is None:
        return value
    return float(number)


def _path_context(path: str) -> Tuple[str, str]:
    root = path.split("[", 1)[0].split(".", 1)[0]
    kind = _ROOT_KIND.get(root, "attribute")
    if ".tiers[" in path:
        kind = "tier"
    elif ".applicabilityConditions" in path or ".eligibility[" in path and ".discounts[" in path:
        kind = "condition"
    leaf = path.rsplit(".", 1)[-1]
    canonical = _CANONICAL_LEAVES.get(leaf)
    if root == "fees":
        if leaf == "amount" or ".fixedAmount.amount" in path:
            canonical = "fee.amount"
        elif ".rateBased.rate" in path or leaf in {"balanceRate", "transactionRate", "accruedRate"}:
            canonical = "fee.rate"
        elif leaf == "additionalValue" and ".discounts[" not in path:
            canonical = "fee.cadence"
    elif root == "eligibility" and leaf == "additionalValue":
        canonical = "eligibility.value"
    elif root == "constraints" and leaf == "additionalValue":
        canonical = "constraint.value"
    elif ".tiers[" in path and leaf in {"minimumValue", "maximumValue"}:
        canonical = f"tier.{leaf.removesuffix('Value').lower()}"
    return kind, canonical or f"source.{_slug(source_pattern(path))}"


def _ancestor_value(ancestors: Sequence[Tuple[str, Mapping[str, Any]]], key: str) -> Any:
    return next((item.get(key) for _, item in reversed(ancestors) if item.get(key) not in (None, "")), None)


def _typed_value(path: str, value: Any, parent: Mapping[str, Any], ancestors: Sequence[Tuple[str, Mapping[str, Any]]]) -> Tuple[str, Any, str, str]:
    leaf = path.rsplit(".", 1)[-1]
    canonical = _path_context(path)[1]
    if isinstance(value, bool):
        return "boolean", value, "boolean", "canonical"
    if _URL.match(str(value)):
        return "text", str(value), "text", "preserved"
    if isinstance(value, str) and _DURATION.match(value):
        return "duration", value.upper(), "duration", "canonical"
    # CDR product identifiers are opaque strings. Numeric-looking IDs must retain
    # leading zeroes and arbitrary precision for exact joins and filtering.
    if canonical == "product.id":
        return "text", str(value), "text", "canonical"
    rate_leaf = canonical in {"rate.advertised", "rate.comparison", "fee.rate"} or leaf == "feeRate"
    lvr = canonical in {"constraint.value", "tier.minimum", "tier.maximum"} and (
        parent.get("unitOfMeasure") == "PERCENT" or "LVR" in str(parent.get("constraintType") or "")
    )
    if (rate_leaf or lvr) and (number := _number(value)) is not None:
        fraction = float(number)
        return "rate", fraction, "fraction", "canonical" if abs(fraction) <= 1 else "preserved"
    constraint_type = str(_ancestor_value(ancestors, "constraintType") or "").upper()
    eligibility_type = str(_ancestor_value(ancestors, "eligibilityType") or "").upper()
    tier_unit = str(_ancestor_value(ancestors, "unitOfMeasure") or "").upper()
    if canonical == "fee.cadence" and isinstance(value, str) and _DURATION.match(value):
        return "duration", value.upper(), "duration", "canonical"
    if canonical == "eligibility.value" and eligibility_type in {"MIN_AGE", "MAX_AGE"} and (number := _number(value)) is not None:
        return "number", float(number), "year", "canonical"
    if canonical == "constraint.value" and "LVR" in constraint_type and (number := _number(value)) is not None:
        return "rate", float(number), "fraction", "canonical"
    money = leaf in {"amount", "feeCap", "feeMinimum", "feeMaximum", "discountMinimum", "discountMaximum"}
    money = money or (canonical == "constraint.value" and constraint_type in {"MIN_BALANCE", "MAX_BALANCE", "OPENING_BALANCE", "MIN_LIMIT", "MAX_LIMIT"})
    money = money or (canonical.startswith("tier.") and tier_unit == "DOLLAR")
    money = money or (leaf in {"minimumValue", "maximumValue"} and parent.get("unitOfMeasure") == "DOLLAR")
    if money and (number := _number(value)) is not None:
        return "money", float(number), str(_ancestor_value(ancestors, "currency") or "AUD").upper(), "canonical"
    if canonical in {"tier.minimum", "tier.maximum"} and tier_unit == "PERCENT" and (number := _number(value)) is not None:
        return "rate", float(number), "fraction", "canonical"
    if (number := _number(value)) is not None and leaf not in _TYPE_KEYS:
        return "number", float(number), "count", "canonical"
    if leaf.endswith("Type") or leaf.endswith("UType") or leaf in {"currency", "unitOfMeasure", "rateApplicationMethod", "interestPaymentDue", "repaymentType", "loanPurpose"}:
        return "enum", str(value), "enum", "canonical"
    return "text", str(value), "text", "canonical" if leaf in _CANONICAL_LEAVES else "preserved"


def _qualifiers(path: str, ancestors: Sequence[Tuple[str, Mapping[str, Any]]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for index, (_, item) in enumerate(ancestors):
        for key in ("name", "description", "title", "additionalInfo", "featureType", "eligibilityType", "constraintType", "feeType", "feeMethodUType", "depositRateType", "lendingRateType", "loanPurpose", "repaymentType", "rateApplicabilityType", "discountEligibilityType", "unitOfMeasure", "currency", "applicationFrequency"):
            if key == "name" and index == 0 and len(ancestors) > 1:
                continue
            if item.get(key) not in (None, ""):
                result[key] = item[key]
    result["sourcePattern"] = source_pattern(path)
    return result


def _fact_id(product_key: str, path: str, canonical: str, value: Any, suffix: str = "") -> str:
    material = json.dumps([product_key, path, canonical, suffix], ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]


def _group_id(product_key: str, path: str, parent: Mapping[str, Any]) -> str:
    pattern = path.rsplit(".", 1)[0]
    discriminator = {key: parent.get(key) for key in ("name", "feeType", "featureType", "eligibilityType", "constraintType", "depositRateType", "lendingRateType", "loanPurpose", "repaymentType", "rateApplicabilityType", "discountEligibilityType", "additionalValue") if parent.get(key) not in (None, "")}
    return hashlib.sha256(json.dumps([product_key, pattern, discriminator], sort_keys=True).encode()).hexdigest()[:16]


def _semantic_entity(parent: Mapping[str, Any], path: str) -> Dict[str, Any]:
    return {key: parent.get(key) for key in (
        "name", "feeType", "feeMethodUType", "featureType", "eligibilityType", "constraintType",
        "depositRateType", "lendingRateType", "loanPurpose", "repaymentType", "applicationType",
        "rateApplicabilityType", "discountEligibilityType", "unitOfMeasure",
    ) if parent.get(key) not in (None, "")} | {"entity": source_pattern(path).rsplit(".", 1)[0]}


def _stable_ids(facts: List[Dict[str, Any]], product_key: str) -> List[Dict[str, Any]]:
    """Replace index IDs with semantic entity IDs; disambiguate true duplicate identities deterministically."""
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for fact in facts:
        qualifiers = fact.get("qualifiers") or {}
        entity = {key: qualifiers.get(key) for key in (
            "name", "featureType", "eligibilityType", "constraintType", "feeType", "feeMethodUType",
            "depositRateType", "lendingRateType", "loanPurpose", "repaymentType",
            "rateApplicabilityType", "discountEligibilityType", "unitOfMeasure", "additionalValue",
        ) if qualifiers.get(key) not in (None, "")}
        if str(fact.get("canonical_key") or "").startswith("product."):
            entity.pop("name", None)
        entity["pattern"] = fact["source_pattern"].rsplit(".", 1)[0]
        if fact["mapping"] == "canonical_text":
            entity["tag_value"] = fact.get("value")
        semantic = json.dumps([product_key, fact["canonical_key"], fact["mapping"], entity], ensure_ascii=False, sort_keys=True)
        buckets.setdefault(semantic, []).append(fact)
        group_semantic = json.dumps([product_key, entity], ensure_ascii=False, sort_keys=True)
        qualifiers["groupId"] = hashlib.sha256(group_semantic.encode()).hexdigest()[:16]
    for semantic, rows in buckets.items():
        rows.sort(key=lambda row: (row["source_value_json"], row["source_path"], json.dumps(row.get("value"), sort_keys=True)))
        for occurrence, fact in enumerate(rows):
            suffix = occurrence if len(rows) > 1 else None
            fact["fact_id"] = hashlib.sha256(json.dumps([semantic, suffix], sort_keys=True).encode()).hexdigest()[:20]
    return facts


def _leaf_facts(record: Mapping[str, Any], product_key: str) -> Iterator[Dict[str, Any]]:
    def walk(value: Any, path: str, ancestors: List[Tuple[str, Mapping[str, Any]]]) -> Iterator[Dict[str, Any]]:
        if isinstance(value, Mapping):
            next_ancestors = [*ancestors, (path, value)]
            for key in sorted(value):
                if key in {"links", "meta"}:  # transport envelope, not product evidence
                    continue
                child = f"{path}.{key}" if path else str(key)
                yield from walk(value[key], child, next_ancestors)
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                yield from walk(item, f"{path}[{index}]", ancestors)
            return
        if value in (None, ""):
            return
        parent = ancestors[-1][1] if ancestors else {}
        kind, canonical = _path_context(path)
        value_type, typed, unit, mapping = _typed_value(path, value, parent, ancestors)
        qualifiers = _qualifiers(path, ancestors)
        group_id = _group_id(product_key, path, parent)
        qualifiers["groupId"] = group_id
        if len(ancestors) > 1:
            parent_path, parent_item = ancestors[-2]
            qualifiers["parentId"] = _group_id(product_key, parent_path, parent_item)
        yield {
            "fact_id": _fact_id(product_key, path, canonical, typed, group_id), "kind": kind,
            "canonical_key": canonical, "value_type": value_type, "value": typed,
            "unit": unit, "mapping": mapping, "source_path": path,
            "source_pattern": source_pattern(path),
            "source_value_json": json.dumps(value, ensure_ascii=False, sort_keys=True),
            "qualifiers": qualifiers,
        }
    yield from walk(record, "", [])


def _semantic_facts(record: Mapping[str, Any], product_key: str) -> Iterator[Dict[str, Any]]:
    def walk(value: Any, path: str, parent: Optional[Tuple[str, Mapping[str, Any]]] = None) -> Iterator[Tuple[str, Mapping[str, Any], Optional[Tuple[str, Mapping[str, Any]]]]]:
        if isinstance(value, Mapping):
            yield path, value, parent
            for key, child in value.items():
                yield from walk(child, f"{path}.{key}" if path else key, (path, value))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from walk(child, f"{path}[{index}]", parent)
    for item_path, item, parent in walk(record, ""):
            for type_key, semantic_kind in _TYPE_KEYS.items():
                source_type = item.get(type_key)
                if not source_type:
                    continue
                key = f"{semantic_kind}.{_slug(str(source_type))}"
                path = f"{item_path}.{type_key}"
                group_id = _group_id(product_key, path, item)
                qualifiers = {"sourceType": source_type, "groupId": group_id}
                for field in ("name", "description", "title", "additionalInfo", "additionalValue", "currency", "applicationFrequency", "loanPurpose", "repaymentType", "depositRateType", "lendingRateType"):
                    if item.get(field) not in (None, ""):
                        qualifiers[field] = item[field]
                if parent:
                    qualifiers["parentId"] = _group_id(product_key, parent[0], parent[1])
                yield {
                    "fact_id": _fact_id(product_key, path, key, True, f"semantic:{group_id}"),
                    "kind": semantic_kind, "canonical_key": key, "value_type": "boolean",
                    "value": True, "unit": "boolean", "mapping": "canonical", "source_path": path,
                    "source_pattern": source_pattern(path),
                    "source_value_json": json.dumps(source_type, ensure_ascii=False),
                    "qualifiers": qualifiers,
                }
            if item.get("name") and "bundles[" in item_path:
                group_id = _group_id(product_key, item_path, item)
                yield {
                    "fact_id": _fact_id(product_key, item_path, f"bundle.{_slug(str(item['name']))}", True, group_id),
                    "kind": "bundle", "canonical_key": f"bundle.{_slug(str(item['name']))}",
                    "value_type": "boolean", "value": True, "unit": "boolean", "mapping": "canonical",
                    "source_path": item_path, "source_pattern": source_pattern(item_path),
                    "source_value_json": json.dumps(item, ensure_ascii=False, sort_keys=True),
                    "qualifiers": {key: value for key, value in {"groupId": group_id, "name": item.get("name"), "description": item.get("description"), "additionalInfo": item.get("additionalInfo")}.items() if value not in (None, "")},
                }


def _range_facts(record: Mapping[str, Any], product_key: str) -> Iterator[Dict[str, Any]]:
    def walk(value: Any, path: str, ancestors: List[Tuple[str, Mapping[str, Any]]]):
        if isinstance(value, Mapping):
            for low_key, high_key in _RANGE_PAIRS:
                low, high = value.get(low_key), value.get(high_key)
                if low not in (None, "", "null") or high not in (None, "", "null"):
                    base_path = path or "product"
                    kind, _ = _path_context(base_path)
                    money = low_key != "minimumValue" or value.get("unitOfMeasure") == "DOLLAR"
                    unit = str(_ancestor_value([*ancestors, (path, value)], "currency") or "AUD").upper() if money else "fraction" if value.get("unitOfMeasure") == "PERCENT" else "count"
                    def convert(item: Any) -> Optional[float]:
                        number = _number(item)
                        return float(number) if number is not None else None
                    canonical = "range.amount" if money else "range.value"
                    group_id = _group_id(product_key, base_path, value)
                    min_value, max_value = convert(low), convert(high)
                    if min_value is not None or max_value is not None:
                        yield {
                            "fact_id": _fact_id(product_key, base_path, canonical, None, "range"), "kind": kind,
                            "canonical_key": canonical, "value_type": "range", "value": None,
                            "min_value": min_value, "max_value": max_value, "unit": unit,
                            "mapping": "canonical", "source_path": base_path, "source_pattern": source_pattern(base_path),
                            "source_value_json": json.dumps(value, ensure_ascii=False, sort_keys=True),
                            "qualifiers": {"groupId": group_id},
                        }
            for key, child in value.items():
                yield from walk(child, f"{path}.{key}" if path else key, [*ancestors, (path, value)])
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from walk(child, f"{path}[{index}]", ancestors)
    yield from walk(record, "", [])


def _text_values(record: Mapping[str, Any]) -> Iterator[Tuple[str, str]]:
    def walk(value: Any, path: str) -> Iterator[Tuple[str, str]]:
        if isinstance(value, Mapping):
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else key
                if key == "description" or key == "additionalInfo":
                    if isinstance(child, str) and child.strip():
                        yield child_path, child.strip()
                else:
                    yield from walk(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from walk(child, f"{path}[{index}]")
    yield from walk(record, "")


def _text_facts(record: Mapping[str, Any], product_key: str, structured: Sequence[Mapping[str, Any]]) -> Iterator[Dict[str, Any]]:
    authoritative: Dict[str, set[str]] = {}
    for fact in structured:
        if fact.get("mapping") == "canonical" and fact.get("source_path"):
            authoritative.setdefault(str(fact["canonical_key"]), set()).add(json.dumps(fact.get("value"), sort_keys=True))
    for path, evidence in _text_values(record):
        lower = evidence.lower()
        matched = [
            rule for rule in TEXT_TAXONOMY
            if any(re.search(pattern, lower, re.I) for pattern in rule.patterns)
        ]
        negative_keys = {rule.key for rule in matched if rule.value is False}
        for rule in matched:
            # Negative language takes precedence over a positive substring in the
            # same clause (for example, "No offset account is available").
            if rule.value is True and rule.key in negative_keys:
                continue
            encoded = json.dumps(rule.value, sort_keys=True)
            values = authoritative.get(rule.key, set())
            conflict = bool(values and encoded not in values)
            yield {
                "fact_id": _fact_id(product_key, path, rule.key, rule.value, f"text:{_group_id(product_key, path, {})}"),
                "kind": rule.key.split(".", 1)[0] if rule.key.split(".", 1)[0] in {"fee", "feature", "eligibility", "constraint", "condition"} else "attribute",
                "canonical_key": rule.key, "value_type": "boolean" if isinstance(rule.value, bool) else "enum",
                "value": rule.value, "unit": "boolean" if isinstance(rule.value, bool) else "enum",
                "mapping": "canonical_text", "source_path": path, "source_pattern": source_pattern(path),
                "source_value_json": json.dumps(evidence, ensure_ascii=False),
                "qualifiers": {"authority": "text", "evidence": evidence, "conflict": conflict, "groupId": _group_id(product_key, path, {})},
            }


def extract_product_facts(record: Mapping[str, Any], product_key: str) -> List[Dict[str, Any]]:
    structured = [*_leaf_facts(record, product_key), *_semantic_facts(record, product_key), *_range_facts(record, product_key)]
    facts = [*structured, *_text_facts(record, product_key, structured)]
    return sorted(_stable_ids(facts, product_key), key=lambda fact: (fact["canonical_key"], fact["source_path"], fact["fact_id"]))


def clean_fact_rows(record: Mapping[str, Any], base: Mapping[str, Any]) -> List[Dict[str, Any]]:
    key = "|".join(str(base.get(field) or "") for field in ("dataset", "provider", "product_id"))
    rows = []
    for fact in extract_product_facts(record, key):
        value = fact["value"]
        rows.append({
            **base, **{field: fact[field] for field in ("fact_id", "kind", "canonical_key", "value_type", "unit", "mapping", "source_path", "source_pattern", "source_value_json")},
            "value_boolean": value if isinstance(value, bool) else None,
            "value_number": value if isinstance(value, (int, float)) and not isinstance(value, bool) else None,
            "value_text": value if isinstance(value, str) else None,
            "value_json": json.dumps(value, ensure_ascii=False, sort_keys=True),
            "min_value": fact.get("min_value"), "max_value": fact.get("max_value"),
            "qualifiers_json": json.dumps(fact["qualifiers"], ensure_ascii=False, sort_keys=True),
        })
    return rows


def compact_facts(record: Mapping[str, Any], product_key: str) -> List[Dict[str, Any]]:
    """Mobile facts are one useful row per source entity, not the lossless leaf table."""
    staged: List[Tuple[str, Dict[str, Any]]] = []

    def add(
        kind: str, canonical: str, label: str, entity: Mapping[str, Any], *,
        value: Any = None, unit: str = "text", source_type: Any = None,
        condition: Any = None, cadence: Any = None, applies_to: Optional[List[str]] = None,
        min_value: Any = None, max_value: Any = None, parent_id: Optional[str] = None,
        comparison_value: Any = None, search: bool = True,
    ) -> str:
        identity = json.dumps([product_key, kind, canonical, entity], ensure_ascii=False, sort_keys=True, default=str)
        group_id = hashlib.sha256(identity.encode()).hexdigest()[:16]
        item = {
            "kind": kind, "canonicalKey": canonical, "label": label, "groupId": group_id,
            "parentId": parent_id, "sourceType": source_type, "value": value, "unit": unit,
            "minValue": min_value, "maxValue": max_value, "comparisonValue": comparison_value,
            "cadence": cadence, "appliesTo": applies_to, "condition": condition,
        }
        if search:
            terms = [label, *canonical.replace("_", " ").split(".")]
            if source_type: terms.append(str(source_type).lower().replace("_", " "))
            item["searchTerms"] = sorted(set(term for term in terms if term))
        staged.append((identity, {key: raw for key, raw in item.items() if raw is not None}))
        return group_id

    def condition(item: Mapping[str, Any]) -> Optional[str]:
        value = item.get("additionalInfo")
        return str(value) if value not in (None, "") else None

    for index, item in enumerate(record.get("features") or []):
        if not isinstance(item, Mapping): continue
        source_type = str(item.get("featureType") or "OTHER")
        entity = {"type": source_type, "label": item.get("name") or item.get("additionalValue")}
        add("feature", f"feature.{_slug(source_type)}", str(item.get("name") or source_type.replace("_", " ").title()), entity, value=True, unit="boolean", source_type=source_type, condition=condition(item))

    for group, kind, type_key in (("eligibility", "eligibility", "eligibilityType"), ("constraints", "constraint", "constraintType")):
        for item in record.get(group) or []:
            if not isinstance(item, Mapping): continue
            source_type = str(item.get(type_key) or "OTHER")
            raw = item.get("additionalValue")
            synthetic_path = f"{group}[0].additionalValue"
            value_type, value, unit, _ = _typed_value(synthetic_path, raw, item, [(group, item)]) if raw not in (None, "") else ("text", True, "boolean", "canonical")
            entity = {"type": source_type, "label": item.get("name")}
            add(kind, f"{kind}.{_slug(source_type)}", str(item.get("name") or source_type.replace("_", " ").title()), entity, value=value, unit=unit, source_type=source_type, condition=condition(item))

    for item in record.get("bundles") or []:
        if not isinstance(item, Mapping): continue
        name = str(item.get("name") or "Bundle")
        add("bundle", f"bundle.{_slug(name)}", name, {"name": name}, value=True, unit="boolean", source_type=name, condition=item.get("additionalInfo") or item.get("description"))

    for item in record.get("fees") or []:
        if not isinstance(item, Mapping): continue
        name = str(item.get("name") or item.get("feeType") or "Fee")
        fee_type, method = item.get("feeType"), item.get("feeMethodUType")
        entity = {"name": name, "type": fee_type, "method": method}
        value = min_value = max_value = None; unit = str(item.get("currency") or "AUD").upper()
        fixed = item.get("fixedAmount") if isinstance(item.get("fixedAmount"), Mapping) else {}
        rated = item.get("rateBased") if isinstance(item.get("rateBased"), Mapping) else {}
        variable = item.get("variable") if isinstance(item.get("variable"), Mapping) else {}
        raw_amount = item.get("amount") if item.get("amount") not in (None, "") else fixed.get("amount")
        if method == "rateBased" or rated.get("rate") not in (None, ""):
            value, unit = _fraction(rated.get("rate") if rated.get("rate") not in (None, "") else item.get("transactionRate")), "fraction"
        elif raw_amount not in (None, ""):
            value = float(_number(raw_amount)) if _number(raw_amount) is not None else raw_amount
        elif variable:
            min_value = float(_number(variable.get("feeMinimum"))) if _number(variable.get("feeMinimum")) is not None else None
            max_value = float(_number(variable.get("feeMaximum"))) if _number(variable.get("feeMaximum")) is not None else None
        cadence = item.get("additionalValue") if isinstance(item.get("additionalValue"), str) and _DURATION.match(str(item.get("additionalValue"))) else item.get("accrualFrequency")
        fee_group = add("fee", f"fee.{_slug(name)}", name, entity, value=value, unit=unit, source_type=fee_type, condition=condition(item), cadence=cadence, min_value=min_value, max_value=max_value)
        for discount in item.get("discounts") or []:
            if not isinstance(discount, Mapping): continue
            description = str(discount.get("description") or "Fee discount")
            add("condition", "fee.discount", description, {"fee": entity, "description": description, "type": discount.get("discountType")}, value=True, unit="boolean", source_type=discount.get("discountType"), condition=discount.get("additionalInfo") or description, parent_id=fee_group)

    for family, key, type_key in (("deposit", "depositRates", "depositRateType"), ("lending", "lendingRates", "lendingRateType")):
        for rate in record.get(key) or []:
            if not isinstance(rate, Mapping): continue
            rate_type = str(rate.get(type_key) or "OTHER")
            applies = [str(rate[field]) for field in ("loanPurpose", "repaymentType") if rate.get(field)]
            entity = {field: rate.get(field) for field in (type_key, "loanPurpose", "repaymentType", "applicationType", "additionalValue") if rate.get(field) not in (None, "")}
            rate_group = add("rate", f"rate.{family}.{_slug(rate_type)}", rate_type.replace("_", " ").title(), entity, value=_fraction(rate.get("rate")), comparison_value=_fraction(rate.get("comparisonRate")) if rate.get("comparisonRate") not in (None, "") else None, unit="fraction", source_type=rate_type, cadence=rate.get("applicationFrequency"), applies_to=applies or None, condition=condition(rate))
            tiers = rate.get("tiers") or []
            for tier in tiers if isinstance(tiers, list) else []:
                if not isinstance(tier, Mapping): continue
                unit_name = str(tier.get("unitOfMeasure") or "").upper()
                unit = "AUD" if unit_name == "DOLLAR" else "fraction" if unit_name == "PERCENT" else "count"
                convert = _fraction if unit == "fraction" else lambda raw: float(_number(raw)) if _number(raw) is not None else None
                tier_entity = {"parent": entity, "name": tier.get("name"), "unit": unit_name, "minimum": tier.get("minimumValue"), "maximum": tier.get("maximumValue")}
                tier_group = add("tier", "tier.range", str(tier.get("name") or "Rate tier"), tier_entity, unit=unit, source_type=tier.get("rateApplicationMethod"), min_value=convert(tier.get("minimumValue")), max_value=convert(tier.get("maximumValue")), condition=condition(tier), parent_id=rate_group)
                tier_conditions = tier.get("applicabilityConditions")
                if isinstance(tier_conditions, Mapping): tier_conditions = [tier_conditions]
                for applies_item in tier_conditions or []:
                    if not isinstance(applies_item, Mapping): continue
                    source_type = str(applies_item.get("rateApplicabilityType") or "OTHER")
                    add("condition", f"condition.{_slug(source_type)}", source_type.replace("_", " ").title(), {"parent": tier_entity, "type": source_type, "value": applies_item.get("additionalValue")}, value=True, unit="boolean", source_type=source_type, condition=condition(applies_item), parent_id=tier_group)
            rate_conditions = rate.get("applicabilityConditions")
            if isinstance(rate_conditions, Mapping): rate_conditions = [rate_conditions]
            for applies_item in rate_conditions or []:
                if not isinstance(applies_item, Mapping): continue
                source_type = str(applies_item.get("rateApplicabilityType") or "OTHER")
                add("condition", f"condition.{_slug(source_type)}", source_type.replace("_", " ").title(), {"parent": entity, "type": source_type, "value": applies_item.get("additionalValue")}, value=True, unit="boolean", source_type=source_type, condition=condition(applies_item), parent_id=rate_group)

    semantic_evidence = list(_semantic_facts(record, product_key))
    authoritative_keys = {fact["canonical_key"] for fact in semantic_evidence}
    for fact in _text_facts(record, product_key, semantic_evidence):
        if fact["canonical_key"] in authoritative_keys and not fact["qualifiers"].get("conflict"):
            continue
        if fact["mapping"] != "canonical_text": continue
        qualifiers = fact["qualifiers"]
        add(fact["kind"], fact["canonical_key"], fact["canonical_key"].replace(".", " ").replace("_", " ").title(), {"text_tag": fact["canonical_key"], "value": fact["value"], "condition": qualifiers.get("evidence")}, value=fact["value"], unit=fact["unit"], source_type="canonical_text", condition=qualifiers.get("evidence"), search=False)

    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for identity, item in staged: buckets.setdefault(identity, []).append(item)
    out: List[Dict[str, Any]] = []
    for identity, items in sorted(buckets.items()):
        items.sort(key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, default=str))
        for occurrence, item in enumerate(items):
            item["id"] = hashlib.sha256(json.dumps([identity, occurrence if len(items) > 1 else None], sort_keys=True).encode()).hexdigest()[:20]
            out.append(item)
    return out


def audit_records(
    records: Iterable[Tuple[str, Mapping[str, Any]]],
    source_failures: Optional[Iterable[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    inventory: Dict[str, Dict[str, Any]] = {}
    text_total = text_tagged = 0
    record_count = fact_count = 0
    uncovered: set[str] = set()
    observed_scalars = covered_scalars = 0
    duplicate_fact_ids: List[Dict[str, str]] = []
    for product_key, record in records:
        record_count += 1
        facts = extract_product_facts(record, product_key)
        fact_count += len(facts)
        ids: set[str] = set()
        for fact in facts:
            if fact["fact_id"] in ids:
                duplicate_fact_ids.append({"product_key": product_key, "fact_id": fact["fact_id"]})
            ids.add(fact["fact_id"])
        covered_exact = {fact["source_path"]: fact["mapping"] for fact in facts if fact["mapping"] not in {"canonical_text"} and fact["value_type"] != "range"}
        covered = {source_pattern(path): mapping for path, mapping in covered_exact.items()}
        def scalar_paths(value: Any, path: str = "") -> Iterator[Tuple[str, str]]:
            if isinstance(value, Mapping):
                for key, child in value.items():
                    if key in {"links", "meta"}:
                        continue
                    yield from scalar_paths(child, f"{path}.{key}" if path else key)
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    yield from scalar_paths(child, f"{path}[{index}]")
            elif value not in (None, ""):
                yield path, source_pattern(path)
        scalar_rows = list(scalar_paths(record))
        observed_scalars += len(scalar_rows)
        covered_scalars += sum(path in covered_exact for path, _ in scalar_rows)
        uncovered.update(pattern for path, pattern in scalar_rows if path not in covered_exact)
        for fact in facts:
            path = fact["source_pattern"]
            entry = inventory.setdefault(path, {"path": path, "observations": 0, "status": covered.get(path, "preserved")})
            entry["observations"] += 1
            if fact["mapping"] == "canonical":
                entry["status"] = "canonical"
        for path, evidence in _text_values(record):
            text_total += 1
            if any(re.search(pattern, evidence, re.I) for rule in TEXT_TAXONOMY for pattern in rule.patterns):
                text_tagged += 1
    failures = [dict(item) for item in (source_failures or []) if isinstance(item, Mapping)]
    detail_failures = [item for item in failures if str(item.get("phase") or "") == "product_detail"]
    return {
        "schema_version": SCHEMA_VERSION, "normalization_version": NORMALIZATION_VERSION,
        "records": record_count, "facts": fact_count, "unmapped_nonempty_scalar_paths": sorted(uncovered),
        "observed_nonempty_scalars": observed_scalars, "covered_nonempty_scalars": covered_scalars,
        "duplicate_fact_ids": sorted(duplicate_fact_ids, key=lambda item: (item["product_key"], item["fact_id"])),
        "source_failures": failures,
        "detail_failures": detail_failures,
        "complete": not failures and not uncovered and not duplicate_fact_ids,
        "text_coverage": {
            "observed": text_total, "tagged": text_tagged, "unmatched": text_total - text_tagged,
            "unmatched_semantic_status": "preserved_not_equivalent",
        },
        "fields": sorted(inventory.values(), key=lambda item: item["path"]),
    }


def records_from_runs(root: Path) -> Iterator[Tuple[str, Mapping[str, Any]]]:
    for path in sorted(root.rglob("product-detail.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        record = raw.get("data", raw) if isinstance(raw, Mapping) else {}
        if isinstance(record, Mapping):
            yield str(record.get("productId") or path.parent.name), record


def failures_from_runs(root: Path) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    for path in sorted(root.rglob("failures.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                value = {"phase": "unknown", "status": "invalid_failure_record"}
            if isinstance(value, Mapping):
                failures.append(dict(value))
    return failures


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Audit retained Banking CDR product-detail fact coverage.")
    parser.add_argument("root", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    report = audit_records(records_from_runs(root), failures_from_runs(root))
    rendered = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 1 if not report["complete"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
