"""Raw local-input bindings and the specific v8 rate-refusal approval control."""
import json

import pytest

from cdr_terms.executable_benchmarks import verify_benchmark
from cdr_terms.identity import canonical_json
from tests.executable_benchmark_fixture import benchmark_control
from tests.executable_protocol_fixture import protocol  # noqa: F401


def edit_case(store, run, index, edit):
    put = lambda value: store.put_blob(canonical_json(value).encode())
    read = lambda identity: json.loads(store.read_blob(identity))
    suite = read(run['suiteSha256'])
    case, expected_case = run['cases'][index], suite['cases'][index]
    actual, expected = read(case['actualSha256']), read(expected_case['expectationSha256'])
    inputs, local = read(case['inputSha256']), read(case['adapterInputSha256'])
    edit(case, expected_case, actual, expected, inputs, local)
    case['actualSha256'] = put(actual)
    expected_case['expectationSha256'] = put(expected)
    run['suiteSha256'] = put(suite)
    return put(run)


@pytest.mark.parametrize('target', ['case', 'expected_case', 'actual', 'expected'])
def test_raw_adapter_hash_is_bound_everywhere(protocol, target):
    store, template, *_ = protocol
    run = benchmark_control(store, template)
    def edit(case, expected_case, actual, expected, *_):
        {'case': case, 'expected_case': expected_case, 'actual': actual, 'expected': expected}[target]['adapterInputSha256'] = 'f' * 64
    identity = edit_case(store, run, 0, edit)
    with pytest.raises(ValueError, match='identity|binding'):
        verify_benchmark(store, identity, template)


@pytest.mark.parametrize('field,value', [('confirmedAnnualRate', '0.03'), ('principal', '999'),
    ('fundedDate', '2026-01-02'), ('maturityDate', '2026-12-01'), ('confirmed', False),
    ('noWithholdingConfirmed', False), ('confirmedAt', '2026-01-01T01:00:00Z'), ('unknown', 'unreviewed')])
def test_rebound_raw_input_cannot_disagree_with_propagation(protocol, field, value):
    store, template, *_ = protocol
    run = benchmark_control(store, template)
    def edit(case, expected_case, actual, expected, inputs, local):
        local[field] = value
        sha = store.put_blob(canonical_json(local).encode())
        for record in (case, expected_case, actual, expected):
            record['adapterInputSha256'] = sha
    identity = edit_case(store, run, 0, edit)
    with pytest.raises(ValueError, match='adapter'):
        verify_benchmark(store, identity, template)


@pytest.mark.parametrize('change', ['unrelated_issue', 'matched_rate', 'false_adapter_execution'])
def test_v8_requires_a_real_rate_mismatch_refusal_control(protocol, change):
    store, template, *_ = protocol
    run = benchmark_control(store, template)
    def edit(case, expected_case, actual, expected, inputs, local):
        if change == 'unrelated_issue':
            actual['result']['issues'] = ['unrelated_protocol_refusal']
            expected['result']['issues'] = ['unrelated_protocol_refusal']
        elif change == 'false_adapter_execution':
            for record in (case, expected_case, actual, expected):
                record['executionKind'] = 'adapter_and_evaluator'
        else:
            local['confirmedAnnualRate'] = template['annualRate']
            inputs['scenario']['tdConfirmation']['annualRate'] = template['annualRate']
            raw_sha = store.put_blob(canonical_json(local).encode())
            input_sha = store.put_blob(canonical_json(inputs).encode())
            for record in (case, expected_case, actual, expected):
                record.update(adapterInputSha256=raw_sha, inputSha256=input_sha)
            actual['result']['inputSha256'] = expected['result']['inputSha256'] = input_sha
    identity = edit_case(store, run, 1, edit)
    with pytest.raises(ValueError, match='opened-rate mismatch refusal'):
        verify_benchmark(store, identity, template)
