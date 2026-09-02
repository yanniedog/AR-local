"""Create immutable v7/v8 backup fixtures; never used by production ingest."""

from __future__ import annotations

import json
import sqlite3
import textwrap
from pathlib import Path


SCHEMA = """
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
"""


def write_legacy_export(root: Path, date: str) -> Path:
    exports = root / f"data/runs/{date}/_exports"
    (exports / "dashboard-cache").mkdir(parents=True)
    groups = {
        "products": [], "rates": [], "product_facts": [], "product_changes": [],
        "fees": [], "features": [], "eligibility": [], "constraints": [],
        "failures": [{}, {}, {}], "holder_attempts": [{}, {}],
    }
    counts = {key: len(value) for key, value in groups.items()}
    (exports / f"banks-{date}.json").write_text(json.dumps(groups), encoding="utf-8")
    (exports / "dashboard-cache/latest.json").write_text(
        json.dumps({"run_date": date, "banks_counts": counts}), encoding="utf-8"
    )
    database = exports / "local-cdr.sqlite"
    connection = sqlite3.connect(database)
    try:
        # sqlite_master preserves the indentation from the historical schema
        # literal. Keep it exact so the immutable v8 definition hashes verify.
        connection.executescript(textwrap.indent(SCHEMA, "        "))
        connection.executemany(
            "INSERT INTO schema_meta VALUES (?, ?)",
            (("version", "8"), ("normalization_version", "legacy-test")),
        )
        connection.execute(
            "INSERT INTO runs VALUES (?, ?, ?)",
            (date, "2026-08-25T00:00:00Z", json.dumps(counts)),
        )
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()
    return exports
