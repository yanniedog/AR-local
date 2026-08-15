"""Normalize one preserved CDR product record into canonical v3 entities."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional

from .classification import classify_product
from .evidence import product_evidence
from .identity import (
    evidence_uid,
    fee_semantics,
    fee_uid_from_semantics,
    product_uid,
    provider_uid,
    rate_identity_statuses,
)
from .models import (
    CanonicalFee,
    CanonicalIdentity,
    CanonicalProduct,
    CanonicalRate,
    DisclosureStatus,
    EvidenceRef,
    EvidenceStatus,
    FeeRateUnit,
    IdentityStatus,
    TypedFeeRate,
)
from .rates import decimal_text, rate_from_record
from .validate import validate_canonical_product

NORMALIZATION_VERSION = "canonical-v3-domain-v1"


def _fee_amounts(fee: Mapping[str, Any]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    method = str(fee.get("feeMethodUType") or "").lower()
    fee_type = str(fee.get("feeType") or "").upper()
    fixed = fee.get("fixedAmount") if isinstance(fee.get("fixedAmount"), Mapping) else {}
    variable = fee.get("variable") if isinstance(fee.get("variable"), Mapping) else {}
    raw = fee.get("amount") if fee.get("amount") not in (None, "") else fixed.get("amount")
    variable_fee = method == "variable" or fee_type == "VARIABLE"
    fixed_amount = None if raw in (None, "") or variable_fee else decimal_text(raw)
    minimum = (
        decimal_text(variable["feeMinimum"])
        if variable.get("feeMinimum") not in (None, "")
        else None
    )
    maximum = (
        decimal_text(variable["feeMaximum"])
        if variable.get("feeMaximum") not in (None, "")
        else None
    )
    for label, value in (("fixed", fixed_amount), ("minimum", minimum), ("maximum", maximum)):
        if value is not None and Decimal(value) < 0:
            raise ValueError(f"fee {label} amount cannot be negative")
    if minimum is not None and maximum is not None and Decimal(minimum) > Decimal(maximum):
        raise ValueError("fee minimum amount cannot exceed maximum amount")
    return fixed_amount, minimum, maximum


def _fee_rate(fee: Mapping[str, Any], evidence_id: str) -> Optional[TypedFeeRate]:
    rated = fee.get("rateBased") if isinstance(fee.get("rateBased"), Mapping) else {}
    raw = rated.get("rate")
    if raw in (None, ""):
        for key in ("transactionRate", "balanceRate", "accruedRate"):
            if fee.get(key) not in (None, ""):
                raw = fee[key]
                break
    if raw in (None, ""):
        return None
    return TypedFeeRate(
        value=decimal_text(raw),
        unit=FeeRateUnit.FRACTION_OF_AMOUNT,
        evidence_status=EvidenceStatus.PUBLISHED,
        evidence_ids=(evidence_id,),
    )


def _fees(
    product: str, record: Mapping[str, Any], evidence_id: str
) -> tuple[CanonicalFee, ...]:
    out = []
    for fee in record.get("fees") or []:
        if not isinstance(fee, Mapping):
            continue
        fixed, minimum, maximum = _fee_amounts(fee)
        rate = _fee_rate(fee, evidence_id)
        methods = sum(
            (
                fixed is not None,
                minimum is not None or maximum is not None,
                rate is not None,
            )
        )
        if methods > 1:
            raise ValueError("fee publishes contradictory pricing methods")
        status = (
            DisclosureStatus.COMPLETE
            if any(value is not None for value in (fixed, minimum, maximum, rate))
            else DisclosureStatus.UNKNOWN
        )
        currency = (
            str(fee.get("currency")).upper()
            if fee.get("currency") not in (None, "") and not rate
            else None
        )
        monetary_values = tuple(
            Decimal(value)
            for value in (fixed, minimum, maximum)
            if value is not None
        )
        if status is DisclosureStatus.COMPLETE and monetary_values and currency is None:
            status = DisclosureStatus.PARTIAL
        semantics = fee_semantics(fee)
        out.append(
            CanonicalFee(
                fee_uid=fee_uid_from_semantics(product, semantics),
                semantic_fee=semantics,
                disclosure_status=status,
                currency=currency,
                fixed_amount=fixed,
                minimum_amount=minimum,
                maximum_amount=maximum,
                rate=rate,
                condition=(str(fee.get("additionalInfo")) if fee.get("additionalInfo") else None),
                evidence_ids=(evidence_id,),
            )
        )
    return tuple(out)


def _rates(
    product: str,
    provider: str,
    product_id: str,
    record: Mapping[str, Any],
    evidence_id: str,
    legacy_aliases: tuple[str, ...],
) -> tuple[CanonicalRate, ...]:
    out: list[CanonicalRate] = []
    for family, key in (("deposit", "depositRates"), ("lending", "lendingRates")):
        rows = [item for item in (record.get(key) or []) if isinstance(item, Mapping)]
        identities = rate_identity_statuses(product, rows, family)
        for source_index, (raw, identity_data) in enumerate(zip(rows, identities)):
            uid, status, semantics = identity_data
            advertised, comparison = rate_from_record(raw, family, evidence_id)
            identity = CanonicalIdentity(
                provider_uid=provider,
                provider_identity_status=(
                    IdentityStatus.FALLBACK
                    if provider.startswith("provider-fallback:")
                    else IdentityStatus.CONFIRMED
                ),
                product_uid=product,
                product_id=product_id,
                rate_uid=uid,
                rate_identity_status=status,
                legacy_aliases=legacy_aliases,
            )
            out.append(
                CanonicalRate(
                    identity=identity,
                    advertised=advertised,
                    comparison=comparison,
                    semantic_tier=semantics,
                    exact_alert_eligible=status is IdentityStatus.CONFIRMED,
                    source_index=source_index,
                )
            )
    return tuple(out)


def normalize_product(
    record: Mapping[str, Any],
    *,
    dataset: str,
    provider_display_name: str,
    register_holder_id: Optional[str],
    register_brand_id: Optional[str] = None,
    authority: Optional[str] = None,
    observed_at: str,
    source_path: str,
    source_locator: str,
    source_sha256: str,
    source_kind: str = "cdr_export_product_detail",
    legacy_aliases: Iterable[str] = (),
) -> CanonicalProduct:
    product_id = str(record.get("productId") or "").strip()
    if not product_id:
        raise ValueError("CDR productId is required")
    provider, provider_status = provider_uid(
        register_holder_id=register_holder_id,
        register_brand_id=register_brand_id,
        authority=authority,
        display_name=provider_display_name,
    )
    product = product_uid(provider, product_id)
    aliases = tuple(sorted({str(alias) for alias in legacy_aliases if str(alias)}))
    record_bytes = json.dumps(
        record,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    source_record_sha256 = hashlib.sha256(record_bytes).hexdigest()
    evidence_id = evidence_uid(
        source_kind=source_kind,
        source_sha256=source_sha256,
        source_path=source_path,
        source_locator=source_locator,
        source_record_sha256=source_record_sha256,
        product_id=product_id,
    )
    evidence_ref = EvidenceRef(
        evidence_id=evidence_id,
        source_kind=source_kind,
        source_path=source_path,
        source_locator=source_locator,
        source_sha256=source_sha256,
        source_record_sha256=source_record_sha256,
        observed_at=observed_at,
        effective_date=(
            str(record.get("effectiveFrom")) if record.get("effectiveFrom") else None
        ),
        source_updated_at=(
            str(record.get("lastUpdated")) if record.get("lastUpdated") else None
        ),
    )
    classification = classify_product(record, dataset)
    identity = CanonicalIdentity(
        provider_uid=provider,
        provider_identity_status=provider_status,
        product_uid=product,
        product_id=product_id,
        legacy_aliases=aliases,
    )
    result = CanonicalProduct(
        schema_version=3,
        normalization_version=NORMALIZATION_VERSION,
        identity=identity,
        display_name=str(record.get("name") or product_id),
        provider_display_name=provider_display_name,
        classification=classification,
        evidence=product_evidence(
            record, classification, evidence_id=evidence_id, observed_at=observed_at
        ),
        rates=_rates(product, provider, product_id, record, evidence_id, aliases),
        fees=_fees(product, record, evidence_id),
        evidence_refs=(evidence_ref,),
    )
    validate_canonical_product(result)
    return result
