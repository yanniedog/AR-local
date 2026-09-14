-- Dedicated evidence database. Never apply this schema to a retained CDR DB.
-- IDs are SHA-256 canonical identities. product_key is the existing export key.
CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY CHECK(length(document_id)=64),
    source_url TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS observations (
    observation_id TEXT PRIMARY KEY CHECK(length(observation_id)=64),
    ingest_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    product_key TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64)
);
CREATE INDEX IF NOT EXISTS observations_product ON observations(product_key, observed_at DESC);
CREATE TABLE IF NOT EXISTS applicability (
    applicability_id TEXT PRIMARY KEY,
    observation_id TEXT NOT NULL REFERENCES observations(observation_id),
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    source_path TEXT NOT NULL,
    relation TEXT NOT NULL,
    context_json TEXT NOT NULL,
    UNIQUE(observation_id, document_id, source_path, context_json)
);
CREATE INDEX IF NOT EXISTS applicability_document ON applicability(document_id, observation_id);
CREATE TABLE IF NOT EXISTS document_versions (
    document_version_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    content_sha256 TEXT NOT NULL CHECK(length(content_sha256)=64),
    media_type TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK(byte_size > 0),
    observed_at TEXT NOT NULL,
    effective_from TEXT,
    effective_to TEXT,
    UNIQUE(document_id, content_sha256)
);
CREATE TABLE IF NOT EXISTS acquisition_checks (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    check_id TEXT NOT NULL UNIQUE,
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    checked_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('fetched','unchanged','failed','deferred')),
    http_status INTEGER,
    document_version_id TEXT REFERENCES document_versions(document_version_id),
    error_code TEXT,
    metadata_json TEXT NOT NULL,
    CHECK((status IN ('fetched','unchanged') AND document_version_id IS NOT NULL
           AND error_code IS NULL) OR (status IN ('failed','deferred')
           AND document_version_id IS NULL AND error_code IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS acquisition_document ON acquisition_checks(document_id, sequence DESC);
CREATE INDEX IF NOT EXISTS acquisition_document_observed ON acquisition_checks(document_id, checked_at DESC, sequence DESC);
CREATE TABLE IF NOT EXISTS extractions (
    extraction_id TEXT PRIMARY KEY,
    document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id),
    extractor_version TEXT NOT NULL,
    text_sha256 TEXT NOT NULL CHECK(length(text_sha256)=64),
    observed_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('partial','complete','failed')),
    coverage_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS extractions_document ON extractions(document_version_id);
CREATE TABLE IF NOT EXISTS clauses (
    clause_id TEXT PRIMARY KEY,
    extraction_id TEXT NOT NULL REFERENCES extractions(extraction_id),
    locator_json TEXT NOT NULL,
    text TEXT NOT NULL CHECK(length(text)>0),
    UNIQUE(extraction_id, locator_json)
);
CREATE TABLE IF NOT EXISTS rule_sets (
    rule_set_id TEXT PRIMARY KEY,
    contract_json TEXT NOT NULL,
    validator_version TEXT NOT NULL,
    benchmark_sha256 TEXT NOT NULL CHECK(length(benchmark_sha256)=64)
);
CREATE TABLE IF NOT EXISTS term_revisions (
    term_revision_id TEXT PRIMARY KEY,
    observation_id TEXT NOT NULL REFERENCES observations(observation_id),
    parameter_key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    unit TEXT,
    applicability_json TEXT NOT NULL,
    rule_set_id TEXT REFERENCES rule_sets(rule_set_id),
    observed_at TEXT NOT NULL,
    interpreter TEXT NOT NULL,
    context_sha256 TEXT NOT NULL CHECK(length(context_sha256)=64)
);
CREATE TABLE IF NOT EXISTS term_sources (
    term_revision_id TEXT NOT NULL REFERENCES term_revisions(term_revision_id),
    clause_id TEXT NOT NULL REFERENCES clauses(clause_id),
    PRIMARY KEY(term_revision_id, clause_id)
);
CREATE TABLE IF NOT EXISTS reviews (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id TEXT NOT NULL UNIQUE,
    term_revision_id TEXT NOT NULL REFERENCES term_revisions(term_revision_id),
    status TEXT NOT NULL CHECK(status IN ('validated','rejected')),
    reviewer TEXT NOT NULL,
    reviewer_kind TEXT NOT NULL CHECK(reviewer_kind IN ('human','deterministic')),
    reviewed_at TEXT NOT NULL,
    evidence_sha256 TEXT NOT NULL CHECK(length(evidence_sha256)=64),
    reason TEXT NOT NULL CHECK(length(reason)>0)
);
CREATE INDEX IF NOT EXISTS reviews_term ON reviews(term_revision_id, sequence DESC);
CREATE TABLE IF NOT EXISTS term_changes (
    term_change_id TEXT PRIMARY KEY,
    product_key TEXT NOT NULL,
    before_revision_id TEXT REFERENCES term_revisions(term_revision_id),
    after_revision_id TEXT REFERENCES term_revisions(term_revision_id),
    kind TEXT NOT NULL CHECK(kind IN ('added','changed','removed','extraction_corrected')),
    observed_at TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    CHECK(before_revision_id IS NOT NULL OR after_revision_id IS NOT NULL),
    CHECK(kind != 'removed' OR (before_revision_id IS NOT NULL AND after_revision_id IS NULL))
);
CREATE TABLE IF NOT EXISTS publications (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    publication_id TEXT NOT NULL UNIQUE,
    product_key TEXT NOT NULL,
    observation_id TEXT NOT NULL REFERENCES observations(observation_id),
    identity_sha256 TEXT NOT NULL CHECK(length(identity_sha256)=64),
    previous_identity_sha256 TEXT,
    published_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS publications_product ON publications(product_key, sequence DESC);
CREATE TABLE IF NOT EXISTS analysis_jobs (
    job_id TEXT PRIMARY KEY,
    extraction_id TEXT NOT NULL REFERENCES extractions(extraction_id),
    context_sha256 TEXT NOT NULL CHECK(length(context_sha256)=64),
    context_blob_sha256 TEXT NOT NULL CHECK(length(context_blob_sha256)=64),
    priority INTEGER NOT NULL CHECK(priority IN (0,1,2)),
    created_at TEXT NOT NULL,
    UNIQUE(extraction_id, context_sha256)
);
CREATE TABLE IF NOT EXISTS job_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    job_id TEXT NOT NULL REFERENCES analysis_jobs(job_id),
    status TEXT NOT NULL CHECK(status IN ('queued','running','staged','retry_wait','blocked','superseded')),
    observed_at TEXT NOT NULL,
    retry_after TEXT,
    error_code TEXT,
    result_sha256 TEXT,
    lease_id TEXT,
    lease_expires_at TEXT,
    CHECK(status != 'retry_wait' OR retry_after IS NOT NULL),
    CHECK(status != 'staged' OR result_sha256 IS NOT NULL),
    CHECK(status != 'running' OR (lease_id IS NOT NULL AND lease_expires_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS job_events_job ON job_events(job_id, sequence DESC);
CREATE TABLE IF NOT EXISTS job_priorities (
    event_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES analysis_jobs(job_id),
    priority INTEGER NOT NULL CHECK(priority IN (0,1,2)),
    observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS job_priorities_job ON job_priorities(job_id, priority);
CREATE TABLE IF NOT EXISTS acquisition_requests (
    request_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    ingest_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    priority INTEGER NOT NULL CHECK(priority IN (0,1,2)),
    UNIQUE(ingest_id,document_id)
);
CREATE TABLE IF NOT EXISTS acquisition_bindings (
    request_id TEXT NOT NULL REFERENCES acquisition_requests(request_id),
    observation_id TEXT NOT NULL REFERENCES observations(observation_id),
    PRIMARY KEY(request_id,observation_id)
);
CREATE TABLE IF NOT EXISTS acquisition_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    request_id TEXT NOT NULL REFERENCES acquisition_requests(request_id),
    status TEXT NOT NULL CHECK(status IN ('queued','running','complete','retry_wait','blocked')),
    observed_at TEXT NOT NULL,
    retry_after TEXT,
    lease_id TEXT,
    lease_expires_at TEXT,
    check_id TEXT REFERENCES acquisition_checks(check_id),
    error_code TEXT,
    CHECK(status!='running' OR (lease_id IS NOT NULL AND lease_expires_at IS NOT NULL)),
    CHECK(status!='complete' OR check_id IS NOT NULL),
    CHECK(status!='retry_wait' OR retry_after IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS acquisition_events_request ON acquisition_events(request_id,sequence DESC);
CREATE TABLE IF NOT EXISTS ingest_captures (
    ingest_id TEXT PRIMARY KEY,
    receipt_sha256 TEXT NOT NULL CHECK(length(receipt_sha256)=64),
    completed_at TEXT NOT NULL,
    products INTEGER NOT NULL CHECK(products > 0)
);
