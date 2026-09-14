"""Private protocol probes. Actual queues/transport guards; no network/business acceptance."""
import json
from pathlib import Path
import pytest
from cdr_terms import acquisition as http, acquisition_batch as batch
from cdr_terms.acquisitions_queue import AcquisitionQueue
from cdr_terms.acquisition_processing import ProcessingQueue
from cdr_terms.graph import DocumentGraph
from cdr_terms.identity import digest
from cdr_terms.store import EvidenceStore
from tests.test_cdr_terms_graph import retained, start, URL
from tests.test_cdr_terms_acquisition_batch import clock, BOM, add_source


def drain_siblings(store, queue, clock):
    while True:
        request = queue.claim()
        if request is None:
            break
        capture(store, queue, request, clock)

def capture(store, queue, request, clock, body=None, defer=False):
    check_id = digest([request['request_id'], request['lease_id']])
    store.record_check(document_id=request['document_id'], check_id=check_id,
                       checked_at=clock.now(), status='fetched', body=body or BOM.read_bytes(),
                       media_type='application/json', metadata={'final_url':'https://www.bankofmelbourne.com.au/'})
    queue.finish(request, check_id, defer_processing=defer)
    return dict(store.db.execute('SELECT * FROM acquisition_checks WHERE check_id=?',(check_id,)).fetchone())

def test_four_guard_yields_must_not_exhaust_current_request(retained, clock, monkeypatch):
    store, _, queue = retained
    def forbidden(*args, **kwargs):
        pytest.fail('An operational yield must never reach a connection')
    monkeypatch.setattr(http, '_connection', forbidden)
    request = queue.claim()
    target = request['request_id']
    observed=[]
    for attempt in range(4):
        if attempt:
            clock.advance(4000)
            request = queue.claim()
            assert request['request_id']==target
        item=batch._fetch_one(store, queue, request, clock.elapsed+105,
                             lambda:'scheduled_or_manual_ingest_active', 16*1024**2)
        event=dict(store.db.execute('SELECT * FROM acquisition_events WHERE request_id=? ORDER BY sequence DESC LIMIT 1',(target,)).fetchone())
        observed.append({'item':item,'event':event})
        # Other real references are completed while target remains in backoff.
        while True:
            sibling=queue.claim()
            if sibling is None: break
            assert sibling['request_id']!=target
            capture(store,queue,sibling,clock)
    assert all(x['item']['error']=='operational_guard:scheduled_or_manual_ingest_active' for x in observed)
    assert observed[-1]['event']['status']!='blocked', 'Four no-network scheduling yields exhausted the acquisition'
    assert queue.charged_attempts(target) == 0


@pytest.mark.parametrize('variant', ['failed_string', 'failed_with_marker', 'missing_marker', 'wrong_marker', 'wrong_check'])
def test_failed_or_malformed_deferrals_still_count(retained, clock, variant):
    store, _, queue = retained
    request = queue.claim()
    target = request['request_id']
    for attempt in range(4):
        if attempt:
            clock.advance(4000)
            request = queue.claim()
            assert request['request_id'] == target
        check_id = digest([target, request['lease_id']]) if variant != 'wrong_check' else digest(['manual', request['lease_id']])
        error = 'operational_guard:ingest_active'
        metadata = http.deferral_metadata(request['document_id'], check_id, error)
        if variant == 'missing_marker': metadata = {}
        if variant == 'wrong_marker': metadata['extra'] = True
        store.record_check(document_id=request['document_id'], check_id=check_id, checked_at=clock.now(),
                           status='failed' if variant.startswith('failed') else 'deferred', error_code=error,
                           metadata=metadata if variant != 'failed_string' else {})
        queue.finish(request, check_id)
        drain_siblings(store, queue, clock)
    assert queue.charged_attempts(target) == 4
    assert store.db.execute('SELECT status FROM acquisition_events WHERE request_id=? ORDER BY sequence DESC LIMIT 1',
                            (target,)).fetchone()[0] == 'blocked'


def test_guard_yields_do_not_forgive_later_real_failures(retained, clock, monkeypatch):
    store, _, queue = retained
    request = queue.claim()
    target = request['request_id']
    batch._fetch_one(store, queue, request, clock.elapsed + 105, lambda: 'ingest_active', 1024)
    assert queue.charged_attempts(target) == 0
    drain_siblings(store, queue, clock)
    def failed(*args, **kwargs):
        raise http.FetchFailure('transport_error')
    monkeypatch.setattr(http, 'fetch_document', failed)
    for attempt in range(4):
        clock.advance(4000)
        request = queue.claim()
        assert request['request_id'] == target
        batch._fetch_one(store, queue, request, clock.elapsed + 105, lambda: None, 1024)
        assert queue.charged_attempts(target) == attempt + 1
    assert queue.next_due() is None


def test_unacknowledged_guard_check_and_crashes_keep_attempt_budget(retained, clock):
    store, _, queue = retained
    target = queue.next_due()['request_id']
    for attempt in range(4):
        request = queue.claim(lease_seconds=1)
        assert request['request_id'] == target
        # Check recorded, but process dies before queue.finish acknowledges it.
        http.acquire_document(store, request['document_id'], check_id=digest([target, request['lease_id']]),
                              policy=http.FetchPolicy(request_guard=lambda: 'ingest_active'))
        clock.advance(2)
        drain_siblings(store, queue, clock)
        assert queue.charged_attempts(target) == attempt + 1
        clock.advance(4000)
    assert queue.next_due() is None


def test_late_changed_disposition_cannot_forgive_terminal_failure(retained, clock):
    from cdr_terms.acquisitions_queue import DEFERRAL_EVENT
    store, _, queue = retained
    request = queue.claim()
    target, check = request['request_id'], digest([request['request_id'], request['lease_id']])
    http.acquire_document(store, request['document_id'], check_id=check,
                          policy=http.FetchPolicy(request_guard=lambda: 'ingest_active'))
    queue.finish(request, check, processing_error='actual_processing_failure')
    assert queue.charged_attempts(target) == 1
    # Even a manually appended ambiguous acknowledgement cannot rewrite cause.
    with store.db:
        queue._event(target, 'retry_wait', clock.now(), retry_after=clock.now(),
                     lease_id=request['lease_id'], check_id=check, error_code=DEFERRAL_EVENT)
    assert queue.charged_attempts(target) == 1

@pytest.mark.parametrize('boundary',['guard','deadline'])
def test_manual_observation_preserves_caller_protection(retained, clock, monkeypatch, boundary):
    store, observation, _ = retained
    reached=[]
    def connection(url, policy, remaining):
        reached.append({'url':url,'remaining':remaining,'guard_present':policy.request_guard is not None,
                        'deadline':policy.deadline_monotonic})
        raise http.FetchFailure('protocol_connection_blocked_no_network')
    monkeypatch.setattr(http,'_connection',connection)
    policy=http.FetchPolicy(request_guard=(lambda:'ingest_active') if boundary=='guard' else None,
                            deadline_monotonic=clock.elapsed-1 if boundary=='deadline' else None)
    value=http.acquire_observation(store,observation,check_prefix='private-'+boundary,
                                   max_documents=1, max_seconds=20, policy=policy)
    assert not reached, 'acquire_observation discarded caller protection before actual fetch'

@pytest.mark.parametrize('boundary',['guard','deadline'])
def test_direct_fetch_enforces_same_caller_protection(clock, monkeypatch, boundary):
    monkeypatch.setattr(http,'_connection',lambda *a,**k:pytest.fail('direct fetch must stop'))
    policy=http.FetchPolicy(request_guard=(lambda:'ingest_active') if boundary=='guard' else None,
                            deadline_monotonic=clock.elapsed-1 if boundary=='deadline' else None)
    with pytest.raises(http.FetchFailure,match='operational_guard' if boundary=='guard' else 'request_deadline'):
        http.fetch_document('https://www.bankofmelbourne.com.au/',policy=policy)


@pytest.mark.parametrize('caller_deadline', [None, 3, 100])
def test_manual_fetch_clips_shared_deadline_without_losing_fields(retained, clock, monkeypatch, caller_deadline):
    store, observation, _ = retained
    forwarded = []
    guard = lambda: None
    def replay(url, **kwargs):
        policy = kwargs['policy']
        forwarded.append(policy)
        clock.advance(2)
        return {'status': 'fetched', 'body': BOM.read_bytes(), 'media_type': 'application/json'}
    monkeypatch.setattr(http, 'fetch_document', replay)
    policy = http.FetchPolicy(max_bytes=65536, timeout_seconds=17, max_redirects=2,
        allowed_hosts=frozenset({'www.bankofmelbourne.com.au'}), allow_http=True,
        request_guard=guard, deadline_monotonic=caller_deadline)
    http.acquire_observation(store, observation, check_prefix='fields', max_documents=3, max_seconds=5, policy=policy)
    expected = min(5, caller_deadline) if caller_deadline is not None else 5
    assert len(forwarded) == (2 if expected == 3 else 3)
    for index, item in enumerate(forwarded):
        assert item.request_guard is guard and item.deadline_monotonic == expected
        assert item.allowed_hosts == policy.allowed_hosts and item.allow_http and item.max_redirects == 2
        assert item.timeout_seconds == expected - 2 * index and item.max_bytes == policy.max_bytes


@pytest.mark.parametrize('value', [float('nan'), float('inf'), True, '5'])
def test_invalid_caller_deadlines_are_refused(value):
    with pytest.raises(ValueError, match='finite'):
        http.FetchPolicy(deadline_monotonic=value)

@pytest.mark.parametrize('legacy_generic', [False, True])
def test_graph_child_does_not_consume_generic_then_node_processing_slots(retained,clock,monkeypatch,legacy_generic):
    store, _, queue=retained
    root, _, _=start(retained,'<a href="/private-protocol-child">Child</a>')
    graph=DocumentGraph(store)
    graph.advance_one()
    child=dict(store.db.execute('SELECT * FROM document_graph_nodes WHERE root_id=? AND depth=1',(root,)).fetchone())
    while True:
        request=queue.claim()
        assert request
        if request['request_id']==child['request_id']: break
        capture(store,queue,request,clock)
    def replay(url,**kwargs):
        assert kwargs['policy'].request_guard() is None
        return {'status':'fetched','http_status':200,'body':b'<p>Protocol leaf.</p>',
                'media_type':'text/html','metadata':{'final_url':url}}
    monkeypatch.setattr(http,'fetch_document',replay)
    batch._fetch_one(store,queue,request,clock.elapsed+105,lambda:None,16*1024**2)
    clock.advance(1)
    processing=ProcessingQueue(store)
    if legacy_generic:
        with store.db:
            legacy = processing.enqueue(request['request_id'], digest([request['request_id'], request['lease_id']]), now=clock.now())
    first=processing.process_one({})
    second=processing.process_one({})
    rows=[dict(x) for x in store.db.execute('SELECT * FROM acquisition_processing WHERE request_id=?',(child['request_id'],))]
    assert first['status']=='complete' and first['node_id']==child['node_id'] and 'graph' in first['outcome']
    assert second is None
    assert len(rows)==(2 if legacy_generic else 1)
    if legacy_generic:
        event = store.db.execute('SELECT * FROM acquisition_processing_events WHERE processing_id=? ORDER BY sequence DESC LIMIT 1', (legacy,)).fetchone()
        assert event['status'] == 'blocked' and event['lease_id'] is None
        assert json.loads(event['receipt_json']) == {'reason':'redundant_graph_only_processing','legal_completeness':'unknown'}

def test_changed_current_capture_precedes_older_unchanged_processing(retained,clock):
    store,_,queue=retained
    while True:
        req=queue.claim()
        if req is None: break
        capture(store,queue,req,clock)
    clock.advance(1)
    add_source(store,ingest='current-next-day',observed='2026-09-08T00:00:00Z')
    parser=ProcessingQueue(store)
    checks=[]
    # Same current capture, three exact document requests. Last changes bytes.
    for i in range(3):
        req=queue.claim()
        assert req
        check=capture(store,queue,req,clock,body=BOM.read_bytes()+(b'\n' if i==2 else b''),defer=True)
        checks.append({'request_id':req['request_id'],'check_id':check['check_id'],
                       'analysis_priority':parser.analysis_priority(req,check)})
        clock.advance(1)
    assert [x['analysis_priority'] for x in checks]==[1,1,0]
    due=parser.due()
    actual=parser.process_one({})
    assert actual['status']=='complete' and actual['outcome']['analysis_job_id']
    assert actual['check_id']==checks[-1]['check_id'], 'Changed current evidence is queued behind unchanged parser work'


def graph_with_older_unchanged_direct(retained, clock, monkeypatch, state):
    store, _, queue = retained
    graph, retry, root = DocumentGraph(store), None, None
    while queue.next_due():
        request = queue.claim()
        url = store.db.execute('SELECT source_url FROM documents WHERE document_id=?', (request['document_id'],)).fetchone()[0]
        chosen = url == URL
        cid = digest([request['request_id'], request['lease_id']])
        store.record_check(document_id=request['document_id'], check_id=cid, checked_at=clock.now(), status='fetched',
            body=b'<a href="/private-priority-child">child</a>' if chosen else BOM.read_bytes(),
            media_type='text/html' if chosen else 'application/json', metadata={'final_url':url})
        check = dict(store.db.execute('SELECT * FROM acquisition_checks WHERE check_id=?', (cid,)).fetchone())
        if chosen:
            root = graph.seed(request, check)
        queue.finish(request, cid, processing_error='protocol_initial_retry' if not chosen and retry is None else None)
        if not chosen and retry is None:
            retry = request['request_id']
    assert root and retry
    graph.advance_one()
    child = dict(store.db.execute('SELECT * FROM document_graph_nodes WHERE root_id=? AND depth=1', (root,)).fetchone())
    clock.advance(4000)
    request = queue.claim()
    assert request['request_id'] == retry
    direct = capture(store, queue, request, clock, defer=True)
    parser = ProcessingQueue(store)
    assert parser.analysis_priority(request, direct) == 1
    clock.advance(1)
    request = queue.claim()
    assert request['request_id'] == child['request_id']
    body = b'<p>Protocol graph leaf.</p>'
    if state != 'first':
        # Prior accepted request for this document, distinct from the node's
        # immutable first-check pin. This is protocol metadata, not bank terms.
        from cdr_terms.acquisitions_queue import _after
        prior = {**request, 'request_id':digest(['prior-graph-protocol', request['request_id']]),
                 'lease_id':digest(['prior-graph-lease', request['request_id']]), 'ingest_id':'protocol-prior-capture'}
        source = json.loads(BOM.read_bytes())
        store.observe(provider=source['data']['brand'], product_key='Bank of Melbourne|BOMHLBasic',
            record=source, source_bytes=BOM.read_bytes(), observed_at='2026-09-06T00:00:00Z', ingest_id=prior['ingest_id'])
        capture_receipt = store.put_blob(b'isolated prior capture finalization boundary')
        with store.db:
            store.db.execute('INSERT INTO ingest_captures VALUES (?,?,?,1)', (prior['ingest_id'], capture_receipt, clock.now()))
            store.db.execute('INSERT INTO acquisition_requests VALUES (?,?,?,?,?)',
                (prior['request_id'], prior['document_id'], prior['ingest_id'], clock.now(), prior['priority']))
            queue._event(prior['request_id'], 'running', clock.now(), lease_id=prior['lease_id'], expiry=_after(clock.now(), 180))
        cid = digest([prior['request_id'], prior['lease_id']])
        store.record_check(document_id=request['document_id'], check_id=cid, checked_at=clock.now(), status='fetched',
            body=body if state == 'unchanged' else body+b'\n', media_type='text/html')
        queue.finish(prior, cid)
        clock.advance(1)
    monkeypatch.setattr(http, 'fetch_document', lambda url, **kwargs: {
        'status':'fetched', 'body':body, 'media_type':'text/html', 'metadata':{'final_url':url}})
    item = batch._fetch_one(store, queue, request, clock.elapsed+105, lambda:None, 16*1024**2)
    check = dict(store.db.execute('SELECT * FROM acquisition_checks WHERE check_id=?', (item['check_id'],)).fetchone())
    assert parser.analysis_priority(request, check) == (1 if state == 'unchanged' else 0)
    return parser, child, check, direct


@pytest.mark.parametrize('state', ['first', 'changed', 'unchanged'])
@pytest.mark.parametrize('migration', [False, True], ids=['new-enqueue', 'bounded-legacy-backfill'])
def test_actual_graph_capture_priority_and_process_one_order(retained, clock, monkeypatch, state, migration):
    parser, child, check, direct = graph_with_older_unchanged_direct(retained, clock, monkeypatch, state)
    store = retained[0]
    if migration:
        identity = digest([child['request_id'], check['check_id'], child['node_id']])
        with store.db:
            parser.enqueue(child['request_id'], check['check_id'], node_id=child['node_id'], now=clock.now())
            # Disposable legacy table fixture: only the derived caches are
            # absent; authoritative task/event/node/check bytes remain intact.
            store.db.execute('DELETE FROM acquisition_processing_schedule')
            store.db.execute("UPDATE acquisition_processing_schedule_migration SET complete=0,after_processing_id=''")
        evidence = [tuple(row) for row in store.db.execute('SELECT * FROM acquisition_processing_events ORDER BY sequence')]
        with store.db:
            parser._backfill_schedule()
        assert [tuple(row) for row in store.db.execute('SELECT * FROM acquisition_processing_events ORDER BY sequence')] == evidence
        assert store.db.execute('SELECT COUNT(*) FROM acquisition_processing_schedule').fetchone()[0] <= 64
        row = store.db.execute('SELECT * FROM acquisition_processing_schedule WHERE processing_id=?', (identity,)).fetchone()
        assert row['priority'] == (1 if state == 'unchanged' else 0), row['evidence_json']
    result = parser.process_one({})
    expected = direct if state == 'unchanged' else check
    assert result['status'] == 'complete' and result['check_id'] == expected['check_id']
    if state != 'unchanged':
        assert result['node_id'] == child['node_id']
        assert result['outcome']['graph']['node_id'] == child['node_id']
    parser.validate_receipt(result)
