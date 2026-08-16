"""Enforce and report mobile payload transfer budgets.

Budgets apply to compressed/encrypted release bytes, which are the bytes a
phone actually downloads.  They deliberately fail payload packaging without
affecting the already-finalized daily ingest (Pi publication is non-fatal).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

KIB = 1024
MIB = 1024 * KIB

MANIFEST_MAX_BYTES = 64 * KIB
CORE_MAX_BYTES = 512 * KIB
DETAILS_MAX_BYTES = 4 * MIB
SEARCH_INDEX_MAX_BYTES = 2 * MIB
OTHER_ASSET_MAX_BYTES = 1 * MIB
ROLLING_TOTAL_MAX_BYTES = 8 * MIB
V2_PRODUCT_HISTORY_MAX_BYTES = 8 * MIB
V2_ECONOMIC_OUTLOOK_MAX_BYTES = 1 * MIB
V2_TOTAL_MAX_BYTES = 9 * MIB
TRANSFER_SPEEDS_MBPS = (0.5, 1.0, 5.0, 20.0)


def transfer_seconds(byte_count: int, mbps: float) -> float:
    if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 0:
        raise ValueError("payload bytes must be a non-negative integer")
    if mbps <= 0:
        raise ValueError("transfer speed must be positive")
    return byte_count * 8 / (mbps * 1_000_000)


def _declared_bytes(key: str, entry: Any) -> int:
    if not isinstance(entry, Mapping):
        raise ValueError(f"payload file {key!r} is not an object")
    value = entry.get("bytes")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"payload file {key!r} bytes must be a positive integer")
    return value


def _asset_cap(key: str) -> int:
    if key == "core":
        return CORE_MAX_BYTES
    if key == "details":
        return DETAILS_MAX_BYTES
    if key == "search_index":
        return SEARCH_INDEX_MAX_BYTES
    return OTHER_ASSET_MAX_BYTES


def validate_payload_network_budget(
    manifest: Mapping[str, Any],
    *,
    manifest_bytes: int,
    asset_root: Path | None = None,
) -> dict[str, Any]:
    if manifest_bytes <= 0 or manifest_bytes > MANIFEST_MAX_BYTES:
        raise ValueError(
            f"payload manifest bytes {manifest_bytes} exceed {MANIFEST_MAX_BYTES}"
        )
    files = manifest.get("files")
    if not isinstance(files, Mapping) or "core" not in files or "details" not in files:
        raise ValueError("payload manifest must declare core and details files")

    sizes: dict[str, int] = {}
    for key, entry in files.items():
        size = _declared_bytes(str(key), entry)
        cap = _asset_cap(str(key))
        if size > cap:
            raise ValueError(f"payload {key} bytes {size} exceed {cap}")
        if asset_root is not None:
            name = str(entry.get("name") or "")
            path = asset_root / name
            if not name or not path.is_file() or path.stat().st_size != size:
                raise ValueError(f"payload {key} local bytes do not match the manifest")
        sizes[str(key)] = size

    total = sum(sizes.values())
    if total > ROLLING_TOTAL_MAX_BYTES:
        raise ValueError(f"payload total bytes {total} exceed {ROLLING_TOTAL_MAX_BYTES}")

    critical = sizes["core"]
    current_home = critical + sizes["details"]
    deep_search = current_home + sizes.get("search_index", 0)
    journeys = {
        "critical_core": critical,
        "current_standard_home": current_home,
        "deep_search": deep_search,
        "all_declared_assets": total,
    }
    return {
        "schema_version": 1,
        "asset_bytes": sizes,
        "journeys": {
            name: {
                "bytes": byte_count,
                "seconds": {
                    f"{speed:g}_mbps": round(transfer_seconds(byte_count, speed), 3)
                    for speed in TRANSFER_SPEEDS_MBPS
                },
            }
            for name, byte_count in journeys.items()
        },
    }


def validate_v2_network_budget(
    manifest: Mapping[str, Any],
    *,
    manifest_bytes: int,
    asset_root: Path | None = None,
) -> dict[str, Any]:
    if manifest_bytes <= 0 or manifest_bytes > MANIFEST_MAX_BYTES:
        raise ValueError("manifest-v2 exceeds the network budget")
    files = manifest.get("files")
    if not isinstance(files, Mapping) or not files:
        raise ValueError("manifest-v2 must declare at least one capability")
    caps = {
        "product_history": V2_PRODUCT_HISTORY_MAX_BYTES,
        "economic_outlook": V2_ECONOMIC_OUTLOOK_MAX_BYTES,
    }
    sizes: dict[str, int] = {}
    for key, entry in files.items():
        key = str(key)
        if key not in caps:
            raise ValueError(f"manifest-v2 capability {key!r} has no network budget")
        size = _declared_bytes(key, entry)
        if size > caps[key]:
            raise ValueError(f"payload {key} bytes {size} exceed {caps[key]}")
        if asset_root is not None:
            path = asset_root / str(entry.get("name") or "")
            if not path.is_file() or path.stat().st_size != size:
                raise ValueError(f"payload {key} local bytes do not match the manifest")
        sizes[key] = size
    total = sum(sizes.values())
    if total > V2_TOTAL_MAX_BYTES:
        raise ValueError(f"payload v2 total bytes {total} exceed {V2_TOTAL_MAX_BYTES}")
    return {
        "schema_version": 1,
        "capabilities": {
            key: {
                "bytes": size,
                "seconds": {
                    f"{speed:g}_mbps": round(transfer_seconds(size, speed), 3)
                    for speed in TRANSFER_SPEEDS_MBPS
                },
            }
            for key, size in sizes.items()
        },
        "total_bytes": total,
    }
