"""Actual retained technical adapter results, independent arithmetic and refusals."""
import copy
import json
import pytest
from tests.executable_v4_bridge_fixture import actual_activity_bridge
from cdr_terms.executable_v4_benchmarks import verify_benchmark
from cdr_terms.executable_v4_reviews import validate_completion_proof
from cdr_terms.executable_v4_inputs import validate_result


def test_actual_activity_capture_code_context_inputs_and_independent_oracle(actual_activity_bridge):
    store, subject, run, put, _ = actual_activity_bridge
    validate_completion_proof(store, subject)
    verify_benchmark(store, put(run), subject)


@pytest.mark.parametrize('mutate', [
    lambda r: r['calculationInputs']['scenario']['savingsAssessments'][0].update(coverage='complete'),
    lambda r: r['calculationInputs']['contract']['savingsSchedule']['intervals'][0]['components'][1].update(tiers=[]),
    lambda r: r.update(basis='Verified bank earnings'),
])
def test_activity_projection_tampering_refused(actual_activity_bridge, mutate):
    _, subject, _, _, bridge = actual_activity_bridge
    record = copy.deepcopy(next(r for r in bridge['records'] if r['name'] == 'unknown_coverage'))
    mutate(record['result'])
    with pytest.raises(ValueError):
        validate_result(record['result'], subject, record['rawInput'])


def test_forged_activity_totals_refused_by_independent_arithmetic(actual_activity_bridge):
    store, subject, run, put, _ = actual_activity_bridge
    actual = json.loads(store.read_blob(run['cases'][0]['actualSha256']))
    actual['outcome']['result']['receipt']['totals']['interestPosted'] = '999.00'
    run['cases'][0]['actualSha256'] = put(actual)
    with pytest.raises(ValueError, match='independent arithmetic'):
        verify_benchmark(store, put(run), subject)


def test_unknown_cannot_become_complete_holdout(actual_activity_bridge):
    store, subject, run, put, _ = actual_activity_bridge
    suite = json.loads(store.read_blob(run['suiteSha256']))
    for case in suite['cases']:
        case['phase'] = 'holdout' if case['id'] == 'unknown_coverage' else 'training'
    run['suiteSha256'] = put(suite)
    with pytest.raises(ValueError, match='complete holdout'):
        verify_benchmark(store, put(run), subject)


def test_missing_bonus_refusal_cannot_pass(actual_activity_bridge):
    store, subject, run, put, _ = actual_activity_bridge
    suite = json.loads(store.read_blob(run['suiteSha256']))
    run['cases'] = [c for c in run['cases'] if c['id'] != 'bonus_refusal']
    suite['cases'] = [c for c in suite['cases'] if c['id'] != 'bonus_refusal']
    run['suiteSha256'] = put(suite)
    with pytest.raises(ValueError, match='five actual refusal'):
        verify_benchmark(store, put(run), subject)


def test_partial_unknown_metric_cannot_be_replaced_with_zero(actual_activity_bridge):
    from cdr_terms.executable_v4_financial import verify_financial
    _, subject, _, _, bridge = actual_activity_bridge
    record = copy.deepcopy(next(r for r in bridge['records'] if r['name'] == 'unknown_with_failed_requirement'))
    verify_financial(record['result'], subject, record['rawInput']['inputs'])
    trace = next(row for row in record['result']['receipt']['ledger'] if row['type'] == 'interest_accrual')
    metric = next(m for m in trace['savingsContributions'][1]['activityResults'] if m['status'] == 'unknown')
    metric.update(status='known', fact=dict(type='decimal', value='0', unit='AUD'))
    with pytest.raises(ValueError, match='unknown dependency disappeared'):
        verify_financial(record['result'], subject, record['rawInput']['inputs'])
