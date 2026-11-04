"""Offline replay of separately timed Melbourne responses, including failures."""
import hashlib
import json
from pathlib import Path

import pytest

import cdr_ingest_support as support

FIXTURES = Path(__file__).parent / 'fixtures/cdr-bom-page100-2026-11-04'


def retained(name):
    provenance = json.loads((FIXTURES / 'provenance.json').read_bytes())['files'][name]
    raw = (FIXTURES / (name + '.json')).read_bytes()
    event_raw = (FIXTURES / (name + '-event.json')).read_bytes()
    event = json.loads(event_raw)
    assert hashlib.sha256(event_raw).hexdigest() == provenance['event_sha256']
    assert hashlib.sha256(raw).hexdigest() == provenance['body_sha256'] == event['response']['body_sha256']
    assert len(raw) == event['response']['body_bytes']
    return raw, event


def test_page100_membership_matches_earlier1000_without_reclassifying_failure():
    raw, event = retained('bom')
    failed, failure = retained('bom-1000-v5-error')
    payload = json.loads(raw)
    earlier = json.loads((FIXTURES.parent / 'cdr-official-single-page-2026-11-04/bom.json').read_bytes())
    assert {p['productId'] for p in payload['data']['products']} == {
        p['productId'] for p in earlier['data']['products']}
    assert len(payload['data']['products']) == 40
    assert payload['meta'] == {'totalRecords': 40, 'totalPages': 1}
    assert not payload['links'].get('next')
    assert failure['response']['status'] == 422 and support.has_cdr_errors(json.loads(failed))
    assert failure['response']['completed_at'] < event['request']['started_at']
    endpoint = event['request']['url'].split('?')[0]
    assert support.product_index_request_url(endpoint) == event['request']['url']


@pytest.mark.parametrize('attempts', [0, 1, 2])
def test_explicit1000_failure_keeps_attempt_budget_and_rejection(attempts, monkeypatch):
    responses = [retained(name) for name in ('bom-1000-v5-error', 'bom-1000-v4-error')]
    url = responses[0][1]['request']['url']
    assert support.product_index_request_url(url) == url
    calls = []

    def http(request_url, headers, *, timeout):
        raw, event = responses[len(calls)]
        assert request_url == event['request']['url']
        assert headers['x-v'] == event['request']['headers']['x-v']
        calls.append(headers['x-v'])
        return support.HttpRequestResult(event['response']['status'], raw.decode(), None,
                                         event['response']['body_sha256'])

    monkeypatch.setattr(support, 'http_request', http)
    result = support.fetch_cdr_json(url, versions=[5, 4], timeout=1, max_retries=0,
                                    sleep_ms=0, max_total_attempts=attempts)
    assert not result.ok and result.attempts == len(calls) == attempts
    assert calls == ['5', '4'][:attempts]
    if attempts:
        assert result.status == 422 and result.text == responses[0][0].decode()
        assert result.body_sha256 == responses[0][1]['response']['body_sha256']
