-- Additive activity storage. Controller owns BEGIN IMMEDIATE and marker insertion.
-- Baselines001/002 are immutable; no existing evidence table is rebuilt or modified.
-- foreign_keys must already be ON before BEGIN. Run statements individually, never executescript.
CREATE TABLE executable_registry_migrations_v4 (
 migration_id TEXT PRIMARY KEY CHECK(migration_id='003_savings_activity_v4'),
 predecessor_migration_id TEXT NOT NULL REFERENCES executable_registry_migrations_v3(migration_id) CHECK(predecessor_migration_id='002_monetary_v3'),
 predecessor_ddl_sha256 TEXT NOT NULL CHECK(length(predecessor_ddl_sha256)=64),
 ddl_sha256 TEXT NOT NULL CHECK(length(ddl_sha256)=64),
 preservation_receipt_sha256 TEXT NOT NULL CHECK(length(preservation_receipt_sha256)=64),
 schema_receipt_sha256 TEXT NOT NULL CHECK(length(schema_receipt_sha256)=64),
 applied_at TEXT NOT NULL
);
-- 001's marker CHECK admits only001. This is migration metadata, not another registry.
-- Insert002_monetary_wire3 only after checking001 marker/hash and full transactional verification.

CREATE TABLE executable_scopes_v4 (
 scope_id TEXT PRIMARY KEY CHECK(length(scope_id)=64),
 capability TEXT NOT NULL CHECK(capability IN ('savings_activity_calculation')),
 product_key TEXT NOT NULL,
 scope_json TEXT NOT NULL CHECK(json_valid(scope_json)),
 UNIQUE(scope_id,capability), UNIQUE(capability,scope_json),
 CHECK(json_extract(scope_json,'$.productKey') IS product_key)
);
CREATE INDEX executable_scopes_v4_product ON executable_scopes_v4(product_key,capability,scope_id);
CREATE TABLE executable_subjects_v4 (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT,
 subject_id TEXT NOT NULL UNIQUE CHECK(length(subject_id)=64),
 wire_version INTEGER NOT NULL CHECK(wire_version=4),
 capability TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind='aud_savings_activity_period_v1'),
 adapter_version TEXT NOT NULL CHECK(adapter_version='aud-savings-activity-v1'), evaluator_version TEXT NOT NULL CHECK(evaluator_version='product-terms-engine-v9'),
 scope_id TEXT NOT NULL,
 observation_id TEXT NOT NULL REFERENCES observations(observation_id),
 previous_subject_id TEXT,
 interpreter TEXT NOT NULL CHECK(length(interpreter) BETWEEN 1 AND 256), staged_at TEXT NOT NULL,
 authority_graph_sha256 TEXT NOT NULL CHECK(length(authority_graph_sha256)=64),
 subject_json TEXT NOT NULL CHECK(json_valid(subject_json)),
 UNIQUE(subject_id,scope_id),
 FOREIGN KEY(scope_id,capability) REFERENCES executable_scopes_v4(scope_id,capability),
 FOREIGN KEY(previous_subject_id,scope_id) REFERENCES executable_subjects_v4(subject_id,scope_id),
 CHECK(previous_subject_id IS NULL OR previous_subject_id<>subject_id),
 CHECK(json_extract(subject_json,'$.id') IS subject_id),
 CHECK(json_extract(subject_json,'$.schemaVersion') IS wire_version),
 CHECK(json_extract(subject_json,'$.capability') IS capability),
 CHECK(json_extract(subject_json,'$.kind') IS kind),
 CHECK(json_extract(subject_json,'$.policy.kind') IS kind),
 CHECK(json_extract(subject_json,'$.adapterVersion') IS adapter_version),
 CHECK(json_extract(subject_json,'$.evaluatorVersion') IS evaluator_version),
 CHECK(json_extract(subject_json,'$.scopeId') IS scope_id),
 CHECK(json_extract(subject_json,'$.authorityGraph.identitySha256') IS authority_graph_sha256)
);
CREATE INDEX executable_subjects_v4_slot ON executable_subjects_v4(scope_id,sequence DESC);
CREATE INDEX executable_subjects_v4_current ON executable_subjects_v4(observation_id,capability,scope_id,sequence DESC);
CREATE TRIGGER executable_subjects_v4_scope_source BEFORE INSERT ON executable_subjects_v4
WHEN NOT EXISTS(
 SELECT 1 FROM executable_scopes_v4 k JOIN observations o ON o.observation_id=NEW.observation_id
 WHERE k.scope_id=NEW.scope_id AND k.scope_json=json_extract(NEW.subject_json,'$.scope')
 AND k.product_key=o.product_key AND json_extract(NEW.subject_json,'$.routing.productKey') IS o.product_key
 AND json_extract(NEW.subject_json,'$.routing.sourceGenerationId') IS o.ingest_id)
BEGIN SELECT RAISE(ABORT,'monetary scope/current routing observation differs'); END;
-- Canonical JSON objects must be encoded without whitespace, matching json_extract object output.
CREATE TABLE executable_subject_terms_v4 (
 subject_id TEXT NOT NULL REFERENCES executable_subjects_v4(subject_id),
 term_revision_id TEXT NOT NULL REFERENCES term_revisions(term_revision_id),
 PRIMARY KEY(subject_id,term_revision_id)
);
CREATE TABLE executable_subject_documents_v4 (
 subject_id TEXT NOT NULL REFERENCES executable_subjects_v4(subject_id),
 document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id),
 PRIMARY KEY(subject_id,document_version_id)
);

CREATE TABLE executable_authorities_v4 (
 authority_id TEXT PRIMARY KEY CHECK(length(authority_id)=64),
 kind TEXT NOT NULL CHECK(kind IN ('retained_observation','dated_official_clause')),
 authority_json TEXT NOT NULL CHECK(json_valid(authority_json)),
 CHECK(json_extract(authority_json,'$.id') IS authority_id),
 CHECK(json_extract(authority_json,'$.kind') IS kind)
);
CREATE TABLE executable_subject_authorities_v4 (
 subject_id TEXT NOT NULL REFERENCES executable_subjects_v4(subject_id),
 authority_id TEXT NOT NULL REFERENCES executable_authorities_v4(authority_id),
 PRIMARY KEY(subject_id,authority_id)
);
CREATE INDEX executable_subject_authorities_v4_reverse ON executable_subject_authorities_v4(authority_id,subject_id);
CREATE TABLE executable_subject_observations_v4 (
 subject_id TEXT NOT NULL REFERENCES executable_subjects_v4(subject_id),
 observation_id TEXT NOT NULL REFERENCES observations(observation_id),
 PRIMARY KEY(subject_id,observation_id)
);
CREATE INDEX executable_subject_observations_v4_reverse ON executable_subject_observations_v4(observation_id,subject_id);
CREATE TABLE executable_subject_members_v4 (
 subject_id TEXT NOT NULL REFERENCES executable_subjects_v4(subject_id),
 member_sha256 TEXT NOT NULL CHECK(length(member_sha256)=64),
 member_kind TEXT NOT NULL CHECK(member_kind IN ('source_document','observation_manifest','core','details','raw_source','coverage_proof')),
 encoding TEXT NOT NULL CHECK(encoding IN ('identity','gzip')),
 bytes INTEGER NOT NULL CHECK(bytes BETWEEN 1 AND 2097152),
 decoded_bytes INTEGER NOT NULL CHECK(decoded_bytes BETWEEN 1 AND 2097152),
 PRIMARY KEY(subject_id,member_sha256)
);
CREATE INDEX executable_subject_members_v4_reverse ON executable_subject_members_v4(member_sha256,subject_id);
CREATE INDEX executable_subject_terms_v4_reverse ON executable_subject_terms_v4(term_revision_id,subject_id);
CREATE INDEX executable_subject_documents_v4_reverse ON executable_subject_documents_v4(document_version_id,subject_id);
CREATE TRIGGER immutable_executable_authorities_v4_UPDATE BEFORE UPDATE ON executable_authorities_v4
BEGIN SELECT RAISE(ABORT,'terms evidence is append-only'); END;
CREATE TRIGGER immutable_executable_authorities_v4_DELETE BEFORE DELETE ON executable_authorities_v4
BEGIN SELECT RAISE(ABORT,'terms evidence is append-only'); END;
CREATE TRIGGER immutable_executable_subject_authorities_v4_UPDATE BEFORE UPDATE ON executable_subject_authorities_v4
BEGIN SELECT RAISE(ABORT,'terms evidence is append-only'); END;
CREATE TRIGGER immutable_executable_subject_authorities_v4_DELETE BEFORE DELETE ON executable_subject_authorities_v4
BEGIN SELECT RAISE(ABORT,'terms evidence is append-only'); END;
CREATE TRIGGER immutable_executable_subject_observations_v4_UPDATE BEFORE UPDATE ON executable_subject_observations_v4
BEGIN SELECT RAISE(ABORT,'terms evidence is append-only'); END;
CREATE TRIGGER immutable_executable_subject_observations_v4_DELETE BEFORE DELETE ON executable_subject_observations_v4
BEGIN SELECT RAISE(ABORT,'terms evidence is append-only'); END;
CREATE TRIGGER immutable_executable_subject_members_v4_UPDATE BEFORE UPDATE ON executable_subject_members_v4
BEGIN SELECT RAISE(ABORT,'terms evidence is append-only'); END;
CREATE TRIGGER immutable_executable_subject_members_v4_DELETE BEFORE DELETE ON executable_subject_members_v4
BEGIN SELECT RAISE(ABORT,'terms evidence is append-only'); END;

-- Exact authority graph/member descriptors remain in hashed subject_json.
-- Blob availability/hash/coverage are admission checks; no invented FK to a nonexistent blob table.
CREATE TABLE executable_reviews_v4 (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT,
 review_id TEXT NOT NULL UNIQUE CHECK(length(review_id)=64),
 subject_id TEXT NOT NULL REFERENCES executable_subjects_v4(subject_id), previous_review_id TEXT,
 decision TEXT NOT NULL CHECK(decision IN ('approved','rejected','revoked')),
 reviewer TEXT NOT NULL CHECK(length(reviewer) BETWEEN 1 AND 256),
 reviewer_kind TEXT NOT NULL CHECK(reviewer_kind IN ('human','deterministic')),
 reviewed_at TEXT NOT NULL, evidence_sha256 TEXT NOT NULL CHECK(length(evidence_sha256)=64),
 source_snapshot_sha256 TEXT CHECK(source_snapshot_sha256 IS NULL OR length(source_snapshot_sha256)=64),
 authority_graph_sha256 TEXT CHECK(authority_graph_sha256 IS NULL OR length(authority_graph_sha256)=64),
 benchmark_sha256 TEXT CHECK(benchmark_sha256 IS NULL OR length(benchmark_sha256)=64),
 reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 4000),
 UNIQUE(review_id,subject_id),
 FOREIGN KEY(previous_review_id,subject_id) REFERENCES executable_reviews_v4(review_id,subject_id),
 CHECK(previous_review_id IS NULL OR previous_review_id<>review_id),
 CHECK(decision<>'approved' OR (source_snapshot_sha256 IS NOT NULL AND authority_graph_sha256 IS NOT NULL AND benchmark_sha256 IS NOT NULL))
);
CREATE INDEX executable_reviews_v4_subject ON executable_reviews_v4(subject_id,sequence DESC);
CREATE TABLE executable_publications_v4 (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT,
 publication_id TEXT NOT NULL UNIQUE CHECK(length(publication_id)=64),
 product_key TEXT NOT NULL,
 capability TEXT NOT NULL CHECK(capability IN ('savings_activity_calculation')),
 observation_id TEXT NOT NULL REFERENCES observations(observation_id),
 previous_publication_id TEXT,
 state TEXT NOT NULL CHECK(state IN ('active','removed')),
 identity_sha256 TEXT NOT NULL CHECK(length(identity_sha256)=64),
 published_at TEXT NOT NULL,
 payload_json TEXT CHECK(payload_json IS NULL OR json_valid(payload_json)),
 UNIQUE(publication_id,product_key,capability),
 FOREIGN KEY(previous_publication_id,product_key,capability)
  REFERENCES executable_publications_v4(publication_id,product_key,capability),
 CHECK(previous_publication_id IS NULL OR previous_publication_id<>publication_id),
 CHECK((state='removed' AND payload_json IS NULL) OR (state='active' AND payload_json IS NOT NULL)),
 CHECK(state='removed' OR json_extract(payload_json,'$.schemaVersion') IS 4),
 CHECK(state='removed' OR json_extract(payload_json,'$.capability') IS capability),
 CHECK(state='removed' OR json_extract(payload_json,'$.productKey') IS product_key),
 CHECK(state='removed' OR json_extract(payload_json,'$.identitySha256') IS identity_sha256)
);
CREATE INDEX executable_publications_v4_product ON executable_publications_v4(product_key,capability,sequence DESC);
CREATE TRIGGER executable_publications_v4_source BEFORE INSERT ON executable_publications_v4
WHEN NOT EXISTS(SELECT 1 FROM observations o WHERE o.observation_id=NEW.observation_id AND o.product_key=NEW.product_key
 AND (NEW.state='removed' OR (json_extract(NEW.payload_json,'$.routing.productKey') IS o.product_key
 AND json_extract(NEW.payload_json,'$.routing.sourceGenerationId') IS o.ingest_id)))
BEGIN SELECT RAISE(ABORT,'monetary publication routing observation differs'); END;

CREATE TRIGGER executable_subjects_v4_cas BEFORE INSERT ON executable_subjects_v4
WHEN NEW.previous_subject_id IS NOT (SELECT subject_id FROM executable_subjects_v4 WHERE scope_id=NEW.scope_id ORDER BY sequence DESC LIMIT 1)
BEGIN SELECT RAISE(ABORT,'stale monetary predecessor'); END;

CREATE TRIGGER executable_reviews_v4_cas BEFORE INSERT ON executable_reviews_v4
WHEN NEW.previous_review_id IS NOT (SELECT review_id FROM executable_reviews_v4 WHERE subject_id=NEW.subject_id ORDER BY sequence DESC LIMIT 1)
BEGIN SELECT RAISE(ABORT,'stale monetary predecessor'); END;

CREATE TRIGGER executable_publications_v4_cas BEFORE INSERT ON executable_publications_v4
WHEN NEW.previous_publication_id IS NOT (SELECT publication_id FROM executable_publications_v4 WHERE product_key=NEW.product_key AND capability=NEW.capability ORDER BY sequence DESC LIMIT 1)
BEGIN SELECT RAISE(ABORT,'stale monetary predecessor'); END;

CREATE TRIGGER executable_subjects_v4_no_executable_templates_collision BEFORE INSERT ON executable_subjects_v4
WHEN EXISTS(SELECT 1 FROM executable_templates WHERE template_id=NEW.subject_id)
BEGIN SELECT RAISE(ABORT,'cross-version executable subject identity collision'); END;

CREATE TRIGGER executable_templates_no_executable_subjects_v4_collision BEFORE INSERT ON executable_templates
WHEN EXISTS(SELECT 1 FROM executable_subjects_v4 WHERE subject_id=NEW.template_id)
BEGIN SELECT RAISE(ABORT,'cross-version executable subject identity collision'); END;

CREATE TRIGGER executable_subjects_v4_no_executable_subjects_v2_collision BEFORE INSERT ON executable_subjects_v4
WHEN EXISTS(SELECT 1 FROM executable_subjects_v2 WHERE subject_id=NEW.subject_id)
BEGIN SELECT RAISE(ABORT,'cross-version executable subject identity collision'); END;

CREATE TRIGGER executable_subjects_v2_no_executable_subjects_v4_collision BEFORE INSERT ON executable_subjects_v2
WHEN EXISTS(SELECT 1 FROM executable_subjects_v4 WHERE subject_id=NEW.subject_id)
BEGIN SELECT RAISE(ABORT,'cross-version executable subject identity collision'); END;

CREATE TRIGGER executable_reviews_v4_no_executable_reviews_collision BEFORE INSERT ON executable_reviews_v4
WHEN EXISTS(SELECT 1 FROM executable_reviews WHERE review_id=NEW.review_id)
BEGIN SELECT RAISE(ABORT,'cross-version executable review identity collision'); END;

CREATE TRIGGER executable_reviews_no_executable_reviews_v4_collision BEFORE INSERT ON executable_reviews
WHEN EXISTS(SELECT 1 FROM executable_reviews_v4 WHERE review_id=NEW.review_id)
BEGIN SELECT RAISE(ABORT,'cross-version executable review identity collision'); END;

CREATE TRIGGER executable_reviews_v4_no_executable_reviews_v2_collision BEFORE INSERT ON executable_reviews_v4
WHEN EXISTS(SELECT 1 FROM executable_reviews_v2 WHERE review_id=NEW.review_id)
BEGIN SELECT RAISE(ABORT,'cross-version executable review identity collision'); END;

CREATE TRIGGER executable_reviews_v2_no_executable_reviews_v4_collision BEFORE INSERT ON executable_reviews_v2
WHEN EXISTS(SELECT 1 FROM executable_reviews_v4 WHERE review_id=NEW.review_id)
BEGIN SELECT RAISE(ABORT,'cross-version executable review identity collision'); END;

CREATE TRIGGER executable_publications_v4_no_executable_publications_collision BEFORE INSERT ON executable_publications_v4
WHEN EXISTS(SELECT 1 FROM executable_publications WHERE publication_id=NEW.publication_id)
BEGIN SELECT RAISE(ABORT,'cross-version executable publication identity collision'); END;

CREATE TRIGGER executable_publications_no_executable_publications_v4_collision BEFORE INSERT ON executable_publications
WHEN EXISTS(SELECT 1 FROM executable_publications_v4 WHERE publication_id=NEW.publication_id)
BEGIN SELECT RAISE(ABORT,'cross-version executable publication identity collision'); END;

CREATE TRIGGER executable_publications_v4_no_executable_publications_v2_collision BEFORE INSERT ON executable_publications_v4
WHEN EXISTS(SELECT 1 FROM executable_publications_v2 WHERE publication_id=NEW.publication_id)
BEGIN SELECT RAISE(ABORT,'cross-version executable publication identity collision'); END;

CREATE TRIGGER executable_publications_v2_no_executable_publications_v4_collision BEFORE INSERT ON executable_publications_v2
WHEN EXISTS(SELECT 1 FROM executable_publications_v4 WHERE publication_id=NEW.publication_id)
BEGIN SELECT RAISE(ABORT,'cross-version executable publication identity collision'); END;

CREATE TRIGGER immutable_executable_registry_migrations_v4_UPDATE BEFORE UPDATE ON executable_registry_migrations_v4
BEGIN SELECT RAISE(ABORT,'terms evidence is append-only'); END;

CREATE TRIGGER immutable_executable_registry_migrations_v4_DELETE BEFORE DELETE ON executable_registry_migrations_v4
BEGIN SELECT RAISE(ABORT,'terms evidence is append-only'); END;

CREATE TRIGGER immutable_executable_scopes_v4_UPDATE BEFORE UPDATE ON executable_scopes_v4
BEGIN SELECT RAISE(ABORT,'terms evidence is append-only'); END;

CREATE TRIGGER immutable_executable_scopes_v4_DELETE BEFORE DELETE ON executable_scopes_v4
BEGIN SELECT RAISE(ABORT,'terms evidence is append-only'); END;

CREATE TRIGGER immutable_executable_subjects_v4_UPDATE BEFORE UPDATE ON executable_subjects_v4
BEGIN SELECT RAISE(ABORT,'terms evidence is append-only'); END;

CREATE TRIGGER immutable_executable_subjects_v4_DELETE BEFORE DELETE ON executable_subjects_v4
BEGIN SELECT RAISE(ABORT,'terms evidence is append-only'); END;

CREATE TRIGGER immutable_executable_subject_terms_v4_UPDATE BEFORE UPDATE ON executable_subject_terms_v4
BEGIN SELECT RAISE(ABORT,'terms evidence is append-only'); END;

CREATE TRIGGER immutable_executable_subject_terms_v4_DELETE BEFORE DELETE ON executable_subject_terms_v4
BEGIN SELECT RAISE(ABORT,'terms evidence is append-only'); END;

CREATE TRIGGER immutable_executable_subject_documents_v4_UPDATE BEFORE UPDATE ON executable_subject_documents_v4
BEGIN SELECT RAISE(ABORT,'terms evidence is append-only'); END;

CREATE TRIGGER immutable_executable_subject_documents_v4_DELETE BEFORE DELETE ON executable_subject_documents_v4
BEGIN SELECT RAISE(ABORT,'terms evidence is append-only'); END;

CREATE TRIGGER immutable_executable_reviews_v4_UPDATE BEFORE UPDATE ON executable_reviews_v4
BEGIN SELECT RAISE(ABORT,'terms evidence is append-only'); END;

CREATE TRIGGER immutable_executable_reviews_v4_DELETE BEFORE DELETE ON executable_reviews_v4
BEGIN SELECT RAISE(ABORT,'terms evidence is append-only'); END;

CREATE TRIGGER immutable_executable_publications_v4_UPDATE BEFORE UPDATE ON executable_publications_v4
BEGIN SELECT RAISE(ABORT,'terms evidence is append-only'); END;

CREATE TRIGGER immutable_executable_publications_v4_DELETE BEFORE DELETE ON executable_publications_v4
BEGIN SELECT RAISE(ABORT,'terms evidence is append-only'); END;


CREATE TRIGGER executable_subjects_v4_no_v3_collision BEFORE INSERT ON executable_subjects_v4
WHEN EXISTS(SELECT 1 FROM executable_subjects_v3 WHERE subject_id=NEW.subject_id)
BEGIN SELECT RAISE(ABORT,'cross-version executable subject identity collision'); END;
CREATE TRIGGER executable_subjects_v3_no_v4_collision BEFORE INSERT ON executable_subjects_v3
WHEN EXISTS(SELECT 1 FROM executable_subjects_v4 WHERE subject_id=NEW.subject_id)
BEGIN SELECT RAISE(ABORT,'cross-version executable subject identity collision'); END;
-- Atomic view upgrade: original column order remains; kind is appended.
DROP VIEW executable_registry_reviews;
DROP VIEW executable_registry_subjects;
CREATE VIEW executable_registry_subjects AS
 SELECT template_id AS subject_id,1 AS wire_version,'fixed_td_calculation' AS capability,
 product_key,observation_id,NULL AS scope_id,template_json AS subject_json,json_extract(template_json,'$.kind') AS kind
 FROM executable_templates
 UNION ALL
 SELECT s.subject_id,2,'eligibility_only',k.product_key,s.observation_id,s.scope_id,s.subject_json,json_extract(s.subject_json,'$.kind')
 FROM executable_subjects_v2 s JOIN executable_scopes_v2 k USING(scope_id)
 UNION ALL
 SELECT s.subject_id,s.wire_version,s.capability,k.product_key,s.observation_id,s.scope_id,s.subject_json,s.kind
 FROM executable_subjects_v3 s JOIN executable_scopes_v3 k USING(scope_id)
 UNION ALL
 SELECT s.subject_id,s.wire_version,s.capability,k.product_key,s.observation_id,s.scope_id,s.subject_json,s.kind
 FROM executable_subjects_v4 s JOIN executable_scopes_v4 k USING(scope_id);
CREATE VIEW executable_registry_reviews AS
 SELECT r.review_id,r.template_id AS subject_id,1 AS wire_version,r.decision,r.reviewer,r.reviewer_kind,
 r.reviewed_at,r.evidence_sha256,r.benchmark_sha256,'fixed_td_calculation' AS capability,json_extract(t.template_json,'$.kind') AS kind
 FROM executable_reviews r JOIN executable_templates t ON t.template_id=r.template_id
 UNION ALL
 SELECT r.review_id,r.subject_id,2,r.decision,r.reviewer,r.reviewer_kind,r.reviewed_at,r.evidence_sha256,r.benchmark_sha256,
 'eligibility_only',json_extract(s.subject_json,'$.kind') FROM executable_reviews_v2 r JOIN executable_subjects_v2 s USING(subject_id)
 UNION ALL
 SELECT r.review_id,r.subject_id,s.wire_version,r.decision,r.reviewer,r.reviewer_kind,r.reviewed_at,r.evidence_sha256,r.benchmark_sha256,
 s.capability,s.kind FROM executable_reviews_v3 r JOIN executable_subjects_v3 s USING(subject_id)
 UNION ALL
 SELECT r.review_id,r.subject_id,s.wire_version,r.decision,r.reviewer,r.reviewer_kind,r.reviewed_at,r.evidence_sha256,r.benchmark_sha256,s.capability,s.kind
 FROM executable_reviews_v4 r JOIN executable_subjects_v4 s USING(subject_id);
-- Internal removed publication has NULL public payload; its typed tombstone identity
-- is computed by controller. Packager omits removed products and empty routes.
-- It never emits an empty public asset or falls back to an older approval.
-- Controller inserts002 marker after bounded before/after raw-row and schema verification.
