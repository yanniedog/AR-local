"""Runtime contract validation and cohort metadata for optional app payloads."""
from __future__ import annotations

from typing import Any, Mapping

MAX_V2_MANIFEST_BYTES = 64 * 1024
MAX_V2_ASSET_BYTES = {
    "product_history": 32 * 1024 * 1024,
    "economic_outlook": 2 * 1024 * 1024,
}
MAX_V2_ASSET_UNCOMPRESSED_BYTES = {
    "product_history": 256 * 1024 * 1024,
    "economic_outlook": 16 * 1024 * 1024,
}
MAX_COVERAGE_FAILURE_GROUPS = 2_000
MAX_HISTORY_DATES = 2_000
MAX_HISTORY_PRODUCTS = 100_000
MAX_ECONOMIC_SERIES = 64

STANDARD_COHORT = {
    "id": "standard",
    "label": "Standard retail products",
    "account_class": "standard",
    "composition": "observed products classified as standard on each observation date",
}

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


def validate_product_history(value: Any) -> None:
    if not isinstance(value, Mapping) or value.get("schema_version") != 2:
        raise ValueError("product_history must be a schema_version 2 object")
    dates = value.get("run_dates")
    products = value.get("products")
    if not isinstance(dates, list) or dates != sorted(set(dates)):
        raise ValueError("product_history.run_dates must be unique and ascending")
    if not isinstance(products, Mapping):
        raise ValueError("product_history.products is required")
    if len(dates) > MAX_HISTORY_DATES or len(products) > MAX_HISTORY_PRODUCTS:
        raise ValueError("product_history exceeds the contract size limits")
    if any(not isinstance(series, list) or len(series) != len(dates) for series in products.values()):
        raise ValueError("every product history series must align to run_dates")
    if (value.get("cohort") or {}).get("id") != "standard":
        raise ValueError("product_history must declare the standard cohort")


def validate_economic_outlook(value: Any) -> None:
    if not isinstance(value, Mapping) or value.get("schema_version") != 1:
        raise ValueError("economic_outlook must be a schema_version 1 object")
    if value.get("kind") != "observed_economic_indicators":
        raise ValueError("economic_outlook.kind is invalid")
    if not str(value.get("generated_at") or ""):
        raise ValueError("economic_outlook.generated_at is required")
    if not isinstance(value.get("series"), list):
        raise ValueError("economic_outlook.series must be a list")
    if len(value["series"]) > MAX_ECONOMIC_SERIES:
        raise ValueError("economic_outlook.series exceeds the contract limit")
    if any(len(item.get("observations") or []) > 2 for item in value["series"]):
        raise ValueError("economic_outlook series may contain at most two observations")


def validate_v2_manifest(value: Any) -> None:
    if not isinstance(value, Mapping) or value.get("schema_version") != 2:
        raise ValueError("manifest-v2 must be a schema_version 2 object")
    base = value.get("base")
    files = value.get("files")
    if not isinstance(base, Mapping) or not all(base.get(key) for key in ("core_sha", "details_sha")):
        raise ValueError("manifest-v2.base must bind core and details hashes")
    if not isinstance(files, Mapping) or "product_history" not in files:
        raise ValueError("manifest-v2.files.product_history is required")
    if set(files) - set(MAX_V2_ASSET_BYTES):
        raise ValueError("manifest-v2 contains an unknown capability")
    if sorted(value.get("capabilities") or []) != sorted(files):
        raise ValueError("manifest-v2 capabilities must exactly match files")
    for kind, entry in files.items():
        required = ("name", "sha256", "bytes", "uncompressed_bytes", "encoding", "url")
        if not isinstance(entry, Mapping) or not all(entry.get(k) for k in required):
            raise ValueError("manifest-v2 file entries are incomplete")
        if entry["encoding"] != "gzip":
            raise ValueError("manifest-v2 assets must use gzip encoding")
        if int(entry["bytes"]) > MAX_V2_ASSET_BYTES[kind]:
            raise ValueError(f"manifest-v2 {kind} exceeds the compressed size limit")
        if int(entry.get("uncompressed_bytes") or 0) > MAX_V2_ASSET_UNCOMPRESSED_BYTES[kind]:
            raise ValueError(f"manifest-v2 {kind} exceeds the uncompressed size limit")
