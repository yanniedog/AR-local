-- DRAFT ONLY. Do not execute or add to EvidenceStore.schema.sql before freeze.
-- SQLite, foreign_keys=ON. Existing v1 tables/rows/schema bytes are untouched.
-- EvidenceStore installs UPDATE/DELETE denial triggers on EVERY new table.
-- Controller owns BEGIN IMMEDIATE, canonical hashes, timestamps and bounded JSON.

CREATE TABLE executable_registry_migrations (
    migration_id TEXT PRIMARY KEY CHECK(migration_id='001_scoped_eligibility_v2'),
    ddl_sha256 TEXT NOT NULL CHECK(length(ddl_sha256)=64),
    applied_at TEXT NOT NULL,
    legacy_preservation_receipt_sha256 TEXT NOT NULL CHECK(length(legacy_preservation_receipt_sha256)=64)
);
-- Insert the marker only after all DDL, immutable triggers and FK checks succeed,
-- in the same transaction. A present marker with another DDL digest fails closed.

CREATE TABLE executable_scopes_v2 (
    scope_id TEXT PRIMARY KEY CHECK(length(scope_id)=64),
    capability TEXT NOT NULL CHECK(capability='eligibility_only'),
    family TEXT NOT NULL CHECK(family IN ('Mortgage','Savings','TD')),
    product_key TEXT NOT NULL,
    cohort_key TEXT NOT NULL,
    tier_key TEXT NOT NULL,
    package_key TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    effective_to_exclusive TEXT NOT NULL CHECK(effective_from<effective_to_exclusive),
    coverage TEXT NOT NULL CHECK(coverage IN ('product','rate_variants')),
    scope_json TEXT NOT NULL CHECK(json_valid(scope_json)),
    UNIQUE(capability,scope_json),
    CHECK(json_extract(scope_json,'$.productKey') IS product_key),
    CHECK(json_extract(scope_json,'$.family') IS family),
    CHECK(json_extract(scope_json,'$.cohortKey') IS cohort_key),
    CHECK(json_extract(scope_json,'$.tierKey') IS tier_key),
    CHECK(json_extract(scope_json,'$.packageKey') IS package_key),
    CHECK(json_extract(scope_json,'$.effectiveFrom') IS effective_from),
    CHECK(json_extract(scope_json,'$.effectiveToExclusive') IS effective_to_exclusive),
    CHECK(json_extract(scope_json,'$.coverage') IS coverage)
);
CREATE INDEX executable_scopes_v2_product
    ON executable_scopes_v2(product_key,capability,scope_id);

CREATE TABLE executable_subjects_v2 (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id TEXT NOT NULL UNIQUE CHECK(length(subject_id)=64),
    scope_id TEXT NOT NULL REFERENCES executable_scopes_v2(scope_id),
    observation_id TEXT NOT NULL REFERENCES observations(observation_id),
    previous_subject_id TEXT,
    interpreter TEXT NOT NULL CHECK(length(interpreter) BETWEEN 1 AND 256),
    staged_at TEXT NOT NULL,
    subject_json TEXT NOT NULL CHECK(json_valid(subject_json)),
    UNIQUE(subject_id,scope_id),
    FOREIGN KEY(previous_subject_id,scope_id)
        REFERENCES executable_subjects_v2(subject_id,scope_id),
    CHECK(previous_subject_id IS NULL OR previous_subject_id<>subject_id),
    CHECK(json_extract(subject_json,'$.id') IS subject_id),
    CHECK(json_extract(subject_json,'$.scopeId') IS scope_id),
    CHECK(json_extract(subject_json,'$.source.observationId') IS observation_id)
);
CREATE INDEX executable_subjects_v2_slot
    ON executable_subjects_v2(scope_id,sequence DESC);
CREATE INDEX executable_subjects_v2_current
    ON executable_subjects_v2(observation_id,scope_id,sequence DESC);

CREATE TABLE executable_subject_terms_v2 (
    subject_id TEXT NOT NULL REFERENCES executable_subjects_v2(subject_id),
    term_revision_id TEXT NOT NULL REFERENCES term_revisions(term_revision_id),
    PRIMARY KEY(subject_id,term_revision_id)
);
CREATE TABLE executable_subject_documents_v2 (
    subject_id TEXT NOT NULL REFERENCES executable_subjects_v2(subject_id),
    document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id),
    PRIMARY KEY(subject_id,document_version_id)
);

CREATE TABLE executable_reviews_v2 (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id TEXT NOT NULL UNIQUE CHECK(length(review_id)=64),
    subject_id TEXT NOT NULL REFERENCES executable_subjects_v2(subject_id),
    previous_review_id TEXT,
    decision TEXT NOT NULL CHECK(decision IN ('approved','rejected','revoked')),
    reviewer TEXT NOT NULL CHECK(length(reviewer) BETWEEN 1 AND 256),
    reviewer_kind TEXT NOT NULL CHECK(reviewer_kind IN ('human','deterministic')),
    reviewed_at TEXT NOT NULL,
    evidence_sha256 TEXT NOT NULL CHECK(length(evidence_sha256)=64),
    source_snapshot_sha256 TEXT CHECK(source_snapshot_sha256 IS NULL OR length(source_snapshot_sha256)=64),
    benchmark_sha256 TEXT CHECK(benchmark_sha256 IS NULL OR length(benchmark_sha256)=64),
    reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 4000),
    UNIQUE(review_id,subject_id),
    FOREIGN KEY(previous_review_id,subject_id)
        REFERENCES executable_reviews_v2(review_id,subject_id),
    CHECK(previous_review_id IS NULL OR previous_review_id<>review_id),
    CHECK(decision<>'approved' OR (benchmark_sha256 IS NOT NULL AND source_snapshot_sha256 IS NOT NULL))
);
CREATE INDEX executable_reviews_v2_subject
    ON executable_reviews_v2(subject_id,sequence DESC);

CREATE TABLE executable_publications_v2 (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    publication_id TEXT NOT NULL UNIQUE CHECK(length(publication_id)=64),
    product_key TEXT NOT NULL,
    observation_id TEXT NOT NULL REFERENCES observations(observation_id),
    identity_sha256 TEXT NOT NULL CHECK(length(identity_sha256)=64),
    previous_publication_id TEXT,
    published_at TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    UNIQUE(publication_id,product_key),
    FOREIGN KEY(previous_publication_id,product_key)
        REFERENCES executable_publications_v2(publication_id,product_key),
    CHECK(json_extract(payload_json,'$.productKey') IS product_key),
    CHECK(json_extract(payload_json,'$.sourceObservationId') IS observation_id),
    CHECK(json_extract(payload_json,'$.identitySha256') IS identity_sha256)
);
CREATE INDEX executable_publications_v2_product
    ON executable_publications_v2(product_key,sequence DESC);

-- Guard the expected predecessor at INSERT as well as in the controller.
-- Idempotent replays return the verified existing row BEFORE an INSERT attempt.
CREATE TRIGGER executable_subjects_v2_cas BEFORE INSERT ON executable_subjects_v2
WHEN NEW.previous_subject_id IS NOT
    (SELECT subject_id FROM executable_subjects_v2 WHERE scope_id=NEW.scope_id ORDER BY sequence DESC LIMIT 1)
BEGIN SELECT RAISE(ABORT,'stale executable subject predecessor'); END;
CREATE TRIGGER executable_reviews_v2_cas BEFORE INSERT ON executable_reviews_v2
WHEN NEW.previous_review_id IS NOT
    (SELECT review_id FROM executable_reviews_v2 WHERE subject_id=NEW.subject_id ORDER BY sequence DESC LIMIT 1)
BEGIN SELECT RAISE(ABORT,'stale executable review predecessor'); END;
CREATE TRIGGER executable_publications_v2_cas BEFORE INSERT ON executable_publications_v2
WHEN NEW.previous_publication_id IS NOT
    (SELECT publication_id FROM executable_publications_v2 WHERE product_key=NEW.product_key ORDER BY sequence DESC LIMIT 1)
BEGIN SELECT RAISE(ABORT,'stale executable publication predecessor'); END;

-- One identity namespace; no copying, converting or approving legacy rows.
CREATE TRIGGER executable_subjects_v2_no_legacy_collision BEFORE INSERT ON executable_subjects_v2
WHEN EXISTS(SELECT 1 FROM executable_templates WHERE template_id=NEW.subject_id)
BEGIN SELECT RAISE(ABORT,'executable identity exists in legacy storage'); END;
CREATE TRIGGER executable_templates_no_v2_collision BEFORE INSERT ON executable_templates
WHEN EXISTS(SELECT 1 FROM executable_subjects_v2 WHERE subject_id=NEW.template_id)
BEGIN SELECT RAISE(ABORT,'executable identity exists in v2 storage'); END;
CREATE TRIGGER executable_reviews_v2_no_legacy_collision BEFORE INSERT ON executable_reviews_v2
WHEN EXISTS(SELECT 1 FROM executable_reviews WHERE review_id=NEW.review_id)
BEGIN SELECT RAISE(ABORT,'executable review identity exists in legacy storage'); END;
CREATE TRIGGER executable_reviews_no_v2_collision BEFORE INSERT ON executable_reviews
WHEN EXISTS(SELECT 1 FROM executable_reviews_v2 WHERE review_id=NEW.review_id)
BEGIN SELECT RAISE(ABORT,'executable review identity exists in v2 storage'); END;

-- Read-only dispatch views. Version selects the exact validator/storage adapter.
-- NULL scope_id for v1 is explicit; never synthesize a v2 scope or rate index.
CREATE VIEW executable_registry_subjects AS
SELECT template_id AS subject_id,1 AS wire_version,'fixed_td_calculation' AS capability,
       product_key,observation_id,NULL AS scope_id,template_json AS subject_json
FROM executable_templates
UNION ALL
SELECT s.subject_id,2,'eligibility_only',k.product_key,s.observation_id,s.scope_id,s.subject_json
FROM executable_subjects_v2 s JOIN executable_scopes_v2 k USING(scope_id);
CREATE VIEW executable_registry_reviews AS
SELECT review_id,template_id AS subject_id,1 AS wire_version,decision,reviewer,reviewer_kind,
       reviewed_at,evidence_sha256,benchmark_sha256
FROM executable_reviews
UNION ALL
SELECT review_id,subject_id,2,decision,reviewer,reviewer_kind,reviewed_at,evidence_sha256,benchmark_sha256
FROM executable_reviews_v2;

-- Representative current-edition lookup (controller binds exact product/observation):
-- SELECT s.* FROM executable_subjects_v2 s JOIN executable_scopes_v2 k USING(scope_id)
-- WHERE k.product_key=:product AND s.observation_id=:current_observation
--   AND s.sequence=(SELECT MAX(x.sequence) FROM executable_subjects_v2 x WHERE x.scope_id=s.scope_id)
-- ORDER BY s.scope_id LIMIT 33;
-- 33 means reject >32, never truncate to a publishable partial result.
-- Per-product current observation is checked before AND during publication.
