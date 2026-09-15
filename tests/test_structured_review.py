"""Generated engineering source and simulated human decisions, never bank review."""
import copy
import json
import sqlite3

import pytest

from cdr_terms.store import EvidenceStore
from cdr_terms.identity import byte_digest, canonical_json, digest
from cdr_terms.extraction import extract_document, EXTRACTOR_VERSION
from cdr_terms.ingest import registry_context
from cdr_terms.observation_checks import bind_manual_check
from cdr_terms.queue import TermsQueue
from cdr_terms.revisions import stage_term, review_term, REVIEW_CHECKS
from cdr_terms.reporting import build_product_asset
from cdr_terms.structured_store import migrate
from cdr_terms.structured_review import create_job, retain_candidate, propose, review, CHECKS
from cdr_terms.structured_admission import materialize, association
from tests.test_cdr_terms_pdf import protocol_pdf

NOW = '2026-09-15T00:00:00Z'
LATER = '2026-09-15T01:00:00Z'
TEXT = 'Name AUD Example* *Not applicable to personal accounts.'


@pytest.fixture
def structured(tmp_path):
    with EvidenceStore(tmp_path / 'private') as store:
        migrate(store)
        record = {'productId': 'engineering', 'name': 'Example', 'additionalInformation': {'termsUri': 'https://example.test/technical.pdf'}}
        observation = store.observe(provider='Engineering only', product_key='technical', record=record, observed_at=NOW, ingest_id='technical-only')
        document = store.register_document('https://example.test/technical.pdf'); store.db.commit()
        raw = protocol_pdf([TEXT]); version = store.record_check(document_id=document, check_id='technical', checked_at=NOW, status='fetched', body=raw, media_type='application/pdf')
        bind_manual_check(store, observation, 'technical')
        text, status, coverage = extract_document(raw, 'application/pdf', 'https://example.test/technical.pdf')
        parent = store.register_extraction(document_version_id=version, extractor_version=EXTRACTOR_VERSION, text=text, observed_at=NOW, status=status, coverage=coverage)
        job = create_job(store, parent, [1], actor='collector', created_at=NOW)
        candidate = {'schema_version': 1, 'job_id': job, 'origin': 'supplied_untrusted_candidate', 'tool_status': 'tool_unavailable', 'pages': [{'page': 1, 'text': TEXT.replace('Example', 'Examp1e')}], 'unresolved': ['Technical OCR-like transcription error; no OCR executed']}
        cid = retain_candidate(store, candidate, actor='candidate-author')
        def region(rid, token, role):
            start = TEXT.index(token)
            return {'id': rid, 'page': 1, 'start': start, 'end': start + len(token), 'role': role}
        proposal = {'schema_version': 1, 'candidate_id': cid, 'pages': [{'page': 1, 'text': TEXT}],
                    'regions': [region('name', 'Example', 'cell'), region('header', 'Name', 'header'), region('unit', 'AUD', 'unit'), region('marker', '*', 'marker'), region('note', 'Not applicable to personal accounts.', 'footnote')],
                    'tables': [{'id': 'table', 'cells': [{'region': 'name', 'row': 0, 'column': 0, 'rowSpan': 1, 'columnSpan': 1, 'headers': ['header'], 'units': ['unit']}], 'headers': ['header'], 'units': ['unit'], 'continuation': None}],
                    'links': [{'id': 'qualifier', 'marker': 'marker', 'note': 'note', 'targets': ['name'], 'relation': 'exception'}], 'unresolved': []}
        pid = propose(store, proposal, actor='structure-author')
        def decide(status='accepted', previous=None, reviewer='independent-human-simulation'):
            proof = store.put_blob(canonical_json({'proposal_id': pid, 'candidate_id': cid, 'source_sha256': byte_digest(raw), 'previous_review_id': previous,
                'passed': status == 'accepted', 'checks': sorted(CHECKS), 'basis': 'technical_fixture_only'}).encode())
            return review(store, pid, status=status, reviewer=reviewer, reviewer_kind='human', evidence_sha256=proof, reviewed_at=NOW if previous is None else LATER, expected_previous_review_id=previous)
        yield dict(store=store, raw=raw, parent=parent, observation=observation, proposal=proposal, pid=pid, decide=decide, version=version, document=document)


def prepared(f):
    store = f['store']; rid = f['decide'](); extraction, extension = materialize(store, f['pid'], rid, observed_at=NOW)
    source_sha = store.db.execute('SELECT source_sha256 FROM observations WHERE observation_id=?', (f['observation'],)).fetchone()[0]
    context = {**registry_context(), 'product_keys': ['technical'], 'source_product_sha256': {'technical': source_sha}, **extension}
    queue = TermsQueue(store); jid = queue.enqueue(extraction, context, now=NOW)
    a = association(store, extraction)[1]
    ordered = list(a['clauses'].values())
    clauses = [{**c['locator'], 'disposition': 'parameter', 'reason': 'Technical reviewed structure only'} for c in ordered]
    applicability = {'product_key': 'technical', 'tier': None, 'package': None, 'cohort': None, 'effective_from': None, 'effective_to': None}
    term = {'parameter_key': 'product.name', 'value': 'Example', 'unit': None, **applicability, 'clause_indexes': list(range(len(clauses))), 'conditions': [], 'exceptions': [], 'rule_pattern': None}
    output = {'schema_version': 1, 'extraction_id': extraction, 'context_sha256': digest(context), 'clauses': clauses, 'terms': [term], 'unresolved': ['Technical structure only, not complete legal interpretation']}
    args = dict(observation_id=f['observation'], parameter_key='product.name', value='Example', unit=None, applicability=applicability, clause_ids=[c['clause_id'] for c in ordered], interpreter='separate-interpreter', context_sha256=digest(context), observed_at=NOW)
    return rid, extraction, context, queue, jid, output, args


def test_connected_structure_staging_review_publication_and_revocation(structured, tmp_path):
    f = structured; store = f['store']; parent_before = dict(store.db.execute('SELECT * FROM extractions WHERE extraction_id=?', (f['parent'],)).fetchone())
    rid, extraction, context, queue, jid, output, args = prepared(f)
    claim = queue.claim(NOW); assert claim['job_id'] == jid
    from pi_terms_worker import prepare_job
    prepare_job(store, claim, (tmp_path / 'worker').resolve())
    worker = json.loads((tmp_path / 'worker/input.json').read_text())
    assert worker['reviewed_structure']['links'][0]['relation'] == 'exception'
    queue.save_staging(jid, output, lease_id=claim['lease_id'], now=NOW)
    term = stage_term(store, **args)
    proof = store.put_blob(canonical_json({'term_revision_id': term, 'passed': True, 'checks': sorted(REVIEW_CHECKS)}).encode())
    review_args = dict(status='validated', reviewer='semantic-human-simulation', reviewer_kind='human', reviewed_at=NOW, evidence_sha256=proof, reason='TECHNICAL FIXTURE ONLY, not actual bank review')
    review_term(store, term, **review_args)
    assert build_product_asset(store, 'technical')['revisions'][0]['term_revision_id'] == term
    assert store.db.execute('SELECT status FROM extractions WHERE extraction_id=?', (extraction,)).fetchone()[0] == 'partial'
    assert dict(store.db.execute('SELECT * FROM extractions WHERE extraction_id=?', (f['parent'],)).fetchone()) == parent_before
    f['decide']('revoked', rid)
    for operation in (lambda: queue.validate_input(jid), lambda: queue.validate_staging(jid, output), lambda: stage_term(store, **args), lambda: review_term(store, term, **review_args), lambda: build_product_asset(store, 'technical')):
        with pytest.raises(ValueError, match='no longer accepted'): operation()
    assert store.db.execute('SELECT count(*) FROM reviews').fetchone()[0] == 1


def test_structure_requires_exact_context_and_all_cell_qualifiers(structured):
    _, extraction, context, queue, jid, output, _ = prepared(structured)
    for mutate in (lambda c: c.pop('structure_review'), lambda c: c['structure_review'].update(contract='unknown'), lambda c: c['structure_review'].update(association_sha256='0' * 64)):
        altered = copy.deepcopy(context); mutate(altered)
        with pytest.raises(ValueError): queue.enqueue(extraction, altered, now=NOW)
    cell_index = next(i for i, c in enumerate(output['clauses']) if c['section'] == 'name')
    output['terms'][0]['clause_indexes'] = [cell_index]
    with pytest.raises(ValueError, match='omitted header'): queue.validate_staging(jid, output)


@pytest.mark.parametrize('fault', ['orphan', 'overlap', 'unit', 'page', 'unknown', 'unresolved'])
def test_closed_structure_negatives(structured, fault):
    f = structured; value = copy.deepcopy(f['proposal'])
    if fault == 'orphan': value['links'][0]['note'] = 'absent'
    if fault == 'overlap': value['tables'][0]['cells'].append(copy.deepcopy(value['tables'][0]['cells'][0]))
    if fault == 'unit': value['tables'][0]['cells'][0]['units'] = []
    if fault == 'page': value['regions'][0]['page'] = 2
    if fault == 'unknown': value['schema_version'] = 2
    if fault == 'unresolved':
        value['unresolved'] = ['Ambiguous qualifier']; pid = propose(f['store'], value, actor='author')
        proof = f['store'].put_blob(canonical_json({'proposal_id': pid, 'candidate_id': value['candidate_id'],
            'source_sha256': byte_digest(f['raw']), 'previous_review_id': None, 'passed': True,
            'checks': sorted(CHECKS), 'basis': 'technical_fixture_only'}).encode())
        with pytest.raises(ValueError, match='unresolved'):
            review(f['store'], pid, status='accepted', reviewer='technical-independent', reviewer_kind='human',
                   evidence_sha256=proof, reviewed_at=NOW, expected_previous_review_id=None)
        return
    with pytest.raises(ValueError): propose(f['store'], value, actor='author')


def test_review_actor_and_predecessor_guards(structured):
    f = structured
    with pytest.raises(ValueError, match='Independent'): f['decide'](reviewer=' structure-author ')
    first = f['decide'](); negative = f['decide']('revoked', first)
    with pytest.raises(ValueError, match='predecessor'): f['decide'](previous=first)
    assert f['decide'](previous=negative) != first


def test_explicit_migration_idempotency_and_append_only(structured):
    store = structured['store']; before = store.db.execute('SELECT count(*) FROM observations').fetchone()[0]
    assert migrate(store) == migrate(store)
    with pytest.raises(sqlite3.IntegrityError): store.db.execute('DELETE FROM structured_proposals')
    store.db.rollback()
    assert store.db.execute('SELECT count(*) FROM observations').fetchone()[0] == before
    assert list(store.db.execute('PRAGMA foreign_key_check')) == []


def staged_reviewed(f, count=1):
    rid, extraction, context, queue, jid, output, args = prepared(f)
    claim = queue.claim(NOW)
    queue.save_staging(jid, output, lease_id=claim['lease_id'], now=NOW)
    terms = []
    for i in range(count):
        term = stage_term(f['store'], **{**args, 'interpreter': f'technical-interpreter-{i}'})
        proof = f['store'].put_blob(canonical_json({'term_revision_id': term, 'passed': True, 'checks': sorted(REVIEW_CHECKS)}).encode())
        review_term(f['store'], term, status='validated', reviewer='technical-semantic-reviewer', reviewer_kind='human',
                    reviewed_at=NOW, evidence_sha256=proof, reason='Simulated technical review only')
        terms.append(term)
    return rid, terms


def test_readonly_report_shared_source_bytes_and_fresh_revocation(structured):
    from app_payload_terms import _ReadView
    f = structured; rid, terms = staged_reviewed(f, 32)
    view = _ReadView(f['store'].root)
    calls = []; original = view.read_blob
    def counted(identity):
        calls.append(identity)
        return original(identity)
    view.read_blob = counted
    try:
        assert len(build_product_asset(view, 'technical')['revisions']) == len(terms)
        # One existing archive verification plus one structured immutable byte read.
        assert calls.count(byte_digest(f['raw'])) == 2
    finally:
        view.db.close()
    f['decide']('revoked', rid)
    view = _ReadView(f['store'].root)
    try:
        with pytest.raises(ValueError, match='no longer accepted'):
            build_product_asset(view, 'technical')
    finally:
        view.db.close()


def test_report_filters_superseded_and_unselected_structure_before_validation(structured):
    from cdr_terms.reporting import _revisions
    from cdr_terms.revisions import record_change
    f = structured; rid, terms = staged_reviewed(f)
    observation = f['store'].db.execute('SELECT * FROM observations WHERE observation_id=?', (f['observation'],)).fetchone()
    pid = propose(f['store'], f['proposal'], actor='replacement-structure-author')
    proof = f['store'].put_blob(canonical_json({'proposal_id': pid, 'candidate_id': f['proposal']['candidate_id'],
        'source_sha256': byte_digest(f['raw']), 'previous_review_id': None, 'passed': True,
        'checks': sorted(CHECKS), 'basis': 'technical_fixture_only'}).encode())
    replacement_review = review(f['store'], pid, status='accepted', reviewer='technical-independent', reviewer_kind='human',
        evidence_sha256=proof, reviewed_at=NOW, expected_previous_review_id=None)
    _, replacements = staged_reviewed({**f, 'pid': pid, 'decide': lambda: replacement_review})
    proof = f['store'].put_blob(canonical_json({'passed': True, 'kind': 'extraction_corrected',
        'before_revision_id': terms[0], 'after_revision_id': replacements[0]}).encode())
    record_change(f['store'], product_key='technical', before_revision_id=terms[0], after_revision_id=replacements[0],
        kind='extraction_corrected', observed_at=LATER, evidence_sha256=proof)
    f['decide']('revoked', rid)
    assert _revisions(f['store'], observation, set()) == ([], [])
    assert [r['term_revision_id'] for r in build_product_asset(f['store'], 'technical')['revisions']] == replacements


@pytest.mark.parametrize('registered', [False, True])
def test_reserved_and_registered_extractors_cannot_use_legacy_context(structured, registered):
    f = structured; rid = f['decide'](); store = f['store']
    extraction = store.register_extraction(document_version_id=f['version'],
        extractor_version='legacy-parser' if registered else 'reviewed-structure-v99',
        text=TEXT, observed_at=NOW, status='partial', coverage={})
    if registered:
        sha = store.put_blob(b'{}')
        with store.db:
            store.db.execute('INSERT INTO structured_extractions VALUES (?,?,?,?)', (extraction, f['pid'], rid, sha))
    with pytest.raises(ValueError, match='binding missing or unsupported'):
        TermsQueue(store).enqueue(extraction, {**registry_context(), 'product_keys': ['technical']}, now=NOW)


def test_stale_source_refuses_positive_but_preserves_negative_review(structured):
    f = structured; first = f['decide']()
    f['store'].record_check(document_id=f['document'], check_id='technical-successor', checked_at=LATER,
        status='fetched', body=protocol_pdf(['Changed technical source']), media_type='application/pdf')
    with pytest.raises(ValueError, match='no longer current'):
        materialize(f['store'], f['pid'], first, observed_at=LATER)
    assert f['decide']('revoked', first) != first


def test_bounded_immutable_read_cache_never_caches_authority(structured, monkeypatch):
    from cdr_terms import structured_contract as c
    f = structured; sha = f['store'].put_blob(b'technical')
    @c.evidence_reads
    def control(store):
        assert c.read(store, sha) == b'technical'
        with pytest.raises(ValueError, match='blob limit'): c.read(store, sha, maximum=2)
        assert c.read(store, byte_digest(f['raw'])) == f['raw']
    control(f['store'])
    assert c._READS.get() is None
    deep = []
    for _ in range(22): deep = [deep]
    with pytest.raises(ValueError, match='structural limit'): c.bounded(deep)


def test_readonly_cache_evicts_multiple_documents_and_rechecks_corruption(structured):
    from app_payload_terms import _ReadView
    from cdr_terms import structured_contract as c
    store = structured['store']; identities = []
    # Retained generated PDF bytes only: this tests byte transport, not OCR.
    for index in range(3):
        prefix = protocol_pdf([f'Technical cache document {index}'])
        identities.append(store.put_blob(prefix + b' ' * (16 * 1024**2 - len(prefix))))
    view = _ReadView(store.root)
    @c.evidence_reads
    def control(reader):
        for identity in identities:
            assert len(c.read(reader, identity, 16 * 1024**2)) == 16 * 1024**2
            assert c._READS.get()['bytes'] <= c.CACHE_BYTES
        assert reader.used == 48 * 1024**2
        assert identities[0] not in c._READS.get()['blobs']
        path = store.root / 'blobs' / identities[0][:2] / identities[0]
        with path.open('r+b') as stream: stream.write(b'!')
        with pytest.raises(ValueError, match='identity changed'):
            c.read(reader, identities[0], 16 * 1024**2)
    try:
        control(view)
    finally:
        view.db.close()
    assert c._READS.get() is None


def test_migration_cancellation_rolls_back_and_reopen_is_idempotent(tmp_path, monkeypatch):
    import cdr_terms.structured_store as module
    with EvidenceStore(tmp_path / 'cancel') as store:
        original = module.statements
        class Interrupted(dict):
            def values(self):
                yield next(iter(super().values()))
                raise KeyboardInterrupt('injected cancellation')
        monkeypatch.setattr(module, 'statements', lambda: Interrupted(original()))
        with pytest.raises(KeyboardInterrupt): module.migrate(store)
        assert not store.db.in_transaction
        assert not module.present(store)
        monkeypatch.setattr(module, 'statements', original)
        identity = module.migrate(store)
    with EvidenceStore(tmp_path / 'cancel') as store:
        assert module.migrate(store) == identity
