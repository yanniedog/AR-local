"""Fail-closed day-over-day checks for suspicious rate changes.

Background — 2026-05-26 CommBank Foreign Currency Account incident:
  CBA's public CDR endpoint briefly served a partial/intermediate set of
  rate values during their repricing window (~06:00 AEST). Our ingest
  captured the bad data exactly as published. The same family of glitch
  also occurred on 2026-05-20. Neither event tripped any existing
  validation — failure counts and row counts were normal — so they
  silently entered the historical record.

This module is the per-product/per-tier guard. It compares the freshly
built bank_rates table to the previous finalized export and writes a
``sanity-report.json`` beside the canonical observation. The daily runner
withholds finalization when HIGH or STRUCTURAL findings exist.

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

from cdr_atomic import atomic_write_json
from cdr_observation_db import APPLICATION_ID, SCHEMA_VERSION
from cdr_product_change_runs import previous_finalized_run

# Tiers can legitimately move by ~50 bp on the day of an RBA decision.
# 100 bp moves are rare but happen (term-deposit specials, neobank promos).
# 200 bp moves are essentially never legitimate same-day.
LOW_BP = 100.0
HIGH_BP = 200.0


def _ladder_query(
    con: sqlite3.Connection,
) -> List[Tuple[str, str, str, str, str, str, str, float]]:
    """Return stable identity, display metadata, tier dimensions, and rate."""
    if con.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION:
        if con.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
            raise ValueError("canonical observation database application ID is invalid")
        output = []
        for stored_uid, raw in con.execute(
            "SELECT product_uid,document_json FROM bank_rates "
            "ORDER BY product_uid,rate_index,rate_uid"
        ):
            try:
                row = json.loads(raw)
                output.append(
                    (
                        str(stored_uid),
                        str(row["provider"]),
                        str(row["product_id"]),
                        str(row.get("application_type") or ""),
                        str(row.get("ribbon_rate_structure") or ""),
                        str(row.get("product_name") or ""),
                        str(row["dataset"]),
                        float(row["rate"]),
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise ValueError("canonical rate document is invalid") from error
        return output
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
    return [
        (f"legacy:{provider}\0{product_id}", provider, product_id, app, structure,
         name, dataset, rate)
        for provider, product_id, app, structure, name, dataset, rate in cur.fetchall()
    ]


def _bucket(rows: List[Tuple[Any, ...]]) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    out: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for identity, provider, pid, app, struct, name, dataset, rate in rows:
        key = (identity, app, struct)
        slot = out.setdefault(
            key,
            {
                "provider": provider,
                "product_id": pid,
                "name": name,
                "dataset": dataset,
                "rates": [],
            },
        )
        slot["rates"].append(float(rate))
    for slot in out.values():
        slot["rates"].sort()
    return out


def _read_ladders(db_path: Path) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    """Open a read-only connection and return bucketed ladders.

    Uses ``Path.resolve().as_uri()`` so paths with spaces/reserved characters
    encode correctly, and ``contextlib.closing`` because the sqlite3 connection
    context manager only commits/rolls back — it does not close the handle.
    """
    uri = f"{db_path.resolve().as_uri()}?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as con:
        return _bucket(_ladder_query(con))


def compare_ladders(curr_db: Path, prev_db: Path) -> List[Dict[str, Any]]:
    """Return a list of finding dicts. Empty list means no concerns."""
    if not curr_db.is_file() or not prev_db.is_file():
        raise FileNotFoundError("sanity comparison database is absent")
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
                "provider": slot["provider"], "product_id": slot["product_id"],
                "application_type": key[1], "ribbon_rate_structure": key[2],
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
                "provider": slot["provider"], "product_id": slot["product_id"],
                "application_type": key[1], "ribbon_rate_structure": key[2],
                "product_name": slot["name"], "dataset": slot["dataset"],
                "worst_delta_bp": round(worst_delta_bp, 1),
                "tiers": per_tier,
            })
    # Sort: HIGH first, then by worst delta desc
    severity_rank = {"HIGH": 0, "STRUCTURAL": 1, "LOW": 2}
    findings.sort(key=lambda f: (severity_rank.get(f["severity"], 9),
                                 -float(f.get("worst_delta_bp", 0))))
    return findings


def write_sanity_report(
    exports_dir: Path,
    run_date: str,
    runs_root: Path,
    state_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Write sanity-report.json into exports_dir. Returns the path written, or
    None if there is no previous day to compare against (first ingest)."""
    curr_db = exports_dir / "local-cdr.sqlite"
    prev_db = _find_previous_export_db(runs_root, run_date, state_dir)
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
    atomic_write_json(out, summary, create_once=True)
    return out


def _find_previous_export_db(
    runs_root: Path, run_date: str, state_dir: Optional[Path] = None
) -> Optional[Path]:
    """Find the most recent prior date's local-cdr.sqlite under runs_root."""
    previous = previous_finalized_run(runs_root / run_date, state_dir=state_dir)
    if previous is None:
        return None
    database = previous / "_exports" / "local-cdr.sqlite"
    return database if database.is_file() else None
