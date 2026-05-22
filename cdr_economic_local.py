"""Local handlers for /api/economic-data/catalog and /health.

These replace upstream proxy calls so the economic-data page renders without
contacting australianrates.com. Series data (`/api/economic-data/series`)
remains proxied for now; per-source ingest is being added in follow-up PRs.

The catalog metadata (series IDs, labels, units, source URLs, descriptions,
preset groupings) is vendored at ``dashboard/economic-data-catalog.json``.
Freshness fields in the vendored file reflect the upstream snapshot at the
time of vendoring and are returned verbatim until the corresponding local
ingest lands; the frontend treats them as advisory and falls back gracefully
when ``last_observation_date`` is missing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

_CATALOG_PATH = Path(__file__).resolve().parent / "dashboard" / "economic-data-catalog.json"

_catalog_cache: dict | None = None
_catalog_mtime: float | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _load_catalog() -> dict:
    global _catalog_cache, _catalog_mtime
    stat = _CATALOG_PATH.stat()
    if _catalog_cache is None or _catalog_mtime != stat.st_mtime:
        with _CATALOG_PATH.open("r", encoding="utf-8") as handle:
            _catalog_cache = json.load(handle)
        _catalog_mtime = stat.st_mtime
    return _catalog_cache


def _series_count(catalog: dict) -> int:
    return sum(len(cat.get("series", [])) for cat in catalog.get("categories", []))


def economic_catalog_payload() -> Tuple[bytes, str]:
    catalog = _load_catalog()
    payload = {
        "ok": True,
        "generated_at": _now_iso(),
        "presets": catalog.get("presets", []),
        "categories": catalog.get("categories", []),
    }
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return body, "application/json; charset=utf-8"


def economic_health_payload() -> Tuple[bytes, str]:
    catalog = _load_catalog()
    payload = {
        "ok": True,
        "service": "economic-data",
        "api_base_path": "/api/economic-data",
        "series_count": _series_count(catalog),
        "preset_count": len(catalog.get("presets", [])),
        "served_by": "ar-local",
    }
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return body, "application/json; charset=utf-8"
