"""Source-to-consumer accounting without inventing or changing rate evidence."""
from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal, InvalidOperation
from collections import Counter, defaultdict
from typing import Any, Mapping

from app_payload_common import section_filter
from cdr_product_classification import category_excludes_section

SECTIONS = ("Mortgage", "Savings", "TD")
ACCOUNTING_VERSION = 1
RATE_FIELDS = ("provider", "product_id", "product_key", "product_name", "category", "rate", "comparison_rate",
               "rate_type", "repayment_type", "loan_purpose", "term", "term_months", "lvr_tier", "taxonomy_path", "rate_index")
# Transport routing is absent from compact app rows, but must be compared
# before trusting an export to determine which SQLite rates reach each section.
SQLITE_RATE_FIELDS = tuple(key for key in RATE_FIELDS if key not in {"category", "rate_index"}) + (
    "dataset", "rate_family", "application_type",
)


def rate_rows_digest(rows: list[dict], *, sqlite_fields: bool = False) -> str:
    normalized = []
    fields = SQLITE_RATE_FIELDS if sqlite_fields else RATE_FIELDS
    for row in rows:
        values = {key: str(row.get(key) if row.get(key) is not None else "") for key in fields}
        for key in ("rate", "comparison_rate", "term_months", "rate_index"):
            try:
                if values.get(key):
                    values[key] = str(Decimal(values[key]).normalize())
            except InvalidOperation:
                pass
        normalized.append(canonical_digest(values))
    return canonical_digest(sorted(normalized))


def canonical_digest(value: Any) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def product_rows_digest(products: list[dict]) -> str:
    rows = []
    fields = ("dataset", "provider", "product_id", "product_key", "product_name", "category", "last_updated")
    for product in products:
        values = {key: str(product.get(key) or "") for key in fields}
        values["details_json"] = json.loads(product.get("details_json") or "null")
        rows.append(canonical_digest(values))
    return canonical_digest(sorted(rows))


def exclusion_reason(row: Mapping[str, Any]) -> str | None:
    section = row.get("dataset")
    if section not in SECTIONS:
        return "unsupported_section"
    if category_excludes_section(row.get("category"), str(section), row=row):
        return "out_of_section_category"
    if section_filter(str(section), dict(row)):
        return None
    if row.get("rate") is None or str(row.get("rate")).strip() in {"", "null", "None"}:
        return "no_rate"
    if section == "Mortgage" and row.get("rate_type") == "DISCOUNT":
        return "discount_not_absolute_rate"
    return "inapplicable_rate_family"


def payload_accounting(products: list[dict], rates: list[dict]) -> dict:
    """Account for every source row using the exact shipping section filter."""
    sections = {}
    visible_keys: set[str] = set()
    exclusions: Counter[str] = Counter()
    for section in (*SECTIONS, "Other"):
        source = [r for r in rates if (r.get("dataset") == section if section != "Other"
                                      else r.get("dataset") not in SECTIONS)]
        reasons = Counter(exclusion_reason(r) for r in source)
        visible = [r for r in source if exclusion_reason(r) is None]
        visible_keys.update(str(r.get("product_key") or "") for r in visible)
        excluded = {str(k): n for k, n in reasons.items() if k is not None}
        exclusions.update(excluded)
        sections[section] = {
            "source_rates": len(source), "published_rates": len(visible),
            "excluded_rates": sum(excluded.values()), "exclusions": excluded,
            "published_products": len({r.get("product_key") for r in visible} - {None, ""}),
            "published_providers": len({r.get("provider") for r in visible} - {None, ""}),
        }
    visible_keys.discard("")
    product_keys = {str(p.get("product_key") or "") for p in products} - {""}
    return {
        "schema_version": ACCOUNTING_VERSION, "source_products": len(products),
        "source_rates": len(rates), "published_rates": sum(s["published_rates"] for s in sections.values()),
        "excluded_rates": sum(exclusions.values()), "exclusions": dict(sorted(exclusions.items())),
        "published_products": len(visible_keys), "products_without_published_rates": len(product_keys - visible_keys),
        "providers_with_products": len({p.get("provider") for p in products} - {None, ""}),
        "providers_with_published_rates": len({r.get("provider") for r in rates if exclusion_reason(r) is None} - {None, ""}),
        "sections": sections,
    }


def audit_rows(products: list[dict], rates: list[dict]) -> dict:
    """Keep exact membership/fingerprints for historical comparisons and repair evidence."""
    product_counts = Counter(str(p.get("product_key") or "") for p in products)
    identities = {(p.get("dataset"), p.get("provider"), p.get("product_id")) for p in products}
    by_provider: dict[str, dict] = defaultdict(lambda: {"products": 0, "rates": 0, "published_rates": 0})
    fingerprints = {}
    for product in products:
        by_provider[str(product.get("provider") or "")]["products"] += 1
        # Stable provider/product identity; names and legacy product_key can change.
        identity = canonical_digest([product.get("dataset"), product.get("provider"), product.get("product_id")])
        fingerprints[identity] = {"provider": product.get("provider"), "product_id": product.get("product_id"),
                                  "dataset": product.get("dataset"), "sha256": canonical_digest({
                                      k: v for k, v in product.items()
                                      if k not in {"id", "run_date", "source_file"}})}
    invalid, orphan, malformed_details, missing_taxonomy = [], [], [], []
    row_hashes: Counter[str] = Counter()
    for number, row in enumerate(rates):
        provider = by_provider[str(row.get("provider") or "")]
        provider["rates"] += 1
        reason = exclusion_reason(row)
        provider["published_rates"] += reason is None
        row_hashes[canonical_digest(row)] += 1
        if (row.get("dataset"), row.get("provider"), row.get("product_id")) not in identities:
            orphan.append(number)
        if reason is not None:
            continue
        try:
            number_rate = float(row.get("rate"))
            # CDR RateString permits negative rates and percentages above 100%.
            # Preserve the reported value; only malformed/non-finite rates fail.
            if not math.isfinite(number_rate):
                invalid.append(number)
        except (ValueError, TypeError):
            invalid.append(number)
        if not row.get("taxonomy_path"):
            missing_taxonomy.append(number)
    for number, product in enumerate(products):
        try:
            if not isinstance(json.loads(product.get("details_json") or "null"), dict):
                malformed_details.append(number)
        except (ValueError, TypeError):
            malformed_details.append(number)
    return {
        "accounting": payload_accounting(products, rates), "provider_products": dict(by_provider),
        "published_rate_digests": {section: rate_rows_digest([r for r in rates
                                    if r.get("dataset") == section and exclusion_reason(r) is None]) for section in SECTIONS},
        "products": fingerprints, "duplicate_product_keys": {k: n for k, n in product_counts.items() if n > 1},
        "missing_product_keys": product_counts.get("", 0), "duplicate_exact_rate_rows": sum(n - 1 for n in row_hashes.values()),
        "invalid_rate_rows": invalid, "orphan_rate_rows": orphan,
        "malformed_product_details": malformed_details, "missing_taxonomy_rows": missing_taxonomy,
    }


def reconcile_public_core(core: dict, accounting: dict) -> list[dict]:
    issues = []
    for section in SECTIONS:
        actual = len((core.get("sections", {}).get(section) or {}).get("rates") or [])
        expected = accounting["sections"][section]["published_rates"]
        if actual != expected:
            issues.append({"code": "PUBLIC_RATE_COUNT_MISMATCH", "section": section,
                           "expected": expected, "actual": actual})
    return issues
