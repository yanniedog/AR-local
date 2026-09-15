"""Independent Fraction expectation comparison; no bank/source authority inferred."""
from .executable_v3_oracle import evaluate
from .executable_v2_inputs import exact_object


def financial_expectation(subject,inputs):
    # Local confirmation validation is separate. The oracle consumes a complete policy rate list.
    private=dict(inputs,confirmedAnnualRates=[t['annualRate'] for i in subject['policy']['intervals'] for t in i['tiers']])
    return evaluate(subject['policy'],private,completed_through_exclusive=subject['authorityGraph']['completedPeriod']['completedThroughExclusive'])


def verify_financial(result,subject,inputs):
    receipt=result['receipt'];expected=financial_expectation(subject,inputs)
    if expected['kind']!='technical_calculation':raise ValueError('Savings independent arithmetic refused')
    exact_object(receipt,('schemaVersion','evaluatorVersion','inputSha256','contractId','dependencies','status','completeness','issueDetails','claimAvailable','issues','assumptions','eligibility','totals','ledger'),'savings evaluator receipt')
    if (receipt['schemaVersion']!=1 or receipt['evaluatorVersion']!=subject['evaluatorVersion'] or receipt['status']!='complete'
        or receipt['completeness']!='factual_complete' or receipt['claimAvailable'] is not True or receipt['issues']!=[] or receipt['issueDetails']!=[] or receipt['assumptions']!=[] or receipt['eligibility']['status']!='meets'):
        raise ValueError('Savings benchmark requires complete independently eligible calculation')
    totals=dict(expected['totals'],principalRepaid=None,externalInflows='0.00',externalOutflows='0.00',feesDebitedBalance='0.00',feesPaidExternal='0.00')
    if receipt['totals']!=totals:raise ValueError('Savings totals differ from independent arithmetic')
    ledger=receipt['ledger']
    if not isinstance(ledger,list) or len(ledger)!=len(expected['ledger']):raise ValueError('Savings ledger inventory differs')
    periods={i['id']:i for i in subject['policy']['intervals']};daily={d['date']:d for d in expected['daily']}
    for actual,entry in zip(ledger,expected['ledger']):
        if {k:actual.get(k) for k in entry}!=entry:raise ValueError('Savings ledger arithmetic differs')
        if entry['type']=='interest_accrual':
            exact_object(actual,('date','id','type','amount','balance','evidenceIds','savingsContributions'),'savings accrual')
            day=daily[entry['date']];period=periods[day['intervalId']];refs=list(dict.fromkeys(r for values in period['fieldEvidenceIds'].values() for r in values))
            if actual['id']!='accrue:'+entry['date'] or actual['evidenceIds']!=result['calculationInputs']['contract']['interest']['evidenceIds']:raise ValueError('Savings accrual evidence differs')
            tiers=[dict(id=t['tierId'],basis=t['basis'],annualRate=t['annualRate'],accrual=t['accrual'],evidenceIds=next(x['evidenceIds'] for x in period['tiers'] if x['id']==t['tierId'])) for t in day['contributions']]
            contribution=dict(intervalId=period['id'],componentId=period['id']+':base',kind='base',allocation=period['allocation'],status='applied',assessmentId=None,qualification=None,tiers=tiers,evidenceIds=refs)
            if actual['savingsContributions']!=[contribution]:raise ValueError('Savings tier trace differs from independent arithmetic')
        else:
            exact_object(actual,('date','id','type','amount','balance','evidenceIds'),'savings posting')
            if actual['id']!='post:'+entry['date'] or actual['evidenceIds']!=list(dict.fromkeys(e['id'] for e in subject['evidence'])):raise ValueError('Savings posting evidence differs')
    return expected
