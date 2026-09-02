"""Deterministic ProductAccountingV1 construction and reconciliation."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from cdr_contracts import (
    DATASETS,
    PROVIDER_UID_RE,
    canonical_json_bytes,
    product_uid as derive_product_uid,
)


SCHEMA_VERSION = 1
PROVIDER_STATES = ("complete", "partial", "empty", "failed", "not_attempted")
DISPOSITIONS = (
    "published_full",
    "published_core_only",
    "omitted_valid",
    "quarantined_invalid",
)
ISSUE_SCOPES = ("product", "provider", "register", "run")
ISSUE_PHASES = (
    "register_discovery",
    "products_index",
    "product_detail",
    "classification_detail",
    "holder",
    "normalization",
    "validation",
    "reconciliation",
    "finalization",
)
PRODUCT_ISSUE_CODES = (
    "detail_fetch_failed",
    "detail_invalid_json",
    "cdr_error",
    "identity_mismatch",
    "duplicate_conflict",
    "rate_invalid",
    "classification_unresolved",
    "no_current_rate",
    "product_closed",
    "unsupported_category",
    "field_omitted_invalid",
)
PROVIDER_ISSUE_CODES = (
    "products_index_failed",
    "pagination_incomplete",
    "holder_worker_crash",
    "provider_population_unknown",
)
REGISTER_ISSUE_CODES = ("register_failed",)
RUN_ISSUE_CODES = (
    "failure_record_corrupt",
    "failure_unattributed",
    "accounting_unreconciled",
)
ISSUE_CODES = PRODUCT_ISSUE_CODES + PROVIDER_ISSUE_CODES + REGISTER_ISSUE_CODES + RUN_ISSUE_CODES

_ASCII_SPACE = re.compile(r"[\t\n\v\f\r ]+")
_ACCOUNTING_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_PROVIDER_UID = PROVIDER_UID_RE
_PRODUCT_UID = re.compile(r"^[0-9a-f]{64}$")
_ISSUE_ID = re.compile(r"^issue:v1:[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_SECTION = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ABSOLUTE_REFERENCE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]{1,2}|[A-Za-z][A-Za-z0-9+.-]*://)")

_PROVIDER_INPUT_FIELDS = frozenset(
    {
        "provider_uid",
        "brand_name",
        "datasets",
        "state",
        "attempted",
        "population_known",
    }
)
_PROVIDER_COMPUTED_FIELDS = frozenset(
    {
        "affected_sections",
        "discovered_count",
        "published_full_count",
        "published_core_only_count",
        "omitted_valid_count",
        "quarantined_invalid_count",
        "issue_count",
        "issue_ids",
    }
)
_PRODUCT_INPUT_FIELDS = frozenset(
    {
        "provider_uid",
        "cdr_product_id",
        "dataset",
        "display_name",
        "legacy_product_key",
        "disposition",
        "reason_codes",
        "evidence_ids",
        "core_valid",
        "details_complete",
    }
)
_ISSUE_INPUT_FIELDS = frozenset(
    {
        "scope",
        "provider_uid",
        "product_uid",
        "affected_sections",
        "phase",
        "code",
        "http_status",
        "occurrence_count",
        "first_seen_at",
        "last_seen_at",
        "evidence_digest",
        "disposition",
        "public_safe",
    }
)


@lru_cache(maxsize=1)
def _schema_validator() -> Draft202012Validator:
    path = Path(__file__).resolve().parent / "contracts" / "product-accounting-v1.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _exact_fields(
    value: Mapping[str, Any],
    required: frozenset[str],
    label: str,
    optional: frozenset[str] = frozenset(),
) -> None:
    missing = sorted(required - value.keys())
    unexpected = sorted(value.keys() - required - optional)
    if missing or unexpected:
        raise ValueError(f"{label} fields invalid: missing={missing}, unexpected={unexpected}")


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value


def _integer(value: Any, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _text(value: Any, label: str, maximum: int, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    normalized = _ASCII_SPACE.sub(" ", unicodedata.normalize("NFC", value).strip())
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{label} must contain 1..{maximum} characters")
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise ValueError(f"{label} contains a control character")
    if _ABSOLUTE_REFERENCE.match(normalized):
        raise ValueError(f"{label} must not be an absolute path or URL")
    return normalized


def _opaque_text(
    value: Any, label: str, maximum: int, *, nullable: bool = False
) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    trimmed = value.strip()
    if not trimmed or len(trimmed) > maximum:
        raise ValueError(f"{label} must contain 1..{maximum} characters")
    if any(unicodedata.category(character).startswith("C") for character in trimmed):
        raise ValueError(f"{label} contains a control character")
    if _ABSOLUTE_REFERENCE.match(trimmed):
        raise ValueError(f"{label} must not be an absolute path or URL")
    return trimmed


def _enum(value: Any, allowed: tuple[str, ...], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{label} must be one of {allowed}")
    return value


def _pattern(value: Any, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


def _sorted_unique(
    value: Any,
    label: str,
    *,
    allowed: tuple[str, ...] | None = None,
    pattern: re.Pattern[str] | None = None,
) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple, set, frozenset)):
        raise ValueError(f"{label} must be an array")
    items = list(value)
    if not all(isinstance(item, str) for item in items):
        raise ValueError(f"{label} must contain strings")
    if len(items) != len(set(items)):
        raise ValueError(f"{label} must not contain duplicates")
    if allowed is not None and any(item not in allowed for item in items):
        raise ValueError(f"{label} contains an unknown value")
    if pattern is not None and any(not pattern.fullmatch(item) for item in items):
        raise ValueError(f"{label} contains an invalid identifier")
    return sorted(items)


def _observation_date(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("observation_date must be an ISO date string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("observation_date must be a valid ISO date") from error
    if parsed.isoformat() != value:
        raise ValueError("observation_date must use YYYY-MM-DD")
    return value


def _timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} must be an RFC 3339 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _timestamp_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _normalise_provider(value: Any, index: int) -> tuple[dict[str, Any], Mapping[str, Any]]:
    source = _mapping(value, f"provider_summaries[{index}]")
    _exact_fields(
        source,
        _PROVIDER_INPUT_FIELDS,
        f"provider_summaries[{index}]",
        _PROVIDER_COMPUTED_FIELDS,
    )
    provider = {
        "provider_uid": _pattern(source["provider_uid"], _PROVIDER_UID, "provider_uid"),
        "brand_name": _text(source["brand_name"], "brand_name", 256),
        "datasets": _sorted_unique(source["datasets"], "datasets", allowed=DATASETS),
        "state": _enum(source["state"], PROVIDER_STATES, "provider state"),
        "attempted": _boolean(source["attempted"], "attempted"),
        "population_known": _boolean(source["population_known"], "population_known"),
    }
    _validate_provider_flags(provider)
    return provider, source


def _validate_provider_flags(provider: Mapping[str, Any]) -> None:
    if provider["attempted"] != (provider["state"] != "not_attempted"):
        raise ValueError("provider attempted flag does not match state")
    if provider["state"] in {"complete", "empty"} and not provider["population_known"]:
        raise ValueError("complete/empty provider population must be known")
    if provider["state"] in {"failed", "not_attempted"} and provider["population_known"]:
        raise ValueError("failed/not_attempted provider population must be unknown")


def _normalise_product(value: Any, index: int) -> dict[str, Any]:
    source = _mapping(value, f"normalized_products[{index}]")
    _exact_fields(source, _PRODUCT_INPUT_FIELDS, f"normalized_products[{index}]", frozenset({"product_uid"}))
    provider = _pattern(source["provider_uid"], _PROVIDER_UID, "provider_uid")
    dataset = _enum(source["dataset"], DATASETS, "dataset")
    cdr_product_id = _opaque_text(source["cdr_product_id"], "cdr_product_id", 512)
    assert cdr_product_id is not None
    uid = derive_product_uid(provider, dataset, cdr_product_id)
    supplied_uid = source.get("product_uid")
    if supplied_uid is not None and _pattern(supplied_uid, _PRODUCT_UID, "product_uid") != uid:
        raise ValueError("product_uid does not match provider, dataset and CDR product ID")
    product = {
        "product_uid": uid,
        "provider_uid": provider,
        "cdr_product_id": cdr_product_id,
        "dataset": dataset,
        "display_name": _text(source["display_name"], "display_name", 256, nullable=True),
        "legacy_product_key": _opaque_text(
            source["legacy_product_key"], "legacy_product_key", 512, nullable=True
        ),
        "disposition": _enum(source["disposition"], DISPOSITIONS, "disposition"),
        "reason_codes": _sorted_unique(
            source["reason_codes"], "reason_codes", allowed=PRODUCT_ISSUE_CODES
        ),
        "evidence_ids": _sorted_unique(source["evidence_ids"], "evidence_ids", pattern=_SAFE_ID),
        "core_valid": _boolean(source["core_valid"], "core_valid"),
        "details_complete": _boolean(source["details_complete"], "details_complete"),
    }
    if not product["evidence_ids"]:
        raise ValueError("every product requires positive evidence IDs")
    _validate_product_flags(product)
    return product


def _validate_product_flags(product: Mapping[str, Any]) -> None:
    disposition = product["disposition"]
    reasons = set(product["reason_codes"])
    if disposition == "published_full":
        if not product["core_valid"] or not product["details_complete"] or reasons:
            raise ValueError("published_full requires valid core, complete details and no reasons")
    elif disposition == "published_core_only":
        if not product["core_valid"] or product["details_complete"] or not reasons:
            raise ValueError("published_core_only requires valid core, incomplete details and reasons")
    elif disposition == "omitted_valid":
        valid_reasons = {"no_current_rate", "product_closed", "unsupported_category"}
        if product["core_valid"] or not reasons or not reasons <= valid_reasons:
            raise ValueError("omitted_valid requires an allowlisted valid-absence reason")
    elif product["core_valid"] or not reasons:
        raise ValueError("quarantined_invalid requires invalid core and reasons")


def _issue_identity(issue: Mapping[str, Any]) -> list[Any]:
    return [
        "issue-v1",
        {
            key: issue[key]
            for key in (
                "scope",
                "provider_uid",
                "product_uid",
                "affected_sections",
                "phase",
                "code",
                "http_status",
                "evidence_digest",
                "disposition",
                "public_safe",
            )
        },
    ]


def issue_id_for(issue: Mapping[str, Any]) -> str:
    """Return the v1 ID for an already-normalized terminal issue."""

    return "issue:v1:" + hashlib.sha256(canonical_json_bytes(_issue_identity(issue))).hexdigest()


def _normalise_issue(value: Any, index: int) -> dict[str, Any]:
    source = _mapping(value, f"terminal_issues[{index}]")
    _exact_fields(source, _ISSUE_INPUT_FIELDS, f"terminal_issues[{index}]", frozenset({"issue_id"}))
    scope = _enum(source["scope"], ISSUE_SCOPES, "issue scope")
    provider = source["provider_uid"]
    product = source["product_uid"]
    disposition = source["disposition"]
    issue = {
        "scope": scope,
        "provider_uid": None if provider is None else _pattern(provider, _PROVIDER_UID, "provider_uid"),
        "product_uid": None if product is None else _pattern(product, _PRODUCT_UID, "product_uid"),
        "affected_sections": _sorted_unique(
            source["affected_sections"], "affected_sections", pattern=_SECTION
        ),
        "phase": _enum(source["phase"], ISSUE_PHASES, "issue phase"),
        "code": _enum(source["code"], ISSUE_CODES, "issue code"),
        "http_status": None
        if source["http_status"] is None
        else _integer(source["http_status"], "http_status", 100),
        "occurrence_count": _integer(source["occurrence_count"], "occurrence_count", 1),
        "first_seen_at": _timestamp(source["first_seen_at"], "first_seen_at"),
        "last_seen_at": _timestamp(source["last_seen_at"], "last_seen_at"),
        "evidence_digest": _pattern(source["evidence_digest"], _DIGEST, "evidence_digest"),
        "disposition": None
        if disposition is None
        else _enum(disposition, DISPOSITIONS, "issue disposition"),
        "public_safe": _boolean(source["public_safe"], "public_safe"),
    }
    if source["http_status"] is not None and issue["http_status"] > 599:
        raise ValueError("http_status must be between 100 and 599")
    if _timestamp_instant(issue["first_seen_at"]) > _timestamp_instant(issue["last_seen_at"]):
        raise ValueError("issue first_seen_at must not follow last_seen_at")
    _validate_issue_scope(issue)
    issue["issue_id"] = issue_id_for(issue)
    supplied_id = source.get("issue_id")
    if supplied_id is not None and _pattern(supplied_id, _ISSUE_ID, "issue_id") != issue["issue_id"]:
        raise ValueError("issue_id does not match normalized issue identity")
    return {"issue_id": issue.pop("issue_id"), **issue}


def _validate_issue_scope(issue: Mapping[str, Any]) -> None:
    scope = issue["scope"]
    code = issue["code"]
    expected_scope = (
        "product"
        if code in PRODUCT_ISSUE_CODES
        else "provider"
        if code in PROVIDER_ISSUE_CODES
        else "register"
        if code in REGISTER_ISSUE_CODES
        else "run"
    )
    if scope != expected_scope:
        raise ValueError(f"issue code {code} requires {expected_scope} scope")
    if scope == "product":
        if not issue["provider_uid"] or not issue["product_uid"] or not issue["disposition"]:
            raise ValueError("product issue requires provider, product and disposition")
    elif scope == "provider":
        if not issue["provider_uid"] or issue["product_uid"] is not None or issue["disposition"] is not None:
            raise ValueError("provider issue requires only a provider reference")
    elif scope == "register":
        if issue["product_uid"] is not None or issue["disposition"] is not None:
            raise ValueError("register issue cannot reference a product or disposition")
    elif any(issue[key] is not None for key in ("provider_uid", "product_uid", "disposition")):
        raise ValueError("run issue cannot carry provider, product or disposition")


def _aggregate_issues(values: Iterable[Any]) -> list[dict[str, Any]]:
    aggregated: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(values):
        issue = _normalise_issue(value, index)
        previous = aggregated.get(issue["issue_id"])
        if previous is None:
            aggregated[issue["issue_id"]] = issue
            continue
        previous["occurrence_count"] += issue["occurrence_count"]
        previous["first_seen_at"] = min(
            previous["first_seen_at"], issue["first_seen_at"], key=_timestamp_instant
        )
        previous["last_seen_at"] = max(
            previous["last_seen_at"], issue["last_seen_at"], key=_timestamp_instant
        )
    return [aggregated[key] for key in sorted(aggregated)]


def _raw_journal_identity(ingest_status: Mapping[str, Any]) -> tuple[str, str]:
    journal = _mapping(ingest_status.get("raw_attempt_journal"), "raw_attempt_journal")
    if journal.get("verified") is not True:
        raise ValueError("raw attempt journal must be verified")
    if "schema_version" in journal and journal["schema_version"] != 1:
        raise ValueError("raw attempt journal schema_version must be 1")
    _integer(journal.get("attempts"), "raw attempt journal attempts", 1)
    accounting_id = _pattern(journal.get("session_id"), _ACCOUNTING_ID, "accounting_id")
    digest = _pattern(journal.get("head_digest"), _DIGEST, "raw_attempt_journal_digest")
    return accounting_id, digest


def _provider_record(
    provider: Mapping[str, Any],
    source: Mapping[str, Any],
    products: list[Mapping[str, Any]],
    issues: list[Mapping[str, Any]],
) -> dict[str, Any]:
    _validate_provider_flags(provider)
    uid = provider["provider_uid"]
    owned_products = [product for product in products if product["provider_uid"] == uid]
    owned_issues = [issue for issue in issues if issue["provider_uid"] == uid]
    counts = Counter(product["disposition"] for product in owned_products)
    record = {
        **provider,
        "affected_sections": sorted(
            {section for issue in owned_issues for section in issue["affected_sections"]}
        ),
        "discovered_count": len(owned_products),
        **{f"{disposition}_count": counts[disposition] for disposition in DISPOSITIONS},
        "issue_count": sum(issue["occurrence_count"] for issue in owned_issues),
        "issue_ids": sorted(issue["issue_id"] for issue in owned_issues),
    }
    if provider["state"] in {"empty", "failed", "not_attempted"} and owned_products:
        raise ValueError(f"{provider['state']} provider cannot carry products")
    if provider["state"] in {"complete", "partial"} and not owned_products:
        raise ValueError(f"{provider['state']} provider must carry a reconciled product")
    product_datasets = {product["dataset"] for product in owned_products}
    if not product_datasets <= set(provider["datasets"]):
        raise ValueError("product dataset is absent from its provider summary")
    for field in _PROVIDER_COMPUTED_FIELDS:
        if field not in source:
            continue
        expected = record[field]
        supplied = source[field]
        if field in {"affected_sections", "issue_ids"}:
            pattern = _SECTION if field == "affected_sections" else _ISSUE_ID
            supplied = _sorted_unique(supplied, field, pattern=pattern)
        else:
            supplied = _integer(supplied, field)
        if supplied != expected:
            raise ValueError(f"provider {uid} {field} does not reconcile")
    return record


def _validate_ingest_status(
    ingest_status: Mapping[str, Any], providers: list[Mapping[str, Any]]
) -> None:
    registered = _integer(ingest_status.get("providers_registered"), "providers_registered")
    attempted = _integer(ingest_status.get("providers_attempted"), "providers_attempted")
    if registered != len(providers):
        raise ValueError("providers_registered does not reconcile")
    expected_attempted = sum(1 for provider in providers if provider["attempted"])
    if attempted != expected_attempted:
        raise ValueError("providers_attempted does not reconcile")
    provider_by_uid = {provider["provider_uid"]: provider for provider in providers}
    status_states = ingest_status.get("provider_states")
    if not isinstance(status_states, list):
        raise ValueError("provider_states must be an array")
    seen: set[str] = set()
    for index, raw in enumerate(status_states):
        item = _mapping(raw, f"provider_states[{index}]")
        uid = _pattern(item.get("provider_uid"), _PROVIDER_UID, "provider state provider_uid")
        if uid in seen or uid not in provider_by_uid:
            raise ValueError("provider_states contains a duplicate or unknown provider")
        seen.add(uid)
        provider = provider_by_uid[uid]
        if item.get("state") != provider["state"]:
            raise ValueError("provider state disagrees with ingest status")
        if item.get("population_known") is not provider["population_known"]:
            raise ValueError("provider population knowledge disagrees with ingest status")
        if item.get("brand_name") is not None:
            if _text(item["brand_name"], "status brand_name", 256) != provider["brand_name"]:
                raise ValueError("provider brand name disagrees with ingest status")
        count_field = (
            "products_in_scope" if "products_in_scope" in item else "products_discovered"
        )
        discovered = item.get(count_field)
        if discovered is not None and _integer(discovered, count_field) != provider["discovered_count"]:
            raise ValueError("provider product count disagrees with ingest status")
    required_status_uids = {
        provider["provider_uid"] for provider in providers if provider["state"] != "not_attempted"
    }
    if not required_status_uids <= seen:
        raise ValueError("attempted provider is missing from ingest provider_states")
    state_counts = ingest_status.get("provider_state_counts")
    if state_counts is not None:
        state_counts = _mapping(state_counts, "provider_state_counts")
        unknown = state_counts.keys() - set(PROVIDER_STATES)
        if unknown:
            raise ValueError(f"provider_state_counts has unknown states: {sorted(unknown)}")
        actual = Counter(provider["state"] for provider in providers)
        for state, value in state_counts.items():
            if _integer(value, f"provider_state_counts.{state}") != actual[state]:
                raise ValueError("provider_state_counts does not reconcile")


def _summary(
    providers: list[Mapping[str, Any]],
    products: list[Mapping[str, Any]],
    issues: list[Mapping[str, Any]],
) -> dict[str, Any]:
    provider_counts = Counter(provider["state"] for provider in providers)
    disposition_counts = Counter(product["disposition"] for product in products)
    code_counts = Counter()
    for issue in issues:
        code_counts[issue["code"]] += issue["occurrence_count"]
    return {
        "providers": {
            "registered": len(providers),
            "attempted": sum(provider_counts[state] for state in PROVIDER_STATES[:-1]),
            **{state: provider_counts[state] for state in PROVIDER_STATES},
            "population_unknown": sum(not provider["population_known"] for provider in providers),
        },
        "products": {
            "discovered": len(products),
            **{disposition: disposition_counts[disposition] for disposition in DISPOSITIONS},
            "consumer_visible": disposition_counts["published_full"]
            + disposition_counts["published_core_only"],
        },
        "issues": {
            "total": sum(code_counts.values()),
            "corrupt": code_counts["failure_record_corrupt"],
            "unattributed": code_counts["failure_unattributed"],
            "affected_providers": len(
                {issue["provider_uid"] for issue in issues if issue["provider_uid"] is not None}
            ),
            "affected_products": len(
                {issue["product_uid"] for issue in issues if issue["product_uid"] is not None}
            ),
            "by_code": {code: code_counts[code] for code in sorted(code_counts)},
        },
    }


def _validate_references(
    providers: list[Mapping[str, Any]],
    products: list[Mapping[str, Any]],
    issues: list[Mapping[str, Any]],
) -> None:
    provider_uids = {provider["provider_uid"] for provider in providers}
    if len(provider_uids) != len(providers):
        raise ValueError("provider_uid values must be unique")
    product_by_uid = {product["product_uid"]: product for product in products}
    if len(product_by_uid) != len(products):
        raise ValueError("product_uid values must be unique")
    legacy_keys: dict[str, str] = {}
    for product in products:
        if product["provider_uid"] not in provider_uids:
            raise ValueError("product references an unknown provider")
        expected_uid = derive_product_uid(
            product["provider_uid"], product["dataset"], product["cdr_product_id"]
        )
        if product["product_uid"] != expected_uid:
            raise ValueError("product_uid does not include its provider, dataset and CDR ID")
        key = product["legacy_product_key"]
        if key is not None and key in legacy_keys and legacy_keys[key] != product["product_uid"]:
            raise ValueError("legacy_product_key must map one-to-one to product_uid")
        if key is not None:
            legacy_keys[key] = product["product_uid"]
        _validate_product_flags(product)
    product_codes: dict[str, set[str]] = defaultdict(set)
    issue_ids: set[str] = set()
    for issue in issues:
        if issue["issue_id"] in issue_ids or issue["issue_id"] != issue_id_for(issue):
            raise ValueError("issue_id values must be unique and deterministic")
        issue_ids.add(issue["issue_id"])
        _validate_issue_scope(issue)
        if issue["provider_uid"] is not None and issue["provider_uid"] not in provider_uids:
            raise ValueError("issue references an unknown provider")
        if issue["product_uid"] is not None:
            product = product_by_uid.get(issue["product_uid"])
            if product is None or product["provider_uid"] != issue["provider_uid"]:
                raise ValueError("issue references an unknown or foreign product")
            if product["disposition"] != issue["disposition"]:
                raise ValueError("issue disposition disagrees with its product")
            product_codes[issue["product_uid"]].add(issue["code"])
    for product in products:
        if set(product["reason_codes"]) != product_codes[product["product_uid"]]:
            raise ValueError("product reason_codes do not reconcile with terminal issues")


def validate_product_accounting(accounting: Mapping[str, Any]) -> None:
    """Validate schema, identities, references, set membership and summaries."""

    document = dict(_mapping(accounting, "product accounting"))
    try:
        _schema_validator().validate(document)
    except ValidationError as error:
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        raise ValueError(
            f"product accounting schema violation at {location}: {error.message}"
        ) from error
    if document["schema_version"] != SCHEMA_VERSION:
        raise ValueError("product accounting schema_version must be 1")
    _observation_date(document["observation_date"])
    providers = document["providers"]
    products = document["products"]
    issues = document["issues"]
    if providers != sorted(providers, key=lambda item: item["provider_uid"]):
        raise ValueError("providers must use canonical provider_uid order")
    if products != sorted(products, key=lambda item: item["product_uid"]):
        raise ValueError("products must use canonical product_uid order")
    if issues != sorted(issues, key=lambda item: item["issue_id"]):
        raise ValueError("issues must use canonical issue_id order")
    for provider in providers:
        _validate_provider_flags(provider)
        if _text(provider["brand_name"], "brand_name", 256) != provider["brand_name"]:
            raise ValueError("provider brand_name must use canonical safe text")
        for field in ("datasets", "affected_sections", "issue_ids"):
            if provider[field] != sorted(provider[field]):
                raise ValueError(f"provider {field} must use canonical order")
    for product in products:
        if _opaque_text(product["cdr_product_id"], "cdr_product_id", 512) != product[
            "cdr_product_id"
        ]:
            raise ValueError("cdr_product_id must use canonical safe text")
        if _text(product["display_name"], "display_name", 256, nullable=True) != product[
            "display_name"
        ]:
            raise ValueError("display_name must use canonical safe text")
        if _opaque_text(
            product["legacy_product_key"], "legacy_product_key", 512, nullable=True
        ) != product["legacy_product_key"]:
            raise ValueError("legacy_product_key must use canonical safe text")
        for field in ("reason_codes", "evidence_ids"):
            if product[field] != sorted(product[field]):
                raise ValueError(f"product {field} must use canonical order")
    for issue in issues:
        if issue["affected_sections"] != sorted(issue["affected_sections"]):
            raise ValueError("issue affected_sections must use canonical order")
        if _timestamp(issue["first_seen_at"], "first_seen_at") != issue["first_seen_at"]:
            raise ValueError("issue first_seen_at must use canonical UTC form")
        if _timestamp(issue["last_seen_at"], "last_seen_at") != issue["last_seen_at"]:
            raise ValueError("issue last_seen_at must use canonical UTC form")
        if _timestamp_instant(issue["first_seen_at"]) > _timestamp_instant(
            issue["last_seen_at"]
        ):
            raise ValueError("issue first_seen_at must not follow last_seen_at")
    _validate_references(providers, products, issues)
    rebuilt_providers = [
        _provider_record(provider, provider, products, issues) for provider in providers
    ]
    if rebuilt_providers != providers:
        raise ValueError("provider accounting records do not reconcile")
    if document["summary"] != _summary(providers, products, issues):
        raise ValueError("product accounting summary does not reconcile")


def build_product_accounting(
    observation_date: str,
    ingest_status: Mapping[str, Any],
    provider_summaries: Iterable[Mapping[str, Any]],
    normalized_products: Iterable[Mapping[str, Any]],
    terminal_issues: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build one canonical, ledger-bindable ProductAccountingV1 document."""

    observation = _observation_date(observation_date)
    status = _mapping(ingest_status, "ingest_status")
    accounting_id, journal_digest = _raw_journal_identity(status)
    provider_inputs = [
        _normalise_provider(value, index) for index, value in enumerate(provider_summaries)
    ]
    products = sorted(
        (_normalise_product(value, index) for index, value in enumerate(normalized_products)),
        key=lambda item: item["product_uid"],
    )
    issues = _aggregate_issues(terminal_issues)
    base_providers = [item[0] for item in provider_inputs]
    _validate_references(base_providers, products, issues)
    providers = sorted(
        (
            _provider_record(provider, source, products, issues)
            for provider, source in provider_inputs
        ),
        key=lambda item: item["provider_uid"],
    )
    _validate_ingest_status(status, providers)
    document = {
        "schema_version": SCHEMA_VERSION,
        "observation_date": observation,
        "accounting_id": accounting_id,
        "raw_attempt_journal_digest": journal_digest,
        "providers": providers,
        "products": products,
        "issues": issues,
        "summary": _summary(providers, products, issues),
    }
    validate_product_accounting(document)
    return document


def build_product_accounting_bytes(
    observation_date: str,
    ingest_status: Mapping[str, Any],
    provider_summaries: Iterable[Mapping[str, Any]],
    normalized_products: Iterable[Mapping[str, Any]],
    terminal_issues: Iterable[Mapping[str, Any]],
) -> bytes:
    """Build exact compact UTF-8 bytes; no newline, clock, path or network input."""

    return canonical_json_bytes(
        build_product_accounting(
            observation_date,
            ingest_status,
            provider_summaries,
            normalized_products,
            terminal_issues,
        )
    )
