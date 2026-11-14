"""Replay official register v2 absence without fabricating product/HTTP results."""
import hashlib
import json

import pytest

import cdr_ingest_lib as ingest
import cdr_ingest_support as support
from cdr_atomic import atomic_write_json
from cdr_attempt_evidence_promotion import promote_attempt_evidence
from cdr_clean_export import coverage_summary, parse_banks_run
from cdr_finalization import _coverage
from cdr_provider_participation_evidence import current_register
from cdr_raw_attempt_journal import RawAttemptJournal
from tests.test_cdr_financial_register import retained

DAY = '2026-11-13'


def capture(tmp_path, monkeypatch, *, response_version='2', register_hour_utc='00',
            register_body=None, holders_filter=None):
    body = register_body if register_body is not None else retained('register.json')
    monkeypatch.setattr(support, 'fetch_cdr_json', lambda *args, **kwargs:
        support.FetchResult(True, 200, support.REGISTER_URL_SUMMARY, body.decode(), version=2))
    snapshot = support.collect_register_snapshot(timeout=1, max_retries=0, sleep_ms=0, holders_filter=holders_filter)
    run = tmp_path / DAY
    journal = RawAttemptJournal(run/'_raw-attempt-journals-v1', 'capture-'+DAY)
    journal.record('register', request_url=support.REGISTER_URL_SUMMARY,
        request_headers={'x-v': '2', 'x-min-v': '2'}, status=200, outcome='success', body=body,
        response_headers={} if response_version is None else {'x-v': response_version},
        started_at=DAY+f'T{register_hour_utc}:00:00Z', completed_at=DAY+f'T{register_hour_utc}:00:01Z',
        context={'phase': 'register_discovery', 'cdr_version': 2})
    banks = run/'banks'; banks.mkdir(); (banks/'failures.jsonl').write_bytes(b'')
    seen = set()
    work = [(row, support.allocate_bank_dir(row['brand_name'], row['legal_entity_name'],
                                            row['endpoint_url'], seen)) for row in snapshot.banking_brands]
    status = ingest._persist_ingest_status(banks_root=banks, run_root=run,
        snapshot=snapshot, bank_work=work, attempt_journal=journal)
    exports = tmp_path/'exports'
    promote_attempt_evidence(run, exports)
    status = json.loads((exports/'ingest-status.json').read_bytes())
    return run, exports, snapshot, status


def test_actual_v2_discovery_keeps306_but_only262_prd_endpoints(tmp_path, monkeypatch):
    _, exports, snapshot, status = capture(tmp_path, monkeypatch)
    unavailable = [row for row in snapshot.banking_brands if row.get('prd_availability') == 'UNAVAILABLE']
    assert len(snapshot.banking_brands) == status['providers_registered'] == 306
    assert len(unavailable) == status['providers_prd_unavailable'] == 44
    assert status['providers_attempted'] == 262
    assert status['incomplete'] is True and status['total'] == 0
    rows, evidence = current_register(exports, status, DAY)
    assert len(rows) == 390 and len(evidence['prd_unavailable']) == 44
    assert all(row['population_known'] is False and row['product_withdrawal_confirmed'] is False
               for row in evidence['prd_unavailable'])
    assert {row['register_body_sha256'] for row in evidence['prd_unavailable']} == {
        hashlib.sha256(retained('register.json')).hexdigest()}


@pytest.mark.parametrize('version', [None, 1, 3])
def test_historical_or_unknown_version_does_not_infer_absence(version):
    rows = list(support.iter_banking_brands_from_payload(
        json.loads(retained('register.json')), register_version=version))
    assert len(rows) == 306 and not any(row.get('prd_availability') == 'UNAVAILABLE' for row in rows)


def test_null_v2_field_has_same_absence_meaning_but_empty_string_does_not():
    payload = json.loads(retained('register.json'))
    row = next(r for r in payload['data'] if r['brandName'] == 'AAA Mortgage Finance')
    for value, unavailable in ((None, True), ('', False)):
        row['productBaseUri'] = value
        result = list(support.iter_banking_brands_from_payload({'data': [row]}, register_version=2))[0]
        assert (result.get('prd_availability') == 'UNAVAILABLE') is unavailable


def test_absence_without_registration_identity_stays_unverified():
    row = next(r for r in json.loads(retained('register.json'))['data']
               if r['brandName'] == 'AAA Mortgage Finance')
    row.pop('dataHolderBrandId', None); row.pop('interimId', None)
    result = list(support.iter_banking_brands_from_payload({'data': [row]}, register_version=2))[0]
    assert 'prd_availability' not in result


@pytest.mark.parametrize('kind', ['failed', 'legacy', 'filtered', 'truncated'])
def test_legacy_and_incomplete_register_captures_still_finalize_partial(tmp_path, kind):
    # No promoted journal is available: invoking new strict proof would fail.
    exports = tmp_path/'exports'
    atomic_write_json(exports/'dashboard-cache/latest.json', {'run_date': DAY, 'banks_counts': {}})
    atomic_write_json(exports/'ingest-status.json', {
        'incomplete': True, 'providers_registered': 2, 'providers_attempted': 1,
        'provider_states': [{'provider_uid': 'legacy-prd:'+'1'*64, 'state': 'failed'}],
        'failure_provenance_complete': kind != 'failed', 'register_provenance_complete': kind == 'filtered',
        'register_attempts': [{'sha256': '1'*64, 'ok': kind == 'filtered'}],
        'providers_prd_unavailable': 0})  # Existing/prospective zero is not new authority.
    assert _coverage(exports)[0] == 'partial'


def test_truncated_register_does_not_gain_absence_authority(monkeypatch):
    payload = json.loads(retained('register.json')); payload['meta'] = {'totalRecords': 999}
    monkeypatch.setattr(support, 'fetch_cdr_json', lambda *a, **k:
        support.FetchResult(True, 200, support.REGISTER_URL_SUMMARY, json.dumps(payload), version=2))
    result = support.collect_register_snapshot(timeout=1, max_retries=0, sleep_ms=0, holders_filter=None)
    assert not result.register_provenance_complete
    assert not any(row.get('prd_availability') == 'UNAVAILABLE' for row in result.banking_brands)


def test_unavailable_holder_performs_no_http_or_empty_index(tmp_path, monkeypatch):
    run, _, snapshot, _ = capture(tmp_path, monkeypatch)
    brand = next(row for row in snapshot.banking_brands if row['brand_name'] == 'AAA Mortgage Finance')
    def forbidden(*args, **kwargs):
        pytest.fail('unavailable PRD must not be fetched')
    monkeypatch.setattr(ingest, 'fetch_cdr_json', forbidden)
    ingest.ingest_brand(brand, date_root=run/'banks', resume=False, sleep_ms=0, timeout=1,
        max_retries=0, max_pages=None, max_products=None, fetch_unknown_detail=True,
        bank_dir_name=brand['brand_name'], detail_workers=1, log=lambda _: None)
    holder = run/'banks/_holders'/brand['brand_name']
    assert (holder/'_register-brand.json').is_file()
    assert not (holder/'_products-index').exists()
    parsed = parse_banks_run(run)
    assert len(parsed['prd_unavailable']) == 44 and parsed['holder_attempts'] == []
    coverage = coverage_summary(parsed, DAY)
    assert coverage['counts']['providers_succeeded'] == 0
    assert coverage['counts']['providers_prd_unavailable'] == 44


def test_finalization_remains_partial_without_regressing_verified_provenance(tmp_path, monkeypatch):
    _, exports, _, status = capture(tmp_path, monkeypatch)
    atomic_write_json(exports/'dashboard-cache/latest.json', {'run_date': DAY, 'banks_counts': {'products': 12, 'rates': 0}})
    state, coverage, providers, _ = _coverage(exports)
    assert state == 'partial'
    assert coverage['failure_provenance_complete'] is True
    assert coverage['providers_registered'] == 306 and coverage['providers_attempted'] == 262
    assert coverage['providers_prd_unavailable'] == 44
    assert coverage['failure_records'] == 0
    assert len(coverage['provider_prd_unavailable']) == 44
    assert all(row['state'] == 'not_attempted' for row in providers if row.get('prd_availability') == 'UNAVAILABLE')
    from cdr_finalization import finalize_observation
    from cdr_export_contract import load_contract
    result = finalize_observation(exports, tmp_path/'state', tmp_path/'state'/f'{DAY}.done.json',
                                  observation_date=DAY, result={'run_date': DAY, 'banks_counts': {'rates': 0}})
    contract = load_contract(tmp_path/'state'/result['export_contract_path'])
    assert contract['observation_state'] == 'partial'
    assert contract['coverage']['providers_prd_unavailable'] == 44


def test_filtered_absence_is_verified_but_cannot_claim_full_scope(tmp_path, monkeypatch):
    _, exports, _, status = capture(tmp_path, monkeypatch)
    status['provider_states'] = [next(row for row in status['provider_states']
                                    if row.get('prd_availability') == 'UNAVAILABLE')]
    status.update(providers_attempted=0, providers_prd_unavailable=1)
    atomic_write_json(exports/'ingest-status.json', status)
    atomic_write_json(exports/'dashboard-cache/latest.json', {'run_date': DAY, 'banks_counts': {}})
    with pytest.raises(ValueError, match='incomplete or filtered'):
        current_register(exports, status, DAY)
    state, coverage, providers, _ = _coverage(exports)
    assert state == 'partial' and coverage['failure_provenance_complete'] is False
    assert coverage['providers_registered'] == 306 and coverage['providers_prd_unavailable'] == 1
    assert providers[0]['state'] == 'not_attempted'


def test_previously_observed_unavailable_provider_stays_unattempted(tmp_path, monkeypatch):
    _, exports, _, status = capture(tmp_path, monkeypatch)
    provider = next(row for row in status['provider_states'] if row.get('prd_availability') == 'UNAVAILABLE')
    atomic_write_json(exports/'dashboard-cache/latest.json', {'run_date': DAY, 'banks_counts': {}})
    atomic_write_json(exports/'provider-population-report.json', {'run_date': DAY, 'provider_population': {
        'status': 'WARN', 'findings': [{'provider': provider['provider_dir'],
            'code': 'provider_population_disappeared', 'population_known': False,
            'disposition': 'UNVERIFIED_SOURCE_ABSENCE'}]}})
    state, coverage, providers, _ = _coverage(exports)
    assert state == 'partial' and coverage['failure_provenance_complete'] is True
    matched = next(row for row in providers if row['provider_uid'] == provider['provider_uid'])
    assert matched['state'] == 'not_attempted' and matched['population_known'] is False
    assert len(coverage['provider_population_unverified']) == 1


@pytest.mark.parametrize('damage', ['digest', 'version', 'state', 'count', 'zero_count', 'requestable', 'population'])
def test_forged_or_missing_disposition_evidence_fails_closed(tmp_path, monkeypatch, damage):
    _, exports, _, status = capture(tmp_path, monkeypatch)
    row = next(r for r in status['provider_states'] if r.get('prd_availability') == 'UNAVAILABLE')
    if damage == 'digest': row['prd_availability_evidence']['register_body_sha256'] = '0'*64
    elif damage == 'version': status['register_attempts'][0]['version'] = 1
    elif damage == 'state': row['state'] = 'complete'
    elif damage == 'count': status['providers_prd_unavailable'] -= 1
    elif damage == 'zero_count':
        status['providers_prd_unavailable'] = 0; status['providers_attempted'] = 306
        for item in status['provider_states']: item['state'] = 'complete'
    elif damage == 'requestable':
        other = next(r for r in status['provider_states'] if r.get('prd_availability') != 'UNAVAILABLE')
        other.update(state='not_attempted', prd_availability='UNAVAILABLE', population_known=False)
        status['providers_attempted'] -= 1; status['providers_prd_unavailable'] += 1
    else: row['population_known'] = True
    with pytest.raises(ValueError): current_register(exports, status, DAY)


@pytest.mark.parametrize('response_version', [None, '1'])
def test_request_v2_binding_survives_missing_header_but_rejects_conflict(tmp_path, monkeypatch, response_version):
    _, exports, _, status = capture(tmp_path, monkeypatch, response_version=response_version)
    if response_version is None:
        assert len(current_register(exports, status, DAY)[1]['prd_unavailable']) == 44
    else:
        with pytest.raises(ValueError, match='register v2'): current_register(exports, status, DAY)


def test_unavailable_population_never_implies_product_removal():
    from cdr_outputs import _exclude_failed_missing_product_groups
    # Metadata-only guard test; no invented rate values or published products.
    key = ('aaa mortgage finance', 'retained-product', 'Mortgage')
    groups, result = _exclude_failed_missing_product_groups([(key, [])], [], [],
        current_providers=[], unavailable_providers=['AAA Mortgage Finance'])
    assert list(groups) == []
    assert result['suppressed'] == 1 and result['reasons'] == {'provider_prd_unavailable': 1}


def test_live_reconciliation_keeps_capture_date_across_midnight(tmp_path, monkeypatch):
    from datetime import datetime
    import pi_live_financial_worker as worker

    # Retained register bytes; only timing controls vary. Capture starts23:00
    # Hobart and finishes00:10, inside the unchanged00:30 absolute cutoff.
    _, exports, _, status = capture(tmp_path, monkeypatch, register_hour_utc='12')

    class AfterMidnight(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 14, 0, 10, tzinfo=worker.TZ).astimezone(tz)

    monkeypatch.setattr(worker, 'datetime', AfterMidnight)
    assert worker.datetime.now(worker.TZ).date().isoformat() != DAY
    report = worker.reconcile_register(exports, status, DAY)
    assert report['registered'] == 306 and report['attempted'] == 262
    assert len(report['prd_unavailable']) == 44
    with pytest.raises(ValueError, match='stale'):
        worker.reconcile_register(exports, status, '2026-11-14')
