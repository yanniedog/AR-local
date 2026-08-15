"""Typed canonical entities shared by every future v3 producer capability."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple


class IdentityStatus(str, Enum):
    CONFIRMED = "confirmed"
    FALLBACK = "fallback"
    AMBIGUOUS = "ambiguous"


class ProductKind(str, Enum):
    MORTGAGE = "mortgage"
    SAVINGS_ACCOUNT = "savings_account"
    TRANSACTION_ACCOUNT = "transaction_account"
    MORTGAGE_OFFSET = "mortgage_offset"
    TERM_DEPOSIT = "term_deposit"
    OTHER = "other"
    UNKNOWN = "unknown"


class ConsumerSection(str, Enum):
    MORTGAGE = "mortgage"
    SAVINGS = "savings"
    TERM_DEPOSIT = "term_deposit"


class ClassificationStatus(str, Enum):
    CONFIRMED = "confirmed"
    QUARANTINED = "quarantined"
    UNKNOWN = "unknown"


class RateUnit(str, Enum):
    FRACTION_PER_ANNUM = "fraction_per_annum"
    PERCENTAGE_POINTS = "percentage_points"
    BASIS_POINTS = "basis_points"


class FeeRateUnit(str, Enum):
    FRACTION_OF_AMOUNT = "fraction_of_amount"


class RateMetric(str, Enum):
    ADVERTISED_INTEREST = "advertised_interest"
    COMPARISON_INTEREST = "comparison_interest"
    BASE_INTEREST = "base_interest"
    CONDITIONAL_INTEREST = "conditional_interest"
    INTRODUCTORY_INTEREST = "introductory_interest"
    PUBLISHED_REVERSION_INTEREST = "published_reversion_interest"
    RBA_CASH_RATE = "rba_cash_rate"
    RATE_CHANGE = "rate_change"
    CATALOGUE_GAP = "catalogue_gap"


class RateBasis(str, Enum):
    ADVERTISED = "advertised"
    COMPARISON = "comparison"
    BASE = "base"
    CONDITIONAL = "conditional"
    INTRODUCTORY = "introductory"
    PUBLISHED_REVERSION = "published_reversion"
    OFFICIAL = "official"
    OBSERVED = "observed"


class EvidenceStatus(str, Enum):
    VERIFIED = "verified"
    PUBLISHED = "published"
    OBSERVED = "observed"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class Availability(str, Enum):
    PUBLIC = "public"
    RESTRICTED = "restricted"
    BUSINESS = "business"
    LINKED = "linked"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class DisclosureStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class PricingStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNPRICED = "unpriced"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EvidenceRef:
    evidence_id: str
    source_kind: str
    source_path: str
    source_locator: str
    source_sha256: str
    source_record_sha256: str
    observed_at: str
    effective_date: Optional[str] = None
    source_updated_at: Optional[str] = None
    source_url: Optional[str] = None


@dataclass(frozen=True)
class CanonicalIdentity:
    provider_uid: str
    provider_identity_status: IdentityStatus
    product_uid: str
    product_id: str
    rate_uid: Optional[str] = None
    rate_identity_status: Optional[IdentityStatus] = None
    legacy_aliases: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ProductClassification:
    product_kind: ProductKind
    consumer_section: Optional[ConsumerSection]
    classification_status: ClassificationStatus
    classification_basis: Tuple[str, ...]
    classification_version: str
    quarantine_reason: Optional[str] = None


@dataclass(frozen=True)
class TypedRate:
    value: str
    unit: RateUnit
    metric: RateMetric
    basis: RateBasis
    evidence_status: EvidenceStatus
    evidence_ids: Tuple[str, ...]


@dataclass(frozen=True)
class TypedFeeRate:
    value: str
    unit: FeeRateUnit
    evidence_status: EvidenceStatus
    evidence_ids: Tuple[str, ...]


@dataclass(frozen=True)
class CanonicalRate:
    identity: CanonicalIdentity
    advertised: TypedRate
    comparison: Optional[TypedRate]
    semantic_tier: dict[str, object]
    exact_alert_eligible: bool
    source_index: int


@dataclass(frozen=True)
class CanonicalFee:
    fee_uid: str
    semantic_fee: dict[str, object]
    disclosure_status: DisclosureStatus
    currency: Optional[str]
    fixed_amount: Optional[str]
    minimum_amount: Optional[str]
    maximum_amount: Optional[str]
    rate: Optional[TypedFeeRate]
    condition: Optional[str]
    evidence_ids: Tuple[str, ...]


@dataclass(frozen=True)
class ProductEvidence:
    availability: Availability
    fee_disclosure_status: DisclosureStatus
    eligibility_disclosure_status: DisclosureStatus
    pricing_status: PricingStatus
    evidence_ids: Tuple[str, ...]
    observed_at: str
    effective_date: Optional[str]
    source_updated_at: Optional[str]
    source_urls: Tuple[str, ...]


@dataclass(frozen=True)
class CanonicalProduct:
    schema_version: int
    normalization_version: str
    identity: CanonicalIdentity
    display_name: str
    provider_display_name: str
    classification: ProductClassification
    evidence: ProductEvidence
    rates: Tuple[CanonicalRate, ...] = field(default_factory=tuple)
    fees: Tuple[CanonicalFee, ...] = field(default_factory=tuple)
    evidence_refs: Tuple[EvidenceRef, ...] = field(default_factory=tuple)
