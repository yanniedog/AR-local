"""Local SQL-backed shims for public AustralianRates API routes used by macro pages."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite file in immutable read-only mode.

    Default ``sqlite3.connect(path)`` opens for read+write and tries to create
    a ``-journal`` or ``-wal`` sibling on first statement, which fails with
    "attempt to write a readonly database" when the parent directory is not
    writable by the dashboard service user. The dashboard never mutates the
    run-export DBs, so ``immutable=1`` skips lock files entirely and survives
    mixed-ownership ``runs/`` trees (e.g. when an ingest is invoked via sudo
    and leaves files owned by root).
    """
    return sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)


def response_rows(rows: list[dict[str, object]]) -> bytes:
    return json.dumps(
        {"ok": True, "rows": rows},
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def percent_rate(raw: object) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value * 100.0 if value <= 1.0 else value


def query_limit(query: dict[str, list[str]], default: int = 20000) -> int:
    raw = str(query.get("limit", [str(default)])[0] or default)
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(1, min(value, 50000))


def min_rate_filter(query: dict[str, list[str]]) -> float:
    raw = str(query.get("min_rate", ["0"])[0] or "0")
    try:
        return float(raw)
    except ValueError:
        return 0.0


def latest_term_deposit_rows(db_path: Path, run_date: str, query: dict[str, list[str]]) -> bytes:
    min_rate = min_rate_filter(query)
    limit = query_limit(query)
    with connect_readonly(db_path) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT provider, product_id, product_name, rate, term_months, interest_payment
            FROM bank_rates
            WHERE run_date = ? AND dataset = 'TD' AND rate_family = 'deposit'
              AND rate IS NOT NULL AND rate != '' AND term_months IS NOT NULL AND term_months != ''
            LIMIT ?
            """,
            (run_date, limit),
        ).fetchall()
    out: list[dict[str, object]] = []
    for row in rows:
        rate = percent_rate(row["rate"])
        if rate is None or rate < min_rate:
            continue
        try:
            months = int(float(row["term_months"]))
        except (TypeError, ValueError):
            continue
        if months <= 0:
            continue
        out.append(
            {
                "collection_date": run_date,
                "bank_name": row["provider"],
                "product_id": row["product_id"],
                "product_name": row["product_name"],
                "interest_rate": rate,
                "term_months": months,
                "interest_payment": row["interest_payment"] or "",
            },
        )
    return response_rows(out)


def latest_home_loan_rows(db_path: Path, run_date: str, query: dict[str, list[str]]) -> bytes:
    structure = str(query.get("rate_structure", [""])[0] or "")
    security = str(query.get("security_purpose", [""])[0] or "")
    repayment = str(query.get("repayment_type", [""])[0] or "")
    min_rate = min_rate_filter(query)
    limit = query_limit(query)
    fixed_years = ""
    match = re.fullmatch(r"fixed_(\d+)yr", structure)
    if match:
        fixed_years = match.group(1)
    with connect_readonly(db_path) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT provider, product_id, product_name, rate, security_purpose,
                   ribbon_repayment_type, ribbon_fixed_term
            FROM bank_rates
            WHERE run_date = ? AND dataset = 'Mortgage' AND rate_family = 'lending'
              AND COALESCE(rate_type, '') != 'DISCOUNT'
              AND rate IS NOT NULL AND rate != ''
            LIMIT ?
            """,
            (run_date, limit),
        ).fetchall()
    out: list[dict[str, object]] = []
    for row in rows:
        if security and str(row["security_purpose"] or "") != security:
            continue
        if repayment and str(row["ribbon_repayment_type"] or "") != repayment:
            continue
        if fixed_years and str(row["ribbon_fixed_term"] or "") != fixed_years:
            continue
        rate = percent_rate(row["rate"])
        if rate is None or rate < min_rate:
            continue
        term = str(row["ribbon_fixed_term"] or "")
        rate_structure = f"fixed_{term}yr" if term else "variable"
        out.append(
            {
                "collection_date": run_date,
                "bank_name": row["provider"],
                "product_id": row["product_id"],
                "product_name": row["product_name"],
                "interest_rate": rate,
                "rate_structure": rate_structure,
                "security_purpose": row["security_purpose"] or "",
                "repayment_type": row["ribbon_repayment_type"] or "",
            },
        )
    return response_rows(out)


def local_rba_history_rows() -> bytes:
    return response_rows([])
