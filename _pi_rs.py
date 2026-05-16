"""Throwaway: inspect ribbon_rate_structure distribution on the Pi."""
import sqlite3

DB = "/srv/ar-local/data/runs/2026-05-16/_exports/local-cdr.sqlite"

with sqlite3.connect(DB) as con:
    print("--- ribbon_normalized distribution for Mortgage ---")
    for r in con.execute(
        "SELECT ribbon_normalized, COUNT(*) FROM bank_rates WHERE dataset='Mortgage' GROUP BY ribbon_normalized"
    ):
        print(f"  ribbon_normalized={r[0]!r} count={r[1]}")

    print("--- distinct ribbon_rate_structure for Investor + interest_only (top 30) ---")
    for r in con.execute(
        "SELECT ribbon_rate_structure, COUNT(*) FROM bank_rates "
        "WHERE dataset='Mortgage' AND security_purpose='investment' AND ribbon_repayment_type='interest_only' "
        "GROUP BY ribbon_rate_structure ORDER BY COUNT(*) DESC LIMIT 30"
    ):
        rs = (r[0] or "")[:90]
        print(f"  ({r[1]}) {rs!r}")

    print("--- length distribution of ribbon_rate_structure ---")
    for r in con.execute(
        "SELECT CASE WHEN length(ribbon_rate_structure)<=10 THEN '<=10' "
        "WHEN length(ribbon_rate_structure)<=30 THEN '11-30' "
        "WHEN length(ribbon_rate_structure)<=80 THEN '31-80' "
        "ELSE '>80' END as bucket, COUNT(*) FROM bank_rates WHERE dataset='Mortgage' GROUP BY bucket"
    ):
        print(f"  {r[0]}: {r[1]}")
