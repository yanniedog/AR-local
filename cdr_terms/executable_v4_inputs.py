"""Independent admission and exact projection of the activity adapter call."""
from decimal import Decimal
from .identity import digest
from .executable_v2_inputs import exact_object
from .executable_v3_inputs import FIELDS, facts, check_inputs as base_check, projection as base_projection
from .executable_v4_contract import schema_validate
from .executable_eligibility import verify_eligibility


def base_inputs(inputs):
    return {key: inputs[key] for key in FIELDS}


def check_inputs(subject, inputs):
    schema_validate(inputs, 'private-input', 512 * 1024)
    intervals = base_check(subject, base_inputs(inputs))
    scope, bonus = subject['scope'], subject['policy']['bonus']
    if (inputs['startDate'], inputs['endDateExclusive']) != (scope['from'], scope['toExclusive']):
        raise ValueError('Account period is outside source-reviewed historical coverage')
    rates = inputs['confirmedBonusAnnualRates']
    if len(rates) != len(bonus['tiers']):
        raise ValueError('Confirm every bonus rate tier')
    tiers = {tier['id']: tier for tier in bonus['tiers']}
    seen = set()
    for rate in rates:
        key = rate['tierId']
        if (rate['componentId'] != bonus['componentId'] or key not in tiers or key in seen
                or Decimal(rate['annualRate']) != Decimal(tiers[key]['annualRate'])):
            raise ValueError('Confirmed bonus rates differ from source')
        seen.add(key)
    assessment, data = bonus['assessment'], inputs['activity']
    coverage = data['coverage']
    if (len(coverage) != 1 or coverage[0]['accountId'] != inputs['accountId']
            or coverage[0]['from'] != assessment['from']
            or coverage[0]['toExclusive'] != assessment['toExclusive']
            or any(event['accountId'] != inputs['accountId']
                   or not assessment['from'] <= event['date'] < assessment['toExclusive']
                   or event['dateBasis'] != assessment['dateBasis'] for event in data['events'])):
        raise ValueError('Activity account or assessment window differs')
    return intervals


def projection(subject, inputs, binding, approval, derived):
    check_inputs(subject, inputs)
    value = base_projection(subject, base_inputs(inputs), binding, approval, derived)
    contract, scenario = value['contract'], value['scenario']
    bonus = subject['policy']['bonus']; assessment = bonus['assessment']
    window = {key: assessment[key] for key in ('from', 'toExclusive', 'appliesFrom', 'appliesToExclusive')}
    window['evidenceIds'] = list(dict.fromkeys(ref for refs in assessment['fieldEvidenceIds'].values() for ref in refs))
    metrics = [dict(id=m['id'], kind=m['kind'], field=m['field'], accountRole=assessment['accountRole'],
                    accountIds=[inputs['accountId']], dateBasis=assessment['dateBasis'], settlement=assessment['settlement'],
                    includedClassifications=m['includedClassifications'], excludedClassifications=m['excludedClassifications'],
                    refundPolicy=None, growthAdjustments=None, evidenceIds=m['evidenceIds']) for m in assessment['metrics']]
    for interval in contract['savingsSchedule']['intervals']:
        interval['components'].append(dict(id=bonus['componentId'], kind='bonus', allocation=bonus['allocation'],
            rateMeaning='additive', tiers=bonus['tiers'], evidenceIds=bonus['evidenceIds'], qualification=dict(
                assessmentKey=assessment['assessmentKey'], accountId=inputs['accountId'], rule=assessment['rule'],
                windows=[window], activityMetrics=metrics)))
    scenario['savingsAssessments'] = [dict(id='preceding-assessment', assessmentKey=assessment['assessmentKey'],
        accountId=inputs['accountId'], **window, coverage=inputs['activity']['coverage'][0]['status'], facts={},
        activity=dict(inputs['activity'], balances=[]))]
    return value


def validate_result(result, subject, raw):
    exact_object(raw, ('target', 'inputs', 'profile'), 'activity raw call')
    exact_object(result, ('schemaVersion', 'evaluationKind', 'adapterVersion', 'evaluatorVersion', 'verificationScope',
                         'basis', 'adapterInputs', 'inputSha256', 'calculationInputs', 'receipt'), 'activity result')
    if (result['schemaVersion'] != 1 or result['evaluationKind'] != subject['capability']
            or any(result[key] != subject[key] for key in ('adapterVersion', 'evaluatorVersion'))):
        raise ValueError('Activity result version differs')
    if (result['verificationScope'] != 'Approved structured historical authority and current publication verified on-device; original historical source bytes verified by producer, not downloaded here.'
            or result['basis'] != 'Historical holding result before tax. Account rates and facts confirmed by you, not independently verified bank account data.'):
        raise ValueError('Activity verification scope or basis differs')
    value = result['adapterInputs']
    exact_object(value, ('subject', 'approval', 'binding', 'target', 'inputs', 'customerAnswers', 'facts'), 'activity adapter input')
    derived, answers = facts(subject, raw['inputs'], raw['profile'])
    if (value['subject'] != subject or value['target'] != raw['target'] or value['inputs'] != raw['inputs']
            or value['facts'] != derived or value['customerAnswers'] != answers or result['inputSha256'] != digest(value)):
        raise ValueError('Activity raw adapter input propagation differs')
    expected = projection(subject, raw['inputs'], value['binding'], value['approval'], derived)
    if result['calculationInputs'] != expected:
        raise ValueError('Activity actual contract/scenario projection differs')
    receipt = result['receipt']
    if (receipt['inputSha256'] != digest(dict(evaluatorVersion=subject['evaluatorVersion'], **expected))
            or receipt['contractId'] != subject['id'] or receipt['dependencies'] != expected['contract']['dependencyIds']
            or receipt['eligibility'] != verify_eligibility(subject['policy']['eligibility'], derived)):
        raise ValueError('Activity evaluator input/eligibility differs')
