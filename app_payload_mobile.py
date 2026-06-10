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
    count = len(ordered)
    mid = count // 2
    median = ordered[mid] if count % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    return {
        "min": ordered[0],
        "max": ordered[-1],
        "mean": sum(ordered) / count,
        "median": median,
        "count": count,
    }

def build_history_banks(exports_dir, *, run_date, load_json, section_filter, normalized_rate_value, schema_version=1):
    dates = _history_dates(exports_dir, run_date)
    points_by_section = {section: [] for section in VALID_SECTIONS}
    for date in dates:
        path = _banks(exports_dir, date)
        if not path:
            continue
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
    sections = {
        section: {"points": points}
        for section, points in points_by_section.items()
        if points
    }
    return {"schema_version": schema_version, "run_date": run_date, "run_dates": dates, "sections": sections}
