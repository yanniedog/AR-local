"""Additive public-pricing tables in the existing evidence database.

The original terms schema and every frozen executable contract remain unchanged.
Only reviewed adapters can produce observations; there is no data-override API.
"""
from __future__ import annotations

import sqlite3


SCHEMA = """
CREATE TABLE IF NOT EXISTS public_rate_schema (
    version INTEGER PRIMARY KEY CHECK(version=1),
    installed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT OR IGNORE INTO public_rate_schema(version) VALUES (1);
CREATE TABLE IF NOT EXISTS public_rate_registers (
    register_id TEXT PRIMARY KEY CHECK(length(register_id)=64),
    register_version TEXT NOT NULL,
    body_sha256 TEXT NOT NULL CHECK(length(body_sha256)=64),
    observed_at TEXT NOT NULL,
    UNIQUE(register_version,body_sha256)
);
CREATE TABLE IF NOT EXISTS public_rate_sources (
    binding_id TEXT PRIMARY KEY CHECK(length(binding_id)=64),
    source_id TEXT NOT NULL,
    register_id TEXT NOT NULL REFERENCES public_rate_registers(register_id),
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    adapter_id TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    context_json TEXT NOT NULL,
    UNIQUE(register_id,source_id)
);
CREATE INDEX IF NOT EXISTS public_rate_sources_document ON public_rate_sources(document_id);
CREATE TABLE IF NOT EXISTS public_rate_checks (
    binding_id TEXT NOT NULL REFERENCES public_rate_sources(binding_id),
    check_id TEXT NOT NULL REFERENCES acquisition_checks(check_id),
    ingest_id TEXT NOT NULL,
    request_id TEXT REFERENCES acquisition_requests(request_id),
    PRIMARY KEY(binding_id,check_id)
);
CREATE TABLE IF NOT EXISTS public_rate_request_bindings (
    request_id TEXT NOT NULL REFERENCES acquisition_requests(request_id),
    binding_id TEXT NOT NULL REFERENCES public_rate_sources(binding_id),
    PRIMARY KEY(request_id,binding_id)
);
CREATE TABLE IF NOT EXISTS public_rate_extractions (
    extraction_id TEXT PRIMARY KEY CHECK(length(extraction_id)=64),
    binding_id TEXT NOT NULL REFERENCES public_rate_sources(binding_id),
    document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id),
    adapter_version TEXT NOT NULL,
    semantic_sha256 TEXT NOT NULL CHECK(length(semantic_sha256)=64),
    result_sha256 TEXT NOT NULL CHECK(length(result_sha256)=64),
    status TEXT NOT NULL CHECK(status IN ('validated','review_required','unresolved','failed')),
    observed_at TEXT NOT NULL,
    reason_code TEXT,
    UNIQUE(binding_id,document_version_id,adapter_version)
);
CREATE TABLE IF NOT EXISTS public_rate_observations (
    observation_id TEXT PRIMARY KEY CHECK(length(observation_id)=64),
    reference_id TEXT NOT NULL,
    extraction_id TEXT NOT NULL REFERENCES public_rate_extractions(extraction_id),
    value_json TEXT NOT NULL,
    effective_from TEXT,
    effective_to TEXT,
    UNIQUE(reference_id,extraction_id)
);
CREATE INDEX IF NOT EXISTS public_rate_observations_reference ON public_rate_observations(reference_id,effective_from);
CREATE INDEX IF NOT EXISTS public_rate_extractions_binding_clock ON public_rate_extractions(binding_id,status,observed_at);
CREATE TABLE IF NOT EXISTS public_rate_extraction_evidence (
    extraction_id TEXT NOT NULL REFERENCES public_rate_extractions(extraction_id),
    evidence_id TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    PRIMARY KEY(extraction_id,evidence_id)
);
CREATE TABLE IF NOT EXISTS public_rate_review_queue (
    review_id TEXT PRIMARY KEY CHECK(length(review_id)=64),
    extraction_id TEXT NOT NULL UNIQUE REFERENCES public_rate_extractions(extraction_id),
    reason_code TEXT NOT NULL,
    created_at TEXT NOT NULL,
    required_adapter_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS public_rate_products (
    product_id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    product_key TEXT NOT NULL,
    UNIQUE(provider_id,product_key)
);
CREATE TABLE IF NOT EXISTS public_rate_product_versions (
    product_id TEXT NOT NULL REFERENCES public_rate_products(product_id),
    observation_id TEXT NOT NULL REFERENCES observations(observation_id),
    discovery_json TEXT NOT NULL,
    PRIMARY KEY(product_id,observation_id)
);
CREATE TABLE IF NOT EXISTS public_rate_programmes (
    programme_id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES public_rate_products(product_id),
    offer_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS public_rate_programme_versions (
    version_id TEXT PRIMARY KEY CHECK(length(version_id)=64),
    programme_id TEXT NOT NULL REFERENCES public_rate_programmes(programme_id),
    observation_id TEXT NOT NULL REFERENCES observations(observation_id),
    body_sha256 TEXT NOT NULL CHECK(length(body_sha256)=64),
    UNIQUE(programme_id,observation_id)
);
CREATE INDEX IF NOT EXISTS public_rate_programme_versions_observation ON public_rate_programme_versions(observation_id,programme_id);
CREATE TABLE IF NOT EXISTS public_rate_programme_summaries (
    version_id TEXT PRIMARY KEY REFERENCES public_rate_programme_versions(version_id),
    has_formula INTEGER NOT NULL CHECK(has_formula IN (0,1))
);
CREATE TABLE IF NOT EXISTS public_rate_evidence_bindings (
    version_id TEXT NOT NULL REFERENCES public_rate_programme_versions(version_id),
    evidence_id TEXT NOT NULL,
    observation_id TEXT REFERENCES observations(observation_id),
    document_version_id TEXT REFERENCES document_versions(document_version_id),
    locator_json TEXT NOT NULL,
    PRIMARY KEY(version_id,evidence_id),
    CHECK(observation_id IS NOT NULL OR document_version_id IS NOT NULL)
);
CREATE TABLE IF NOT EXISTS public_rate_source_evidence (
    evidence_id TEXT NOT NULL,
    observation_id TEXT NOT NULL REFERENCES observations(observation_id),
    evidence_json TEXT NOT NULL,
    PRIMARY KEY(evidence_id,observation_id)
);
CREATE INDEX IF NOT EXISTS observations_public_ingest ON observations(ingest_id);
CREATE TABLE IF NOT EXISTS public_rate_coverage (
    coverage_id TEXT PRIMARY KEY CHECK(length(coverage_id)=64),
    ingest_id TEXT NOT NULL,
    register_id TEXT NOT NULL REFERENCES public_rate_registers(register_id),
    body_sha256 TEXT NOT NULL CHECK(length(body_sha256)=64),
    observed_at TEXT NOT NULL,
    UNIQUE(ingest_id,register_id,body_sha256)
);
CREATE TABLE IF NOT EXISTS public_rate_candidate_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE CHECK(length(event_id)=64),
    ingest_id TEXT NOT NULL,
    register_id TEXT NOT NULL REFERENCES public_rate_registers(register_id),
    status TEXT NOT NULL CHECK(status IN ('dirty','fresh')),
    observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS public_rate_candidate_due ON public_rate_candidate_events(ingest_id,register_id,sequence DESC);
"""


def install(db: sqlite3.Connection) -> None:
    """Idempotent additive migration; the store installs immutable triggers next."""
    db.executescript(SCHEMA)
    from .public_rates_budget_migration import install as install_budget
    install_budget(db)

