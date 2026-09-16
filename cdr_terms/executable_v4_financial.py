"""Compare exposed actual activity financial fields against independent Fractions."""
from fractions import Fraction
from .executable_v4_oracle import evaluate


def verify_financial(result,subject,inputs):
    expected=evaluate(subject,inputs);receipt=result['receipt'];met=expected['qualified']
    if receipt['evaluatorVersion']!='product-terms-engine-v9':raise ValueError('Activity evaluator differs')
    status='incomplete' if met is None else 'complete'
    if receipt['status']!=status or receipt['claimAvailable'] is not (met is not None):
        raise ValueError('Activity completeness or claim differs')
    totals=dict(expected['totals'],principalRepaid=None,externalInflows='0.00',externalOutflows='0.00',feesDebitedBalance='0.00',feesPaidExternal='0.00')
    if receipt['totals']!=totals:raise ValueError('Activity totals differ from independent arithmetic')
    ledger=receipt['ledger']
    if len(ledger)!=len(expected['ledger']):raise ValueError('Activity ledger inventory differs')
    days={x['date']:x for x in expected['daily']}
    periods={x['id']:x for x in subject['policy']['intervals']};bonus=subject['policy']['bonus']
    for row,financial in zip(ledger,expected['ledger']):
        if {k:row.get(k) for k in financial}!=financial:raise ValueError('Activity ledger arithmetic differs')
        if row['type']!='interest_accrual':continue
        day=days[row['date']];period=periods[day['intervalId']]
        contributions=row['savingsContributions']
        if len(contributions)!=2:raise ValueError('Activity component inventory differs')
        base,extra=contributions
        qualification='needs_information' if met is None else 'meets' if met else 'does_not_meet'
        if (base['kind']!='base' or base['componentId']!=period['id']+':base' or base['status']!='applied'
            or extra['kind']!='bonus' or extra['componentId']!=bonus['componentId']
            or extra['assessmentId']!='preceding-assessment'
            or extra['status']!=('applied' if met else qualification)
            or extra['qualification']['status']!=qualification):
            raise ValueError('Activity component qualification differs')
        for component,tiers,definitions in ((base,day['baseTiers'],period['tiers']),(extra,day['bonusTiers'],bonus['tiers'])):
            refs={t['id']:t['evidenceIds'] for t in definitions}
            wanted=[dict(id=t['tierId'],basis=t['basis'],annualRate=t['annualRate'],accrual=t['accrual'],evidenceIds=refs[t['tierId']]) for t in tiers]
            if component['tiers']!=wanted:raise ValueError('Activity tier contributions differ')
        actual_facts=extra['activityResults']
        if len(actual_facts)!=len(bonus['assessment']['metrics']):raise ValueError('Activity metric inventory differs')
        for actual,metric in zip(actual_facts,bonus['assessment']['metrics']):
            if actual['metricId']!=metric['id'] or actual['field']!=metric['field'] or actual['evidenceIds']!=metric['evidenceIds']:
                raise ValueError('Activity metric identity differs')
            if metric['field'] in expected['facts']:
                fact=actual['fact'];unit='AUD' if metric['kind']=='deposit_total' else 'count'
                if actual['status']!='known' or fact['type']!='decimal' or fact['unit']!=unit or Fraction(fact['value'])!=Fraction(expected['facts'][metric['field']]):
                    raise ValueError('Activity metric amount differs')
            elif actual['status']!='unknown' or actual['fact'] is not None:
                raise ValueError('Activity unknown dependency disappeared')
    return expected
