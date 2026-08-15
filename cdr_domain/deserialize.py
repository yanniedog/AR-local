"""Strict conversion of schema-validated JSON primitives into canonical entities."""

from __future__ import annotations

from typing import Any, Mapping

from .models import (
    Availability,
    CanonicalFee,
    CanonicalIdentity,
    CanonicalProduct,
    CanonicalRate,
    ClassificationStatus,
    ConsumerSection,
    DisclosureStatus,
    EvidenceRef,
    EvidenceStatus,
    FeeRateUnit,
    IdentityStatus,
    PricingStatus,
    ProductClassification,
    ProductEvidence,
    ProductKind,
    RateBasis,
    RateMetric,
    RateUnit,
    TypedFeeRate,
    TypedRate,
)
from .serialize import freeze_semantics


def _identity(value: Mapping[str, Any]) -> CanonicalIdentity:
    return CanonicalIdentity(
        provider_uid=str(value["provider_uid"]),
        provider_identity_status=IdentityStatus(value["provider_identity_status"]),
        product_uid=str(value["product_uid"]),
        product_id=str(value["product_id"]),
        rate_uid=str(value["rate_uid"]) if value["rate_uid"] is not None else None,
        rate_identity_status=(
            IdentityStatus(value["rate_identity_status"])
            if value["rate_identity_status"] is not None
            else None
        ),
        legacy_aliases=tuple(str(item) for item in value["legacy_aliases"]),
    )


def _typed_rate(value: Mapping[str, Any]) -> TypedRate:
    return TypedRate(
        value=str(value["value"]),
        unit=RateUnit(value["unit"]),
        metric=RateMetric(value["metric"]),
        basis=RateBasis(value["basis"]),
        evidence_status=EvidenceStatus(value["evidence_status"]),
        evidence_ids=tuple(str(item) for item in value["evidence_ids"]),
    )


def _typed_fee_rate(value: Mapping[str, Any]) -> TypedFeeRate:
    return TypedFeeRate(
        value=str(value["value"]),
        unit=FeeRateUnit(value["unit"]),
        evidence_status=EvidenceStatus(value["evidence_status"]),
        evidence_ids=tuple(str(item) for item in value["evidence_ids"]),
    )


def canonical_product_from_primitive(value: Mapping[str, Any]) -> CanonicalProduct:
    """Convert only after canonical-core-v3 JSON Schema validation has succeeded."""

    classification_value = value["classification"]
    evidence_value = value["evidence"]
    return CanonicalProduct(
        schema_version=int(value["schema_version"]),
        normalization_version=str(value["normalization_version"]),
        identity=_identity(value["identity"]),
        display_name=str(value["display_name"]),
        provider_display_name=str(value["provider_display_name"]),
        classification=ProductClassification(
            product_kind=ProductKind(classification_value["product_kind"]),
            consumer_section=(
                ConsumerSection(classification_value["consumer_section"])
                if classification_value["consumer_section"] is not None
                else None
            ),
            classification_status=ClassificationStatus(
                classification_value["classification_status"]
            ),
            classification_basis=tuple(
                str(item) for item in classification_value["classification_basis"]
            ),
            classification_version=str(classification_value["classification_version"]),
            quarantine_reason=(
                str(classification_value["quarantine_reason"])
                if classification_value["quarantine_reason"] is not None
                else None
            ),
        ),
        evidence=ProductEvidence(
            availability=Availability(evidence_value["availability"]),
            fee_disclosure_status=DisclosureStatus(
                evidence_value["fee_disclosure_status"]
            ),
            eligibility_disclosure_status=DisclosureStatus(
                evidence_value["eligibility_disclosure_status"]
            ),
            pricing_status=PricingStatus(evidence_value["pricing_status"]),
            evidence_ids=tuple(str(item) for item in evidence_value["evidence_ids"]),
            observed_at=str(evidence_value["observed_at"]),
            effective_date=evidence_value["effective_date"],
            effective_to=evidence_value["effective_to"],
            source_updated_at=evidence_value["source_updated_at"],
            source_urls=tuple(str(item) for item in evidence_value["source_urls"]),
        ),
        rates=tuple(
            CanonicalRate(
                identity=_identity(rate["identity"]),
                advertised=_typed_rate(rate["advertised"]),
                comparison=(
                    _typed_rate(rate["comparison"])
                    if rate["comparison"] is not None
                    else None
                ),
                semantic_tier=freeze_semantics(rate["semantic_tier"]),
                exact_alert_eligible=bool(rate["exact_alert_eligible"]),
                source_index=int(rate["source_index"]),
            )
            for rate in value["rates"]
        ),
        fees=tuple(
            CanonicalFee(
                fee_uid=str(fee["fee_uid"]),
                fee_identity_status=IdentityStatus(fee["fee_identity_status"]),
                semantic_fee=freeze_semantics(fee["semantic_fee"]),
                disclosure_status=DisclosureStatus(fee["disclosure_status"]),
                currency=fee["currency"],
                fixed_amount=fee["fixed_amount"],
                minimum_amount=fee["minimum_amount"],
                maximum_amount=fee["maximum_amount"],
                rate=(
                    _typed_fee_rate(fee["rate"]) if fee["rate"] is not None else None
                ),
                condition=fee["condition"],
                evidence_ids=tuple(str(item) for item in fee["evidence_ids"]),
            )
            for fee in value["fees"]
        ),
        evidence_refs=tuple(
            EvidenceRef(
                evidence_id=str(evidence["evidence_id"]),
                source_kind=str(evidence["source_kind"]),
                source_path=str(evidence["source_path"]),
                source_locator=str(evidence["source_locator"]),
                source_sha256=str(evidence["source_sha256"]),
                source_record_sha256=str(evidence["source_record_sha256"]),
                observed_at=str(evidence["observed_at"]),
                effective_date=evidence["effective_date"],
                effective_to=evidence["effective_to"],
                source_updated_at=evidence["source_updated_at"],
                source_url=evidence["source_url"],
            )
            for evidence in value["evidence_refs"]
        ),
    )
