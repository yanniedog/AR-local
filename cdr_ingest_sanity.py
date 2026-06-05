"""Post-ingest sanity check: flag suspicious day-over-day rate changes.

Background — 2026-05-26 CommBank Foreign Currency Account incident:
  CBA's public CDR endpoint briefly served a partial/intermediate set of
  rate values during their repricing window (~06:00 AEST). Our ingest
  captured the bad data exactly as published. The same family of glitch
  also occurred on 2026-05-20. Neither event tripped any existing
  validation — failure counts and row counts were normal — so they
  silently entered the historical record and were only detected by
  visual review of the dashboard chart.

This module is the per-product/per-tier guard. It compares the freshly
built bank_rates table to the previous day's export and writes a
``sanity-report.json`` next to the daily marker. It does NOT block the
ingest — large legitimate rate moves do happen — but a non-empty
report means a human should eyeball the dashboard before publishing.

Heuristic (intentionally simple, no time-window memory):
  For each (provider, product_id, application_type, ribbon_rate_structure)
  group, sort the rate ladder ascending. If the sorted ladders have the
  same length, compare tier-by-tier. Any tier shift |delta| >= HIGH_BP is
  a HIGH severity flag; LOW_BP <= |delta| < HIGH_BP is a LOW flag.
  Tier-count changes are reported as STRUCTURAL.

The report is JSON-formatted and small enough to tail in journalctl.
``cdr_daily.run_once`` calls ``write_sanity_report`` after
``build_outputs`` succeeds.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Tiers can legitimately move by ~50 bp on the day of an RBA decision.
# 100 bp moves are rare but happen (term-deposit specials, neobank promos).
# 200 bp moves are essentially never legitimate same-day.
LOW_BP = 100.0
HIGH_BP = 200.0


def _ladder_query(con: sqlite3.Connection) -> List[Tuple[str, str, str, str, str, str, float]]:
    """Return rows of (provider, product_id, application_type, ribbon_rate_structure,
    product_name, dataset, rate). Caller buckets by the first four columns."""
    cur = con.execute(
        """
        select provider, product_id,
               coalesce(application_type, ''),
               coalesce(ribbon_rate_structure, ''),
               coalesce(product_name, ''),
               coalesce(dataset, ''),
               cast(rate as real)
        from bank_rates
        where rate is not null and rate != ''
        """
    )
    return cur.fetchall()


def _bucket(rows: List[Tuple[Any, ...]]) -> Dict[Tuple[str, str, str, str], Dict[str, Any]]:
    out: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
    for provider, pid, app, struct, name, dataset, rate in rows:
        key = (provider, pid, app, struct)
        slot = out.setdefault(key, {"name": name, "dataset": dataset, "rates": []})
        slot["rates"].append(float(rate))
    for slot in out.values():
        slot["rates"].sort()
    return out


def compare_ladders(curr_db: Path, prev_db: Path) -> List[Dict[str, Any]]:
    """Return a list of finding dicts. Empty list means no concerns."""
    if not curr_db.is_file() or not prev_db.is_file():
        return []
    with sqlite3.connect(f"file:{curr_db}?mode=ro", uri=True) as con:
        curr = _bucket(_ladder_query(con))
    with sqlite3.connect(f"file:{prev_db}?mode=ro", uri=True) as con:
        prev = _bucket(_ladder_query(con))
    findings: List[Dict[str, Any]] = []
    for key, slot in curr.items():
        prev_slot = prev.get(key)
        if not prev_slot:
            continue  # new product; not a sanity-check target
        cv, pv = slot["rates"], prev_slot["rates"]
        if len(cv) != len(pv):
            findings.append({
                "severity": "STRUCTURAL",
                "provider": key[0], "product_id": key[1],
                "application_type": key[2], "ribbon_rate_structure": key[3],
                "product_name": slot["name"], "dataset": slot["dataset"],
                "tier_count_prev": len(pv), "tier_count_curr": len(cv),
            })
            continue
        worst_delta_bp = 0.0
        per_tier = []
        for i, (c, p) in enumerate(zip(cv, pv)):
            d_bp = abs(c - p) * 10000.0
            per_tier.append({"tier_idx": i, "prev": p, "curr": c, "delta_bp": round(d_bp, 1)})
            if d_bp > worst_delta_bp:
                worst_delta_bp = d_bp
        if worst_delta_bp >= LOW_BP:
            severity = "HIGH" if worst_delta_bp >= HIGH_BP else "LOW"
            findings.append({
                "severity": severity,
                "provider": key[0], "product_id": key[1],
                "application_type": key[2], "ribbon_rate_structure": key[3],
                "product_name": slot["name"], "dataset": slot["dataset"],
                "worst_delta_bp": round(worst_delta_bp, 1),
                "tiers": per_tier,
            })
    # Sort: HIGH first, then by worst delta desc
    severity_rank = {"HIGH": 0, "STRUCTURAL": 1, "LOW": 2}
    findings.sort(key=lambda f: (severity_rank.get(f["severity"], 9),
                                 -float(f.get("worst_delta_bp", 0))))
    return findings


def write_sanity_report(exports_dir: Path, run_date: str, runs_root: Path) -> Optional[Path]:
    """Write sanity-report.json into exports_dir. Returns the path written, or
    None if there is no previous day to compare against (first ingest)."""
    curr_db = exports_dir / "local-cdr.sqlite"
    prev_db = _find_previous_export_db(runs_root, run_date)
    if prev_db is None:
        return None
    findings = compare_ladders(curr_db, prev_db)
    summary = {
        "run_date": run_date,
        "compared_against": prev_db.parent.parent.name,
        "thresholds_bp": {"low": LOW_BP, "high": HIGH_BP},
        "counts": {
            "HIGH": sum(1 for f in findings if f["severity"] == "HIGH"),
            "STRUCTURAL": sum(1 for f in findings if f["severity"] == "STRUCTURAL"),
            "LOW": sum(1 for f in findings if f["severity"] == "LOW"),
        },
        "findings": findings,
    }
    out = exports_dir / "sanity-report.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def _find_previous_export_db(runs_root: Path, run_date: str) -> Optional[Path]:
    """Find the most recent prior date's local-cdr.sqlite under runs_root."""
    if not runs_root.is_dir():
        return None
    candidates = []
    for child in runs_root.iterdir():
        if not child.is_dir() or child.name >= run_date:
            continue
        db = child / "_exports" / "local-cdr.sqlite"
        if db.is_file():
            candidates.append((child.name, db))
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][1]
