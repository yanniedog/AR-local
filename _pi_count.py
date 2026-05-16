"""Throwaway: count bank_items by group on each retained Pi DB."""
import sqlite3
import os

RUNS = "/srv/ar-local/data/runs"


def main() -> None:
    for d in sorted(os.listdir(RUNS)):
        db = os.path.join(RUNS, d, "_exports", "local-cdr.sqlite")
        if not os.path.isfile(db):
            continue
        with sqlite3.connect(db) as con:
            products = con.execute("SELECT COUNT(*) FROM bank_products").fetchone()[0]
            rates = con.execute("SELECT COUNT(*) FROM bank_rates").fetchone()[0]
            features = con.execute("SELECT COUNT(*) FROM bank_items WHERE item_group='features'").fetchone()[0]
            eligi = con.execute("SELECT COUNT(*) FROM bank_items WHERE item_group='eligibility'").fetchone()[0]
            fees = con.execute("SELECT COUNT(*) FROM bank_items WHERE item_group='fees'").fetchone()[0]
            constraints = con.execute("SELECT COUNT(*) FROM bank_items WHERE item_group='constraints'").fetchone()[0]
            sample = con.execute(
                "SELECT provider, COUNT(*) FROM bank_items WHERE item_group='features' GROUP BY provider ORDER BY COUNT(*) DESC LIMIT 5"
            ).fetchall()
        print(f"{d}: products={products} rates={rates} features={features} eligibility={eligi} fees={fees} constraints={constraints}")
        print(f"  top feature counts: {sample}")


main()
