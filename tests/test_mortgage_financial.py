"""Independent hand anchors for generalized events; no source-admission claim."""
import copy,json
from pathlib import Path
from fractions import Fraction
import pytest
from cdr_terms.identity import digest
from cdr_terms.mortgage_projection import projection
from cdr_terms.mortgage_financial import expectation,rounded


def event_case(phase):
    bridge=json.loads((Path(__file__).parent/'fixtures/mortgage-v3/actual-bridge.json').read_bytes());s=copy.deepcopy(bridge['selection']['subject']);i=copy.deepcopy(bridge['records'][0]['rawInput']['inputs'])
    p=s['policy'];s['scope'].update({'from':'2026-01-31','toExclusive':'2026-02-01'})
    for a in s['authorityGraph']['authorities']:
        a.update({'from':'2026-01-31','toExclusive':'2026-02-01'})
        for c in a['fieldCoverage']:c.update({'from':'2026-01-31','toExclusive':'2026-02-01','postingEventDates':['2026-01-31']})
    p.update(paymentPhase=phase,interestBearing=['principal','postedInterest','accruedInterest','capitalizedCharges','otherDebt'],allocation=['accruedInterest','postedInterest','capitalizedCharges','otherDebt','principal'])
    p['postingInventory']['dueDates']=['2026-01-31']
    p['fees']['occurrences']=[dict(id='fee',amount='2.50',incurredDate='2026-01-31',dueDate='2026-01-31',order=0,externalAccountRole='settlement',evidenceIds=p['fieldEvidenceIds']['feeInventory'])]
    i.update({'from':'2026-01-31','toExclusive':'2026-02-01','confirmedAt':'2026-02-02T00:00:00Z','originalAnchor':'2025-12-31','obligationAmount':'70','openingOutstanding':'1060.005',
        'openingComponents':dict(principal='1000',postedInterest='10',accruedInterest='0.005',capitalizedCharges='20',otherDebt='30'),
        'externalAccounts':[dict(role='settlement',accountId='external')],
        'feeSettlements':[dict(occurrenceId='fee',externalAccountId='external',date='2026-01-31',amount='2.50',status='cleared')]})
    identity=digest(['mortgage-obligation-v1',s['id'],i['accountId'],'2026-01-31'])
    i['payments']=[dict(id='payment',obligationId=identity,accountId=i['accountId'],date='2026-01-31',phase=phase,order=0,amount='70',status='cleared')]
    return s,i,projection(s,i,bridge['records'][0]['result']['adapterInputs']['binding'],bridge['selection']['approval'],{'adult':dict(type='boolean',value=True)})


@pytest.mark.parametrize('phase',['before_accrual','after_accrual'])
def test_all_components_payment_fee_and_month_end_hand_anchor(phase):
    s,i,calculation=event_case(phase);expected=expectation(s,i,calculation)
    assert expected['issues']==[] and expected['loan']['obligations'][0]['status']=='paid'
    assert expected['totals']['feesPaidExternal']=='2.50' and expected['totals']['feesDebitedBalance']=='0.00'
    if phase=='before_accrual':
        assert expected['totals']['principalRepaid']=='9.99'
        assert expected['totals']['interestAccrued']=='0.099001000000'
        assert expected['totals']['interestRoundingAdjustment']=='0.005999000000'
        assert expected['loan']['closing']['principal']=='990.01' and expected['loan']['closing']['postedInterest']=='0.10'
    else:
        assert expected['totals']['principalRepaid']=='9.89'
        assert expected['totals']['interestAccrued']=='0.106000500000'
        assert expected['totals']['interestRoundingAdjustment']=='-0.001000500000'
        assert expected['loan']['closing']['principal']=='990.11' and expected['loan']['closing']['postedInterest']=='0.00'
    assert expected['totals']['closingBalance']=='990.11'
    assert expected['loan']['chargesPaid']=='20.00'
    assert Fraction(expected['loan']['outstandingDebt'])==Fraction(i['openingOutstanding'])+Fraction(expected['totals']['interestAccrued'])+Fraction(expected['totals']['interestRoundingAdjustment'])-70


def test_rounding_tie_and_negative_adjustment():
    assert rounded('0.005',2,'half_up')==Fraction(1,100)
    assert rounded('0.005',2,'half_even')==0
    assert rounded('-0.005',2,'half_up')==Fraction(-1,100)
