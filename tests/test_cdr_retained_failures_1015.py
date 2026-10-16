"""Actual retained provider failures must stay scoped, attributable and unmanufactured."""
import hashlib
import json
from pathlib import Path

import pytest

import cdr_ingest_support as support
from cdr_compatibility import classify_fetch_failure, response_shape_error

ROOT = Path(__file__).parent/'fixtures/ingest-capture-20261015'
CASES = json.loads((ROOT/'terminal-errors.json').read_text())


def test_targeted_source_bytes_match_the_finalized_contract_artifacts():
    provenance = json.loads((ROOT/'provenance.json').read_text())
    for row in provenance['records']:
        raw = (ROOT/row['file']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row['body_sha256'] == row['contract_body_entry']['sha256']
        assert len(raw) == row['bytes'] == row['contract_body_entry']['bytes']
        assert row['event_file_sha256'] == row['contract_event_entry']['sha256']


@pytest.mark.parametrize('case', CASES, ids=lambda c:c['request']['provider_dir']+':'+c['request']['product_id'])
def test_upstream_errors_do_not_turn_into_products_or_fabricated_rate_defaults(monkeypatch, case):
    request=case['request'];raw=case['body'].encode()
    assert hashlib.sha256(raw).hexdigest() == case['body_sha256'] == case['contract_body_entry']['sha256']
    failure = classify_fetch_failure(request['status'],case['body'])
    assert failure.category == case['current_category']
    calls=[]
    def http(url, headers, **kwargs):
        calls.append(url)
        return support.HttpRequestResult(request['status'],case['body'],None,case['body_sha256'])
    monkeypatch.setattr(support,'http_request',http)
    result=support.fetch_cdr_json(request['url'],versions=[case['version']],timeout=1,
        max_retries=0,sleep_ms=0,attempt_context={'phase':request['phase'],'product_id':request['product_id']})
    assert result.ok is False
    assert result.failure_category == case['current_category']
    assert result.text == case['body'] and len(calls)==1


def test_ddh_internal_token_failure_does_not_request_caller_credentials():
    case = next(c for c in CASES if c['request']['provider_dir']=='DDH Graham')
    failure = classify_fetch_failure(case['request']['status'],case['body'])
    assert 'given tenantId' in case['body']
    assert failure.category == 'upstream_dependency_failure'
    assert failure.retryable is True and failure.negotiate is False


def test_current_partial_index_fix_recovers_only_the_17_real_identified_rows(monkeypatch):
    raw=(ROOT/'geelong-index.json').read_bytes();data=json.loads(raw)
    digest=hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(support,'http_request',lambda *a,**k:support.HttpRequestResult(200,raw.decode(),None,digest))
    result=support.fetch_cdr_json(data['links']['self'],versions=[5],timeout=1,max_retries=0,
        sleep_ms=0,attempt_context={'phase':'products_index'},allow_partial_index=True)
    assert response_shape_error(data,phase='products_index') is not None
    assert result.ok and result.partial_index == {'raw_records':18,'identified_records':17,
        'unidentified_records':1,'omitted_row_positions':[17],'unique_products':17}
    assert result.text == raw.decode()  # Missing identity remains missing.


def test_melbourne_requested_exactly_the_next_page_supplied_by_upstream():
    page=json.loads((ROOT/'melbourne-page1.json').read_bytes())
    error=json.loads((ROOT/'melbourne-invalid-page.json').read_bytes())
    provenance=json.loads((ROOT/'provenance.json').read_text())
    request=next(r['request'] for r in provenance['records'] if r['file']=='melbourne-invalid-page.json')
    assert page['meta'] == {'totalRecords':40,'totalPages':2}
    assert request['url'] == page['links']['next']
    assert request['headers']['x-v'] == '5'
    assert error['errors'][0]['title'] == 'Invalid Page'
    assert 'out of page range' in error['errors'][0]['detail']
