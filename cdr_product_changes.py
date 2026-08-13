"""Deterministic longitudinal changes between normalized Banking CDR facts.

The pure diff accepts normalized fact lists supplied by callers.  The run-level
wrapper only loads finalized product details and enriches their normalized
facts.  There is no network, LLM, or runtime semantic inference.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from cdr_clean_export import bank_base_row, inner_record, load_json
from cdr_product_facts import NORMALIZATION_VERSION, extract_product_facts


SCHEMA_VERSION = 1
_SPACE = re.compile(r"\s+")
_PUNCT = re.compile(r"[^a-z0-9]+", re.I)
_WORDS = re.compile(r"[a-z]+(?:'[a-z]+)?", re.I)
_NUMBER = re.compile(
    r"(?P<op><=|>=|<|>|no more than|no less than|greater than|less than|more than|"
    r"at least|at most|up to)?\s*(?P<currency>\$|AUD\s*)?"
    r"(?P<num>\d+(?:,\d{3})*(?:\.\d+)?)\s*"
    r"(?P<unit>%|percent|dollars?|days?|weeks?|fortnights?|months?|years?)?",
    re.I,
)
_DURATION = re.compile(r"\bP(?:[0-9.]+[YMWD])+(?:T(?:[0-9.]+[HMS])+)?\b", re.I)
_EXCEPTIONS = ("except", "unless", "excluding", "other than", "apart from", "with the exception")
_NEGATIONS = {"no", "not", "never", "without", "neither", "nor", "cannot", "can't", "unavailable"}
_MODALITY = {
    "must": "required", "required": "required", "requires": "required", "shall": "required",
    "may": "permitted", "can": "permitted", "permitted": "permitted",
    "cannot": "prohibited", "can't": "prohibited", "should": "recommended",
}
_CADENCE = {
    "daily": "P1D", "day": "P1D", "weekly": "P1W", "week": "P1W",
    "fortnightly": "P2W", "fortnight": "P2W", "monthly": "P1M", "month": "P1M",
    "quarterly": "P3M", "quarter": "P3M", "annually": "P1Y", "annual": "P1Y",
    "yearly": "P1Y", "year": "P1Y",
}
_TIMING = {"after", "before", "by", "during", "from", "per", "until", "within"}
_COHORTS = {
    "applicant", "applicants", "borrower", "borrowers", "business", "businesses",
    "child", "children", "customer", "customers", "existing", "individual", "individuals",
    "investor", "investors", "member", "members", "new", "owner", "owners",
    "resident", "residents", "staff", "student", "students", "youth",
}
_ACTORS = {"applicant", "applicants", "bank", "borrower", "borrowers", "customer", "customers", "lender", "member", "members", "you", "your"}
_SCOPES = {
    "account", "accounts", "application", "applications", "balance", "balances",
    "deposit", "deposits", "loan", "loans", "mortgage", "mortgages", "product", "products",
    "purchase", "purchases", "refinance", "refinancing", "transaction", "transactions",
    "withdrawal", "withdrawals",
}
_OPERATORS = {
    "at least": ">=", "no less than": ">=", "more than": ">", "greater than": ">",
    "at most": "<=", "no more than": "<=", "up to": "<=", "less than": "<",
}
_UNITS = {
    "%": "percent", "percent": "percent", "dollar": "AUD", "dollars": "AUD",
    "day": "day", "days": "day", "week": "week", "weeks": "week",
    "fortnight": "fortnight", "fortnights": "fortnight", "month": "month", "months": "month",
    "year": "year", "years": "year",
}
_PRODUCT_ALIASES = {
    "provider": ("provider",), "product_id": ("product_id", "productId"), "dataset": ("dataset",),
}
_PRODUCT_NAMES = ("product_name", "productName")
_TEXT_FIELDS = (
    "text", "description", "condition", "conditions", "qualifier", "info",
    "additional_info", "additionalInfo", "additional_value", "additionalValue",
)
_VALUE_FIELDS = (
    "value", "amount", "rate", "comparison_rate", "comparisonRate", "balance_rate",
    "balanceRate", "transaction_rate", "transactionRate", "fee_rate", "feeRate",
    "value_boolean", "value_number", "value_text", "value_json",
)
_RANGE_FIELDS = (
    "minimum", "maximum", "min", "max", "lower", "upper", "operator", "unit",
    "min_value", "max_value", "minValue", "maxValue", "minimumValue", "maximumValue",
    "feeMinimum", "feeMaximum",
)
_CADENCE_FIELDS = (
    "cadence", "frequency", "timing", "period", "accrual_frequency", "accrualFrequency",
    "applicationFrequency", "calculationFrequency", "feeCapPeriod",
)
_QUALIFIER_ID_FIELDS = (
    "name", "sourceType", "feeType", "feeMethodUType", "featureType",
    "eligibilityType", "constraintType", "discountEligibilityType", "loanPurpose",
    "repaymentType", "depositRateType", "lendingRateType", "rateApplicabilityType",
    "unitOfMeasure", "currency", "applicationFrequency",
)
_EVENT_ORDER = {
    "product_added": 0, "product_removed": 1, "product_renamed": 2,
    "ambiguous_match": 3, "fact_added": 4, "fact_removed": 5, "value_changed": 6,
    "range_changed": 7, "cadence_changed": 8, "condition_changed": 9,
    "wording_changed": 10, "metadata_changed": 11,
}
_INDEX = re.compile(r"\[\d+\]")


def _decimal_text(value: str) -> str:
    try:
        return format(Decimal(value.replace(",", "")).normalize(), "f")
    except InvalidOperation:
        return value


def _banking_distinctions(text: str) -> Dict[str, List[str]]:
    plain = _SPACE.sub(" ", re.sub(r"[-_/]+", " ", text.casefold())).strip()

    def present(pattern: str) -> bool:
        return re.search(pattern, plain, re.I) is not None

    residency: List[str] = []
    if present(r"\bnon\s+residents?\b"):
        residency.append("non_resident")
    if present(r"\bpermanent\s+residents?\b"):
        residency.append("permanent_resident")
    if present(r"\btemporary\s+residents?\b"):
        residency.append("temporary_resident")
    if present(r"\bcitizens?\b"):
        residency.append("citizen")

    employment: List[str] = []
    if present(r"\bself\s+employed\b"):
        employment.append("self_employed")
    elif present(r"\bemployed\b"):
        employment.append("employed")

    customer_status = []
    if present(r"\bnew\s+(?:customers?|members?|borrowers?|applicants?)\b"):
        customer_status.append("new")
    if present(r"\bexisting\s+(?:customers?|members?|borrowers?|applicants?)\b"):
        customer_status.append("existing")

    offset_access = []
    if present(r"\b(?:without|no)\s+(?:an?\s+)?offset\b"):
        offset_access.append("without_offset")
    elif present(r"\bwith\s+(?:an?\s+)?offset\b"):
        offset_access.append("with_offset")

    period_timing = []
    if present(r"\bbefore\s+(?:the\s+)?(?:start\s+of\s+the\s+)?period\b"):
        period_timing.append("before_period")
    if present(r"\bafter\s+(?:the\s+)?(?:end\s+of\s+the\s+)?period\b"):
        period_timing.append("after_period")
    if present(r"\b(?:at\s+the\s+)?end\s+of\s+(?:the\s+)?period\b"):
        period_timing.append("end_of_period")

    return {
        "rate_structure": sorted(
            value for value, pattern in (
                ("fixed", r"\bfixed(?:\s+rate)?\b"),
                ("variable", r"\bvariable(?:\s+rate)?\b"),
            ) if present(pattern)
        ),
        "occupancy": sorted(
            value for value, pattern in (
                ("owner_occupied", r"\bowner\s+occup(?:ied|ier)\b"),
                ("investment", r"\binvestment\b"),
            ) if present(pattern)
        ),
        "repayment_structure": sorted(
            value for value, pattern in (
                ("principal_and_interest", r"\b(?:principal\s+(?:and|&)\s+interest|p\s*(?:&|and)\s*i)\b"),
                ("interest_only", r"\binterest\s+only\b"),
            ) if present(pattern)
        ),
        "customer_status": customer_status,
        "residency": residency,
        "employment": employment,
        "legal_entity": sorted(
            value for value, pattern in (
                ("individual", r"\bindividuals?\b"),
                ("business", r"\bbusiness(?:es)?\b"),
                ("trust", r"\btrusts?\b"),
            ) if present(pattern)
        ),
        "channel": sorted(
            value for value, pattern in (
                ("online", r"\bonline\b"),
                ("branch", r"\bbranch(?:es)?\b"),
            ) if present(pattern)
        ),
        "offset_access": offset_access,
        "period_timing": period_timing,
    }


def semantic_clause_signature(text: str) -> Dict[str, Any]:
    """Extract explicit semantic slots without claiming paraphrase equivalence."""
    normalized = _SPACE.sub(" ", str(text or "").strip())
    folded = normalized.casefold()
    words = [word.casefold() for word in _WORDS.findall(folded)]
    thresholds = []
    for match in _NUMBER.finditer(normalized):
        raw_operator = (match.group("op") or "=").casefold()
        raw_unit = (match.group("unit") or "").casefold()
        unit = "AUD" if match.group("currency") else _UNITS.get(raw_unit, raw_unit or "number")
        thresholds.append({
            "operator": _OPERATORS.get(raw_operator, raw_operator),
            "value": _decimal_text(match.group("num")),
            "unit": unit,
        })
    cadence_timing = {_CADENCE[word] for word in words if word in _CADENCE}
    cadence_timing.update(word for word in words if word in _TIMING)
    cadence_timing.update(match.upper() for match in _DURATION.findall(normalized))
    return {
        "negation": sorted(set(words) & _NEGATIONS),
        "modality": sorted({_MODALITY[word] for word in words if word in _MODALITY}),
        "thresholds": sorted(thresholds, key=lambda item: (item["operator"], item["value"], item["unit"])),
        "cadence_timing": sorted(cadence_timing),
        "cohorts": sorted(set(words) & _COHORTS),
        "actors": sorted(set(words) & _ACTORS),
        "applicability_scope": sorted((set(words) & _SCOPES) | ({"only"} if "only" in words else set())),
        "exceptions": [marker for marker in _EXCEPTIONS if marker in folded],
        **_banking_distinctions(folded),
    }


# Backward-compatible integration name used by the initial run wrapper.
clause_signature = semantic_clause_signature


def _first(row: Mapping[str, Any], fields: Sequence[str]) -> Any:
    for field in fields:
        value = row.get(field)
        if value is not None and str(value).strip():
            return value
    return None


def _product_key(fact: Mapping[str, Any]) -> Tuple[str, str, str]:
    values = []
    for name, aliases in _PRODUCT_ALIASES.items():
        value = _first(fact, aliases)
        if value is None:
            raise ValueError(f"normalized fact is missing required product field {name!r}: {fact!r}")
        values.append(str(value).strip())
    return tuple(values)  # type: ignore[return-value]


def _qualifiers(fact: Mapping[str, Any]) -> Mapping[str, Any]:
    value = fact.get("qualifiers")
    if isinstance(value, Mapping):
        return value
    encoded = fact.get("qualifiers_json")
    if isinstance(encoded, str):
        try:
            parsed = json.loads(encoded)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, Mapping) else {}
    return {}


def _fact_key(fact: Mapping[str, Any]) -> Tuple[str, str]:
    kind = str(_first(fact, ("kind", "fact_type", "factType", "category", "section")) or "").casefold()
    canonical = _first(fact, ("canonical_key", "canonicalKey", "fact_key", "factKey", "path"))
    if canonical is not None:
        return kind, str(canonical)
    explicit = _first(fact, ("fact_id", "factId", "id"))
    if explicit is not None:
        return kind, str(explicit)
    name = _first(fact, ("name", "label", "title"))
    if name is None:
        raise ValueError(f"normalized fact needs a stable fact key: {fact!r}")
    return kind, _cosmetic_fold(name)


def _cosmetic_fold(value: Any) -> str:
    return _PUNCT.sub("", str(value or "").casefold())


def _evidence_text(fact: Mapping[str, Any]) -> str:
    encoded = fact.get("source_value_json")
    if isinstance(encoded, str):
        try:
            parsed = json.loads(encoded)
        except json.JSONDecodeError:
            parsed = encoded
        if isinstance(parsed, str):
            return parsed
    parts = []
    for field in ("name", "label", "title", *_TEXT_FIELDS):
        value = fact.get(field)
        if value is not None and str(value).strip():
            parts.append(str(value))
    return " ".join(parts)


def _product_name(facts: Sequence[Mapping[str, Any]]) -> str:
    names = {str(_first(fact, _PRODUCT_NAMES) or "").strip() for fact in facts}
    names.discard("")
    if len(names) > 1:
        raise ValueError(f"normalized facts disagree on product name: {sorted(names)!r}")
    return next(iter(names), "")


def _index(facts: Iterable[Mapping[str, Any]]) -> Dict[Tuple[str, str, str], List[Dict[str, Any]]]:
    products: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    for supplied in facts:
        if not isinstance(supplied, Mapping):
            raise TypeError(f"normalized facts must be mappings, got {type(supplied).__name__}")
        fact = deepcopy(dict(supplied))
        product_key = _product_key(fact)
        _fact_key(fact)  # Validate before accepting the supplied record.
        products.setdefault(product_key, []).append(fact)
    return products


def _entity_instance(fact: Mapping[str, Any]) -> str:
    """Return the source object containing a fact, preserving indices for grouping only."""
    path = str(fact.get("source_path") or "")
    if path and "]" in path:
        return path[:path.rfind("]") + 1]
    explicit = _first(fact, ("fact_id", "factId", "id"))
    if not path and explicit is not None:
        return f"explicit:{explicit}"
    return "product"


def _entity_pattern(instance: str, facts: Sequence[Mapping[str, Any]]) -> str:
    if instance == "product" or instance.startswith("explicit:"):
        return instance
    return _INDEX.sub("[]", instance)


def _entity_family(pattern: str, facts: Sequence[Mapping[str, Any]]) -> str:
    if pattern != "product":
        return pattern.split(".", 1)[0].split("[", 1)[0].casefold()
    return str(_first(facts[0], ("kind", "fact_type", "factType", "category")) or "product").casefold()


def _entity_qualifiers(family: str, facts: Sequence[Mapping[str, Any]]) -> Dict[str, List[Any]]:
    if family.startswith("fee"):
        allowed = {"name", "feeType", "feeMethodUType", "currency"}
    elif "rate" in family or family in {"tiers", "tier"}:
        allowed = {
            "depositRateType", "lendingRateType", "loanPurpose", "repaymentType",
            "rateApplicabilityType", "applicationFrequency", "unitOfMeasure", "currency",
        }
    elif family.startswith(("feature", "eligib", "constraint")):
        allowed = {
            "name", "sourceType", "featureType", "eligibilityType", "constraintType",
            "discountEligibilityType", "unitOfMeasure", "currency",
        }
    else:
        allowed = set(_QUALIFIER_ID_FIELDS)
    values: Dict[str, set[str]] = {}
    for fact in facts:
        product_name = str(_first(fact, _PRODUCT_NAMES) or "")
        for key, value in _qualifiers(fact).items():
            if key not in allowed or value in (None, ""):
                continue
            if key == "name" and str(value) == product_name:
                continue
            values.setdefault(key, set()).add(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))
    return {key: [json.loads(value) for value in sorted(items)] for key, items in sorted(values.items())}


def _identity_fact_value(fact: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "canonical_key": _fact_key(fact)[1],
        "value": _fact_value(fact),
        "min_value": fact.get("min_value"),
        "max_value": fact.get("max_value"),
        "unit": fact.get("unit"),
        "evidence": _evidence_text(fact),
    }


def _entity_descriptor(facts: Sequence[Mapping[str, Any]], *, exact: bool) -> str:
    instance = _entity_instance(facts[0])
    pattern = _entity_pattern(instance, facts)
    family = _entity_family(pattern, facts)
    identity_facts: List[Dict[str, Any]] = []
    for fact in facts:
        canonical = _fact_key(fact)[1].casefold()
        include = canonical.endswith(".type") or canonical in {
            "fee.method", "loan.purpose", "loan.repayment", "repayment.type",
            "rate.application", "rate.application.method",
        }
        if exact and (canonical.startswith(("range.", "tier.")) or canonical == "condition.text"):
            include = True
        if include:
            identity_facts.append(_identity_fact_value(fact))
    descriptor = {
        "pattern": pattern,
        "family": family,
        "qualifiers": _entity_qualifiers(family, facts),
        "identity_facts": sorted(identity_facts, key=lambda row: json.dumps(row, sort_keys=True, default=str)),
    }
    return json.dumps(descriptor, ensure_ascii=False, sort_keys=True, default=str)


def _semantic_fact(fact: Mapping[str, Any]) -> Dict[str, Any]:
    """Strip array-position provenance before testing semantic equality."""
    ignored = {
        "fact_id", "factId", "id", "source_path", "source_pattern", "qualifiers_json",
        *_PRODUCT_NAMES, *_PRODUCT_ALIASES["provider"], *_PRODUCT_ALIASES["product_id"],
        *_PRODUCT_ALIASES["dataset"],
    }
    normalized = {key: deepcopy(value) for key, value in fact.items() if key not in ignored}
    qualifiers = {
        key: value for key, value in _qualifiers(fact).items()
        if key not in {"groupId", "parentId", "sourcePattern"}
    }
    if qualifiers:
        normalized["qualifiers"] = qualifiers
    return normalized


def _content_fingerprint(facts: Sequence[Mapping[str, Any]]) -> str:
    rows = sorted(
        (_semantic_fact(fact) for fact in facts),
        key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True, default=str),
    )
    return json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)


def _entities(facts: Sequence[Mapping[str, Any]]) -> List[List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for fact in facts:
        grouped.setdefault(_entity_instance(fact), []).append(dict(fact))
    return [grouped[key] for key in sorted(grouped)]


def _fact_value(fact: Optional[Mapping[str, Any]]) -> Any:
    if fact is None:
        return None
    if "value" in fact:
        return fact.get("value")
    encoded = fact.get("value_json")
    if isinstance(encoded, str):
        try:
            return json.loads(encoded)
        except json.JSONDecodeError:
            return encoded
    return None


def _source_evidence(fact: Optional[Mapping[str, Any]]) -> Optional[str]:
    if fact is None:
        return None
    encoded = fact.get("source_value_json")
    if isinstance(encoded, str):
        return encoded
    text = _evidence_text(fact)
    return json.dumps(text, ensure_ascii=False) if text else json.dumps(dict(fact), ensure_ascii=False, sort_keys=True, default=str)


def _event(
    event_type: str,
    product_key: Tuple[str, str, str],
    before: Optional[Mapping[str, Any]],
    after: Optional[Mapping[str, Any]],
    *,
    materiality: str,
    equivalence: str,
    reasons: Sequence[str],
) -> Dict[str, Any]:
    current = after or before or {}
    before_text, after_text = _evidence_text(before or {}), _evidence_text(after or {})
    before_signature = semantic_clause_signature(before_text) if before_text else None
    after_signature = semantic_clause_signature(after_text) if after_text else None
    changed_slots = [
        key for key in (before_signature or {})
        if after_signature is not None and before_signature[key] != after_signature[key]
    ]
    identity = "|".join((product_key[2].casefold(), product_key[0].casefold(), product_key[1]))
    payload = {
        "identity": identity,
        "product": _product_ref(product_key),
        "dataset": product_key[2],
        "provider": product_key[0],
        "product_id": product_key[1],
        "product_name": str(_first(current, _PRODUCT_NAMES) or ""),
        "event_type": event_type,
        "change_type": event_type,
        "kind": str(_first(current, ("kind", "fact_type", "factType", "category")) or ""),
        "canonical_key": str(_first(current, ("canonical_key", "canonicalKey", "fact_key", "factKey", "path")) or ""),
        "before": deepcopy(dict(before)) if before is not None else None,
        "after": deepcopy(dict(after)) if after is not None else None,
        "before_value_json": json.dumps(_fact_value(before), ensure_ascii=False, sort_keys=True, default=str),
        "after_value_json": json.dumps(_fact_value(after), ensure_ascii=False, sort_keys=True, default=str),
        "before_evidence_json": _source_evidence(before),
        "after_evidence_json": _source_evidence(after),
        "before_signature_json": json.dumps(before_signature, ensure_ascii=False, sort_keys=True) if before_signature else None,
        "after_signature_json": json.dumps(after_signature, ensure_ascii=False, sort_keys=True) if after_signature else None,
        "materiality": materiality,
        "equivalence": equivalence,
        "reasons": list(dict.fromkeys(reasons)),
        "review_required": materiality == "review" or equivalence == "unknown",
        # Compatibility booleans for tabular consumers.
        "cosmetic": materiality == "cosmetic",
        "material": materiality == "material",
        "slots_changed": bool(changed_slots),
    }
    event_material = {key: value for key, value in payload.items() if key != "event_id"}
    payload["event_id"] = hashlib.sha256(
        json.dumps(event_material, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:20]
    return payload


def _different(before: Mapping[str, Any], after: Mapping[str, Any], fields: Sequence[str]) -> List[str]:
    return [field for field in fields if before.get(field) != after.get(field)]


def _metadata(fact: Mapping[str, Any]) -> Dict[str, Any]:
    excluded = {
        *_PRODUCT_ALIASES["provider"], *_PRODUCT_ALIASES["product_id"], *_PRODUCT_ALIASES["dataset"],
        *_PRODUCT_NAMES, "fact_id", "factId", "id", "kind", "fact_type", "factType",
        "category", "canonical_key", "canonicalKey", "fact_key", "factKey", "path",
        "name", "label", "title", "source_value_json", "value_json", "qualifiers", "qualifiers_json",
        "source_path",
        *_TEXT_FIELDS, *_VALUE_FIELDS, *_RANGE_FIELDS, *_CADENCE_FIELDS,
    }
    metadata = {key: value for key, value in fact.items() if key not in excluded}
    qualifiers = {
        key: value for key, value in _qualifiers(fact).items()
        if key not in {"groupId", "parentId", "sourcePattern"}
    }
    if qualifiers:
        metadata["qualifiers"] = qualifiers
    return metadata


def _semantic_change_type(before: Mapping[str, Any], after: Mapping[str, Any]) -> Tuple[str, List[str]]:
    value_fields = _different(before, after, _VALUE_FIELDS)
    range_fields = _different(before, after, _RANGE_FIELDS)
    cadence_fields = _different(before, after, _CADENCE_FIELDS)
    canonical = str(_first(after, ("canonical_key", "canonicalKey")) or "").casefold()
    if range_fields or any(token in canonical for token in ("range.", "minimum", "maximum")) and value_fields:
        return "range_changed", [f"structured_range_changed:{field}" for field in range_fields or value_fields]
    if cadence_fields or any(token in canonical for token in ("frequency", "cadence", "period", "timing")) and value_fields:
        return "cadence_changed", [f"structured_cadence_changed:{field}" for field in cadence_fields or value_fields]
    if value_fields:
        return "value_changed", [f"structured_value_changed:{field}" for field in value_fields]
    return "", []


def _compare_fact(
    product_key: Tuple[str, str, str],
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    if before == after:
        return []
    events: List[Dict[str, Any]] = []
    before_text, after_text = _evidence_text(before), _evidence_text(after)
    before_signature = semantic_clause_signature(before_text)
    after_signature = semantic_clause_signature(after_text)
    changed_slots = [key for key in before_signature if before_signature[key] != after_signature[key]]
    slot_reasons = [f"semantic_slot_changed:{slot}" for slot in changed_slots]
    structured_type, structured_reasons = _semantic_change_type(before, after)
    if structured_type:
        events.append(_event(
            structured_type, product_key, before, after,
            materiality="material", equivalence="non_equivalent",
            reasons=[*structured_reasons, *slot_reasons],
        ))
    # Multiple structured groups in one caller-supplied fact remain observable.
    range_fields = _different(before, after, _RANGE_FIELDS)
    cadence_fields = _different(before, after, _CADENCE_FIELDS)
    value_fields = _different(before, after, _VALUE_FIELDS)
    if value_fields and structured_type != "value_changed":
        events.append(_event(
            "value_changed", product_key, before, after,
            materiality="material", equivalence="non_equivalent",
            reasons=[f"structured_value_changed:{field}" for field in value_fields] + slot_reasons,
        ))
    if range_fields and structured_type != "range_changed":
        events.append(_event(
            "range_changed", product_key, before, after,
            materiality="material", equivalence="non_equivalent",
            reasons=[f"structured_range_changed:{field}" for field in range_fields] + slot_reasons,
        ))
    if cadence_fields and structured_type != "cadence_changed":
        events.append(_event(
            "cadence_changed", product_key, before, after,
            materiality="material", equivalence="non_equivalent",
            reasons=[f"structured_cadence_changed:{field}" for field in cadence_fields] + slot_reasons,
        ))
    condition_slots = [slot for slot in changed_slots if slot not in {"thresholds", "cadence_timing"}]
    if "thresholds" in changed_slots and not any(event["event_type"] == "range_changed" for event in events):
        events.append(_event(
            "range_changed", product_key, before, after,
            materiality="material", equivalence="non_equivalent", reasons=["semantic_slot_changed:thresholds"],
        ))
    if "cadence_timing" in changed_slots and not any(event["event_type"] == "cadence_changed" for event in events):
        events.append(_event(
            "cadence_changed", product_key, before, after,
            materiality="material", equivalence="non_equivalent", reasons=["semantic_slot_changed:cadence_timing"],
        ))
    if condition_slots:
        events.append(_event(
            "condition_changed", product_key, before, after,
            materiality="material", equivalence="non_equivalent",
            reasons=[f"semantic_slot_changed:{slot}" for slot in condition_slots],
        ))
    if before_text != after_text:
        if _cosmetic_fold(before_text) == _cosmetic_fold(after_text) and not changed_slots:
            events.append(_event(
                "wording_changed", product_key, before, after,
                materiality="cosmetic", equivalence="equivalent",
                reasons=["only_whitespace_case_or_punctuation_changed"],
            ))
        elif not changed_slots:
            events.append(_event(
                "wording_changed", product_key, before, after,
                materiality="review", equivalence="unknown",
                reasons=["content_words_changed_with_same_semantic_slots"],
            ))
        elif not structured_type:
            events.append(_event(
                "wording_changed", product_key, before, after,
                materiality="material", equivalence="non_equivalent", reasons=slot_reasons,
            ))
    if _metadata(before) != _metadata(after):
        events.append(_event(
            "metadata_changed", product_key, before, after,
            materiality="review", equivalence="unknown", reasons=["non_semantic_metadata_changed"],
        ))
    return events


def _match_entity_stage(
    previous: Dict[int, List[Dict[str, Any]]],
    current: Dict[int, List[Dict[str, Any]]],
    *,
    exact: bool,
) -> Tuple[
    List[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]],
    List[Tuple[List[List[Dict[str, Any]]], List[List[Dict[str, Any]]]]],
]:
    """Match entities without deriving identity from mutable rates or fees."""
    old_buckets: Dict[str, List[int]] = {}
    new_buckets: Dict[str, List[int]] = {}
    for index, entity in previous.items():
        old_buckets.setdefault(_entity_descriptor(entity, exact=exact), []).append(index)
    for index, entity in current.items():
        new_buckets.setdefault(_entity_descriptor(entity, exact=exact), []).append(index)
    pairs: List[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]] = []
    ambiguities: List[Tuple[List[List[Dict[str, Any]]], List[List[Dict[str, Any]]]]] = []
    for descriptor in sorted(set(old_buckets) & set(new_buckets)):
        old_ids = old_buckets[descriptor]
        new_ids = new_buckets[descriptor]
        # Content-identical entities are safe to cancel, even when indistinguishable.
        old_content: Dict[str, List[int]] = {}
        new_content: Dict[str, List[int]] = {}
        for index in old_ids:
            old_content.setdefault(_content_fingerprint(previous[index]), []).append(index)
        for index in new_ids:
            new_content.setdefault(_content_fingerprint(current[index]), []).append(index)
        for content in sorted(set(old_content) & set(new_content)):
            while old_content[content] and new_content[content]:
                old_index = old_content[content].pop()
                new_index = new_content[content].pop()
                pairs.append((previous.pop(old_index), current.pop(new_index)))
        old_left = [index for index in old_ids if index in previous]
        new_left = [index for index in new_ids if index in current]
        if len(old_left) == len(new_left) == 1:
            pairs.append((previous.pop(old_left[0]), current.pop(new_left[0])))
        elif old_left and new_left:
            ambiguities.append(
                ([previous.pop(index) for index in old_left], [current.pop(index) for index in new_left])
            )
    return pairs, ambiguities


def _match_entities(
    previous_facts: Sequence[Mapping[str, Any]],
    current_facts: Sequence[Mapping[str, Any]],
) -> Tuple[
    List[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]],
    List[List[Dict[str, Any]]],
    List[List[Dict[str, Any]]],
    List[Tuple[List[List[Dict[str, Any]]], List[List[Dict[str, Any]]]]],
]:
    previous = {index: entity for index, entity in enumerate(_entities(previous_facts))}
    current = {index: entity for index, entity in enumerate(_entities(current_facts))}
    pairs: List[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]] = []
    ambiguities: List[Tuple[List[List[Dict[str, Any]]], List[List[Dict[str, Any]]]]] = []
    for exact in (True, False):
        matched, unclear = _match_entity_stage(previous, current, exact=exact)
        pairs.extend(matched)
        ambiguities.extend(unclear)
    return pairs, list(previous.values()), list(current.values()), ambiguities


def _candidate_evidence(
    product_key: Tuple[str, str, str],
    entities: Sequence[Sequence[Mapping[str, Any]]],
    canonical_key: str = "",
) -> Dict[str, Any]:
    first = next((fact for entity in entities for fact in entity), {})
    return {
        **_product_ref(product_key),
        "product_name": str(_first(first, _PRODUCT_NAMES) or ""),
        "canonical_key": canonical_key,
        "candidates": [[deepcopy(dict(fact)) for fact in entity] for entity in entities],
    }


def _diff_entity_facts(
    product_key: Tuple[str, str, str],
    previous: Sequence[Mapping[str, Any]],
    current: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    old: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    new: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for fact in previous:
        old.setdefault(_fact_key(fact), []).append(dict(fact))
    for fact in current:
        new.setdefault(_fact_key(fact), []).append(dict(fact))
    events: List[Dict[str, Any]] = []
    for key in sorted(set(old) | set(new)):
        before_rows, after_rows = old.get(key, []), new.get(key, [])
        # Remove semantically identical occurrences without looking at order or source indices.
        before_by_content: Dict[str, List[Dict[str, Any]]] = {}
        after_by_content: Dict[str, List[Dict[str, Any]]] = {}
        for fact in before_rows:
            before_by_content.setdefault(_content_fingerprint([fact]), []).append(fact)
        for fact in after_rows:
            after_by_content.setdefault(_content_fingerprint([fact]), []).append(fact)
        for content in sorted(set(before_by_content) & set(after_by_content)):
            count = min(len(before_by_content[content]), len(after_by_content[content]))
            del before_by_content[content][:count]
            del after_by_content[content][:count]
        before_left = [fact for content in sorted(before_by_content) for fact in before_by_content[content]]
        after_left = [fact for content in sorted(after_by_content) for fact in after_by_content[content]]
        if len(before_left) == len(after_left) == 1:
            events.extend(_compare_fact(product_key, before_left[0], after_left[0]))
        elif before_left and after_left:
            events.append(_event(
                "ambiguous_match", product_key,
                _candidate_evidence(product_key, [[fact] for fact in before_left], key[1]),
                _candidate_evidence(product_key, [[fact] for fact in after_left], key[1]),
                materiality="review", equivalence="unknown",
                reasons=["ambiguous_duplicate_facts", f"before_candidates:{len(before_left)}", f"after_candidates:{len(after_left)}"],
            ))
        else:
            for fact in before_left:
                events.append(_event(
                    "fact_removed", product_key, fact, None,
                    materiality="material", equivalence="non_equivalent", reasons=["stable_fact_key_removed"],
                ))
            for fact in after_left:
                events.append(_event(
                    "fact_added", product_key, None, fact,
                    materiality="material", equivalence="non_equivalent", reasons=["stable_fact_key_added"],
                ))
    return events


def diff_normalized_product_facts(
    previous_facts: Iterable[Mapping[str, Any]],
    current_facts: Iterable[Mapping[str, Any]],
    *,
    previous_run_date: Optional[str] = None,
    current_run_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Diff normalized facts by stable provider + product id + dataset."""
    previous, current = _index(previous_facts), _index(current_facts)
    events: List[Dict[str, Any]] = []
    for product_key in sorted(set(previous) | set(current), key=lambda key: (key[0].casefold(), key[1], key[2])):
        old_facts, new_facts = previous.get(product_key), current.get(product_key)
        representative = next(iter(new_facts or old_facts or []), {})
        if old_facts is None:
            events.append(_event(
                "product_added", product_key, None, representative,
                materiality="material", equivalence="non_equivalent", reasons=["stable_product_key_added"],
            ))
            for fact in sorted(new_facts or [], key=lambda row: (_fact_key(row), _content_fingerprint([row]))):
                events.append(_event(
                    "fact_added", product_key, None, fact,
                    materiality="material", equivalence="non_equivalent", reasons=["fact_added_to_new_product"],
                ))
            continue
        if new_facts is None:
            events.append(_event(
                "product_removed", product_key, representative, None,
                materiality="material", equivalence="non_equivalent", reasons=["stable_product_key_removed"],
            ))
            for fact in sorted(old_facts, key=lambda row: (_fact_key(row), _content_fingerprint([row]))):
                events.append(_event(
                    "fact_removed", product_key, fact, None,
                    materiality="material", equivalence="non_equivalent", reasons=["fact_removed_with_product"],
                ))
            continue
        old_name, new_name = _product_name(old_facts), _product_name(new_facts)
        if old_name != new_name:
            cosmetic = _cosmetic_fold(old_name) == _cosmetic_fold(new_name)
            before = {"product_name": old_name}
            after = {"product_name": new_name}
            events.append(_event(
                "product_renamed", product_key, before, after,
                materiality="cosmetic" if cosmetic else "review",
                equivalence="equivalent" if cosmetic else "unknown",
                reasons=["only_whitespace_case_or_punctuation_changed" if cosmetic else "product_name_content_changed"],
            ))
        pairs, removed_entities, added_entities, ambiguities = _match_entities(old_facts, new_facts)
        for before_entity, after_entity in pairs:
            events.extend(_diff_entity_facts(product_key, before_entity, after_entity))
        for before_entities, after_entities in ambiguities:
            events.append(_event(
                "ambiguous_match", product_key,
                _candidate_evidence(product_key, before_entities),
                _candidate_evidence(product_key, after_entities),
                materiality="review", equivalence="unknown",
                reasons=[
                    "ambiguous_semantic_entity_match",
                    f"before_candidates:{len(before_entities)}",
                    f"after_candidates:{len(after_entities)}",
                ],
            ))
        for entity in removed_entities:
            for fact in entity:
                events.append(_event(
                    "fact_removed", product_key, fact, None,
                    materiality="material", equivalence="non_equivalent", reasons=["semantic_entity_removed"],
                ))
        for entity in added_entities:
            for fact in entity:
                events.append(_event(
                    "fact_added", product_key, None, fact,
                    materiality="material", equivalence="non_equivalent", reasons=["semantic_entity_added"],
                ))
    events.sort(key=lambda event: (
        event["provider"].casefold(), event["product_id"], event["dataset"],
        _EVENT_ORDER[event["event_type"]], event["canonical_key"], event["event_id"],
    ))
    return {
        "schema_version": SCHEMA_VERSION,
        "normalization_version": NORMALIZATION_VERSION,
        "previous_run_date": previous_run_date,
        "run_date": current_run_date,
        "current_run_date": current_run_date,
        "products": {
            "previous": len(previous), "current": len(current), "joined": len(set(previous) & set(current)),
        },
        "change_count": len(events),
        "events": events,
        # Alias for pure consumers; rows are identical flat event records.
        "changes": events,
    }


build_product_changes = diff_normalized_product_facts


def _product_ref(key: Tuple[str, str, str]) -> Dict[str, str]:
    return {"provider": key[0], "product_id": key[1], "dataset": key[2]}


def _run_date(run_root: Path) -> str:
    return run_root.parent.name if run_root.name == "_exports" else run_root.name


def _export_file(run_root: Path) -> Optional[Path]:
    date = _run_date(run_root)
    export_root = run_root if run_root.name == "_exports" else run_root / "_exports"
    exact = export_root / f"banks-{date}.json"
    if exact.is_file():
        return exact
    candidates = sorted(export_root.glob("banks-*.json")) if export_root.is_dir() else []
    return candidates[0] if len(candidates) == 1 else None


def _load_run(run_root: Path) -> Dict[str, Dict[str, Any]]:
    exported = _export_file(run_root)
    if exported:
        payload = load_json(exported)
        facts = payload.get("product_facts") if isinstance(payload, Mapping) else None
        if not isinstance(facts, list):
            raise ValueError(f"finalized export has no normalized product_facts list: {exported}")
        products: Dict[str, Dict[str, Any]] = {}
        for supplied in facts:
            if not isinstance(supplied, Mapping):
                raise ValueError(f"finalized product fact is not an object: {exported}")
            key = _product_key(supplied)
            identity = "|".join((key[2].casefold(), key[0].casefold(), key[1]))
            products.setdefault(identity, {"base": {
                "provider": key[0], "product_id": key[1], "dataset": key[2],
                "product_name": str(_first(supplied, _PRODUCT_NAMES) or ""),
            }, "facts": []})["facts"].append(dict(supplied))
        return products
    banks_root = run_root / "banks"
    products = {}
    for path in sorted(banks_root.rglob("product-detail.json")):
        record = inner_record(load_json(path))
        base = bank_base_row(path, banks_root, record)
        identity = "|".join((base["dataset"].casefold(), base["provider"].casefold(), base["product_id"]))
        products[identity] = {"base": base, "record": record, "facts": extract_product_facts(record, identity)}
    return products


def _enriched_facts(products: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    output = []
    for identity in sorted(products):
        product = products[identity]
        base = product["base"]
        for fact in product["facts"]:
            if _first(fact, _PRODUCT_ALIASES["provider"]):
                output.append(dict(fact))
                continue
            output.append({
                "provider": base["provider"], "product_id": base["product_id"],
                "dataset": base["dataset"], "product_name": base["product_name"], **fact,
            })
    return output


def compare_runs(previous_root: Path, current_root: Path) -> Dict[str, Any]:
    """Load two finalized roots and return the integration report with flat events."""
    previous, current = _load_run(previous_root), _load_run(current_root)
    return diff_normalized_product_facts(
        _enriched_facts(previous), _enriched_facts(current),
        previous_run_date=_run_date(previous_root), current_run_date=_run_date(current_root),
    )


def previous_finalized_run(current_root: Path) -> Optional[Path]:
    current = current_root.parent if current_root.name == "_exports" else current_root
    runs = current.parent
    candidates = [
        path for path in runs.iterdir()
        if path.is_dir() and path.name < current.name and _export_file(path) is not None
    ]
    return max(candidates, key=lambda path: path.name) if candidates else None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Compare normalized facts from finalized Banking CDR runs.")
    parser.add_argument("current", type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    current = args.current.resolve()
    previous = args.previous.resolve() if args.previous else previous_finalized_run(current)
    report = compare_runs(previous, current) if previous else {
        "schema_version": SCHEMA_VERSION, "normalization_version": NORMALIZATION_VERSION,
        "previous_run_date": None, "run_date": current.name, "current_run_date": current.name,
        "products": {"previous": 0, "current": 0, "joined": 0},
        "change_count": 0, "events": [], "changes": [],
    }
    rendered = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
