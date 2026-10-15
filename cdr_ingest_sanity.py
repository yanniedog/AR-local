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
from contextlib import closing
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


def _read_ladders(db_path: Path) -> Dict[Tuple[str, str, str, str], Dict[str, Any]]:
    """Open a read-only connection and return bucketed ladders.

    Uses ``Path.resolve().as_uri()`` so paths with spaces/reserved characters
    encode correctly, and ``contextlib.closing`` because the sqlite3 connection
    context manager only commits/rolls back — it does not close the handle.
    """
    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as con:
        return _bucket(_ladder_query(con))


def compare_ladders(curr_db: Path, prev_db: Path) -> List[Dict[str, Any]]:
    """Return a list of finding dicts. Empty list means no concerns."""
    if not curr_db.is_file() or not prev_db.is_file():
        return []
    curr = _read_ladders(curr_db)
    prev = _read_ladders(prev_db)
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


def write_sanity_report(exports_dir: Path, run_date: str, runs_root: Path, *, state_dir=None,
                        db_path=None) -> Optional[Path]:
    """Write sanity-report.json into exports_dir. Returns the path written, or
    None if there is no previous day to compare against (first ingest)."""
    curr_db = Path(db_path) if db_path is not None else exports_dir / "local-cdr.sqlite"
    prev_db = _find_previous_export_db(runs_root, run_date)
    from cdr_population_baseline import finalized_population_report
    from cdr_atomic import atomic_write_json
    population = finalized_population_report(curr_db,
        state_dir if state_dir is not None else runs_root.parent / 'state', run_date=run_date)
    # Zero normalized rows can mean that every detail failed. Only a complete
    # empty index needs the additional hold; ordinary HTTP recovery stays valid.
    try:
        status_path = exports_dir / 'ingest-status.json'
        if status_path.stat().st_size > 4*1024*1024:
            raise ValueError('index diagnostics exceed metadata budget')
        diagnostics = json.loads(status_path.read_bytes()).get('index_diagnostics') or {}
    except (OSError, ValueError, AttributeError):
        diagnostics = {}
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    def nonempty_index(provider):
        diagnostic = diagnostics.get(provider) or {}
        return (isinstance(diagnostic, dict) and diagnostic.get('pagination_complete') is True
            and type(diagnostic.get('unique_products')) is int and diagnostic['unique_products'] > 0)
    if population.get('unresolved_prior'):
        population['unresolved_prior'] = [row for row in population['unresolved_prior']
                                         if not nonempty_index(row['provider'])]
    if population['status'] in {'PASS','WARN'}:
        retained = []
        unverified_index = False
        for finding in population['findings']:
            diagnostic = diagnostics.get(finding['provider']) or {}
            if not isinstance(diagnostic, dict):
                diagnostic = {}
            count = diagnostic.get('unique_products')
            complete = diagnostic.get('pagination_complete') is True and type(count) is int
            if complete and count > 0:
                continue
            if (complete and count == 0) or finding.get('carried_unresolved'):
                retained.append(finding)
            else:
                unverified_index = True
        population.update(findings=retained,
            status='WARN' if retained else 'UNKNOWN' if unverified_index else 'PASS')
        if unverified_index:
            population['reason'] = 'current_index_unverified'
    compared = (population.get('baseline') or {}).get('observation_date')
    population_summary = {'run_date':run_date,'compared_against':compared,
                          'provider_population':population}
    # Seal bounded authority before the separate, non-blocking ladder advisory.
    atomic_write_json(exports_dir / 'provider-population-report.json', population_summary)
    if prev_db is None:
        return None
    findings = compare_ladders(curr_db, prev_db)
    findings.extend(population["findings"])
    summary = {
        "run_date": run_date,
        "compared_against": compared,
        "thresholds_bp": {"low": LOW_BP, "high": HIGH_BP},
        "provider_population": population,
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
