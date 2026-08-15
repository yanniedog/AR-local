"""Stable provider, product, rate-tier, and fee identities."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Optional

from .models import IdentityStatus

IDENTITY_VERSION = "identity-v1"


def _digest(kind: str, value: object) -> str:
    material = json.dumps(
        [IDENTITY_VERSION, kind, value],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def evidence_uid(
    *,
    source_kind: str,
    source_sha256: str,
    source_path: str,
    source_locator: str,
    source_record_sha256: str,
    product_id: str,
) -> str:
    material = [
        source_kind,
        source_sha256,
        source_path,
        source_locator,
        source_record_sha256,
        product_id,
    ]
    encoded = json.dumps(material, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return "evidence:v1:" + hashlib.sha256(encoded).hexdigest()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _decimal_text(value: Any) -> Optional[str]:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return _text(value) or None
    if not number.is_finite():
        return None
    rendered = format(number, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in {"", "-0"} else rendered


def _semantic_text(value: Any) -> Optional[str]:
    text = unicodedata.normalize("NFKC", _text(value))
    return re.sub(r"\s+", " ", text).casefold() or None


def provider_uid(
    *,
    register_holder_id: Optional[str],
    register_brand_id: Optional[str] = None,
    authority: Optional[str] = None,
    display_name: Optional[str] = None,
) -> tuple[str, IdentityStatus]:
    """Return an official CDR identity or an explicitly marked fallback."""

    holder = _text(register_holder_id)
    brand = _text(register_brand_id)
    if holder and brand:
        return (
            f"provider:v1:{_digest('provider', {'holder': holder, 'brand': brand})}",
            IdentityStatus.CONFIRMED,
        )
    fallback = {
        "authority": _text(authority).lower(),
        "holder": holder or None,
        "brand": _text(display_name),
    }
    if not fallback["authority"] or not fallback["brand"]:
        raise ValueError("fallback provider identity requires authority and display_name")
    return f"provider-fallback:v1:{_digest('provider-fallback', fallback)}", IdentityStatus.FALLBACK


def product_uid(provider: str, product_id: str) -> str:
    product_id = _text(product_id)
    if not provider or not product_id:
        raise ValueError("provider_uid and product_id are required")
    return f"product:v1:{_digest('product', {'provider_uid': provider, 'product_id': product_id})}"


def _conditions(values: Any) -> list[dict[str, Optional[str]]]:
    if isinstance(values, Mapping):
        values = [values]
    if not isinstance(values, list):
        return []
    out = []
    for item in values:
        if not isinstance(item, Mapping):
            continue
        out.append(
            {
                "type": _text(item.get("rateApplicabilityType")).upper() or None,
                "value": _decimal_text(item.get("additionalValue"))
                or _text(item.get("additionalValue"))
                or None,
                "additional_info": _semantic_text(item.get("additionalInfo")),
            }
        )
    return sorted(out, key=lambda item: json.dumps(item, sort_keys=True))


def _tiers(values: Any) -> list[dict[str, object]]:
    if not isinstance(values, list):
        return []
    out: list[dict[str, object]] = []
    for item in values:
        if not isinstance(item, Mapping):
            continue
        out.append(
            {
                "unit": _text(item.get("unitOfMeasure")).upper() or None,
                "method": _text(item.get("rateApplicationMethod")).upper() or None,
                "minimum": _decimal_text(item.get("minimumValue")),
                "maximum": _decimal_text(item.get("maximumValue")),
                "additional_info": _semantic_text(item.get("additionalInfo")),
                "conditions": _conditions(item.get("applicabilityConditions")),
            }
        )
    return sorted(out, key=lambda item: json.dumps(item, sort_keys=True))


def rate_semantics(rate: Mapping[str, Any], family: str) -> dict[str, object]:
    """Canonical tier semantics; price, display text, and array position are absent."""

    type_key = "lendingRateType" if family == "lending" else "depositRateType"
    return {
        "family": family,
        "rate_type": _text(rate.get(type_key)).upper() or None,
        "application_type": _text(rate.get("applicationType")).upper() or None,
        "application_frequency": _text(rate.get("applicationFrequency")).upper() or None,
        "calculation_frequency": _text(rate.get("calculationFrequency")).upper() or None,
        "repayment_type": _text(rate.get("repaymentType")).upper() or None,
        "loan_purpose": _text(rate.get("loanPurpose")).upper() or None,
        "interest_payment_due": _text(rate.get("interestPaymentDue")).upper() or None,
        "duration": _text(rate.get("additionalValue")).upper() or None,
        "additional_info": _semantic_text(rate.get("additionalInfo")),
        "tiers": _tiers(rate.get("tiers")),
        "conditions": _conditions(rate.get("applicabilityConditions")),
    }


def rate_uid(product: str, semantics: Mapping[str, object]) -> str:
    if not product:
        raise ValueError("product_uid is required")
    return f"rate:v1:{_digest('rate', {'product_uid': product, 'semantics': semantics})}"


def rate_identity_statuses(
    product: str,
    rates: Iterable[Mapping[str, Any]],
    family: str,
) -> list[tuple[str, IdentityStatus, dict[str, object]]]:
    staged = []
    for rate in rates:
        semantics = rate_semantics(rate, family)
        staged.append((rate_uid(product, semantics), semantics))
    counts: dict[str, int] = {}
    for uid, _ in staged:
        counts[uid] = counts.get(uid, 0) + 1
    return [
        (uid, IdentityStatus.AMBIGUOUS if counts[uid] > 1 else IdentityStatus.CONFIRMED, semantics)
        for uid, semantics in staged
    ]


def fee_semantics(fee: Mapping[str, Any]) -> dict[str, Optional[str]]:
    return {
        "name": _text(fee.get("name") or fee.get("feeType") or "Fee"),
        "fee_type": _text(fee.get("feeType") or "UNKNOWN").upper(),
        "method": _text(fee.get("feeMethodUType")).upper() or None,
        "cadence": _text(fee.get("additionalValue")).upper() or None,
    }


def fee_uid_from_semantics(product: str, semantics: Mapping[str, object]) -> str:
    if not product:
        raise ValueError("product_uid is required")
    return f"fee:v1:{_digest('fee', {'product_uid': product, 'semantics': semantics})}"


def fee_uid(product: str, fee: Mapping[str, Any]) -> str:
    return fee_uid_from_semantics(product, fee_semantics(fee))
