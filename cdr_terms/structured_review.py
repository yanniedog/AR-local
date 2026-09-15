"""Private candidate and human structure decisions; no OCR execution authority."""
from . import structured_contract as contract
from .identity import canonical_json, digest, timestamp, byte_digest
from .pdf_layout_contract import RetainedExtraction, Budget, LayoutLimits
from .structured_store import present, write_transaction

CHECKS = {'source_page_alignment', 'transcription', 'numbers_units', 'headers_cells',
          'negation_exceptions', 'footnotes_cross_references', 'scope_precedence', 'unresolved_inventory'}


def source(store, extraction_id, *, current=True):
    row = store.db.execute('SELECT x.*,v.document_id,v.content_sha256,v.media_type FROM extractions x '
                           'JOIN document_versions v USING(document_version_id) WHERE extraction_id=?', (extraction_id,)).fetchone()
    if not row or row['media_type'] != 'application/pdf': raise ValueError('Structured source must be retained PDF')
    raw = contract.read(store, row['content_sha256'], 16 * 1024**2)
    text = contract.read(store, row['text_sha256'], 8 * 1024**2).decode('utf-8')
    if len(row['coverage_json']) > contract.MAX_JSON: raise ValueError('Structured parent coverage limit')
    coverage = __import__('json').loads(row['coverage_json']); contract.bounded(coverage)
    retained = RetainedExtraction(row['document_id'], row['document_version_id'], row['content_sha256'],
                                 extraction_id, row['extractor_version'], text, row['text_sha256'], row['status'], coverage)
    retained.verify(raw, Budget(LayoutLimits()))
    if current:
        latest = store.db.execute("SELECT * FROM acquisition_checks WHERE document_id=? "
                                  "AND status IN ('fetched','unchanged') ORDER BY checked_at DESC,sequence DESC LIMIT 1",
                                  (row['document_id'],)).fetchone()
        if not latest or latest['document_version_id'] != row['document_version_id']:
            raise ValueError('Structured source is no longer current')
    return dict(row), coverage


def job_record(store, identity, *, current=True):
    row = store.db.execute('SELECT * FROM structured_jobs WHERE job_id=?', (identity,)).fetchone()
    if not row: raise ValueError('Structured job missing')
    value = contract.load(store, row['blob_sha256'])
    contract.keys(value, 'schema_version contract schema_sha256 source parent_coverage_sha256 pages tool_status actor created_at')
    if value['schema_version'] != 1 or value['contract'] != contract.CONTRACT or value['schema_sha256'] != contract.schema_sha() or value['tool_status'] != 'tool_unavailable':
        raise ValueError('Structured job contract differs')
    if digest(value) != identity: raise ValueError('Structured job identity differs')
    parent, coverage = source(store, row['parent_extraction_id'], current=current)
    expected = {key: parent[key] for key in ('document_id', 'document_version_id', 'extraction_id', 'content_sha256', 'text_sha256')}
    if value['source'] != expected or value['parent_coverage_sha256'] != digest(coverage):
        raise ValueError('Structured parent binding differs')
    return value


def create_job(store, extraction_id, pages, *, actor, created_at):
    if not present(store): raise ValueError('Initialize structured protocol explicitly')
    contract.actor(actor)
    row, coverage = source(store, extraction_id)
    spans = {p['page'] for p in coverage['page_spans']}
    if (not isinstance(pages, list) or not 1 <= len(pages) <= 8 or any(type(p) is not int or p not in spans for p in pages)
            or pages != sorted(set(pages))): raise ValueError('Structured selected pages invalid')
    value = {'schema_version': 1, 'contract': contract.CONTRACT, 'schema_sha256': contract.schema_sha(),
             'source': {key: row[key] for key in ('document_id', 'document_version_id', 'extraction_id', 'content_sha256', 'text_sha256')},
             'parent_coverage_sha256': digest(coverage), 'pages': pages, 'tool_status': 'tool_unavailable',
             'actor': actor, 'created_at': timestamp(created_at)}
    raw = contract.bounded(value); identity = digest(value); sha = store.put_blob(raw)
    with write_transaction(store):
        source(store, extraction_id)
        store.db.execute('INSERT OR IGNORE INTO structured_jobs VALUES (?,?,?,?,?)', (identity, extraction_id, sha, actor, value['created_at']))
    return identity


def retain_candidate(store, value, *, actor):
    contract.actor(actor); contract.validate('candidate', value)
    job = job_record(store, value['job_id']); contract.pages(value['pages'], job['pages'])
    identity = digest([value, actor]); sha = store.put_blob(contract.bounded(value))
    with write_transaction(store):
        job_record(store, value['job_id'])
        store.db.execute('INSERT OR IGNORE INTO structured_candidates VALUES (?,?,?,?)', (identity, value['job_id'], sha, actor))
    return identity


def candidate_record(store, identity, *, current=True):
    row = store.db.execute('SELECT * FROM structured_candidates WHERE candidate_id=?', (identity,)).fetchone()
    if not row: raise ValueError('Structured candidate missing')
    value = contract.load(store, row['blob_sha256']); contract.validate('candidate', value)
    if digest([value, row['actor']]) != identity or value['job_id'] != row['job_id']:
        raise ValueError('Structured candidate identity differs')
    job = job_record(store, row['job_id'], current=current); contract.pages(value['pages'], job['pages'])
    return dict(row), value, job


def propose(store, value, *, actor):
    contract.actor(actor)
    _, _, job = candidate_record(store, value['candidate_id'])
    contract.proposal(value, job['pages'])
    identity = digest([value, actor]); sha = store.put_blob(contract.bounded(value))
    with write_transaction(store):
        candidate_record(store, value['candidate_id'])
        store.db.execute('INSERT OR IGNORE INTO structured_proposals VALUES (?,?,?,?)', (identity, value['candidate_id'], sha, actor))
    return identity


def proposal_record(store, identity, *, current=True):
    row = store.db.execute('SELECT * FROM structured_proposals WHERE proposal_id=?', (identity,)).fetchone()
    if not row: raise ValueError('Structured proposal missing')
    value = contract.load(store, row['blob_sha256'])
    candidate, _, job = candidate_record(store, row['candidate_id'], current=current)
    if digest([value, row['actor']]) != identity or value['candidate_id'] != row['candidate_id']:
        raise ValueError('Structured proposal identity differs')
    regions = contract.proposal(value, job['pages'])
    return dict(row), value, job, regions, candidate


def latest_review(store, proposal_id):
    return store.db.execute('SELECT * FROM structured_reviews WHERE proposal_id=? ORDER BY sequence DESC LIMIT 1', (proposal_id,)).fetchone()


def review(store, proposal_id, *, status, reviewer, reviewer_kind, evidence_sha256,
           reviewed_at, expected_previous_review_id):
    actor = contract.actor(reviewer)
    if status not in ('accepted', 'rejected', 'revoked') or reviewer_kind != 'human':
        raise ValueError('Independent human structure review required; model consensus is insufficient')
    proof = contract.load(store, evidence_sha256); contract.validate('reviewEvidence', proof)
    with write_transaction(store):
        row, value, job, _, candidate = proposal_record(store, proposal_id, current=status == 'accepted')
        if actor in (contract.actor(row['actor']), contract.actor(candidate['actor']), contract.actor(job['actor'])):
            raise ValueError('Independent structured reviewer required')
        previous = latest_review(store, proposal_id)
        if (previous['review_id'] if previous else None) != expected_previous_review_id:
            raise ValueError('Structured review predecessor changed')
        if (proof['proposal_id'] != proposal_id or proof['candidate_id'] != row['candidate_id']
                or proof['previous_review_id'] != expected_previous_review_id
                or proof['source_sha256'] != job['source']['content_sha256']):
            raise ValueError('Structured review evidence binding differs')
        if status == 'accepted' and (proof['passed'] is not True or not CHECKS <= set(proof['checks']) or value['unresolved']):
            raise ValueError('Structured source checks or unresolved associations incomplete')
        fields = (proposal_id, expected_previous_review_id, status, reviewer, reviewer_kind, evidence_sha256, timestamp(reviewed_at))
        identity = digest(fields)
        store.db.execute('INSERT INTO structured_reviews (review_id,proposal_id,previous_review_id,status,actor,reviewer_kind,evidence_sha256,created_at) VALUES (?,?,?,?,?,?,?,?)', (identity, *fields))
    return identity


def accepted(store, proposal_id, review_id, *, current=True):
    row, value, job, regions, candidate = proposal_record(store, proposal_id, current=current)
    review_row = latest_review(store, proposal_id)
    if not review_row or review_row['review_id'] != review_id or review_row['status'] != 'accepted':
        raise ValueError('Structured review is no longer accepted')
    proof = contract.load(store, review_row['evidence_sha256']); contract.validate('reviewEvidence', proof)
    fields = tuple(review_row[k] for k in ('proposal_id', 'previous_review_id', 'status', 'actor', 'reviewer_kind', 'evidence_sha256', 'created_at'))
    if (digest(fields) != review_id or review_row['reviewer_kind'] != 'human'
            or contract.actor(review_row['actor']) in (contract.actor(row['actor']), contract.actor(candidate['actor']), contract.actor(job['actor']))
            or proof['proposal_id'] != proposal_id or proof['candidate_id'] != row['candidate_id']
            or proof['previous_review_id'] != review_row['previous_review_id']
            or proof['source_sha256'] != job['source']['content_sha256'] or proof['passed'] is not True
            or not CHECKS <= set(proof['checks']) or value['unresolved']):
        raise ValueError('Structured review proof differs')
    return row, value, job, regions
