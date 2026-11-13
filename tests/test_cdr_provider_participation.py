"""Lifecycle protocol tests replaying untouched official register/provider captures."""
import hashlib
import json
import shutil

import pytest

from cdr_atomic import ImmutablePathError, atomic_write_json
from cdr_finalization import _coverage
from cdr_ingest_support import REGISTER_URL_SUMMARY, iter_banking_brands_from_payload
from cdr_population_lifecycle import reconcile_participation, participation_coverage
from cdr_population_sanity import compare_population_counts
from cdr_provider_participation_evidence import (
    EVIDENCE_ROOT, load_cessation_evidence, provider_uid,
)
from cdr_raw_attempt_journal import RawAttemptJournal

DAY = '2026-11-13'


def captured_population():
    entry = load_cessation_evidence()[0]
    identity = {'provider': 'Wise', 'provider_uid': entry['provider_uid'],
        'provider_dir': 'Wise', 'identity_status': 'verified_prior_register',
        'endpoint_url': entry['endpoint_url'], 'source_observation': {
            'observation_date': '2026-10-31', 'generation_id': 'obs-2026-10-31-' + '1' * 16,
            'contract_digest': '1' * 64, 'database_sha256': '2' * 64, 'ledger_event_digest': '3' * 64}}
    # Counts and source pointer are protocol metadata, never published product/rate fixtures.
    return {'status': 'WARN', 'findings': [{'provider': 'Wise', 'products_prev': 1,
        'products_curr': 0, 'rates_prev': 0, 'rates_curr': 0, 'severity': 'HIGH',
        'code': 'provider_population_disappeared', 'population_known': False,
        'disposition': 'UNVERIFIED_SOURCE_ABSENCE', 'provider_identity': identity}]}


def captured_status(root, day=DAY, payload=None):
    body = (EVIDENCE_ROOT / 'cessation-register.json').read_bytes() if payload is None else json.dumps(payload).encode()
    payload = json.loads(body)
    journal = RawAttemptJournal(root / 'attempt-evidence/raw-attempt-journals-v1', 'capture-' + day)
    journal.record('register', request_url=REGISTER_URL_SUMMARY, status=200,
                   outcome='success', body=body, started_at=day+'T00:00:00Z',
                   completed_at=day+'T00:00:01Z', context={'phase': 'register_discovery'})
    brands = list(iter_banking_brands_from_payload(payload))
    return {'register_provenance_complete': True, 'providers_registered': len(brands),
        'providers_attempted': len(brands), 'provider_states': [dict(brand, provider_uid=provider_uid(brand),
            state='complete') for brand in brands],
        'register_attempts': [{'ok': True, 'status': 200, 'source_url': REGISTER_URL_SUMMARY,
            'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)}],
        'raw_attempt_journal': {'verified': True, 'session_id': journal.session_id,
            'path': journal.root.relative_to(root).as_posix(),
            'path_resolution': 'relative_to_finalized_export_root'}}


def test_real_cessation_keeps_evidence_without_product_withdrawal(tmp_path):
    status = captured_status(tmp_path)
    population = captured_population()
    result = reconcile_participation(population, status, tmp_path, DAY)
    assert result['status'] == 'PASS' and result['findings'] == []
    assert population['status'] == 'WARN'  # no mutation of prior authority
    row = result['participation_cessations'][0]
    assert row['disposition'] == 'CDR_PARTICIPATION_CEASED'
    assert row['product_withdrawal_confirmed'] is False
    for source in row['sources'].values():
        assert hashlib.sha256((tmp_path / source['path']).read_bytes()).hexdigest() == source['sha256']
    atomic_write_json(tmp_path/'provider-population-report.json', {'run_date': DAY,'provider_population':result})
    assert participation_coverage(tmp_path, status, DAY) == result['participation_cessations']


@pytest.mark.parametrize('breakage', ['filtered', 'scope', 'stale', 'incomplete', 'digest',
                                      'wrong_uid', 'wrong_endpoint', 'unverified_identity', 'predates'])
def test_uncertain_or_unrelated_evidence_never_clears_warning(tmp_path, breakage):
    status = captured_status(tmp_path)
    population = captured_population()
    day = DAY
    if breakage == 'filtered':
        status['providers_attempted'] -= 1
        status['provider_states'].pop()
    elif breakage == 'scope':
        status['provider_states'][0]['provider_uid'] = 'different'
    elif breakage == 'stale':
        day = '2026-11-14'
    elif breakage == 'incomplete':
        status['register_provenance_complete'] = False
    elif breakage == 'digest':
        status['register_attempts'][0]['sha256'] = '0' * 64
    elif breakage in {'wrong_uid', 'wrong_endpoint', 'unverified_identity'}:
        field = {'wrong_uid': 'provider_uid', 'wrong_endpoint': 'endpoint_url',
                 'unverified_identity': 'identity_status'}[breakage]
        population['findings'][0]['provider_identity'][field] = 'unrelated'
    else:
        day = '2026-11-12'
        status = captured_status(tmp_path, day)
    result = reconcile_participation(population, status, tmp_path, day)
    assert result == population


@pytest.mark.parametrize('field', ['dataHolderBrandId', 'abn', 'acn', 'brandName', 'publicBaseUri'])
def test_any_current_registration_identity_revokes_cessation(tmp_path, field):
    payload = json.loads((EVIDENCE_ROOT/'cessation-register.json').read_bytes())
    prior = load_cessation_evidence()[0]['prior_registration']
    # Controlled registry mutation tests a renamed/reclassified entity. No rates invented.
    payload['data'][0][field] = prior[field]
    status = captured_status(tmp_path, payload=payload)
    population = captured_population()
    assert reconcile_participation(population, status, tmp_path, DAY) == population


def test_current_return_or_missing_proof_reopens_previous_disposition(tmp_path):
    status = captured_status(tmp_path)
    resolved = reconcile_participation(captured_population(), status, tmp_path, DAY)
    status['register_provenance_complete'] = False
    result = reconcile_participation(resolved, status, tmp_path, DAY)
    assert result['status'] == 'WARN' and len(result['findings']) == 1
    assert 'participation_cessations' not in result


def test_unknown_report_cannot_smuggle_a_cessation_disposition(tmp_path):
    status = captured_status(tmp_path)
    resolved = reconcile_participation(captured_population(), status, tmp_path, DAY)
    resolved['status'] = 'UNKNOWN'
    atomic_write_json(tmp_path/'provider-population-report.json', {'run_date': DAY, 'provider_population': resolved})
    with pytest.raises(ValueError, match='verified population comparison'):
        participation_coverage(tmp_path, status, DAY)


def test_next_day_rechecks_original_hold_instead_of_erasing_history(tmp_path):
    resolved = reconcile_participation(captured_population(), captured_status(tmp_path), tmp_path, DAY)
    unresolved = [row['unresolved_finding'] for row in resolved['participation_cessations']]
    following = compare_population_counts(({}, {}), ({}, {}), unresolved)
    status = captured_status(tmp_path, '2026-11-14')
    result = reconcile_participation(following, status, tmp_path, '2026-11-14')
    assert result['status'] == 'PASS'
    assert result['participation_cessations'][0]['observed_at'] == resolved['participation_cessations'][0]['observed_at']
    assert result['participation_cessations'][0]['applicable_observation_date'] == '2026-11-14'


@pytest.mark.parametrize('mutation', ['body', 'generic_422', 'prior_url', 'register_present'])
def test_unsupported_or_corrupt_evidence_is_not_cessation(tmp_path, mutation):
    shutil.copytree(EVIDENCE_ROOT, tmp_path/'evidence')
    root = tmp_path/'evidence'
    manifest = json.loads((root/'evidence.json').read_bytes())
    record = manifest['records'][0]
    if mutation == 'prior_url':
        record['response']['url'] = record['response']['final_url'] = 'https://unrelated.example/products'
    else:
        kind = 'cessation_register' if mutation == 'register_present' else 'response'
        path = root/record[kind]['path']
        body = ((root/'prior-register.json').read_bytes() if mutation == 'register_present'
                else b'{"errors":[{"title":"Unavailable"}]}')
        path.write_bytes(body)
        if mutation != 'body':
            record[kind].update(sha256=hashlib.sha256(body).hexdigest(), bytes=len(body))
    (root/'evidence.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        load_cessation_evidence(root)


def test_finalization_retains_lifecycle_proof_in_coverage(tmp_path):
    from tests.test_irreplaceable_finalization import make_export
    make_export(tmp_path, observation_date=DAY)
    status = captured_status(tmp_path)
    status.update(total=0, corrupt_records=0, failure_provenance_complete=True, incomplete=False)
    atomic_write_json(tmp_path/'ingest-status.json', status)
    population = reconcile_participation(captured_population(), status, tmp_path, DAY)
    atomic_write_json(tmp_path/'provider-population-report.json', {'run_date': DAY, 'provider_population':population})
    state, coverage, _, _ = _coverage(tmp_path)
    assert state == 'complete' and 'provider_population_unverified' not in coverage
    assert len(coverage['provider_participation_ceased']) == 1
    source = population['participation_cessations'][0]['sources']['response']['path']
    (tmp_path/source).write_bytes(b'corrupt')
    with pytest.raises(ImmutablePathError):
        _coverage(tmp_path)
