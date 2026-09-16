"""Independent technical Fraction expectations; never source or bank approval."""
from fractions import Fraction as F
from .executable_v3_oracle import days, fixed, rounded, interest_for_day


def metric_amount(metric, data):
    amount=F(0)
    for event in data['events']:
        if event['status']=='unknown':return None
        if event['status']=='pending':continue
        if event['kind']=='unknown':return None
        expected_kind='deposit' if metric['kind']=='deposit_total' else 'withdrawal'
        if event['kind']!=expected_kind:continue
        classification=event['classification']
        if classification in metric['excludedClassifications']:continue
        if classification not in metric['includedClassifications']:return None
        amount+=F(event['amount']) if metric['kind']=='deposit_total' else 1
    return amount


def qualification(policy, inputs):
    assessment=policy['bonus']['assessment']; data=inputs['activity']
    if any(c['status']!='complete' for c in data['coverage']):return None,{}
    facts={m['field']:amount for m in assessment['metrics'] if (amount:=metric_amount(m,data)) is not None}
    def compare(rule):
        if rule['field'] not in facts:return None
        left=facts[rule['field']];right=F(rule['expected']['value'])
        return {'eq':left==right,'ne':left!=right,'gt':left>right,'gte':left>=right,
                'lt':left<right,'lte':left<=right}[rule['comparison']]
    rule=assessment['rule']
    if rule['op'] in ('and','or'):
        states=[compare(x) for x in rule['rules']]
        decisive=rule['op']=='or'
        met=decisive if any(x is decisive for x in states) else None if any(x is None for x in states) else not decisive
    else:met=compare(rule)
    return met,facts


def evaluate(subject, inputs):
    """Inputs must independently pass the closed adapter binding before this oracle."""
    policy=subject['policy'];met,facts=qualification(policy,inputs)
    opening=balance=F(inputs['openingBalance']);accrued=unposted=posted=F(0)
    daily=[];ledger=[];bonus=policy['bonus']
    for day in days(inputs['startDate'],inputs['endDateExclusive']):
        period=next(x for x in policy['intervals'] if x['from']<=day<x['toExclusive'])
        earned,base_tiers=interest_for_day(balance,period)
        bonus_earned=F(0);bonus_tiers=[]
        if met:
            bonus_earned,bonus_tiers=interest_for_day(balance,dict(period,allocation=bonus['allocation'],tiers=bonus['tiers']))
        total=earned+bonus_earned;accrued+=total;unposted+=total
        daily.append(dict(date=day,intervalId=period['id'],basis=fixed(balance,2),baseAccrual=fixed(earned,12),
                          bonusAccrual=fixed(bonus_earned,12),baseTiers=base_tiers,bonusTiers=bonus_tiers,accrual=fixed(total,12)))
        ledger.append(dict(date=day,type='interest_accrual',amount=fixed(total,12),balance=fixed(balance,2)))
        if day in policy['postingInventory']['dueDates']:
            payment=rounded(unposted,2,period['interest']['postingRounding']);balance+=payment;posted+=payment;unposted=F(0)
            ledger.append(dict(date=day,type='interest_posting',amount=fixed(payment,2),balance=fixed(balance,2)))
    totals=dict(openingBalance=fixed(opening,2),interestAccrued=fixed(accrued,12),interestPosted=fixed(posted,2),
                interestUnposted=fixed(unposted,12),closingBalance=fixed(balance,2),
                interestRoundingAdjustment=fixed(posted+unposted-accrued,12),feesCharged='0.00',externalCashflowNet='0.00')
    return dict(kind='technical_incomplete' if met is None else 'technical_calculation',qualified=met,
                facts={k:str(v) for k,v in facts.items()},totals=totals,daily=daily,ledger=ledger)
