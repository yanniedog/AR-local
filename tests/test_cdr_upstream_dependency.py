"""Retained DDH dependency failure, bounded recovery and accounting controls."""
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

import cdr_ingest_lib as ingest
import cdr_ingest_support as support
from app_payload_authentication import authentication_exclusions
from app_payload_partial_accounting import reconciled_partial_v1_allowed
from cdr_compatibility import classify_fetch_failure, compact_failure_evidence
from cdr_ingest_recovery import recover_transient_providers
from cdr_http_policy import HttpPolicyError, PolicyResponse
from cdr_raw_attempt_journal import RawAttemptJournal
from tests.test_app_payload_partial_accounting import contract, seal

BODY = (Path(__file__).parent / 'fixtures/cdr-index-failures-20261012/ddh-index-error.json').read_text(encoding='utf-8')
CATEGORY = 'upstream_dependency_failure'


def test_exact_retained_failure_is_a_dependency_outage():
    assert hashlib.sha256(BODY.encode()).hexdigest() == 'fc6cd986fbef03494dfbd487f1ac228403b57526de4f8dd27395f0f8decd63f5'
    assert classify_fetch_failure(401, BODY) == (CATEGORY, True, False)
    assert classify_fetch_failure('401', BODY) == (CATEGORY, True, False)


@pytest.mark.parametrize('status,expected', [(403, 'public_endpoint_auth_required'),
    (406, 'incompatible_version'), (495, 'security_policy'), (500, 'transient_upstream')])
def test_only_evidenced_status_is_reclassified(status, expected):
    assert classify_fetch_failure(status, BODY).category == expected


@pytest.mark.parametrize('fault', ['mixed', 'code', 'title', 'detail', 'meta', 'outer', 'extra', 'invalid_token'])
def test_generic_or_mixed_client_auth_remains_terminal(fault):
    value = json.loads(BODY)
    if fault == 'mixed':
        value['errors'].append({'code': 'invalid_token'})
    elif fault == 'outer':
        value['error'] = 'invalid_token'
    elif fault == 'invalid_token':
        value = {'error': 'invalid_token'}
    elif fault == 'extra':
        value['errors'][0]['authentication'] = 'API key is required'
    else:
        value['errors'][0][fault] = 'invalid_token'
    assert classify_fetch_failure(401, json.dumps(value)) == ('public_endpoint_auth_required', False, False)


def test_compact_classification_roundtrips_after_display_truncation(tmp_path):
    body = ' ' * 1000 + BODY
    assert 'EBAU001' not in body[:500]
    compact = compact_failure_evidence(401, body)
    assert len(compact) <= 500 and classify_fetch_failure(401, compact).category == CATEGORY
    response = support.FetchResult(False, 401, '', body, failure_category=CATEGORY, retryable=True)
    support.append_failure(tmp_path, {'bank': 'DDH Graham', 'phase': 'products_index',
        'snippet': body[:500], **ingest._fetch_failure_fields(response)})
    status = support.summarize_failures(tmp_path)
    assert status['by_provider_failure_category'] == {'DDH Graham': {CATEGORY: 1}}
    assert status['by_retryable'] == {'true': 1}


def test_duplicate_error_keys_never_override_client_authentication():
    body = BODY.replace('"code":"EBAU001"', '"code":"invalid_token","code":"EBAU001"')
    assert body != BODY
    assert classify_fetch_failure(401, body) == ('public_endpoint_auth_required', False, False)


def test_deeply_nested_auth_body_is_recorded_without_aborting_fetch(tmp_path, monkeypatch):
    raw = ('[' * 2000 + 'null' + ']' * 2000).encode()
    url = 'https://api.cds.ddhgraham.com.au/cds-au/v1/banking/products'
    response = PolicyResponse(401, url, {}, raw, len(raw), len(raw), hashlib.sha256(raw).hexdigest(), None, ())
    request = Mock(return_value=response)
    monkeypatch.setattr(support, 'request_https', request)
    journal = RawAttemptJournal(tmp_path / 'attempt-evidence/raw-attempt-journals-v1', 'nested-error')
    brand = {'brand_name': 'DDH Graham', 'endpoint_url': url}
    ingest.ingest_brand(brand, date_root=tmp_path, resume=False, sleep_ms=0, timeout=5,
        max_retries=6, max_pages=None, max_products=None, fetch_unknown_detail=False,
        bank_dir_name='DDH Graham', detail_workers=1, log=lambda _: None, attempt_journal=journal)
    request.assert_called_once()
    failure = json.loads((tmp_path / 'failures.jsonl').read_text())
    assert failure['status'] == 401 and failure['failure_category'] == 'public_endpoint_auth_required'
    assert failure['retryable'] is False and failure['phase'] == 'products_index'
    snapshot = support.RegisterSnapshot(True, True, [{'ok': True, 'sha256': 'a' * 64}], [brand], 1)
    status = ingest._persist_ingest_status(banks_root=tmp_path, run_root=tmp_path,
        snapshot=snapshot, bank_work=[(brand, 'DDH Graham')], attempt_journal=journal)
    assert status['by_failure_category'] == {'public_endpoint_auth_required': 1}
    assert status['provider_states'][0]['state'] == 'partial'
    assert status['unresolved_requests'][0]['failure_category'] == 'public_endpoint_auth_required'
    events = list(journal.events.glob('*.json'))
    assert len(events) == 1
    event = json.loads(events[0].read_bytes())
    assert event['response']['status'] == 401 and event['context']['phase'] == 'products_index'
    assert (journal.root / event['body_path']).read_bytes() == raw
    assert event['response']['body_sha256'] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize('status,received', [(495, False), (599, False), (200, True), (401, True)])
def test_missing_response_has_no_digest_but_received_empty_body_does(monkeypatch, status, received):
    url = 'https://holder.example/products'
    expected = hashlib.sha256(b'').hexdigest() if received else None
    request = (Mock(return_value=PolicyResponse(status, url, {}, b'', 0, 0, expected, None, ()))
               if received else Mock(side_effect=HttpPolicyError('request_failed', 'No response', status=status)))
    monkeypatch.setattr(support, 'request_https', request)
    response = support.http_request(url, {}, timeout=5)
    assert response.body_sha256 == expected
    result = support.fetch_cdr_json(url, versions=[5], timeout=5, max_retries=0,
                                   sleep_ms=0, allow_partial_index=True, attempt_context={'phase': 'products_index'})
    assert result.body_sha256 == expected and result.partial_index is None


def test_dependency_outage_retries_same_version_then_one_recovery_pass(tmp_path, monkeypatch):
    request = Mock(return_value=(401, BODY, None))
    monkeypatch.setattr(support, 'http_request', request)
    monkeypatch.setattr(support.time, 'sleep', lambda _: None)
    result = support.fetch_cdr_json('https://api.cds.ddhgraham.com.au/cds-au/v1/banking/products',
        versions=[6, 5, 4], timeout=5, max_retries=6, sleep_ms=0)
    assert not result.ok and result.retryable and result.failure_category == CATEGORY
    assert result.attempts == request.call_count == 6  # Two fallback slots reserved, never swept.
    assert {call.args[1]['x-v'] for call in request.call_args_list} == {'6'}
    support.append_failure(tmp_path, {'bank': 'DDH Graham', 'phase': 'products_index',
        'snippet': BODY, **ingest._fetch_failure_fields(result)})
    retry = Mock()
    report = recover_transient_providers(tmp_path, [({}, 'DDH Graham')], retry,
        log=lambda _: None, sleep=lambda _: None)
    assert report['result'] == 'completed' and retry.call_count == 1
    assert support.summarize_failures(tmp_path)['total'] == 1  # No positive recapture: never clear it.


def test_dependency_is_publishable_partial_without_auth_exemption(contract):
    # Change only failure classification on a real retained accounting fixture.
    provider = next(row for row in contract['provider_states'] if row['failure_records'])
    provider['failure_categories'] = {CATEGORY: provider['failure_records']}
    seal(contract)
    assert reconciled_partial_v1_allowed(contract)
    exclusions = authentication_exclusions(contract)
    assert provider['provider_uid'] not in {row['provider_uid'] for row in exclusions['providers']}
    assert contract['observation_state'] == 'partial'


@pytest.mark.parametrize('budget,expected', [(2, [6, 5]), (4, [6, 5, 5, 5])])
def test_negotiated_dependency_retry_stays_on_version_and_inside_shared_attempts(monkeypatch, budget, expected):
    versions = []
    def request(url, headers, *, timeout):
        version = int(headers['x-v']); versions.append(version)
        return (406, '{"detail":"Unsupported Version; Available: 5"}', None) if version == 6 else (401, BODY, None)
    monkeypatch.setattr(support, 'http_request', request)
    monkeypatch.setattr(support.time, 'sleep', lambda _: None)
    result = support.fetch_cdr_json('https://holder.example/products', versions=[6, 5],
        timeout=5, max_retries=2, sleep_ms=0, max_total_attempts=budget)
    assert versions == expected and result.attempts == len(expected)
    assert result.status == 401 and result.text == BODY and result.failure_category == CATEGORY


@pytest.mark.parametrize('status,body', [(401, '{"error":"invalid_token"}'), (403, BODY),
    (401, BODY.replace('EBAU001', 'OTHER')), (401, BODY[:-1] + ',"error":"invalid_token"}')])
def test_cdr_numeric_auth_admission_never_retries_unrecognized_or_mixed_auth(monkeypatch, status, body):
    request = Mock(return_value=(status, body, None))
    monkeypatch.setattr(support, 'http_request', request)
    monkeypatch.setattr(support.time, 'sleep', lambda _: pytest.fail('authentication must remain terminal'))
    result = support.fetch_cdr_json('https://holder.example/products', versions=[6, 5],
        timeout=5, max_retries=6, sleep_ms=0)
    assert request.call_count == result.attempts == 1 and not result.retryable


def test_dependency_retry_does_not_override_an_explicit_caller_predicate(monkeypatch):
    request = Mock(return_value=(401, BODY, None))
    monkeypatch.setattr(support, 'http_request', request)
    result = support.fetch_with_retries('https://holder.example/products', {}, timeout=1,
        max_retries=6, sleep_ms=0, retry_on=lambda _: False)
    assert request.call_count == result.attempts == 1


def test_dependency_retry_can_recover_a_real_valid_index(monkeypatch):
    captured = json.loads((Path(__file__).parent / 'fixtures/cdr-september7/defence.json').read_text())
    body = json.dumps(captured['products_index']['body'])
    request = Mock(side_effect=[(401, BODY, None), (200, body, None)])
    monkeypatch.setattr(support, 'http_request', request)
    monkeypatch.setattr(support.time, 'sleep', lambda _: None)
    result = support.fetch_cdr_json('https://holder.example/products', versions=[5],
        timeout=5, max_retries=1, sleep_ms=0, attempt_context={'phase': 'products_index'})
    assert result.ok and result.attempts == 2 and result.version == 5 and result.text == body


def test_dependency_retry_after_is_bounded_by_remaining_logical_deadline(monkeypatch):
    clock, waits = [0.0], []
    request = Mock(return_value=(401, BODY, 10))
    def sleep(seconds):
        waits.append(seconds); clock[0] += seconds
    monkeypatch.setattr(support, 'http_request', request)
    monkeypatch.setattr(support.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(support.time, 'sleep', sleep)
    result = support.fetch_cdr_json('https://holder.example/products', versions=[5],
        timeout=5, max_retries=6, sleep_ms=0, max_total_seconds=4)
    assert waits == [4] and clock[0] == 4 and request.call_count == result.attempts == 1
    assert result.status == 401 and result.failure_category == CATEGORY
