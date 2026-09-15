"""Actual adapter output negative controls for every material calculation family."""
import copy
import json

import pytest

from cdr_terms.executable_inputs import validate_instantiated_input
from tests.test_executable_actual_bridge import BRIDGE


@pytest.mark.parametrize('field', ['term', 'daycount', 'rounding', 'fees', 'eligibility', 'evidence', 'applicability', 'dependencies', 'rate', 'minimal'])
def test_actual_contract_material_changes_are_refused(field):
    record = json.loads(BRIDGE.with_name('actual-v8-bridge.json').read_bytes())['records'][0]
    inputs, template = copy.deepcopy(record['instantiatedInput']), record['template']
    validate_instantiated_input(template, inputs)
    contract = inputs['contract']
    if field == 'term':
        contract['tdLifecycle']['term']['count'] += 1
    elif field == 'daycount':
        contract['interest']['dayCount'] = 'actual_actual'
    elif field == 'rounding':
        contract['interest']['postingRounding'] = 'toward_zero'
    elif field == 'fees':
        contract['feeSchedule']['fees'] = [{'amount': '10'}]
    elif field == 'eligibility':
        contract['eligibility'] = {'op': 'and', 'rules': []}
    elif field == 'evidence':
        contract['initialRateEvidenceIds'] = []
    elif field == 'applicability':
        contract['applicability']['cohortKey'] = 'another'
    elif field == 'dependencies':
        contract['dependencyIds'] = [template['id']]
    elif field == 'rate':
        contract['initialAnnualRate'] = '0.03'
    else:
        inputs['contract'] = {'id': template['id'], 'productId': template['productKey'], 'dependencyIds': [template['id']]}
    with pytest.raises(ValueError):
        validate_instantiated_input(template, inputs)


@pytest.mark.parametrize('field', ['accountId', 'productId', 'cohortKey', 'startDate', 'endDateExclusive', 'initialOffset', 'events', 'assumptions', 'facts', 'openingBalance', 'tdConfirmation'])
def test_actual_complete_scenario_material_changes_are_refused(field):
    record = json.loads(BRIDGE.with_name('actual-v8-bridge.json').read_bytes())['records'][0]
    inputs = record['instantiatedInput']
    if field in {'events', 'assumptions'}:
        inputs['scenario'][field] = ['unreviewed']
    elif field == 'facts':
        inputs['scenario']['facts']['protocol_amount']['value'] = '999'
    elif field == 'tdConfirmation':
        inputs['scenario'][field]['fundedDate'] = '2028-01-01'
    else:
        inputs['scenario'][field] = '999'
    with pytest.raises(ValueError):
        validate_instantiated_input(record['template'], inputs)
