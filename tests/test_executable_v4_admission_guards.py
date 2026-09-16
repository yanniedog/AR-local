"""Publication and independent review must reject unsafe activity candidates."""
import copy
import gzip
import json
from pathlib import Path
import pytest
from cdr_terms.executable_v4_inputs import check_inputs
from cdr_terms.executable_v4_financial import verify_financial
from cdr_terms.executable_eligibility import verify_eligibility


@pytest.fixture
def positive():
    bridge = json.loads(gzip.decompress((Path(__file__).parent / 'fixtures/activity-v4/actual-bridge.json.gz').read_bytes()))
    record = next(r for r in bridge['records'] if r['name'] == 'positive')
    return bridge['selection']['subject'], record['rawInput']['inputs'], record['result']


@pytest.mark.parametrize('changed', [False, True])
def test_repeated_transaction_id_is_refused(positive, changed):
    subject, inputs, _ = positive
    duplicate = copy.deepcopy(inputs['activity']['events'][0])
    if changed:
        duplicate['amount'] = '999.00'
    inputs['activity']['events'].append(duplicate)
    with pytest.raises(ValueError, match='duplicate event identity'):
        check_inputs(subject, inputs)


@pytest.mark.parametrize('state', ['does_not_meet', 'needs_information'])
def test_ineligible_claim_is_withheld_and_valid_withholding_passes(positive, state):
    subject, inputs, result = positive
    rule = subject['policy']['eligibility']
    rule['field'] = 'eligibility_control'
    facts = result['calculationInputs']['scenario']['facts']
    if state == 'does_not_meet':
        facts['eligibility_control'] = dict(type='decimal', value='-1', unit=rule['expected']['unit'])
    receipt = result['receipt']
    receipt['eligibility'] = verify_eligibility(rule, facts)
    assert receipt['eligibility']['status'] == state
    with pytest.raises(ValueError, match='eligibility or claim'):
        verify_financial(result, subject, inputs)
    receipt.update(status='incomplete', completeness='incomplete', claimAvailable=False, issues=['eligibility:' + state])
    verify_financial(result, subject, inputs)


@pytest.mark.parametrize('field,value', [('completeness', 'conditional_complete'), ('issues', ['extra']),
    ('assumptions', ['unverified']), ('issueDetails', [dict(index=0, code='extra')]), ('schemaVersion', 2)])
def test_receipt_metadata_cannot_be_forged(positive, field, value):
    subject, inputs, result = positive
    result['receipt'][field] = value
    with pytest.raises(ValueError):
        verify_financial(result, subject, inputs)


@pytest.mark.parametrize('kind', ['interest_accrual', 'interest_posting'])
@pytest.mark.parametrize('field,value', [('id', 'forged'), ('evidenceIds', ['0' * 64])])
def test_ledger_attribution_cannot_be_forged(positive, kind, field, value):
    subject, inputs, result = positive
    next(r for r in result['receipt']['ledger'] if r['type'] == kind)[field] = value
    with pytest.raises(ValueError, match='identity/evidence'):
        verify_financial(result, subject, inputs)


@pytest.mark.parametrize('index,field,value', [(0, 'intervalId', 'forged'), (1, 'intervalId', 'forged'),
    (0, 'allocation', 'whole_balance'), (1, 'allocation', 'whole_balance'),
    (0, 'assessmentId', 'forged'), (0, 'qualification', {}),
    (0, 'evidenceIds', []), (1, 'evidenceIds', []),
    (1, 'qualification', dict(status='meets', trace={}, reasons=[]))])
def test_component_trace_cannot_be_forged(positive, index, field, value):
    subject, inputs, result = positive
    result['receipt']['ledger'][0]['savingsContributions'][index][field] = value
    with pytest.raises(ValueError, match='audit trace'):
        verify_financial(result, subject, inputs)


def test_metric_reason_cannot_be_forged(positive):
    subject, inputs, result = positive
    result['receipt']['ledger'][0]['savingsContributions'][1]['activityResults'][0]['reason'] = 'forged'
    with pytest.raises(ValueError, match='metric reason'):
        verify_financial(result, subject, inputs)


def test_unfrozen_v4_fails_before_compute_store_or_asset_write(tmp_path):
    from app_payload_build import build_payload, build_and_publish_dual
    from app_payload_executable_v4 import load_published_executable_v4, package_executable_v4
    from cdr_terms.executable_v4_contract import require_publication_ready
    calls = [require_publication_ready,
        lambda: build_payload(tmp_path / 'absent', tmp_path / 'out', executable_v4_root=tmp_path),
        lambda: build_and_publish_dual(tmp_path / 'absent', executable_v4_root=tmp_path),
        lambda: load_published_executable_v4(tmp_path / 'absent', source_observation={}, run_date='',
            core_asset_sha256='', details_asset_sha256='', product_keys=[]),
        lambda: package_executable_v4({}, core={}, details={}, core_asset_sha256='',
            details_asset_sha256='', run_date='', write_asset=lambda *args: pytest.fail('wrote asset'))]
    for call in calls:
        with pytest.raises(ValueError, match='approved publication freeze'):
            call()
    assert not (tmp_path / 'out').exists()
