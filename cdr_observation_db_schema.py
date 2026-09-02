"""SQLite v10 schema and validation constants for canonical observations."""

from __future__ import annotations

import re

from cdr_contracts import PROVIDER_UID_RE

SCHEMA_VERSION = 10
APPLICATION_ID = 1_095_912_515  # ASCII "ARLC"
FAILURE_STAGES = (
    "after_schema", "after_accounting", "after_projections", "after_commit",
    "after_verify", "before_install", "after_install",
)
DATASETS = frozenset({"Mortgage", "Savings", "TD"})
SECTIONS = frozenset(
    {
        "constraints", "details", "eligibility", "features", "fees", "mortgage",
        "products", "rates", "register", "savings", "term_deposit",
    }
)
STATES = frozenset({"complete", "partial", "empty", "failed", "not_attempted"})
PUBLISHABLE = frozenset({"published_full", "published_core_only"})
DISPOSITIONS = PUBLISHABLE | {"omitted_valid", "quarantined_invalid"}
SCOPES = frozenset({"product", "provider", "register", "run"})
ISSUE_CODES = frozenset(
    {
        "detail_fetch_failed",
        "detail_array_invalid",
        "detail_invalid_json",
        "cdr_error",
        "identity_mismatch",
        "duplicate_conflict",
        "rate_invalid",
        "classification_unresolved",
        "no_current_rate",
        "product_closed",
        "unsupported_category",
        "field_omitted_invalid",
        "products_index_failed",
        "pagination_incomplete",
        "holder_worker_crash",
        "provider_population_unknown",
        "register_failed",
        "failure_record_corrupt",
        "failure_unattributed",
        "accounting_unreconciled",
    }
)
ITEM_GROUPS = frozenset({"fees", "features", "eligibility", "constraints"})
FACT_KINDS = frozenset(
    {
        "fee",
        "rate",
        "tier",
        "bundle",
        "attribute",
        "feature",
        "eligibility",
        "constraint",
        "condition",
    }
)
VALUE_TYPES = frozenset({"boolean", "money", "rate", "number", "duration", "range", "enum", "text"})
PROJECTION_FIELDS = frozenset({"products", "rates", "items", "product_facts", "product_changes"})
PROJECTION_KEYS = {
    "products": {"product_uid", "provider_uid", "dataset", "cdr_product_id", "legacy_product_key", "document"},
    "rates": {"rate_uid", "product_uid", "rate_index", "rate", "comparison_rate", "document"},
    "items": {"product_uid", "item_group", "item_index", "document"},
    "product_facts": {"product_uid", "fact_id", "kind", "canonical_key", "value_type", "value_boolean", "value_number", "value_text", "min_value", "max_value", "document"},
    "product_changes": {"event_id", "provider_uid", "product_uid", "event_type", "canonical_key", "document"},
}
ACCOUNTING_KEYS = {"schema_version", "observation_date", "accounting_id", "raw_attempt_journal_digest", "providers", "products", "issues", "summary"}
PROVIDER_KEYS = {
    "provider_uid",
    "brand_name",
    "datasets",
    "affected_sections",
    "state",
    "attempted",
    "population_known",
    "discovered_count",
    "published_full_count",
    "published_core_only_count",
    "omitted_valid_count",
    "quarantined_invalid_count",
    "issue_count",
    "issue_ids",
}
PRODUCT_KEYS = {
    "product_uid",
    "provider_uid",
    "cdr_product_id",
    "dataset",
    "display_name",
    "legacy_product_key",
    "disposition",
    "reason_codes",
    "evidence_ids",
    "core_valid",
    "details_complete",
}
ISSUE_KEYS = {
    "issue_id",
    "scope",
    "provider_uid",
    "product_uid",
    "affected_sections",
    "phase",
    "code",
    "http_status",
    "occurrence_count",
    "first_seen_at",
    "last_seen_at",
    "evidence_digest",
    "disposition",
    "public_safe",
}
PROVIDER_UID = PROVIDER_UID_RE
PRODUCT_UID = re.compile(r"^[0-9a-f]{64}$")
RATE_UID = re.compile(r"^[0-9a-f]{64}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

SCHEMA_SQL = r"""
CREATE TABLE schema_meta(key TEXT PRIMARY KEY NOT NULL,value TEXT NOT NULL) STRICT,WITHOUT ROWID;
CREATE TABLE runs(
 observation_date TEXT PRIMARY KEY NOT NULL,
 accounting_id TEXT NOT NULL UNIQUE CHECK(length(trim(accounting_id))>0),
 raw_attempt_journal_digest TEXT NOT NULL CHECK(length(raw_attempt_journal_digest)=64 AND raw_attempt_journal_digest NOT GLOB '*[^0-9a-f]*'),
 generated_at TEXT NOT NULL CHECK(length(trim(generated_at))>0),
 sidecar_bytes BLOB NOT NULL CHECK(length(sidecar_bytes)>2),
 projection_counts_json TEXT NOT NULL CHECK(length(projection_counts_json)>1)
) STRICT,WITHOUT ROWID;
CREATE TABLE bank_provider_observations(
 accounting_id TEXT NOT NULL,provider_uid TEXT NOT NULL CHECK(length(trim(provider_uid))>0),brand_name TEXT NOT NULL CHECK(length(trim(brand_name))>0),
 datasets_json TEXT NOT NULL CHECK(length(datasets_json)>=2),affected_sections_json TEXT NOT NULL CHECK(length(affected_sections_json)>=2),
 state TEXT NOT NULL CHECK(state IN ('complete','partial','empty','failed','not_attempted')),
 attempted INTEGER NOT NULL CHECK(attempted IN(0,1)),population_known INTEGER NOT NULL CHECK(population_known IN(0,1)),
 discovered_count INTEGER NOT NULL CHECK(discovered_count>=0),published_full_count INTEGER NOT NULL CHECK(published_full_count>=0),
 published_core_only_count INTEGER NOT NULL CHECK(published_core_only_count>=0),omitted_valid_count INTEGER NOT NULL CHECK(omitted_valid_count>=0),
 quarantined_invalid_count INTEGER NOT NULL CHECK(quarantined_invalid_count>=0),issue_count INTEGER NOT NULL CHECK(issue_count>=0),issue_ids_json TEXT NOT NULL,
 PRIMARY KEY(accounting_id,provider_uid),FOREIGN KEY(accounting_id) REFERENCES runs(accounting_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
 CHECK(discovered_count=published_full_count+published_core_only_count+omitted_valid_count+quarantined_invalid_count),
 CHECK((state='not_attempted' AND attempted=0) OR(state<>'not_attempted' AND attempted=1)),CHECK(state<>'empty' OR(population_known=1 AND discovered_count=0)),
 CHECK((state IN('complete','empty') AND population_known=1)OR state='partial' OR(state IN('failed','not_attempted') AND population_known=0))
) STRICT,WITHOUT ROWID;
CREATE TABLE bank_product_dispositions(
 accounting_id TEXT NOT NULL,product_uid TEXT NOT NULL CHECK(length(trim(product_uid))>0),provider_uid TEXT NOT NULL CHECK(length(trim(provider_uid))>0),cdr_product_id TEXT NOT NULL CHECK(length(trim(cdr_product_id))>0),
 dataset TEXT NOT NULL CHECK(dataset IN('Mortgage','Savings','TD')),display_name TEXT CHECK(display_name IS NULL OR length(trim(display_name))>0),legacy_product_key TEXT CHECK(legacy_product_key IS NULL OR length(trim(legacy_product_key))>0),
 disposition TEXT NOT NULL CHECK(disposition IN('published_full','published_core_only','omitted_valid','quarantined_invalid')),
 reason_codes_json TEXT NOT NULL CHECK(length(reason_codes_json)>=2),evidence_ids_json TEXT NOT NULL CHECK(length(evidence_ids_json)>2),core_valid INTEGER NOT NULL CHECK(core_valid IN(0,1)),details_complete INTEGER NOT NULL CHECK(details_complete IN(0,1)),
 PRIMARY KEY(accounting_id,product_uid),UNIQUE(accounting_id,provider_uid,dataset,cdr_product_id),UNIQUE(accounting_id,product_uid,provider_uid),
 UNIQUE(accounting_id,product_uid,provider_uid,dataset,cdr_product_id),
 FOREIGN KEY(accounting_id,provider_uid) REFERENCES bank_provider_observations(accounting_id,provider_uid) ON UPDATE RESTRICT ON DELETE RESTRICT,
 CHECK(disposition NOT IN('published_full','published_core_only') OR core_valid=1),CHECK(disposition<>'published_full' OR details_complete=1),CHECK(disposition<>'published_core_only' OR details_complete=0)
) STRICT,WITHOUT ROWID;
CREATE UNIQUE INDEX uq_bank_product_dispositions_legacy_key ON bank_product_dispositions(accounting_id,legacy_product_key) WHERE legacy_product_key IS NOT NULL;
CREATE TABLE bank_observation_issues(
 accounting_id TEXT NOT NULL,issue_id TEXT NOT NULL CHECK(length(trim(issue_id))>0),scope TEXT NOT NULL CHECK(scope IN('product','provider','register','run')),provider_uid TEXT,product_uid TEXT,
 affected_sections_json TEXT NOT NULL CHECK(length(affected_sections_json)>=2),phase TEXT NOT NULL CHECK(length(trim(phase))>0),code TEXT NOT NULL CHECK(code IN('detail_fetch_failed','detail_array_invalid','detail_invalid_json','cdr_error','identity_mismatch','duplicate_conflict','rate_invalid','classification_unresolved','no_current_rate','product_closed','unsupported_category','field_omitted_invalid','products_index_failed','pagination_incomplete','holder_worker_crash','provider_population_unknown','register_failed','failure_record_corrupt','failure_unattributed','accounting_unreconciled')),
 http_status INTEGER CHECK(http_status IS NULL OR http_status BETWEEN 100 AND 599),occurrence_count INTEGER NOT NULL CHECK(occurrence_count>0),
 first_seen_at TEXT NOT NULL,last_seen_at TEXT NOT NULL,evidence_digest TEXT NOT NULL CHECK(length(evidence_digest)=64 AND evidence_digest NOT GLOB '*[^0-9a-f]*'),
 disposition TEXT CHECK(disposition IS NULL OR disposition IN('published_full','published_core_only','omitted_valid','quarantined_invalid')),public_safe INTEGER NOT NULL CHECK(public_safe IN(0,1)),
 PRIMARY KEY(accounting_id,issue_id),FOREIGN KEY(accounting_id) REFERENCES runs(accounting_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
 FOREIGN KEY(accounting_id,provider_uid) REFERENCES bank_provider_observations(accounting_id,provider_uid) ON UPDATE RESTRICT ON DELETE RESTRICT,
 FOREIGN KEY(accounting_id,product_uid,provider_uid) REFERENCES bank_product_dispositions(accounting_id,product_uid,provider_uid) ON UPDATE RESTRICT ON DELETE RESTRICT,
 CHECK(product_uid IS NULL OR provider_uid IS NOT NULL),CHECK((scope='product' AND provider_uid IS NOT NULL AND product_uid IS NOT NULL)OR(scope='provider' AND provider_uid IS NOT NULL AND product_uid IS NULL)OR(scope='register' AND product_uid IS NULL)OR(scope='run' AND provider_uid IS NULL AND product_uid IS NULL))
) STRICT,WITHOUT ROWID;
CREATE TABLE bank_products(
 accounting_id TEXT NOT NULL,product_uid TEXT NOT NULL CHECK(length(trim(product_uid))>0),provider_uid TEXT NOT NULL CHECK(length(trim(provider_uid))>0),dataset TEXT NOT NULL CHECK(dataset IN('Mortgage','Savings','TD')),
 cdr_product_id TEXT NOT NULL CHECK(length(trim(cdr_product_id))>0),legacy_product_key TEXT,document_json TEXT NOT NULL CHECK(length(document_json)>1),PRIMARY KEY(accounting_id,product_uid),
 FOREIGN KEY(accounting_id,product_uid,provider_uid,dataset,cdr_product_id) REFERENCES bank_product_dispositions(accounting_id,product_uid,provider_uid,dataset,cdr_product_id) ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT,WITHOUT ROWID;
CREATE TRIGGER bank_products_publishable_insert BEFORE INSERT ON bank_products WHEN NOT EXISTS(SELECT 1 FROM bank_product_dispositions d WHERE d.accounting_id=NEW.accounting_id AND d.product_uid=NEW.product_uid AND d.disposition IN('published_full','published_core_only')) BEGIN SELECT RAISE(ABORT,'consumer product is not publishable');END;
CREATE TRIGGER bank_products_publishable_update BEFORE UPDATE OF accounting_id,product_uid ON bank_products WHEN NOT EXISTS(SELECT 1 FROM bank_product_dispositions d WHERE d.accounting_id=NEW.accounting_id AND d.product_uid=NEW.product_uid AND d.disposition IN('published_full','published_core_only')) BEGIN SELECT RAISE(ABORT,'consumer product is not publishable');END;
CREATE TRIGGER bank_disposition_publishable_update BEFORE UPDATE OF disposition ON bank_product_dispositions WHEN NEW.disposition NOT IN('published_full','published_core_only') AND EXISTS(SELECT 1 FROM bank_products p WHERE p.accounting_id=NEW.accounting_id AND p.product_uid=NEW.product_uid) BEGIN SELECT RAISE(ABORT,'published product cannot become non-publishable');END;
CREATE TABLE bank_rates(
 accounting_id TEXT NOT NULL,rate_uid TEXT NOT NULL CHECK(length(trim(rate_uid))>0),product_uid TEXT NOT NULL,rate_index INTEGER NOT NULL CHECK(rate_index>0),rate TEXT NOT NULL CHECK(length(trim(rate))>0),comparison_rate TEXT,document_json TEXT NOT NULL CHECK(length(document_json)>1),
 PRIMARY KEY(accounting_id,rate_uid),UNIQUE(accounting_id,product_uid,rate_index),FOREIGN KEY(accounting_id,product_uid) REFERENCES bank_products(accounting_id,product_uid) ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT,WITHOUT ROWID;
CREATE TABLE bank_items(
 accounting_id TEXT NOT NULL,product_uid TEXT NOT NULL,item_group TEXT NOT NULL CHECK(item_group IN('fees','features','eligibility','constraints')),item_index INTEGER NOT NULL CHECK(item_index>0),document_json TEXT NOT NULL CHECK(length(document_json)>1),
 PRIMARY KEY(accounting_id,product_uid,item_group,item_index),FOREIGN KEY(accounting_id,product_uid) REFERENCES bank_products(accounting_id,product_uid) ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT,WITHOUT ROWID;
CREATE TABLE bank_product_facts(
 accounting_id TEXT NOT NULL,product_uid TEXT NOT NULL,fact_id TEXT NOT NULL CHECK(length(trim(fact_id))>0),kind TEXT NOT NULL CHECK(kind IN('fee','rate','tier','bundle','attribute','feature','eligibility','constraint','condition')),
 canonical_key TEXT NOT NULL CHECK(length(trim(canonical_key))>0),value_type TEXT NOT NULL CHECK(value_type IN('boolean','money','rate','number','duration','range','enum','text')),value_boolean INTEGER,value_number REAL,value_text TEXT,min_value REAL,max_value REAL,document_json TEXT NOT NULL CHECK(length(document_json)>1),
 PRIMARY KEY(accounting_id,product_uid,fact_id),FOREIGN KEY(accounting_id,product_uid) REFERENCES bank_products(accounting_id,product_uid) ON UPDATE RESTRICT ON DELETE RESTRICT,
 CHECK(value_boolean IS NULL OR value_boolean IN(0,1)),
 CHECK((value_type='boolean' AND value_boolean IS NOT NULL AND value_number IS NULL AND value_text IS NULL AND min_value IS NULL AND max_value IS NULL)
 OR(value_type IN('money','rate','number') AND value_boolean IS NULL AND value_number IS NOT NULL AND value_text IS NULL AND min_value IS NULL AND max_value IS NULL)
 OR(value_type IN('duration','enum','text') AND value_boolean IS NULL AND value_number IS NULL AND value_text IS NOT NULL AND min_value IS NULL AND max_value IS NULL)
 OR(value_type='range' AND value_boolean IS NULL AND value_number IS NULL AND value_text IS NULL AND(min_value IS NOT NULL OR max_value IS NOT NULL))),
 CHECK(value_number IS NULL OR(kind<>'rate' AND value_type<>'rate')OR value_number BETWEEN 0 AND 1),
 CHECK(min_value IS NULL OR max_value IS NULL OR min_value<=max_value)
) STRICT,WITHOUT ROWID;
CREATE TABLE bank_product_changes(
 accounting_id TEXT NOT NULL,event_id TEXT NOT NULL CHECK(length(trim(event_id))>0),provider_uid TEXT NOT NULL CHECK(length(trim(provider_uid))>0),product_uid TEXT NOT NULL CHECK(length(trim(product_uid))>0),event_type TEXT NOT NULL CHECK(length(trim(event_type))>0),canonical_key TEXT,document_json TEXT NOT NULL CHECK(length(document_json)>1),
 PRIMARY KEY(accounting_id,event_id),FOREIGN KEY(accounting_id) REFERENCES runs(accounting_id) ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT,WITHOUT ROWID;
CREATE INDEX idx_bank_provider_observations_state ON bank_provider_observations(accounting_id,state,population_known,provider_uid);
CREATE INDEX idx_bank_product_dispositions_identity ON bank_product_dispositions(accounting_id,provider_uid,dataset,cdr_product_id,product_uid);
CREATE INDEX idx_bank_product_dispositions_disposition ON bank_product_dispositions(accounting_id,disposition,provider_uid,product_uid);
CREATE INDEX idx_bank_observation_issues_code ON bank_observation_issues(accounting_id,code,issue_id);
CREATE INDEX idx_bank_observation_issues_scope ON bank_observation_issues(accounting_id,scope,provider_uid,product_uid,issue_id);
CREATE INDEX idx_bank_products_provider ON bank_products(accounting_id,dataset,provider_uid,product_uid);
CREATE INDEX idx_bank_rates_product ON bank_rates(accounting_id,product_uid,rate_index,rate_uid);
CREATE INDEX idx_bank_product_facts_numeric ON bank_product_facts(accounting_id,canonical_key,value_number,product_uid,fact_id);
CREATE INDEX idx_bank_product_facts_text ON bank_product_facts(accounting_id,canonical_key,value_text,product_uid,fact_id);
CREATE INDEX idx_bank_product_changes_lookup ON bank_product_changes(accounting_id,provider_uid,event_type,canonical_key,product_uid);
"""
