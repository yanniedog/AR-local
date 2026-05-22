"""Local SQL-backed shims for public AustralianRates API routes used by macro pages."""

from __future__ import annotations

import contextlib
import json
import re
import sqlite3
from pathlib import Path


@contextlib.contextmanager
def connect_readonly(db_path: Path):
    """Open a SQLite file read-only without attempting to create lock files.

    Default ``sqlite3.connect(path)`` opens for read+write and tries to
    create a ``-journal`` or ``-wal`` sibling on first statement, which
    fails with "attempt to write a readonly database" when the parent
    ``_exports/`` directory is not writable by the dashboard service
    user (e.g. when an ingest invoked via sudo leaves a
    ``runs/<date>/_exports/`` tree owned by root).

    ``mode=ro`` alone is insufficient on the deployed Pi (SQLite 3.46.1
    with default compile options) — even ``mode=ro`` still tries to
    acquire a SHARED lock that needs to write a lock file into the
    parent dir. ``nolock=1`` is the URI flag that would skip locking,
    but this SQLite build was not compiled with the option enabled.
    ``immutable=1`` is the remaining workaround that lets the open
    succeed on root-owned directories.

    Trade-off (Codex review feedback on PR #114): ``immutable=1`` tells
    SQLite the file will not change while open, so it skips change
    detection. If an ingest rewrote the same DB file during a read,
    the result would be undefined. In practice this is safe for the
    bank-history payload because:

    - Run-export DBs are per-date artifacts: ``runs/<date>/_exports/
      local-cdr.sqlite`` is written once during the ingest of that
      date and never rewritten afterwards.
    - The history endpoint reads PAST dates' DBs, which are static.
    - The only file that could be written while being read is the
      current date's DB during the ~5 minutes of scheduled ingest at
      06:00 AEST. Mitigations: nightly traffic is near zero, and
      ``bank_history_payload`` already catches ``sqlite3.Error`` and
      skips unreadable DBs rather than failing the whole request.

    If the ingest pipeline ever starts rewriting historical DBs, this
    helper must be revisited.

    Wrapped with ``@contextlib.contextmanager`` so the caller's ``with``
    block actually closes the connection — Python's default ``sqlite3``
    context manager only commits/rolls back the transaction (Gemini
    review feedback on PR #114).
    """
    uri = f"file:{db_path}?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    try:
        yield con
    finally:
        con.close()


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
