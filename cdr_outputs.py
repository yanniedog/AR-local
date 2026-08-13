"""Build local CDR JSON, XLSX, SQLite, and dashboard cache artifacts."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from cdr_clean_export import coverage_summary, parse_banks_run, summary_counts, utc_now
from cdr_product_changes import diff_normalized_product_facts, load_run_facts, previous_finalized_run
from cdr_taxonomy import build_taxonomy_summary
from cdr_xlsx import write_workbook

SCHEMA_VERSION = "8"

TABLE_COLUMNS: Dict[str, List[str]] = {
    "runs": ["run_date", "generated_at", "banks_counts_json"],
    "bank_products": [
        "run_date",
        "dataset",
        "provider",
        "product_id",
        "product_key",
        "product_name",
        "category",
        "last_updated",
        "source_file",
        "details_json",
    ],
    "bank_rates": [
        "run_date",
        "dataset",
        "provider",
        "product_id",
        "product_key",
        "product_name",
        "rate_family",
        "rate",
        "comparison_rate",
        "rate_type",
        "application_type",
        "application_frequency",
        "repayment_type",
        "loan_purpose",
        "term",
        "ribbon_normalized",
        "security_purpose",
        "ribbon_repayment_type",
        "lvr_tier",
        "lvr_source",
        "ribbon_rate_structure",
        "ribbon_fixed_term",
        "account_type",
        "ribbon_deposit_kind",
        "balance_min",
        "balance_max",
        "term_months",
        "interest_payment",
        "feature_set",
        "taxonomy_path",
        "account_class",
        "details_json",
    ],
    "bank_items": [
        "run_date",
        "item_group",
        "dataset",
        "provider",
        "product_id",
        "product_key",
        "product_name",
        "item_type",
        "name",
        "value",
        "details_json",
    ],
    "bank_product_facts": [
        "run_date", "dataset", "provider", "product_id", "product_key", "product_name",
        "fact_id", "kind", "canonical_key", "value_type", "value_boolean", "value_number",
        "value_text", "value_json", "min_value", "max_value", "unit", "mapping", "source_path", "source_pattern",
        "source_value_json", "qualifiers_json",
    ],
    "bank_product_changes": [
        "run_date", "previous_run_date", "event_id", "dataset", "provider", "product_id",
        "product_name", "event_type", "canonical_key", "kind", "materiality", "equivalence",
        "review_required", "cosmetic", "material", "slots_changed", "reasons_json",
        "before_json", "after_json", "before_value_json", "after_value_json",
        "before_evidence_json", "after_evidence_json", "before_signature_json", "after_signature_json",
    ],
}

RESET_TABLES = (
    "bank_products",
    "bank_rates",
    "bank_items",
    "bank_product_facts",
    "bank_product_changes",
    "runs",
    "schema_meta",
)
REMOVED_SECTOR_TABLES = tuple("en" + "ergy_" + suffix for suffix in ("plans", "items"))
REMOVED_SECTOR_DROP_SQL = (
    'DROP TABLE IF EXISTS "en' 'ergy_plans"',
    'DROP TABLE IF EXISTS "en' 'ergy_items"',
)


def write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def row_for_columns(row: Mapping[str, Any], columns: List[str]) -> List[Any]:
    out: List[Any] = []
    for col in columns:
        val = row.get(col, "")
        if col == "ribbon_normalized":
            if val is True:
                val = "1"
            elif val is False:
                val = ""
        out.append(val)
    return out


def bank_rates_column_names(con: sqlite3.Connection) -> set[str]:
    if not table_exists(con, "bank_rates"):
        return set()
    rows = con.execute("PRAGMA table_info(bank_rates)").fetchall()
    return {str(row[1]) for row in rows}


def table_column_names(con: sqlite3.Connection, table: str) -> set[str]:
    if not table_exists(con, table):
        return set()
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({quote_table(table)})").fetchall()}


def migrate_bank_rates_columns(con: sqlite3.Connection) -> bool:
    """Add missing bank_rates columns in place (avoids wiping history on minor schema bumps)."""
    if not table_exists(con, "bank_rates"):
        return False
    existing = bank_rates_column_names(con)
    changed = False
    for column in TABLE_COLUMNS["bank_rates"]:
        if column in existing:
            continue
        con.execute(f"ALTER TABLE bank_rates ADD COLUMN {quote_column(column)} TEXT DEFAULT ''")
        changed = True
    return changed


def schema_columns_compatible(con: sqlite3.Connection) -> bool:
    if not table_exists(con, "bank_products"):
        return False
    if not table_exists(con, "bank_rates"):
        return False
    if any(table_exists(con, table) for table in REMOVED_SECTOR_TABLES):
        return False
    if table_exists(con, "runs"):
        run_cols = {str(row[1]) for row in con.execute("PRAGMA table_info(runs)").fetchall()}
        if run_cols != set(TABLE_COLUMNS["runs"]):
            return False
    return (
        bank_rates_column_names(con) >= set(TABLE_COLUMNS["bank_rates"])
        and table_column_names(con, "bank_product_facts") >= set(TABLE_COLUMNS["bank_product_facts"])
        and table_column_names(con, "bank_product_changes") >= set(TABLE_COLUMNS["bank_product_changes"])
    )


def ensure_db(con: sqlite3.Connection) -> None:
    # Ingest writes one SQLite file per run under runs/<date>/_exports/local-cdr.sqlite.
    # Re-opening the same path across runs is unsupported; a version bump normally means
    # a fresh DB for that run. migrate_bank_rates_columns() only helps when the same file
    # is reopened after adding export columns (e.g. ribbon_fixed_term) without a full reset.
    if needs_schema_reset(con):
        reset_schema(con)
    con.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS schema_meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runs (
          run_date TEXT PRIMARY KEY,
          generated_at TEXT NOT NULL,
          banks_counts_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bank_products (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_date TEXT NOT NULL,
          dataset TEXT NOT NULL,
          provider TEXT NOT NULL,
          product_id TEXT NOT NULL,
          product_key TEXT NOT NULL,
          product_name TEXT NOT NULL,
          category TEXT,
          last_updated TEXT,
          source_file TEXT NOT NULL,
          details_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bank_rates (
          run_date TEXT NOT NULL,
          dataset TEXT NOT NULL,
          provider TEXT NOT NULL,
          product_id TEXT NOT NULL,
          product_key TEXT NOT NULL,
          product_name TEXT NOT NULL,
          rate_family TEXT NOT NULL,
          rate TEXT,
          comparison_rate TEXT,
          rate_type TEXT,
          application_type TEXT,
          application_frequency TEXT,
          repayment_type TEXT,
          loan_purpose TEXT,
          term TEXT,
          ribbon_normalized TEXT,
          security_purpose TEXT,
          ribbon_repayment_type TEXT,
          lvr_tier TEXT,
          lvr_source TEXT,
          ribbon_rate_structure TEXT,
          ribbon_fixed_term TEXT,
          account_type TEXT,
          ribbon_deposit_kind TEXT,
          balance_min TEXT,
          balance_max TEXT,
          term_months TEXT,
          interest_payment TEXT,
          feature_set TEXT,
          taxonomy_path TEXT,
          account_class TEXT,
          details_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bank_items (
          run_date TEXT NOT NULL,
          item_group TEXT NOT NULL,
          dataset TEXT NOT NULL,
          provider TEXT NOT NULL,
          product_id TEXT NOT NULL,
          product_key TEXT NOT NULL,
          product_name TEXT NOT NULL,
          item_type TEXT,
          name TEXT,
          value TEXT,
          details_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bank_product_facts (
          run_date TEXT NOT NULL, dataset TEXT NOT NULL, provider TEXT NOT NULL,
          product_id TEXT NOT NULL, product_key TEXT NOT NULL, product_name TEXT NOT NULL,
          fact_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('fee','rate','tier','bundle','attribute','feature','eligibility','constraint','condition')),
          canonical_key TEXT NOT NULL,
          value_type TEXT NOT NULL CHECK(value_type IN ('boolean','money','rate','number','duration','range','enum','text')),
          value_boolean INTEGER CHECK(value_boolean IN (0,1)), value_number REAL, value_text TEXT,
          value_json TEXT NOT NULL, min_value REAL, max_value REAL,
          unit TEXT NOT NULL, mapping TEXT NOT NULL CHECK(mapping IN ('canonical','preserved','canonical_text')),
          source_path TEXT NOT NULL, source_pattern TEXT NOT NULL,
          source_value_json TEXT NOT NULL, qualifiers_json TEXT NOT NULL,
          UNIQUE(run_date, product_key, fact_id),
          CHECK(
            (value_type = 'boolean' AND value_boolean IS NOT NULL AND value_number IS NULL AND value_text IS NULL AND min_value IS NULL AND max_value IS NULL)
            OR (value_type IN ('money','rate','number') AND value_boolean IS NULL AND value_number IS NOT NULL AND value_text IS NULL AND min_value IS NULL AND max_value IS NULL)
            OR (value_type IN ('duration','enum','text') AND value_boolean IS NULL AND value_number IS NULL AND value_text IS NOT NULL AND min_value IS NULL AND max_value IS NULL)
            OR (value_type = 'range' AND value_boolean IS NULL AND value_number IS NULL AND value_text IS NULL AND (min_value IS NOT NULL OR max_value IS NOT NULL))
          )
        );
        CREATE TABLE IF NOT EXISTS bank_product_changes (
          run_date TEXT NOT NULL, previous_run_date TEXT, event_id TEXT NOT NULL,
          dataset TEXT NOT NULL, provider TEXT NOT NULL, product_id TEXT NOT NULL,
          product_name TEXT, event_type TEXT NOT NULL, canonical_key TEXT, kind TEXT,
          materiality TEXT NOT NULL, equivalence TEXT NOT NULL,
          review_required INTEGER NOT NULL CHECK(review_required IN (0,1)),
          cosmetic INTEGER NOT NULL CHECK(cosmetic IN (0,1)),
          material INTEGER NOT NULL CHECK(material IN (0,1)),
          slots_changed INTEGER NOT NULL CHECK(slots_changed IN (0,1)),
          reasons_json TEXT NOT NULL, before_json TEXT, after_json TEXT,
          before_value_json TEXT, after_value_json TEXT,
          before_evidence_json TEXT, after_evidence_json TEXT,
          before_signature_json TEXT, after_signature_json TEXT,
          UNIQUE(run_date, event_id)
        );
        CREATE INDEX IF NOT EXISTS idx_bank_rates_taxonomy
          ON bank_rates (run_date, taxonomy_path);
        CREATE INDEX IF NOT EXISTS idx_bank_rates_lookup
          ON bank_rates (run_date, dataset, provider, rate_family);
        CREATE INDEX IF NOT EXISTS idx_bank_products_provider
          ON bank_products (run_date, dataset, provider);
        CREATE INDEX IF NOT EXISTS idx_bank_product_facts_numeric
          ON bank_product_facts (run_date, dataset, canonical_key, value_number, product_key);
        CREATE INDEX IF NOT EXISTS idx_bank_product_facts_categorical
          ON bank_product_facts (run_date, dataset, canonical_key, value_text, product_key);
        CREATE INDEX IF NOT EXISTS idx_bank_product_facts_product
          ON bank_product_facts (run_date, product_key, kind);
        CREATE INDEX IF NOT EXISTS idx_bank_product_changes_lookup
          ON bank_product_changes (run_date, provider, event_type, canonical_key, product_id);
        """
    )
    con.execute(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('version', ?)",
        (SCHEMA_VERSION,),
    )


def needs_schema_reset(con: sqlite3.Connection) -> bool:
    if not table_exists(con, "bank_products"):
        return False
    migrate_bank_rates_columns(con)
    if schema_columns_compatible(con):
        return False
    return True


def reset_schema(con: sqlite3.Connection) -> None:
    for table in RESET_TABLES:
        con.execute(f"DROP TABLE IF EXISTS {quote_table(table)}")
    for sql in REMOVED_SECTOR_DROP_SQL:
        con.execute(sql)


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    return (
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )


def quote_table(table: str) -> str:
    if table not in RESET_TABLES and table not in TABLE_COLUMNS:
        raise ValueError(f"unknown table: {table}")
    return '"' + table.replace('"', '""') + '"'


def quote_column(column: str) -> str:
    known = {name for columns in TABLE_COLUMNS.values() for name in columns}
    if column not in known:
        raise ValueError(f"unknown column: {column}")
    return '"' + column.replace('"', '""') + '"'


def insert_rows(con: sqlite3.Connection, table: str, rows: List[Mapping[str, Any]]) -> None:
    if not rows:
        return
    columns = TABLE_COLUMNS[table]
    placeholders = ",".join("?" for _ in columns)
    quoted_columns = ",".join(quote_column(col) for col in columns)
    sql = f"INSERT INTO {quote_table(table)} ({quoted_columns}) VALUES ({placeholders})"
    values = (
        [[row.get(column) for column in columns] for row in rows]
        if table in {"bank_product_facts", "bank_product_changes"}
        else [row_for_columns(row, columns) for row in rows]
    )
    con.executemany(sql, values)


def rebuild_run_db(db_path: Path, run_date: str, banks: Mapping[str, Any]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as con:
        ensure_db(con)
        for table in TABLE_COLUMNS:
            if table != "runs":
                con.execute(f"DELETE FROM {quote_table(table)} WHERE run_date = ?", (run_date,))
        con.execute("DELETE FROM runs WHERE run_date = ?", (run_date,))
        con.execute(
            "INSERT INTO runs VALUES (?, ?, ?)",
            (
                run_date,
                utc_now(),
                json.dumps(summary_counts(banks), sort_keys=True),
            ),
        )
        insert_rows(con, "bank_products", with_run_date(banks["products"], run_date))
        insert_rows(con, "bank_rates", with_run_date(banks["rates"], run_date))
        for group in ("fees", "features", "eligibility", "constraints"):
            insert_rows(con, "bank_items", with_run_date(add_group(banks[group], group), run_date))
        insert_rows(con, "bank_product_facts", with_run_date(banks["product_facts"], run_date))
        insert_rows(con, "bank_product_changes", banks.get("product_changes", []))


def add_group(rows: List[Mapping[str, Any]], group: str) -> List[Dict[str, Any]]:
    return [{**row, "item_group": group} for row in rows]


def with_run_date(rows: List[Mapping[str, Any]], run_date: str) -> List[Dict[str, Any]]:
    return [{"run_date": run_date, **row} for row in rows]


def write_sector_workbooks(out_dir: Path, run_date: str, banks: Mapping[str, Any]) -> None:
    write_workbook(
        out_dir / f"banks-{run_date}.xlsx",
        {
            "taxonomy": build_taxonomy_summary(banks["rates"]),
            "products": banks["products"],
            "rates": banks["rates"],
            "fees": banks["fees"],
            "features": banks["features"],
            "eligibility": banks["eligibility"],
            "constraints": banks["constraints"],
            "product_facts": banks["product_facts"],
            "product_changes": banks.get("product_changes", []),
            "change_summary": [{
                **{key: value for key, value in (banks.get("product_change_summary") or {}).items() if key != "products"},
                "products_json": json.dumps((banks.get("product_change_summary") or {}).get("products") or {}, sort_keys=True),
            }],
            "failures": banks["failures"],
        },
    )


def write_dashboard_cache(out_dir: Path, run_date: str, banks: Mapping[str, Any]) -> None:
    cache_dir = out_dir / "dashboard-cache" / run_date
    banks_cache = {
        "run_date": run_date,
        "products": banks["products"],
        "rates": banks["rates"],
        "counts": summary_counts(banks),
        "coverage": coverage_summary(banks, run_date),
    }
    manifest = {
        "generated_at": utc_now(),
        "run_date": run_date,
        "banks_counts": banks_cache["counts"],
        "files": {
            "banks_json": f"banks-{run_date}.json",
            "banks_xlsx": f"banks-{run_date}.xlsx",
            "db": "local-cdr.sqlite",
        },
    }
    write_json(cache_dir / "banks.json", banks_cache)
    write_json(cache_dir / "manifest.json", manifest)
    write_json(out_dir / "dashboard-cache" / "latest.json", manifest)


def product_change_rows(report: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for event in report.get("events") or []:
        if not isinstance(event, Mapping):
            continue
        rows.append({
            "run_date": report.get("run_date") or report.get("current_run_date"),
            "previous_run_date": report.get("previous_run_date"),
            "event_id": event.get("event_id"), "dataset": event.get("dataset"),
            "provider": event.get("provider"), "product_id": event.get("product_id"),
            "product_name": event.get("product_name"), "event_type": event.get("event_type"),
            "canonical_key": event.get("canonical_key"), "kind": event.get("kind"),
            "materiality": event.get("materiality"), "equivalence": event.get("equivalence"),
            "review_required": int(bool(event.get("review_required"))),
            "cosmetic": int(bool(event.get("cosmetic"))), "material": int(bool(event.get("material"))),
            "slots_changed": int(bool(event.get("slots_changed"))),
            "reasons_json": json.dumps(event.get("reasons") or [], ensure_ascii=False, sort_keys=True),
            "before_json": json.dumps(event.get("before"), ensure_ascii=False, sort_keys=True),
            "after_json": json.dumps(event.get("after"), ensure_ascii=False, sort_keys=True),
            **{key: event.get(key) for key in (
                "before_value_json", "after_value_json", "before_evidence_json", "after_evidence_json",
                "before_signature_json", "after_signature_json",
            )},
        })
    return rows


def build_outputs(
    run_root: Path,
    out_dir: Optional[Path] = None,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    out_dir = (out_dir or (run_root / "_exports")).resolve()
    run_date = run_root.name
    banks = parse_banks_run(run_root)
    previous = previous_finalized_run(run_root)
    changes = diff_normalized_product_facts(
        load_run_facts(previous),
        banks["product_facts"],
        previous_run_date=previous.name,
        current_run_date=run_date,
    ) if previous else {
        "schema_version": 1, "normalization_version": None,
        "previous_run_date": None, "run_date": run_date, "change_count": 0,
        "products": {"previous": 0, "current": len(banks["products"]), "joined": 0},
        "events": [],
    }
    banks["product_changes"] = product_change_rows(changes)
    banks["product_change_summary"] = {
        "schema_version": changes.get("schema_version", 1),
        "normalization_version": changes.get("normalization_version"),
        "previous_run_date": changes.get("previous_run_date"),
        "run_date": changes.get("run_date", run_date),
        "change_count": changes.get("change_count", len(changes.get("events") or [])),
        "products": changes.get("products") or {},
    }
    write_json(out_dir / f"banks-{run_date}.json", banks)
    write_sector_workbooks(out_dir, run_date, banks)
    rebuild_run_db(db_path or (out_dir / "local-cdr.sqlite"), run_date, banks)
    write_dashboard_cache(out_dir, run_date, banks)
    return {"run_date": run_date, "out_dir": str(out_dir), "banks": summary_counts(banks)}


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build local CDR exports from one run folder.")
    parser.add_argument("run_root", type=Path, help="Run date folder, e.g. runs/2026-05-06")
    parser.add_argument("--out", type=Path, default=None, help="Export folder (default: <run>/_exports)")
    parser.add_argument("--db", type=Path, default=None, help="SQLite path (default: <out>/local-cdr.sqlite)")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    result = build_outputs(
        args.run_root.expanduser().resolve(),
        args.out,
        args.db,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
