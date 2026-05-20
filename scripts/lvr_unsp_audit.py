"""Phase-1 audit: where LVR lives for mortgage lending rows marked lvr_unspecified."""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from cdr_ribbon_normalize import (  # noqa: E402
    parse_lvr_bounds_from_constraints,
    parse_lvr_bounds_from_rate_item,
)


def _load_constraints_by_product(exports: Path) -> dict[tuple[str, str], list[dict]]:
    out: dict[tuple[str, str], list[dict]] = {}
    banks = exports / "dashboard-cache"
    latest = json.loads((banks / "latest.json").read_text(encoding="utf-8"))
    run_date = latest.get("run_date") or latest.get("date")
    path = banks / str(run_date) / "banks.json"
    if not path.is_file():
        return out
    payload = json.loads(path.read_text(encoding="utf-8"))
    for row in payload.get("constraints") or []:
        if str(row.get("dataset") or "") != "Mortgage":
            continue
        key = (str(row.get("provider") or ""), str(row.get("product_id") or ""))
        out.setdefault(key, []).append(row)
    return out


def _constraint_has_lvr(row: dict) -> bool:
    ctype = str(row.get("item_type") or row.get("constraintType") or "").lower()
    name = str(row.get("name") or "").lower()
    value = str(row.get("value") or "").lower()
    blob = f"{ctype} {name} {value}"
    return "lvr" in blob or "loan to value" in blob or "ltv" in blob


def _parse_product_lvr(constraints: list[dict]) -> tuple[float | None, float | None] | None:
    items = []
    for row in constraints:
        if not _constraint_has_lvr(row):
            continue
        detail = row.get("details_json")
        if isinstance(detail, str) and detail.strip():
            try:
                parsed = json.loads(detail)
            except json.JSONDecodeError:
                parsed = {}
        else:
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}
        parsed.setdefault("constraintType", row.get("item_type") or "")
        items.append(parsed)
    if not items:
        return None
    bounds = parse_lvr_bounds_from_constraints(items)
    return bounds


def audit(exports: Path) -> dict:
    db = exports / "local-cdr.sqlite"
    if not db.is_file():
        raise SystemExit(f"missing sqlite: {db}")

    product_constraints = _load_constraints_by_product(exports)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT provider, product_id, product_name, rate_type,
               lvr_tier, details_json
        FROM bank_rates
        WHERE dataset = 'Mortgage' AND rate_family = 'lending'
        """
    ).fetchall()
    con.close()

    reasons = Counter()
    samples: dict[str, list[str]] = {}

    for row in rows:
        tier = str(row["lvr_tier"] or "")
        if tier and tier != "lvr_unspecified":
            continue
        provider = str(row["provider"] or "")
        product_id = str(row["product_id"] or "")
        detail = {}
        raw = row["details_json"]
        if raw:
            try:
                detail = json.loads(raw)
            except json.JSONDecodeError:
                detail = {}
        rate_bounds = parse_lvr_bounds_from_rate_item(detail if isinstance(detail, dict) else {})
        if rate_bounds != (None, None):
            reasons["rate_has_bounds_but_unspecified"] += 1
            bucket = "rate_has_bounds_but_unspecified"
        else:
            prod_rows = product_constraints.get((provider, product_id), [])
            prod_bounds = _parse_product_lvr(prod_rows) if prod_rows else None
            if prod_bounds and prod_bounds != (None, None):
                reasons["product_constraints_only"] += 1
                bucket = "product_constraints_only"
            else:
                text_bits = [
                    str(detail.get("additionalInfo") or ""),
                    str(detail.get("additionalValue") or ""),
                    str(detail.get("name") or ""),
                    str(row["product_name"] or ""),
                ]
                joined = " ".join(text_bits).lower()
                if "%" in joined and ("lvr" in joined or "loan to value" in joined or "ltv" in joined):
                    reasons["text_lvr_not_parsed"] += 1
                    bucket = "text_lvr_not_parsed"
                elif prod_rows and any(_constraint_has_lvr(r) for r in prod_rows):
                    reasons["product_lvr_unparsed"] += 1
                    bucket = "product_lvr_unparsed"
                else:
                    reasons["no_lvr_signal"] += 1
                    bucket = "no_lvr_signal"

        label = f"{provider} | {row['product_name']} | {row['rate_type']}"
        samples.setdefault(bucket, [])
        if len(samples[bucket]) < 3:
            samples[bucket].append(label)

    total_unsp = sum(reasons.values())
    total_mortgage = sum(1 for r in rows if True)
    # recount mortgage
    mortgage_n = len(rows)
    classified = mortgage_n - total_unsp

    return {
        "mortgage_lending_rows": mortgage_n,
        "lvr_unspecified_rows": total_unsp,
        "lvr_classified_rows": classified,
        "pct_unspecified": round(100 * total_unsp / mortgage_n, 2) if mortgage_n else 0,
        "reasons": dict(reasons),
        "samples": samples,
    }


def main() -> None:
    exports = REPO / "runs" / "2026-05-19" / "_exports"
    if len(sys.argv) > 1:
        exports = Path(sys.argv[1])
    report = audit(exports)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
