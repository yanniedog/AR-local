"""Independent audit metadata checks for the narrow admitted activity contract."""
from fractions import Fraction
from .executable_eligibility import verify_eligibility
from .executable_v2_inputs import exact_object
from .executable_v3_oracle import fixed


def check_receipt(result, subject, expected):
    receipt = result['receipt']
    exact_object(receipt, ('schemaVersion', 'evaluatorVersion', 'inputSha256', 'contractId',
        'dependencies', 'status', 'completeness', 'issueDetails', 'claimAvailable',
        'issues', 'assumptions', 'eligibility', 'totals', 'ledger'), 'activity receipt')
    eligibility = verify_eligibility(subject['policy']['eligibility'], result['calculationInputs']['scenario']['facts'])
    issues = [] if eligibility['status'] == 'meets' else ['eligibility:' + eligibility['status']]
    if expected['qualified'] is None:
        issues += list(dict.fromkeys('savings_qualification_unknown:' + day['intervalId'] + ':'
            + subject['policy']['bonus']['componentId'] for day in expected['daily']))
    if (receipt['schemaVersion'] != 1 or receipt['eligibility'] != eligibility
        or receipt['status'] != ('incomplete' if issues else 'complete')
        or receipt['completeness'] != ('incomplete' if issues else 'factual_complete')
        or receipt['claimAvailable'] is not (not issues) or receipt['issues'] != issues
        or receipt['issueDetails'] != [] or receipt['assumptions'] != []):
        raise ValueError('Activity completeness, eligibility or claim differs')


def check_row(row, result, subject):
    fields = ('date', 'id', 'type', 'amount', 'balance', 'evidenceIds')
    accrual = row['type'] == 'interest_accrual'
    exact_object(row, fields + (('savingsContributions',) if accrual else ()), 'activity ledger row')
    refs = (result['calculationInputs']['contract']['interest']['evidenceIds'] if accrual
            else list(dict.fromkeys(e['id'] for e in subject['evidence'])))
    if row['id'] != ('accrue:' if accrual else 'post:') + row['date'] or row['evidenceIds'] != refs:
        raise ValueError('Activity ledger identity/evidence differs')


def check_components(base, extra, period, bonus, expected, inputs):
    fields = ('intervalId', 'componentId', 'kind', 'allocation', 'status', 'assessmentId',
              'qualification', 'tiers', 'evidenceIds')
    exact_object(base, fields, 'activity base trace')
    exact_object(extra, fields + ('activityResults',), 'activity bonus trace')
    refs = list(dict.fromkeys(ref for values in period['fieldEvidenceIds'].values() for ref in values))
    window_refs = [ref for values in bonus['assessment']['fieldEvidenceIds'].values() for ref in values]
    bonus_refs = list(dict.fromkeys(refs + bonus['evidenceIds'] + window_refs))
    facts = {metric['field']: dict(type='decimal', value=fixed(Fraction(expected['facts'][metric['field']]),
        2 if metric['kind'] == 'deposit_total' else 0), unit='AUD' if metric['kind'] == 'deposit_total' else 'count')
        for metric in bonus['assessment']['metrics'] if metric['field'] in expected['facts']}
    qualification = verify_eligibility(bonus['assessment']['rule'], facts)
    if (base['intervalId'] != period['id'] or extra['intervalId'] != period['id']
        or base['allocation'] != period['allocation'] or extra['allocation'] != bonus['allocation']
        or base['assessmentId'] is not None or base['qualification'] is not None
        or base['evidenceIds'] != refs or extra['evidenceIds'] != bonus_refs
        or extra['qualification'] != qualification):
        raise ValueError('Activity component audit trace differs')
    for actual in extra['activityResults']:
        exact_object(actual, ('metricId', 'field', 'status', 'fact', 'reason', 'evidenceIds'), 'activity metric trace')
        reason = None if actual['field'] in facts else ('activity_coverage_unknown'
            if inputs['activity']['coverage'][0]['status'] != 'complete' else 'activity_classification_unknown')
        if actual['reason'] != reason:
            raise ValueError('Activity metric reason differs')
        if actual['fact'] is not None:
            exact_object(actual['fact'], ('type', 'value', 'unit'), 'activity metric fact')
