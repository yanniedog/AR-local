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

def build_history_banks(exports_dir, *, run_date, load_json, section_filter, normalized_rate_value, schema_version=1):
    dates = sorted({c.name for c in (exports_dir / "dashboard-cache").iterdir() if c.is_dir() and c.name <= run_date and (c / "banks.json").is_file()} if (exports_dir / "dashboard-cache").is_dir() else [])
    sections = {}
    for section in VALID_SECTIONS:
        by_date = {}
        for d in dates:
            path = _banks(exports_dir, d)
            if not path: continue
            rows = [r for r in (load_json(path).get("rates") or []) if isinstance(r, dict) and r.get("dataset") == section and section_filter(section, r)]
            values = []
            keys = [str(r.get("product_key") or r.get("product_id") or "") for r in rows]
            pct = {k for k, r in zip(keys, rows) if k and float(r.get("rate") or 0) > 1}
            for key, row in zip(keys, rows):
                norm = normalized_rate_value(row.get("rate"), section, key in pct)
                if norm is not None: values.append(norm)
            if not values: continue
            slot = by_date.setdefault(d, {"rates": [], "min": None, "max": None, "sum": 0.0, "count": 0})
            slot["rates"].extend(values)
            slot["min"] = min(slot["min"], min(values)) if slot["min"] is not None else min(values)
            slot["max"] = max(slot["max"], max(values)) if slot["max"] is not None else max(values)
            slot["sum"] += sum(values); slot["count"] += len(values)
        points = []
        for date, slot in sorted(by_date.items()):
            if slot["count"] <= 0: continue
            ordered = sorted(slot["rates"]); n = len(ordered); mid = n // 2
            med = ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2
            points.append({"date": date, "min": slot["min"], "max": slot["max"], "mean": slot["sum"]/slot["count"], "median": med, "count": slot["count"]})
        if points: sections[section] = {"points": points}
    return {"schema_version": schema_version, "run_date": run_date, "run_dates": dates, "sections": sections}
