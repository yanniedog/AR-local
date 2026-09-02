"""Pure JSON parsing and product classification for CDR ingest."""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Optional


DATASET_CATEGORY_ALIASES = {
    "home_loans": (
        "RESIDENTIAL_MORTGAGES",
        "RESIDENTIAL_MORTGAGE",
        "MORTGAGES",
        "MORTGAGE",
        "HOME_LOANS",
        "HOME_LOAN",
    ),
    "savings": (
        "TRANS_AND_SAVINGS_ACCOUNTS",
        "TRANS_AND_SAVINGS_ACCOUNT",
        "TRANS_AND_SAVINGS",
        "SAVINGS_ACCOUNTS",
        "SAVINGS_ACCOUNT",
        "SAVINGS",
        "TRANSACTION_AND_SAVINGS_ACCOUNTS",
    ),
    "term_deposits": (
        "TERM_DEPOSITS",
        "TERM_DEPOSIT",
        "FIXED_TERM_DEPOSITS",
        "FIXED_TERM_DEPOSIT",
        "FIXED_DEPOSITS",
        "FIXED_DEPOSIT",
    ),
}

KNOWN_OUT_OF_SCOPE_CATEGORIES = frozenset(
    {
        "BUSINESS_LOANS",
        "BUY_NOW_PAY_LATER",
        "CRED_AND_CHRG_CARDS",
        "LEASES",
        "MARGIN_LOANS",
        "OVERDRAFTS",
        "PERS_LOANS",
        "REGULATED_TRUST_ACCOUNTS",
        "TRADE_FINANCE",
        "TRAVEL_CARDS",
    }
)

DATASET_TO_FOLDER = {
    "home_loans": "Mortgage",
    "savings": "Savings",
    "term_deposits": "TD",
}


def is_record(value: Any) -> bool:
    return isinstance(value, dict)


def as_array(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def pick_text(record: Mapping[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        raw = record.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            return text
    return ""


def normalize_category_token(value: str) -> str:
    text = str(value or "").strip().upper()
    return re.sub(r"[^A-Z0-9]+", "_", text).strip("_")


def normalize_cdr_product_category(value: Any) -> Optional[str]:
    token = normalize_category_token(str(value or ""))
    return token or None


def extract_cdr_product_category(product: Mapping[str, Any]) -> Optional[str]:
    return normalize_cdr_product_category(
        pick_text(product, ("productCategory", "category", "type"))
    )


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
    for rate in as_array(product.get("lendingRates")):
        if is_record(rate) and pick_text(
            rate, ("loanPurpose", "repaymentType", "lendingRateType")
        ):
            return True
    return False


def has_deposit_structured_signals(product: Mapping[str, Any]) -> bool:
    """Whether deposit fields exist; this deliberately does not choose a dataset."""
    if any(is_record(item) for item in as_array(product.get("depositRates"))):
        return True
    return any(
        is_record(rate)
        and bool(
            pick_text(
                rate,
                (
                    "depositRateType",
                    "rateType",
                    "applicationType",
                    "rateApplicabilityType",
                ),
            )
        )
        for rate in as_array(product.get("rates"))
    )


def infer_dataset_from_structured_signals(
    product: Mapping[str, Any],
) -> Optional[str]:
    if has_mortgage_structured_signals(product):
        return "home_loans"
    # Deposit-rate fields are shared by savings and term deposits. They prove
    # neither dataset, so an unknown category must fall through to explicit
    # product-name evidence or remain unresolved.
    return None


def infer_dataset_from_name(product: Mapping[str, Any]) -> Optional[str]:
    name = pick_text(product, ("name", "productName")).upper()
    if "MORTGAGE" in name or "HOME LOAN" in name:
        return "home_loans"
    if "TERM DEPOSIT" in name or "FIXED DEPOSIT" in name:
        return "term_deposits"
    if "SAVINGS" in name or "SAVER" in name or "AT CALL" in name:
        return "savings"
    return None


def infer_cdr_dataset(
    product: Mapping[str, Any], *, allow_name_fallback: bool = True
) -> Optional[str]:
    raw_category = extract_cdr_product_category(product)
    dataset = dataset_from_cdr_category(raw_category)
    if dataset:
        return dataset
    if raw_category in KNOWN_OUT_OF_SCOPE_CATEGORIES:
        return None
    structured = infer_dataset_from_structured_signals(product)
    if structured:
        return structured
    return infer_dataset_from_name(product) if allow_name_fallback else None


def detail_inner_record(parsed: Any) -> Optional[dict[str, Any]]:
    if not is_record(parsed):
        return None
    inner = parsed.get("data")
    return inner if is_record(inner) else parsed
