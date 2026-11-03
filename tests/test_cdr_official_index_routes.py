"""Official route compatibility; retained first pages are not full-run acceptance."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import cdr_ingest_lib as lib
import cdr_ingest_support as support
import cdr_same_day_reuse as reuse
from cdr_population_identity import population_finding_resolved
from pi_cdr_recovery_probe import current_target_url

FIXTURES = Path(__file__).parent / 'fixtures' / 'cdr-official-index-routes-2026-11-04'
HOLDERS = [('bom', 'Bank of Melbourne', 'digital-api.bankofmelbourne.com.au', 40),
           ('stgeorge', 'St.George Bank', 'digital-api.stgeorge.com.au', 42)]


@pytest.mark.parametrize('fixture,provider,host,total', HOLDERS)
def test_register_identity_stays_stable_and_request_uses_documented_route(fixture, provider, host, total):
    base = f'https://{host}/cds-au/v1/banking/products'
    assert support.normalize_banking_products_url(f'https://{host}') == base
    assert support.normalize_banking_products_url(base + '/') == base
    assert support.product_index_request_url(base) == base + '/'
    assert support.product_index_request_url(base + '/') == base + '/'
    assert support.product_index_request_url(base + '?page=2&page-size=25') == base + '/?page=2&page-size=25'
    material = '\x1f'.join((base, provider.lower(), provider.lower()))
    uid = 'legacy-prd:' + hashlib.sha256(material.encode()).hexdigest()
    finding = {'provider': provider, 'provider_identity': {'provider_uid': uid, 'endpoint_url': base}}
    status = {'provider_states': [{'provider_dir': provider, 'provider_uid': uid, 'endpoint_url': base}],
              'index_diagnostics': {provider: {'pagination_complete': True, 'unique_products': total}}}
    assert population_finding_resolved(finding, status)
    status['index_diagnostics'][provider]['pagination_complete'] = False
    assert not population_finding_resolved(finding, status)
    status['index_diagnostics'][provider].update(pagination_complete=True, unique_products=0)
    assert not population_finding_resolved(finding, status)


@pytest.mark.parametrize('url', [
    'https://digital-api.bankofmelbourne.com.au/cds-au/v1/banking/products/p',
    'https://digital-api.bankofmelbourne.com.au/cds-au/v1/banking/products-other',
    'https://digital-api.bankofmelbourne.com.au/other',
    'https://digital-api.bankofmelbourne.com.au:443/cds-au/v1/banking/products',
    'https://user@digital-api.bankofmelbourne.com.au/cds-au/v1/banking/products',
    'https://digital-api.bankofmelbourne.com.au.evil.test/cds-au/v1/banking/products',
    'http://digital-api.bankofmelbourne.com.au/cds-au/v1/banking/products',
    'https://digital-api.banksa.com.au/cds-au/v1/banking/products',
    'https://example.test/cds-au/v1/banking/products',
])
def test_other_hosts_paths_details_and_authorities_unchanged(url):
    assert support.product_index_request_url(url) == url


@pytest.mark.parametrize('fixture,provider,host,total', HOLDERS)
def test_recovery_routes_old_plain_request_without_changing_details(fixture, provider, host, total):
    base = f'https://{host}/cds-au/v1/banking/products'
    brand = {'brand_name': provider, 'legal_entity_name': provider, 'endpoint_url': base}
    state = dict(brand, provider_dir=provider)
    request = {'phase': 'products_index', 'url': base + '?page=2&page-size=25'}
    assert current_target_url(request, state, [brand]) == base + '/?page=2&page-size=25'
    detail = {'phase': 'product_detail', 'product_id': 'a/b', 'url': base}
    assert current_target_url(detail, state, [brand]) == base + '/a%2Fb'
    with pytest.raises(ValueError, match='ambiguous'):
        current_target_url(request, state, [brand, copy.deepcopy(brand)])


@pytest.mark.parametrize('fixture,provider,host,total', HOLDERS)
def test_retained_v5_first_page_and_next_link_are_bound(fixture, provider, host, total, monkeypatch):
    raw = (FIXTURES / (fixture + '.json')).read_bytes()
    provenance = json.loads((FIXTURES / 'provenance.json').read_bytes())
    assert hashlib.sha256(raw).hexdigest() == provenance['files'][fixture + '.json']
    payload = json.loads(raw)
    assert len(payload['data']['products']) == 25
    assert payload['meta'] == {'totalRecords': total, 'totalPages': 2}
    url = support.product_index_request_url(f'https://{host}/cds-au/v1/banking/products')
    seen = []
    def http(request_url, headers, *, timeout):
        seen.append((request_url, headers['x-v']))
        if headers['x-v'] == '6':
            return 406, '{"errors":[{"detail":"Unsupported version"}]}', None
        return 200, raw.decode(), None
    monkeypatch.setattr(support, 'http_request', http)
    result = support.fetch_cdr_json(url, versions=lib.PRODUCT_INDEX_VERSION_ORDER,
                                    timeout=1, max_retries=0, sleep_ms=0)
    assert result.ok and result.version == 5
    assert seen == [(url, '6'), (url, '5')]
    assert support.next_link(result.data, url) == url + '?page=2&page-size=25'


@pytest.mark.parametrize('fixture,provider,host,total', HOLDERS)
def test_seeded_ingest_uses_official_route_reuses_details_and_retains_incomplete_index(
        fixture, provider, host, total, tmp_path, monkeypatch):
    base = f'https://{host}/cds-au/v1/banking/products'
    raw = (FIXTURES / (fixture + '.json')).read_text()
    products = json.loads(raw)['data']['products']
    seen = []
    def fetch(url, **kwargs):
        seen.append((url, kwargs['versions']))
        if len(seen) == 1:
            return support.FetchResult(True, 200, url, raw, version=5)
        return support.FetchResult(False, 599, url, '', failure_category='transport_error')
    monkeypatch.setattr(lib, 'fetch_cdr_json', fetch)
    monkeypatch.setattr(lib, 'existing_product_leaves', lambda *a: ({r['productId']: tmp_path for r in products}, set()))
    monkeypatch.setattr(lib, 'usable_cached_detail', lambda *a: True)
    monkeypatch.setattr(lib, '_fetch_detail', lambda *a, **k: pytest.fail('seeded detail must not be fetched again'))
    lib.ingest_brand({'endpoint_url': base}, date_root=tmp_path, resume=True, sleep_ms=0,
                     timeout=1, max_retries=0, max_pages=None, max_products=None,
                     fetch_unknown_detail=False, bank_dir_name=provider, detail_workers=1, log=lambda *a: None)
    assert seen == [(base + '/', [6, 5, 4, 3, 2, 1]),
                    (base + '/?page=2&page-size=25', [5, 6, 4, 3, 2, 1])]
    diagnostics = json.loads((tmp_path / '_holders' / provider / '_products-index' / 'diagnostics.json').read_bytes())
    assert diagnostics['pagination_complete'] is False
    assert diagnostics['unique_products'] == 25


def test_fresh_reuse_index_binds_official_first_page_without_identity_change(tmp_path, monkeypatch):
    # Structural empty-list control checks route/provenance, not financial data.
    provider = 'Bank of Melbourne'
    endpoint = 'https://digital-api.bankofmelbourne.com.au/cds-au/v1/banking/products'
    payload = {'data': {'products': []}, 'meta': {'totalRecords': 0, 'totalPages': 0}, 'links': {}}
    path = tmp_path / '_holders' / provider / '_products-index' / 'page-0001.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload))
    event = {'context': {'phase': 'products_index', 'provider': provider, 'page': 1},
             'request': {'url': endpoint + '/'}, 'response': {'body_sha256': 'a' * 64},
             'event_digest': 'b' * 64, 'sequence': 1}
    monkeypatch.setattr(reuse, '_successful_body', lambda *a: (b'', payload))
    diagnostics = dict(pagination_complete=True, conflicting_duplicate_records=0,
                       declared_total_records=0, raw_records=0, pages=1, declared_total_pages=0)
    journal = SimpleNamespace(session_id='structural-route-control')
    assert reuse._fresh_index(tmp_path, provider, diagnostics, journal, [event], endpoint) is not None
    event['request']['url'] = 'https://other.test/cds-au/v1/banking/products/'
    assert reuse._fresh_index(tmp_path, provider, diagnostics, journal, [event], endpoint) is None
