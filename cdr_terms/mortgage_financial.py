"""Fraction verification oracle for the supported fixed-policy mortgage projection.

Independent of app execution. Original eighteen anchor expectations stay immutable.
"""
import calendar
from datetime import date,timedelta
from fractions import Fraction as F
from .identity import digest
from .mortgage_inputs import COMPONENTS,check_inputs
from .mortgage_projection import unique
from .executable_v2_inputs import exact_object


def rounded(value,scale,mode='half_up'):
    value=F(value);factor=10**scale;sign=-1 if value<0 else 1
    whole,remainder=divmod(abs(value.numerator)*factor,value.denominator)
    if mode=='away_from_zero':up=bool(remainder)
    elif mode=='toward_zero':up=False
    elif mode in ('half_up','half_even'):
        doubled=remainder*2;up=doubled>value.denominator or doubled==value.denominator and (mode=='half_up' or whole%2==1)
    else:raise ValueError('Mortgage unsupported rounding mode')
    return F(sign*(whole+int(up)),factor)


def text(value,scale=2):
    n=int(rounded(value,scale)*10**scale);digits=str(abs(n)).zfill(scale+1)
    return ('-' if n<0 else '')+(digits[:-scale]+'.'+digits[-scale:] if scale else digits)


def expectation(subject,inputs,calculation):
    obligations=check_inputs(subject,inputs);p=subject['policy'];contract=calculation['contract']
    balances={k:F(inputs['openingComponents'][k]) for k in COMPONENTS};opening=sum(balances.values())
    allocation={k:F(0) for k in COMPONENTS};paid_by={};accrued=posted=adjustment=payments=fee_total=F(0)
    ledger=[];daily=[];current=date.fromisoformat(inputs['from']);end=date.fromisoformat(inputs['toExclusive'])
    executions=sorted(inputs['payments'],key=lambda x:(x['date'],x['order']))
    fees=sorted(contract['feeSchedule']['fees'],key=lambda x:x['order'])
    def line(day,identity,kind,amount,evidence,note,**extra):
        ledger.append(dict(date=day,id=identity,type=kind,amount=text(amount,12 if kind=='interest_accrual' else 2),balance=text(sum(balances.values())),evidenceIds=evidence,note=note,**extra))
    def settle(mode):
        old=balances['accruedInterest'];balances['accruedInterest']=rounded(old,2,mode)
        return balances['accruedInterest']-old
    while current<end:
        day=current.isoformat();before=sum(balances.values());day_interest=day_payment=day_adjustment=F(0)
        today=[e for e in executions if e['date']==day]
        def apply_payments():
            nonlocal payments,adjustment,day_payment,day_adjustment
            for e in today:
                delta=settle(p['paymentRounding']);adjustment+=delta;day_adjustment+=delta
                amount=F(e['amount']);remaining=amount
                if amount>sum(balances.values()):raise ValueError('loan_overpayment_rejected')
                for k in p['allocation']:
                    taken=min(remaining,balances[k]);balances[k]-=taken;allocation[k]+=taken;remaining-=taken
                if remaining:raise ValueError('Mortgage payment allocation incomplete')
                payments+=amount;day_payment+=amount;paid_by[e['obligationId']]=paid_by.get(e['obligationId'],F(0))+amount
                line(day,e['id'],'cashflow',amount,e['evidenceIds'] if 'evidenceIds' in e else p['fieldEvidenceIds']['paymentPhase'],'Payment received; source-defined component allocation.',settlementStatus='cleared')
        def apply_fees():
            nonlocal fee_total
            for fee in fees:
                occurrence=fee['timing']['occurrences'][0]
                if occurrence['dueDate']!=day:continue
                amount=F(fee['price']['value']);fee_total+=amount
                identity='fee:'+digest([fee['chargeIdentity'],'account',inputs['accountId'],occurrence['triggerId']])
                line(day,identity,'fee',amount,fee['evidenceIds'],'Paid from the separately nominated account; product balance unchanged.',feeRuleTraces=[],feeDebitAccountId=fee['debit']['accountId'])
        if p['fees']['ordering']=='before_scenario_events':apply_fees()
        if p['paymentPhase']=='before_accrual':
            apply_payments()
            if p['fees']['ordering']=='after_scenario_events':apply_fees()
        basis=sum(balances[k] for k in p['interestBearing']);divisor=366 if p['dayCount']=='actual_actual' and calendar.isleap(current.year) else 365
        daily_rate=F(p['annualRate'])/divisor
        if p['dailyRateRounding']:
            rule=p['dailyRateRounding'];unit=100 if rule['unit']=='percent' else 1
            daily_rate=rounded(daily_rate*unit,rule['scale'],rule['mode'])/unit
        day_interest=basis*daily_rate
        if p['dailyAccrualScale'] is not None:day_interest=rounded(day_interest,p['dailyAccrualScale'],p['accrualRounding'])
        balances['accruedInterest']+=day_interest;accrued+=day_interest
        evidence=unique([*contract['interest']['evidenceIds'],*contract['initialRateEvidenceIds'],*contract['loanContract']['evidenceIds']])
        line(day,'accrue:'+day,'interest_accrual',day_interest,evidence,'New daily interest cost.')
        if p['paymentPhase']=='after_accrual':
            apply_payments()
            if p['fees']['ordering']=='after_scenario_events':apply_fees()
        if day in p['postingInventory']['dueDates']:
            delta=settle(p['postingRounding']);adjustment+=delta;day_adjustment+=delta
            amount=balances['accruedInterest'];balances['postedInterest']+=amount;balances['accruedInterest']=F(0);posted+=amount
            line(day,'post:'+day,'interest_posting',amount,contract['interest']['evidenceIds'],'Transfer unposted interest into posted debt; no new cost.')
        if sum(balances.values())!=before+day_interest+day_adjustment-day_payment:raise ValueError('Mortgage daily conservation failed')
        daily.append(dict(date=day,interestBasis=text(basis,12),interestAccrued=text(day_interest,12),roundingAdjustment=text(day_adjustment,12),payment=text(day_payment),outstandingDebt=text(sum(balances.values()),12)))
        current+=timedelta(days=1)
    statuses=[];issues=[]
    for o in obligations:
        due=F(o['amount']['value']);paid=paid_by.get(o['id'],F(0));status='paid' if paid>=due else 'unpaid' if not paid else 'partial'
        statuses.append(dict(id=o['id'],dueDate=o['dueDate'],due=text(due),paid=text(paid),status=status))
        if status!='paid':issues.append('loan_obligation_'+status+':'+o['id'])
    closing=sum(balances.values())
    if closing!=opening+accrued+adjustment-payments:raise ValueError('Mortgage period conservation failed')
    values=lambda rows:{k:text(rows[k],12 if k=='accruedInterest' else 2) for k in COMPONENTS}
    loan=dict(componentStatus='known',outstandingDebt=text(closing,12),knownComponentDebt=text(closing,12),opening=values({k:F(inputs['openingComponents'][k]) for k in COMPONENTS}),closing=values(balances),
        principalAdvanced='0.00',principalRepaid=text(allocation['principal']),interestPaid=text(allocation['accruedInterest']+allocation['postedInterest']),chargesPaid=text(allocation['capitalizedCharges']),redrawAvailable='0.00',redrawUsed='0.00',obligations=statuses,perspective='product_account_with_external_fees_separate')
    totals=dict(openingBalance=calculation['scenario']['openingBalance'],closingBalance=text(closing),principalRepaid=text(allocation['principal']),externalInflows=text(payments),externalOutflows='0.00',externalCashflowNet=text(payments),interestAccrued=text(accrued,12),interestPosted=text(posted),interestUnposted=text(balances['accruedInterest'],12),interestRoundingAdjustment=text(adjustment,12),feesCharged=text(fee_total),feesDebitedBalance='0.00',feesPaidExternal=text(fee_total))
    return dict(loan=loan,totals=totals,ledger=ledger,issues=issues,daily=daily)


def verify_financial(result,subject,inputs):
    # Caller first verifies the complete independent adapter projection.
    expected=expectation(subject,inputs,result['calculationInputs']);receipt=result['receipt']
    exact_object(receipt,('schemaVersion','evaluatorVersion','inputSha256','contractId','dependencies','status','completeness','issueDetails','claimAvailable','issues','assumptions','eligibility','totals','ledger','loan'),'mortgage evaluator receipt')
    if (type(receipt['schemaVersion']) is not int or receipt['schemaVersion']!=1 or receipt['evaluatorVersion']!=subject['evaluatorVersion']
        or receipt['status']!='complete' or receipt['completeness']!='factual_complete' or receipt['claimAvailable'] is not True
        or expected['issues'] or receipt['issues']!=[] or receipt['issueDetails']!=[] or receipt['assumptions']!=[] or receipt['eligibility']['status']!='meets'):
        raise ValueError('Mortgage benchmark requires complete independently eligible calculation')
    for key in ('totals','loan','ledger'):
        if digest(receipt[key])!=digest(expected[key]):raise ValueError('Mortgage '+key+' differs from independent arithmetic')
    return dict(kind='technical_calculation',**expected)
