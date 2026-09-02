"""Canonical public observation and consumer-safe projection construction."""

from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from cdr_atomic import atomic_write_bytes
from cdr_contracts import canonical_json_bytes, parse_rate_string, product_uid
from cdr_observation_db import validate_observation_inputs
from cdr_product_accounting import validate_product_accounting


SCHEMA_VERSION = 1
ACCOUNTING_FILE = "product-accounting-v1.json"
OBSERVATION_FILE = "observation-v1.json"
PROJECTION_GROUPS = ("products", "rates", "items", "product_facts", "product_changes")


class ObservationError(ValueError):
    """An observation would be ambiguous, unsafe, or internally inconsistent."""


@lru_cache(maxsize=1)
def _schema_validator() -> Draft202012Validator:
    path = Path(__file__).resolve().parent / "contracts" / "observation-v1.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _uid(row: Mapping[str, Any], label: str) -> str:
    value = str(row.get("product_uid") or "")
    if len(value) != 64:
        raise ObservationError(f"{label} lacks product_uid")
    return value


def _document(row: Mapping[str, Any], envelope: Mapping[str, Any]) -> dict[str, Any]:
    return {**dict(row), **dict(envelope)}


def _product_projections(
    banks: Mapping[str, Any], accounting: Mapping[str, Any]
) -> list[dict[str, Any]]:
    publishable = {
        row["product_uid"]: row
        for row in accounting["products"]
        if row["disposition"] in {"published_full", "published_core_only"}
    }
    rows: dict[str, Mapping[str, Any]] = {}
    for raw in banks.get("products") or []:
        if not isinstance(raw, Mapping):
            raise ObservationError("product projection source is invalid")
        uid = _uid(raw, "product")
        if uid in rows:
            raise ObservationError("product projection identity is duplicated")
        rows[uid] = raw
    if not set(publishable) <= set(rows):
        raise ObservationError("publishable product lacks a normalized source row")
    output = []
    for uid, disposition in publishable.items():
        envelope = {
            "product_uid": uid,
            "provider_uid": disposition["provider_uid"],
            "dataset": disposition["dataset"],
            "cdr_product_id": disposition["cdr_product_id"],
            "legacy_product_key": disposition["legacy_product_key"],
        }
        output.append({**envelope, "document": _document(rows[uid], envelope)})
    return output


def _rate_projections(
    rows: Iterable[Any], visible: set[str]
) -> list[dict[str, Any]]:
    output = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ObservationError("rate projection source is invalid")
        uid = _uid(raw, "rate")
        if uid not in visible:
            continue
        index = raw.get("rate_index")
        if isinstance(index, bool) or not isinstance(index, int) or index < 1:
            raise ObservationError("rate_index must be a positive integer")
        rate = parse_rate_string(raw.get("rate"))
        comparison_raw = raw.get("comparison_rate")
        comparison = None if comparison_raw in (None, "") else parse_rate_string(comparison_raw)
        identity = ["rate-v1", uid, index, rate, comparison]
        envelope = {
            "rate_uid": hashlib.sha256(canonical_json_bytes(identity)).hexdigest(),
            "product_uid": uid,
            "rate_index": index,
            "rate": rate,
            "comparison_rate": comparison,
        }
        output.append({**envelope, "document": _document(raw, envelope)})
    return output


def _item_projections(
    banks: Mapping[str, Any], visible: set[str]
) -> list[dict[str, Any]]:
    output = []
    for group in ("fees", "features", "eligibility", "constraints"):
        for raw in banks.get(group) or []:
            if not isinstance(raw, Mapping):
                raise ObservationError("item projection source is invalid")
            uid = _uid(raw, "item")
            if uid not in visible:
                continue
            index = raw.get("item_index")
            if isinstance(index, bool) or not isinstance(index, int) or index < 1:
                raise ObservationError("item_index must be a positive integer")
            envelope = {"product_uid": uid, "item_group": group, "item_index": index}
            output.append({**envelope, "document": _document(raw, envelope)})
    return output


def _fact_projections(rows: Iterable[Any], visible: set[str]) -> list[dict[str, Any]]:
    output = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ObservationError("fact projection source is invalid")
        uid = _uid(raw, "fact")
        if uid not in visible:
            continue
        number = raw.get("value_number")
        if number is not None:
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
                raise ObservationError("fact value_number must be finite or null")
            number = float(number)
        text = raw.get("value_text")
        if text is not None and not isinstance(text, str):
            raise ObservationError("fact value_text must be text or null")
        envelope = {
            "product_uid": uid,
            "fact_id": str(raw.get("fact_id") or ""),
            "kind": str(raw.get("kind") or ""),
            "canonical_key": str(raw.get("canonical_key") or ""),
            "value_type": str(raw.get("value_type") or ""),
            "value_number": number,
            "value_text": text,
        }
        output.append({**envelope, "document": _document(raw, envelope)})
    return output


def _provider_labels(
    banks: Mapping[str, Any], accounting: Mapping[str, Any]
) -> dict[str, str]:
    labels: dict[str, set[str]] = {}

    def add(label: Any, uid: str) -> None:
        key = str(label or "").strip().casefold()
        if key:
            labels.setdefault(key, set()).add(uid)

    for provider in accounting["providers"]:
        add(provider["brand_name"], provider["provider_uid"])
    for provider in banks.get("provider_observations") or []:
        if isinstance(provider, Mapping):
            uid = str(provider.get("provider_uid") or "")
            add(provider.get("provider_dir"), uid)
            add(provider.get("brand_name"), uid)
    return {label: next(iter(uids)) for label, uids in labels.items() if len(uids) == 1}


def _change_projections(
    banks: Mapping[str, Any], accounting: Mapping[str, Any]
) -> list[dict[str, Any]]:
    labels = _provider_labels(banks, accounting)
    output = []
    for raw in banks.get("product_changes") or []:
        if not isinstance(raw, Mapping):
            raise ObservationError("product change source is invalid")
        provider = labels.get(str(raw.get("provider") or "").strip().casefold())
        dataset = str(raw.get("dataset") or "")
        product_id_value = str(raw.get("product_id") or "").strip()
        if provider is None or dataset not in {"Mortgage", "Savings", "TD"} or not product_id_value:
            raise ObservationError("product change cannot be bound to a canonical identity")
        envelope = {
            "event_id": str(raw.get("event_id") or ""),
            "provider_uid": provider,
            "product_uid": product_uid(provider, dataset, product_id_value),
            "event_type": str(raw.get("event_type") or ""),
            "canonical_key": str(raw.get("canonical_key") or "").strip() or None,
        }
        output.append({**envelope, "document": _document(raw, envelope)})
    return output


def build_projections(
    banks: Mapping[str, Any], accounting: Mapping[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    products = _product_projections(banks, accounting)
    visible = {row["product_uid"] for row in products}
    projections = {
        "products": products,
        "rates": _rate_projections(banks.get("rates") or [], visible),
        "items": _item_projections(banks, visible),
        "product_facts": _fact_projections(banks.get("product_facts") or [], visible),
        "product_changes": _change_projections(banks, accounting),
    }
    _, normalized = validate_observation_inputs(accounting, projections)
    return normalized


def validate_observation(
    observation: Mapping[str, Any], accounting: Mapping[str, Any]
) -> None:
    document = dict(observation)
    try:
        _schema_validator().validate(document)
    except ValidationError as error:
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        raise ObservationError(
            f"observation schema violation at {location}: {error.message}"
        ) from error
    validate_product_accounting(accounting)
    expected_digest = hashlib.sha256(canonical_json_bytes(accounting)).hexdigest()
    if document["accounting"] != {
        "schema_version": 1,
        "accounting_id": accounting["accounting_id"],
        "file": ACCOUNTING_FILE,
        "sha256": expected_digest,
    }:
        raise ObservationError("observation does not bind its accounting sidecar")
    if document["observation_date"] != accounting["observation_date"]:
        raise ObservationError("observation date disagrees with accounting")
    if document["summaries"] != accounting["summary"]:
        raise ObservationError("observation summaries disagree with accounting")
    projections = {group: document[group] for group in PROJECTION_GROUPS}
    _, normalized = validate_observation_inputs(accounting, projections)
    if projections != normalized:
        raise ObservationError("observation projections are not canonical")
    counts = {group: len(normalized[group]) for group in PROJECTION_GROUPS}
    if document["row_counts"] != counts:
        raise ObservationError("observation row counts do not reconcile")


def build_observation(
    *,
    accounting: Mapping[str, Any],
    projections: Mapping[str, Any],
    observed_at: str,
    normalization_version: str,
    blockers: Iterable[str] = (),
) -> dict[str, Any]:
    blockers = sorted(set(blockers))
    if blockers:
        raise ObservationError("global observation blockers: " + ", ".join(blockers))
    normalized_accounting, normalized = validate_observation_inputs(accounting, projections)
    degraded = bool(normalized_accounting["issues"]) or any(
        provider["state"] not in {"complete", "empty"}
        for provider in normalized_accounting["providers"]
    )
    document = {
        "schema_version": SCHEMA_VERSION,
        "observation_date": normalized_accounting["observation_date"],
        "observed_at": observed_at,
        "normalization_version": normalization_version,
        "state": "degraded" if degraded else "complete",
        "accounting": {
            "schema_version": 1,
            "accounting_id": normalized_accounting["accounting_id"],
            "file": ACCOUNTING_FILE,
            "sha256": hashlib.sha256(canonical_json_bytes(normalized_accounting)).hexdigest(),
        },
        "summaries": normalized_accounting["summary"],
        "row_counts": {group: len(normalized[group]) for group in PROJECTION_GROUPS},
        **normalized,
    }
    validate_observation(document, normalized_accounting)
    return document


def write_observation(
    out_dir: Path, observation: Mapping[str, Any], accounting: Mapping[str, Any]
) -> None:
    validate_observation(observation, accounting)
    out_dir = out_dir.expanduser().resolve()
    atomic_write_bytes(out_dir / ACCOUNTING_FILE, canonical_json_bytes(accounting), create_once=True)
    atomic_write_bytes(out_dir / OBSERVATION_FILE, canonical_json_bytes(observation), create_once=True)
