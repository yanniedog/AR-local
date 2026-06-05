#!/usr/bin/env python3
"""Patch CBA Foreign Currency Account anomalies for 2026-05-20 and 2026-05-26.

Replaces ribbon-normalized rate values that came from a transient mis-publication
on CBA's CDR endpoint. Replacement values are sourced from the flanking-day
ladder (the one that is corroborated by CBA's current live CDR response).

Touches three artefacts per affected run_date:
  - data/runs/<date>/_exports/local-cdr.sqlite    (table bank_rates)
  - data/runs/<date>/_exports/banks-<date>.json   (raw export)
  - data/runs/<date>/_exports/dashboard-cache/<date>/banks.json (dashboard cache)

All originals are backed up with a .bak-<utc-stamp> suffix before mutation.
Run with --dry-run first to print what would change.
"""
from __future__ import annotations
import argparse, json, sqlite3, shutil, sys, datetime
from pathlib import Path

ROOT = Path('/srv/ar-local/data/runs')

# (run_date, source_run_date_for_replacement, product_name) — Retail and Business
# Replacements use the source-date ladder values, sorted ascending by rate.
# These ladders are the documented CBA values around the anomaly.
PATCHES = [
    # 26 May: CBA mid-repricing window. Use 25 May ladder (pre-cut state at our ingest moment).
    {'date': '2026-05-26', 'product_name_like': 'Foreign Currency Account (Retail)',
     'old_sorted': [0.0, 0.0, 0.0, 0.00225, 0.01225, 0.0125, 0.015, 0.02225],
     'new_sorted': [0.0, 0.0, 0.0, 0.0125,  0.015,   0.02625, 0.03625, 0.04625],
     'note': '26 May transient mis-publication; replaced with 25 May ladder'},
    {'date': '2026-05-26', 'product_name_like': 'Foreign Currency Account (Business)',
     'old_sorted': [0.0, 0.0, 0.0, 0.00225, 0.01225, 0.0125, 0.015, 0.02225],
     'new_sorted': [0.0, 0.0, 0.0, 0.0125,  0.015,   0.02625, 0.03625, 0.04625],
     'note': '26 May transient mis-publication; replaced with 25 May ladder'},
    # 20 May: CBA Retail only (audit found no Business anomaly that day).
    {'date': '2026-05-20', 'product_name_like': 'Foreign Currency Account (Retail)',
     'old_sorted': [0.0, 0.0, 0.0, 0.0125, 0.015, 0.02225, 0.03225, 0.04225],
     'new_sorted': [0.0, 0.0, 0.0, 0.0125, 0.015, 0.02725, 0.03725, 0.04725],
     'note': '20 May transient mis-publication; replaced with 19 May ladder'},
]

def backup(path: Path, stamp: str) -> Path:
    bak = path.with_suffix(path.suffix + f'.bak-{stamp}')
    if not bak.exists():
        shutil.copy2(path, bak)
    return bak

def patch_sqlite(db_path: Path, name_like: str, old_sorted: list[float], new_sorted: list[float], dry_run: bool) -> tuple[int, list]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "select rowid, rate from bank_rates where provider='CommBank' and product_name=? order by cast(rate as real)",
        (name_like,),
    ).fetchall()
    actual = [float(r['rate']) for r in rows]
    if actual != old_sorted:
        con.close()
        return 0, [f'WARN: ladder mismatch for {db_path} / {name_like}: got {actual}, expected {old_sorted}']
    changes = []
    if not dry_run:
        for row, new_val in zip(rows, new_sorted):
            con.execute('update bank_rates set rate=? where rowid=?', (str(new_val), row['rowid']))
        con.commit()
    for row, new_val in zip(rows, new_sorted):
        if float(row['rate']) != new_val:
            changes.append(f"  rowid={row['rowid']:>5}  {row['rate']:>8} -> {new_val}")
    con.close()
    return len(changes), changes

def patch_json(json_path: Path, name_like: str, old_sorted: list[float], new_sorted: list[float], dry_run: bool) -> tuple[int, list]:
    if not json_path.exists():
        return 0, [f'skip (not present): {json_path}']
    data = json.loads(json_path.read_text())
    # locate the rates list — either top-level "rates" or nested
    rates = data.get('rates') if isinstance(data, dict) else None
    if not isinstance(rates, list):
        return 0, [f'WARN: no rates list in {json_path}']
    matched = [r for r in rates if isinstance(r, dict) and r.get('provider')=='CommBank' and r.get('product_name')==name_like]
    matched.sort(key=lambda r: float(r.get('rate') or 0))
    actual = [float(r.get('rate') or 0) for r in matched]
    if actual != old_sorted:
        return 0, [f'WARN: json ladder mismatch in {json_path}: got {actual}, expected {old_sorted}']
    changes = []
    for r, new_val in zip(matched, new_sorted):
        if float(r.get('rate') or 0) != new_val:
            changes.append(f"  {json_path.name}: rate {r['rate']} -> {new_val}")
            if not dry_run:
                r['rate'] = str(new_val)
    if not dry_run and changes:
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return len(changes), changes

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    stamp = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    print(f'patch run @ {stamp}  dry_run={args.dry_run}\n')
    total = 0
    for p in PATCHES:
        run_dir = ROOT / p['date']
        exports = run_dir / '_exports'
        db = exports / 'local-cdr.sqlite'
        raw = exports / f'banks-{p["date"]}.json'
        cache = exports / 'dashboard-cache' / p['date'] / 'banks.json'
        print(f"--- {p['date']} :: {p['product_name_like']} ({p['note']}) ---")
        for f in (db, raw, cache):
            if f.exists() and not args.dry_run:
                bak = backup(f, stamp)
                print(f'  backup: {bak.name}')
        n_db, ch_db = patch_sqlite(db, p['product_name_like'], p['old_sorted'], p['new_sorted'], args.dry_run)
        for line in ch_db: print(line)
        n_raw, ch_raw = patch_json(raw, p['product_name_like'], p['old_sorted'], p['new_sorted'], args.dry_run)
        for line in ch_raw: print(line)
        n_cache, ch_cache = patch_json(cache, p['product_name_like'], p['old_sorted'], p['new_sorted'], args.dry_run)
        for line in ch_cache: print(line)
        total += n_db + n_raw + n_cache
        print(f'  changes for this patch: sqlite={n_db}, raw={n_raw}, cache={n_cache}\n')
    print(f'TOTAL row changes: {total}')

if __name__ == '__main__':
    sys.exit(main())
