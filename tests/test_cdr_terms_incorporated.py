"""Real retained CDR scopes; child markup/transport are protocol controls only."""
from __future__ import annotations

import copy
import json

import pytest

from cdr_terms.acquisition_processing import ProcessingGuardFailure, ProcessingQueue
from cdr_terms.graph import DocumentGraph
from cdr_terms.identity import digest
from cdr_terms.incorporated import build_target, output_scope, validate_target
from cdr_terms.ingest import registry_context
from cdr_terms.queue import TermsQueue
from cdr_terms.reporting import build_product_asset, validate_public_asset
from cdr_terms.revisions import stage_term
from tests.test_cdr_terms_graph import retained, start, FIXTURE, URL
from tests.test_cdr_terms_acquisition_batch import clock, add_source


def ready_child(retained, clock, monkeypatch, markup='<p>Protocol child text.</p>'):
    monkeypatch.setattr('cdr_terms.queue.utc_now', clock.now)
    store, observation, acquisition = retained
    root, _, _ = start(retained, '<a href="/protocol-child">Child</a><a href="/protocol-child">Repeated scope</a>')
    queue = ProcessingQueue(store)
    expanded = queue.process_one(registry_context())
    assert expanded['status'] == 'complete' and 'analysis_job_id' not in expanded['outcome']
    node = next(row for row in DocumentGraph(store).inventory(root)['nodes'] if row['depth'] == 1)
    while True:
        request = acquisition.claim()
        assert request
        chosen = request['request_id'] == node['request_id']
        check_id = digest([request['request_id'], request['lease_id']])
        url = store.db.execute('SELECT source_url FROM documents WHERE document_id=?', (request['document_id'],)).fetchone()[0]
        store.record_check(document_id=request['document_id'], check_id=check_id, checked_at=clock.now(), status='fetched',
            body=markup.encode() if chosen else FIXTURE.read_bytes(), media_type='text/html' if chosen else 'application/json', metadata={'final_url': url})
        acquisition.finish(request, check_id, defer_processing=True)
        if chosen:
            return queue, node, observation


def child_job(store, queue, node):
    for _ in range(12):
        receipt = queue.process_one(registry_context())
        assert receipt is not None
        if receipt.get('node_id') == node['node_id']:
            assert receipt['status'] == 'complete'
            queue.validate_receipt(receipt)
            job_id = receipt['outcome']['analysis_job_id']
            return receipt, dict(store.db.execute('SELECT * FROM analysis_jobs WHERE job_id=?', (job_id,)).fetchone())
    pytest.fail('bounded child processing did not progress')


def output(store, job):
    context = TermsQueue(store).validate_input(job['job_id'])
    extraction = store.db.execute('SELECT text_sha256 FROM extractions WHERE extraction_id=?', (job['extraction_id'],)).fetchone()
    text = store.read_blob(extraction[0]).decode()
    return {'schema_version': 1, 'extraction_id': job['extraction_id'], 'context_sha256': job['context_sha256'],
        'incorporated_scope': output_scope(context['incorporated_target']),
        'clauses': [{'start': 0, 'end': len(text), 'page': None, 'section': None,
                     'disposition': 'unresolved', 'reason': 'Protocol only; legal applicability unreviewed'}],
        'terms': [], 'unresolved': ['Applicability unreviewed']}


def test_actual_graph_child_reaches_worker_staging_without_applicability(retained, clock, monkeypatch, tmp_path):
    import pi_terms_worker as worker
    import pi_terms_codex as transport
    from tests.test_cdr_quality_resources import receipt as resource_receipt
    store, _, _ = retained
    processing, node, observation = ready_child(retained, clock, monkeypatch)
    receipt, created = child_job(store, processing, node)
    queue = TermsQueue(store)
    # Other direct reference jobs are legitimate independent work; select the
    # candidate by blocking only this disposable test's earlier jobs.
    while True:
        job = queue.claim(now=clock.now())
        assert job
        if job['job_id'] == created['job_id']:
            break
        queue.event(job['job_id'], 'blocked', now=clock.now(), lease_id=job['lease_id'], error_code='protocol_other_job')
    context = queue.validate_input(job['job_id'])
    target = context['incorporated_target']
    assert len(target['source_scopes']) == 3
    assert len(target['ancestry']) == 2 and len(target['ancestry'][0]['parent_edges']) == 2
    assert {scope['observation_id'] for scope in target['source_scopes']} == {observation}
    operation = (tmp_path / 'protocol-operation').resolve()
    worker.prepare_job(store, job, operation)
    prepared = json.loads((operation / 'input.json').read_bytes())
    assert prepared['expected_incorporated_scope'] == output_scope(target)
    staged = output(store, job)
    transport.write_receipt(operation / 'result.json', staged)
    transport.write_receipt(operation / 'transport.json', {'schema_version': 1, 'result': 'STAGING_ONLY',
        'codex_called': False, 'started_at': clock.now(), 'finished_at': clock.now(), **transport.input_hashes(operation),
        'result_sha256': transport.file_hash(operation / 'result.json', transport.MAX_RESULT_BYTES)})
    result = worker.complete_job(queue, job, operation, resource_receipt())
    assert result['result'] == 'STAGED_INCORPORATED_CANDIDATE'
    assert result['current_publication'] == 'PROHIBITED_UNREVIEWED_APPLICABILITY'
    assert result['codex_called'] is False
    assert store.db.execute('SELECT COUNT(*) FROM term_revisions').fetchone()[0] == 0
    assert store.db.execute('SELECT COUNT(*) FROM applicability WHERE document_id=?', (node['document_id'],)).fetchone()[0] == 0
    public = build_product_asset(store, target['source_scopes'][0]['product_key'])
    assert public['revisions'] == []
    with pytest.raises(ValueError, match='candidate staging'):
        validate_public_asset({**public, 'incorporated_scope': output_scope(target)})
    processing.validate_receipt(receipt)


@pytest.mark.parametrize('mutation', ['scope', 'check', 'product', 'boolean_version', 'unknown_profile'])
def test_target_tampering_and_profile_context_are_rejected(retained, clock, monkeypatch, mutation, tmp_path):
    import pi_terms_worker as worker
    store, _, _ = retained
    processing, node, _ = ready_child(retained, clock, monkeypatch)
    _, job = child_job(store, processing, node)
    context = TermsQueue(store).validate_input(job['job_id'])
    bad = copy.deepcopy(context)
    if mutation == 'scope':
        bad['incorporated_target']['scope'] = 'current'
    elif mutation == 'check':
        bad['incorporated_target']['ancestry'][0]['check_id'] = '0' * 64
    elif mutation == 'product':
        bad['source_product_sha256'] = {'unrelated': '0' * 64}
    elif mutation == 'boolean_version':
        bad['incorporated_target']['schema_version'] = True
    else:
        bad['customer_profile'] = {'private': 'must not leave test'}
        identity = TermsQueue(store).enqueue(job['extraction_id'], bad)
        row = dict(store.db.execute('SELECT j.*,x.text_sha256 FROM analysis_jobs j JOIN extractions x USING(extraction_id) WHERE job_id=?', (identity,)).fetchone())
        with pytest.raises(ValueError, match='customer profiles'):
            worker.prepare_job(store, row, (tmp_path / 'forbidden').resolve())
        assert not (tmp_path / 'forbidden').exists()
        return
    with pytest.raises(ValueError, match='exact retained'):
        validate_target(store, job['extraction_id'], bad)


@pytest.mark.parametrize('change', ['source', 'parent', 'child'])
def test_source_advance_prevents_input_but_keeps_exact_old_receipt(retained, clock, monkeypatch, tmp_path, change):
    import pi_terms_worker as worker
    store, _, _ = retained
    processing, node, _ = ready_child(retained, clock, monkeypatch)
    receipt, job = child_job(store, processing, node)
    target = TermsQueue(store).validate_input(job['job_id'])['incorporated_target']
    clock.advance(2)
    if change == 'source':
        add_source(store, ingest='new-completed-observation', observed='2026-09-08T00:00:00Z')
    else:
        chosen = target['ancestry'][0 if change == 'child' else 1]
        document = store.db.execute('SELECT document_id FROM document_versions WHERE document_version_id=?', (chosen['document_version_id'],)).fetchone()[0]
        store.record_check(document_id=document, check_id=digest(['changed', change]), checked_at=clock.now(), status='fetched',
            body=b'Changed protocol document', media_type='text/plain', metadata={'final_url': chosen['final_url']})
    with pytest.raises(ValueError, match='superseded'):
        worker.prepare_job(store, job, (tmp_path / 'forbidden').resolve())
    assert not (tmp_path / 'forbidden').exists()
    processing.validate_receipt(receipt)  # Historical receipt readback is not new work admission.
    assert store.db.execute('SELECT COUNT(*) FROM term_revisions').fetchone()[0] == 0


@pytest.mark.parametrize('seam', ['context_blob', 'job_insert'])
def test_expiry_during_child_enqueue_rolls_back_graph_and_job(retained, clock, monkeypatch, seam):
    store, _, _ = retained
    processing, node, _ = ready_child(retained, clock, monkeypatch)
    original = store.put_blob
    armed = {'value': False}
    if seam == 'context_blob':
        def expired(body):
            result = original(body)
            if b'"incorporated_target"' in body:
                armed['value'] = True
                clock.advance(181)
            return result
        monkeypatch.setattr(store, 'put_blob', expired)
    else:
        def trace(sql):
            if sql.startswith('INSERT OR IGNORE INTO analysis_jobs'):
                armed['value'] = True
                clock.advance(181)
        store.db.set_trace_callback(trace)
    # Before the child, dispose of any unrelated direct processing in order.
    with pytest.raises(ProcessingGuardFailure, match='Stale processing'):
        for _ in range(12):
            processing.process_one(registry_context())
    store.db.set_trace_callback(None)
    assert armed['value']
    assert store.db.execute('SELECT COUNT(*) FROM document_graph_expansions WHERE node_id=?', (node['node_id'],)).fetchone()[0] == 0
    for row in store.db.execute('SELECT context_blob_sha256 FROM analysis_jobs'):
        assert 'incorporated_target' not in json.loads(store.read_blob(row[0]))


def test_required_scope_exact_extraction_and_no_current_term_admission(retained, clock, monkeypatch):
    store, _, _ = retained
    processing, node, observation = ready_child(retained, clock, monkeypatch)
    _, job = child_job(store, processing, node)
    queue, staged = TermsQueue(store), output(store, job)
    without = {key: value for key, value in staged.items() if key != 'incorporated_scope'}
    with pytest.raises(ValueError, match='candidate-only'):
        queue.validate_staging(job['job_id'], without)
    queue.validate_staging(job['job_id'], staged)
    context = queue.validate_input(job['job_id'])
    with pytest.raises(ValueError, match='exact retained'):
        validate_target(store, '0' * 64, context)
    with pytest.raises(ValueError, match='historical'):
        queue.enqueue(job['extraction_id'], context, priority=2)
    clause = store.add_clause(job['extraction_id'], start=0, end=1)
    applicability = dict.fromkeys(('tier', 'package', 'cohort', 'effective_from', 'effective_to'))
    applicability['product_key'] = context['product_keys'][0]
    with pytest.raises(ValueError, match='applicability'):
        stage_term(store, observation_id=observation, parameter_key='product.name', value='Protocol', unit=None,
            applicability=applicability, clause_ids=[clause], interpreter='protocol', context_sha256=job['context_sha256'], observed_at=clock.now())
    assert store.db.execute('SELECT COUNT(*) FROM term_revisions').fetchone()[0] == 0


def test_empty_child_finishes_graph_without_false_job_and_sibling_progresses(retained, clock, monkeypatch):
    store, _, _ = retained
    processing, node, _ = ready_child(retained, clock, monkeypatch, markup='<a href="/next"><img src="icon"></a>')
    for _ in range(12):
        result = processing.process_one(registry_context())
        if result.get('node_id') == node['node_id']:
            break
    assert result['status'] == 'complete' and 'analysis_job_id' not in result['outcome']
    processing.validate_receipt(result)
    assert any(row['depth'] == 2 for row in DocumentGraph(store).inventory(node['root_id'])['nodes'])
    assert not store.db.execute('SELECT 1 FROM analysis_jobs j JOIN extractions x USING(extraction_id) '
        'JOIN document_versions v USING(document_version_id) WHERE v.document_id=?', (node['document_id'],)).fetchone()


def test_due_scan_reads_only_context_and_admission_still_requires_originals(retained, clock, monkeypatch):
    store, _, _ = retained
    processing, node, _ = ready_child(retained, clock, monkeypatch)
    _, job = child_job(store, processing, node)
    queue = TermsQueue(store)
    target = queue.validate_input(job['job_id'])['incorporated_target']
    original = store.read_blob
    forbidden = {target['document_content_sha256'], target['extraction_text_sha256'],
                 *(scope['source_sha256'] for scope in target['source_scopes'])}
    def missing(identity):
        if identity in forbidden:
            raise OSError('protocol original unavailable')
        return original(identity)
    monkeypatch.setattr(store, 'read_blob', missing)
    assert queue._source_state(job['job_id'], check_blobs=False) == 'current'
    with pytest.raises(OSError, match='original unavailable'):
        queue.validate_input(job['job_id'])
