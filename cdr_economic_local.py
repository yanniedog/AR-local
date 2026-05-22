"""Local handlers for /api/economic-data/* endpoints.

These replace upstream proxy calls so the economic-data page renders without
contacting australianrates.com. ``/catalog`` and ``/health`` have been
locally-served since PR1a. ``/series`` is partially local from PR1b: when
every requested ``id`` is in ``LOCAL_SERIES_IDS``, the response is built
from ``state/local-macro.sqlite`` (populated by ``cdr_macro_ingest.py``);
otherwise the caller falls back to the upstream proxy.

The catalog metadata (series IDs, labels, units, source URLs, descriptions,
preset groupings) is vendored at ``dashboard/economic-data-catalog.json``.
Freshness fields in the vendored file reflect the upstream snapshot at the
time of vendoring and are returned verbatim until the corresponding local
ingest lands; the frontend treats them as advisory and falls back gracefully
when ``last_observation_date`` is missing.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Tuple

from cdr_public_api_shims import connect_readonly

_CATALOG_PATH = Path(__file__).resolve().parent / "dashboard" / "economic-data-catalog.json"
_CATALOG_TTL_SECONDS = 5.0
_MACRO_STORE_PATH = Path(__file__).resolve().parent / "state" / "local-macro.sqlite"

# Series IDs supplied locally. Anything else still round-trips to the
# upstream proxy via cdr_economic_proxy.
#   PR1b: RBA H5 (unemployment_rate, participation_rate)
#   PR1c: ABS CPI_M (monthly_cpi_indicator, monthly_trimmed_mean_cpi)
#   PR1c.2: ABS LF_UNDER + LF_HOURS (employment_to_population,
#           underemployment_rate, underutilisation_rate, hours_worked)
#   PR1c.3: ABS HSI_M + LEND_HOUSING (household_spending_indicator,
#           lending_indicator_housing)
#   PR1c.4: ABS BA_GCCSA (building_approvals_abs)
#   PR1b.x: RBA H3 (dwelling_approvals, consumer_sentiment, business_conditions)
LOCAL_SERIES_IDS: frozenset[str] = frozenset(
    {
        "unemployment_rate",
        "participation_rate",
        "monthly_cpi_indicator",
        "monthly_trimmed_mean_cpi",
        "employment_to_population",
        "underemployment_rate",
        "underutilisation_rate",
        "hours_worked",
        "household_spending_indicator",
        "lending_indicator_housing",
        "building_approvals_abs",
        "dwelling_approvals",
        "consumer_sentiment",
        "business_conditions",
    }
)

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


def _catalog_index() -> dict[str, dict]:
    """Return a dict keyed by series_id -> series metadata dict."""
    catalog = _load_catalog()
    out: dict[str, dict] = {}
    for category in catalog.get("categories", []):
        for series in category.get("series", []):
            sid = series.get("id")
            if sid:
                out[sid] = series
    return out


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _years_before(d: date, years: int) -> date:
    """``d`` minus ``years`` calendar years, clamping Feb 29 to Feb 28 when
    the target year is not a leap year. Plain ``date.replace(year=...)``
    raises ValueError for ``2024-02-29`` -> ``2019-02-29`` (Codex P1 PR #118
    would 500 the endpoint on a leap-day end_date)."""
    try:
        return d.replace(year=d.year - years)
    except ValueError:
        return d.replace(year=d.year - years, month=2, day=28)


def _resolve_window(start: str | None, end: str | None) -> tuple[date, date]:
    """Pick a [start, end] window. Defaults: last 5 years through today (UTC)."""
    today_utc = datetime.now(timezone.utc).date()
    end_date = _parse_iso_date(end) or today_utc
    start_date = _parse_iso_date(start) or _years_before(end_date, 5)
    if start_date > end_date:
        start_date = end_date
    return start_date, end_date


def _read_observations(
    store_path: Path, series_id: str, end_date: date
) -> list[tuple[date, float, str | None]]:
    """All observations for ``series_id`` with observation_date <= end_date.

    Returns ascending by observation_date. The dashboard service should never
    write to this store, so the connection is opened read-only via the same
    helper used for run-export DBs.
    """
    try:
        with connect_readonly(store_path) as con:
            rows = con.execute(
                """SELECT observation_date, raw_value, release_date
                   FROM series_observations
                   WHERE series_id = ? AND observation_date <= ?
                     AND raw_value IS NOT NULL
                   ORDER BY observation_date ASC""",
                (series_id, end_date.isoformat()),
            ).fetchall()
    except sqlite3.Error:
        return []
    out: list[tuple[date, float, str | None]] = []
    for obs_date_str, raw_value, release_date in rows:
        parsed = _parse_iso_date(obs_date_str)
        if parsed is None:
            continue
        out.append((parsed, float(raw_value), release_date))
    return out


def _read_freshness(store_path: Path, series_id: str) -> dict | None:
    try:
        with connect_readonly(store_path) as con:
            row = con.execute(
                """SELECT last_checked_at, last_success_at, last_observation_date,
                          last_value, status, message
                   FROM ingest_runs WHERE series_id = ?""",
                (series_id,),
            ).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    return {
        "last_checked_at": row[0],
        "last_success_at": row[1],
        "last_observation_date": row[2],
        "last_value": row[3],
        "status": row[4],
        "message": row[5],
    }


def _build_series_points(
    observations: list[tuple[date, float, str | None]],
    start_date: date,
    end_date: date,
) -> tuple[list[dict], str | None, float | None]:
    """Forward-fill observations into daily points; compute baseline.

    Baseline is the first non-null daily value in the window — exactly the
    upstream contract documented in the frontend ('Index = 100 at the start
    of the visible range'). Returns ``(points, baseline_date, baseline_value)``.
    """
    if not observations:
        return [], None, None

    points: list[dict] = []
    obs_idx = 0
    next_obs_idx = 0
    current_obs: tuple[date, float, str | None] | None = None
    baseline_date: str | None = None
    baseline_value: float | None = None

    day = start_date
    one = timedelta(days=1)
    while day <= end_date:
        # Advance through observations whose date <= day; current_obs ends up
        # as the latest observation at or before this day.
        while next_obs_idx < len(observations) and observations[next_obs_idx][0] <= day:
            current_obs = observations[next_obs_idx]
            next_obs_idx += 1
        if current_obs is not None:
            obs_date, raw_value, release_date = current_obs
            if baseline_value is None and raw_value:
                baseline_date = day.isoformat()
                baseline_value = raw_value
            normalized = (
                round(100.0 * raw_value / baseline_value, 6)
                if baseline_value
                else None
            )
            points.append(
                {
                    "date": day.isoformat(),
                    "raw_value": raw_value,
                    "normalized_value": normalized,
                    "observation_date": obs_date.isoformat(),
                    "release_date": release_date,
                }
            )
        day += one
    return points, baseline_date, baseline_value


def is_series_request_local(ids: Iterable[str]) -> bool:
    """True iff every requested id is locally-served (no proxy fallback needed)."""
    ids_list = [i for i in ids if i]
    if not ids_list:
        return False
    return all(i in LOCAL_SERIES_IDS for i in ids_list)


def economic_series_payload(
    ids: list[str], start: str | None, end: str | None
) -> Tuple[bytes, str] | None:
    """Build the locally-served /series response, or return ``None`` if local
    data is incomplete and the caller should fall back to the upstream proxy.

    Caller is expected to have checked ``is_series_request_local(ids)`` first
    so unmapped ids never reach this path. The additional empty-points check
    handles a fresh Pi where the code has deployed but ``cdr_macro_ingest.py``
    has not yet populated ``state/local-macro.sqlite`` — proxy fallback keeps
    the page rendering until ingest catches up.
    """
    start_date, end_date = _resolve_window(start, end)
    catalog_meta = _catalog_index()
    series_out: list[dict] = []
    for series_id in ids:
        meta = catalog_meta.get(series_id) or {"id": series_id}
        observations = _read_observations(_MACRO_STORE_PATH, series_id, end_date)
        points, baseline_date, baseline_value = _build_series_points(
            observations, start_date, end_date
        )
        if not points:
            # Signal proxy fallback rather than serving an empty chart.
            return None
        freshness = _read_freshness(_MACRO_STORE_PATH, series_id) or meta.get("freshness")
        entry = {
            "id": series_id,
            "label": meta.get("label", series_id),
            "short_label": meta.get("short_label", meta.get("label", series_id)),
            "category": meta.get("category"),
            "unit": meta.get("unit"),
            "frequency": meta.get("frequency"),
            "proxy": meta.get("proxy", False),
            "source_label": meta.get("source_label"),
            "source_url": meta.get("source_url"),
            "description": meta.get("description"),
            "presets": meta.get("presets", []),
            "baseline_date": baseline_date,
            "baseline_value": baseline_value,
            "freshness": freshness,
            "quarantine": None,
            "points": points,
        }
        series_out.append(entry)
    payload = {
        "ok": True,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "normalized_compare": True,
        "served_by": "ar-local",
        "series": series_out,
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
