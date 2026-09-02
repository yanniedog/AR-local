"""Exact public-safe document fields shared by JSON and SQLite validation."""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, time, timedelta
from typing import Any, Mapping
from urllib.parse import urlsplit

from ar_local_ingest_schedule import DAILY_INGEST_TZ


class PublicProjectionError(ValueError):
    """A projection document contains data outside the public contract."""


_BASE_FIELDS = {
    "sector", "dataset", "provider", "brand", "brand_name", "provider_uid",
    "provider_identity_status", "product_id", "product_name", "category",
    "last_updated", "effective_from", "effective_to", "is_tailored",
    "description", "product_key", "legacy_product_key", "product_uid",
    "details_complete", "evidence_id",
}
_RIBBON_FIELDS = {
    "ribbon_normalized", "security_purpose", "ribbon_repayment_type", "lvr_tier",
    "lvr_source", "ribbon_rate_structure", "ribbon_fixed_term", "account_type",
    "ribbon_deposit_kind", "balance_min", "balance_max", "term_months",
    "interest_payment", "feature_set", "taxonomy_path", "account_class",
}
PUBLIC_DOCUMENT_FIELDS = {
    "products": _BASE_FIELDS | {"cdr_product_id", "details_json"},
    "rates": _BASE_FIELDS | _RIBBON_FIELDS | {
        "rate_uid", "rate_family", "rate_index", "rate", "comparison_rate",
        "rate_type", "application_type", "application_frequency",
        "calculation_frequency", "repayment_type", "loan_purpose", "term",
    },
    "items": _BASE_FIELDS | {"item_group", "item_index", "item_type", "name", "value"},
    "product_facts": _BASE_FIELDS | {
        "fact_id", "kind", "canonical_key", "value_type", "unit", "mapping",
        "source_path", "source_pattern", "value_boolean", "value_number",
        "value_text", "value_json", "min_value", "max_value", "qualifiers_json",
    },
    "product_changes": {
        "run_date", "previous_run_date", "event_id", "dataset", "provider",
        "provider_uid", "product_id", "product_uid", "product_name", "event_type",
        "canonical_key", "kind", "materiality", "equivalence", "review_required",
        "cosmetic", "material", "slots_changed", "reasons_json",
        "before_value_json", "after_value_json", "before_signature_json",
        "after_signature_json",
    },
}
_JSON_TEXT_FIELDS = {
    "details_json", "value_json", "qualifiers_json", "reasons_json",
    "before_value_json", "after_value_json", "before_signature_json",
    "after_signature_json",
}
_SENSITIVE_KEY = re.compile(
    r"(?:authorization|proxy[_-]?authorization|cookie|set[_-]?cookie|credential|"
    r"password|client[_-]?secret|private[_-]?key|api[_-]?key|"
    r"(?:access|refresh|session|bearer|auth|id)[_-]?token|"
    r"request[_-]?headers?|response[_-]?headers?|raw[_-]?response|"
    r"response[_-]?body|traceback|stack[_-]?trace)",
    re.I,
)
_URL = re.compile(r"https?://\S+", re.I)
_OFFICIAL_LINK_FIELDS = {
    "overviewUri", "eligibilityUri", "feesAndPricingUri", "termsUri", "bundleUri"
}
_MAX_DOCUMENT_BYTES = 512 * 1024
_DATE_FIELDS = ("last_updated", "effective_from", "effective_to")
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


def _safe_https(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and not parsed.fragment
    )


def _scan(value: Any, *, path: tuple[str, ...] = ()) -> None:
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PublicProjectionError("public projection contains a non-finite number")
        return
    if isinstance(value, str):
        urls = _URL.findall(value)
        allowed_link = bool(path and path[-1] in _OFFICIAL_LINK_FIELDS)
        if urls and (not allowed_link or len(urls) != 1 or urls[0] != value or not _safe_https(value)):
            raise PublicProjectionError("public projection contains an unapproved URL")
        return
    if isinstance(value, list):
        for item in value:
            _scan(item, path=path)
        return
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            if _SENSITIVE_KEY.search(key):
                location = ".".join((*path, key))
                raise PublicProjectionError(
                    f"public projection contains a sensitive field: {location}"
                )
            _scan(item, path=(*path, key))
        return
    raise PublicProjectionError("public projection contains an unsupported value")


def _validated_json_text(field: str, value: Any, omitted: frozenset[str]) -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) > _MAX_DOCUMENT_BYTES:
        raise PublicProjectionError(f"public {field} is invalid")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise PublicProjectionError(f"public {field} is invalid JSON") from error
    if field == "details_json":
        if not isinstance(parsed, dict):
            raise PublicProjectionError("public details_json must be an object")
        to_remove = {"fees", "features", "eligibility", "constraints"} if "details" in omitted else set(omitted)
        parsed = {key: item for key, item in parsed.items() if key not in to_remove}
    _scan(parsed)
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True)


def _source_instant(field: str, value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise PublicProjectionError(f"public {field} is not an ISO date or RFC 3339 timestamp")
    try:
        if _DATE_ONLY.fullmatch(value):
            return datetime.combine(date.fromisoformat(value), time.min, DAILY_INGEST_TZ)
        if not _RFC3339.fullmatch(value):
            raise ValueError
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise PublicProjectionError(
            f"public {field} is not an ISO date or RFC 3339 timestamp"
        ) from error
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise PublicProjectionError(f"public {field} timestamp lacks a timezone")
    return instant.astimezone(DAILY_INGEST_TZ)


def _validate_source_dates(document: Mapping[str, Any], observation_date: str) -> None:
    try:
        observed = date.fromisoformat(observation_date)
    except (TypeError, ValueError) as error:
        raise PublicProjectionError("observation_date must be YYYY-MM-DD") from error
    latest = datetime.combine(observed + timedelta(days=1), time.min, DAILY_INGEST_TZ)
    parsed = {
        field: _source_instant(field, document.get(field))
        for field in _DATE_FIELDS
        if field in document
    }
    if any(value is not None and value > latest for value in parsed.values()):
        raise PublicProjectionError(
            "public source date is more than 24 hours beyond observation_date"
        )
    start, end = parsed.get("effective_from"), parsed.get("effective_to")
    if start is not None and end is not None and start > end:
        raise PublicProjectionError("public effective date range is reversed")


def public_document(
    group: str,
    source: Mapping[str, Any],
    envelope: Mapping[str, Any],
    *,
    observation_date: str,
    omitted_detail_groups: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Select only documented fields, validate content, and bind indexed keys."""

    allowed = PUBLIC_DOCUMENT_FIELDS.get(group)
    if allowed is None or not isinstance(source, Mapping):
        raise PublicProjectionError("unknown public projection group")
    document = {key: source[key] for key in allowed if key in source}
    document.update(envelope)
    _validate_source_dates(document, observation_date)
    for field in _JSON_TEXT_FIELDS & document.keys():
        value = document[field]
        if value is not None:
            document[field] = _validated_json_text(field, value, omitted_detail_groups)
    for key, value in document.items():
        if key not in _JSON_TEXT_FIELDS:
            _scan(value, path=(key,))
    try:
        size = len(
            json.dumps(document, ensure_ascii=False, sort_keys=True, allow_nan=False).encode(
                "utf-8"
            )
        )
    except (TypeError, ValueError) as error:
        raise PublicProjectionError("public projection is not canonical JSON") from error
    if size > _MAX_DOCUMENT_BYTES:
        raise PublicProjectionError("public projection exceeds its size limit")
    return document


def validate_public_document(
    group: str,
    document: Mapping[str, Any],
    envelope: Mapping[str, Any],
    *,
    observation_date: str,
) -> dict[str, Any]:
    """Require stored public bytes to be exactly the safe projection."""

    normalized = public_document(
        group, document, envelope, observation_date=observation_date
    )
    if normalized != document:
        raise PublicProjectionError("public projection has fields outside its contract")
    return normalized
