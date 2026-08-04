"""Build the small, historical fallback consumed by AR-app.

The daily payload remains canonical. This producer selects a representative
subset solely for offline first-run recovery and writes a self-contained local
manifest; it must never be presented as current or complete market coverage.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import payload_crypto
from cdr_ribbon_normalize import aggregate_ribbon, effective_rate, normalized_rate_value


# Keep the bounded producer aligned with the app's cheap, core-only
# `isBroadlyAvailable` predicate. Structured eligibility is not present in the
# core payload, so these are deliberately the same product/name safeguards the
# app applies before details have loaded.
_CURATED_NON_STANDARD_PRODUCTS = {
    "racq": {"green home loan", "green home loan investment"},
    "westpac": {
        "sustainable upgrades home loan",
        "sustainable upgrades investment",
        "sustainable upgrades investment loan",
    },
}
_NAME_RESTRICTS_ACCESS = re.compile(
    r"\b(staff|employe[er]|colleague)\b"
    r"|\b(police|nurs(?:e|es|ing)|teacher|educator(?:s)?|doctor|health\s*(?:care|sector|worker)|medical|defence|defense|military|navy|army|veteran|firefighter|ambulance|paramedic|emergency\s*services|first\s*responder)\b"
    r"|\bmembers?\s+of\b|\bassociation\b|\bunion\b|\balumni\b|\bdiocese\b|\bparish\b"
    r"|\b(business|commercial|corporate|company|smsf|self[-\s]?managed\s+super|trust)\b"
    r"|\bstudent[s]?\b"
    r"|\bresidents?\s+of\b|\bonly\s+available\s+in\b",
    re.IGNORECASE,
)


def _is_broadly_available(row: dict[str, Any]) -> bool:
    if row.get("account_class") == "non_standard":
        return False
    provider = str(row.get("provider") or "").strip().lower()
    provider_key = "racq" if "racq" in provider else "westpac" if "westpac" in provider else ""
    product_name = str(row.get("product_name") or "").strip()
    if product_name.lower() in _CURATED_NON_STANDARD_PRODUCTS.get(provider_key, set()):
        return False
    return not bool(_NAME_RESTRICTS_ACCESS.search(product_name))


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _read_verified_payload(payload_dir: Path, manifest: dict[str, Any], kind: str) -> dict[str, Any]:
    entry = manifest["files"][kind]
    compressed = (payload_dir / entry["name"]).read_bytes()
    if len(compressed) != int(entry["bytes"]):
        raise ValueError(f"{kind} compressed byte count does not match manifest")
    if hashlib.sha256(compressed).hexdigest() != entry["sha256"]:
        raise ValueError(f"{kind} compressed SHA-256 does not match manifest")
    encryption = entry.get("enc") or manifest.get("enc")
    if encryption or compressed.startswith(payload_crypto.MAGIC):
        key_path = Path(
            os.environ.get(payload_crypto.ENV_KEY_FILE) or payload_crypto.DEFAULT_KEY_FILE
        )
        key = payload_crypto.load_key(key_path)
        expected_key_id = (encryption or {}).get("key_id")
        if expected_key_id and payload_crypto.key_id(key) != expected_key_id:
            raise ValueError(f"{kind} payload encryption key id does not match manifest")
        compressed = payload_crypto.decrypt_asset(compressed, key)
    value = json.loads(gzip.decompress(compressed))
    if not isinstance(value, dict):
        raise ValueError(f"{kind} payload must be an object")
    return value


def _normalized_rates(
    rows: list[dict[str, Any]], section: str
) -> dict[int, float | None]:
    percent_style: set[str] = set()
    for row in rows:
        key = str(row.get("product_key") or "")
        try:
            raw = float(effective_rate(row))
        except (TypeError, ValueError):
            continue
        if key and raw > 1:
            percent_style.add(key)
    return {
        id(row): normalized_rate_value(
            effective_rate(row), section, str(row.get("product_key") or "") in percent_style
        )
        for row in rows
    }


def _representative_rows(rows: list[dict[str, Any]], section: str) -> list[dict[str, Any]]:
    by_provider: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_provider.setdefault(str(row.get("provider") or ""), []).append(row)
    selected: list[dict[str, Any]] = []
    reverse = section != "Mortgage"
    rates = _normalized_rates(rows, section)
    for provider_rows in by_provider.values():
        ranked = sorted(
            provider_rows,
            key=lambda row: rates[id(row)]
            if rates[id(row)] is not None
            else float("-inf") if reverse else float("inf"),
            reverse=reverse,
        )
        # Preserve at least one broadly available product when the provider has
        # one, so the app's default Standard-only filter does not erase that
        # provider from the representative fallback.
        broadly_available = [row for row in ranked if _is_broadly_available(row)]
        candidates = [*broadly_available[:1], *ranked]
        product_keys: set[str] = set()
        for row in candidates:
            if rates[id(row)] is None:
                continue
            key = str(row.get("product_key") or "")
            if not key or key in product_keys:
                continue
            selected.append(row)
            product_keys.add(key)
            if len(product_keys) == 2:
                break
    return selected


def _section(rows: list[dict[str, Any]], name: str) -> dict[str, Any]:
    selected = _representative_rows(rows, name)
    return {
        "rates": selected,
        "ribbon": aggregate_ribbon(selected, name),
    }


def build_app_sample(payload_dir: Path, output_dir: Path) -> dict[str, Any]:
    source_manifest = json.loads((payload_dir / "manifest.json").read_text(encoding="utf-8"))
    if source_manifest.get("schema_version") != 1:
        raise ValueError("manifest, core, and details must use supported schema_version 1")
    core = _read_verified_payload(payload_dir, source_manifest, "core")
    details = _read_verified_payload(payload_dir, source_manifest, "details")
    if any(
        value.get("schema_version") != 1
        for value in (source_manifest, core, details)
    ):
        raise ValueError("manifest, core, and details must use supported schema_version 1")
    run_date = str(source_manifest.get("run_date") or "")
    if not run_date or core.get("run_date") != run_date or details.get("run_date") != run_date:
        raise ValueError("manifest, core, and details run_date values must match")

    sections = {
        name: _section(list(section.get("rates") or []), name)
        for name, section in core["sections"].items()
    }
    selected_keys = {
        str(row["product_key"])
        for section in sections.values()
        for row in section["rates"]
    }
    selected_rate_count = sum(len(section["rates"]) for section in sections.values())
    if not selected_keys or selected_rate_count <= 0:
        raise ValueError("refusing to replace the bundled fallback with an empty sample")
    products = {
        key: value for key, value in details["products"].items() if key in selected_keys
    }
    providers = {
        str(row["provider"])
        for section in sections.values()
        for row in section["rates"]
    }
    source_coverage = core.get("coverage") if isinstance(core.get("coverage"), dict) else {}
    coverage_sections = {
        name: {
            "rates": len(section["rates"]),
            "products": len({str(row["product_key"]) for row in section["rates"]}),
            "providers": len({str(row["provider"]) for row in section["rates"]}),
        }
        for name, section in sections.items()
    }
    limitations = [
        *(source_coverage.get("limitations") or []),
        "Bundled sample only: up to two representative published products per provider and section; not a complete or current market view.",
    ]
    sample_counts = {
        "providers": len(providers),
        "products": len(selected_keys),
        "rates": selected_rate_count,
        "failures": int(source_manifest.get("counts", {}).get("failures") or 0),
    }
    sample_coverage = {
        **source_coverage,
        "schema_version": 1,
        "observed_on": run_date,
        "observed_at": source_coverage.get("observed_at") or source_manifest.get("generated_at"),
        "counts": source_coverage.get("counts") or sample_counts,
        "sample_counts": sample_counts,
        "sections": source_coverage.get("sections") or coverage_sections,
        "sample_sections": coverage_sections,
        "provider_failures": list(source_coverage.get("provider_failures") or []),
        "failures": list(
            source_coverage.get("failures")
            or source_coverage.get("provider_failures")
            or []
        ),
        "limitations": limitations,
    }
    if not source_coverage:
        sample_coverage.update(
            providers_attempted=len(providers),
            providers_succeeded=len(providers),
            failure_provenance_complete=False,
        )
    sample_core: dict[str, Any] = {
        **core,
        "sections": sections,
        "brands": {key: value for key, value in core.get("brands", {}).items() if key in providers},
        "coverage": sample_coverage,
    }
    sample_details = {**details, "products": products}
    encoded = {"core": _json_bytes(sample_core), "details": _json_bytes(sample_details)}

    def local_entry(kind: str) -> dict[str, Any]:
        name = f"{kind}.json"
        return {
            "name": name,
            "bytes": len(encoded[kind]),
            "sha256": hashlib.sha256(encoded[kind]).hexdigest(),
            "url": f"bundled://sample/{name}",
        }

    detail_values = list(products.values())
    manifest = {
        "schema_version": 1,
        "run_date": run_date,
        "generated_at": source_manifest.get("generated_at") or f"{run_date}T00:00:00Z",
        "app_min_version": source_manifest.get("app_min_version") or "1.0.0",
        "repo": "yanniedog/AR-local",
        "tag": "bundled-sample",
        "counts": {
            "products": len(selected_keys),
            "providers": len(providers),
            "rates": selected_rate_count,
            "fees": sum(len(item.get("fees") or []) for item in detail_values),
            "features": sum(len(item.get("features") or []) for item in detail_values),
            "eligibility": sum(len(item.get("eligibility") or []) for item in detail_values),
            "constraints": sum(len(item.get("constraints") or []) for item in detail_values),
            "failures": int(source_manifest.get("counts", {}).get("failures") or 0),
        },
        "schedule": {"label": "Bundled historical sample; no live update schedule"},
        "files": {"core": local_entry("core"), "details": local_entry("details")},
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    for kind, data in encoded.items():
        (output_dir / f"{kind}.json").write_bytes(data)
    (output_dir / "manifest.json").write_bytes(_json_bytes(manifest))
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload_dir", type=Path, help="Verified AR-local app-payload directory")
    parser.add_argument("output_dir", type=Path, help="Output directory for core.json/details.json/manifest.json")
    args = parser.parse_args()
    manifest = build_app_sample(args.payload_dir.resolve(), args.output_dir.resolve())
    print(
        f"[app_sample] wrote run_date={manifest['run_date']} "
        f"products={manifest['counts']['products']} rates={manifest['counts']['rates']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
