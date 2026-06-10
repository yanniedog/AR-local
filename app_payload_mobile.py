"""Mobile payload assets: search index + pre-aggregated history."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
VALID_SECTIONS = ("Mortgage", "Savings", "TD")
_WS = re.compile(r"\s+")

def _norm(text: str) -> str:
    return _WS.sub(" ", str(text or "").strip().lower())

def _items(items: Any) -> List[str]:
    if not isinstance(items, list): return []
    out: List[str] = []
    for item in items:
        if not isinstance(item, dict): continue
        for key in ("label", "name", "value", "info"):
            raw = item.get(key)
            if raw not in (None, ""): out.append(str(raw))
    return out

def build_search_index(core_rows, details_map, *, run_date: str, schema_version: int = 1):
    meta: Dict[str, Dict[str, str]] = {}
    for row in core_rows:
        key = str(row.get("product_key") or "")
        if not key or key in meta: continue
        meta[key] = {"provider": str(row.get("provider") or ""), "product_name": str(row.get("product_name") or "")}
    products = {}
    for key in sorted(set(meta) | set(details_map)):
        chunks = []
        m = meta.get(key, {})
        if m.get("provider"): chunks.append(m["provider"])
        if m.get("product_name"): chunks.append(m["product_name"])
        detail = details_map.get(key)
        if detail:
            if detail.get("description"): chunks.append(str(detail["description"]))
            for field in ("fees", "features", "eligibility", "constraints"):
                chunks.extend(_items(detail.get(field)))
        chunks.append(key)
        products[key] = _norm(" ".join(chunks))
    return {"schema_version": schema_version, "run_date": run_date, "products": products}

def _runs_root(exports_dir: Path):
    r = exports_dir.resolve()
    return r.parent.parent if r.name == "_exports" and r.parent.parent.name == "runs" else None

def _banks(exports_dir: Path, run_date: str):
    direct = exports_dir / "dashboard-cache" / run_date / "banks.json"
    if direct.is_file(): return direct
    root = _runs_root(exports_dir)
    if root:
        s = root / run_date / "_exports" / "dashboard-cache" / run_date / "banks.json"
        if s.is_file(): return s
    return None

def _history_dates(exports_dir: Path, run_date: str) -> List[str]:
    dates = set()
    direct = exports_dir / "dashboard-cache"
    if direct.is_dir():
        dates.update(
            child.name
            for child in direct.iterdir()
            if child.is_dir() and child.name <= run_date and (child / "banks.json").is_file()
        )
    root = _runs_root(exports_dir)
    if root:
        dates.update(
            child.name
            for child in root.iterdir()
            if child.is_dir()
            and child.name <= run_date
            and (child / "_exports" / "dashboard-cache" / child.name / "banks.json").is_file()
        )
    return sorted(dates)

# A matched product's best advertised rate must move at least this much (5 bps,
# rates are fractions) before it counts toward a provider rate-move event.
MOVE_THRESHOLD = 0.0005
# Newest events kept in the bank-history asset (providers move rarely; this is years).
MAX_EVENTS = 800
_SERIES_ROUND = 6


def _median(ordered: List[float]) -> float:
    count = len(ordered)
    mid = count // 2
    return ordered[mid] if count % 2 else (ordered[mid - 1] + ordered[mid]) / 2

def _history_point(rows, section, normalized_rate_value):
    keys = [str(row.get("product_key") or row.get("product_id") or "") for row in rows]
    percent_style = {
        key for key, row in zip(keys, rows) if key and float(row.get("rate") or 0) > 1
    }
    values = [
        normalized
        for key, row in zip(keys, rows)
        if (normalized := normalized_rate_value(row.get("rate"), section, key in percent_style)) is not None
    ]
    if not values:
        return None
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "max": ordered[-1],
        "mean": sum(ordered) / len(ordered),
        "median": _median(ordered),
        "count": len(ordered),
    }


def _section_day(rows, section, normalized_rate_value):
    """Per-provider normalized values + per-product best rate for one day's section rows."""
    keys = [str(row.get("product_key") or row.get("product_id") or "") for row in rows]
    percent_style = set()
    for key, row in zip(keys, rows):
        if key:
            try:
                if float(row.get("rate") or 0) > 1:
                    percent_style.add(key)
            except (TypeError, ValueError):
                pass
    lower_is_best = section == "Mortgage"
    providers: Dict[str, Dict[str, Any]] = {}
    for key, row in zip(keys, rows):
        value = normalized_rate_value(row.get("rate"), section, key in percent_style)
        if value is None:
            continue
        provider = str(row.get("provider") or "Unknown")
        bucket = providers.setdefault(provider, {"values": [], "best_by_product": {}})
        bucket["values"].append(value)
        if key:
            best = bucket["best_by_product"].get(key)
            if best is None or (value < best if lower_is_best else value > best):
                bucket["best_by_product"][key] = value
    return providers


def _provider_events(date, section, prev_best, providers):
    """Rate-move events vs the previous day: matched product best-rate deltas >= 5 bps."""
    events = []
    for provider in sorted(providers):
        prev = prev_best.get(provider)
        if not prev:
            continue
        cur = providers[provider]["best_by_product"]
        matched = [key for key in cur if key in prev]
        movers = [
            delta for key in matched if abs(delta := cur[key] - prev[key]) >= MOVE_THRESHOLD
        ]
        if not movers:
            continue
        ups = sum(1 for delta in movers if delta > 0)
        direction = "hike" if ups == len(movers) else "cut" if ups == 0 else "mixed"
        events.append({
            "date": date,
            "provider": provider,
            "section": section,
            "dir": direction,
            "moved": len(movers),
            "total": len(matched),
            "avg_bps": round(sum(movers) / len(movers) * 10000, 1),
        })
    return events


def build_history_assets(exports_dir, *, run_date, load_json, section_filter, normalized_rate_value, schema_version=1):
    """Single pass over the daily banks.json snapshots producing BOTH mobile history assets:

    1. ``history_banks`` — per-section daily aggregate ribbon points (existing asset).
    2. ``bank_history`` — per-provider daily median/best/count series per section, plus
       precomputed provider rate-move events (the historical-series "bank behavior" moat).
    """
    dates = _history_dates(exports_dir, run_date)
    points_by_section = {section: [] for section in VALID_SECTIONS}
    # day_stats[i][section][provider] -> (median, best, count), positionally aligned to dates.
    day_stats: List[Dict[str, Dict[str, Tuple[float, float, int]]]] = []
    events: List[Dict[str, Any]] = []
    prev_best: Dict[str, Dict[str, Dict[str, float]]] = {section: {} for section in VALID_SECTIONS}

    for date in dates:
        stats_for_day: Dict[str, Dict[str, Tuple[float, float, int]]] = {}
        path = _banks(exports_dir, date)
        if path:
            rates = [row for row in (load_json(path).get("rates") or []) if isinstance(row, dict)]
            for section in VALID_SECTIONS:
                rows = [
                    row
                    for row in rates
                    if row.get("dataset") == section and section_filter(section, row)
                ]
                point = _history_point(rows, section, normalized_rate_value)
                if point:
                    points_by_section[section].append({"date": date, **point})
                providers = _section_day(rows, section, normalized_rate_value)
                if not providers:
                    continue
                lower_is_best = section == "Mortgage"
                section_stats: Dict[str, Tuple[float, float, int]] = {}
                for provider, bucket in providers.items():
                    values = sorted(bucket["values"])
                    best = values[0] if lower_is_best else values[-1]
                    section_stats[provider] = (_median(values), best, len(values))
                stats_for_day[section] = section_stats
                events.extend(_provider_events(date, section, prev_best[section], providers))
                prev_best[section] = {
                    provider: bucket["best_by_product"] for provider, bucket in providers.items()
                }
        day_stats.append(stats_for_day)

    sections = {
        section: {"points": points}
        for section, points in points_by_section.items()
        if points
    }
    history_banks = {
        "schema_version": schema_version,
        "run_date": run_date,
        "run_dates": dates,
        "sections": sections,
    }

    banks: Dict[str, Dict[str, Dict[str, List[Any]]]] = {}
    for section in VALID_SECTIONS:
        providers_seen = sorted({p for day in day_stats for p in day.get(section, {})})
        for provider in providers_seen:
            series = banks.setdefault(provider, {}).setdefault(
                section, {"median": [], "best": [], "count": []}
            )
            for day in day_stats:
                stat = day.get(section, {}).get(provider)
                if stat is None:
                    series["median"].append(None)
                    series["best"].append(None)
                    series["count"].append(None)
                else:
                    median, best, count = stat
                    series["median"].append(round(median, _SERIES_ROUND))
                    series["best"].append(round(best, _SERIES_ROUND))
                    series["count"].append(count)
    bank_history = {
        "schema_version": schema_version,
        "run_date": run_date,
        "run_dates": dates,
        "banks": banks,
        "events": events[-MAX_EVENTS:],
    }
    return history_banks, bank_history


def build_history_banks(exports_dir, *, run_date, load_json, section_filter, normalized_rate_value, schema_version=1):
    history_banks, _ = build_history_assets(
        exports_dir,
        run_date=run_date,
        load_json=load_json,
        section_filter=section_filter,
        normalized_rate_value=normalized_rate_value,
        schema_version=schema_version,
    )
    return history_banks
