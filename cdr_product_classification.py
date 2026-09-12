"""Pure, permissive product classification shared by CDR ingest callers."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional


DATASET_CATEGORY_ALIASES: Dict[str, List[str]] = {
    "home_loans": [
        "RESIDENTIAL_MORTGAGES",
        "RESIDENTIAL_MORTGAGE",
        "MORTGAGES",
        "MORTGAGE",
        "HOME_LOANS",
        "HOME_LOAN",
    ],
    "savings": [
        "TRANS_AND_SAVINGS_ACCOUNTS",
        "TRANS_AND_SAVINGS_ACCOUNT",
        "TRANS_AND_SAVINGS",
        "SAVINGS_ACCOUNTS",
        "SAVINGS_ACCOUNT",
        "SAVINGS",
        "TRANSACTION_AND_SAVINGS_ACCOUNTS",
    ],
    "term_deposits": [
        "TERM_DEPOSITS",
        "TERM_DEPOSIT",
        "FIXED_TERM_DEPOSITS",
        "FIXED_TERM_DEPOSIT",
        "FIXED_DEPOSITS",
        "FIXED_DEPOSIT",
    ],
}

DATASET_TO_FOLDER = {
    "home_loans": "Mortgage",
    "savings": "Savings",
    "term_deposits": "TD",
}

# Explicit product categories outrank a marketing name or generic rate fields.
# A business loan secured by a term deposit is not a term deposit product.
OUT_OF_SCOPE_CATEGORIES = frozenset({
    "BUSINESS_LOANS", "BUSINESS_LOAN", "PERS_LOANS", "PERSONAL_LOANS", "PERSONAL_LOAN",
    "OVERDRAFTS", "OVERDRAFT", "CRED_AND_CHRG_CARDS", "CREDIT_CARDS", "MARGIN_LOANS",
    "LEASES", "TRADE_FINANCE", "REGULATED_TRUST_ACCOUNTS", "TRAVEL_CARDS",
})


def category_excludes_section(category: Any, section: str) -> bool:
    normalized = normalize_cdr_product_category(category)
    if normalized in OUT_OF_SCOPE_CATEGORIES:
        return True
    dataset = dataset_from_cdr_category(normalized)
    return dataset is not None and DATASET_TO_FOLDER[dataset] != section


def excluded_category_tokens(section: str) -> list[str]:
    return sorted(OUT_OF_SCOPE_CATEGORIES | {token for dataset, tokens in DATASET_CATEGORY_ALIASES.items()
                                            if DATASET_TO_FOLDER[dataset] != section for token in tokens})


def is_record(value: Any) -> bool:
    return isinstance(value, dict)


def as_array(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return []


def pick_text(record: Mapping[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        raw = record.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            return text
    return ""


def safe_url(value: str) -> str:
    return value.rstrip("/")


def normalize_category_token(value: str) -> str:
    text = str(value or "").strip().upper()
    text = re.sub(r"[^A-Z0-9]+", "_", text)
    return text.strip("_")


def normalize_cdr_product_category(value: Any) -> Optional[str]:
    token = normalize_category_token(str(value or ""))
    return token if token else None


def extract_cdr_product_category(product: Mapping[str, Any]) -> Optional[str]:
    raw = pick_text(product, ["productCategory", "category", "type"])
    return normalize_cdr_product_category(raw)


def dataset_from_cdr_category(category: Optional[str]) -> Optional[str]:
    normalized = normalize_cdr_product_category(category or "")
    if not normalized:
        return None
    for dataset, aliases in DATASET_CATEGORY_ALIASES.items():
        if normalized in aliases:
            return dataset
    if "MORTGAGE" in normalized or "HOME_LOAN" in normalized:
        return "home_loans"
    if "TERM_DEPOSIT" in normalized or "FIXED_DEPOSIT" in normalized:
        return "term_deposits"
    if "SAVINGS" in normalized or "TRANS_AND_SAVINGS" in normalized:
        return "savings"
    return None


def has_mortgage_structured_signals(product: Mapping[str, Any]) -> bool:
    rates = [x for x in as_array(product.get("lendingRates")) if is_record(x)]
    if not rates:
        return False
    for rate in rates:
        if not is_record(rate):
            continue
        lp = pick_text(rate, ["loanPurpose"])
        rt = pick_text(rate, ["repaymentType"])
        lrt = pick_text(rate, ["lendingRateType"])
        if lp or rt or lrt:
            return True
    return False


def has_deposit_structured_signals(product: Mapping[str, Any]) -> bool:
    dr = [x for x in as_array(product.get("depositRates")) if is_record(x)]
    if dr:
        return True
    generic = [x for x in as_array(product.get("rates")) if is_record(x)]
    for rate in generic:
        if not is_record(rate):
            continue
        dt = pick_text(rate, ["depositRateType", "rateType"])
        at = pick_text(rate, ["applicationType", "rateApplicabilityType"])
        if dt or at:
            return True
    return False


def infer_dataset_from_structured_signals(product: Mapping[str, Any]) -> Optional[str]:
    if has_mortgage_structured_signals(product):
        return "home_loans"
    if has_deposit_structured_signals(product):
        cat_ds = dataset_from_cdr_category(extract_cdr_product_category(product))
        if cat_ds:
            return cat_ds
        return "savings"
    return None


def infer_dataset_from_name(product: Mapping[str, Any]) -> Optional[str]:
    name = pick_text(product, ["name", "productName"]).upper()
    if not name:
        return None
    if "MORTGAGE" in name or "HOME LOAN" in name:
        return "home_loans"
    if "TERM DEPOSIT" in name or "FIXED DEPOSIT" in name:
        return "term_deposits"
    if "SAVINGS" in name or "SAVER" in name or "AT CALL" in name:
        return "savings"
    return None


def infer_cdr_dataset(
    product: Mapping[str, Any],
    *,
    allow_name_fallback: bool = True,
) -> Optional[str]:
    category = extract_cdr_product_category(product)
    if category in OUT_OF_SCOPE_CATEGORIES:
        return None
    cat_ds = dataset_from_cdr_category(category)
    if cat_ds:
        return cat_ds
    structured = infer_dataset_from_structured_signals(product)
    if structured:
        return structured
    if not allow_name_fallback:
        return None
    return infer_dataset_from_name(product)


def detail_inner_record(parsed: Any) -> Optional[Dict[str, Any]]:
    if not is_record(parsed):
        return None
    inner = parsed.get("data")
    if is_record(inner):
        return inner
    return parsed  # type: ignore[return-value]
