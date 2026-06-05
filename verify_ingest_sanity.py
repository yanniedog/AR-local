#!/usr/bin/env python3
"""Self-test for cdr_ingest_sanity.compare_ladders.

Standalone (no pytest dependency) to match this repo's verify_* convention.
Builds two throwaway SQLite exports with a known tier ladder and asserts the
guard flags the CommBank-FX-style transient, ignores small moves, and reports
structural tier-count changes. Exit 0 on pass, 1 on failure.

Run: python verify_ingest_sanity.py
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

from cdr_ingest_sanity import LOW_BP, HIGH_BP, compare_ladders


_DDL = """
create table bank_rates (
    run_date text, dataset text, provider text, product_id text,
    product_key text, product_name text, rate_family text, rate text,
    application_type text, ribbon_rate_structure text
);
"""


def _make_db(path: Path, rows: list[tuple]) -> None:
    con = sqlite3.connect(path)
    con.executescript(_DDL)
    con.executemany(
        "insert into bank_rates (provider, product_id, application_type, "
        "ribbon_rate_structure, product_name, dataset, rate) values (?,?,?,?,?,?,?)",
        rows,
    )
    con.commit()
    con.close()


def _row(provider, pid, name, rate, app="PERIODIC", struct="base", dataset="Savings"):
    return (provider, pid, app, struct, name, dataset, str(rate))


def main() -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        prev = tmpdir / "prev.sqlite"
        curr = tmpdir / "curr.sqlite"

        # prev day: a clean FX ladder + an unrelated stable product
        prev_rows = [
            _row("CommBank", "fx1", "Foreign Currency Account (Retail)", 0.02625),
            _row("CommBank", "fx1", "Foreign Currency Account (Retail)", 0.03625),
            _row("CommBank", "fx1", "Foreign Currency Account (Retail)", 0.04625),
            _row("ANZ", "sav1", "Online Saver", 0.0450),
            _row("ANZ", "sav1", "Online Saver", 0.0500),
        ]
        # curr day: FX top tier collapses ~240 bp (the incident), ANZ nudges 5 bp
        curr_rows = [
            _row("CommBank", "fx1", "Foreign Currency Account (Retail)", 0.0125),   # -140 bp
            _row("CommBank", "fx1", "Foreign Currency Account (Retail)", 0.02225),  # -140 bp
            _row("CommBank", "fx1", "Foreign Currency Account (Retail)", 0.02225),  # -240 bp
            _row("ANZ", "sav1", "Online Saver", 0.0455),                            # +5 bp
            _row("ANZ", "sav1", "Online Saver", 0.0505),                            # +5 bp
        ]
        _make_db(prev, prev_rows)
        _make_db(curr, curr_rows)

        findings = compare_ladders(curr, prev)
        by_provider = {f["provider"]: f for f in findings}

        # 1. The FX collapse must be flagged HIGH.
        if "CommBank" not in by_provider:
            failures.append("expected a CommBank finding, got none")
        elif by_provider["CommBank"]["severity"] != "HIGH":
            failures.append(
                f"expected CommBank HIGH, got {by_provider['CommBank']['severity']}"
            )
        elif by_provider["CommBank"]["worst_delta_bp"] < HIGH_BP:
            failures.append(
                f"expected worst_delta >= {HIGH_BP}, got "
                f"{by_provider['CommBank']['worst_delta_bp']}"
            )

        # 2. The 5 bp ANZ move must NOT be flagged.
        if "ANZ" in by_provider:
            failures.append("5 bp ANZ move should not be flagged")

        # 3. Structural tier-count change is reported, not a delta.
        prev2 = tmpdir / "prev2.sqlite"
        curr2 = tmpdir / "curr2.sqlite"
        _make_db(prev2, [
            _row("UpBank", "td1", "Saver", 0.05),
            _row("UpBank", "td1", "Saver", 0.055),
        ])
        _make_db(curr2, [
            _row("UpBank", "td1", "Saver", 0.05),
        ])
        struct_findings = compare_ladders(curr2, prev2)
        if not any(f["severity"] == "STRUCTURAL" for f in struct_findings):
            failures.append("tier-count drop should produce a STRUCTURAL finding")

        # 4. Identical ladders produce no findings.
        if compare_ladders(prev, prev):
            failures.append("identical DBs should produce zero findings")

    if failures:
        print("verify_ingest_sanity: FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"verify_ingest_sanity: OK (LOW_BP={LOW_BP}, HIGH_BP={HIGH_BP})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
