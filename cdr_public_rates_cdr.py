"""Compile retained public CDR records into deterministic pricing programmes.

CDR adjustment types retain their adjustment roles. A source convention which
uses those types for net rates needs a separately reviewed provider adapter.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import urlparse

from cdr_domain.identity import product_uid, provider_uid, rate_semantics
from cdr_domain.public_pricing import canonical_bytes, decimal_value, semantic_id
from cdr_domain.public_pricing_validation import validate_programme, validate_wire
from cdr_domain.rates import decimal_text
from cdr_public_rates_conditions import (
    applicability_conditions, condition, duration_months, product_constraints,
    structured_rate_conditions, tier_bounds,
)
from cdr_public_rates_fees import compile_fees
from cdr_public_rates_metadata import rate_metadata

ADAPTER_VERSION = "structured-cdr-public-pricing-v1"
LENDING_ROLES = {"VARIABLE": "payable", "FIXED": "payable", "DISCOUNT": "discount",
                 "BUNDLE_DISCOUNT_FIXED": "discount", "BUNDLE_DISCOUNT_VARIABLE": "discount",
                 "INTRODUCTORY": "discount"}
DEPOSIT_ROLES = {"FIXED": "payable", "VARIABLE": "payable", "BASE": "reference",
                 "BONUS": "bonus", "BUNDLE_BONUS": "bonus", "INTRODUCTORY": "bonus"}


def capture_pricing_source(source: bytes, *, source_url: str = "", checked_at: str = "", provider_id: str = "") -> str:
    envelope = json.loads(source)
    record = envelope.get("data", envelope)
    if not isinstance(record, Mapping):
        raise ValueError("public CDR product must be an object")
    fields = ("productId", "name", "brand", "brandName", "productCategory", "effectiveFrom", "effectiveTo", "isTailored",
              "lastUpdated", "lendingRates", "depositRates", "constraints", "eligibility", "fees")
    capture = {"schemaVersion": 1, "sourceSha256": hashlib.sha256(source).hexdigest(),
               "sourceUrl": source_url, "checkedAt": checked_at,
               "providerId": provider_id,
               "pointer": "/data" if "data" in envelope else "",
               "record": {field: record[field] for field in fields if field in record}}
    return canonical_bytes(capture).decode("utf-8")


def _evidence(capture, pointer, checked_at):
    result = {"evidenceId": semantic_id("evidence", [capture["sourceSha256"], pointer]),
              "url": capture["sourceUrl"], "sha256": capture["sourceSha256"], "locator": pointer,
              "extractionVersion": ADAPTER_VERSION}
    if checked_at:
        result["checkedAt"] = checked_at
    return result


def _price_kind(rate):
    text = str(rate.get("additionalInfo", "")).casefold()
    if "rate displayed is the minimum advertised rate" in text or "rate displayed is the minimum rate" in text:
        return "minimum"
    if "rate displayed is the maximum rate" in text:
        return "maximum"
    return "exact"


def _offer_semantics(rate, family):
    result = rate_semantics(rate, family)
    if _price_kind(rate) in {"minimum", "maximum"}:
        # Exact recognized range disclosures differ only in endpoint prose.
        # All purpose/repayment/tier/applicability semantics remain in identity.
        result["additional_info"] = "published-assessed-rate-range"
    return result


def _component(rate, role, offer_id, pointer, evidence_id, identity):
    result = {"componentId": semantic_id("component", [offer_id, role, identity]), "role": role,
              "unit": "fraction_per_annum", "scopeId": offer_id, "conditions": [],
              "evidenceIds": [evidence_id], "source": {"rawType": str(rate.get("lendingRateType") or rate.get("depositRateType") or ""),
                                                        "pointer": pointer}}
    if rate.get("rate") is not None:
        result["source"]["rawValue"] = str(rate["rate"])
        try:
            if not isinstance(rate['rate'], str):
                raise ValueError('CDR rate scalars require a reviewed provider adapter')
            value = decimal_text(rate["rate"])
            if abs(decimal_value(value)) > 1:
                raise ValueError('CDR fraction units require a reviewed provider adapter')
            result["value"] = value
        except (ValueError, TypeError):
            pass
    return result


def _uninterpreted_material_pricing(rate):
    text = str(rate.get('additionalInfo') or '').casefold()
    patterns = (
        r'\b(?:minimum|maximum|lowest)\s+(?:advertised\s+|interest\s+)?rate\b',
        r'\b(?:interest\s+)?rates?\s+(?:start\s+)?from\b',
        r'\b(?:reference|indicator|index)\s+(?:interest\s+)?rate\b',
        r'\b(?:before|excluding|less|minus)\s+(?:any\s+|applicable\s+)?discount',
        r'\b(?:plus|minus)\s+(?:any\s+|applicable\s+)?margin',
        r'\b(?:discretion|assessment|negotiated|personalised|personalized|case[- ]by[- ]case)\b',
        r'\brate\b.{0,80}\bdepend(?:s)?\b',
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _tier_formula(rate, section, component, evidence_id):
    direct = {"op": "component", "componentId": component["componentId"]}
    raw_tiers = rate.get("tiers")
    if not raw_tiers:
        return direct, []
    grouped, extra = defaultdict(list), []
    for raw in raw_tiers:
        if not isinstance(raw, Mapping):
            raise ValueError("malformed_tier")
        field, method, bounds = tier_bounds(raw, section)
        if field in {"termMonths", "termDays"}:
            extra.append(condition(field, "bounds", evidence_id, **bounds))
        else:
            grouped[(field, method)].append(bounds)
        applicability = raw.get("applicabilityConditions")
        if field in {"termMonths", "termDays"} and isinstance(applicability, list):
            applicability = [item for item in applicability if not (
                isinstance(item, Mapping) and item.get("rateApplicabilityType") == "OTHER"
                and re.fullmatch(r"[0-9\s.\-<]+(?:days?|months?|years?)(?:\s*-\s*<?\s*[0-9]+\s*(?:days?|months?|years?))?",
                                 str(item.get("additionalInfo", "")).strip(), flags=re.IGNORECASE))]
        extra.extend(applicability_conditions(applicability, evidence_id))
    formula = direct
    if len({field for field, _ in grouped}) != len(grouped):
        raise ValueError("mixed_tier_application_methods")
    for (field, method), bounds in sorted(grouped.items()):
        formula = {"op": "tiered", "field": field, "method": method,
                   "tiers": [{**tier, "formula": formula} for tier in bounds]}
    return formula, extra


def _rate_group(record, capture, product, section, rates, indices, semantics, checked_at, legacy_ordinals):
    family = "lending" if section == "Mortgage" else "deposit"
    source_key = "lendingRates" if family == "lending" else "depositRates"
    offer_id = semantic_id("offer", [product["productId"], semantics])
    programme = {"schemaVersion": 1, "programmeId": semantic_id("programme", [offer_id, ADAPTER_VERSION]),
                 "productId": product["productId"], "section": section, "offerId": offer_id,
                 "conditions": [], "components": [], "evidenceIds": [], "reasonCodes": [], "sourceBindings": [],
                 "freshness": {"state": "current" if checked_at and capture["sourceUrl"] else "unknown",
                               "reasonCodes": []}}
    programme['metadata'] = rate_metadata(rates[0])
    if checked_at:
        programme["freshness"].update(checkedAt=checked_at, lastSuccessAt=checked_at)
    for field, source in (("effectiveFrom", "effectiveFrom"), ("effectiveTo", "effectiveTo")):
        if record.get(source):
            programme[field] = record[source]
    evidence, endpoint_formulas = [], {}
    constraint_evidence = _evidence(capture, capture['pointer'] + '/constraints', checked_at)
    evidence.append(constraint_evidence)
    programme['conditions'].extend(product_constraints(record, section, constraint_evidence['evidenceId']))
    programme['evidenceIds'].append(constraint_evidence['evidenceId'])
    for rate, index in zip(rates, indices):
        pointer = f"{capture['pointer']}/{source_key}/{index}"
        ref = _evidence(capture, pointer, checked_at)
        evidence.append(ref)
        eid = ref["evidenceId"]
        kind = str(rate.get("lendingRateType") or rate.get("depositRateType") or "")
        role = (LENDING_ROLES if family == "lending" else DEPOSIT_ROLES).get(kind)
        programme["sourceBindings"].append({"pointer": pointer, "rateIndex": legacy_ordinals[index]})
        programme["evidenceIds"].append(eid)
        if role is None:
            programme["reasonCodes"].append("unsupported_cdr_rate_type")
            continue
        endpoint = _price_kind(rate)
        component = _component(rate, role, offer_id, pointer, eid, endpoint)
        programme["components"].append(component)
        if not isinstance(rate.get('rate'), str):
            programme['reasonCodes'].append('non_string_cdr_rate')
        elif 'value' not in component:
            try:
                amount = decimal_value(decimal_text(rate['rate']))
                reason = 'nonconforming_cdr_rate_unit' if abs(amount) > 1 else 'invalid_cdr_rate_value'
            except (ValueError, TypeError):
                reason = 'invalid_cdr_rate_value'
            programme['reasonCodes'].append(reason)
        if endpoint == 'exact' and role in {'payable', 'reference'} and _uninterpreted_material_pricing(rate):
            programme['reasonCodes'].append('uninterpreted_material_pricing')
        conditions = structured_rate_conditions(rate, section, eid)
        if endpoint in {"minimum", "maximum"}:
            conditions = [c for c in conditions if c.get('description', '').casefold() not in
                          {'based on customer relationship', 'customer relationship'}]
            conditions.append(condition("customerCategory", "known", eid, description="Public range subject to lender assessment"))
            programme["reasonCodes"].append("lender_assessment_required")
        elif any(c.get('description', '').casefold() in {'based on customer relationship', 'customer relationship'} for c in conditions):
            programme['reasonCodes'].append('uninterpreted_material_condition')
        programme["conditions"].extend(conditions)
        if role in {"discount", "bonus"}:
            programme["reasonCodes"].append("adjustment_base_unbound")
            continue
        try:
            formula, tier_conditions = _tier_formula(rate, section, component, eid)
            programme["conditions"].extend(tier_conditions)
            if endpoint in endpoint_formulas:
                programme["reasonCodes"].append("conflicting_source_rates")
            endpoint_formulas[endpoint] = formula
            if rate.get("comparisonRate") not in (None, ""):
                comparison = _component({**rate, "rate": rate["comparisonRate"]}, "comparison", offer_id,
                                        pointer + "/comparisonRate", eid, endpoint)
                programme["components"].append(comparison)
        except (ValueError, TypeError):
            programme["reasonCodes"].append("unsupported_cdr_tiers")
    if not set(programme["reasonCodes"]) & {"unsupported_cdr_rate_type", "conflicting_source_rates", "unsupported_cdr_tiers", "adjustment_base_unbound", "uninterpreted_material_condition", "uninterpreted_material_pricing", "non_string_cdr_rate", "nonconforming_cdr_rate_unit", "invalid_cdr_rate_value"}:
        if set(endpoint_formulas) == {"minimum", "maximum"}:
            programme["formula"] = {"op": "range", "minimum": endpoint_formulas["minimum"], "maximum": endpoint_formulas["maximum"]}
        elif set(endpoint_formulas) == {"minimum"}:
            programme["formula"] = {"op": "from", "formula": endpoint_formulas["minimum"]}
        elif set(endpoint_formulas) == {"exact"}:
            programme["formula"] = endpoint_formulas["exact"]
        else:
            programme["reasonCodes"].append("pricing_relationship_unavailable")
    programme["conditions"] = list({c["conditionId"]: c for c in programme["conditions"]}.values())
    duplicates = defaultdict(list)
    for component in programme['components']:
        duplicates[component['componentId']].append(component)
    programme['components'] = [group[0] for group in duplicates.values()]
    if any(len(group) > 1 for group in duplicates.values()):
        programme['reasonCodes'].append('conflicting_source_rates')
        programme.pop('formula', None)
    if record.get('isTailored') is True and programme.get('formula', {}).get('op') not in {'from', 'range'}:
        programme.pop('formula', None)
        programme['reasonCodes'].append('tailored_pricing_scope_unavailable')
    programme["reasonCodes"] = sorted(set(programme["reasonCodes"]))
    metadata = programme['metadata']
    if (programme.get('formula') and section == 'Mortgage' and metadata.get('rateStructure') == 'fixed'
            and metadata.get('quotedTerm', {}).get('unit') == 'month'):
        programme['phases'] = [{'phaseId': 'fixed', 'startMonth': 0, 'endMonth': int(metadata['quotedTerm']['value']),
                               'formula': programme['formula'], 'conditions': [], 'evidenceIds': programme['evidenceIds']}]
    if capture["sourceUrl"]:
        validate_programme(programme)
        for item in evidence:
            validate_wire(item, "Evidence")
    return programme, evidence


def compile_record(record: Mapping[str, Any], *, provider_name: str, section: str,
                   source_url: str, source_sha256: str, checked_at: str = "",
                   product_key: str = "", pointer: str = "/data",
                   register_holder_id: str | None = None, register_brand_id: str | None = None,
                   provider_id: str | None = None) -> dict:
    if section not in {"Mortgage", "Savings", "TD"}:
        raise ValueError("unsupported_public_rate_section")
    provider, _ = provider_uid(register_holder_id=register_holder_id, register_brand_id=register_brand_id,
                               authority=urlparse(source_url).hostname or "public-cdr-unknown", display_name=provider_name)
    provider = provider_id or provider
    pid = product_uid(provider, str(record.get("productId") or product_key))
    product = {"productId": pid, "productKey": product_key, "providerId": provider, "providerName": provider_name,
               "name": str(record.get("name") or record.get("productId") or product_key), "section": section,
               "aliases": [], "status": "unknown", "programmeIds": [], "referenceIds": [], "reasonCodes": []}
    capture = {"sourceUrl": source_url, "sourceSha256": source_sha256, "pointer": pointer}
    product['freshness'] = {'state': 'current' if source_url and checked_at else 'unknown', 'reasonCodes': []}
    if checked_at:
        product['freshness'].update(checkedAt=checked_at, lastSuccessAt=checked_at)
    if source_url:
        product['sourceEvidence'] = _evidence(capture, pointer, checked_at)
    rates_key = "lendingRates" if section == "Mortgage" else "depositRates"
    family = "lending" if section == "Mortgage" else "deposit"
    groups = defaultdict(lambda: ([], [], {}))
    legacy_ordinals = {}
    for index, rate in enumerate(record.get(rates_key) or []):
        if isinstance(rate, Mapping):
            legacy_ordinals[index] = len(legacy_ordinals) + 1
            semantics = _offer_semantics(rate, family)
            group = groups[canonical_bytes(semantics)]
            group[0].append(rate)
            group[1].append(index)
            group[2].update(semantics)
    programmes, evidence = [], []
    for rates, indices, semantics in groups.values():
        programme, refs = _rate_group(record, capture, product, section, rates, indices, semantics, checked_at, legacy_ordinals)
        programmes.append(programme)
        evidence.extend(refs)
    _bind_structured_adjustments(programmes, record, section)
    for programme in programmes:
        fees, fee_coverage, fee_evidence = compile_fees(
            record, product_id=pid, offer_id=programme["offerId"], source_sha256=source_sha256,
            source_url=source_url, pointer=pointer, checked_at=checked_at,
        )
        programme["fees"] = fees
        programme["feeCoverage"] = fee_coverage
        evidence.extend(fee_evidence)
    product["programmeIds"] = sorted(programme["programmeId"] for programme in programmes)
    if not programmes:
        product["reasonCodes"].append("no_public_rates_disclosed")
    if not source_url:
        product["reasonCodes"].append("original_source_url_unavailable")
        evidence = []
        for programme in programmes:
            programme.pop("formula", None)
            programme.pop("phases", None)
            programme["reasonCodes"] = sorted(set(programme["reasonCodes"] + ["original_source_url_unavailable"]))
            programme["evidenceIds"] = []
            programme["feeCoverage"] = {"status": "unknown", "reasonCodes": ["original_source_url_unavailable"], "evidenceIds": []}
            for item in [*programme["components"], *programme.get("fees", []), *programme["conditions"]]:
                item["evidenceIds"] = []
    product['reasonCodes'] = sorted(set(product['reasonCodes'])
                                   | {reason for programme in programmes for reason in programme['reasonCodes']})
    validate_wire(product, "Product")
    return {"product": product, "programmes": sorted(programmes, key=lambda p: p["programmeId"]),
            "evidence": sorted({item["evidenceId"]: item for item in evidence}.values(), key=lambda e: e["evidenceId"])}


def _bind_structured_adjustments(programmes, record, section):
    """CDR base/adjustment joins require one identical structured offer scope.

    Each adjustment is a separate alternative programme. Two adjustment rows
    are never summed, and unbound/mutually ambiguous bases remain unresolved.
    """
    for programme in programmes:
        if set(programme['reasonCodes']) & {'non_string_cdr_rate', 'nonconforming_cdr_rate_unit', 'invalid_cdr_rate_value',
                                          'uninterpreted_material_condition', 'uninterpreted_material_pricing',
                                          'unsupported_cdr_rate_type', 'conflicting_source_rates', 'unsupported_cdr_tiers'}:
            continue
        adjustments = [c for c in programme["components"] if c["role"] in {"discount", "bonus"}]
        if len(adjustments) != 1:
            continue
        adjustment = adjustments[0]
        raw = _source_rate(record, section, programme)
        if raw is None:
            continue
        candidates = [other for other in programmes if other is not programme and other.get("formula")
                      and _compatible_base(_source_rate(record, section, other), raw, section)]
        if len(candidates) != 1:
            continue
        base = candidates[0]
        # Uninterpreted custom/material predicates cannot silently migrate.
        if any(c["field"] in {"custom", "qualification"} for c in base["conditions"]):
            continue
        components = [{**c, "scopeId": programme["offerId"],
                       "componentId": semantic_id("component", [programme["offerId"], c["componentId"]])}
                      for c in base["components"]]
        for component in components:
            if component["role"] == "payable":
                component["role"] = "reference"
        mapping = {old["componentId"]: new["componentId"] for old, new in zip(base["components"], components)}
        base_formula = _replace_component_ids(base["formula"], mapping)
        try:
            adjustment_formula, tier_conditions = _tier_formula(raw, section, adjustment, adjustment["evidenceIds"][0])
        except (TypeError, ValueError):
            continue
        programme["components"] = components + programme["components"]
        programme["conditions"] = list({c["conditionId"]: c for c in base["conditions"] + programme["conditions"] + tier_conditions}.values())
        programme["evidenceIds"] = sorted(set(base["evidenceIds"] + programme["evidenceIds"]))
        programme["formula"] = {"op": "subtract" if section == "Mortgage" else "add",
                                "operands": [base_formula, adjustment_formula]}
        programme["reasonCodes"] = [reason for reason in programme["reasonCodes"] if reason != "adjustment_base_unbound"]
        if str(raw.get("lendingRateType") or raw.get("depositRateType")) == "INTRODUCTORY":
            months = duration_months(raw.get("additionalValue"))
            if not months:
                programme.pop("formula", None)
                programme["reasonCodes"].append("introductory_duration_unavailable")
            else:
                programme["phases"] = [
                    {"phaseId": "introductory", "startMonth": 0, "endMonth": int(months),
                     "formula": programme["formula"], "conditions": [], "evidenceIds": programme["evidenceIds"]},
                    {"phaseId": "ongoing", "startMonth": int(months), "formula": base_formula,
                     "conditions": [], "evidenceIds": base["evidenceIds"]}]
        validate_programme(programme)


def _source_rate(record, section, programme):
    bindings = programme["sourceBindings"]
    if len(bindings) != 1:
        return None
    rows = record.get("lendingRates" if section == "Mortgage" else "depositRates", [])
    index = int(bindings[0]['pointer'].rsplit('/', 1)[1])
    return rows[index] if index < len(rows) and isinstance(rows[index], Mapping) else None


def _compatible_base(base, adjustment, section):
    if base is None:
        return False
    field = "lendingRateType" if section == "Mortgage" else "depositRateType"
    kind = str(adjustment.get(field, ""))
    expected = "FIXED" if kind == "BUNDLE_DISCOUNT_FIXED" else "VARIABLE" if section == "Mortgage" else "BASE"
    explicit_variable_base = section != "Mortgage" and base.get(field) == "VARIABLE" and (
        "base rate" in str(base.get("additionalInfo", "")).casefold()
        or "in addition to the current variable base interest" in str(adjustment.get("additionalInfo", "")).casefold())
    if base.get(field) != expected and not explicit_variable_base:
        return False
    keys = ("loanPurpose", "repaymentType", "applicationFrequency", "calculationFrequency")
    if any(base.get(key) != adjustment.get(key) for key in keys):
        return False
    if base.get("tiers") and base.get("tiers") != adjustment.get("tiers"):
        return False
    if section == "Mortgage" and kind == "BUNDLE_DISCOUNT_FIXED":
        # The bundle name and fixed duration are distinct CDR additionalValue
        # roles; a public relationship adapter must bind them explicitly.
        return False
    return True


def _replace_component_ids(value, mapping):
    if isinstance(value, list):
        return [_replace_component_ids(child, mapping) for child in value]
    if isinstance(value, dict):
        return {key: mapping.get(child, child) if key == "componentId" else _replace_component_ids(child, mapping)
                for key, child in value.items()}
    return value


def compile_export_products(products: list[dict], *, checked_at: str = "") -> dict:
    compiled = {"products": [], "programmes": [], "evidence": []}
    for row in products:
        section = row.get("dataset")
        if section not in {"Mortgage", "Savings", "TD"}:
            continue
        capture = json.loads(row.get("public_pricing_source_json") or "{}")
        record = capture.get("record")
        if not isinstance(record, Mapping):
            record = json.loads(row.get("details_json") or "{}")
        if not isinstance(record, Mapping):
            record = {}
        record = {"productId": row.get("product_id"), "name": row.get("product_name"), **record}
        result = compile_record(record, provider_name=str(row.get("provider") or "Unknown provider"), section=section,
                                source_url=str(capture.get("sourceUrl") or ""),
                                source_sha256=str(capture.get("sourceSha256") or hashlib.sha256(canonical_bytes(record)).hexdigest()),
                                checked_at=str(capture.get("checkedAt") or checked_at),
                                product_key=str(row.get("product_key") or ""), pointer=str(capture.get("pointer", "/data")),
                                provider_id=capture.get("providerId") or None)
        compiled["products"].append(result["product"])
        compiled["programmes"].extend(result["programmes"])
        compiled["evidence"].extend(result["evidence"])
    return compiled


def inventory_from_compiled(compiled: Mapping[str, Any], holder_names: list[str] | None = None) -> list[dict]:
    """Every observed/registered provider remains visible in all three categories."""
    providers = {product["providerName"]: product["providerId"] for product in compiled.get("products", [])}
    for name in holder_names or []:
        providers.setdefault(name, provider_uid(register_holder_id=None, authority="public-cdr-unknown", display_name=name)[0])
    groups = defaultdict(list)
    for product in compiled.get("products", []):
        groups[(product["providerId"], product["section"])].append(product)
    programmes = {p["programmeId"]: p for p in compiled.get("programmes", [])}
    result = []
    for name, identity in sorted(providers.items()):
        for section in ("Mortgage", "Savings", "TD"):
            products = groups[(identity, section)]
            formulas = sum(bool(programmes[p].get("formula")) for product in products for p in product["programmeIds"])
            result.append({"providerId": identity, "providerName": name, "section": section,
                           "sourceStatus": "observed" if products else "unavailable",
                           "resolutionStatus": "candidate" if formulas else "unresolved",
                           "publicationStatus": "candidate", "products": len(products),
                           "programmesWithFormula": formulas,
                           "reasonCodes": [] if products else ["no_category_products_observed"]})
    return result
