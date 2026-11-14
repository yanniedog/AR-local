"""Real retained product/register bodies; availability/time changes are fault controls."""
import hashlib
import json

import pytest

import cdr_ingest_lib as ingest
import cdr_ingest_support as support
import cdr_same_day_reuse as reuse
from cdr_atomic import atomic_write_json
from cdr_provider_participation_evidence import current_register
from cdr_raw_attempt_journal import RawAttemptJournal
from tests import test_cdr_same_day_reuse as fixture
from tests.test_cdr_prd_availability import capture, DAY
from tests.test_cdr_financial_register import retained


@pytest.mark.parametrize('retained_failure', [False, True])
def test_unavailable_reconciliation_retains_product_and_finalizes_without_new_request(tmp_path, monkeypatch, retained_failure):
    monkeypatch.setattr(fixture, 'DATE', DAY)
    row = fixture._record()
    # The official register omits legalEntityName; preserve that actual identity.
    row['brand']['legal_entity_name'] = ''
    material = '\x1f'.join(row['brand'][key].lower() for key in
                           ('endpoint_url', 'legal_entity_name', 'brand_name'))
    row['state'].update(row['brand'], provider_uid='legacy-prd:' + hashlib.sha256(material.encode()).hexdigest())
    row['state']['legal_entity_name'] = None  # Production status serializes absent names as null.
    state, _, parent = fixture._observation(tmp_path, records=[row], captured=DAY+'T00:00:00Z')
    baseline = fixture._bytes(tmp_path / 'data')
    stage = tmp_path / 'repair' / DAY
    reuse.seed_same_day_reuse(reuse.prepare_same_day_reuse(state, DAY), stage)
    payload = json.loads(retained('register.json'))
    next(item for item in payload['data'] if item['brandName'] == row['provider']).pop('productBaseUri')
    body = json.dumps(payload).encode()
    monkeypatch.setattr(support, 'fetch_cdr_json', lambda *a, **k:
        support.FetchResult(True, 200, support.REGISTER_URL_SUMMARY, body.decode(), version=2))
    snapshot = support.collect_register_snapshot(timeout=1, max_retries=0, sleep_ms=0, holders_filter=None)
    journal = RawAttemptJournal(stage / '_raw-attempt-journals-v1', 'unavailable-reuse')
    journal.record('register', request_url=support.REGISTER_URL_SUMMARY,
        request_headers={'x-v': '2'}, status=200, outcome='success', body=body,
        response_headers={'x-v': '2'}, started_at=DAY+'T01:00:00Z', completed_at=DAY+'T01:00:01Z',
        context={'phase': 'register_discovery', 'cdr_version': 2})
    banks = stage / 'banks'; (banks / 'failures.jsonl').write_bytes(b'')
    if retained_failure:
        support.append_failure(banks, {'bank': row['provider'], 'phase': 'products_index', 'status': 504})
    seen = set()
    work = [(brand, support.allocate_bank_dir(brand['brand_name'], brand['legal_entity_name'],
              brand['endpoint_url'], seen)) for brand in snapshot.banking_brands]
    brand = next(brand for brand, name in work if name == row['provider'])
    monkeypatch.setattr(ingest, 'fetch_cdr_json', lambda *a, **k: pytest.fail('unavailable provider HTTP'))
    ingest.ingest_brand(brand, date_root=banks, resume=True, sleep_ms=0, timeout=1,
        max_retries=0, max_pages=None, max_products=None, fetch_unknown_detail=True,
        bank_dir_name=row['provider'], detail_workers=1, log=lambda _: None)
    ingest._persist_ingest_status(banks_root=banks, run_root=stage, snapshot=snapshot,
                                  bank_work=work, attempt_journal=journal)
    reuse.reconcile_same_day_reuse(stage)
    status = json.loads((banks / 'ingest-status.json').read_bytes())
    provider = next(item for item in status['provider_states'] if item['provider_dir'] == row['provider'])
    assert provider['state'] == 'not_attempted' and provider['population_known'] is False
    assert status['providers_attempted'] == 261 and status['providers_prd_unavailable'] == 45
    assert status['total'] == provider['failure_records'] == int(retained_failure)
    assert not status['unresolved_requests'] and not status['same_day_reuse']['withdrawals']
    assert status['same_day_reuse']['unconfirmed'] == [{'provider_dir': row['provider'], 'product_id': row['pid']}]
    assert (fixture._leaf(stage, row) / 'product-detail.json').read_bytes() == row['body']
    finalized = fixture._finalize_repair(state, stage, parent, 'unavailable')
    assert finalized['observation_state'] == 'partial'
    for name, original in baseline.items():
        # New ledger selection files legitimately change; original export bytes do not.
        if name.startswith('runs/'):
            assert (tmp_path / 'data' / name).read_bytes() == original


def test_unavailable_markers_without_count_fail_closed(tmp_path, monkeypatch):
    _, exports, _, status = capture(tmp_path, monkeypatch)
    status.pop('providers_prd_unavailable')
    status['providers_attempted'] = status['providers_registered']
    for provider in status['provider_states']: provider['state'] = 'complete'
    with pytest.raises(ValueError, match='count is missing'):
        current_register(exports, status, DAY)


@pytest.mark.parametrize('damage', ['negative', 'categories', 'rollup'])
def test_unavailable_retained_failure_counters_still_require_reconciliation(tmp_path, monkeypatch, damage):
    _, exports, _, status = capture(tmp_path, monkeypatch)
    provider = next(p for p in status['provider_states'] if p.get('prd_availability') == 'UNAVAILABLE')
    if damage == 'negative': provider['failure_records'] = -1
    elif damage == 'categories': provider['failure_categories'] = {'unknown': True}
    else: provider.update(failure_records=1, failure_categories={'unknown': 1})
    with pytest.raises(ValueError, match='failures do not reconcile'):
        current_register(exports, status, DAY)
