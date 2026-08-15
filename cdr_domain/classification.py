"""One evidence-reporting classifier for every consumer-facing capability."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional

from cdr_taxonomy import ACCOUNT_CLASS_NON_STANDARD, classify_account_standardness

from .models import (
    ClassificationStatus,
    ConsumerSection,
    ProductClassification,
    ProductKind,
)

CLASSIFICATION_VERSION = "product-classification-v1"

_MORTGAGE_CATEGORIES = {
    "RESIDENTIAL_MORTGAGES",
    "RESIDENTIAL_MORTGAGE",
    "MORTGAGES",
    "MORTGAGE",
    "HOME_LOANS",
    "HOME_LOAN",
}
_TERM_DEPOSIT_CATEGORIES = {
    "TERM_DEPOSITS",
    "TERM_DEPOSIT",
    "FIXED_TERM_DEPOSITS",
    "FIXED_TERM_DEPOSIT",
    "FIXED_DEPOSITS",
    "FIXED_DEPOSIT",
}
_DEPOSIT_CATEGORIES = {
    "TRANS_AND_SAVINGS_ACCOUNTS",
    "TRANS_AND_SAVINGS_ACCOUNT",
    "TRANSACTION_AND_SAVINGS_ACCOUNTS",
    "SAVINGS_ACCOUNTS",
    "SAVINGS_ACCOUNT",
    "SAVINGS",
}
_TERM_DEPOSIT_NAME = re.compile(r"\b(?:term|fixed)[-\s]+deposit\b", re.IGNORECASE)
_TRANSACTION_NAME = re.compile(
    r"\b(?:transaction|everyday|spending|access|debit)\b", re.IGNORECASE
)
_BUSINESS_NAME = re.compile(
    r"\b(?:business|commercial|corporate|wholesale|institutional|sme)\b",
    re.IGNORECASE,
)
_RESTRICTED_NAME = re.compile(
    r"\b(?:smsf|self[-\s]*managed\s+super|staff|veterans?|dhoas)\b",
    re.IGNORECASE,
)
_BUSINESS_PURPOSE = re.compile(
    r"\b(?:only\s+available\s+to\s+business|business\s+lending\s+customers?|"
    r"(?:loans?|finance|lending)\s+for\s+business\s+purposes?|"
    r"residentially\s+secured\s+loans?\s+for\s+business\s+purposes?)\b",
    re.IGNORECASE,
)
_NEGATED_BUSINESS = re.compile(
    r"\b(?:cannot|can't|must\s+not|not)\b[^.;]{0,50}\b(?:business|commercial)\b",
    re.IGNORECASE,
)
_COMPANY_ONLY = re.compile(
    r"\b(?:be|borrowers?\s+must\s+be|applicants?\s+must\s+be|a)\s+(?:a\s+)?company\b"
    r"|\bnon[-\s]*individual\s+borrowers?\b",
    re.IGNORECASE,
)
_PERSONAL_ALTERNATIVE = re.compile(
    r"\b(?:individuals?|natural\s+persons?|personal\s+use)\b",
    re.IGNORECASE,
)
_OPTIONAL_COHORT = re.compile(
    r"\b(?:also\s+available\s+for\s+dhoas|smsf\s+allowed|"
    r"individuals?\s+and\s+(?:self[-\s]*managed\s+superannuation\s+funds?|smsfs?))\b",
    re.IGNORECASE,
)


def _eligibility_text(item: Mapping[str, Any]) -> str:
    return " ".join(str(item.get(key) or "") for key in ("additionalInfo", "additionalValue"))


def _business_restricted(record: Mapping[str, Any]) -> bool:
    category = str(record.get("productCategory") or "").strip().upper()
    if "BUSINESS" in category or "COMMERCIAL" in category:
        return True
    name = str(record.get("name") or "")
    if _BUSINESS_NAME.search(name):
        return True
    description = str(record.get("description") or "")
    if _BUSINESS_PURPOSE.search(description) and not _NEGATED_BUSINESS.search(description):
        return True
    eligibility = [
        item
        for item in (record.get("eligibility") or [])
        if isinstance(item, Mapping)
    ]
    eligibility_text = " ".join(_eligibility_text(item) for item in eligibility)
    has_personal_path = bool(
        _PERSONAL_ALTERNATIVE.search(eligibility_text)
        or any(
            str(item.get("eligibilityType") or "").strip().upper()
            == "NATURAL_PERSON"
            for item in eligibility
        )
    )
    if _BUSINESS_PURPOSE.search(eligibility_text) and not _NEGATED_BUSINESS.search(
        eligibility_text
    ):
        return True
    if _COMPANY_ONLY.search(eligibility_text) and not has_personal_path:
        return True
    return False


def _scope_reason(record: Mapping[str, Any], category: str, dataset: str) -> Optional[str]:
    name = str(record.get("name") or "")
    eligibility = record.get("eligibility")
    if _business_restricted(record):
        return "business_product"
    dataset_key = str(dataset or "").strip().upper()
    taxonomy_dataset = {
        "MORTGAGE": "Mortgage",
        "SAVINGS": "Savings",
        "TD": "TD",
    }.get(dataset_key, dataset)
    if (
        classify_account_standardness(name, category, taxonomy_dataset, eligibility=None)
        == ACCOUNT_CLASS_NON_STANDARD
    ):
        return "restricted_eligibility" if _RESTRICTED_NAME.search(name) else "non_standard_product"
    if (
        classify_account_standardness(name, category, taxonomy_dataset, eligibility=eligibility)
        == ACCOUNT_CLASS_NON_STANDARD
    ):
        all_text = " ".join(
            [str(record.get("description") or "")]
            + [
                _eligibility_text(item)
                for item in (eligibility or [])
                if isinstance(item, Mapping)
            ]
        )
        if _OPTIONAL_COHORT.search(all_text) or "for personal use" in all_text.casefold():
            return None
        return "restricted_eligibility"
    return None


def _feature_types(record: Mapping[str, Any]) -> set[str]:
    return {
        str(item.get("featureType") or "").upper()
        for item in (record.get("features") or [])
        if isinstance(item, Mapping)
    }


def _has_positive_deposit_rate(record: Mapping[str, Any]) -> bool:
    for rate in record.get("depositRates") or []:
        if not isinstance(rate, Mapping) or rate.get("rate") in (None, ""):
            continue
        try:
            if Decimal(str(rate["rate"])) > 0:
                return True
        except InvalidOperation:
            continue
    return False


def _result(
    kind: ProductKind,
    section: Optional[ConsumerSection],
    status: ClassificationStatus,
    basis: list[str],
    reason: Optional[str] = None,
) -> ProductClassification:
    return ProductClassification(
        product_kind=kind,
        consumer_section=section,
        classification_status=status,
        classification_basis=tuple(basis),
        classification_version=CLASSIFICATION_VERSION,
        quarantine_reason=reason,
    )


def classify_product(record: Mapping[str, Any], dataset: str) -> ProductClassification:
    dataset_key = str(dataset or "").strip().upper()
    category = str(record.get("productCategory") or "").strip().upper()
    name = str(record.get("name") or "")
    features = _feature_types(record)
    basis = [f"dataset:{dataset or 'unknown'}", f"productCategory:{category or 'missing'}"]
    restricted_reason = _scope_reason(record, category, dataset_key)

    if category in _TERM_DEPOSIT_CATEGORIES or dataset_key == "TD" or _TERM_DEPOSIT_NAME.search(name):
        basis.append("explicit_term_deposit")
        if restricted_reason:
            basis.append(f"restricted_scope:{restricted_reason}")
            return _result(
                ProductKind.TERM_DEPOSIT,
                None,
                ClassificationStatus.QUARANTINED,
                basis,
                restricted_reason,
            )
        return _result(
            ProductKind.TERM_DEPOSIT,
            ConsumerSection.TERM_DEPOSIT,
            ClassificationStatus.CONFIRMED,
            basis,
        )
    if category in _MORTGAGE_CATEGORIES or dataset_key == "MORTGAGE":
        basis.append("explicit_mortgage")
        if restricted_reason:
            basis.append(f"restricted_scope:{restricted_reason}")
            return _result(
                ProductKind.MORTGAGE,
                None,
                ClassificationStatus.QUARANTINED,
                basis,
                restricted_reason,
            )
        return _result(
            ProductKind.MORTGAGE,
            ConsumerSection.MORTGAGE,
            ClassificationStatus.CONFIRMED,
            basis,
        )
    description = str(record.get("description") or "")
    if "OFFSET" in features or (
        "offset" in name.casefold() and "loan" in description.casefold()
    ):
        basis.append("feature:OFFSET")
        return _result(
            ProductKind.MORTGAGE_OFFSET,
            None,
            ClassificationStatus.QUARANTINED,
            basis,
            "mortgage_linked_offset",
        )
    if category not in _DEPOSIT_CATEGORIES and dataset_key != "SAVINGS":
        return _result(
            ProductKind.UNKNOWN,
            None,
            ClassificationStatus.UNKNOWN,
            basis,
            "unsupported_or_missing_product_category",
        )

    positive_rate = _has_positive_deposit_rate(record)
    transaction_signal = bool(
        features.intersection({"CARD_ACCESS", "NPP_ENABLED", "NPP_PAYID", "UNLIMITED_TXNS"})
        or _TRANSACTION_NAME.search(name)
    )
    kind = (
        ProductKind.TRANSACTION_ACCOUNT
        if transaction_signal
        else ProductKind.SAVINGS_ACCOUNT if positive_rate else ProductKind.UNKNOWN
    )
    if restricted_reason:
        basis.append(f"restricted_scope:{restricted_reason}")
        return _result(kind, None, ClassificationStatus.QUARANTINED, basis, restricted_reason)
    if kind is ProductKind.SAVINGS_ACCOUNT:
        basis.append("published_positive_deposit_rate")
        return _result(
            kind,
            ConsumerSection.SAVINGS,
            ClassificationStatus.CONFIRMED,
            basis,
        )
    if kind is ProductKind.TRANSACTION_ACCOUNT:
        basis.append("transaction_access_signal")
        return _result(kind, None, ClassificationStatus.QUARANTINED, basis, "transaction_account")
    return _result(
        ProductKind.UNKNOWN,
        None,
        ClassificationStatus.UNKNOWN,
        basis,
        "insufficient_pricing_evidence",
    )
