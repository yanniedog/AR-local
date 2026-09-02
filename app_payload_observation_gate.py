"""One publication policy for every app-payload path.

Two things used to decide independently whether a run may reach GitHub:
``pi_daily_sync`` (contract-gated) and ``scripts/backfill_app_payload.py`` (not
gated at all).  That is how the broken 2026-08-15 observation — 1,195 failure
records against 1,856 products — became a public dated release while the daily
path was correctly refusing it.  Both callers now share the predicates here.

The gate reads the export-contract v2 written by ``cdr_finalization``: the
audited, ledger-bound account of the run.  It is deliberately the *only*
accounting allowed to authorise a publication.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

# Compatibility v1 is allowed to advance from a fully-audited partial
# observation only inside these deliberately narrow bounds.
# Sized against observed production days rather than a round number. On
# 2026-08-16 a healthy run recorded 17 failure records across 3,035 products with
# 7 of 118 providers partial; a broken run the day before recorded 1,195 records
# with 34 of 118 partial. The absolute floor exists only to stop a tiny catalogue
# slipping through on ratio alone — for a catalogue this size the 1% ratio is the
# real gate, and a genuinely broken day misses every bound by an order of
# magnitude.
PARTIAL_V1_MAX_FAILURE_RECORDS = 50
PARTIAL_V1_MAX_FAILURE_RATIO = 0.01
PARTIAL_V1_MAX_PARTIAL_PROVIDER_RATIO = 0.15

CONTRACT_DIRNAME = "export-contracts-v2"


def bounded_partial_v1_allowed(contract: Mapping[str, Any]) -> bool:
    """Allow a current v1 payload without mislabelling the observation complete."""
    if contract.get("observation_state") != "partial":
        return False
    coverage = contract.get("coverage")
    if not isinstance(coverage, Mapping):
        return False
    try:
        failures = int(coverage.get("failure_records") or 0)
        corrupt = int(coverage.get("corrupt_failure_records") or 0)
        unattributed = int(coverage.get("unattributed_failure_records") or 0)
        products = int(coverage.get("products_discovered") or 0)
        registered = int(coverage.get("providers_registered") or 0)
        attempted = int(coverage.get("providers_attempted") or 0)
        partial = int(coverage.get("providers_partial") or 0)
        failed = int(coverage.get("providers_failed") or 0)
        register_attempted = int(coverage.get("register_sources_attempted") or 0)
        register_complete = int(coverage.get("register_sources_complete") or 0)
    except (TypeError, ValueError):
        return False
    return (
        coverage.get("failure_provenance_complete") is True
        and coverage.get("register_provenance_complete") is True
        and corrupt == 0
        and unattributed == 0
        and products > 0
        and registered > 0
        and attempted == registered
        and register_attempted > 0
        and register_complete == register_attempted
        and failed == 0
        and 0 <= failures <= PARTIAL_V1_MAX_FAILURE_RECORDS
        and failures / products <= PARTIAL_V1_MAX_FAILURE_RATIO
        and partial / registered <= PARTIAL_V1_MAX_PARTIAL_PROVIDER_RATIO
    )


def publication_allowed(contract: Optional[Mapping[str, Any]]) -> Tuple[bool, str]:
    """Return ``(allowed, reason)`` for one observation's v1 publication."""
    if not isinstance(contract, Mapping) or not contract:
        return False, "missing_export_contract"
    state = str(contract.get("observation_state") or "unknown")
    if state == "complete":
        return True, "complete"
    if state == "partial":
        if bounded_partial_v1_allowed(contract):
            return True, "bounded_partial"
        return False, "outside_bounded_v1_policy"
    return False, f"observation_state={state}"


def contract_coverage(contract: Optional[Mapping[str, Any]]) -> Optional[dict]:
    """The audited coverage block, when the contract carries one."""
    if not isinstance(contract, Mapping):
        return None
    coverage = contract.get("coverage")
    return dict(coverage) if isinstance(coverage, Mapping) else None


def contract_for_run_date(state_dir: Path, run_date: str) -> Optional[dict]:
    """Newest export contract written for ``run_date``, or None.

    ``cdr_finalization`` writes one contract per generation under
    ``<state>/export-contracts-v2/<run_date>/<generation_id>.json``. A revised day
    has several; the newest ``generated_at`` is the one the exports on disk
    correspond to. Ordering falls back to the filename so a contract missing the
    timestamp still sorts deterministically rather than at random.
    """
    directory = state_dir / CONTRACT_DIRNAME / run_date
    if not directory.is_dir():
        return None
    newest: Optional[dict] = None
    newest_key: Tuple[str, str] = ("", "")
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        key = (str(payload.get("generated_at") or ""), path.name)
        if newest is None or key > newest_key:
            newest, newest_key = payload, key
    return newest
