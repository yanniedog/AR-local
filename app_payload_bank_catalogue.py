"""Complete historical tier catalogue with observation-scoped filter evidence."""
from __future__ import annotations

import json
import math
import re

from app_payload_bank_rates import OBSERVATION_FIELDS, rate_percent
from app_payload_common import VALID_SECTIONS
from app_payload_details import _detail_items
from app_payload_feature_facts import feature_facts

IDENTITY_FIELDS = ("provider", "product_id", "product_key", "category", "dataset")
UNKNOWN = {"status": "unknown"}
MAX_TEXT = 65536


def _scalar(value, *, boolean=True):
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= MAX_TEXT
            or type(value) is bool and boolean
            or type(value) in (int, float) and math.isfinite(value))


def _valid_fact(fact):
    if not all(isinstance(fact.get(key), str) and fact[key].strip() for key in ("id", "canonicalKey", "kind")):
        return False
    for key, value in fact.items():
        if isinstance(value, str):
            if len(value) > MAX_TEXT or key in ("id", "canonicalKey", "groupId", "parentId", "label") and not value.strip():
                return False
        elif isinstance(value, list):
            if len(value) > 128 or any(not isinstance(item, str) or len(item) > MAX_TEXT for item in value):
                return False
        elif not _scalar(value):
            return False
    if any(key in fact and not isinstance(fact[key], str) for key in ("groupId", "parentId", "label", "cadence", "condition", "sourceType")):
        return False
    if any(key in fact and not isinstance(fact[key], list) for key in ("appliesTo", "searchTerms")):
        return False
    if any(key in fact and not _scalar(fact[key], boolean=key == "value") for key in ("value", "minValue", "maxValue")):
        return False
    unit = fact.get("unit")
    return unit is None or isinstance(unit, str) and (unit in {"AUD", "fraction", "duration", "day", "month", "year", "count", "boolean", "text", "enum"} or re.fullmatch("[A-Z]{3}", unit))


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def identity(row, section=None):
    value = {field: section if field == "dataset" and section else row.get(field)
             for field in IDENTITY_FIELDS}
    return value if all(isinstance(item, str) and item.strip() for item in value.values()) else None


def detail_projection(detail):
    """Keep relevant negative/conditional facts as well as positive declarations."""
    if not isinstance(detail, dict):
        return None
    result = {}
    if "description" in detail:
        if not isinstance(detail["description"], str) or len(detail["description"]) > MAX_TEXT:
            return None
        if detail["description"].strip():
            result["description"] = detail["description"]
    for field in ("eligibility", "constraints", "facts"):
        if field not in detail:
            continue
        items = detail[field]
        if not isinstance(items, list) or len(items) > 4096 or any(not isinstance(item, dict) for item in items):
            return None
        if field == "facts":
            if any(not _valid_fact(item) for item in items):
                return None
        elif any(key not in {"label", "name", "info", "value"}
                 or not (isinstance(value, str) and len(value) <= MAX_TEXT
                         or key == "value" and type(value) in (int, float) and math.isfinite(value))
                 for item in items for key, value in item.items()):
            return None
        result[field] = [dict(item) for item in items if field != "facts" or item.get("kind") == "feature"]
    return result if any(result.values()) else None


def published_evidence(row, section, details):
    bound = identity(row, section)
    source = details.get(row.get("product_key")) if isinstance(details, dict) else None
    if isinstance(source, dict) and "displayIdentity" in source:
        display = source["displayIdentity"]
        if not isinstance(display, dict):
            return UNKNOWN
        for key, field in (("name", "product_name"), ("provider", "provider"), ("productCategory", "category")):
            if key in display and (not isinstance(display[key], str)
                    or " ".join(display[key].split()).casefold() != " ".join(str(row.get(field, "")).split()).casefold()):
                return UNKNOWN
    detail = detail_projection(source)
    if bound is None or detail is None:
        return UNKNOWN
    return {"status": "known", "identity": bound, "detail": detail}


def retained_evidence(products):
    """Conflicting copies cannot donate another product's eligibility evidence."""
    groups = {}
    if not isinstance(products, list):
        return {}
    for product in products:
        if isinstance(product, dict) and product.get("product_key"):
            groups.setdefault(product["product_key"], []).append(product)
    result = {}
    for key, group in groups.items():
        candidates = []
        for product in group:
            bound = identity(product)
            raw = product.get("details_json")
            try:
                record = json.loads(raw) if isinstance(raw, str) else raw
            except (ValueError, TypeError):
                record = None
            if (bound is None or not isinstance(record, dict)
                    or record.get("productId") != bound["product_id"]
                    or any(field in record and (not isinstance(record[field], list)
                           or any(not isinstance(item, dict) for item in record[field]))
                           for field in ("features", "eligibility", "constraints"))):
                candidates.append(UNKNOWN)
                continue
            description = product.get("description") or record.get("description")
            detail = detail_projection({
                **({"description": description} if description is not None else {}),
                "eligibility": _detail_items(record, "eligibility", "eligibilityType"),
                "constraints": _detail_items(record, "constraints", "constraintType"),
                "facts": feature_facts(record, key, product.get("description")),
            })
            candidates.append({"status": "known", "identity": bound, "detail": detail}
                              if detail is not None else UNKNOWN)
        if len({canonical(item) for item in candidates}) == 1:
            result[key] = candidates[0]
    return result


class HistoricalCatalogue:
    def __init__(self, dates):
        self.dates = list(dates)
        self.index = {day: index for index, day in enumerate(dates)}
        if not dates or len(self.index) != len(dates) or len(dates) > 5000:
            raise ValueError("Invalid historical catalogue date axis")
        self.sections = {section: [] for section in VALID_SECTIONS}
        self.tiers = {section: {} for section in VALID_SECTIONS}
        self.evidence = [UNKNOWN]
        self.evidence_ids = {canonical(UNKNOWN): 0}
        self.sources, self.unavailable, self.seen = {}, {}, set()

    def observe(self, day, sections, evidence_for_row, source=None):
        if day not in self.index or day in self.seen:
            raise ValueError("Unknown or duplicate historical catalogue date")
        self.seen.add(day)
        position = self.index[day]
        daily_evidence = {}
        if source is not None:
            self.sources[day] = source
        for section in VALID_SECTIONS:
            buckets = {}
            for row in sections.get(section, []):
                value = rate_percent(row.get("rate"))
                if value is None:
                    continue
                descriptor = {key: item for key, item in row.items() if key not in OBSERVATION_FIELDS}
                key = canonical(descriptor)
                if key not in self.tiers[section]:
                    self.tiers[section][key] = len(self.sections[section])
                    self.sections[section].append({"row": descriptor, "spans": []})
                tier = self.tiers[section][key]
                product = (section, *(row.get(field) for field in IDENTITY_FIELDS[:-1]), row.get("product_name"))
                if product not in daily_evidence:
                    evidence = evidence_for_row(row, section)
                    if evidence.get("status") == "known" and evidence.get("identity") != identity(row, section):
                        evidence = UNKNOWN
                    evidence_key = canonical(evidence)
                    if evidence_key not in self.evidence_ids:
                        self.evidence_ids[evidence_key] = len(self.evidence)
                        self.evidence.append(evidence)
                    daily_evidence[product] = self.evidence_ids[evidence_key]
                evidence_id = daily_evidence[product]
                buckets.setdefault((tier, evidence_id), []).append(value)
            for (tier, evidence_id), values in sorted(buckets.items()):
                values.sort()
                spans = self.sections[section][tier]["spans"]
                if spans and spans[-1][0] + spans[-1][1] == position and spans[-1][2:] == [values, evidence_id]:
                    spans[-1][1] += 1
                else:
                    spans.append([position, 1, values, evidence_id])

    def finish(self, unavailable=None):
        return {"schema_version": 2, "run_dates": self.dates,
                "sources": self.sources, "unavailable_dates": dict(unavailable or {}),
                "evidence": self.evidence, "sections": self.sections}
