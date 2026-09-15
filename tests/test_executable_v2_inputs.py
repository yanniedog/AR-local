"""Actual in-progress app adapter vectors; no final-code or source approval."""
import copy
import gzip
import json
from pathlib import Path

import pytest

from cdr_terms.executable_v2_inputs import derive_facts, validate_evaluation
from cdr_terms.identity import digest


@pytest.fixture
def bridge():
    return json.loads(gzip.decompress((Path(__file__).parent/'fixtures/executable-templates/eligibility-v2-working-bridge.json.gz').read_bytes()))


def test_actual_four_results_match_private_inputs_and_oracle(bridge):
    records = [r for r in bridge['records'] if 'result' in r]
    assert len(records) == 4
    for record in records:
        assert digest(record['rawInput']) == record['rawInputSha256']
        assert digest(record['result']) == record['resultSha256']
        validate_evaluation(record['result'],bridge['selection']['subject'],record['rawInput'])


@pytest.mark.parametrize('index',[4,5])
def test_actual_adapter_refusal_conditions(bridge,index):
    record = bridge['records'][index]
    assert record['resultReturned'] is False
    with pytest.raises(ValueError,match=record['refusal']):
        derive_facts(bridge['selection']['subject'],record['rawInput']['scenario'],{})


def test_equal_forged_output_cannot_change_scenario_owned_fact(bridge):
    record = copy.deepcopy(bridge['records'][0])
    result = record['result']
    result['evaluationInputs']['facts']['amount']['value'] = '0'
    result['inputSha256'] = digest(result['evaluationInputs'])
    with pytest.raises(ValueError,match='facts/result'):
        validate_evaluation(result,bridge['selection']['subject'],record['rawInput'])


def test_raw_profile_cannot_fill_missing_scenario_role(bridge):
    record = copy.deepcopy(bridge['records'][2])
    subject = bridge['selection']['subject']
    record['rawInput']['profile']['answers']['elig_'+digest([subject['id'],'amount'])] = {
        'state':'known','fact':{'type':'decimal','unit':'AUD','value':'1000'},'provenance':{'productKey':subject['scope']['productKey']}}
    validate_evaluation(record['result'],subject,record['rawInput'])
    assert record['result']['eligibility']['status'] == 'needs_information'
