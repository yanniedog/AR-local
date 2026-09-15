"""Actual technical capture and independent negative controls; not bank acceptance."""
import copy,json
from pathlib import Path
import pytest
from cdr_terms.store import EvidenceStore
from cdr_terms.identity import digest
from cdr_terms.executable_v3_benchmarks import verify_benchmark
from cdr_terms.mortgage_result import validate_result
from cdr_terms.mortgage_inputs import require_offer_facts
from tests.executable_v3_bridge_fixture import retain_benchmark

ROOT=Path(__file__).parent/'fixtures/mortgage-v3'


@pytest.fixture
def bridge_store(tmp_path):
    bridge=json.loads((ROOT/'actual-bridge.json').read_bytes())
    with EvidenceStore(tmp_path/'engineering-bridge') as store:
        for path in (ROOT/'blobs').iterdir():assert store.put_blob(path.read_bytes())==path.name
        subject,run,put=retain_benchmark(store,bridge,json.loads((ROOT/'code-identities.json').read_bytes()))
        yield store,subject,run,put,bridge


@pytest.mark.parametrize('author',['execution',' execution ','execution '])
def test_whitespace_equivalent_expectation_author_refused(bridge_store,author):
    store,subject,run,put,_=bridge_store;suite=json.loads(store.read_blob(run['suiteSha256']))
    run['executionActor']='execution';suite['expectationAuthor']=author;run['suiteSha256']=put(suite)
    with pytest.raises(ValueError,match='independent expectation author'):verify_benchmark(store,put(run),subject)


def test_distinct_author_actual_capture_passes(bridge_store):
    store,subject,run,put,_=bridge_store
    verify_benchmark(store,put(run),subject)


@pytest.mark.parametrize('part',['opening','allocation','payment','fact','label'])
def test_actual_adapter_projection_cannot_be_self_asserted(bridge_store,part):
    _,subject,_,_,bridge=bridge_store;record=copy.deepcopy(bridge['records'][0]);result=record['result']
    if part=='opening':result['calculationInputs']['scenario']['openingBalance']='999.000000000000'
    elif part=='allocation':result['calculationInputs']['contract']['loanContract']['allocation'].reverse()
    elif part=='payment':result['calculationInputs']['scenario']['loan']['executions']=[{}]
    elif part=='fact':result['adapterInputs']['facts']['adult']['value']=False
    else:result['verificationScope']='Bank verified'
    result['inputSha256']=digest(result['adapterInputs'])
    with pytest.raises(ValueError):validate_result(result,subject,record['rawInput'])


def test_relevant_offer_confirmation_no_profile_fallback():
    subject=json.loads((ROOT/'actual-bridge.json').read_bytes())['selection']['subject']
    rule=copy.deepcopy(subject['policy']['eligibility']);rule.update(id='purpose',field='offer_purpose',expected=dict(type='text',value='owner'))
    subject['policy']['inputDefinitions'].append(dict(field='offer_purpose',binding='offer_purpose',type='text',unit=None,label='Purpose'))
    adult=subject['policy']['eligibility'];subject['policy']['eligibility']=dict(id='both',op='and',rules=[adult,rule],evidenceIds=[])
    require_offer_facts(subject,{'adult':dict(type='boolean',value=False)})  # Decisive false AND.
    with pytest.raises(ValueError,match='offer confirmation'):require_offer_facts(subject,{'adult':dict(type='boolean',value=True)})
