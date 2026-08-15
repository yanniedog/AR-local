"""Runtime validation for the dormant v3 producer boundary."""

from __future__ import annotations

import hashlib
import json
import re
import zlib
from datetime import date
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from .time import is_rfc3339
from .deserialize import canonical_product_from_primitive
from .models import Availability, ClassificationStatus
from .validate import validate_canonical_product


CONTRACT_ROOT = Path(__file__).resolve().parents[1] / "contracts" / "v3"
SCHEMA_FILES = (
    "asset-descriptor-v3.schema.json",
    "canonical-core-v3.schema.json",
    "coverage-v2.schema.json",
    "generation-manifest-v3.schema.json",
    "generation-pointer-v3.schema.json",
)
RELEASE_URL_PREFIX = "https://github.com/yanniedog/AR-local/releases/download/"
GENERATION_ID = re.compile(
    r"^gen-(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})-r(?P<revision>[0-9]{4})-"
    r"(?P<digest>[0-9a-f]{12})$"
)
SUPPORTED_CAPABILITY_SCHEMAS = {
    "core": "https://australianrates.app/contracts/v3/canonical-core-v3.schema.json",
}
FORMAT_CHECKER = FormatChecker()


class DuplicateJsonKeyError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise DuplicateJsonKeyError(f"duplicate JSON object key: {key}")
        value[key] = child
    return value


def _strict_json_bytes(supplied: bytes, label: str) -> object:
    try:
        return json.loads(
            supplied.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (UnicodeDecodeError, json.JSONDecodeError, DuplicateJsonKeyError) as error:
        raise ValueError(f"{label} bytes are not unambiguous UTF-8 JSON") from error


@FORMAT_CHECKER.checks("date")
def _is_calendar_date(value: object) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


@FORMAT_CHECKER.checks("date-time")
def _is_rfc3339_datetime(value: object) -> bool:
    return is_rfc3339(value)


@FORMAT_CHECKER.checks("uri")
def _is_absolute_uri(value: object) -> bool:
    if not isinstance(value, str) or any(character.isspace() for character in value):
        return False
    parsed = urlparse(value)
    return bool(parsed.scheme and (parsed.netloc or parsed.scheme not in {"http", "https"}))


def load_schemas(root: Path = CONTRACT_ROOT) -> dict[str, dict[str, Any]]:
    schemas = {}
    for name in SCHEMA_FILES:
        schemas[name] = json.loads((root / name).read_text(encoding="utf-8"))
    return schemas


def contract_sha256(root: Path = CONTRACT_ROOT) -> str:
    schemas = load_schemas(root)
    canonical = json.dumps(
        {name: schemas[name] for name in sorted(schemas)},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def generation_manifest_digest(manifest: Mapping[str, Any]) -> str:
    """Digest a manifest without its derived ID and digest fields."""

    material = {
        key: value
        for key, value in manifest.items()
        if key not in {"generation_id", "generation_digest"}
    }
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _generation_parts(generation_id: str) -> tuple[str, int, str]:
    match = GENERATION_ID.fullmatch(generation_id)
    if not match:
        raise ValueError("invalid generation ID")
    try:
        date.fromisoformat(match.group("date"))
    except ValueError as error:
        raise ValueError("generation ID contains an invalid calendar date") from error
    return match.group("date"), int(match.group("revision")), match.group("digest")


def _validate_release_url(url: str, digest: str, label: str) -> None:
    parsed = urlparse(url)
    if parsed.username or parsed.password:
        raise ValueError(f"{label} URL cannot contain credentials")
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.port not in (None, 443)
        or not parsed.path.startswith("/yanniedog/AR-local/releases/download/")
    ):
        raise ValueError(f"{label} URL must use the canonical AR-local release origin")
    if digest not in parsed.path:
        raise ValueError(f"{label} URL must be content-addressed by its SHA-256")


def _registry(schemas: Mapping[str, Mapping[str, Any]]) -> Registry:
    registry = Registry()
    for schema in schemas.values():
        registry = registry.with_resource(
            str(schema["$id"]), Resource.from_contents(schema)
        )
    return registry


def validate_contract(
    schema_name: str,
    instance: object,
    *,
    root: Path = CONTRACT_ROOT,
) -> None:
    schemas = load_schemas(root)
    try:
        schema = schemas[schema_name]
    except KeyError as error:
        raise ValueError(f"unknown v3 schema: {schema_name}") from error
    validator = Draft202012Validator(
        schema,
        registry=_registry(schemas),
        format_checker=FORMAT_CHECKER,
    )
    errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.path))
    if errors:
        error = errors[0]
        location = "/".join(str(part) for part in error.absolute_path) or "<root>"
        raise ValueError(f"{schema_name} validation failed at {location}: {error.message}")


def validate_coverage_v2(coverage: Mapping[str, Any]) -> None:
    validate_contract("coverage-v2.schema.json", coverage)
    complete = coverage["providers_complete"]
    empty = coverage["providers_empty"]
    partial = coverage["providers_partial"]
    failed = coverage["providers_failed"]
    not_attempted = coverage["providers_not_attempted"]
    responded = complete + empty + partial
    attempted = responded + failed
    registered = attempted + not_attempted
    equations = {
        "providers_responded": responded,
        "providers_attempted": attempted,
        "providers_registered": registered,
    }
    for field, expected in equations.items():
        if coverage[field] != expected:
            raise ValueError(
                f"coverage reconciliation failed: {field}={coverage[field]} expected {expected}"
            )

    discovered = coverage["products_discovered"]
    priced = coverage["products_priced"]
    eligible = coverage["products_consumer_eligible"]
    if not 0 <= eligible <= priced <= discovered:
        raise ValueError(
            "coverage reconciliation failed: consumer-eligible <= priced <= discovered"
        )
    excluded = sum(coverage["exclusions_by_reason"].values())
    if eligible + excluded != discovered:
        raise ValueError(
            "coverage reconciliation failed: eligible products plus exclusions "
            "must equal discovered products"
        )

    status = coverage["reconciliation_status"]
    if status == "reconciled":
        if not coverage["failure_provenance_complete"]:
            raise ValueError("reconciled coverage requires complete failure provenance")
        if coverage["corrupt_failure_records"]:
            raise ValueError("reconciled coverage cannot contain corrupt failure records")
    failure_records_by_provider = coverage["failure_records_by_provider"]
    if len(failure_records_by_provider) != failed:
        raise ValueError("each failed provider requires attributable failure evidence")
    if sum(failure_records_by_provider.values()) != coverage["failure_records"]:
        raise ValueError("provider-attributed failure evidence must reconcile to failure_records")
    register_attempted = coverage["register_sources_attempted"]
    register_complete = coverage["register_sources_complete"]
    if register_complete > register_attempted:
        raise ValueError("complete register sources cannot exceed attempted sources")
    if coverage["register_provenance_complete"] and (
        register_attempted == 0 or register_complete != register_attempted
    ):
        raise ValueError("complete register provenance requires every configured source")


def validate_asset_descriptor(descriptor: Mapping[str, Any]) -> None:
    validate_contract("asset-descriptor-v3.schema.json", descriptor)
    expected_schema = SUPPORTED_CAPABILITY_SCHEMAS.get(descriptor["capability"])
    if expected_schema is None:
        raise ValueError(f"unsupported v3 capability: {descriptor['capability']}")
    if descriptor["schema_id"] != expected_schema:
        raise ValueError("capability schema_id does not match the producer contract")
    if descriptor["capability"] == "core" and (
        descriptor["media_type"] != "application/json"
        or descriptor["cohort"] != "confirmed-consumer-products"
    ):
        raise ValueError("core descriptor media type and cohort are fixed by contract")
    _validate_release_url(str(descriptor["url"]), descriptor["sha256"], "asset")
    if (
        descriptor["encoding"] == "identity"
        and descriptor["compressed_bytes"] != descriptor["uncompressed_bytes"]
    ):
        raise ValueError("identity-encoded asset byte counts must match")


def _decode_asset_bytes(descriptor: Mapping[str, Any], supplied: bytes) -> bytes:
    if not isinstance(supplied, bytes):
        raise ValueError("capability must be supplied as exact bytes")
    if len(supplied) != descriptor["compressed_bytes"]:
        raise ValueError("capability compressed byte count does not match descriptor")
    if hashlib.sha256(supplied).hexdigest() != descriptor["sha256"]:
        raise ValueError("capability byte SHA-256 does not match descriptor")
    if descriptor["encoding"] == "identity":
        decoded = supplied
    else:
        limit = int(descriptor["uncompressed_bytes"])
        inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            decoded = inflater.decompress(supplied, limit + 1)
        except zlib.error as error:
            raise ValueError("capability gzip stream is corrupt") from error
        if len(decoded) > limit or inflater.unconsumed_tail:
            raise ValueError("capability exceeds its declared inflated byte count")
        try:
            decoded += inflater.flush(limit - len(decoded) + 1)
        except zlib.error as error:
            raise ValueError("capability gzip stream is corrupt") from error
        if not inflater.eof:
            raise ValueError("capability gzip stream is truncated")
        if inflater.unused_data:
            raise ValueError("capability gzip stream contains trailing data")
    if len(decoded) != descriptor["uncompressed_bytes"]:
        raise ValueError("capability inflated byte count does not match descriptor")
    return decoded


def _validate_core_capability(
    decoded: bytes,
    manifest: Mapping[str, Any],
) -> None:
    core = _strict_json_bytes(decoded, "core capability")
    if not isinstance(core, Mapping):
        raise ValueError("core capability must be a JSON object")
    validate_contract("canonical-core-v3.schema.json", core)
    if core["observation_date"] != manifest["observation_date"]:
        raise ValueError("core observation_date disagrees with generation manifest")
    if core["normalization_version"] != manifest["normalization_version"]:
        raise ValueError("core normalization_version disagrees with generation manifest")
    products = core["products"]
    coverage = manifest["coverage"]
    if len(products) != coverage["products_consumer_eligible"]:
        raise ValueError("core product count disagrees with consumer-eligible coverage")
    rate_count = 0
    product_uids: set[str] = set()
    for value in products:
        product = canonical_product_from_primitive(value)
        validate_canonical_product(product)
        if product.identity.product_uid in product_uids:
            raise ValueError("core contains a duplicate product_uid")
        product_uids.add(product.identity.product_uid)
        if (
            product.classification.classification_status
            is not ClassificationStatus.CONFIRMED
            or product.evidence.availability is not Availability.PUBLIC
        ):
            raise ValueError("core contains a product outside its confirmed-public cohort")
        if not product.rates:
            raise ValueError("core contains a consumer product without a visible rate tier")
        rate_count += len(product.rates)
    if rate_count != coverage["rate_tiers_eligible"]:
        raise ValueError("core rate-tier count disagrees with eligible coverage")


def validate_generation_manifest(
    manifest: Mapping[str, Any],
    capability_bytes: Mapping[str, bytes],
) -> None:
    validate_contract("generation-manifest-v3.schema.json", manifest)
    validate_coverage_v2(manifest["coverage"])
    coverage = manifest["coverage"]
    if coverage["reconciliation_status"] != "reconciled":
        raise ValueError("generation manifest requires reconciled coverage")
    if manifest["observation_state"] == "complete" and any(
        coverage[field]
        for field in (
            "providers_partial",
            "providers_failed",
            "providers_not_attempted",
            "corrupt_failure_records",
        )
    ):
        raise ValueError("complete observation contains incomplete provider states")
    if (
        manifest["observation_state"] == "complete"
        and not coverage["register_provenance_complete"]
    ):
        raise ValueError("complete observation requires complete register provenance")
    generation_date, revision, digest_prefix = _generation_parts(manifest["generation_id"])
    if generation_date != manifest["observation_date"]:
        raise ValueError("generation ID date does not match observation_date")
    if revision != manifest["generation_revision"]:
        raise ValueError("generation ID revision does not match generation_revision")
    expected_digest = generation_manifest_digest(manifest)
    if manifest["generation_digest"] != expected_digest:
        raise ValueError("generation digest does not match canonical manifest content")
    if digest_prefix != expected_digest[:12]:
        raise ValueError("generation ID digest suffix does not match generation digest")
    if set(capability_bytes) != set(manifest["capabilities"]):
        raise ValueError("generation capability bytes must exactly match manifest capabilities")
    for capability, descriptor in manifest["capabilities"].items():
        validate_asset_descriptor(descriptor)
        decoded = _decode_asset_bytes(descriptor, capability_bytes[capability])
        if capability == "core":
            _validate_core_capability(decoded, manifest)


def _pointer_order(head: Mapping[str, Any]) -> tuple[date, int]:
    return date.fromisoformat(str(head["observation_date"])), int(
        head["generation_revision"]
    )


def validate_generation_pointer(
    pointer: Mapping[str, Any],
    manifest_bytes_by_generation: Mapping[str, bytes],
    capability_bytes_by_generation: Mapping[str, Mapping[str, bytes]],
    *,
    previous_pointer_bytes: bytes | None = None,
    expected_previous_pointer_sha256: str | None = None,
) -> None:
    """Validate a pointer, its exact manifest bytes, and an optional CAS transition."""

    validate_contract("generation-pointer-v3.schema.json", pointer)
    if pointer["contract_sha256"] != contract_sha256():
        raise ValueError("generation pointer contract SHA does not match producer schemas")
    observation = pointer["latest_observation"]
    complete = pointer["latest_complete"]
    for label, head in (("latest observation", observation), ("latest complete", complete)):
        generation_date, revision, digest_prefix = _generation_parts(head["generation_id"])
        if generation_date != head["observation_date"]:
            raise ValueError(f"{label} generation date does not match observation date")
        if revision != head["generation_revision"]:
            raise ValueError(f"{label} generation revision does not match its ID")
        if digest_prefix != head["generation_digest"][:12]:
            raise ValueError(f"{label} generation digest does not match its ID")
        _validate_release_url(
            str(head["manifest_url"]), head["manifest_sha256"], f"{label} manifest"
        )
        try:
            manifest_bytes = manifest_bytes_by_generation[head["generation_id"]]
        except KeyError as error:
            raise ValueError(f"{label} manifest bytes are required") from error
        if not isinstance(manifest_bytes, bytes):
            raise ValueError(f"{label} manifest must be supplied as exact bytes")
        if hashlib.sha256(manifest_bytes).hexdigest() != head["manifest_sha256"]:
            raise ValueError(f"{label} manifest byte SHA-256 does not match its head")
        manifest = _strict_json_bytes(manifest_bytes, f"{label} manifest")
        if not isinstance(manifest, Mapping):
            raise ValueError(f"{label} manifest must be a JSON object")
        try:
            capability_bytes = capability_bytes_by_generation[head["generation_id"]]
        except KeyError as error:
            raise ValueError(f"{label} capability bytes are required") from error
        validate_generation_manifest(manifest, capability_bytes)
        for field in (
            "generation_id",
            "generation_revision",
            "generation_digest",
            "observation_date",
            "observation_state",
        ):
            if head[field] != manifest[field]:
                raise ValueError(f"{label} head disagrees with manifest field {field}")
    if date.fromisoformat(observation["observation_date"]) < date.fromisoformat(
        complete["observation_date"]
    ):
        raise ValueError("latest_observation cannot predate latest_complete")
    if (
        observation["observation_date"] == complete["observation_date"]
        and observation["generation_revision"] < complete["generation_revision"]
    ):
        raise ValueError("latest_observation cannot regress the same-date revision")
    if _pointer_order(observation) == _pointer_order(complete) and observation != complete:
        raise ValueError("equal-coordinate generation heads must be byte-equivalent")

    transition_args = (
        previous_pointer_bytes is not None,
        expected_previous_pointer_sha256 is not None,
    )
    if transition_args[0] != transition_args[1]:
        raise ValueError("pointer transition requires both prior bytes and expected CAS hash")
    if previous_pointer_bytes is None:
        return
    if not isinstance(previous_pointer_bytes, bytes):
        raise ValueError("prior pointer must be supplied as exact bytes")
    actual_previous_sha = hashlib.sha256(previous_pointer_bytes).hexdigest()
    if actual_previous_sha != expected_previous_pointer_sha256:
        raise ValueError("prior pointer CAS hash does not match the supplied bytes")
    previous = _strict_json_bytes(previous_pointer_bytes, "prior pointer")
    if not isinstance(previous, Mapping):
        raise ValueError("prior pointer must be a JSON object")
    validate_contract("generation-pointer-v3.schema.json", previous)
    if previous["contract_sha256"] != pointer["contract_sha256"]:
        raise ValueError("pointer transition cannot silently change the contract SHA")
    for field in ("latest_observation", "latest_complete"):
        candidate_order = _pointer_order(pointer[field])
        previous_order = _pointer_order(previous[field])
        if candidate_order < previous_order:
            raise ValueError(f"pointer transition regresses {field}")
        if candidate_order == previous_order and pointer[field] != previous[field]:
            raise ValueError(
                f"pointer transition replaces immutable {field} at an equal coordinate"
            )
