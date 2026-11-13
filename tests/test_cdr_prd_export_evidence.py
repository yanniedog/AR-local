"""Export absence authority requires the retained register, before any outputs."""
import hashlib
import json

import pytest

from cdr_clean_export import parse_banks_run
from cdr_ingest_support import FINANCIAL_PRD_INDUSTRIES
from cdr_outputs import build_outputs
from cdr_provider_participation_evidence import current_register
from tests.test_cdr_financial_register import retained
from tests.test_cdr_prd_availability import DAY, capture


def raw_status(run):
    path = run / 'banks/ingest-status.json'
    return path, json.loads(path.read_bytes())


@pytest.mark.parametrize('damage', ['digest', 'version', 'date', 'count', 'directory',
    'brand', 'entity', 'endpoint', 'pointer', 'head', 'missing_journal', 'missing_count'])
def test_exports_reject_unverified_absence_before_writing(tmp_path, monkeypatch, damage):
    run, _, _, _ = capture(tmp_path, monkeypatch)
    path, status = raw_status(run)
    provider = next(row for row in status['provider_states'] if row.get('prd_availability') == 'UNAVAILABLE')
    if damage == 'digest': provider['prd_availability_evidence']['register_body_sha256'] = '0' * 64
    elif damage == 'version': status['register_attempts'][0]['version'] = 1
    elif damage == 'count': status['providers_prd_unavailable'] -= 1
    elif damage == 'directory': provider['provider_dir'] = 'Westpac'
    elif damage in {'brand', 'entity', 'endpoint'}:
        key = {'brand': 'brand_name', 'entity': 'legal_entity_name', 'endpoint': 'endpoint_url'}[damage]
        provider[key] = 'different identity with unchanged UID'
    elif damage == 'pointer': status['raw_attempt_journal']['path_resolution'] = 'relative_to_finalized_export_root'
    elif damage == 'head': status['raw_attempt_journal']['head_digest'] = '0' * 64
    elif damage == 'missing_count': status.pop('providers_prd_unavailable')
    elif damage == 'missing_journal': status.pop('raw_attempt_journal')
    path.write_text(json.dumps(status), encoding='utf-8')
    if damage == 'date':
        later = run.with_name('2026-11-14')
        run.rename(later)
        run = later
    with pytest.raises((ValueError, KeyError)):
        build_outputs(run)
    assert not (run / '_exports').exists()


def test_raw_and_promoted_proof_are_explicit_readonly_modes(tmp_path, monkeypatch):
    run, exports, _, promoted = capture(tmp_path, monkeypatch)
    _, raw = raw_status(run)
    def inventory():
        return {path.relative_to(run).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in run.rglob('*') if path.is_file()}
    before = inventory()
    parsed = parse_banks_run(run)
    assert len(parsed['prd_unavailable']) == 44
    assert inventory() == before
    with pytest.raises(ValueError, match='bound raw evidence'):
        current_register(run, raw, DAY)
    with pytest.raises(ValueError, match='bound raw evidence'):
        current_register(exports, promoted, DAY, ingest_root=True)
    assert len(current_register(exports, promoted, DAY)[1]['prd_unavailable']) == 44


@pytest.mark.parametrize('filtered', [False, True])
def test_canonical_directories_follow_sorted_filtered_capture_order(tmp_path, monkeypatch, filtered):
    # Two retained unavailable registrations; vary names only to exercise a
    # sanitized collision and deliberately reverse their register order.
    payload = json.loads(retained('register.json'))
    absent = [row for row in payload['data'] if row.get('productBaseUri') is None
              and set(row['industries']) & FINANCIAL_PRD_INDUSTRIES]
    assert len(absent) >= 2
    absent[0]['brandName'], absent[1]['brandName'] = 'Routing : collision', 'Routing / collision'
    run, _, snapshot, _ = capture(tmp_path, monkeypatch, register_body=json.dumps(payload).encode(),
                                 holders_filter='Routing /' if filtered else 'Routing')
    _, status = raw_status(run)
    parsed = parse_banks_run(run)
    assert len(parsed['prd_unavailable']) == (1 if filtered else 2)
    directories = [row['provider_dir'] for row in status['provider_states']]
    assert len(set(directories)) == len(directories)
    assert [row['brand_name'] for row in status['provider_states']] == [row['brand_name'] for row in snapshot.banking_brands]
    if filtered:
        assert not directories[0].endswith('_host')
    else:
        assert directories[1].startswith(directories[0] + '_')


def test_legacy_zero_unavailability_does_not_require_new_raw_proof(tmp_path):
    run = tmp_path / DAY
    path = run / 'banks/ingest-status.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'providers_prd_unavailable': 0,
                               'provider_states': [{'state': 'failed'}]}), encoding='utf-8')
    assert parse_banks_run(run)['prd_unavailable'] == []


def test_conflicting_raw_response_version_cannot_authorize_export(tmp_path, monkeypatch):
    run, _, _, _ = capture(tmp_path, monkeypatch, response_version='1')
    with pytest.raises(ValueError, match='register v2'):
        parse_banks_run(run)
