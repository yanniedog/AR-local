"""Create-once, verified SQLite v10 storage for one canonical CDR observation."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import quote

from ar_local_ingest_schedule import DAILY_INGEST_TZ
from cdr_contracts import (
    PROVIDER_UID_RE,
    canonical_json_bytes,
    parse_rate_string,
    product_uid,
    rate_uid,
)
from cdr_product_accounting import validate_product_accounting

from cdr_observation_db_schema import (
    ACCOUNTING_KEYS,
    APPLICATION_ID,
    DATASETS,
    DISPOSITIONS,
    FACT_KINDS,
    FAILURE_STAGES,
    ISSUE_CODES,
    ISSUE_KEYS,
    ITEM_GROUPS,
    PROJECTION_FIELDS,
    PROJECTION_KEYS,
    PROVIDER_KEYS,
    PROVIDER_UID,
    PRODUCT_KEYS,
    PRODUCT_UID,
    PUBLISHABLE,
    RATE_UID,
    SCHEMA_SQL,
    SCHEMA_VERSION,
    SCOPES,
    SECTIONS,
    SHA256,
    STATES,
    VALUE_TYPES,
)
from cdr_public_projection import PublicProjectionError, validate_public_document

FailureHook = Callable[[str], None]


class ObservationDatabaseError(ValueError):
    """The supplied observation or database fails a safety contract."""


@dataclass(frozen=True)
class DatabaseVerification:
    path: Path
    database_sha256: str
    schema_sha256: str
    accounting_sha256: str
    projections_sha256: str
    sidecar_bytes: bytes
    counts: Mapping[str, int]


@dataclass(frozen=True)
class DatabaseBuildResult:
    verification: DatabaseVerification
    created: bool


def _fail(message: str) -> None:
    raise ObservationDatabaseError(message)


def _json_bytes(value: Any) -> bytes:
    try:
        return canonical_json_bytes(value)
    except (TypeError, ValueError) as error:
        raise ObservationDatabaseError("value is not finite canonical JSON") from error


def _json_text(value: Any) -> str:
    return _json_bytes(value).decode("utf-8").removesuffix("\n")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{label} must be an object")
    return value


def _exact(row: Mapping[str, Any], keys: set[str], label: str) -> None:
    if set(row) != keys:
        _fail(f"{label} has missing or unexpected keys")


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{label} must be non-empty text")
    return value


def _nullable_text(value: Any, label: str) -> str | None:
    return None if value is None else _text(value, label)


def _integer(value: Any, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail(f"{label} must be an integer >= {minimum}")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        _fail(f"{label} must be boolean")
    return value


def _enum(value: Any, allowed: frozenset[str], label: str) -> str:
    if value not in allowed:
        _fail(f"{label} is not allowed")
    return value


def _ordered(values: Any, label: str, allowed: frozenset[str] | None = None, nonempty: bool = False) -> list[str]:
    if not isinstance(values, list) or any(not isinstance(item, str) or not item for item in values):
        _fail(f"{label} must be an array of non-empty strings")
    if nonempty and not values:
        _fail(f"{label} must not be empty")
    if values != sorted(set(values)) or (allowed is not None and any(item not in allowed for item in values)):
        _fail(f"{label} must be sorted, unique, and allowlisted")
    return values


def _timestamp(value: Any, label: str) -> str:
    text = _text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ObservationDatabaseError(f"{label} must be RFC 3339") from error
    if parsed.tzinfo is None:
        _fail(f"{label} must include a timezone")
    return text


def _timestamp_on_observation_date(value: Any, observation_date: str, label: str) -> str:
    text = _timestamp(value, label)
    instant = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if instant.astimezone(DAILY_INGEST_TZ).date() != date.fromisoformat(observation_date):
        _fail(f"{label} must fall on the observation date")
    return text


def _summary(providers: Sequence[Mapping[str, Any]], products: Sequence[Mapping[str, Any]], issues: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    states = Counter(row["state"] for row in providers)
    dispositions = Counter(row["disposition"] for row in products)
    codes: Counter[str] = Counter()
    for row in issues:
        codes[row["code"]] += row["occurrence_count"]
    return {
        "providers": {
            "registered": len(providers),
            "attempted": sum(row["attempted"] for row in providers),
            "complete": states["complete"],
            "partial": states["partial"],
            "empty": states["empty"],
            "failed": states["failed"],
            "not_attempted": states["not_attempted"],
            "population_unknown": sum(not row["population_known"] for row in providers),
        },
        "products": {
            "discovered": len(products),
            "published_full": dispositions["published_full"],
            "published_core_only": dispositions["published_core_only"],
            "omitted_valid": dispositions["omitted_valid"],
            "quarantined_invalid": dispositions["quarantined_invalid"],
            "consumer_visible": dispositions["published_full"] + dispositions["published_core_only"],
        },
        "issues": {
            "total": sum(codes.values()),
            "corrupt": codes["failure_record_corrupt"],
            "unattributed": codes["failure_unattributed"],
            "affected_providers": len({row["provider_uid"] for row in issues if row["provider_uid"]}),
            "affected_products": len({row["product_uid"] for row in issues if row["product_uid"]}),
            "by_code": dict(sorted(codes.items())),
        },
    }


def _validate_summary(value: Any) -> None:
    root = _mapping(value, "summary")
    _exact(root, {"providers", "products", "issues"}, "summary")
    expected = {
        "providers": {"registered", "attempted", "complete", "partial", "empty", "failed", "not_attempted", "population_unknown"},
        "products": {"discovered", "published_full", "published_core_only", "omitted_valid", "quarantined_invalid", "consumer_visible"},
        "issues": {"total", "corrupt", "unattributed", "affected_providers", "affected_products", "by_code"},
    }
    for group, keys in expected.items():
        section = _mapping(root[group], f"summary.{group}")
        _exact(section, keys, f"summary.{group}")
        for key, count in section.items():
            if key != "by_code":
                _integer(count, f"summary.{group}.{key}")
    by_code = _mapping(root["issues"]["by_code"], "summary.issues.by_code")
    if any(code not in ISSUE_CODES for code in by_code):
        _fail("summary issue code is not allowlisted")
    for code, count in by_code.items():
        _integer(count, f"summary.issues.by_code.{code}")


def _normalize_provider(raw: Any, index: int) -> dict[str, Any]:
    row = dict(_mapping(raw, f"providers[{index}]"))
    _exact(row, PROVIDER_KEYS, f"providers[{index}]")
    uid = _text(row["provider_uid"], "provider_uid")
    if not PROVIDER_UID.fullmatch(uid):
        _fail("provider_uid has invalid structure")
    row["brand_name"] = _text(row["brand_name"], "brand_name")
    row["datasets"] = _ordered(row["datasets"], "datasets", DATASETS)
    row["affected_sections"] = _ordered(row["affected_sections"], "affected_sections", SECTIONS)
    row["issue_ids"] = _ordered(row["issue_ids"], "issue_ids")
    row["state"] = _enum(row["state"], STATES, "provider state")
    row["attempted"] = _boolean(row["attempted"], "attempted")
    row["population_known"] = _boolean(row["population_known"], "population_known")
    if row["state"] in {"complete", "empty"} and not row["population_known"]:
        _fail("complete or empty provider population must be known")
    if row["state"] in {"failed", "not_attempted"} and row["population_known"]:
        _fail("failed or unattempted provider population must be unknown")
    for key in ("discovered_count", "published_full_count", "published_core_only_count", "omitted_valid_count", "quarantined_invalid_count", "issue_count"):
        row[key] = _integer(row[key], key)
    return row


def _normalize_product(raw: Any, index: int) -> dict[str, Any]:
    row = dict(_mapping(raw, f"products[{index}]"))
    _exact(row, PRODUCT_KEYS, f"products[{index}]")
    if not PRODUCT_UID.fullmatch(_text(row["product_uid"], "product_uid")):
        _fail("product_uid has invalid structure")
    if not PROVIDER_UID.fullmatch(_text(row["provider_uid"], "provider_uid")):
        _fail("provider_uid has invalid structure")
    row["cdr_product_id"] = _text(row["cdr_product_id"], "cdr_product_id")
    row["dataset"] = _enum(row["dataset"], DATASETS, "dataset")
    row["display_name"] = _nullable_text(row["display_name"], "display_name")
    row["legacy_product_key"] = _nullable_text(row["legacy_product_key"], "legacy_product_key")
    row["disposition"] = _enum(row["disposition"], DISPOSITIONS, "disposition")
    row["reason_codes"] = _ordered(row["reason_codes"], "reason_codes", ISSUE_CODES)
    row["evidence_ids"] = _ordered(row["evidence_ids"], "evidence_ids", nonempty=True)
    row["core_valid"] = _boolean(row["core_valid"], "core_valid")
    row["details_complete"] = _boolean(row["details_complete"], "details_complete")
    return row


def _normalize_issue(raw: Any, index: int) -> dict[str, Any]:
    row = dict(_mapping(raw, f"issues[{index}]"))
    _exact(row, ISSUE_KEYS, f"issues[{index}]")
    row["issue_id"] = _text(row["issue_id"], "issue_id")
    row["scope"] = _enum(row["scope"], SCOPES, "issue scope")
    row["provider_uid"] = _nullable_text(row["provider_uid"], "issue provider_uid")
    row["product_uid"] = _nullable_text(row["product_uid"], "issue product_uid")
    row["affected_sections"] = _ordered(row["affected_sections"], "issue affected_sections", SECTIONS)
    row["phase"] = _text(row["phase"], "issue phase")
    row["code"] = _enum(row["code"], ISSUE_CODES, "issue code")
    if row["http_status"] is not None:
        row["http_status"] = _integer(row["http_status"], "http_status", 100)
    if row["http_status"] is not None and row["http_status"] > 599:
        _fail("http_status must be <= 599")
    row["occurrence_count"] = _integer(row["occurrence_count"], "occurrence_count", 1)
    row["first_seen_at"] = _timestamp(row["first_seen_at"], "first_seen_at")
    row["last_seen_at"] = _timestamp(row["last_seen_at"], "last_seen_at")
    if datetime.fromisoformat(row["last_seen_at"].replace("Z", "+00:00")) < datetime.fromisoformat(row["first_seen_at"].replace("Z", "+00:00")):
        _fail("issue timestamps are reversed")
    if not SHA256.fullmatch(_text(row["evidence_digest"], "evidence_digest")):
        _fail("evidence_digest must be SHA-256")
    if row["disposition"] is not None:
        row["disposition"] = _enum(row["disposition"], DISPOSITIONS, "issue disposition")
    row["public_safe"] = _boolean(row["public_safe"], "public_safe")
    return row


def _normalize_accounting(value: Mapping[str, Any]) -> dict[str, Any]:
    root = dict(_mapping(value, "accounting"))
    _exact(root, ACCOUNTING_KEYS, "accounting")
    if isinstance(root["schema_version"], bool) or root["schema_version"] != 1:
        _fail("accounting schema_version must be 1")
    try:
        root["observation_date"] = date.fromisoformat(root["observation_date"]).isoformat()
    except (TypeError, ValueError) as error:
        raise ObservationDatabaseError("observation_date must be YYYY-MM-DD") from error
    root["accounting_id"] = _text(root["accounting_id"], "accounting_id")
    if not SHA256.fullmatch(_text(root["raw_attempt_journal_digest"], "raw_attempt_journal_digest")):
        _fail("raw journal digest must be SHA-256")
    for key in ("providers", "products", "issues"):
        if not isinstance(root[key], list):
            _fail(f"{key} must be an array")
    providers = [_normalize_provider(row, i) for i, row in enumerate(root["providers"])]
    products = [_normalize_product(row, i) for i, row in enumerate(root["products"])]
    issues = [_normalize_issue(row, i) for i, row in enumerate(root["issues"])]
    for rows, key in ((providers, "provider_uid"), (products, "product_uid"), (issues, "issue_id")):
        if [row[key] for row in rows] != sorted({row[key] for row in rows}):
            _fail(f"{key} records must be sorted and unique")
    provider_map = {row["provider_uid"]: row for row in providers}
    product_map = {row["product_uid"]: row for row in products}
    legacy = [row["legacy_product_key"] for row in products if row["legacy_product_key"] is not None]
    natural = [(row["provider_uid"], row["dataset"], row["cdr_product_id"]) for row in products]
    if len(legacy) != len(set(legacy)) or len(natural) != len(set(natural)):
        _fail("product aliases and natural identities must be unique")
    for row in products:
        if row["provider_uid"] not in provider_map:
            _fail("product references an unknown provider")
        if row["disposition"] in PUBLISHABLE and not row["core_valid"]:
            _fail("publishable product requires valid core")
        if row["disposition"] == "published_full" and not row["details_complete"]:
            _fail("published_full requires complete details")
        if row["disposition"] == "published_core_only" and row["details_complete"]:
            _fail("published_core_only cannot claim complete details")
    for row in issues:
        provider, product, scope = row["provider_uid"], row["product_uid"], row["scope"]
        scoped = (
            (scope == "product" and provider is not None and product is not None)
            or (scope == "provider" and provider is not None and product is None)
            or (scope == "register" and product is None)
            or (scope == "run" and provider is None and product is None)
        )
        if not scoped or (provider is not None and provider not in provider_map):
            _fail("issue identity contradicts scope")
        if product is not None and (product not in product_map or product_map[product]["provider_uid"] != provider):
            _fail("issue references unknown or foreign product")
        if product is not None and row["disposition"] is not None and row["disposition"] != product_map[product]["disposition"]:
            _fail("issue disposition contradicts product")
    by_products = {uid: [] for uid in provider_map}
    by_issues = {uid: [] for uid in provider_map}
    for row in products:
        by_products[row["provider_uid"]].append(row)
    for row in issues:
        if row["provider_uid"] in by_issues:
            by_issues[row["provider_uid"]].append(row)
    for row in providers:
        uid, member_products, member_issues = row["provider_uid"], by_products[row["provider_uid"]], by_issues[row["provider_uid"]]
        counts = Counter(item["disposition"] for item in member_products)
        expected = {
            "discovered_count": len(member_products),
            "published_full_count": counts["published_full"],
            "published_core_only_count": counts["published_core_only"],
            "omitted_valid_count": counts["omitted_valid"],
            "quarantined_invalid_count": counts["quarantined_invalid"],
            "issue_count": sum(item["occurrence_count"] for item in member_issues),
        }
        if any(row[key] != count for key, count in expected.items()):
            _fail(f"provider {uid} counts do not reconcile")
        if row["attempted"] != (row["state"] != "not_attempted"):
            _fail(f"provider {uid} attempted contradicts state")
        if row["state"] == "empty" and (not row["population_known"] or member_products):
            _fail(f"provider {uid} cannot claim empty")
        if not {item["dataset"] for item in member_products} <= set(row["datasets"]):
            _fail(f"provider {uid} omits a discovered product dataset")
        if row["issue_ids"] != sorted(item["issue_id"] for item in member_issues):
            _fail(f"provider {uid} issue IDs do not reconcile")
        if row["affected_sections"] != sorted({section for item in member_issues for section in item["affected_sections"]}):
            _fail(f"provider {uid} affected sections do not reconcile")
        terminal_unknown = {
            "pagination_incomplete", "products_index_failed", "provider_population_unknown"
        }
        if terminal_unknown & {item["code"] for item in member_issues} and (
            row["population_known"] or row["state"] not in {"partial", "failed", "not_attempted"}
        ):
            _fail("terminal provider issue requires an unknown, incomplete population")
    _validate_summary(root["summary"])
    root.update({"providers": providers, "products": products, "issues": issues})
    if root["summary"] != _summary(providers, products, issues):
        _fail("accounting summary does not reconcile")
    return json.loads(_json_bytes(root))


def _document(group: str, value: Any, expected: Mapping[str, Any]) -> dict[str, Any]:
    document = json.loads(_json_bytes(_mapping(value, "projection document")))
    try:
        return validate_public_document(group, document, expected)
    except PublicProjectionError as error:
        raise ObservationDatabaseError(str(error)) from error


def _rate(value: Any, label: str, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    text = _text(value, label)
    try:
        canonical = parse_rate_string(text)
    except ValueError as error:
        raise ObservationDatabaseError(f"{label} is not a decimal fraction") from error
    if text != canonical:
        _fail(f"{label} must be a canonical fraction from 0 to 1")
    return text


def _normalize_projections(value: Mapping[str, Any], accounting: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    root = _mapping(value, "projections")
    if set(root) != PROJECTION_FIELDS:
        _fail("projections have missing or unexpected groups")
    output: dict[str, list[dict[str, Any]]] = {}
    for group in PROJECTION_FIELDS:
        if not isinstance(root[group], list):
            _fail(f"projections.{group} must be an array")
        output[group] = []
        for index, raw in enumerate(root[group]):
            row = dict(_mapping(raw, f"{group}[{index}]"))
            _exact(row, PROJECTION_KEYS[group], f"{group}[{index}]")
            output[group].append(row)
    accounting_products = {row["product_uid"]: row for row in accounting["products"]}
    publishable = {uid for uid, row in accounting_products.items() if row["disposition"] in PUBLISHABLE}
    products: dict[str, dict[str, Any]] = {}
    for row in output["products"]:
        expected = {
            "product_uid": _text(row["product_uid"], "product_uid"),
            "provider_uid": _text(row["provider_uid"], "provider_uid"),
            "dataset": _enum(row["dataset"], DATASETS, "dataset"),
            "cdr_product_id": _text(row["cdr_product_id"], "cdr_product_id"),
            "legacy_product_key": _nullable_text(row["legacy_product_key"], "legacy_product_key"),
        }
        uid = expected["product_uid"]
        if uid in products or uid not in publishable or any(accounting_products[uid][key] != val for key, val in expected.items()):
            _fail("consumer product identity or membership is invalid")
        products[uid] = {**expected, "document": _document("products", row["document"], expected)}
    if set(products) != publishable:
        _fail("consumer products differ from publishable dispositions")
    output["products"] = sorted(products.values(), key=lambda row: row["product_uid"])
    rates, rate_ids, rate_slots, rated = [], set(), set(), set()
    for row in output["rates"]:
        expected = {
            "rate_uid": _text(row["rate_uid"], "rate_uid"),
            "product_uid": _text(row["product_uid"], "rate product_uid"),
            "rate_index": _integer(row["rate_index"], "rate_index", 1),
            "rate": _rate(row["rate"], "rate"),
            "comparison_rate": _rate(row["comparison_rate"], "comparison_rate", True),
        }
        key = (expected["product_uid"], expected["rate_index"])
        canonical_rate_uid = rate_uid(
            expected["product_uid"], expected["rate_index"],
            expected["rate"], expected["comparison_rate"]
        )
        if (
            not RATE_UID.fullmatch(expected["rate_uid"])
            or expected["rate_uid"] != canonical_rate_uid
            or expected["product_uid"] not in products
            or expected["rate_uid"] in rate_ids
            or key in rate_slots
        ):
            _fail("rate identity or membership is invalid")
        rate_ids.add(expected["rate_uid"])
        rate_slots.add(key)
        rated.add(expected["product_uid"])
        rates.append({**expected, "document": _document("rates", row["document"], expected)})
    if rated != publishable:
        _fail("every publishable product requires at least one rate")
    output["rates"] = sorted(rates, key=lambda row: (row["product_uid"], row["rate_index"], row["rate_uid"]))
    items, item_keys = [], set()
    for row in output["items"]:
        expected = {
            "product_uid": _text(row["product_uid"], "item product_uid"),
            "item_group": _enum(row["item_group"], ITEM_GROUPS, "item_group"),
            "item_index": _integer(row["item_index"], "item_index", 1),
        }
        key = tuple(expected.values())
        if expected["product_uid"] not in products or key in item_keys:
            _fail("item identity or membership is invalid")
        item_keys.add(key)
        items.append({**expected, "document": _document("items", row["document"], expected)})
    output["items"] = sorted(items, key=lambda row: (row["product_uid"], row["item_group"], row["item_index"]))
    facts, fact_keys = [], set()
    for row in output["product_facts"]:
        product = _text(row["product_uid"], "fact product_uid")
        fact_id = _text(row["fact_id"], "fact_id")
        boolean, number, text = row["value_boolean"], row["value_number"], row["value_text"]
        minimum, maximum = row["min_value"], row["max_value"]
        key = (product, fact_id)
        if product not in products or key in fact_keys or row["kind"] not in FACT_KINDS or row["value_type"] not in VALUE_TYPES:
            _fail("fact identity, kind, or membership is invalid")
        if number is not None and (isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number)):
            _fail("fact value_number must be finite or null")
        if text is not None and not isinstance(text, str):
            _fail("fact value_text must be text or null")
        if boolean is not None and not isinstance(boolean, bool):
            _fail("fact value_boolean must be boolean or null")
        for label, value in (("min_value", minimum), ("max_value", maximum)):
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                _fail(f"fact {label} must be finite or null")
        number = None if number is None else float(number)
        minimum = None if minimum is None else float(minimum)
        maximum = None if maximum is None else float(maximum)
        typed = (boolean, number, text, minimum, maximum)
        value_type = row["value_type"]
        valid_shape = {
            "boolean": boolean is not None and typed[1:] == (None, None, None, None),
            "money": number is not None and boolean is None and text is None and minimum is None and maximum is None,
            "rate": number is not None and boolean is None and text is None and minimum is None and maximum is None,
            "number": number is not None and boolean is None and text is None and minimum is None and maximum is None,
            "duration": text is not None and boolean is None and number is None and minimum is None and maximum is None,
            "enum": text is not None and boolean is None and number is None and minimum is None and maximum is None,
            "text": text is not None and boolean is None and number is None and minimum is None and maximum is None,
            "range": boolean is None and number is None and text is None and (minimum is not None or maximum is not None),
        }.get(value_type, False)
        if not valid_shape:
            _fail("fact values do not match value_type")
        if (
            (row["kind"] == "rate" or row["value_type"] == "rate")
            and number is not None
            and not 0 <= number <= 1
        ):
            _fail("rate fact value_number must be a fraction from 0 to 1")
        expected = {
            "product_uid": product,
            "fact_id": fact_id,
            "kind": row["kind"],
            "canonical_key": _text(row["canonical_key"], "canonical_key"),
            "value_type": value_type,
            "value_boolean": boolean,
            "value_number": number,
            "value_text": text,
            "min_value": minimum,
            "max_value": maximum,
        }
        fact_keys.add(key)
        facts.append({**expected, "document": _document("product_facts", row["document"], expected)})
    output["product_facts"] = sorted(facts, key=lambda row: (row["product_uid"], row["fact_id"]))
    changes, event_ids = [], set()
    for row in output["product_changes"]:
        expected = {
            "event_id": _text(row["event_id"], "event_id"),
            "provider_uid": _text(row["provider_uid"], "change provider_uid"),
            "product_uid": _text(row["product_uid"], "change product_uid"),
            "event_type": _text(row["event_type"], "event_type"),
            "canonical_key": _nullable_text(row["canonical_key"], "canonical_key"),
        }
        document = _document("product_changes", row["document"], expected)
        dataset = _enum(document.get("dataset"), DATASETS, "change dataset")
        cdr_product_id = _text(document.get("product_id"), "change product_id")
        if (
            expected["event_id"] in event_ids
            or not PROVIDER_UID.fullmatch(expected["provider_uid"])
            or expected["product_uid"] not in products
            or products[expected["product_uid"]]["provider_uid"]
            != expected["provider_uid"]
            or expected["product_uid"]
            != product_uid(expected["provider_uid"], dataset, cdr_product_id)
        ):
            _fail("change identity or provider is invalid")
        event_ids.add(expected["event_id"])
        changes.append({**expected, "document": document})
    output["product_changes"] = sorted(changes, key=lambda row: row["event_id"])
    return output


def validate_observation_inputs(
    accounting: Mapping[str, Any], projections: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    """Validate and canonicalize the sidecar and every consumer projection."""

    try:
        validate_product_accounting(accounting)
    except ValueError as error:
        raise ObservationDatabaseError(str(error)) from error
    normalized_accounting = _normalize_accounting(accounting)
    return normalized_accounting, _normalize_projections(projections, normalized_accounting)


def _schema_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        {"type": row[0], "name": row[1], "table": row[2], "sql": row[3]}
        for row in connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")
    ]


def _schema_fingerprint(connection: sqlite3.Connection) -> str:
    return _sha256(_json_bytes({"objects": _schema_rows(connection)}))


@lru_cache(maxsize=1)
def expected_schema_fingerprint() -> str:
    with sqlite3.connect(":memory:") as connection:
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.executescript(SCHEMA_SQL)
        return _schema_fingerprint(connection)


def _configure_writer(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys=ON")
    if connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0].lower() != "delete":
        _fail("SQLite refused DELETE journal mode")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA trusted_schema=OFF")
    connection.execute("PRAGMA writable_schema=OFF")
    connection.execute("PRAGMA secure_delete=ON")
    connection.execute("PRAGMA temp_store=MEMORY")


def _insert_many(connection: sqlite3.Connection, table: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
    if rows:
        marks = ",".join("?" for _ in columns)
        connection.executemany(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({marks})", rows)


def _projection_counts(projections: Mapping[str, Sequence[Any]]) -> dict[str, int]:
    return {f"bank_{group}": len(projections[group]) for group in sorted(PROJECTION_FIELDS)}


def _storage_rows(accounting_id: str, rows: Sequence[Mapping[str, Any]], columns: Sequence[str], boolean_fields: frozenset[str] = frozenset()) -> list[tuple[Any, ...]]:
    def stored(row: Mapping[str, Any], column: str) -> Any:
        key = column.removesuffix("_json")
        if column.endswith("_json"):
            return _json_text(row[key])
        if key in boolean_fields:
            return None if row[key] is None else int(row[key])
        return row[key]
    return [(accounting_id, *(stored(row, column) for column in columns[1:])) for row in rows]


def _write_accounting(connection: sqlite3.Connection, accounting: Mapping[str, Any], generated_at: str, projections: Mapping[str, Sequence[Any]]) -> None:
    accounting_id = accounting["accounting_id"]
    connection.execute("INSERT INTO runs VALUES(?,?,?,?,?,?)", (
        accounting["observation_date"], accounting_id, accounting["raw_attempt_journal_digest"], generated_at,
        _json_bytes(accounting), _json_text(_projection_counts(projections)),
    ))
    specifications = (
        ("bank_provider_observations", "providers", ("accounting_id", "provider_uid", "brand_name", "datasets_json", "affected_sections_json", "state", "attempted", "population_known", "discovered_count", "published_full_count", "published_core_only_count", "omitted_valid_count", "quarantined_invalid_count", "issue_count", "issue_ids_json"), frozenset({"attempted", "population_known"})),
        ("bank_product_dispositions", "products", ("accounting_id", "product_uid", "provider_uid", "cdr_product_id", "dataset", "display_name", "legacy_product_key", "disposition", "reason_codes_json", "evidence_ids_json", "core_valid", "details_complete"), frozenset({"core_valid", "details_complete"})),
        ("bank_observation_issues", "issues", ("accounting_id", "issue_id", "scope", "provider_uid", "product_uid", "affected_sections_json", "phase", "code", "http_status", "occurrence_count", "first_seen_at", "last_seen_at", "evidence_digest", "disposition", "public_safe"), frozenset({"public_safe"})),
    )
    for table, group, columns, boolean_fields in specifications:
        _insert_many(connection, table, columns, _storage_rows(accounting_id, accounting[group], columns, boolean_fields))


def _write_projections(connection: sqlite3.Connection, accounting_id: str, projections: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
    specifications = {
        "products": ("product_uid", "provider_uid", "dataset", "cdr_product_id", "legacy_product_key", "document_json"),
        "rates": ("rate_uid", "product_uid", "rate_index", "rate", "comparison_rate", "document_json"),
        "items": ("product_uid", "item_group", "item_index", "document_json"),
        "product_facts": ("product_uid", "fact_id", "kind", "canonical_key", "value_type", "value_boolean", "value_number", "value_text", "min_value", "max_value", "document_json"),
        "product_changes": ("event_id", "provider_uid", "product_uid", "event_type", "canonical_key", "document_json"),
    }
    for group, fields in specifications.items():
        columns = ("accounting_id", *fields)
        boolean_fields = frozenset({"value_boolean"}) if group == "product_facts" else frozenset()
        _insert_many(
            connection,
            f"bank_{group}",
            columns,
            _storage_rows(accounting_id, projections[group], columns, boolean_fields),
        )


def _load_json(value: Any, label: str, object_only: bool = False) -> Any:
    if not isinstance(value, str):
        _fail(f"{label} is not text JSON")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise ObservationDatabaseError(f"{label} is invalid JSON") from error
    if object_only and not isinstance(parsed, dict):
        _fail(f"{label} must be an object")
    if value != _json_text(parsed):
        _fail(f"{label} is not canonical JSON")
    return parsed


def _read_records(connection: sqlite3.Connection, table: str, columns: Sequence[str], order: str, boolean_fields: frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    records = []
    for values in connection.execute(f"SELECT {','.join(columns)} FROM {table} ORDER BY {order}"):
        record = {}
        for column, value in zip(columns, values):
            key = column.removesuffix("_json")
            if column.endswith("_json"):
                value = _load_json(value, f"{table}.{column}", key == "document")
            elif key in boolean_fields:
                value = None if value is None else bool(value)
            record[key] = value
        records.append(record)
    return records


def _sidecar_from_database(connection: sqlite3.Connection) -> tuple[dict[str, Any], bytes]:
    runs = connection.execute("SELECT observation_date,accounting_id,raw_attempt_journal_digest,sidecar_bytes FROM runs").fetchall()
    if len(runs) != 1:
        _fail("database must contain exactly one run")
    run = runs[0]
    providers = _read_records(connection, "bank_provider_observations", ("provider_uid", "brand_name", "datasets_json", "affected_sections_json", "state", "attempted", "population_known", "discovered_count", "published_full_count", "published_core_only_count", "omitted_valid_count", "quarantined_invalid_count", "issue_count", "issue_ids_json"), "provider_uid", frozenset({"attempted", "population_known"}))
    products = _read_records(connection, "bank_product_dispositions", ("product_uid", "provider_uid", "cdr_product_id", "dataset", "display_name", "legacy_product_key", "disposition", "reason_codes_json", "evidence_ids_json", "core_valid", "details_complete"), "product_uid", frozenset({"core_valid", "details_complete"}))
    issues = _read_records(connection, "bank_observation_issues", ("issue_id", "scope", "provider_uid", "product_uid", "affected_sections_json", "phase", "code", "http_status", "occurrence_count", "first_seen_at", "last_seen_at", "evidence_digest", "disposition", "public_safe"), "issue_id", frozenset({"public_safe"}))
    sidecar = {
        "schema_version": 1,
        "observation_date": run[0],
        "accounting_id": run[1],
        "raw_attempt_journal_digest": run[2],
        "providers": providers,
        "products": products,
        "issues": issues,
        "summary": _summary(providers, products, issues),
    }
    if not isinstance(run[3], bytes):
        _fail("stored sidecar is not a BLOB")
    return _normalize_accounting(sidecar), run[3]


def _projections_from_database(connection: sqlite3.Connection) -> dict[str, Any]:
    specifications = {
        "products": (("product_uid", "provider_uid", "dataset", "cdr_product_id", "legacy_product_key", "document_json"), "product_uid"),
        "rates": (("rate_uid", "product_uid", "rate_index", "rate", "comparison_rate", "document_json"), "product_uid,rate_index,rate_uid"),
        "items": (("product_uid", "item_group", "item_index", "document_json"), "product_uid,item_group,item_index"),
        "product_facts": (("product_uid", "fact_id", "kind", "canonical_key", "value_type", "value_boolean", "value_number", "value_text", "min_value", "max_value", "document_json"), "product_uid,fact_id", frozenset({"value_boolean"})),
        "product_changes": (("event_id", "provider_uid", "product_uid", "event_type", "canonical_key", "document_json"), "event_id"),
    }
    return {
        group: _read_records(
            connection,
            f"bank_{group}",
            spec[0],
            spec[1],
            spec[2] if len(spec) > 2 else frozenset(),
        )
        for group, spec in specifications.items()
    }


def _integrity(connection: sqlite3.Connection) -> None:
    if [row[0] for row in connection.execute("PRAGMA quick_check")] != ["ok"]:
        _fail("SQLite quick_check failed")
    if [row[0] for row in connection.execute("PRAGMA integrity_check")] != ["ok"]:
        _fail("SQLite integrity_check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        _fail("SQLite foreign_key_check failed")


def _sidecar_paths(path: Path) -> tuple[Path, Path, Path]:
    return Path(f"{path}-journal"), Path(f"{path}-wal"), Path(f"{path}-shm")


def _connect_immutable(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(path.resolve().as_posix(), safe='/:')}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA trusted_schema=OFF")
    return connection


def _verify_connection(connection: sqlite3.Connection, path: Path, expected_sidecar_bytes: bytes | None, expected_projections: Mapping[str, Any] | None, expected_normalization_version: str | None, expected_generated_at: str | None) -> DatabaseVerification:
    if connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
        _fail("SQLite application_id is wrong")
    if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        _fail("SQLite schema version is wrong")
    if connection.execute("PRAGMA journal_mode").fetchone()[0].lower() != "delete":
        _fail("SQLite journal mode is not DELETE")
    page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
    page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
    if path.stat().st_size != page_count * page_size:
        _fail("SQLite file has non-page trailing or truncated bytes")
    schema_sha = _schema_fingerprint(connection)
    if schema_sha != expected_schema_fingerprint():
        _fail("SQLite tables, constraints, indexes, or triggers differ from v10")
    _integrity(connection)
    meta = dict(connection.execute("SELECT key,value FROM schema_meta"))
    required = {"schema_sha256", "accounting_sha256", "projections_sha256", "normalization_version"}
    if set(meta) != required or meta["schema_sha256"] != schema_sha:
        _fail("schema metadata is incomplete or inconsistent")
    _text(meta["normalization_version"], "stored normalization_version")
    stored_generated_at = _timestamp(connection.execute("SELECT generated_at FROM runs").fetchone()[0], "stored generated_at")
    if expected_generated_at is not None and stored_generated_at != expected_generated_at:
        _fail("generated_at differs from expected")
    sidecar, stored_sidecar = _sidecar_from_database(connection)
    _timestamp_on_observation_date(
        stored_generated_at, sidecar["observation_date"], "stored generated_at"
    )
    rebuilt_sidecar = _json_bytes(sidecar)
    accounting_sha = _sha256(rebuilt_sidecar)
    if stored_sidecar != rebuilt_sidecar or meta["accounting_sha256"] != accounting_sha:
        _fail("stored and regenerated accounting sidecar bytes differ")
    if expected_sidecar_bytes is not None and rebuilt_sidecar != expected_sidecar_bytes:
        _fail("database accounting differs from expected sidecar")
    projections = _normalize_projections(_projections_from_database(connection), sidecar)
    projections_sha = _sha256(_json_bytes({"schema_version": 1, **projections}))
    if meta["projections_sha256"] != projections_sha:
        _fail("projection digest does not match database rows")
    if expected_projections is not None and projections != expected_projections:
        _fail("database projections differ from expected rows")
    if expected_normalization_version is not None and meta["normalization_version"] != expected_normalization_version:
        _fail("normalization version differs from expected")
    counts = _projection_counts(projections)
    stored_counts = _load_json(connection.execute("SELECT projection_counts_json FROM runs").fetchone()[0], "projection counts")
    if counts != stored_counts:
        _fail("projection counts do not reconcile")
    return DatabaseVerification(path, "", schema_sha, accounting_sha, projections_sha, rebuilt_sidecar, counts)
def _database_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_observation_database(path: Path | str, *, expected_sidecar_bytes: bytes | None = None, expected_projections: Mapping[str, Any] | None = None, expected_normalization_version: str | None = None, expected_generated_at: str | None = None) -> DatabaseVerification:
    """Verify every structural and semantic contract through immutable read-only I/O."""
    supplied = Path(path).expanduser()
    if supplied.is_symlink():
        _fail("database path must not be a symlink")
    target = supplied.resolve()
    if not target.is_file() or any(sidecar.exists() for sidecar in _sidecar_paths(target)):
        _fail("database must be a regular sidecar-free immutable file")
    before, digest_before = target.stat(), _database_sha256(target)
    connection = _connect_immutable(target)
    try:
        result = _verify_connection(connection, target, expected_sidecar_bytes, expected_projections, expected_normalization_version, expected_generated_at)
    except ObservationDatabaseError:
        raise
    except (sqlite3.DatabaseError, KeyError, IndexError, TypeError, ValueError) as error:
        raise ObservationDatabaseError("database verification failed closed") from error
    finally:
        connection.close()
    after, digest_after = target.stat(), _database_sha256(target)
    before_state = before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns
    after_state = after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
    if before_state != after_state or digest_before != digest_after or any(sidecar.exists() for sidecar in _sidecar_paths(target)):
        _fail("database changed during immutable verification")
    return DatabaseVerification(result.path, digest_after, result.schema_sha256, result.accounting_sha256, result.projections_sha256, result.sidecar_bytes, result.counts)
def _fsync_file(path: Path) -> None:
    with path.open("rb+") as stream:
        os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
def _cleanup_candidate(path: Path) -> None:
    path.unlink(missing_ok=True)
    for sidecar in _sidecar_paths(path):
        sidecar.unlink(missing_ok=True)
def build_observation_database(target: Path | str, *, accounting: Mapping[str, Any], projections: Mapping[str, Any], generated_at: str, normalization_version: str, failure_hook: FailureHook | None = None) -> DatabaseBuildResult:
    """Build privately, verify, then atomically install without overwriting history."""
    supplied = Path(target).expanduser()
    if supplied.is_symlink():
        _fail("database path must not be a symlink")
    destination = supplied.resolve()
    normalized_accounting, normalized_projections = validate_observation_inputs(
        accounting, projections
    )
    sidecar_bytes = _json_bytes(normalized_accounting)
    generated_at = _timestamp_on_observation_date(
        generated_at, normalized_accounting["observation_date"], "generated_at"
    )
    normalization_version = _text(normalization_version, "normalization_version")
    hook = failure_hook or (lambda _stage: None)
    if destination.exists():
        verification = verify_observation_database(destination, expected_sidecar_bytes=sidecar_bytes, expected_projections=normalized_projections, expected_normalization_version=normalization_version, expected_generated_at=generated_at)
        return DatabaseBuildResult(verification, False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, candidate_name = tempfile.mkstemp(prefix=f".{destination.name}.tmp-", dir=destination.parent)
    os.close(descriptor)
    candidate, installed = Path(candidate_name), False
    try:
        os.chmod(candidate, 0o600)
        connection = sqlite3.connect(candidate)
        try:
            _configure_writer(connection)
            connection.executescript(SCHEMA_SQL)
            connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            hook("after_schema")
            connection.execute("BEGIN IMMEDIATE")
            _write_accounting(connection, normalized_accounting, generated_at, normalized_projections)
            hook("after_accounting")
            _write_projections(connection, normalized_accounting["accounting_id"], normalized_projections)
            hook("after_projections")
            schema_sha = _schema_fingerprint(connection)
            projection_sha = _sha256(_json_bytes({"schema_version": 1, **normalized_projections}))
            connection.executemany(
                "INSERT INTO schema_meta VALUES(?,?)",
                (
                    ("schema_sha256", schema_sha),
                    ("accounting_sha256", _sha256(sidecar_bytes)),
                    ("projections_sha256", projection_sha),
                    ("normalization_version", normalization_version),
                ),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        hook("after_commit")
        _fsync_file(candidate)
        verified = verify_observation_database(candidate, expected_sidecar_bytes=sidecar_bytes, expected_projections=normalized_projections, expected_normalization_version=normalization_version, expected_generated_at=generated_at)
        hook("after_verify")
        hook("before_install")
        try:
            os.link(candidate, destination)
            installed = True
        except FileExistsError:
            verification = verify_observation_database(destination, expected_sidecar_bytes=sidecar_bytes, expected_projections=normalized_projections, expected_normalization_version=normalization_version, expected_generated_at=generated_at)
            return DatabaseBuildResult(verification, False)
        hook("after_install")
        _cleanup_candidate(candidate)
        _fsync_directory(destination.parent)
        verification = verify_observation_database(destination, expected_sidecar_bytes=sidecar_bytes, expected_projections=normalized_projections, expected_normalization_version=normalization_version, expected_generated_at=generated_at)
        if verification.database_sha256 != verified.database_sha256:
            _fail("installed database differs from verified candidate")
        return DatabaseBuildResult(verification, True)
    finally:
        _cleanup_candidate(candidate)
        if installed:
            _fsync_directory(destination.parent)
