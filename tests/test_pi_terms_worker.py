"""Worker state-machine faults use retained CDR evidence; no live model calls."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import pi_terms_codex as transport
import pi_terms_worker as worker
from cdr_atomic import atomic_write_json
from cdr_terms.extraction import extract_version
from cdr_terms.identity import timestamp
from cdr_terms.queue import TermsQueue
from cdr_terms.store import EvidenceStore
from tests.test_cdr_quality_resources import receipt

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 14, 1, 0, tzinfo=timezone.utc)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    evidence = tmp_path / 'evidence'
    auth = tmp_path / 'auth'
    auth.mkdir(mode=0o700)
    auth_file = auth / 'auth.json'
    auth_file.write_text(json.dumps({'auth_mode': 'chatgpt', 'tokens': {'access_token': 'infrastructure-test-only'}}))
    auth_file.chmod(0o600)
    executable = tmp_path / 'codex'
    executable.write_text('Never executed: tests stub the entire supervisor boundary.')
    body = (ROOT / 'tests/fixtures/cdr-canary-2026-09-07/Bank of Melbourne-null-detail.json').read_bytes()
    source = json.loads(body)
    with EvidenceStore(evidence) as store:
        observation = store.observe(provider=source['data']['brand'], product_key='Bank of Melbourne|' + source['data']['productId'],
                                    record=source, source_bytes=body, observed_at='2026-09-07T00:00:00Z', ingest_id='retained-september7')
        row = store.db.execute('SELECT document_id FROM documents WHERE source_url=?', (source['links']['self'],)).fetchone()
        extraction = extract_version(store, store.last_success(row[0])['document_version_id'])
        queue = TermsQueue(store)
        job_id = queue.enqueue(extraction, {'product_keys': ['Bank of Melbourne|' + source['data']['productId']]})
        job = store.db.execute('SELECT * FROM analysis_jobs WHERE job_id=?', (job_id,)).fetchone()
        output = {'schema_version': 1, 'extraction_id': extraction, 'context_sha256': job['context_sha256'],
                  'clauses': [], 'terms': [], 'unresolved': ['Protocol test, not a complete financial interpretation']}
    monkeypatch.setattr(worker, 'utc_now', lambda: NOW)
    monkeypatch.setattr(worker, 'admission', lambda *_: None)
    # Queue uses its own real clock; tests exercising leases must align them.
    import cdr_terms.queue as queue_module
    monkeypatch.setattr(queue_module, 'utc_now', lambda: NOW.isoformat())
    monkeypatch.setattr(worker, 'supervise', lambda *_a, **_k: pytest.fail('unexpected interpreter call'))
    return evidence, auth, executable, job_id, output, observation


def invoke(setup):
    evidence, auth, executable, *_ = setup
    return worker.run_one(ROOT, evidence, auth, executable)


def latest(setup):
    with EvidenceStore(setup[0]) as store:
        return dict(store.db.execute('SELECT * FROM job_events WHERE job_id=? ORDER BY sequence DESC LIMIT 1', (setup[3],)).fetchone())


def simulate(monkeypatch, setup, outcome='STAGING_ONLY', **fields):
    calls = []
    def supervisor(command, output, limits, **kwargs):
        calls.append(command)
        operation = output.parent
        transport.write_receipt(operation / 'result.json', setup[4])
        row = {'schema_version': 1, 'started_at': NOW.isoformat(), 'finished_at': NOW.isoformat(),
               'result': outcome, 'codex_called': True, **transport.input_hashes(operation), **fields}
        if outcome == 'STAGING_ONLY':
            row['result_sha256'] = transport.file_hash(operation / 'result.json', transport.MAX_RESULT_BYTES)
        transport.write_receipt(operation / 'transport.json', row)
        result = receipt()
        result['workload_started'] = True
        return result
    monkeypatch.setattr(worker, 'supervise', supervisor)
    return calls


def test_success_stages_only_and_clears_backoff(setup, monkeypatch):
    calls = simulate(monkeypatch, setup)
    result = invoke(setup)
    assert result['result'] == 'STAGED' and result['publication'] == 'NOT_ATTEMPTED'
    assert result['validation'] == 'FORMAT_AND_BINDING_ONLY' and len(calls) == 1
    assert latest(setup)['status'] == 'staged'
    assert worker.read_state(setup[0]) == {'schema_version': 1, 'failures': 0}
    assert invoke(setup)['result'] == 'NO_WORK' and len(calls) == 1


def test_admission_and_missing_auth_do_not_claim_or_call(setup, monkeypatch):
    monkeypatch.setattr(worker, 'admission', lambda *_: 'production_ingest_active')
    assert invoke(setup)['codex_called'] is False
    assert latest(setup)['status'] == 'queued'
    monkeypatch.setattr(worker, 'admission', lambda *_: None)
    (setup[1] / 'auth.json').unlink()
    assert invoke(setup)['reason'] == 'saved_subscription_auth_unavailable'
    assert latest(setup)['status'] == 'queued'


def test_quota_cooldown_applies_to_other_jobs_and_survives_new_invocation(setup, monkeypatch):
    reset = NOW + timedelta(hours=5)
    calls = simulate(monkeypatch, setup, 'DEFERRED', reason='quota', reset_at=reset.isoformat())
    first = invoke(setup)
    assert first['retry_basis'] == 'structured_reset'
    assert worker.parsed_time(first['retry_after']) == reset + timedelta(minutes=1)
    with EvidenceStore(setup[0]) as store:
        job = store.db.execute('SELECT extraction_id FROM analysis_jobs WHERE job_id=?', (setup[3],)).fetchone()
        TermsQueue(store).enqueue(job[0], {'product_keys': ['second-context-protocol-only']})
    assert invoke(setup)['reason'] == 'account_cooldown' and len(calls) == 1
    # Replacing valid credentials cannot bypass a quota deadline.
    (setup[1] / 'auth.json').write_text(json.dumps({'auth_mode': 'chatgpt', 'tokens': {'access_token': 'replacement-test-only'}}))
    assert invoke(setup)['reason'] == 'account_cooldown' and len(calls) == 1


def test_auth_reconciliation_automatically_requeues_only_its_blocked_job(setup, monkeypatch):
    calls = simulate(monkeypatch, setup, 'DEFERRED', reason='authentication')
    assert invoke(setup)['result'] == 'BLOCKED'
    assert invoke(setup)['reason'] == 'account_cooldown' and len(calls) == 1
    (setup[1] / 'auth.json').write_text(json.dumps({'auth_mode': 'chatgpt', 'tokens': {'access_token': 'repaired-test-session'}}))
    calls = simulate(monkeypatch, setup)
    assert invoke(setup)['result'] == 'STAGED' and len(calls) == 1


def test_expired_auth_cooldown_retries_saved_session_once(setup, monkeypatch):
    simulate(monkeypatch, setup, 'DEFERRED', reason='authentication')
    invoke(setup)
    monkeypatch.setattr(worker, 'utc_now', lambda: NOW + timedelta(hours=2))
    import cdr_terms.queue as queue_module
    monkeypatch.setattr(queue_module, 'utc_now', lambda: (NOW + timedelta(hours=2)).isoformat())
    calls = simulate(monkeypatch, setup)
    assert invoke(setup)['result'] == 'STAGED' and len(calls) == 1


def test_resource_exception_does_not_strand_running_lease(setup, monkeypatch):
    def fail(*_a, **_kw):
        raise RuntimeError('resource admission unavailable')
    monkeypatch.setattr(worker, 'supervise', fail)
    result = invoke(setup)
    assert result['result'] == 'DEFERRED'
    assert latest(setup)['status'] == 'retry_wait'
    assert invoke(setup)['reason'] == 'account_cooldown'


def test_schema_validation_failure_is_blocked_without_publication(setup, monkeypatch):
    setup[4]['terms'] = 'malformed'
    simulate(monkeypatch, setup)
    result = invoke(setup)
    assert result['result'] == 'BLOCKED' and result['reason'] == 'invalid_staging_schema'
    assert latest(setup)['status'] == 'blocked'


def test_source_superseded_inside_save_is_not_overwritten_with_blocked(setup, monkeypatch):
    simulate(monkeypatch, setup)
    original = TermsQueue.save_staging
    def supersede(self, job_id, output, *, lease_id):
        self.event(job_id, 'superseded', lease_id=lease_id, error_code='source_version_changed')
        raise ValueError('Document changed while interpretation was running')
    monkeypatch.setattr(TermsQueue, 'save_staging', supersede)
    assert invoke(setup)['result'] == 'SUPERSEDED'
    assert latest(setup)['status'] == 'superseded'
    monkeypatch.setattr(TermsQueue, 'save_staging', original)


def test_expired_lease_recovered_even_without_queued_job(setup, monkeypatch):
    with EvidenceStore(setup[0]) as store:
        TermsQueue(store).claim(now=(NOW - timedelta(hours=1)).isoformat(), lease_seconds=1)
    calls = simulate(monkeypatch, setup)
    assert invoke(setup)['result'] == 'STAGED' and len(calls) == 1


def test_replaced_lease_is_not_changed_by_old_worker(setup):
    with EvidenceStore(setup[0]) as store:
        queue = TermsQueue(store)
        old = queue.claim(now=(NOW - timedelta(hours=1)).isoformat(), lease_seconds=1)
        new = queue.claim(now=NOW.isoformat())
        assert worker.transition_owned(queue, old, 'blocked', reason='test') == 'STALE'
        assert latest(setup)['lease_id'] == new['lease_id']


def test_transport_receipt_from_different_input_is_rejected(setup, monkeypatch):
    calls = simulate(monkeypatch, setup, input_sha256='0' * 64)
    assert invoke(setup)['result'] == 'DEFERRED' and len(calls) == 1
    assert latest(setup)['status'] != 'staged'


def test_priority_yield_never_approves_staging_or_claims_no_call_after_start(setup, monkeypatch):
    monkeypatch.setattr(worker, 'supervise', lambda *_a, **_kw: {
        'operational_outcome': 'PRIORITY_YIELD', 'workload_started': True, 'samples': 0})
    result = invoke(setup)
    assert result['reason'] == 'interpreter_priority' and result['codex_called'] is None
    assert latest(setup)['status'] == 'retry_wait'


def test_corrupt_cooldown_fails_closed(setup):
    atomic_write_json(setup[0] / worker.STATE_NAME, {'schema_version': 1, 'failures': -1})
    with pytest.raises(ValueError, match='failure counter'):
        invoke(setup)
    assert latest(setup)['status'] == 'queued'


def test_retry_bounds_and_timezones():
    for count in (0, 1, 10, 100):
        deadline, basis = worker.retry_deadline('quota', count, NOW)
        assert NOW + timedelta(hours=2) <= worker.parsed_time(deadline) <= NOW + timedelta(hours=24)
        assert basis == 'conservative_backoff'
    with pytest.raises(ValueError):
        worker.parsed_time('2026-09-14T01:00:00')
    assert worker.operating_window(datetime(2026, 9, 13, 17, 30, tzinfo=timezone.utc))
    assert not worker.operating_window(datetime(2026, 9, 14, 11, 45, tzinfo=timezone.utc))
    assert worker.runtime_window(datetime(2026, 9, 14, 11, 59, tzinfo=timezone.utc))
    assert not worker.runtime_window(datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc))


def test_acquisition_proceeds_without_auth_or_model_calls(setup, monkeypatch):
    from cdr_terms.acquisitions_queue import AcquisitionQueue
    (setup[1] / 'auth.json').unlink()
    monkeypatch.setattr(AcquisitionQueue, 'next_due', lambda *_: {'due': 'protocol-only'})
    calls = []
    def supervised(command, output, limits, **kwargs):
        calls.append(command)
        assert limits.runtime_seconds == 120
        assert 'pi_terms_acquire.py' in command[1]
        assert '--codex-home' not in command and '--codex-bin' not in command
        transport.write_receipt(output.parent / 'acquisition.json', {
            'schema_version': 1, 'result': 'NO_WORK', 'codex_called': False, 'network_called': False,
            'input_sha256': transport.file_hash(output.parent / 'input.json', transport.MAX_INPUT_BYTES)})
        return receipt()
    monkeypatch.setattr(worker, 'supervise', supervised)
    value = invoke(setup)
    assert len(calls) == 1 and value['reason'] == 'saved_subscription_auth_unavailable'
    assert value['acquisition']['result'] == 'NO_WORK'
    assert latest(setup)['status'] == 'queued'


def test_acquisition_is_independent_of_subscription_quota_cooldown(setup, monkeypatch):
    from cdr_terms.acquisitions_queue import AcquisitionQueue
    atomic_write_json(setup[0] / worker.STATE_NAME, {
        'schema_version': 1, 'failures': 1, 'reason': 'quota', 'retry_after': (NOW + timedelta(hours=5)).isoformat()})
    monkeypatch.setattr(AcquisitionQueue, 'next_due', lambda *_: {'due': 'protocol-only'})
    calls = []
    def supervised(command, output, limits, **kwargs):
        calls.append(command)
        assert limits.runtime_seconds == 120
        transport.write_receipt(output.parent / 'acquisition.json', {
            'schema_version': 1, 'result': 'INCOMPLETE', 'codex_called': False, 'network_called': True,
            'input_sha256': transport.file_hash(output.parent / 'input.json', transport.MAX_INPUT_BYTES)})
        return receipt()
    monkeypatch.setattr(worker, 'supervise', supervised)
    value = invoke(setup)
    assert value['reason'] == 'account_cooldown' and len(calls) == 1
    assert value['acquisition']['result'] == 'INCOMPLETE'


def test_empty_acquisition_child_does_no_network_or_model_call(tmp_path, monkeypatch):
    import pi_terms_acquire
    import cdr_terms.acquisitions_queue as acquisition
    from cdr_terms.ingest import registry_context
    evidence, operation = tmp_path / 'evidence', tmp_path / 'operation'
    with EvidenceStore(evidence):
        pass
    operation.mkdir(mode=0o700)
    transport.write_receipt(operation / 'input.json', {'evidence_root': str(evidence), 'registry_context': registry_context()})
    monkeypatch.setattr(acquisition, 'acquire_document', lambda *_a, **_k: pytest.fail('no due work may fetch'))
    result = pi_terms_acquire.run(operation)
    assert result['result'] == 'NO_WORK' and result['network_called'] is False and result['codex_called'] is False


def test_changed_acquisition_receipt_cannot_advance_interpreter(setup, monkeypatch):
    from cdr_terms.acquisitions_queue import AcquisitionQueue
    monkeypatch.setattr(AcquisitionQueue, 'next_due', lambda *_: {'due': 'protocol-only'})
    def supervised(command, output, limits, **kwargs):
        transport.write_receipt(output.parent / 'acquisition.json', {
            'schema_version': 1, 'result': 'NO_WORK', 'codex_called': False, 'network_called': False,
            'input_sha256': '0' * 64})
        return receipt()
    monkeypatch.setattr(worker, 'supervise', supervised)
    assert invoke(setup)['reason'] == 'acquisition_not_accepted'
    assert latest(setup)['status'] == 'queued'


@pytest.mark.parametrize('relative', ['runs', 'runs/2026-05-19', 'state', ''])
def test_private_store_cannot_overlap_source_or_state_before_any_write(setup, monkeypatch, tmp_path, relative):
    data = tmp_path / 'protected-data'
    monkeypatch.setenv('AR_LOCAL_DATA_ROOT', str(data))
    candidate = data / relative
    with pytest.raises(ValueError, match='overlap original'):
        worker.run_one(ROOT, candidate, setup[1], setup[2])
    assert not data.exists()


def test_unreviewed_context_cannot_upload_customer_profile(setup):
    with EvidenceStore(setup[0]) as store:
        queue = TermsQueue(store)
        old = queue.claim(now=NOW.isoformat())
        queue.event(old['job_id'], 'blocked', lease_id=old['lease_id'], error_code='protocol_setup')
        job_id = queue.enqueue(old['extraction_id'], {'product_keys': ['protocol-only'],
                                                    'customer_profile': {'private': 'must remain local'}})
        job = queue.claim(now=NOW.isoformat())
        operation = setup[0] / 'forbidden-profile-operation'
        with pytest.raises(ValueError, match='customer profiles'):
            worker.prepare_job(store, job, operation)
        assert job['job_id'] == job_id and not operation.exists()


def historical_setup(setup):
    from cdr_terms.historical import historical_scope
    from cdr_terms.identity import digest
    from cdr_terms.ingest import registry_context
    with EvidenceStore(setup[0]) as store:
        queue = TermsQueue(store)
        job = queue.enqueue_historical(setup[4]['extraction_id'], [setup[5]], registry_context=registry_context())
        context = queue.validate_input(job)
        scope = historical_scope(context['historical_target'])
        setup[4].update(context_sha256=digest(context), historical_scope=scope)
        target = context['historical_target']
        document = store.db.execute('SELECT document_id FROM document_versions WHERE document_version_id=?',
                                    (target['document_version_id'],)).fetchone()[0]
        # Whitespace-only new bytes preserve the retained real financial data.
        body = store.read_blob(target['document_content_sha256'])
        store.record_check(document_id=document, check_id='subsequent-source-format', checked_at=NOW.isoformat(),
                           status='fetched', body=body + b'\n', media_type='application/json')
    return job, scope


def test_historical_pin_survives_new_source_but_receipt_and_output_cannot_publish_current(setup, monkeypatch):
    from cdr_terms.reporting import validate_public_asset
    job, scope = historical_setup(setup)
    calls = simulate(monkeypatch, setup)
    value = invoke(setup)
    assert value['result'] == 'STAGED_HISTORICAL' and value['job_id'] == job and len(calls) == 1
    assert value['historical_scope'] == scope
    assert value['current_publication'] == 'PROHIBITED_HISTORICAL_SCOPE'
    prepared = json.loads((Path(value['operation']) / 'input.json').read_text())
    assert prepared['expected_historical_scope'] == scope
    assert latest(setup)['status'] == 'superseded'  # Ordinary current job remains protected.
    for payload in (setup[4], value):
        with pytest.raises(ValueError, match='Historical-only staging'):
            validate_public_asset(payload)
    with EvidenceStore(setup[0]) as store:
        assert store.db.execute('SELECT COUNT(*) FROM publications').fetchone()[0] == 0
        assert store.db.execute('SELECT COUNT(*) FROM term_revisions').fetchone()[0] == 0


def test_historical_output_without_required_scope_cannot_stage(setup, monkeypatch):
    job, _ = historical_setup(setup)
    del setup[4]['historical_scope']
    simulate(monkeypatch, setup)
    assert invoke(setup)['result'] == 'DEFERRED'
    with EvidenceStore(setup[0]) as store:
        row = store.db.execute('SELECT status FROM job_events WHERE job_id=? ORDER BY sequence DESC LIMIT 1', (job,)).fetchone()
        assert row[0] == 'retry_wait'
