"""Explicit additive private migration; no original table or frozen DDL changes."""
from contextlib import contextmanager
import re

from .identity import digest

TABLES = {
    'structured_protocol': 'version TEXT PRIMARY KEY, schema_sha256 TEXT NOT NULL',
    'structured_jobs': 'job_id TEXT PRIMARY KEY, parent_extraction_id TEXT NOT NULL REFERENCES extractions(extraction_id), blob_sha256 TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL',
    'structured_candidates': 'candidate_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES structured_jobs(job_id), blob_sha256 TEXT NOT NULL, actor TEXT NOT NULL',
    'structured_proposals': 'proposal_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES structured_candidates(candidate_id), blob_sha256 TEXT NOT NULL, actor TEXT NOT NULL',
    'structured_reviews': '''sequence INTEGER PRIMARY KEY AUTOINCREMENT, review_id TEXT NOT NULL UNIQUE,
        proposal_id TEXT NOT NULL REFERENCES structured_proposals(proposal_id), previous_review_id TEXT,
        status TEXT NOT NULL CHECK(status IN ('accepted','rejected','revoked')), actor TEXT NOT NULL,
        reviewer_kind TEXT NOT NULL CHECK(reviewer_kind='human'), evidence_sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
        UNIQUE(review_id,proposal_id), FOREIGN KEY(previous_review_id,proposal_id) REFERENCES structured_reviews(review_id,proposal_id)''',
    'structured_extractions': '''extraction_id TEXT PRIMARY KEY REFERENCES extractions(extraction_id),
        proposal_id TEXT NOT NULL REFERENCES structured_proposals(proposal_id), review_id TEXT NOT NULL,
        association_sha256 TEXT NOT NULL, UNIQUE(proposal_id,review_id),
        FOREIGN KEY(review_id,proposal_id) REFERENCES structured_reviews(review_id,proposal_id)''',
    'structured_clauses': '''clause_id TEXT PRIMARY KEY REFERENCES clauses(clause_id),
        extraction_id TEXT NOT NULL REFERENCES structured_extractions(extraction_id), region_id TEXT NOT NULL,
        UNIQUE(extraction_id,region_id)''',
}


def statements():
    result = {name: f'CREATE TABLE {name} ({fields})' for name, fields in TABLES.items()}
    result['structured_reviews_latest'] = 'CREATE INDEX structured_reviews_latest ON structured_reviews(proposal_id,sequence DESC)'
    for name in TABLES:
        for operation in ('UPDATE', 'DELETE'):
            key = f'immutable_{name}_{operation.lower()}'
            result[key] = f"CREATE TRIGGER {key} BEFORE {operation} ON {name} BEGIN SELECT RAISE(ABORT,'append-only structured evidence'); END"
    return result


@contextmanager
def write_transaction(store):
    if store.db.in_transaction: raise ValueError('Structured operation requires its own transaction')
    store.db.execute('BEGIN IMMEDIATE')
    try:
        yield
        store.db.commit()
    except BaseException:
        store.db.rollback()
        raise


def present(store):
    return store.db.execute("SELECT 1 FROM sqlite_master WHERE name='structured_protocol' AND type='table'").fetchone() is not None


def migrate(store):
    """Explicit fixture/controller call only. Never run from ordinary store open."""
    expected = statements(); identity = digest(expected)
    normalize = lambda sql: re.sub(r'\s+', ' ', sql.strip()).lower()
    with write_transaction(store):
        count, size = store.db.execute("SELECT count(*),coalesce(sum(length(sql)),0) FROM sqlite_master").fetchone()
        if count > 4096 or size > 2 * 1024**2: raise ValueError('Structured schema inventory limit')
        old = {r[0]: r[1] for r in store.db.execute('SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL')}
        existing = set(expected) & set(old)
        if existing:
            if existing != set(expected) or any(normalize(old[k]) != normalize(v) for k, v in expected.items()):
                raise ValueError('Structured installed schema differs')
            marker = store.db.execute("SELECT schema_sha256 FROM structured_protocol WHERE version='1'").fetchone()
            if not marker or marker[0] != identity: raise ValueError('Structured migration marker differs')
            return identity
        for sql in expected.values(): store.db.execute(sql)
        store.db.execute('INSERT INTO structured_protocol VALUES (?,?)', ('1', identity))
        now = {r[0]: r[1] for r in store.db.execute('SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL')}
        if any(now.get(k) != v for k, v in old.items()): raise ValueError('Original schema changed')
    return identity
