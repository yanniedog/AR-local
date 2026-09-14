"""Lease/source boundaries using retained raw CDR and labelled graph markup."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cdr_terms.acquisition_processing import ProcessingGuardFailure, ProcessingQueue
from cdr_terms.graph import DocumentGraph
from cdr_terms.identity import digest
from cdr_terms.queue import TermsQueue
from cdr_terms import acquisition_batch as batch
from tests.test_cdr_terms_graph import retained, start
from tests.test_cdr_terms_acquisition_batch import BOM, add_source, clock


def test_explicit_graph_node_does_not_fall_through_to_another_node(retained):
    store, _, _ = retained
    root, _, _ = start(retained, '<a href="/protocol-one">One</a>')
    graph = DocumentGraph(store)
    node = graph.pending()['node_id']
    with pytest.raises(ValueError, match='accepted and pending'):
        graph.advance_one('missing-node')
    assert graph.pending()['node_id'] == node
    assert graph.advance_one(node)['node_id'] == node
    with pytest.raises(ValueError, match='accepted and pending'):
        graph.advance_one(node)
    assert len(graph.inventory(root)['edges']) == 1


@pytest.mark.parametrize('failed_parse', [False, True])
def test_expired_processing_lease_cannot_write_children_or_failure_expansion(retained, clock, monkeypatch, failed_parse):
    import cdr_terms.graph as graph_module
    store, _, _ = retained
    root, _, _ = start(retained, '<a href="/protocol-child">Child</a>')
    graph = DocumentGraph(store)
    before = {table: store.db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
              for table in ('document_graph_nodes', 'document_graph_edges', 'document_graph_expansions', 'acquisition_requests')}
    original = graph_module.extract_version
    def expired(*args, **kwargs):
        clock.advance(181)
        if failed_parse:
            raise OSError('isolated corrupted private blob')
        return original(*args, **kwargs)
    monkeypatch.setattr(graph_module, 'extract_version', expired)
    with pytest.raises(ProcessingGuardFailure, match='Stale processing admission'):
        ProcessingQueue(store).process_one({})
    assert {table: store.db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] for table in before} == before
    event = store.db.execute('SELECT status FROM acquisition_processing_events ORDER BY sequence DESC LIMIT 1').fetchone()[0]
    assert event == 'running'  # Guard refusal is not completion or parser exhaustion.
    assert graph.inventory(root)['nodes'][0]['expansion'] is None


def test_new_completed_source_during_parse_rolls_back_graph_frontier(retained, clock, monkeypatch):
    import cdr_terms.graph as graph_module
    store, _, _ = retained
    root, _, _ = start(retained, '<a href="/protocol-child">Child</a>')
    original = graph_module.extract_version
    def replace_source(*args, **kwargs):
        extraction = original(*args, **kwargs)
        add_source(store, ingest='completed-source-replacement', observed='2026-09-08T00:00:00Z')
        return extraction
    monkeypatch.setattr(graph_module, 'extract_version', replace_source)
    with pytest.raises(ProcessingGuardFailure, match='superseded'):
        ProcessingQueue(store).process_one({})
    inventory = DocumentGraph(store).inventory(root)
    assert len(inventory['nodes']) == 1 and inventory['edges'] == []
    assert inventory['nodes'][0]['expansion'] is None


def test_replaced_processing_lease_rejects_old_owner(retained, clock):
    store, _, _ = retained
    start(retained, '<p>Protocol structure only</p>')
    queue = ProcessingQueue(store)
    first = queue.claim(lease_seconds=1)
    clock.advance(2)
    assert queue.claim() is None  # Crash recovery gives future backoff.
    clock.advance(301)
    second = queue.claim()
    assert second['processing_id'] == first['processing_id'] and second['lease_id'] != first['lease_id']
    with pytest.raises(ValueError, match='Stale processing completion'):
        queue.finish(first, {'invalid': 'stale'})
    queue.assert_lease(second)


def test_unaccepted_graph_root_cannot_keep_collector_runnable(retained, clock):
    store, _, acquisitions = retained
    root, request, check = start(retained, '<p>Protocol structure only</p>')
    # An orphan seeded from another exact check is retained, but never admitted.
    store.record_check(document_id=request['document_id'], check_id='unaccepted-capture', checked_at=clock.now(),
                       status='fetched', body=b'<p>Isolated orphan protocol bytes</p>', media_type='text/html')
    orphan = dict(store.db.execute("SELECT * FROM acquisition_checks WHERE check_id='unaccepted-capture'").fetchone())
    other_root = DocumentGraph(store).seed(request, orphan)
    assert other_root != root
    ProcessingQueue(store).process_one({})
    assert ProcessingQueue(store).has_work() is False
    assert store.db.execute('SELECT COUNT(*) FROM document_graph_expansions').fetchone()[0] == 0


def _capture_deferred(retained, clock, *, request_id=None):
    store, _, queue = retained
    while True:
        request = queue.claim()
        assert request
        chosen = request_id is None or request['request_id'] == request_id
        identity = digest([request['request_id'], request['lease_id']])
        store.record_check(document_id=request['document_id'], check_id=identity, checked_at=clock.now(),
            status='fetched', body=BOM.read_bytes(), media_type='application/json',
            metadata={'final_url': 'https://www.bankofmelbourne.com.au/'})
        queue.finish(request, identity, defer_processing=chosen)
        if chosen:
            return identity


@pytest.mark.parametrize('boundary', ['context_blob', 'after_job_writes'])
def test_analysis_admission_rolls_back_expired_owner_at_actual_transaction(retained, clock, monkeypatch, boundary):
    store, _, _ = retained
    _capture_deferred(retained, clock)
    observed_transactions = []
    if boundary == 'context_blob':
        original = store.put_blob
        def delayed(body):
            if b'"source_product_sha256"' in body:
                observed_transactions.append(store.db.in_transaction)
                clock.advance(181)
            return original(body)
        monkeypatch.setattr(store, 'put_blob', delayed)
    else:
        original = TermsQueue._prioritize
        def delayed(queue, *args):
            original(queue, *args)
            observed_transactions.append(store.db.in_transaction)
            clock.advance(181)
        monkeypatch.setattr(TermsQueue, '_prioritize', delayed)
    with pytest.raises(ProcessingGuardFailure, match='Stale processing admission'):
        ProcessingQueue(store).process_one({})
    assert observed_transactions == [boundary == 'after_job_writes']
    assert {table: store.db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
            for table in ('analysis_jobs', 'job_events', 'job_priorities')} == {
                'analysis_jobs': 0, 'job_events': 0, 'job_priorities': 0}
    assert TermsQueue(store).claim(now=clock.now()) is None


@pytest.mark.parametrize('shared_scope', [False, True])
def test_changed_completed_scope_during_context_storage_cannot_enqueue(retained, clock, monkeypatch, shared_scope):
    store, original_observation, _ = retained
    selected = None
    if shared_scope:
        second = add_source(store, Path(__file__).parent / 'fixtures/cdr-document-graph-2026-05-19/bom-variable.json')
        selected = store.db.execute('SELECT request_id FROM acquisition_bindings WHERE observation_id IN (?,?) '
            'GROUP BY request_id HAVING COUNT(*)=2 LIMIT 1', (original_observation, second)).fetchone()[0]
    _capture_deferred(retained, clock, request_id=selected)
    original = store.put_blob
    replaced = []
    def replace_source(body):
        if b'"source_product_sha256"' in body and not replaced:
            replaced.append(True)
            add_source(store, ingest='replacement-completed-source', observed='2026-09-08T00:00:00Z')
        return original(body)
    monkeypatch.setattr(store, 'put_blob', replace_source)
    with pytest.raises(ProcessingGuardFailure, match='superseded'):
        ProcessingQueue(store).process_one({})
    assert replaced
    assert store.db.execute('SELECT COUNT(*) FROM analysis_jobs').fetchone()[0] == 0


def test_current_processing_output_readback_binds_job_context_and_event(retained, clock):
    store, _, _ = retained
    _capture_deferred(retained, clock)
    queue = ProcessingQueue(store)
    value = queue.process_one({})
    assert value['status'] == 'complete' and value['outcome']['analysis_job_id']
    queue.validate_receipt(value)
    # Later current observations cannot rewrite the accepted historical receipt.
    add_source(store, ingest='later-completed-source', observed='2026-09-08T00:00:00Z')
    queue.validate_receipt(value)


@pytest.mark.parametrize('field', ['processing_event_id', 'processing_id', 'check_id', 'lease_id', 'request_id', 'node_id', 'analysis_job_id'])
def test_processing_output_corruption_cannot_pass_batch_controller(retained, clock, field):
    store, _, _ = retained
    _capture_deferred(retained, clock)
    receipt = ProcessingQueue(store).process_one({})
    value = batch.run_batch(store, registry_context={}, deadline=105, guard=lambda: 'protocol-stop')
    value['processing'] = json.loads(json.dumps(receipt))
    if field == 'analysis_job_id':
        value['processing']['outcome'][field] = 'f' * 64
    else:
        value['processing'][field] = 'f' * 64
    value['batch_sha256'] = digest({key: body for key, body in value.items() if key != 'batch_sha256'})
    batch.validate_batch_receipt(value)
    with pytest.raises(ValueError, match='(?i)processing'):
        batch.validate_batch_evidence(store, value)


def test_queued_processing_cannot_claim_an_invented_completed_job(retained, clock):
    store, _, _ = retained
    check = _capture_deferred(retained, clock)
    task = ProcessingQueue(store).due()
    value = batch.run_batch(store, registry_context={}, deadline=105, guard=lambda: 'protocol-stop')
    value['processing'] = {'processing_id': task['processing_id'], 'check_id': check, 'analysis_job_id': 'f' * 64}
    with pytest.raises(ValueError, match='(?i)processing'):
        batch.validate_batch_evidence(store, value)


def test_graph_processing_receipt_matches_actual_expansion(retained, clock):
    store, _, _ = retained
    start(retained, '<a href="/protocol-reference">Protocol link only</a>')
    value = ProcessingQueue(store).process_one({})
    assert value['outcome']['graph']['links_observed'] == 1
    ProcessingQueue(store).validate_receipt(value)
    changed = json.loads(json.dumps(value))
    changed['outcome']['graph']['links_observed'] = 0
    with pytest.raises(ValueError, match='durable outcome'):
        ProcessingQueue(store).validate_receipt(changed)


def test_failed_parser_receipt_does_not_claim_a_job(retained, clock, monkeypatch):
    store, _, _ = retained
    _capture_deferred(retained, clock)
    def fail(*args, **kwargs):
        raise ValueError('Isolated parser protocol failure')
    monkeypatch.setattr('cdr_terms.acquisitions_queue.enqueue_interpretation', fail)
    value = ProcessingQueue(store).process_one({})
    assert value['status'] == 'retry_wait' and value['outcome']['attempts'] == 1
    assert 'analysis_job_id' not in value['outcome']
    ProcessingQueue(store).validate_receipt(value)


def test_guard_checks_both_transaction_boundaries_for_idempotent_job(retained, clock, monkeypatch):
    store, _, _ = retained
    _capture_deferred(retained, clock)
    value = ProcessingQueue(store).process_one({})
    job = store.db.execute('SELECT * FROM analysis_jobs WHERE job_id=?', (value['outcome']['analysis_job_id'],)).fetchone()
    context = json.loads(store.read_blob(job['context_blob_sha256']))
    calls = []
    def reject_return():
        calls.append(store.db.in_transaction)
        if len(calls) == 2:
            raise ProcessingGuardFailure('Protocol late authority loss')
    with pytest.raises(ProcessingGuardFailure, match='late authority loss'):
        TermsQueue(store).enqueue(job['extraction_id'], context, priority=0, completion_guard=reject_return)
    assert calls == [True, True]
    assert store.db.execute('SELECT COUNT(*) FROM analysis_jobs').fetchone()[0] == 1


def test_processing_job_corruption_rejected_after_all_artifact_hashes_match(retained, clock, tmp_path):
    from pi_terms_codex import write_receipt
    from pi_terms_worker import read_acquisition_batch
    from cdr_terms.identity import byte_digest, canonical_json
    store, _, _ = retained
    _capture_deferred(retained, clock)
    processing = ProcessingQueue(store).process_one({})
    result = batch.run_batch(store, registry_context={}, deadline=105, guard=lambda: 'protocol-stop')
    result['processing'] = processing
    operation = tmp_path / 'private-artifacts'
    operation.mkdir(mode=0o700)
    write_receipt(operation / 'input.json', {'evidence_root': str(store.root), 'registry_context': {}})
    def write_artifacts():
        result['batch_sha256'] = digest({key: value for key, value in result.items() if key != 'batch_sha256'})
        value = {'schema_version': 2, 'input_sha256': byte_digest((operation / 'input.json').read_bytes()), **result}
        body = canonical_json(value).encode('utf-8')
        write_receipt(operation / 'batch.json', value)
        write_receipt(operation / 'acquisition.json', {'schema_version': 2, 'input_sha256': value['input_sha256'],
            'result': result['result'], 'network_called': False, 'codex_called': False,
            'batch_file_sha256': byte_digest(body), 'batch_file_bytes': len(body)})
        return value
    value = write_artifacts()
    assert read_acquisition_batch(operation, store=store) == value
    processing['outcome']['analysis_job_id'] = 'f' * 64
    operation = tmp_path / 'corrupted-artifacts'
    operation.mkdir(mode=0o700)
    write_receipt(operation / 'input.json', {'evidence_root': str(store.root), 'registry_context': {}})
    write_artifacts()  # Integrity hashes alone cannot certify a nonexistent job.
    with pytest.raises(ValueError, match='durable outcome'):
        read_acquisition_batch(operation, store=store)


@pytest.mark.parametrize('failed_parse',[False,True])
def test_expiry_during_final_graph_sql_rolls_back_unaccepted_children_and_expansion(retained,clock,monkeypatch,failed_parse):
    import cdr_terms.graph as graph_module
    store,_,_=retained
    root,_,_=start(retained,'<a href="/independent-protocol-child">Protocol link only</a>')
    tables=('document_graph_nodes','document_graph_edges','document_graph_expansions','acquisition_requests')
    before={table:store.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in tables}
    if failed_parse:
        def fail(*args,**kwargs):raise OSError('Protocol parse failure')
        monkeypatch.setattr(graph_module,'extract_version',fail)
    observed=[]
    def trace(sql):
        if 'INSERT' in sql and 'INTO document_graph_expansions' in sql and not observed:
            observed.append({'sql':sql,'in_transaction':store.db.in_transaction,'before_clock':clock.now()})
            clock.advance(181)
    store.db.set_trace_callback(trace)
    try:
        with pytest.raises(ValueError,match='Stale processing'):
            ProcessingQueue(store).process_one({})
    finally:
        # Python3.10 sqlite's set_authorizer(None) bug is unrelated; this trace
        # callback API can be cleared normally without installing a new runtime.
        store.db.set_trace_callback(None)
    assert observed and observed[0]['in_transaction']
    after={table:store.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in tables}
    expansion=DocumentGraph(store).inventory(root)['nodes'][0]['expansion']
    assert after==before and expansion is None, {'before':before,'after':after,'expansion':expansion,'injection':observed}


def graph_sql_counts(store):
    return {table: store.db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] for table in (
        'documents', 'document_graph_nodes', 'document_graph_edges', 'document_graph_expansions',
        'acquisition_requests', 'acquisition_events', 'acquisition_bindings')}


@pytest.mark.parametrize('failed_parse', [False, True])
@pytest.mark.parametrize('boundary', ['source_validation', 'expansion_readback'])
def test_graph_post_write_validation_cannot_cross_lease_expiry(retained, clock, monkeypatch, failed_parse, boundary):
    import cdr_terms.graph as graph_module
    store, _, _ = retained
    start(retained, '<a href="/protocol-late-validation">Protocol link only</a>')
    before = graph_sql_counts(store)
    if failed_parse:
        def fail(*args, **kwargs):
            raise OSError('Protocol retained parser error')
        monkeypatch.setattr(graph_module, 'extract_version', fail)
    observed = []
    original = ProcessingQueue.validate
    def expire_after_validation(queue, task, *, expanded=False):
        result = original(queue, task, expanded=expanded)
        if expanded and boundary == 'source_validation' and not observed:
            observed.append(store.db.in_transaction)
            clock.advance(181)
        return result
    def trace(sql):
        if boundary == 'expansion_readback' and 'SELECT * FROM document_graph_expansions WHERE node_id=' in sql and not observed:
            observed.append(store.db.in_transaction)
            clock.advance(181)
    monkeypatch.setattr(ProcessingQueue, 'validate', expire_after_validation)
    store.db.set_trace_callback(trace)
    try:
        with pytest.raises(ProcessingGuardFailure, match='Stale processing'):
            ProcessingQueue(store).process_one({})
    finally:
        store.db.set_trace_callback(None)
    assert observed == [True]
    assert graph_sql_counts(store) == before


@pytest.mark.parametrize('field', ['node_id', 'check_id', 'extraction_id', 'observed_at', 'reason', 'receipt_json', 'extra'])
def test_post_write_guard_binds_every_exact_expansion_field(retained, clock, monkeypatch, field):
    store, _, _ = retained
    start(retained, '<a href="/protocol-exact-expansion">Protocol link only</a>')
    before = graph_sql_counts(store)
    original = ProcessingQueue.assert_expansion
    def corrupt_expected(queue, task, expected):
        assert store.db.in_transaction
        changed = {**expected, field: 'protocol altered expected field'}
        return original(queue, task, changed)
    monkeypatch.setattr(ProcessingQueue, 'assert_expansion', corrupt_expected)
    with pytest.raises(ProcessingGuardFailure, match='expansion_identity_mismatch'):
        ProcessingQueue(store).process_one({})
    assert graph_sql_counts(store) == before


def test_post_write_guard_rejects_source_scope_loss(retained, clock, monkeypatch):
    store, _, _ = retained
    start(retained, '<a href="/protocol-source-loss">Protocol link only</a>')
    before = graph_sql_counts(store)
    original = ProcessingQueue.validate
    def changed_source(queue, task, *, expanded=False):
        result = original(queue, task, expanded=expanded)
        if expanded:
            # Guard negative control: source validation must propagate refusal
            # while every frontier write is still uncommitted.
            assert store.db.in_transaction
            raise ValueError('protocol graph source superseded')
        return result
    monkeypatch.setattr(ProcessingQueue, 'validate', changed_source)
    with pytest.raises(ProcessingGuardFailure, match='source superseded'):
        ProcessingQueue(store).process_one({})
    assert graph_sql_counts(store) == before


@pytest.mark.parametrize('failed_parse', [False, True])
def test_live_guard_accepts_pending_then_only_its_new_exact_expansion(retained, clock, monkeypatch, failed_parse):
    import cdr_terms.graph as graph_module
    store, _, _ = retained
    start(retained, '<a href="/protocol-live-expansion">Protocol link only</a>')
    if failed_parse:
        def fail(*args, **kwargs):
            raise OSError('Protocol retained parser error')
        monkeypatch.setattr(graph_module, 'extract_version', fail)
    original = ProcessingQueue.assert_lease
    boundaries = []
    def capture_guard(queue, task, *, observation_ids=None, expanded=False):
        boundaries.append((expanded, store.db.in_transaction))
        return original(queue, task, observation_ids=observation_ids, expanded=expanded)
    monkeypatch.setattr(ProcessingQueue, 'assert_lease', capture_guard)
    result = ProcessingQueue(store).process_one({})
    assert boundaries == [(False, True), (True, True)]
    assert result['status'] == 'complete'
    ProcessingQueue(store).validate_receipt(result)
    assert store.db.execute('SELECT COUNT(*) FROM document_graph_expansions').fetchone()[0] == 1
