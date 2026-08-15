"""Fail-closed invariants for canonical v3 entities."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from .models import (
    CanonicalProduct,
    ClassificationStatus,
    ConsumerSection,
    DisclosureStatus,
    IdentityStatus,
    ProductKind,
    RateBasis,
    RateMetric,
    RateUnit,
    FeeRateUnit,
)
from .identity import evidence_uid, fee_uid_from_semantics, product_uid, rate_uid
from .time import parse_rfc3339

_DIGEST_ID = re.compile(r"^(?:provider(?:-fallback)?|product|rate|fee):v1:[0-9a-f]{64}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_EVIDENCE_ID = re.compile(r"^evidence:v1:[0-9a-f]{64}$")

_RATE_CONTRACTS = {
    RateMetric.ADVERTISED_INTEREST: (RateUnit.FRACTION_PER_ANNUM, RateBasis.ADVERTISED),
    RateMetric.COMPARISON_INTEREST: (RateUnit.FRACTION_PER_ANNUM, RateBasis.COMPARISON),
    RateMetric.BASE_INTEREST: (RateUnit.FRACTION_PER_ANNUM, RateBasis.BASE),
    RateMetric.CONDITIONAL_INTEREST: (RateUnit.FRACTION_PER_ANNUM, RateBasis.CONDITIONAL),
    RateMetric.INTRODUCTORY_INTEREST: (RateUnit.FRACTION_PER_ANNUM, RateBasis.INTRODUCTORY),
    RateMetric.PUBLISHED_REVERSION_INTEREST: (
        RateUnit.FRACTION_PER_ANNUM,
        RateBasis.PUBLISHED_REVERSION,
    ),
    RateMetric.RBA_CASH_RATE: (RateUnit.PERCENTAGE_POINTS, RateBasis.OFFICIAL),
    RateMetric.RATE_CHANGE: (RateUnit.BASIS_POINTS, RateBasis.OBSERVED),
    RateMetric.CATALOGUE_GAP: (RateUnit.PERCENTAGE_POINTS, RateBasis.OBSERVED),
}
_PRODUCT_INTEREST_METRICS = {
    RateMetric.ADVERTISED_INTEREST,
    RateMetric.BASE_INTEREST,
    RateMetric.CONDITIONAL_INTEREST,
    RateMetric.INTRODUCTORY_INTEREST,
    RateMetric.PUBLISHED_REVERSION_INTEREST,
}


def _validate_rate(rate: Any) -> None:
    expected = _RATE_CONTRACTS.get(rate.metric)
    if expected != (rate.unit, rate.basis):
        raise ValueError(f"metric/unit/basis mismatch for {rate.metric.value}")
    try:
        number = Decimal(rate.value)
    except InvalidOperation as error:
        raise ValueError("rate value must be a decimal string") from error
    if not number.is_finite():
        raise ValueError("rate value must be finite")
    if rate.unit is RateUnit.FRACTION_PER_ANNUM and not Decimal("0") <= number <= Decimal("1"):
        raise ValueError("product rates must be fractions between 0 and 1")
    if rate.unit is RateUnit.PERCENTAGE_POINTS and not Decimal("-100") <= number <= Decimal("100"):
        raise ValueError("percentage-point rate is outside the supported domain")
    if not rate.evidence_ids:
        raise ValueError("typed rate requires evidence")


def _validate_fee_rate(rate: Any) -> None:
    if rate.unit is not FeeRateUnit.FRACTION_OF_AMOUNT:
        raise ValueError("fee rate must be a fraction of the charged amount")
    try:
        number = Decimal(rate.value)
    except InvalidOperation as error:
        raise ValueError("fee rate must be a decimal string") from error
    if not number.is_finite() or number < 0 or number > 1:
        raise ValueError("fee rate must be a finite fraction between 0 and 1")
    if not rate.evidence_ids:
        raise ValueError("fee rate requires evidence")


def _validate_rfc3339(label: str, value: Any, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    try:
        parse_rfc3339(value)
    except ValueError as error:
        raise ValueError(f"{label} must be an RFC3339 date-time") from error


def validate_canonical_product(product: CanonicalProduct) -> None:
    identity = product.identity
    if not _DIGEST_ID.fullmatch(identity.provider_uid):
        raise ValueError("invalid provider_uid")
    if not _DIGEST_ID.fullmatch(identity.product_uid):
        raise ValueError("invalid product_uid")
    if identity.rate_uid is not None or identity.rate_identity_status is not None:
        raise ValueError("product identity cannot carry a rate identity")
    if identity.product_uid != product_uid(identity.provider_uid, identity.product_id):
        raise ValueError("product_uid does not match its canonical derivation")
    expected_provider_status = (
        IdentityStatus.FALLBACK
        if identity.provider_uid.startswith("provider-fallback:")
        else IdentityStatus.CONFIRMED
    )
    if identity.provider_identity_status is not expected_provider_status:
        raise ValueError("provider identity status does not match provider_uid")
    classification = product.classification
    if classification.classification_status is ClassificationStatus.CONFIRMED:
        expected = {
            ProductKind.MORTGAGE: ConsumerSection.MORTGAGE,
            ProductKind.SAVINGS_ACCOUNT: ConsumerSection.SAVINGS,
            ProductKind.TERM_DEPOSIT: ConsumerSection.TERM_DEPOSIT,
        }.get(classification.product_kind)
        if expected is None or classification.consumer_section is not expected:
            raise ValueError("confirmed product has an invalid consumer section")
        if classification.quarantine_reason is not None:
            raise ValueError("confirmed product cannot have a quarantine reason")
    elif classification.consumer_section is not None:
        raise ValueError("unconfirmed products cannot enter a consumer section")
    if not product.evidence_refs:
        raise ValueError("canonical product requires evidence")
    _validate_rfc3339("product observed_at", product.evidence.observed_at)
    _validate_rfc3339(
        "product effective_date", product.evidence.effective_date, optional=True
    )
    _validate_rfc3339(
        "product source_updated_at", product.evidence.source_updated_at, optional=True
    )
    evidence_ids = {item.evidence_id for item in product.evidence_refs}
    for evidence in product.evidence_refs:
        if not _EVIDENCE_ID.fullmatch(evidence.evidence_id):
            raise ValueError("invalid evidence_id")
        if not _SHA.fullmatch(evidence.source_sha256):
            raise ValueError("invalid evidence source hash")
        if not _SHA.fullmatch(evidence.source_record_sha256):
            raise ValueError("invalid evidence source-record hash")
        if not evidence.source_locator:
            raise ValueError("evidence source locator is required")
        expected_evidence_id = evidence_uid(
            source_kind=evidence.source_kind,
            source_sha256=evidence.source_sha256,
            source_path=evidence.source_path,
            source_locator=evidence.source_locator,
            source_record_sha256=evidence.source_record_sha256,
            product_id=identity.product_id,
        )
        if evidence.evidence_id != expected_evidence_id:
            raise ValueError("evidence_id does not match its canonical derivation")
        _validate_rfc3339("evidence observed_at", evidence.observed_at)
        _validate_rfc3339(
            "evidence effective_date", evidence.effective_date, optional=True
        )
        _validate_rfc3339(
            "evidence source_updated_at", evidence.source_updated_at, optional=True
        )
        if (
            evidence.observed_at != product.evidence.observed_at
            or evidence.effective_date != product.evidence.effective_date
            or evidence.source_updated_at != product.evidence.source_updated_at
        ):
            raise ValueError("product and evidence-reference lineage timestamps disagree")
        path = evidence.source_path
        if (
            not path
            or path.startswith("/")
            or "\\" in path
            or ":" in path
            or ".." in path.split("/")
        ):
            raise ValueError("evidence source path must be safe and relative")
    if not set(product.evidence.evidence_ids).issubset(evidence_ids):
        raise ValueError("product evidence references unknown evidence")
    rate_uid_counts: dict[str, int] = {}
    for rate in product.rates:
        if rate.identity.rate_uid is not None:
            rate_uid_counts[rate.identity.rate_uid] = rate_uid_counts.get(rate.identity.rate_uid, 0) + 1
    for rate in product.rates:
        if rate.identity.rate_uid is None or not _DIGEST_ID.fullmatch(rate.identity.rate_uid):
            raise ValueError("invalid rate_uid")
        if rate.identity.rate_uid != rate_uid(identity.product_uid, rate.semantic_tier):
            raise ValueError("rate_uid does not match its canonical derivation")
        if rate.identity.product_uid != identity.product_uid:
            raise ValueError("rate identity belongs to another product")
        if (
            rate.identity.provider_uid != identity.provider_uid
            or rate.identity.provider_identity_status is not identity.provider_identity_status
            or rate.identity.product_id != identity.product_id
            or rate.identity.legacy_aliases != identity.legacy_aliases
        ):
            raise ValueError("rate identity disagrees with its product identity")
        if rate.identity.rate_identity_status not in {
            IdentityStatus.CONFIRMED,
            IdentityStatus.AMBIGUOUS,
        }:
            raise ValueError("rate identity status must be confirmed or ambiguous")
        if rate_uid_counts[rate.identity.rate_uid] > 1 and (
            rate.identity.rate_identity_status is not IdentityStatus.AMBIGUOUS
            or rate.exact_alert_eligible
        ):
            raise ValueError("duplicate semantic rates must be ambiguous")
        if rate.identity.rate_identity_status is IdentityStatus.AMBIGUOUS and rate.exact_alert_eligible:
            raise ValueError("ambiguous rates cannot power exact alerts")
        _validate_rate(rate.advertised)
        if rate.advertised.metric not in _PRODUCT_INTEREST_METRICS:
            raise ValueError("product advertised slot requires a product-interest metric")
        if rate.comparison is not None:
            _validate_rate(rate.comparison)
            if rate.comparison.metric is not RateMetric.COMPARISON_INTEREST:
                raise ValueError("product comparison slot requires comparison_interest")
            if not set(rate.comparison.evidence_ids).issubset(evidence_ids):
                raise ValueError("comparison rate references unknown evidence")
        if not set(rate.advertised.evidence_ids).issubset(evidence_ids):
            raise ValueError("rate references unknown evidence")
    for fee in product.fees:
        if not _DIGEST_ID.fullmatch(fee.fee_uid):
            raise ValueError("invalid fee_uid")
        if fee.fee_uid != fee_uid_from_semantics(identity.product_uid, fee.semantic_fee):
            raise ValueError("fee_uid does not match its canonical derivation")
        if fee.rate is not None:
            _validate_fee_rate(fee.rate)
            if not set(fee.rate.evidence_ids).issubset(evidence_ids):
                raise ValueError("fee rate references unknown evidence")
        amounts = []
        for value in (fee.fixed_amount, fee.minimum_amount, fee.maximum_amount):
            if value is None:
                amounts.append(None)
                continue
            try:
                amount = Decimal(value)
            except InvalidOperation as error:
                raise ValueError("fee amount must be a decimal string") from error
            if not amount.is_finite() or amount < 0:
                raise ValueError("fee amount must be finite and non-negative")
            amounts.append(amount)
        _, minimum, maximum = amounts
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError("fee minimum amount cannot exceed maximum amount")
        has_pricing = any(value is not None for value in amounts) or fee.rate is not None
        pricing_methods = sum(
            (
                fee.fixed_amount is not None,
                fee.minimum_amount is not None or fee.maximum_amount is not None,
                fee.rate is not None,
            )
        )
        if pricing_methods > 1:
            raise ValueError("fee contains contradictory pricing methods")
        if fee.disclosure_status is DisclosureStatus.COMPLETE and not has_pricing:
            raise ValueError("complete fee disclosure requires published pricing")
        if fee.disclosure_status is DisclosureStatus.UNKNOWN and has_pricing:
            raise ValueError("unknown fee disclosure cannot carry settled pricing")
        if (
            fee.disclosure_status is DisclosureStatus.COMPLETE
            and fee.currency is None
            and any(value is not None for value in amounts)
        ):
            raise ValueError("complete monetary fee disclosure requires a currency")
        if not set(fee.evidence_ids).issubset(evidence_ids):
            raise ValueError("fee references unknown evidence")
