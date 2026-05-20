"""Phase 5: compare mortgage LVR unspecified counts before/after resolve_lvr_tier."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def counts(exports: Path) -> dict:
    db = exports / "local-cdr.sqlite"
    con = sqlite3.connect(db)
    mortgage = con.execute(
        "SELECT COUNT(*) FROM bank_rates WHERE dataset='Mortgage' AND rate_family='lending'"
    ).fetchone()[0]
    unsp = con.execute(
        """
        SELECT COUNT(*) FROM bank_rates
        WHERE dataset='Mortgage' AND rate_family='lending'
          AND (lvr_tier IS NULL OR lvr_tier = '' OR lvr_tier = 'lvr_unspecified')
        """
    ).fetchone()[0]
    cols = {r[1] for r in con.execute("PRAGMA table_info(bank_rates)").fetchall()}
    by_source: dict[str, int] = {}
    if "lvr_source" in cols:
        by_source = {
            r[0]: r[1]
            for r in con.execute(
                """
                SELECT COALESCE(NULLIF(lvr_source, ''), 'empty') AS src, COUNT(*)
                FROM bank_rates
                WHERE dataset='Mortgage' AND rate_family='lending'
                GROUP BY src
                ORDER BY COUNT(*) DESC
                """
            ).fetchall()
        }
    con.close()
    classified = mortgage - unsp
    return {
        "mortgage_lending_rows": mortgage,
        "lvr_unspecified_rows": unsp,
        "lvr_classified_rows": classified,
        "pct_unspecified": round(100 * unsp / mortgage, 2) if mortgage else 0,
        "lvr_source_counts": by_source,
    }


def main() -> None:
    exports = REPO / "runs" / "2026-05-19" / "_exports"
    print(json.dumps(counts(exports), indent=2))


if __name__ == "__main__":
    main()
