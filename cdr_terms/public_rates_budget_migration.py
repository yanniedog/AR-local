"""Additive immutable admission and retained compilation input records."""
from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS public_rate_budget_reservations (
    reservation_id TEXT PRIMARY KEY CHECK(length(reservation_id)=64),
    ingest_id TEXT NOT NULL REFERENCES ingest_capture_attempts(ingest_id),
    work_id TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK(kind IN ('capture','source','candidate')),
    reserved_bytes INTEGER NOT NULL CHECK(reserved_bytes BETWEEN 0 AND 67108864),
    reserved_ms INTEGER NOT NULL CHECK(reserved_ms BETWEEN 1 AND 300000),
    observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS public_rate_budget_ingest ON public_rate_budget_reservations(ingest_id);
CREATE TABLE IF NOT EXISTS public_rate_budget_settlements (
    reservation_id TEXT PRIMARY KEY REFERENCES public_rate_budget_reservations(reservation_id),
    charged_bytes INTEGER NOT NULL CHECK(charged_bytes BETWEEN 0 AND 67108864),
    charged_ms INTEGER NOT NULL CHECK(charged_ms>=0),
    observed_at TEXT NOT NULL,
    check_id TEXT REFERENCES acquisition_checks(check_id)
);
CREATE TABLE IF NOT EXISTS public_rate_compile_inputs (
    observation_id TEXT PRIMARY KEY REFERENCES observations(observation_id),
    ingest_id TEXT NOT NULL REFERENCES ingest_capture_attempts(ingest_id),
    context_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS public_rate_compile_inputs_ingest ON public_rate_compile_inputs(ingest_id,observation_id);
CREATE TABLE IF NOT EXISTS public_rate_compile_jobs (
    ingest_id TEXT PRIMARY KEY REFERENCES ingest_capture_attempts(ingest_id),
    register_id TEXT NOT NULL REFERENCES public_rate_registers(register_id),
    receipt_sha256 TEXT NOT NULL CHECK(length(receipt_sha256)=64)
);
"""


def install(db: sqlite3.Connection) -> None:
    db.executescript(SCHEMA)
