import copy
import json
import pytest
from tests.executable_v3_bridge_fixture import actual_savings_bridge
from tests.executable_v3_bridge_fixture import ROOT
from cdr_terms.executable_v3_benchmarks import verify_benchmark
from cdr_terms.executable_v3_reviews import validate_completion_proof
from cdr_terms.executable_v3_inputs import validate_result
from cdr_terms.executable_v3_inputs import money,check_inputs
from cdr_terms.executable_v3_context import target_binding
from cdr_terms.identity import digest


def test_actual_final_bridge_private_gzip_code_projection_arithmetic(actual_savings_bridge):
    store,subject,run,put,_=actual_savings_bridge
    validate_completion_proof(store,subject)
    verify_benchmark(store,put(run),subject)


@pytest.mark.parametrize('mutate',[
    lambda r:r['calculationInputs']['scenario'].update(openingBalance='1001.00'),
    lambda r:r['calculationInputs']['contract']['interest'].update(postingDates=[]),
    lambda r:r['adapterInputs']['facts']['balance'].update(value='2000'),
])
def test_material_adapter_projection_tampering(actual_savings_bridge,mutate):
    _,subject,_,_,bridge=actual_savings_bridge
    record=copy.deepcopy(bridge['records'][0]);mutate(record['result'])
    with pytest.raises(ValueError):validate_result(record['result'],subject,record['rawInput'])


def test_equal_actual_expected_forged_totals_still_refused(actual_savings_bridge):
    store,subject,run,put,_=actual_savings_bridge
    actual=json.loads(store.read_blob(run['cases'][0]['actualSha256']))
    actual['outcome']['result']['receipt']['totals']['interestPosted']='999.00'
    run['cases'][0]['actualSha256']=put(actual)
    with pytest.raises(ValueError,match='independent arithmetic'):verify_benchmark(store,put(run),subject)


def test_unrelated_refusal_cannot_replace_rate_control(actual_savings_bridge):
    store,subject,run,put,_=actual_savings_bridge
    actual=json.loads(store.read_blob(run['cases'][2]['actualSha256']))
    actual['outcome']['refusal']='Unrelated failure'
    run['cases'][2]['actualSha256']=put(actual)
    with pytest.raises(ValueError,match='refusal control'):verify_benchmark(store,put(run),subject)


@pytest.mark.parametrize('value,expected',[('1000.000000000000000000000000','1000.00'),('-0.000','0.00'),('9'*72,'9'*72+'.00')])
def test_actual_decimal_grammar_preserves_exact_cents(value,expected):
    assert money(value)==expected


@pytest.mark.parametrize('value',['01000','00','1.001','-0.01','1e3','9'*73,'1\u0661'])
def test_actual_decimal_grammar_refuses_non_adapter_inputs(value):
    with pytest.raises(ValueError):money(value)


def test_leading_zero_rate_and_boolean_rate_index_refuse(actual_savings_bridge):
    _,subject,_,_,bridge=actual_savings_bridge
    raw=copy.deepcopy(bridge['records'][0]['rawInput']);raw['inputs']['confirmedAnnualRates'][0]['annualRate']='00.0365'
    with pytest.raises(ValueError,match='rate confirmation'):check_inputs(subject,raw['inputs'])
    row=dict(product_key=subject['scope']['productKey'],rate_index=1)
    target=dict(kind='rate_variant',productKey=subject['scope']['productKey'],productRecordSha256=subject['routing']['productRecordSha256'],section='Savings',coreRowIndex=0,rateIndex=True,rowSha256=digest(row))
    with pytest.raises(ValueError,match='not verified'):target_binding(target,subject,{'sections':{'Savings':{'rates':[row]}}})


def test_adapter_confirmation_requires_utc_z_spelling(actual_savings_bridge):
    _,subject,_,_,bridge=actual_savings_bridge
    inputs=copy.deepcopy(bridge['records'][0]['rawInput']['inputs']);inputs['confirmedAt']='2026-01-12T01:00:00+00:00'
    with pytest.raises(ValueError,match='complete local'):check_inputs(subject,inputs)


def test_actual_ledger_distinct_evidence_union_control(actual_savings_bridge):
    """Separate actual ledger control, not a second claimed adapter transport capture."""
    from cdr_terms.executable_v3_financial import verify_financial
    _,subject,_,_,bridge=actual_savings_bridge
    vector=json.loads((ROOT/'actual-distinct-evidence.json').read_bytes())
    assert digest(vector['input'])==vector['inputSha256'] and digest(vector['result'])==vector['resultSha256']
    subject=copy.deepcopy(subject);subject['evidence']=vector['input']['contract']['evidence']
    b=subject['evidence'][1]['id']
    for interval in subject['policy']['intervals']:interval['fieldEvidenceIds']['feeCoverage']=[b]
    result=dict(receipt=vector['result'],calculationInputs=vector['input'])
    verify_financial(result,subject,bridge['records'][0]['rawInput']['inputs'])
