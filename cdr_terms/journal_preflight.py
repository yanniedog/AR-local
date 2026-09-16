"""Bind a private journal subset to finalization without issuing a capture."""
from __future__ import annotations

import json
from typing import Any, Mapping

from cdr_clean_export import bank_product_key, inner_record, text
from cdr_ledger_v2 import _validate_event

from .journal_sources import JournalSource


def verify_finalization(contract: Mapping[str, Any], marker: Mapping[str, Any],
                        event: Mapping[str, Any], *, detail_products: int) -> dict[str, Any]:
    """Caller supplies a load_contract-validated contract and verified details.

    Count agreement is necessary, not proof of product-by-product accounting.
    This result never grants completed-capture or full-population authority.
    """
    _validate_event(event)
    if marker.get("finalization_schema_version") != 2 or marker.get("ledger_state") != "finalized":
        raise ValueError("journal_finalization_marker_invalid")
    bindings = (
        ("generation_id", "generation_id", "generation_id"),
        ("contract_digest", "export_contract_digest", "contract_digest"),
        ("observation_date", "run_date", "observation_date"),
        ("observation_state", "observation_state", "observation_state"),
    )
    for contract_key, marker_key, event_key in bindings:
        expected = contract.get(contract_key)
        if expected is None or marker.get(marker_key) != expected or event.get(event_key) != expected:
            raise ValueError("journal_finalization_identity_mismatch")
    if (marker.get("ledger_event_digest") != event["event_digest"]
            or marker.get("export_contract_path") != event.get("contract_path")
            or contract.get("prior_ledger_head") != event.get("previous_event_digest")):
        raise ValueError("journal_finalization_ledger_binding_mismatch")
    coverage = contract.get("coverage", {})
    counts = (detail_products, marker.get("banks", {}).get("products"), coverage.get("products_discovered"))
    if (any(type(n) is not int or n < 1 for n in counts) or len(set(counts)) != 1):
        raise ValueError("journal_finalization_product_count_mismatch")
    return {
        "status": "FINALIZATION_AND_DETAIL_COUNT_VERIFIED",
        "generation_id": contract["generation_id"],
        "contract_digest": contract["contract_digest"],
        "ledger_event_digest": event["event_digest"],
        "observed_at": contract["observed_at"],
        "observation_state": contract["observation_state"],
        "detail_products": detail_products,
        "providers_partial": coverage.get("providers_partial"),
        "unavailable_populations": list(coverage.get("unavailable_populations", [])),
        "product_accounting_reconciled": False,
        "capture_authorized": False,
    }


def product_identity_index(contract: Mapping[str, Any], sources: tuple[JournalSource, ...]) -> list[dict[str, str]]:
    """Reconcile selected response providers and existing export-key semantics."""
    providers: dict[str, str] = {}
    for provider in contract.get("provider_states", []):
        directory, uid = provider.get("provider_dir"), provider.get("provider_uid")
        if not isinstance(directory, str) or not directory or not isinstance(uid, str) or not uid or directory in providers:
            raise ValueError("journal_provider_directory_ambiguous")
        providers[directory] = uid
    result = []
    keys: set[str] = set()
    for source in sources:
        if source.provider not in providers:
            raise ValueError("journal_provider_not_in_contract")
        record = inner_record(json.loads(source.body))
        row = {"provider": source.provider, "product_id": source.product_id,
               "category": text(record.get("productCategory") or record.get("category")),
               "product_name": text(record.get("name") or record.get("productName"))}
        if not row["product_name"]:
            raise ValueError("journal_product_name_requires_source_path_review")
        key = bank_product_key(row)
        if key in keys:
            raise ValueError("journal_product_key_collision")
        keys.add(key)
        result.append({"provider_uid": providers[source.provider], "provider": source.provider,
                       "product_id": source.product_id, "product_key": key,
                       "sha256": source.sha256, "event_path": source.event_path})
    return result
