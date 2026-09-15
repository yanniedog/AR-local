"""Versioned admission controls; fixtures do not approve any banking product."""
import json

import pytest

from cdr_terms.executable_benchmarks import validate_result
from cdr_terms.executable_contract import validate_template
from cdr_terms.executable_reviews import review_template, stage_template
from cdr_terms.identity import canonical_json
from tests.executable_benchmark_fixture import benchmark_control
from tests.executable_protocol_fixture import NOW, protocol, reidentify  # noqa: F401


def test_v7_readable_but_new_staging_and_approval_refused(protocol):
    store, template, *_ = protocol
    template['evaluatorVersion'] = 'product-terms-engine-v7'
    reidentify(template)
    validate_template(template)
    with pytest.raises(ValueError, match='staging requires evaluator v8'):
        stage_template(store, template, interpreter='old-author', staged_at=NOW)
    # An authentic immutable prior row can exist; it cannot receive a new approval.
    with store.db:
        store.db.execute('INSERT INTO executable_templates (template_id,observation_id,product_key,cohort_key,rate_index,interpreter,staged_at,template_json) VALUES (?,?,?,?,?,?,?,?)',
            (template['id'], template['sourceObservationId'], template['productKey'], template['cohortKey'],
             template['selectedRate']['rateIndex'], 'old-author', NOW, canonical_json(template)))
    before = store.db.execute('SELECT template_json FROM executable_templates').fetchone()[0]
    with pytest.raises(ValueError, match='approval requires evaluator v8'):
        review_template(store, template['id'], decision='approved', reviewer='new-reviewer', reviewer_kind='human',
            reviewed_at=NOW, evidence_sha256=store.put_blob(b'{}'), reason='Version control', expected_previous_review_id=None)
    assert store.db.execute('SELECT template_json FROM executable_templates').fetchone()[0] == before


@pytest.mark.parametrize('change', ['missing', 'malformed', 'mismatch', 'contract', 'scenario', 'receipt', 'coherent_mismatch'])
def test_v8_complete_confirmation_rate_is_mandatory_and_bound(protocol, change):
    store, template, *_ = protocol
    run = benchmark_control(store, template)
    case = run['cases'][0]
    inputs = json.loads(store.read_blob(case['inputSha256']))
    result = json.loads(store.read_blob(case['actualSha256']))['result']
    validate_result(result, template, inputs)
    if change == 'missing':
        del result['localTdConfirmation']['annualRate']
    elif change == 'malformed':
        result['localTdConfirmation']['annualRate'] = 'NaN'
    elif change == 'mismatch':
        result['localTdConfirmation']['annualRate'] = '0.123'
    elif change == 'contract':
        inputs['contract']['initialAnnualRate'] = '0.123'
    elif change == 'scenario':
        inputs['scenario']['tdConfirmation']['annualRate'] = '0.123'
    elif change == 'coherent_mismatch':
        inputs['scenario']['tdConfirmation']['annualRate'] = '0.123'
        inputs['contract']['initialAnnualRate'] = '0.123'
        result['localTdConfirmation']['annualRate'] = '0.123'
    else:
        del result['localTdConfirmation']
    # Rebind input identity to demonstrate semantic checks, not only a stale hash.
    from cdr_terms.identity import digest
    result['inputSha256'] = digest(inputs)
    with pytest.raises(ValueError):
        validate_result(result, template, inputs)


def test_v7_receipt_does_not_silently_accept_v8_confirmation():
    from tests.test_executable_actual_bridge import BRIDGE
    record = json.loads(BRIDGE.read_bytes())['records'][0]
    record['output']['localTdConfirmation']['annualRate'] = record['template']['annualRate']
    with pytest.raises(ValueError, match='shape mismatch'):
        validate_result(record['output'], record['template'], record['instantiatedInput'])


@pytest.mark.parametrize('rate', ['5e-2', 'NaN', 'Infinity', '0.0500000000000'])
def test_v8_rate_lexical_contract_is_exact(protocol, rate):
    store, template, *_ = protocol
    case = benchmark_control(store, template)['cases'][0]
    inputs = json.loads(store.read_blob(case['inputSha256']))
    result = json.loads(store.read_blob(case['actualSha256']))['result']
    inputs['scenario']['tdConfirmation']['annualRate'] = rate
    inputs['contract']['initialAnnualRate'] = rate
    result['localTdConfirmation']['annualRate'] = rate
    from cdr_terms.identity import digest
    result['inputSha256'] = digest(inputs)
    with pytest.raises(ValueError, match='confirmed annual rate'):
        validate_result(result, template, inputs)


def test_equivalent_rate_decimal_strings_are_accepted(protocol):
    from decimal import Decimal
    from cdr_terms.identity import digest
    store, template, *_ = protocol
    case = benchmark_control(store, template)['cases'][0]
    inputs = json.loads(store.read_blob(case['inputSha256']))
    result = json.loads(store.read_blob(case['actualSha256']))['result']
    rate = format(Decimal(template['annualRate']), '.8f')
    inputs['scenario']['tdConfirmation']['annualRate'] = rate
    result['localTdConfirmation']['annualRate'] = rate
    result['inputSha256'] = digest(inputs)
    validate_result(result, template, inputs)
