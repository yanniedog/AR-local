"""Retained CDR identities/URLs; transport replays are local protocol evidence only.

No HTTP occurs. Replayed CDR bytes exercise capture and budgets, not the content
or legal meaning of the linked document. Clock/crash injections are protocol tests.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cdr_terms import acquisition as http
from cdr_terms import acquisition_batch as batch
from cdr_terms.acquisition_processing import ProcessingQueue
from cdr_terms.acquisitions_queue import AcquisitionQueue
from cdr_terms.identity import digest, timestamp
from cdr_terms.store import EvidenceStore

FIXTURES = Path(__file__).parent / 'fixtures/cdr-canary-2026-09-07'
BOM = FIXTURES / 'Bank of Melbourne-null-detail.json'
OBSERVED = '2026-09-07T00:00:00Z'


class Clock:
    elapsed = 0.0
    def now(self):
        return timestamp((datetime(2026, 9, 14, 10, tzinfo=timezone.utc) + timedelta(seconds=self.elapsed)).isoformat())
    def advance(self, seconds):
        self.elapsed += seconds


@pytest.fixture
def clock(monkeypatch):
    value = Clock()
    monkeypatch.setattr(batch.time, 'monotonic', lambda: value.elapsed)
    for module in ('acquisition', 'acquisition_batch', 'acquisitions_queue', 'acquisition_processing', 'graph'):
        monkeypatch.setattr('cdr_terms.' + module + '.utc_now', value.now)
    monkeypatch.setattr('tests.test_cdr_terms_graph.utc_now', value.now)
    return value


def add_source(store, path=BOM, *, ingest='retained-september7', observed=OBSERVED, completed=True):
    body = path.read_bytes()
    source = json.loads(body)
    key = source['data']['brand'] + '|' + source['data']['productId']
    observation = store.observe(provider=source['data']['brand'], product_key=key, record=source,
        source_bytes=body, observed_at=observed, ingest_id=ingest)
    AcquisitionQueue(store).enqueue(observation, ingest_id=ingest, now=observed)
    with store.db:
        store.db.execute('INSERT OR IGNORE INTO ingest_capture_attempts VALUES (?,?,?,?)',
                          (ingest, timestamp(observed), timestamp(observed), '{}'))
        if completed:
            store.db.execute('INSERT OR IGNORE INTO ingest_captures VALUES (?,?,?,1)',
                              (ingest, digest(['isolated-finalization', ingest]), timestamp(observed)))
    return observation


@pytest.fixture
def retained(tmp_path, clock):
    with EvidenceStore(tmp_path / 'private') as store:
        for path in sorted(FIXTURES.glob('*-null-detail.json')):
            add_source(store, path)
        assert store.db.execute('SELECT COUNT(*) FROM acquisition_requests').fetchone()[0] == 24
        yield store


def replay(monkeypatch, clock, *, elapsed=0):
    calls = []
    def fetch(url, **kwargs):
        policy = kwargs['policy']
        assert policy.allowed_hosts and policy.max_redirects == 5 and not policy.allow_http
        assert policy.request_guard() is None
        calls.append((url, policy))
        clock.advance(min(elapsed, policy.timeout_seconds))
        return {'status': 'fetched', 'http_status': 200, 'body': BOM.read_bytes(),
                'media_type': 'application/json', 'metadata': {'final_url': url}}
    monkeypatch.setattr(http, 'fetch_document', fetch)
    return calls


def run(store, clock, *, guard=lambda: None, **kwargs):
    return batch.run_batch(store, registry_context={}, deadline=clock.elapsed + 105, guard=guard, **kwargs)


def test_24_retained_urls_capture_sequentially_without_synchronous_parser(retained, clock, monkeypatch):
    calls = replay(monkeypatch, clock)
    monkeypatch.setattr('cdr_terms.acquisitions_queue.enqueue_interpretation', lambda *a, **k: pytest.fail('capture cannot parse'))
    value = run(retained, clock)
    assert len(calls) == value['attempts'] == 24 and len({url for url, _ in calls}) == 24
    assert value['charged_bytes'] == value['actual_body_bytes'] == 24 * len(BOM.read_bytes())
    assert value['remaining']['processing_pending'] == 24 and value['remaining']['due'] == 0
    assert value['processing'] is None and value['legal_completeness'] == 'unknown'
    assert retained.db.execute('SELECT COUNT(*) FROM extractions').fetchone()[0] == 0
    assert retained.db.execute('SELECT COUNT(*) FROM analysis_jobs').fetchone()[0] == 0
    assert all(item['extraction_status'] == 'pending' for item in value['items'])
    batch.validate_batch_receipt(value)
    batch.validate_batch_evidence(retained, value)


def test_attempt_byte_and_remaining_time_limits(retained, clock, monkeypatch):
    calls = replay(monkeypatch, clock, elapsed=30)
    value = run(retained, clock)
    assert len(calls) == 4 and clock.elapsed == 105 and value['stop_reason'] == 'admission_deadline'
    assert [policy.timeout_seconds for _, policy in calls] == [30, 30, 30, 15]
    assert all(policy.deadline_monotonic == 105 for _, policy in calls)
    # Processing is skipped here to isolate the next cycle's byte admission.
    monkeypatch.setattr(ProcessingQueue, 'process_one', lambda *_: None)
    calls.clear()
    value = run(retained, clock, limits=batch.BatchLimits(body_bytes=len(BOM.read_bytes())))
    assert len(calls) == 1 and value['stop_reason'] == 'body_byte_budget'
    assert calls[0][1].max_bytes == len(BOM.read_bytes())


def test_unknown_partial_transfers_charge_reserved_allowance(retained, clock, monkeypatch):
    calls = []
    def partial(*args, **kwargs):
        calls.append(kwargs['policy'].max_bytes)
        raise http.FetchFailure('transport_error')
    monkeypatch.setattr(http, 'fetch_document', partial)
    value = run(retained, clock)
    assert calls == [16 * 1024**2] * 4
    assert value['charged_bytes'] == 64 * 1024**2 and value['actual_body_bytes'] == 0
    assert value['stop_reason'] == 'body_byte_budget'
    assert all(item['byte_accounting'] == 'reserved_unknown_partial_transfer' for item in value['items'])
    assert value['remaining']['retry_wait'] == 4 and value['remaining']['processing_pending'] == 0


def test_dns_timeout_stops_before_another_resolver_is_started(retained, clock, monkeypatch):
    calls = []
    def timeout(*args, **kwargs):
        calls.append(args)
        raise http.FetchFailure('dns_deadline')
    monkeypatch.setattr(http, 'fetch_document', timeout)
    value = run(retained, clock)
    assert len(calls) == 1 and value['stop_reason'] == 'dns_deadline'


def test_guard_change_between_items_preserves_completed_capture(retained, clock, monkeypatch):
    calls = replay(monkeypatch, clock)
    def guard():
        return 'scheduled_or_manual_ingest_active' if calls else None
    value = run(retained, clock, guard=guard)
    assert len(calls) == 1 and value['stop_reason'] == 'scheduled_or_manual_ingest_active'
    assert value['remaining']['processing_pending'] == 1 and value['remaining']['due'] == 23


def test_no_due_work_has_no_guard_network_or_parser(tmp_path, clock, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('idle means no host probe, network or parser')
    monkeypatch.setattr(http, 'fetch_document', forbidden)
    monkeypatch.setattr(ProcessingQueue, 'process_one', forbidden)
    with EvidenceStore(tmp_path / 'empty') as store:
        value = run(store, clock, guard=forbidden)
        assert value['result'] == 'NO_WORK' and not value['network_called']


def test_receipt_tampering_and_overbound_configuration_refused(retained, clock, monkeypatch):
    replay(monkeypatch, clock)
    value = run(retained, clock, limits=batch.BatchLimits(attempts=1))
    value['items'][0]['check_id'] = 'changed'
    with pytest.raises(ValueError, match='receipt'):
        batch.validate_batch_receipt(value)
    # Even a recomputed artifact hash cannot create accepted source evidence.
    with pytest.raises(ValueError, match='accepted acquisition'):
        batch.validate_batch_evidence(retained, value)
    for values in ({'attempts': 33}, {'body_bytes': 64 * 1024**2 + 1}, {'maintenance': 129}, {'attempts': True}):
        with pytest.raises(ValueError, match='bounds'):
            batch.BatchLimits(**values)


def test_processing_crash_lease_backoff_and_four_attempt_exhaustion_allows_siblings(retained, clock, monkeypatch):
    calls = replay(monkeypatch, clock)
    run(retained, clock, limits=batch.BatchLimits(attempts=1))
    parser = ProcessingQueue(retained)
    poison = parser.due()['processing_id']
    original = parser.validate
    # An abrupt process loss happens AFTER a committed processing lease.
    def crash(*args, **kwargs):
        raise SystemExit('isolated poison parser process death')
    monkeypatch.setattr('cdr_terms.acquisitions_queue.enqueue_interpretation', crash)
    with pytest.raises(SystemExit):
        run(retained, clock)
    assert retained.db.execute('SELECT status FROM acquisition_processing_events WHERE processing_id=? ORDER BY sequence DESC LIMIT 1', (poison,)).fetchone()[0] == 'running'
    # First restart recovers the lease into future backoff, then fetches siblings.
    clock.advance(181)
    calls.clear()
    value = run(retained, clock)
    assert len(calls) == 23 and value['remaining']['processing_pending'] >= 24
    # Claim exactly the poison again after other work is explicitly dispositioned
    # as a protocol control. Its four-crash budget cannot reset after reopening.
    with retained.db:
        for row in retained.db.execute('SELECT processing_id FROM acquisition_processing WHERE processing_id!=?', (poison,)).fetchall():
            parser._event(row[0], 'blocked', clock.now(), {'reason': 'isolated sibling control'})
    for attempt in range(2, 5):
        clock.advance(4000)
        with pytest.raises(SystemExit):
            parser.process_one({})
        clock.advance(181)
        parser.claim()  # expired owner becomes backoff/exhausted, never immediate retry
    event = retained.db.execute('SELECT * FROM acquisition_processing_events WHERE processing_id=? ORDER BY sequence DESC LIMIT 1', (poison,)).fetchone()
    assert event['status'] == 'blocked' and json.loads(event['receipt_json'])['attempts'] == 4
    assert json.loads(event['receipt_json'])['extraction_completeness'] == 'unknown'


def test_unfinished_new_capture_cannot_obsolete_old_and_complete_replacement_has_proof(tmp_path, clock, monkeypatch):
    with EvidenceStore(tmp_path / 'derived') as store:
        old = add_source(store)
        new = add_source(store, ingest='next-retained-capture', observed='2026-09-08T00:00:00Z', completed=False)
        request = AcquisitionQueue(store).next_due()
        assert batch.request_scope(store, request)[0] == [old]
        with store.db:
            store.db.execute('INSERT INTO ingest_captures VALUES (?,?,?,1)', ('next-retained-capture', digest(['accepted-new']), clock.now()))
        _, _, proof = batch.request_scope(store, request)
        assert proof['obsolete'] and proof['replacements'][0]['replacement_observation_id'] == new
        assert batch.dispose_unrunnable(store, request, proof)
        assert store.db.execute('SELECT COUNT(*) FROM acquisition_checks WHERE document_id=?', (request['document_id'],)).fetchone()[0] == 0
        assert store.db.execute('SELECT COUNT(*) FROM acquisition_bindings WHERE observation_id=?', (old,)).fetchone()[0] == 3


def test_ties_and_historical_priority_never_receive_obsolete_disposition(tmp_path, clock):
    with EvidenceStore(tmp_path / 'derived') as store:
        add_source(store)
        add_source(store, ingest='tied-capture')
        request = AcquisitionQueue(store).next_due()
        proof = batch.request_scope(store, request)[2]
        assert proof['obsolete'] is False and proof['reason'] == 'source_scope_unresolved'
        # Protocol-only priority mutation of the selected dict cannot invent an
        # obsolete historical disposition; actual historical target jobs are separate.
        assert batch.request_scope(store, {**request, 'priority': 2})[2]['obsolete'] is False
