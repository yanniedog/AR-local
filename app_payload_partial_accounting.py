"""Admit classified partial observations without an arbitrary failure quota.

This supplements the legacy bounded policy. Callers must still verify the
completion marker, ledger event and every retained artifact before publication.
It does not turn a partial observation into a complete one.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from cdr_export_contract import (
    contract_digest, generation_id_for, source_generation_digest, validate_contract,
)

CLASSIFIED_FAILURES = frozenset({
    "endpoint_not_found", "product_inactive", "incompatible_version",
    "public_endpoint_auth_required", "access_denied", "transient_upstream",
    "transport", "upstream_schema_invalid", "upstream_rejection", "invalid_response",
})


def _count(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("Accounting requires nonnegative integers")
    return value


def _provider_totals(providers: list) -> dict[str, int]:
    totals = Counter(failure_records=0, providers_complete=0,
                     providers_partial=0, providers_failed=0)
    for provider in providers:
        state = provider["state"]
        if state not in {"complete", "empty", "partial", "failed"}:
            raise ValueError("Every registered provider must be attempted")
        failures = _count(provider.get("failure_records"))
        categories = provider.get("failure_categories")
        if not isinstance(categories, Mapping) or set(categories) - CLASSIFIED_FAILURES:
            raise ValueError("Failure classifications are incomplete or unsafe")
        if sum(_count(value) for value in categories.values()) != failures:
            raise ValueError("Failure categories do not reconcile")
        if (state in {"complete", "empty"}) != (failures == 0):
            raise ValueError("Provider state contradicts its failure accounting")
        totals["failure_records"] += failures
        totals["providers_complete" if state == "empty" else f"providers_{state}"] += 1
    return dict(totals)


def reconciled_partial_v1_allowed(contract: Mapping[str, Any]) -> bool:
    """Require the complete sealed contract and exact provider reconciliation."""
    try:
        validate_contract(contract)
        source = source_generation_digest(contract)
        if (contract["observation_state"] != "partial" or contract["quarantines"]
                or not contract["register_hashes"]
                or source != contract["source_generation_digest"]
                or contract_digest(contract) != contract["contract_digest"]
                or generation_id_for(contract["observation_date"], source,
                                     contract["prior_ledger_head"]) != contract["generation_id"]):
            return False
        coverage, providers = contract["coverage"], contract["provider_states"]
        totals = _provider_totals(providers)
        return (
            coverage.get("failure_provenance_complete") is True
            and coverage.get("register_provenance_complete") is True
            and coverage.get("reconciliation_status") == "partial"
            and _count(coverage.get("corrupt_failure_records")) == 0
            and _count(coverage.get("unattributed_failure_records")) == 0
            and _count(coverage.get("products_discovered")) > 0
            and _count(coverage.get("eligible_rate_rows")) > 0
            and len(providers) == _count(coverage.get("providers_registered"))
            == _count(coverage.get("providers_attempted")) > 0
            and _count(coverage.get("register_sources_attempted"))
            == _count(coverage.get("register_sources_complete")) > 0
            and totals["failure_records"] > 0
            and all(total == _count(coverage.get(key)) for key, total in totals.items())
        )
    except (KeyError, TypeError, ValueError):
        return False
