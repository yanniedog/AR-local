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
        coverage = contract["coverage"]
        if any(type(coverage.get(key)) is not int or coverage[key] <= 0
               for key in ("products_discovered", "eligible_rate_rows")):
            return False
        return (source_generation_digest(contract) == contract["source_generation_digest"]
                and contract_digest(contract) == contract["contract_digest"])
    except (KeyError, TypeError, ValueError):
        return False


def public_population_findings(findings: list) -> list[dict]:
    """Disclose uncertainty without copying private historical transport data."""
    if not isinstance(findings, list) or any(not isinstance(row, Mapping) for row in findings):
        raise ValueError("invalid provider population findings")
    fields = ("provider", "provider_uid", "population_known", "disposition",
              "current_register_membership")
    result = []
    for row in findings:
        public = {key: row[key] for key in fields if key in row
                  and (row[key] is None or type(row[key]) in (str, bool))}
        last = row.get("last_nonempty")
        if isinstance(last, Mapping):
            public["last_nonempty"] = {key: last[key] for key in ("observation_date", "products", "rates")
                                      if key in last and type(last[key]) in (str, int)}
        result.append(public)
    return result
