"""Standing publication policy for the best available retained daily capture.

The 2026-11-07 operator decision, already implemented by the scheduled
pi-payload-backfill workflow, covers observed dates from 2026-10-29 onwards.
Partial coverage is disclosed, never relabelled complete. Admission does not
replace the caller's marker, ledger, artifact and selected-source verification.
"""
from __future__ import annotations

from typing import Any, Mapping

from cdr_export_contract import contract_digest, source_generation_digest, validate_contract

AUTHORISED_FROM = "2026-10-29"
POLICY_ID = "best-available-retained-v1"


def retained_partial_allowed(contract: Mapping[str, Any]) -> bool:
    """Apply the standing policy only to an intact sealed partial contract."""
    try:
        if (contract.get("observation_state") != "partial"
                or str(contract.get("observation_date") or "") < AUTHORISED_FROM):
            return False
        validate_contract(contract)
        return (source_generation_digest(contract) == contract["source_generation_digest"]
                and contract_digest(contract) == contract["contract_digest"])
    except (KeyError, TypeError, ValueError):
        return False
