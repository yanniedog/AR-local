"""Apply retained, rate-local winner restrictions to derived standard history.

Original rows and source details remain immutable. Today's restrictions are
never projected backwards onto a different day's missing or different detail.
"""
from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
import hashlib
import json

from cdr_clean_export import append_bank_details
from cdr_savings_conditions import winner_rate_evidence

POLICY = "retained-savings-winner-restrictions-v1"
_IDENTITY = ("provider", "product_id", "category", "dataset")
_TEXT = ("rate_family", "rate_type", "application_type", "application_frequency",
         "repayment_type", "loan_purpose", "term")
_NUMBERS = ("rate", "comparison_rate", "balance_min", "balance_max")
_INVALID = object()


def identity(row):
    return "\x1f".join(str(row.get(field) or "").strip() for field in _IDENTITY)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode()).hexdigest()


def _number(value):
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else _INVALID
    except InvalidOperation:
        return _INVALID


def _matches(row, candidate):
    # Price alone cannot distinguish a restricted and an ordinary sibling.
    for field in _NUMBERS:
        left, right = _number(row.get(field)), _number(candidate.get(field))
        if left is _INVALID or right is _INVALID or left != right:
            return False
    return all(str(row.get(field) or "") == str(candidate.get(field) or "") for field in _TEXT)


def _source(product):
    raw = product.get("details_json")
    try:
        details = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return None
    product_id = product.get("product_id")
    if (not isinstance(product_id, str) or not product_id.strip()
            or not isinstance(details, Mapping) or details.get("productId") != product_id
            or not isinstance(details.get("depositRates"), list) or not details["depositRates"]
            or any(not isinstance(item, Mapping) for item in details["depositRates"])):
        return None
    return details


def _product_sources(products):
    grouped = {}
    for product in products:
        if isinstance(product, Mapping) and product.get("dataset") == "Savings":
            grouped.setdefault(str(product.get("product_key") or ""), []).append(product)
    result = {}
    for key, group in grouped.items():
        # A conflicting duplicate key cannot donate its detail to another row.
        if len({digest(product) for product in group}) != 1:
            continue
        product = group[0]
        details = _source(product)
        if details is None:
            continue
        restricted = {index for index, item in enumerate(details["depositRates"], 1)
                      if winner_rate_evidence(item)}
        dataset = {field: [] for field in ("rates", "fees", "features", "eligibility", "constraints")}
        append_bank_details(dataset, product, details)
        result[key] = (product, details, restricted, dataset["rates"])
    return result


def _matching_candidates(row, candidates):
    index = row.get("rate_index")
    if index not in (None, ""):
        # A retained array position is usable only with matching exported fields.
        try:
            if isinstance(index, bool) or str(int(index)) != str(index):
                return []
            candidates = [item for item in candidates if item["rate_index"] == int(index)]
        except (ValueError, TypeError, OverflowError):
            return []
    return [item for item in candidates if _matches(row, item)]


def _unknown(unknown, product_identity, note, row, reason, details=None):
    issue = unknown.setdefault(product_identity, {**note, "reason": reason, "unresolved_rows": []})
    evidence = {"row_sha256": digest(row), "reason": reason}
    if details is not None:
        evidence["details_sha256"] = digest(details)
    issue["unresolved_rows"].append(evidence)


def project_standard_history_rows(banks, run_date):
    """Return projection copies plus evidence; unknown affected days stay gaps."""
    sources = _product_sources(banks.get("products") or [])
    rates, changes, unknown, restricted_products = [], [], {}, set()
    for row in banks.get("rates") or []:
        if not isinstance(row, Mapping):
            continue
        rates.append(row)
        if row.get("dataset") != "Savings":
            continue
        key, product_identity = str(row.get("product_key") or ""), identity(row)
        source = sources.get(key)
        note = {"date": run_date, "product_key": key}
        if not source or identity(source[0]) != product_identity:
            if row.get("account_class") == "standard":
                _unknown(unknown, product_identity, note, row, "retained_detail_unavailable_or_ambiguous")
            continue
        product, details, restricted, candidates = source
        if restricted:
            restricted_products.add(product_identity)
        if row.get("account_class") != "standard":
            continue  # Existing exclusions are never upgraded to ordinary.
        matches = _matching_candidates(row, candidates)
        flags = {candidate["rate_index"] in restricted for candidate in matches}
        if not matches or len(flags) != 1:
            _unknown(unknown, product_identity, note, row, "retained_rate_mapping_unresolved", details)
            continue
        if flags == {True}:
            rates[-1] = {**row, "account_class": "non_standard"}
            changes.append({**note, "action": "exclude_winner_rate", "from_class": "standard",
                "to_class": "non_standard", "row_sha256": digest(row), "details_sha256": digest(details),
                "source_rates": [{"index": candidate["rate_index"],
                                  "sha256": digest(details["depositRates"][candidate["rate_index"] - 1])}
                                 for candidate in matches]})
    return rates, {"changes": changes, "unknown": unknown, "restricted_products": restricted_products}
