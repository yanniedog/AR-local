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
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

_CATALOG_PATH = Path(__file__).resolve().parent / "dashboard" / "economic-data-catalog.json"
_CATALOG_TTL_SECONDS = 5.0

_catalog_lock = threading.Lock()
_catalog_cache: dict | None = None
_catalog_mtime: float | None = None
_catalog_last_check: float = 0.0


class CatalogUnavailableError(Exception):
    """Raised when the vendored catalog file is missing or malformed."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _load_catalog() -> dict:
    """Return the catalog dict, refreshing from disk only when the cache TTL
    has expired and the file mtime has changed.

    Double-checked locking avoids the race where two threads observe a stale
    cache simultaneously and both re-read from disk. The TTL skips the
    filesystem ``stat()`` call entirely while warm, matching the
    ``LATEST_EXPORTS_TTL_SECONDS`` pattern used elsewhere in the server.
    """
    global _catalog_cache, _catalog_mtime, _catalog_last_check
    now = time.monotonic()
    if _catalog_cache is not None and (now - _catalog_last_check) < _CATALOG_TTL_SECONDS:
        return _catalog_cache

    with _catalog_lock:
        now = time.monotonic()
        if _catalog_cache is not None and (now - _catalog_last_check) < _CATALOG_TTL_SECONDS:
            return _catalog_cache
        try:
            stat = _CATALOG_PATH.stat()
        except OSError as exc:
            raise CatalogUnavailableError(
                f"economic-data catalog file is missing: {_CATALOG_PATH}"
            ) from exc
        if _catalog_cache is None or _catalog_mtime != stat.st_mtime:
            try:
                with _CATALOG_PATH.open("r", encoding="utf-8") as handle:
                    _catalog_cache = json.load(handle)
            except (OSError, json.JSONDecodeError) as exc:
                raise CatalogUnavailableError(
                    f"economic-data catalog file is not valid JSON: {_CATALOG_PATH}"
                ) from exc
            _catalog_mtime = stat.st_mtime
        _catalog_last_check = now
        return _catalog_cache


def _series_count(catalog: dict) -> int:
    return sum(len(cat.get("series", [])) for cat in catalog.get("categories", []))


def _error_body(message: str) -> bytes:
    return json.dumps(
        {"ok": False, "error": {"code": "catalog_unavailable", "message": message}},
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def economic_catalog_payload() -> Tuple[bytes, str]:
    try:
        catalog = _load_catalog()
    except CatalogUnavailableError as exc:
        return _error_body(str(exc)), "application/json; charset=utf-8"
    payload = {
        "ok": True,
        "generated_at": _now_iso(),
        "presets": catalog.get("presets", []),
        "categories": catalog.get("categories", []),
    }
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return body, "application/json; charset=utf-8"


def economic_health_payload() -> Tuple[bytes, str]:
    try:
        catalog = _load_catalog()
    except CatalogUnavailableError as exc:
        return _error_body(str(exc)), "application/json; charset=utf-8"
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
