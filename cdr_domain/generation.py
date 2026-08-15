"""Deterministic, local-only candidate generation for dormant payload v3."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any

from cdr_atomic import ImmutablePathError, atomic_write_bytes

from .capabilities import CoreCapability, build_core_capability, deterministic_gzip
from .contract_validation import (
    generation_manifest_digest,
    validate_contract,
    validate_coverage_v2,
    validate_generation_manifest,
)
from .models import (
    Availability,
    CanonicalProduct,
    ClassificationStatus,
    PricingStatus,
)
from .serialize import canonical_json_bytes, to_primitive
from .time import parse_rfc3339
from .validate import validate_canonical_product


_PROVIDER_UID = re.compile(r"^provider(?:-fallback)?:v1:[0-9a-f]{64}$")
_PROVIDER_STATES = {"complete", "empty", "partial", "failed", "not_attempted"}
_REGISTER_STATES = {"complete", "failed", "not_attempted"}
FAILURE_STAGES = ("after_core_write", "after_manifest_write", "before_commit")
FailureHook = Callable[[str], None]


def _frozen_mapping(value: Mapping[str, Any], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    if any(not isinstance(key, str) or not key for key in value):
        raise TypeError(f"{label} keys must be non-empty strings")
    return MappingProxyType(dict(sorted(value.items())))


@dataclass(frozen=True)
class GenerationInputs:
    """Hash-bound generation and exact run-coverage inputs."""

    observation_date: str
    observed_at: str
    observation_state: str
    generation_revision: int
    normalization_version: str
    producer_commit: str
    prior_ledger_digest: str | None
    ledger_event_digest: str
    provider_states: Mapping[str, str]
    products_discovered_by_provider: Mapping[str, int]
    register_source_states: Mapping[str, str]
    failure_records_by_provider: Mapping[str, int]
    corrupt_failure_records: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider_states",
            _frozen_mapping(self.provider_states, "provider_states"),
        )
        object.__setattr__(
            self,
            "products_discovered_by_provider",
            _frozen_mapping(
                self.products_discovered_by_provider,
                "products_discovered_by_provider",
            ),
        )
        object.__setattr__(
            self,
            "register_source_states",
            _frozen_mapping(self.register_source_states, "register_source_states"),
        )
        object.__setattr__(
            self,
            "failure_records_by_provider",
            _frozen_mapping(
                self.failure_records_by_provider,
                "failure_records_by_provider",
            ),
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "GenerationInputs":
        if not isinstance(value, Mapping):
            raise TypeError("generation metadata must be a mapping")
        required = {
            "observation_date",
            "observed_at",
            "observation_state",
            "generation_revision",
            "normalization_version",
            "producer_commit",
            "prior_ledger_digest",
            "ledger_event_digest",
            "provider_states",
            "products_discovered_by_provider",
            "register_source_states",
            "failure_records_by_provider",
        }
        optional = {"corrupt_failure_records"}
        missing = required - set(value)
        unexpected = set(value) - required - optional
        if missing or unexpected:
            raise ValueError(
                "generation metadata keys disagree with the local candidate contract: "
                f"missing={sorted(missing)} unexpected={sorted(unexpected)}"
            )
        return cls(**dict(value))


@dataclass(frozen=True)
class GenerationCandidate:
    """Immutable exact bytes for a validated, unpublished generation."""

    generation_id: str
    generation_digest: str
    manifest_sha256: str
    manifest_bytes: bytes
    core: CoreCapability

    @property
    def manifest_filename(self) -> str:
        return f"{self.manifest_sha256}.json"

    def manifest(self) -> dict[str, Any]:
        return json.loads(self.manifest_bytes.decode("utf-8"))


def _validate_inputs(inputs: GenerationInputs) -> None:
    try:
        observation_date = date.fromisoformat(inputs.observation_date)
    except (TypeError, ValueError) as error:
        raise ValueError("observation_date must be a calendar date") from error
    observed_at = parse_rfc3339(inputs.observed_at)
    if observed_at.date() != observation_date:
        raise ValueError("observed_at local date must match observation_date")
    if inputs.observation_state not in {"complete", "partial"}:
        raise ValueError("observation_state must be complete or partial")
    if (
        isinstance(inputs.generation_revision, bool)
        or not isinstance(inputs.generation_revision, int)
        or not 1 <= inputs.generation_revision <= 9999
    ):
        raise ValueError("generation_revision must be an integer from 1 to 9999")
    if not inputs.register_source_states:
        raise ValueError("at least one configured register source is required")
    if not inputs.provider_states:
        raise ValueError("at least one registered provider is required")
    invalid_provider_states = set(inputs.provider_states.values()) - _PROVIDER_STATES
    invalid_register_states = (
        set(inputs.register_source_states.values()) - _REGISTER_STATES
    )
    if invalid_provider_states or invalid_register_states:
        raise ValueError("run coverage contains an unsupported state")
    if any(not _PROVIDER_UID.fullmatch(key) for key in inputs.provider_states):
        raise ValueError("provider state keys must be canonical provider UIDs")


def _validate_provider_population(
    products: tuple[CanonicalProduct, ...],
    inputs: GenerationInputs,
) -> None:
    product_providers = Counter(product.identity.provider_uid for product in products)
    if set(inputs.products_discovered_by_provider) != set(inputs.provider_states):
        raise ValueError(
            "discovered-product counts must name every registered provider"
        )
    if any(
        isinstance(count, bool) or not isinstance(count, int) or count < 0
        for count in inputs.products_discovered_by_provider.values()
    ):
        raise ValueError("discovered-product counts must be non-negative integers")
    if dict(product_providers) != {
        provider_uid: count
        for provider_uid, count in inputs.products_discovered_by_provider.items()
        if count
    }:
        raise ValueError(
            "canonical entities do not reconcile to discovered-product counts"
        )
    missing = set(product_providers) - set(inputs.provider_states)
    if missing:
        raise ValueError(
            "canonical products reference providers absent from run coverage"
        )
    for provider_uid, state in inputs.provider_states.items():
        product_count = product_providers[provider_uid]
        if state == "complete" and product_count == 0:
            raise ValueError(
                "complete providers require at least one canonical product"
            )
        if state in {"empty", "failed", "not_attempted"} and product_count:
            raise ValueError(f"{state} providers cannot carry canonical products")
    failed = {
        provider_uid
        for provider_uid, state in inputs.provider_states.items()
        if state == "failed"
    }
    failure_keys = set(inputs.failure_records_by_provider)
    if failure_keys != failed:
        raise ValueError("failure records must identify every and only failed provider")
    if any(
        isinstance(count, bool) or not isinstance(count, int) or count < 1
        for count in inputs.failure_records_by_provider.values()
    ):
        raise ValueError("failure record counts must be positive integers")


def _exclusion_reason(product: CanonicalProduct) -> str:
    classification = product.classification
    if classification.classification_status is not ClassificationStatus.CONFIRMED:
        return classification.quarantine_reason or (
            "classification_" + classification.classification_status.value
        )
    if product.evidence.availability is not Availability.PUBLIC:
        return "availability_" + product.evidence.availability.value
    return "unpriced"


def _coverage_and_core(
    products: tuple[CanonicalProduct, ...],
    inputs: GenerationInputs,
) -> tuple[dict[str, Any], tuple[CanonicalProduct, ...]]:
    eligible = tuple(
        product
        for product in products
        if product.classification.classification_status
        is ClassificationStatus.CONFIRMED
        and product.evidence.availability is Availability.PUBLIC
        and product.rates
    )
    eligible_uids = {product.identity.product_uid for product in eligible}
    exclusions = Counter(
        _exclusion_reason(product)
        for product in products
        if product.identity.product_uid not in eligible_uids
    )
    provider_counts = Counter(inputs.provider_states.values())
    register_counts = Counter(inputs.register_source_states.values())
    failure_records = sum(inputs.failure_records_by_provider.values())
    coverage = {
        "products_discovered": sum(inputs.products_discovered_by_provider.values()),
        "products_priced": sum(bool(product.rates) for product in products),
        "products_consumer_eligible": len(eligible),
        "rate_tiers_eligible": sum(len(product.rates) for product in eligible),
        "providers_registered": len(inputs.provider_states),
        "providers_attempted": len(inputs.provider_states)
        - provider_counts["not_attempted"],
        "providers_responded": sum(
            provider_counts[state] for state in ("complete", "empty", "partial")
        ),
        "providers_complete": provider_counts["complete"],
        "providers_empty": provider_counts["empty"],
        "providers_partial": provider_counts["partial"],
        "providers_failed": provider_counts["failed"],
        "providers_not_attempted": provider_counts["not_attempted"],
        "register_sources_attempted": len(inputs.register_source_states)
        - register_counts["not_attempted"],
        "register_sources_complete": register_counts["complete"],
        "register_provenance_complete": all(
            state == "complete" for state in inputs.register_source_states.values()
        ),
        "failure_records": failure_records,
        "failure_records_by_provider": dict(inputs.failure_records_by_provider),
        "corrupt_failure_records": inputs.corrupt_failure_records,
        "exclusions_by_reason": dict(sorted(exclusions.items())),
        "failure_provenance_complete": (
            inputs.corrupt_failure_records == 0
            and set(inputs.failure_records_by_provider)
            == {
                provider_uid
                for provider_uid, state in inputs.provider_states.items()
                if state == "failed"
            }
        ),
        "reconciliation_status": "reconciled",
    }
    validate_coverage_v2(coverage)
    return coverage, eligible


def build_generation_candidate(
    products: Iterable[CanonicalProduct],
    inputs: GenerationInputs,
) -> GenerationCandidate:
    """Build and validate an unpublished candidate without network access."""

    _validate_inputs(inputs)
    ordered = tuple(sorted(products, key=lambda item: item.identity.product_uid))
    seen: set[str] = set()
    observed_at = parse_rfc3339(inputs.observed_at)
    for product in ordered:
        validate_canonical_product(product)
        if product.identity.product_uid in seen:
            raise ValueError("generation inputs contain a duplicate product_uid")
        seen.add(product.identity.product_uid)
        if product.normalization_version != inputs.normalization_version:
            raise ValueError("product normalization version disagrees with generation")
        if product.rates and product.evidence.pricing_status in {
            PricingStatus.UNPRICED,
            PricingStatus.UNKNOWN,
        }:
            raise ValueError("visible rates contradict the product pricing status")
        if parse_rfc3339(product.evidence.observed_at) > observed_at:
            raise ValueError("product evidence cannot postdate its generation")
    validate_contract(
        "canonical-core-v3.schema.json",
        {
            "schema_version": 3,
            "normalization_version": inputs.normalization_version,
            "observation_date": inputs.observation_date,
            "products": [to_primitive(product) for product in ordered],
        },
    )
    _validate_provider_population(ordered, inputs)
    coverage, eligible = _coverage_and_core(ordered, inputs)
    core = build_core_capability(
        eligible,
        observation_date=inputs.observation_date,
        normalization_version=inputs.normalization_version,
    )
    manifest: dict[str, Any] = {
        "schema_version": 3,
        "generation_id": "",
        "generation_revision": inputs.generation_revision,
        "generation_digest": "",
        "observation_date": inputs.observation_date,
        "observed_at": inputs.observed_at,
        "observation_state": inputs.observation_state,
        "ledger_state": "finalized",
        "normalization_version": inputs.normalization_version,
        "producer_commit": inputs.producer_commit,
        "coverage": coverage,
        "prior_ledger_digest": inputs.prior_ledger_digest,
        "ledger_event_digest": inputs.ledger_event_digest,
        "capabilities": {"core": core.descriptor()},
    }
    digest = generation_manifest_digest(manifest)
    manifest["generation_digest"] = digest
    manifest["generation_id"] = (
        f"gen-{inputs.observation_date}-r{inputs.generation_revision:04d}-{digest[:12]}"
    )
    validate_generation_manifest(manifest, {"core": core.encoded_bytes})
    manifest_bytes = canonical_json_bytes(manifest)
    return GenerationCandidate(
        generation_id=manifest["generation_id"],
        generation_digest=digest,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        manifest_bytes=manifest_bytes,
        core=core,
    )


def _verify_existing(target: Path, candidate: GenerationCandidate) -> None:
    expected = {
        candidate.core.filename: candidate.core.encoded_bytes,
        candidate.manifest_filename: candidate.manifest_bytes,
    }
    if target.is_symlink() or not target.is_dir():
        raise ImmutablePathError(f"candidate target is not a real directory: {target}")
    entries = {entry.name: entry for entry in target.iterdir()}
    if set(entries) != set(expected):
        raise ImmutablePathError(
            f"candidate directory has unexpected contents: {target}"
        )
    for name, payload in expected.items():
        path = entries[name]
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != len(payload)
            or path.read_bytes() != payload
        ):
            raise ImmutablePathError(
                f"candidate artifact differs from expected bytes: {path}"
            )


def _validate_candidate(candidate: GenerationCandidate) -> None:
    if not isinstance(candidate, GenerationCandidate):
        raise TypeError("candidate must be a GenerationCandidate")
    if (
        hashlib.sha256(candidate.core.encoded_bytes).hexdigest()
        != candidate.core.sha256
    ):
        raise ValueError("candidate core SHA-256 does not match its exact bytes")
    if deterministic_gzip(candidate.core.decoded_bytes) != candidate.core.encoded_bytes:
        raise ValueError("candidate core decoded and encoded bytes disagree")
    try:
        manifest = candidate.manifest()
        canonical_manifest = canonical_json_bytes(manifest)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("candidate manifest must be canonical UTF-8 JSON") from error
    if canonical_manifest != candidate.manifest_bytes:
        raise ValueError("candidate manifest bytes are not canonical or unambiguous")
    if (
        hashlib.sha256(candidate.manifest_bytes).hexdigest()
        != candidate.manifest_sha256
    ):
        raise ValueError("candidate manifest SHA-256 does not match its exact bytes")
    validate_generation_manifest(manifest, {"core": candidate.core.encoded_bytes})
    if manifest["capabilities"]["core"] != candidate.core.descriptor():
        raise ValueError("candidate core descriptor disagrees with its exact bytes")
    if manifest["generation_id"] != candidate.generation_id:
        raise ValueError("candidate generation_id disagrees with its manifest")
    if manifest["generation_digest"] != candidate.generation_digest:
        raise ValueError("candidate generation digest disagrees with its manifest")


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_generation_candidate(
    candidate: GenerationCandidate,
    output_root: Path,
    *,
    failure_hook: FailureHook | None = None,
) -> Path:
    """Atomically install a create-once local candidate directory."""

    _validate_candidate(candidate)
    requested_root = output_root.expanduser()
    if requested_root.is_symlink():
        raise ValueError("candidate output root cannot be a symbolic link")
    root = requested_root.resolve()
    if root.exists() and not root.is_dir():
        raise ValueError("candidate output root must be a real directory")
    root.mkdir(parents=True, exist_ok=True)
    target = root / candidate.generation_id
    if target.is_symlink() or target.exists():
        _verify_existing(target, candidate)
        return target

    hook = failure_hook or (lambda _stage: None)
    with tempfile.TemporaryDirectory(
        prefix=f".{candidate.generation_id}.tmp-",
        dir=root,
    ) as temporary:
        staging = Path(temporary)
        atomic_write_bytes(
            staging / candidate.core.filename,
            candidate.core.encoded_bytes,
            create_once=True,
        )
        hook("after_core_write")
        atomic_write_bytes(
            staging / candidate.manifest_filename,
            candidate.manifest_bytes,
            create_once=True,
        )
        hook("after_manifest_write")
        hook("before_commit")
        _verify_existing(staging, candidate)
        try:
            os.replace(staging, target)
        except OSError:
            if not target.exists():
                raise
            _verify_existing(target, candidate)
        _verify_existing(target, candidate)
        _fsync_directory(root)
    return target


__all__ = [
    "FAILURE_STAGES",
    "GenerationCandidate",
    "GenerationInputs",
    "build_generation_candidate",
    "write_generation_candidate",
]
