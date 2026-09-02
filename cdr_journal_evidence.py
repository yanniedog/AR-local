"""Bind accounting claims to provider- and product-specific HTTP evidence."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any, Mapping

from cdr_contracts import canonical_json_bytes
from cdr_ingest_support import allocate_bank_dir, extract_products, pick_text
from cdr_product_accounting import validate_product_accounting
from cdr_raw_attempt_journal import RawAttemptJournal


PRODUCT_PHASES = frozenset(
    {"products_index", "product_detail", "classification_detail"}
)


def journal_product_evidence(
    journal: RawAttemptJournal,
) -> dict[tuple[str, str], list[dict[str, str]]]:
    """Index successful JSON bodies by their journal provider and product."""

    evidence: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for record in journal.evidence_records(recover=False):
        if record["outcome"] != "success" or not 200 <= record["status"] < 300:
            continue
        context = record["context"]
        provider = str(context.get("provider") or "")
        phase = str(context.get("phase") or "")
        if not provider or phase not in PRODUCT_PHASES:
            continue
        try:
            body = (journal.root / str(record["body_path"])).read_bytes()
            parsed = json.loads(body)
            canonical_digest = hashlib.sha256(
                canonical_json_bytes(parsed)
            ).hexdigest()
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            continue
        digest = str(record["body_sha256"])
        product_id = str(context.get("product_id") or "")
        if product_id and phase in {"product_detail", "classification_detail"}:
            evidence[(provider, product_id)].append(
                {
                    "body_sha256": digest,
                    "canonical_digest": canonical_digest,
                    "phase": phase,
                }
            )
        if phase != "products_index":
            continue
        try:
            products = extract_products(parsed)
        except ValueError:
            continue
        for item in products:
            product_id = pick_text(item, ["productId", "id"])
            if product_id:
                evidence[(provider, product_id)].append(
                    {
                        "body_sha256": digest,
                        "canonical_digest": canonical_digest,
                        "phase": phase,
                    }
                )
    return evidence


def _provider_directories(
    provider_states: object,
) -> dict[str, str]:
    if not isinstance(provider_states, list):
        raise ValueError("promoted ingest provider states are invalid")
    seen_directories: set[str] = set()
    directories: dict[str, str] = {}
    for raw in provider_states:
        if not isinstance(raw, Mapping):
            raise ValueError("promoted ingest provider state is invalid")
        uid = str(raw.get("provider_uid") or "")
        if not uid or uid in directories:
            raise ValueError("promoted ingest provider identity is invalid")
        derived = allocate_bank_dir(
            str(raw.get("brand_name") or ""),
            str(raw.get("legal_entity_name") or ""),
            str(raw.get("endpoint_url") or ""),
            seen_directories,
        )
        explicit = raw.get("provider_dir")
        if explicit is not None and explicit != derived:
            raise ValueError("promoted ingest provider directory is invalid")
        directories[uid] = derived
    return directories


def validate_journal_evidence(
    accounting: Mapping[str, Any],
    provider_states: object,
    journal: RawAttemptJournal,
) -> None:
    """Reconcile accounting with contextual outcomes in one verified journal."""

    validate_product_accounting(accounting)
    directories = _provider_directories(provider_states)
    providers = {item["provider_uid"]: item for item in accounting["providers"]}
    if set(directories) != set(providers):
        raise ValueError("promoted ingest provider population does not reconcile")

    records_by_provider: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    successful_indexes: set[str] = set()
    for record in journal.evidence_records(recover=False):
        context = record["context"]
        phase = str(context.get("phase") or "")
        provider_dir = str(context.get("provider") or "")
        if phase not in PRODUCT_PHASES or not provider_dir:
            continue
        records_by_provider[provider_dir].append(record)
        if (
            phase == "products_index"
            and record["outcome"] == "success"
            and 200 <= record["status"] < 300
        ):
            try:
                payload = json.loads(
                    (journal.root / str(record["body_path"])).read_bytes()
                )
                extract_products(payload)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                continue
            successful_indexes.add(provider_dir)

    known_directories = set(directories.values())
    if set(records_by_provider) - known_directories:
        raise ValueError("journal attempt references an unknown provider")
    for uid, provider in providers.items():
        directory = directories[uid]
        attempts = records_by_provider[directory]
        if provider["attempted"] is True and not attempts:
            raise ValueError("attempted provider lacks journal-bound evidence")
        if provider["attempted"] is False and attempts:
            raise ValueError("unattempted provider has journal-bound evidence")
        if provider["state"] in {"complete", "empty", "partial"}:
            if directory not in successful_indexes:
                raise ValueError("provider state lacks a successful product-index attempt")
        if provider["state"] == "failed" and not any(
            item["context"].get("phase") == "products_index" for item in attempts
        ):
            raise ValueError("failed provider lacks a product-index attempt")

    product_evidence = journal_product_evidence(journal)
    for product in accounting["products"]:
        key = (directories[product["provider_uid"]], product["cdr_product_id"])
        available = {
            item["body_sha256"] for item in product_evidence.get(key, ())
        }
        if not set(product["evidence_ids"]) <= available:
            raise ValueError(
                "product evidence does not resolve to its verified journal attempts"
            )
