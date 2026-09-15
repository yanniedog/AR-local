"""Retained real JS adapter/evaluator execution; technical fixtures, no bank approval."""
import copy
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from cdr_terms.executable_benchmarks import validate_result, verify_benchmark
from cdr_terms.executable_contract import validate_template
from cdr_terms.identity import canonical_json, digest
from cdr_terms.store import EvidenceStore

BRIDGE = Path(__file__).parent / 'fixtures/executable-templates/actual-v7-bridge.json'


def independently_check(record):
    """Decimal/calendar expectations independent of the captured JavaScript engine."""
    inputs, result = record['instantiatedInput'], record['output']
    assert digest(inputs) == record['inputCanonicalSha256'] == result['inputSha256']
    assert digest(result) == record['outputCanonicalSha256']
    if record['name'] == 'refusal':
        assert inputs['contract']['tdLifecycle']['investmentAmount'] != inputs['scenario']['openingBalance']
        assert result['issues'] == ['td_confirmed_investment_amount_mismatch']
        assert result['status'] == 'unsupported' and result['totals'] is None and result['ledger'] == []
        return
    local = record['localInput']
    principal = Decimal(local['principal'])
    start, end = map(date.fromisoformat, (local['fundedDate'], local['maturityDate']))
    daily = principal * Decimal(inputs['contract']['initialAnnualRate']) / 365
    days = (end - start).days
    interest = daily * days
    assert days == 29 and daily == Decimal('0.10') and interest == Decimal('2.90')
    accrual = [e for e in result['ledger'] if e['type'] == 'interest_accrual']
    assert [e['date'] for e in accrual] == [(start + timedelta(days=n)).isoformat() for n in range(days)]
    assert all(Decimal(e['amount']) == daily and Decimal(e['balance']) == principal for e in accrual)
    settlement = [e for e in result['ledger'] if e['type'] != 'interest_accrual']
    assert [(e['date'], e['type'], Decimal(e['amount']), Decimal(e['balance'])) for e in settlement] == [
        (end.isoformat(), 'interest_posting', interest, principal + interest),
        (end.isoformat(), 'cashflow', -(principal + interest), Decimal(0))]
    expected = dict(openingBalance=principal, interestAccrued=interest, interestPosted=interest,
        externalOutflows=principal + interest, externalCashflowNet=-(principal + interest),
        externalInflows=0, interestUnposted=0, interestRoundingAdjustment=0,
        feesCharged=0, feesDebitedBalance=0, feesPaidExternal=0, closingBalance=0)
    assert all(Decimal(result['totals'][key]) == value for key, value in expected.items())
    assert result['totals']['principalRepaid'] is None
    assert result['localTdConfirmation'] == inputs['scenario']['tdConfirmation']


def test_actual_adapter_evaluator_bridge_passes_full_benchmark(tmp_path):
    bridge = json.loads(BRIDGE.read_bytes())
    store = EvidenceStore(tmp_path)
    put = lambda value: store.put_blob(canonical_json(value).encode('utf-8'))
    codes = {key: put([item for item in bridge['code'] if marker in item['file']]) for key, marker in (
        ('adapterCodeSha256', 'executableContracts/'), ('evaluatorCodeSha256', 'productTermsEngine/'))}
    cases, expectations = [], []
    for record in bridge['records']:
        template = record['template']
        validate_template(template)
        independently_check(record)
        input_sha = put(record['instantiatedInput'])
        actual = dict(templateId=template['id'], inputSha256=input_sha,
            adapterVersion=bridge['adapterVersion'], evaluatorVersion=bridge['evaluatorVersion'],
            **codes, result=record['output'])
        # The actual values are accepted only after the separate Decimal/date derivation above.
        expected = dict(templateId=template['id'], inputSha256=input_sha,
            derivationSha256=store.put_blob(Path(__file__).read_bytes()), result=record['output'])
        cases.append(dict(id=record['name'], inputSha256=input_sha, actualSha256=put(actual)))
        expectations.append(dict(id=record['name'], inputSha256=input_sha, expectationSha256=put(expected)))
    suite = dict(expectationAuthor='independent-python-decimal-calendar', expectationKind='deterministic',
        **codes, cases=expectations)
    run = dict(schemaVersion=1, templateId=template['id'], adapterVersion=bridge['adapterVersion'],
        evaluatorVersion=bridge['evaluatorVersion'], executionActor='retained-jest-real-adapter-engine',
        suiteSha256=put(suite), cases=cases)
    verify_benchmark(store, put(run), template)
    store.db.close()


@pytest.mark.parametrize('mutation', ['input', 'confirmation', 'dependency', 'fee'])
def test_actual_bridge_negative_controls(mutation):
    record = copy.deepcopy(json.loads(BRIDGE.read_bytes())['records'][0])
    if mutation == 'input':
        record['instantiatedInput']['scenario']['openingBalance'] = '999'
    elif mutation == 'confirmation':
        record['output']['localTdConfirmation']['principal'] = '999'
    elif mutation == 'dependency':
        record['output']['dependencies'] = []
    else:
        record['output']['totals']['feesPaidExternal'] = 'unavailable'
    with pytest.raises(ValueError):
        validate_result(record['output'], record['template'], record['instantiatedInput'])
