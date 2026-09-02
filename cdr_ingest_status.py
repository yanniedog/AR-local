"""Build the final, auditable ingest-status document."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cdr_atomic import atomic_write_json
from cdr_ingest_support import RegisterSnapshot, summarize_failures
from cdr_raw_attempt_journal import RawAttemptJournal


def _population_counts(population: dict[str, Any]) -> tuple[int, int, int, list[str]]:
    unique = population.get("unique_product_ids")
    relevant = population.get("relevant_products")
    unresolved = population.get("classification_unresolved", [])
    if (
        isinstance(unique, bool)
        or not isinstance(unique, int)
        or unique < 0
        or isinstance(relevant, bool)
        or not isinstance(relevant, int)
        or relevant < 0
        or not isinstance(unresolved, list)
        or not all(isinstance(item, str) and item for item in unresolved)
        or len(unresolved) != len(set(unresolved))
    ):
        raise ValueError("invalid holder population counts")
    out_of_scope = population.get(
        "out_of_scope_products", unique - relevant - len(unresolved)
    )
    if (
        isinstance(out_of_scope, bool)
        or not isinstance(out_of_scope, int)
        or out_of_scope < 0
        or relevant + out_of_scope + len(unresolved) != unique
    ):
        raise ValueError("holder product classification does not reconcile")
    return unique, relevant, out_of_scope, unresolved


def _provider_state(
    banks_root: Path,
    brand: dict[str, str],
    directory: str,
    failures: int,
) -> tuple[dict[str, Any], bool, int]:
    summary_path = (
        banks_root / "_holders" / directory / "_products-index" / "index-summary.json"
    )
    complete = True
    try:
        population = json.loads(summary_path.read_text(encoding="utf-8"))
        if (
            not isinstance(population, dict)
            or population.get("schema_version") != 1
            or population.get("provider_uid") != brand["provider_uid"]
        ):
            raise ValueError("invalid holder population summary")
        state = str(population.get("state") or "failed")
        if state not in {"complete", "empty", "partial", "failed"}:
            raise ValueError("invalid holder state")
        population_known = population.get("population_known")
        if not isinstance(population_known, bool):
            raise ValueError("invalid holder population knowledge")
        unique, relevant, out_of_scope, unresolved = _population_counts(population)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        population, state = {}, "failed"
        unique = relevant = out_of_scope = None
        unresolved = []
        population_known = False
        complete = False
    if unresolved or not population_known:
        complete = False
    if failures and state in {"complete", "empty"}:
        state = "partial"
    return (
        {
            "provider_uid": brand["provider_uid"],
            "identity_status": brand["provider_identity_status"],
            "data_holder_id": brand.get("data_holder_id") or None,
            "data_holder_brand_id": brand.get("data_holder_brand_id") or None,
            "interim_id": brand.get("interim_id") or None,
            "brand_name": brand.get("brand_name") or None,
            "legal_entity_name": brand.get("legal_entity_name") or None,
            "endpoint_url": brand.get("endpoint_url") or None,
            "state": state,
            "failure_records": failures,
            "population_known": population_known,
            "products_discovered": unique,
            "products_in_scope": relevant,
            "products_out_of_scope": out_of_scope,
            "products_unresolved": len(unresolved),
            "products_indexed": unique,
            "details_present": population.get("details_present"),
        },
        complete,
        len(unresolved),
    )


def persist_ingest_status(
    *,
    banks_root: Path,
    run_root: Path,
    snapshot: RegisterSnapshot,
    bank_work: list[tuple[dict[str, str], str]],
    attempt_journal: RawAttemptJournal,
) -> dict[str, Any]:
    """Publish a discoverable evidence pointer on success and every early exit."""

    banks_root.mkdir(parents=True, exist_ok=True)
    status = summarize_failures(banks_root)
    status["register_attempts"] = snapshot.register_attempts
    status["register_provenance_complete"] = snapshot.register_provenance_complete
    status["failure_provenance_complete"] = bool(
        status.get("failure_provenance_complete")
        and snapshot.register_provenance_complete
    )
    status["incomplete"] = bool(
        status.get("incomplete") or not snapshot.register_provenance_complete
    )
    by_provider = status.get("by_provider") or {}
    provider_states = []
    coverage_complete = True
    unresolved_total = 0
    for brand, directory in bank_work:
        provider, complete, unresolved = _provider_state(
            banks_root,
            brand,
            directory,
            int(by_provider.get(directory) or 0),
        )
        provider_states.append(provider)
        coverage_complete = coverage_complete and complete
        unresolved_total += unresolved
    scope_complete = len(bank_work) == snapshot.banking_count_before_filter
    status.update(
        {
            "providers_registered": snapshot.banking_count_before_filter,
            "providers_available": snapshot.banking_count_before_filter,
            "providers_attempted": len(bank_work),
            "provider_states": provider_states,
            "provider_scope_complete": scope_complete,
            "coverage_evidence_complete": coverage_complete and scope_complete,
            "classification_unresolved_products": unresolved_total,
            "provider_state_counts": {
                state: sum(1 for provider in provider_states if provider["state"] == state)
                for state in ("complete", "empty", "partial", "failed")
            },
        }
    )
    status["incomplete"] = bool(
        status["incomplete"]
        or not coverage_complete
        or not scope_complete
        or any(provider["state"] not in {"complete", "empty"} for provider in provider_states)
    )
    attempt_summary = attempt_journal.summary()
    attempt_summary.update(
        {
            "path": attempt_journal.root.relative_to(run_root).as_posix(),
            "path_resolution": "relative_to_ingest_run_root",
            "retention": "follows_ingest_run_root",
        }
    )
    status["raw_attempt_journal"] = attempt_summary
    atomic_write_json(banks_root / "ingest-status.json", status)
    return status
