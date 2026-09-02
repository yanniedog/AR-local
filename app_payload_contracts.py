"""Runtime validation for the public v1 payload."""
from __future__ import annotations

from typing import Any, Mapping

MAX_COVERAGE_FAILURE_GROUPS = 2_000

ALL_PRODUCTS_COHORT = {
    "id": "all",
    "label": "All observed products",
    "account_class": "all",
    "composition": "all observed products passing the section rate filter",
}


def validate_coverage(value: Any) -> None:
    if not isinstance(value, Mapping) or value.get("schema_version") != 1:
        raise ValueError("coverage must be a schema_version 1 object")
    if not str(value.get("observed_on") or ""):
        raise ValueError("coverage.observed_on is required")
    if not isinstance(value.get("counts"), Mapping):
        raise ValueError("coverage.counts is required")
    if not isinstance(value.get("sections"), Mapping):
        raise ValueError("coverage.sections is required")
    if not isinstance(value.get("provider_failures"), list):
        raise ValueError("coverage.provider_failures must be a list")
    if len(value["provider_failures"]) > MAX_COVERAGE_FAILURE_GROUPS:
        raise ValueError("coverage.provider_failures exceeds the contract limit")
    if "failures" in value and not isinstance(value.get("failures"), list):
        raise ValueError("coverage.failures must be a list when present")
    if len(value.get("failures") or []) > MAX_COVERAGE_FAILURE_GROUPS:
        raise ValueError("coverage.failures exceeds the contract limit")
    for field in ("providers_attempted", "providers_succeeded"):
        if field in value and (not isinstance(value[field], int) or value[field] < 0):
            raise ValueError(f"coverage.{field} must be a non-negative integer")
