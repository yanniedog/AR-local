"""Real retained index bodies through request, ingest and same-day proof binding."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

import cdr_ingest_lib as lib
import cdr_ingest_support as support
import cdr_observation_selection as selection
import cdr_same_day_reuse as reuse
from cdr_raw_attempt_journal import RawAttemptJournal
from pi_cdr_recovery_probe import current_target_url

FIXTURES = Path(__file__).parent / 'fixtures/cdr-official-single-page-2026-11-04'
HOLDERS = [('bom', 'Bank of Melbourne', 40), ('stgeorge', 'St.George Bank', 42)]
QUERY = '?page=1&page-size=1000'


def retained(fixture):
    provenance = json.loads((FIXTURES / 'provenance.json').read_bytes())
    raw = (FIXTURES / (fixture + '.json')).read_bytes()
    register = (FIXTURES / 'register.json').read_bytes()
    for name, body in ((fixture + '.json', raw), ('register.json', register)):
        assert hashlib.sha256(body).hexdigest() == provenance['files'][name]
    return raw, list(support.iter_banking_brands_from_payload(json.loads(register)))


@pytest.mark.parametrize('fixture,provider,total', HOLDERS)
@pytest.mark.parametrize('suffix', ['', '/', '?page=2&page-size=25', '/?page=2&page-size=25',
                                    '?product-category=TERM_DEPOSITS&effective=CURRENT', '/?brand=Bank%20Name'])
def test_fresh_register_recovery_route_preserves_explicit_queries(fixture, provider, total, suffix):
    _, brands = retained(fixture)
    brand = next(row for row in brands if row['brand_name'] == provider)
    endpoint = brand['endpoint_url']
    state = dict(brand, provider_dir=provider)
    before = copy.deepcopy(state)
    request = {'phase': 'products_index', 'url': endpoint + suffix}
    query = '?' + suffix.split('?', 1)[1] if '?' in suffix else QUERY
    assert current_target_url(request, state, brands) == endpoint + '/' + query
    assert support.product_index_request_url(endpoint + suffix) == endpoint + '/' + query
    assert state == before and '?' not in state['endpoint_url']
    assert current_target_url({'phase': 'product_detail', 'product_id': 'a/b'}, state, brands) == endpoint + '/a%2Fb'


@pytest.mark.parametrize('fixture,provider,total', HOLDERS)
def test_real_single_page_ingest_and_bound_reuse_selection(fixture, provider, total, tmp_path, monkeypatch):
    raw, brands = retained(fixture)
    brand = next(row for row in brands if row['brand_name'] == provider)
    endpoint = brand['endpoint_url']
    payload = json.loads(raw)
    ids = {row['productId'] for row in payload['data']['products']}
    assert len(ids) == len(payload['data']['products']) == total
    assert payload['meta'] == {'totalRecords': total, 'totalPages': 1}
    assert not payload['links'].get('next')
    banks = tmp_path / 'banks'
    journal = RawAttemptJournal(tmp_path / 'attempt-evidence/raw-attempt-journals-v1', 'fresh-index')
    events, calls = [], []
    def fetch(url, **kwargs):
        calls.append(url)
        assert url == endpoint + '/' + QUERY
        assert kwargs['versions'] == [6, 5, 4, 3, 2, 1]
        events.append(journal.record('page-1', request_url=url, status=200, outcome='success', body=raw,
            started_at='2026-11-04T01:39:20Z', completed_at='2026-11-04T01:39:21Z',
            context=kwargs['attempt_context']))
        return support.FetchResult(True, 200, url, raw.decode(), version=5)
    monkeypatch.setattr(lib, 'fetch_cdr_json', fetch)
    # Isolate index work: cached-detail admission is a separate tested contract.
    monkeypatch.setattr(lib, 'existing_product_leaves', lambda *a: ({pid: banks for pid in ids}, set()))
    monkeypatch.setattr(lib, 'usable_cached_detail', lambda *a: True)
    monkeypatch.setattr(lib, '_fetch_detail', lambda *a, **k: pytest.fail('unexpected detail fetch'))
    lib.ingest_brand(brand, date_root=banks, resume=True, sleep_ms=0, timeout=1,
        max_retries=0, max_pages=None, max_products=None, fetch_unknown_detail=False,
        bank_dir_name=provider, detail_workers=1, log=lambda *a: None, attempt_journal=journal)
    assert calls == [endpoint + '/' + QUERY]
    index = banks / '_holders' / provider / '_products-index'
    diagnostic = json.loads((index / 'diagnostics.json').read_bytes())
    assert diagnostic['pagination_complete'] is True
    assert diagnostic['unique_products'] == diagnostic['raw_records'] == total
    proof = reuse._fresh_index(banks, provider, diagnostic, journal, events, endpoint)
    assert proof['complete'] is True and set(proof['observed_product_ids']) == ids

    artifacts = []
    for path in journal.root.rglob('*'):
        if path.is_file():
            body = path.read_bytes()
            artifacts.append({'path': path.relative_to(tmp_path).as_posix(), 'bytes': len(body),
                              'sha256': hashlib.sha256(body).hexdigest()})
    material = '\x1f'.join(str(brand[key]).strip().lower()
                          for key in ('endpoint_url', 'legal_entity_name', 'brand_name'))
    state = dict(brand, provider_dir=provider, identity_status='derived_legacy',
                 provider_uid='legacy-prd:' + hashlib.sha256(material.encode()).hexdigest())
    observation = {'export_root': tmp_path, 'contract': {'observation_date': '2026-11-04', 'artifacts': artifacts},
        'status': {'provider_states': [state], 'index_diagnostics': {provider: diagnostic},
                   'raw_attempt_journal': {'path': journal.root.relative_to(tmp_path).as_posix(), 'session_id': journal.session_id}}}
    assert selection._verified_withdrawal_index(observation, provider, proof) == ids
    assert state['endpoint_url'] == endpoint and '?' not in endpoint
    # Changing only the recorded request must fail both proof layers.
    for bad in (endpoint + '/?page=1&page-size=25', endpoint + '/?brand=other',
                'https://other.test/cds-au/v1/banking/products/' + QUERY):
        altered = copy.deepcopy(events)
        altered[0]['request']['url'] = bad
        assert reuse._fresh_index(banks, provider, diagnostic, journal, altered, endpoint) is None


@pytest.mark.parametrize('fixture,provider,total', HOLDERS)
@pytest.mark.parametrize('suffix,accepted', [('', True), ('/?page=1&page-size=1000', True),
                                           ('/?brand=other', False), ('/?page=1&page-size=25', False)])
def test_selection_current_and_retained_legacy_first_request(fixture, provider, total, suffix, accepted, tmp_path):
    raw, brands = retained(fixture)
    brand = next(row for row in brands if row['brand_name'] == provider)
    endpoint = brand['endpoint_url']
    journal = RawAttemptJournal(tmp_path / 'attempt-evidence/raw-attempt-journals-v1', 'proof')
    event = journal.record('page-1', request_url=endpoint + suffix, status=200, outcome='success', body=raw,
        started_at='2026-11-04T01:39:20Z', completed_at='2026-11-04T01:39:21Z',
        context={'phase':'products_index', 'provider':provider, 'page':1})
    digest = event['response']['body_sha256']
    from cdr_atomic import canonical_json_bytes
    proof = {'complete':True, 'observed_product_ids':[r['productId'] for r in json.loads(raw)['data']['products']],
        'pages':[{'body_sha256':digest, 'event_digest':event['event_digest'], 'event_seq':event['sequence'], 'journal_session_id':journal.session_id}],
        'fresh_index_sha256':hashlib.sha256(canonical_json_bytes({'page_body_sha256':[digest]})).hexdigest()}
    artifacts = [{'path':p.relative_to(tmp_path).as_posix(), 'bytes':p.stat().st_size,
                  'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in journal.root.rglob('*') if p.is_file()]
    observation = {'export_root':tmp_path, 'contract':{'observation_date':'2026-11-04','artifacts':artifacts},
        'status':{'provider_states':[dict(brand,provider_dir=provider)],
                  'raw_attempt_journal':{'path':journal.root.relative_to(tmp_path).as_posix(),'session_id':journal.session_id},
                  'index_diagnostics':{provider:{'pagination_complete':True,'pages':1,'raw_records':total,'declared_total_pages':1}}}}
    if accepted:
        assert len(selection._verified_withdrawal_index(observation, provider, proof)) == total
    else:
        with pytest.raises(ValueError, match='discontinuous'):
            selection._verified_withdrawal_index(observation, provider, proof)
