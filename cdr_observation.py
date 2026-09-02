"""Canonical public observation and consumer-safe projection construction."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from ar_local_ingest_schedule import DAILY_INGEST_TZ
from cdr_atomic import atomic_write_bytes
from cdr_contracts import canonical_json_bytes, parse_rate_string, product_uid, rate_uid
from cdr_observation_db import validate_observation_inputs, verify_observation_database
from cdr_product_accounting import validate_product_accounting
from cdr_public_projection import PublicProjectionError, public_document


SCHEMA_VERSION = 1
ACCOUNTING_FILE = "product-accounting-v1.json"
OBSERVATION_FILE = "observation-v1.json"
PROJECTION_GROUPS = ("products", "rates", "items", "product_facts", "product_changes")
_GLOBAL_ISSUE_BLOCKERS = {
    "accounting_unreconciled",
    "failure_record_corrupt",
    "failure_unattributed",
    "register_failed",
}


class ObservationError(ValueError):
    """An observation would be ambiguous, unsafe, or internally inconsistent."""


def _accounting_blockers(accounting: Mapping[str, Any]) -> list[str]:
    blockers = {
        issue["code"]
        for issue in accounting["issues"]
        if issue["code"] in _GLOBAL_ISSUE_BLOCKERS
    }
    if any(provider["state"] == "not_attempted" for provider in accounting["providers"]):
        blockers.add("provider_not_attempted")
    summary = accounting["summary"]
    if summary["providers"]["registered"] == 0:
        blockers.add("no_registered_providers")
    if summary["products"]["consumer_visible"] == 0:
        blockers.add("zero_publishable_products")
    return sorted(blockers)


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


def _evidence_id(
    row: Mapping[str, Any], allowed: frozenset[str], label: str
) -> str:
    value = row.get("evidence_id")
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
        or value not in allowed
    ):
        raise ObservationError(f"{label} lacks accounting-bound evidence")
    return value


def _document(
    group: str,
    row: Mapping[str, Any],
    envelope: Mapping[str, Any],
    *,
    observation_date: str,
    omitted_detail_groups: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    try:
        return public_document(
            group,
            row,
            envelope,
            observation_date=observation_date,
            omitted_detail_groups=omitted_detail_groups,
        )
    except PublicProjectionError as error:
        raise ObservationError(str(error)) from error


def _product_projections(
    banks: Mapping[str, Any],
    accounting: Mapping[str, Any],
    rejected_details: Mapping[str, frozenset[str]],
    observation_date: str,
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
        evidence = _evidence_id(
            rows[uid], frozenset(disposition["evidence_ids"]), "product"
        )
        envelope = {
            "product_uid": uid,
            "provider_uid": disposition["provider_uid"],
            "dataset": disposition["dataset"],
            "cdr_product_id": disposition["cdr_product_id"],
            "legacy_product_key": disposition["legacy_product_key"],
        }
        document_envelope = {
            **envelope,
            "details_complete": disposition["details_complete"],
            "evidence_id": evidence,
        }
        output.append(
            {
                **envelope,
                "document": _document(
                    "products",
                    rows[uid],
                    document_envelope,
                    observation_date=observation_date,
                    omitted_detail_groups=rejected_details.get(uid, frozenset()),
                ),
            }
        )
    return output


def _rate_projections(
    rows: Iterable[Any],
    visible: set[str],
    evidence_by_uid: Mapping[str, str],
    observation_date: str,
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
        evidence = _evidence_id(
            raw, frozenset({evidence_by_uid[uid]}), "rate"
        )
        envelope = {
            "rate_uid": rate_uid(uid, index, rate, comparison),
            "product_uid": uid,
            "rate_index": index,
            "rate": rate,
            "comparison_rate": comparison,
        }
        document_envelope = {**envelope, "evidence_id": evidence}
        output.append(
            {
                **envelope,
                "document": _document(
                    "rates", raw, document_envelope, observation_date=observation_date
                ),
            }
        )
    return output


def _item_projections(
    banks: Mapping[str, Any],
    visible: set[str],
    rejected_details: Mapping[str, frozenset[str]],
    evidence_by_uid: Mapping[str, str],
    observation_date: str,
) -> list[dict[str, Any]]:
    output = []
    for group in ("fees", "features", "eligibility", "constraints"):
        for raw in banks.get(group) or []:
            if not isinstance(raw, Mapping):
                raise ObservationError("item projection source is invalid")
            uid = _uid(raw, "item")
            if uid not in visible or group in rejected_details.get(uid, frozenset()):
                continue
            index = raw.get("item_index")
            if isinstance(index, bool) or not isinstance(index, int) or index < 1:
                raise ObservationError("item_index must be a positive integer")
            envelope = {"product_uid": uid, "item_group": group, "item_index": index}
            document_envelope = {
                **envelope,
                "evidence_id": _evidence_id(
                    raw, frozenset({evidence_by_uid[uid]}), "item"
                ),
            }
            output.append(
                {
                    **envelope,
                    "document": _document(
                        "items", raw, document_envelope, observation_date=observation_date
                    ),
                }
            )
    return output


def _fact_projections(
    rows: Iterable[Any],
    visible: set[str],
    rejected_details: Mapping[str, frozenset[str]] | None = None,
    *,
    evidence_by_uid: Mapping[str, str],
    observation_date: str,
) -> list[dict[str, Any]]:
    output = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ObservationError("fact projection source is invalid")
        uid = _uid(raw, "fact")
        rejected = (rejected_details or {}).get(uid, frozenset())
        source_group = str(raw.get("source_path") or "").split("[", 1)[0].split(".", 1)[0]
        if uid not in visible or source_group in rejected or "details" in rejected:
            continue
        boolean = raw.get("value_boolean")
        if boolean is not None and not isinstance(boolean, bool):
            raise ObservationError("fact value_boolean must be boolean or null")
        number = raw.get("value_number")
        if number is not None:
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
                raise ObservationError("fact value_number must be finite or null")
            number = float(number)
        text = raw.get("value_text")
        if text is not None and not isinstance(text, str):
            raise ObservationError("fact value_text must be text or null")
        minimum = raw.get("min_value")
        maximum = raw.get("max_value")
        for label, value in (("min_value", minimum), ("max_value", maximum)):
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ObservationError(f"fact {label} must be finite or null")
        minimum = None if minimum is None else float(minimum)
        maximum = None if maximum is None else float(maximum)
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ObservationError("fact range bounds are reversed")
        kind = str(raw.get("kind") or "")
        value_type = str(raw.get("value_type") or "")
        typed = (boolean, number, text, minimum, maximum)
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
            raise ObservationError("fact values do not match value_type")
        if (
            (kind == "rate" or value_type == "rate")
            and number is not None
            and not 0 <= number <= 1
        ):
            raise ObservationError("rate fact value_number must be a fraction from 0 to 1")
        envelope = {
            "product_uid": uid,
            "fact_id": str(raw.get("fact_id") or ""),
            "kind": kind,
            "canonical_key": str(raw.get("canonical_key") or ""),
            "value_type": value_type,
            "value_boolean": boolean,
            "value_number": number,
            "value_text": text,
            "min_value": minimum,
            "max_value": maximum,
        }
        document_envelope = {
            **envelope,
            "evidence_id": _evidence_id(
                raw, frozenset({evidence_by_uid[uid]}), "fact"
            ),
        }
        output.append(
            {
                **envelope,
                "document": _document(
                    "product_facts", raw, document_envelope, observation_date=observation_date
                ),
            }
        )
    return output


def _validate_observed_at(observation_date: str, observed_at: Any) -> str:
    if not isinstance(observed_at, str):
        raise ObservationError("observed_at must be an RFC 3339 timestamp")
    try:
        source_date = date.fromisoformat(observation_date)
        instant = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ObservationError("observed_at must be an RFC 3339 timestamp") from error
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ObservationError("observed_at must include a timezone")
    if instant.astimezone(DAILY_INGEST_TZ).date() != source_date:
        raise ObservationError("observed_at must fall on the observation date")
    return observed_at


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


def _change_provider_uid(
    raw: Mapping[str, Any], labels: Mapping[str, str], dataset: str, cdr_product_id: str
) -> str:
    candidates: set[str] = set()
    label_uid = labels.get(str(raw.get("provider") or "").strip().casefold())
    if label_uid:
        candidates.add(label_uid)
    for side in ("before", "after"):
        fact = raw.get(side)
        if not isinstance(fact, Mapping):
            continue
        provider = str(fact.get("provider_uid") or "")
        supplied_product = str(fact.get("product_uid") or "")
        if not provider and not supplied_product:
            continue
        if (
            not provider
            or supplied_product != product_uid(provider, dataset, cdr_product_id)
        ):
            raise ObservationError(
                "product change carries invalid canonical identity evidence"
            )
        candidates.add(provider)
    if len(candidates) != 1:
        raise ObservationError(
            "product change cannot be bound to one canonical provider"
        )
    return next(iter(candidates))


def _change_projections(
    banks: Mapping[str, Any],
    accounting: Mapping[str, Any],
    visible: set[str],
    rejected_details: Mapping[str, frozenset[str]],
    evidence_by_uid: Mapping[str, str],
    observation_date: str,
) -> list[dict[str, Any]]:
    labels = _provider_labels(banks, accounting)
    output = []
    for raw in banks.get("product_changes") or []:
        if not isinstance(raw, Mapping):
            raise ObservationError("product change source is invalid")
        dataset = str(raw.get("dataset") or "")
        product_id_value = str(raw.get("product_id") or "").strip()
        if dataset not in {"Mortgage", "Savings", "TD"} or not product_id_value:
            raise ObservationError("product change cannot be bound to a canonical identity")
        provider = _change_provider_uid(raw, labels, dataset, product_id_value)
        uid = product_uid(provider, dataset, product_id_value)
        if uid not in visible:
            continue
        rejected = rejected_details.get(uid, frozenset())
        changed_group = str(raw.get("kind") or raw.get("canonical_key") or "").split(".", 1)[0]
        if "details" in rejected or changed_group in rejected:
            continue
        envelope = {
            "event_id": str(raw.get("event_id") or ""),
            "provider_uid": provider,
            "product_uid": uid,
            "event_type": str(raw.get("event_type") or ""),
            "canonical_key": str(raw.get("canonical_key") or "").strip() or None,
        }
        document_envelope = {**envelope, "evidence_id": evidence_by_uid[uid]}
        output.append(
            {
                **envelope,
                "document": _document(
                    "product_changes", raw, document_envelope, observation_date=observation_date
                ),
            }
        )
    return output


def build_projections(
    banks: Mapping[str, Any], accounting: Mapping[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    rejected: dict[str, set[str]] = {}
    for issue in accounting["issues"]:
        if issue["code"] == "field_omitted_invalid" and issue["product_uid"] is not None:
            rejected.setdefault(issue["product_uid"], set()).update(issue["affected_sections"])
    rejected_details = {uid: frozenset(groups) for uid, groups in rejected.items()}
    observation_date = str(accounting["observation_date"])
    products = _product_projections(
        banks, accounting, rejected_details, observation_date
    )
    visible = {row["product_uid"] for row in products}
    evidence_by_uid = {
        row["product_uid"]: row["document"]["evidence_id"] for row in products
    }
    projections = {
        "products": products,
        "rates": _rate_projections(
            banks.get("rates") or [], visible, evidence_by_uid, observation_date
        ),
        "items": _item_projections(
            banks, visible, rejected_details, evidence_by_uid, observation_date
        ),
        "product_facts": _fact_projections(
            banks.get("product_facts") or [],
            visible,
            rejected_details,
            evidence_by_uid=evidence_by_uid,
            observation_date=observation_date,
        ),
        "product_changes": _change_projections(
            banks, accounting, visible, rejected_details, evidence_by_uid,
            observation_date,
        ),
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
    mandatory_blockers = _accounting_blockers(accounting)
    if mandatory_blockers:
        raise ObservationError(
            "global observation blockers: " + ", ".join(mandatory_blockers)
        )
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
    _validate_observed_at(document["observation_date"], document["observed_at"])
    if document["summaries"] != accounting["summary"]:
        raise ObservationError("observation summaries disagree with accounting")
    expected_state = "degraded" if (
        accounting["issues"]
        or any(
            provider["state"] not in {"complete", "empty"}
            for provider in accounting["providers"]
        )
    ) else "complete"
    if document["state"] != expected_state:
        raise ObservationError("observation state disagrees with accounting")
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
    normalized_accounting, normalized = validate_observation_inputs(accounting, projections)
    blockers = sorted(
        set(blockers) | set(_accounting_blockers(normalized_accounting))
    )
    if blockers:
        raise ObservationError("global observation blockers: " + ", ".join(blockers))
    observed_at = _validate_observed_at(
        normalized_accounting["observation_date"], observed_at
    )
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


def load_verified_observation(out_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the one canonical observation only after every stored form agrees."""

    out_dir = out_dir.expanduser().resolve()

    def read(name: str, label: str) -> tuple[dict[str, Any], bytes]:
        try:
            raw = (out_dir / name).read_bytes()
            value = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ObservationError(f"{label} is unreadable") from error
        if not isinstance(value, dict) or raw != canonical_json_bytes(value):
            raise ObservationError(f"{label} is not canonical")
        return value, raw

    observation, _ = read(OBSERVATION_FILE, "observation")
    accounting, accounting_bytes = read(ACCOUNTING_FILE, "product accounting")
    validate_observation(observation, accounting)
    projections = {group: observation[group] for group in PROJECTION_GROUPS}
    verify_observation_database(
        out_dir / "local-cdr.sqlite",
        expected_sidecar_bytes=accounting_bytes,
        expected_projections=projections,
        expected_normalization_version=observation["normalization_version"],
        expected_generated_at=observation["observed_at"],
    )
    return observation, accounting
