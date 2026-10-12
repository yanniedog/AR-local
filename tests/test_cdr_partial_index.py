"""Replay the malformed retained Geelong index without inventing its missing ID."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

import cdr_ingest_lib as ingest
import cdr_ingest_support as support
import pi_cdr_recovery as recovery
import pi_cdr_recovery_probe as probe
from cdr_compatibility import response_shape_error
from cdr_atomic import canonical_json_bytes
from cdr_export_contract import load_contract
from cdr_finalization import finalize_observation
from cdr_http_policy import PolicyResponse
from cdr_ingest_recovery import _index_captured
from cdr_observation_selection import _verified_withdrawal_index
from cdr_partial_index import partial_index_evidence, partial_probe_has_progress
from cdr_raw_attempt_journal import RawAttemptJournal
from cdr_same_day_reuse import _successful_body
from scripts.ingest_notification_snapshot import _count_failures
from tests.test_pi_same_day_recovery import NOW, stage

RAW = (Path(__file__).parent / 'fixtures/cdr-index-failures-20261012/geelong-index.json').read_bytes()
BODY = RAW.decode('utf-8')
VALUE = json.loads(RAW)
SHA = '22d9b04e4ffca25f1850478209789944ea4e067fe384854f6c3775f1a9689a68'
URL = VALUE['links']['self']
IDS = {row['productId'] for row in VALUE['data']['products'] if row['productId']}


def transport(monkeypatch, raw=RAW, status=200):
    response = PolicyResponse(status, URL, {}, raw, len(raw), len(raw),
                              hashlib.sha256(raw).hexdigest(), None, ())
    monkeypatch.setattr(support, 'request_https', lambda *a, **k: response)
    monkeypatch.setattr(support, 'attempt_utc_now', lambda: '2026-10-11T14:05:24.681605Z')


def fetch(monkeypatch, *, partial=False):
    transport(monkeypatch)
    return support.fetch_cdr_json(URL, versions=[5], timeout=5, max_retries=0,
        sleep_ms=0, attempt_context={'phase': 'products_index'}, allow_partial_index=partial)


def test_partial_capture_is_explicit_and_strict_validator_is_unchanged(monkeypatch):
    assert hashlib.sha256(RAW).hexdigest() == SHA
    assert response_shape_error(VALUE, phase='products_index')
    assert not fetch(monkeypatch).ok
    result = fetch(monkeypatch, partial=True)
    assert result.ok and result.text == BODY and result.attempts == 1
    assert result.partial_index == {'raw_records': 18, 'identified_records': 17,
        'unidentified_records': 1, 'omitted_row_positions': [17], 'unique_products': 17}


@pytest.mark.parametrize('fault', ['all_missing', 'nonobject', 'links', 'meta', 'next'])
def test_partial_capture_does_not_accept_other_shape_faults(fault):
    value = copy.deepcopy(VALUE)
    if fault == 'all_missing':
        for row in value['data']['products']:
            row['productId'] = ''
    elif fault == 'nonobject':
        value['data']['products'][0] = None
    elif fault == 'next':
        value['links']['next'] = 1
    else:
        value[fault] = []
    assert partial_index_evidence(value) is None


def capture(tmp_path, monkeypatch, raw=RAW):
    transport(monkeypatch, raw)
    dispatched = []
    def detail(work, *a, **k):
        dispatched.append(work.pid)
        return ingest._DetailOutcome(True, True)
    monkeypatch.setattr(ingest, '_fetch_bank_detail', detail)
    brand = {'brand_name': 'Geelong Bank', 'endpoint_url': URL}
    directory = support.allocate_bank_dir(brand['brand_name'], '', URL, set())
    journal = RawAttemptJournal(tmp_path / 'attempt-evidence/raw-attempt-journals-v1', 'partial-index')
    ingest.ingest_brand(brand, date_root=tmp_path, resume=False, sleep_ms=0, timeout=5,
        max_retries=0, max_pages=None, max_products=None, fetch_unknown_detail=False,
        bank_dir_name=directory, detail_workers=1, log=lambda _: None, attempt_journal=journal)
    events = list(journal.events.glob('*.json'))
    assert len(events) == 1
    event = json.loads(events[0].read_bytes())
    assert event['context']['phase'] == 'products_index' and event['context']['provider'] == directory
    assert event['response']['body_sha256'] == hashlib.sha256(raw).hexdigest()
    assert (journal.root / event['body_path']).read_bytes() == raw
    # Register receipt is a protocol control; no fabricated financial rows.
    snapshot = support.RegisterSnapshot(True, True, [{'ok': True, 'sha256': 'a' * 64}], [brand], 1)
    status = ingest._persist_ingest_status(banks_root=tmp_path, run_root=tmp_path,
        snapshot=snapshot, bank_work=[(brand, directory)], attempt_journal=journal)
    return status, directory, dispatched, journal, event


def test_valid_rows_dispatch_while_provider_omission_and_unknown_population_survive(tmp_path, monkeypatch):
    status, provider, dispatched, journal, event = capture(tmp_path, monkeypatch)
    assert len(dispatched) == 17 and set(dispatched) == IDS
    failure = json.loads((tmp_path / 'failures.jsonl').read_text())
    assert failure['source_body_sha256'] == SHA and failure['unidentified_records'] == 1
    assert failure['phase'] == 'products_index' and not failure.get('product_id')
    assert status['total'] == 1 and status['unattributed_records'] == status['corrupt_records'] == 0
    assert status['provider_states'][0]['state'] == 'partial'
    assert status['provider_states'][0]['failure_categories'] == {'invalid_response': 1}
    diagnostic = status['index_diagnostics'][provider]
    assert diagnostic['raw_records'] == 18 and diagnostic['unique_products'] == 17
    assert diagnostic['pagination_complete'] is False and diagnostic['partial_index_body_sha256s'] == [SHA]
    assert _count_failures(status) == {'failed_request_records': 1, 'known_failed_products': 0,
        'failed_providers': 1, 'providers_with_unknown_product_population': 1, 'product_count_is_lower_bound': True}
    assert _successful_body(journal, event, 'products_index') is None
    assert _index_captured(tmp_path, provider) is False


def test_replacement_decoding_never_changes_original_response_identity(tmp_path, monkeypatch):
    # Protocol corruption only: retain every original product row unchanged.
    raw = RAW.replace(b'{', b'{"protocol_test":"\xff",', 1)
    status, provider, _, journal, event = capture(tmp_path, monkeypatch, raw)
    digest = hashlib.sha256(raw).hexdigest()
    assert digest != hashlib.sha256(raw.decode('utf-8', errors='replace').encode()).hexdigest()
    failure = json.loads((tmp_path / 'failures.jsonl').read_text())
    assert failure['source_body_sha256'] == digest == event['response']['body_sha256']
    assert status['index_diagnostics'][provider]['partial_index_body_sha256s'] == [digest]
    monkeypatch.setattr(probe, 'request_https', lambda *a, **k: SimpleNamespace(status=200, body=raw))
    report = probe.probe_request(URL, phase='products_index', deadline=probe.time.monotonic() + 60,
                                allow_partial_index=True)
    assert report['ok'] is False and report['attempts'][0]['body_sha256'] == digest


def test_many_partial_pages_keep_diagnostics_available_and_all_failures_bound(tmp_path, monkeypatch):
    def request(url, *a, **k):
        number = int(parse_qs(urlsplit(url).query).get('page', ['1'])[0])
        # Repeat retained products to exercise pagination accounting, not new rates.
        value = copy.deepcopy(VALUE)
        value['meta'] = {'totalRecords': 60 * 18, 'totalPages': 60}
        value['links']['self'] = url
        value['links']['next'] = URL + f'?page={number + 1}' if number < 60 else None
        raw = canonical_json_bytes(value)
        return PolicyResponse(200, url, {}, raw, len(raw), len(raw), hashlib.sha256(raw).hexdigest(), None, ())
    monkeypatch.setattr(support, 'request_https', request)
    monkeypatch.setattr(ingest, '_fetch_bank_detail', lambda *a, **k: ingest._DetailOutcome(True, True))
    brand, provider = {'brand_name': 'Geelong Bank', 'endpoint_url': URL}, 'Geelong Bank'
    ingest.ingest_brand(brand, date_root=tmp_path, resume=False, sleep_ms=0, timeout=5,
        max_retries=0, max_pages=None, max_products=None, fetch_unknown_detail=False,
        bank_dir_name=provider, detail_workers=1, log=lambda _: None)
    path = tmp_path / '_holders' / provider / '_products-index/diagnostics.json'
    assert path.stat().st_size <= 4096
    diagnostic = ingest._provider_index_diagnostics(tmp_path, [(brand, provider)])[provider]
    assert diagnostic['unique_products'] == 17 and diagnostic['raw_records'] == 1080
    assert diagnostic['partial_index_body_count'] == 60
    assert diagnostic['partial_index_body_hashes_complete'] is False
    assert len(diagnostic['partial_index_body_sha256s']) == 32
    failures = [json.loads(row) for row in (tmp_path / 'failures.jsonl').read_text().splitlines()]
    assert len(failures) == 60 and len({row['source_body_sha256'] for row in failures}) == 60
    # Failure to keep the bounded reader usable used to disable every later probe.
    report = {'body_sha256': 'f' * 64, 'partial_index': {'unique_products': 18}}
    assert partial_probe_has_progress(report, {'provider_dir': provider, 'request_key': 'r'},
        {'status': {'index_diagnostics': {provider: diagnostic}}}, [])


def test_maximum_partial_proofs_fit_durable_history_without_omission_arrays(tmp_path, monkeypatch):
    value = {'data': {'products': [VALUE['data']['products'][0], *([{}] * 8191)]},
             'meta': {'totalRecords': 8192, 'totalPages': 1}, 'links': {}}
    raw = canonical_json_bytes(value)
    monkeypatch.setattr(probe, 'request_https', lambda *a, **k: SimpleNamespace(status=200, body=raw))
    report = probe.probe_request(URL, phase='products_index', deadline=probe.time.monotonic() + 60,
                                allow_partial_index=True)
    report.pop('data')  # Same boundary as the production _probe_due path.
    assert report['partial_index'] == {'raw_records': 8192, 'identified_records': 1,
                                      'unidentified_records': 8191, 'unique_products': 1}
    proofs = [{**report, 'request_key': str(number)} for number in range(recovery.MAX_PROBES_PER_TICK)]
    reservation = recovery._reserve(tmp_path, '2026-09-07', 'g1', 'capture', NOW, proofs=proofs)
    assert next(tmp_path.glob('*.reserved.json')).stat().st_size < 4096
    assert recovery._history(tmp_path, '2026-09-07') == [reservation]


def test_nested_json_probe_preserves_terminal_authentication_status(monkeypatch):
    raw = ('[' * 2000 + 'null' + ']' * 2000).encode()
    monkeypatch.setattr(probe, 'request_https', lambda *a, **k: SimpleNamespace(status=401, body=raw))
    report = probe.probe_request(URL, phase='products_index', deadline=probe.time.monotonic() + 60,
                                allow_partial_index=True)
    assert report['ok'] is False and len(report['attempts']) == 1
    assert report['attempts'][0]['failure_category'] == 'public_endpoint_auth_required'


@pytest.mark.parametrize('nonempty_rates', [False, True])
def test_finalized_partial_stays_honest_and_publication_requires_nonempty_rates(tmp_path, monkeypatch, nonempty_rates):
    from app_payload_observation_gate import contract_coverage, publication_allowed
    from app_payload_source_verification import verify_reconciled_source
    root, state = tmp_path / 'runs/2026-10-12/_exports', tmp_path / 'state'
    root.mkdir(parents=True)
    status, provider, dispatched, journal, event = capture(root, monkeypatch)
    # Exercise finalization's counter protocol, not live/financial acceptance.
    # The nonzero rate counter comes from a retained real detail fixture; this
    # test does not fabricate a Geelong detail or claim that one was captured.
    defence = json.loads((Path(__file__).parent / 'fixtures/cdr-september7/defence.json').read_bytes())
    rates = len(defence['product_detail']['body']['data']['depositRates']) if nonempty_rates else 0
    counts = {'products': len(dispatched), 'rates': rates}
    (root / 'dashboard-cache').mkdir()
    (root / 'dashboard-cache/latest.json').write_bytes(canonical_json_bytes({
        'run_date': '2026-10-12', 'banks_counts': counts}))
    marker = finalize_observation(root, state, state / '2026-10-12.done.json',
        observation_date='2026-10-12', result={'run_date': '2026-10-12', 'banks_counts': counts})
    contract = load_contract(state / marker['export_contract_path'])
    assert contract['observation_state'] == 'partial'
    coverage = contract_coverage(contract)
    assert coverage['failure_records'] == coverage['providers_partial'] == 1
    assert coverage['unattributed_failure_records'] == coverage['corrupt_failure_records'] == 0
    assert publication_allowed(contract)[0] is nonempty_rates
    assert verify_reconciled_source(state, root, '2026-10-12', contract) is nonempty_rates
    # Even an adversarial complete-index claim cannot use these immutable raw
    # bytes as withdrawal evidence, or erase the unknown product population.
    page = {'body_sha256': SHA, 'event_digest': event['event_digest'],
        'event_seq': event['sequence'], 'journal_session_id': journal.session_id}
    proof = {'complete': True, 'pages': [page], 'observed_product_ids': sorted(IDS),
        'fresh_index_sha256': hashlib.sha256(canonical_json_bytes({'page_body_sha256': [SHA]})).hexdigest()}
    observation = {'status': status, 'export_root': root, 'contract': contract}
    with pytest.raises(ValueError, match='incomplete'):
        _verified_withdrawal_index(observation, provider, proof)
    tampered = copy.deepcopy(status)
    tampered['index_diagnostics'][provider]['pagination_complete'] = True
    with pytest.raises(ValueError, match='body is invalid'):
        _verified_withdrawal_index({**observation, 'status': tampered}, provider, proof)


@pytest.mark.parametrize('partial,status,accepted', [(False, 200, False), (True, 200, True), (True, 404, False)])
def test_probe_partial_evidence_never_claims_complete_capture(monkeypatch, partial, status, accepted):
    monkeypatch.setattr(probe, 'request_https', lambda *a, **k: SimpleNamespace(status=status, body=RAW))
    result = probe.probe_request(URL, phase='products_index', deadline=probe.time.monotonic() + 60,
                                allow_partial_index=partial)
    assert result['ok'] is accepted and result['complete_capture'] is False
    assert all(attempt['valid'] is False for attempt in result['attempts'])


@pytest.mark.parametrize('previous,hashes,history,expected', [
    (0, [], [], True), (17, [], [], False), (None, [], [], False),
    (0, [SHA], [], False), (0, [], [{'kind': 'capture', 'proofs': [
        {'request_key': 'r', 'body_sha256': SHA}]}], False),
])
def test_partial_progress_requires_new_population_and_never_repeats_identical_capture(previous, hashes, history, expected):
    observation = {'status': {'index_diagnostics': {'Geelong Bank': {
        'unique_products': previous, 'partial_index_body_sha256s': hashes}}}}
    request = {'provider_dir': 'Geelong Bank', 'request_key': 'r'}
    report = {'partial_index': partial_index_evidence(VALUE), 'body_sha256': SHA}
    assert partial_probe_has_progress(report, request, observation, history) is expected


def test_unselected_partial_capture_cannot_spend_budget_again_after_cooldown(tmp_path, monkeypatch):
    from datetime import timedelta
    state, observation = stage(monkeypatch, tmp_path)
    observation['status']['index_diagnostics'] = {'Provider': {'unique_products': 0}}
    observation['status']['unresolved_requests'][0].update(phase='products_index', product_id='')
    monkeypatch.setattr(recovery, 'probe_request', lambda *a, **k: {
        'ok': True, 'body_sha256': SHA, 'partial_index': partial_index_evidence(VALUE)})
    launch = Mock()
    first = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=launch)
    assert launch.call_count == 1 and first['selection_advanced'] is False
    second = recovery.run_same_day_recovery(tmp_path, now_utc=NOW + timedelta(hours=3), dry_run=False, launch=launch)
    assert launch.call_count == 1 and second['status'] == 'upstream_gaps_remain'
    assert second['probes'][0]['failure_category'] == 'unchanged_partial_index'
