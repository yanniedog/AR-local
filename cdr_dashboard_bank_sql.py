"""Read-only banking dashboard SQL, shared by section and history routes."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

from cdr_product_classification import excluded_category_tokens, has_savings_term_deposit_evidence
from cdr_public_api_shims import connect_readonly as _connect_readonly


def register_bank_category_filter(connection: sqlite3.Connection) -> None:
    def source_term_deposit(details_json):
        try:
            detail = json.loads(details_json or "null")
            return int(isinstance(detail, dict) and has_savings_term_deposit_evidence(detail))
        except (ValueError, TypeError):
            return 0

    connection.create_function("cdr_source_term_deposit", 1, source_term_deposit, deterministic=True)


@contextmanager
def connect_readonly(path: Path, *, connector=None, register=None):
    with (connector or _connect_readonly)(path) as connection:
        (register or register_bank_category_filter)(connection)
        yield connection


def bank_section_rate_filter(run_date: str | None, section: str) -> tuple[str, list[str]]:
    excluded = excluded_category_tokens(section)
    # Bind the section/date so SQLite builds one exclusion set, without a
    # correlated product scan for each rate. Historical identity includes date.
    identity = "product_key" if run_date else "(run_date, product_key)"
    columns = "product_key" if run_date else "run_date, product_key"
    date_clause = "run_date = ? AND " if run_date else ""
    category_params = [run_date, section, *excluded] if run_date else [section, *excluded]
    category_sql = (f" AND {identity} NOT IN (SELECT {columns} FROM bank_products WHERE "
                    + date_clause + "dataset = ? AND product_key IS NOT NULL AND run_date IS NOT NULL AND "
                    "UPPER(COALESCE(category, '')) IN (" + ",".join("?" for _ in excluded) + ")"
                    + (" AND cdr_source_term_deposit(details_json) = 0" if section == "TD" else "") + ")")
    if section == "Mortgage":
        return " AND rate_family = ? AND COALESCE(rate_type, '') != ?" + category_sql, ["lending", "DISCOUNT", *category_params]
    return " AND rate_family = ?" + category_sql, ["deposit", *category_params]


def bank_history_rate_filter(section: str, *, rate_filter=bank_section_rate_filter) -> tuple[str, list[str]]:
    # The unscoped endpoint is the union of the same three section policies.
    # Keep each predicate bound to its dataset: a product's category on another
    # day or in another section cannot exclude a valid historical observation.
    sections = (section,) if section else ("Mortgage", "Savings", "TD")
    clauses = []
    params = []
    for selected in sections:
        tail, values = rate_filter(None, selected)
        clauses.append("(dataset = ?" + tail + ")")
        params.extend([selected, *values])
    return " AND (" + " OR ".join(clauses) + ")", params


def bank_rate_columns(con: sqlite3.Connection) -> set[str]:
    rows = con.execute("PRAGMA table_info(bank_rates)").fetchall()
    return {str(row[1]) for row in rows}


def bank_rate_select_list(available: set[str], columns: tuple[str, ...]) -> str:
    return ", ".join(column if column in available else f"'' AS {column}" for column in columns)


def select_bank_history_rows(
    con: sqlite3.Connection, max_run_date: str, section: str, columns: tuple[str, ...],
    *, rate_filter=bank_section_rate_filter,
):
    select_list = bank_rate_select_list(bank_rate_columns(con), columns)
    sql = f"SELECT {select_list} FROM bank_rates WHERE rate IS NOT NULL AND rate != ''"
    params = []
    if max_run_date:
        sql += " AND run_date <= ?"
        params.append(max_run_date)
    tail, filter_params = bank_history_rate_filter(section, rate_filter=rate_filter)
    # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query
    for row in con.execute(sql + tail, [*params, *filter_params]):
        yield dict(zip(columns, row))
