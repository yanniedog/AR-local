"""Independent verification of the declared mortgage adapter's private admission."""
import calendar,re
from datetime import date
from fractions import Fraction
from .identity import digest
from .mortgage_contract import schema_validate,periods
from .executable_v3_inputs import money
from .executable_v3_graph import _covers
from .executable_v2_inputs import valid_fact
from .executable_eligibility import verify_eligibility

COMPONENTS=('principal','postedInterest','accruedInterest','capitalizedCharges','otherDebt')


def safe_id(value):
    return isinstance(value,str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_.:-]{0,179}',value) and value not in ('constructor','prototype')


def component(value):
    if not isinstance(value,str) or len(value)>72 or not re.fullmatch(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,24})?',value):raise ValueError('loan_component_precision_invalid')
    result=Fraction(value)
    if result<0 or (result*10**12).denominator!=1:raise ValueError('loan_component_precision_invalid')
    return result


def fixed(value,scale):
    integer=Fraction(value)*10**scale
    if integer.denominator!=1:raise ValueError('Mortgage exact decimal projection differs')
    n=int(integer);return str(n//10**scale)+'.'+str(n%10**scale).zfill(scale)


def due_dates(subject,anchor):
    a=date.fromisoformat(anchor);start,end=subject['scope']['from'],subject['scope']['toExclusive']
    if anchor>start:raise ValueError('Mortgage anchor follows opening date')
    finish=date.fromisoformat(end);count=(finish.year-a.year)*12+finish.month-a.month
    if count>1200:raise ValueError('Mortgage anchor is outside supported calendar')
    result=[]
    for offset in range(count+1):
        year,month=divmod(a.year*12+a.month-1+offset,12);month+=1;last=calendar.monthrange(year,month)[1]
        day=last if subject['policy']['obligationCalendar']['monthConvention']=='preserve_month_end' and a.day==calendar.monthrange(a.year,a.month)[1] else min(a.day,last)
        current=date(year,month,day).isoformat()
        if current>=end:break
        if current>=start:result.append(current)
    if len(result)>24:raise ValueError('Mortgage obligation limit')
    return result


def event_coverage(subject,dates):
    authorities={a['id']:a for a in subject['authorityGraph']['authorities']}
    for field in ('obligationCalendar','paymentPhase','paymentRounding','accruedSettlement'):
        refs=set(subject['policy']['fieldEvidenceIds'][field]);entries=[]
        for segment in periods(subject):
            entries.extend((segment,e) for e in authorities[segment['authorityId']]['fieldCoverage'] if e['field']==field and set(e['evidenceIds'])&refs)
        if any(not any(max(s['from'],e['from'])<=d<min(s['toExclusive'],e['toExclusive']) and d in e['postingEventDates'] for s,e in entries) for d in dates):raise ValueError('Mortgage field event gap')


def check_inputs(subject,inputs):
    schema_validate(inputs,'privateInput',512*1024);p=subject['policy'];i=inputs
    if not all(safe_id(i[k]) for k in ('accountId','offerId','sourceVersion','snapshotId')) or (i['from'],i['toExclusive'])!=(subject['scope']['from'],subject['scope']['toExclusive']) or i['noCarriedArrearsOrDefault'] is not True or i['noExcludedMovements'] is not True or i['executionCoverage']!='complete':raise ValueError('Mortgage account period or confirmations unavailable')
    if Fraction(i['confirmedAnnualRate'])!=Fraction(p['annualRate']):raise ValueError('Confirmed mortgage rate differs')
    total=sum(component(i['openingComponents'][k]) if k=='accruedInterest' else Fraction(money(i['openingComponents'][k])) for k in COMPONENTS)
    if total!=component(i['openingOutstanding']):raise ValueError('Mortgage opening components do not reconcile')
    amount=money(i['obligationAmount'])
    if Fraction(amount)<=0:raise ValueError('Mortgage obligation must be positive')
    due=due_dates(subject,i['originalAnchor']);event_coverage(subject,due)
    obligations=[dict(id=digest(['mortgage-obligation-v1',subject['id'],i['accountId'],d]),dueDate=d,accountId=i['accountId'],amount={'type':'fixed','value':amount},evidenceIds=p['fieldEvidenceIds']['obligationCalendar']) for d in due]
    paid={};orders=set();ids=set()
    for e in i['payments']:
        obligation=next((o for o in obligations if o['id']==e['obligationId']),None);key=(e['date'],e['order']);value=Fraction(money(e['amount']))
        if not safe_id(e['id']) or e['id'] in ids or key in orders or e['accountId']!=i['accountId'] or obligation is None:raise ValueError('Mortgage payment identity invalid')
        ids.add(e['id']);orders.add(key)
        if e['date']!=obligation['dueDate'] or e['phase']!=p['paymentPhase']:raise ValueError('Mortgage payment timing unsupported')
        if value<=0:raise ValueError('Mortgage payment must be positive')
        paid[e['obligationId']]=paid.get(e['obligationId'],Fraction(0))+value
        if paid[e['obligationId']]>Fraction(amount):raise ValueError('Mortgage payment exceeds obligation')
    positive=[f for f in p['fees']['occurrences'] if Fraction(money(f['amount']))>0]
    if len(i['feeSettlements'])!=len(positive) or len({f['occurrenceId'] for f in i['feeSettlements']})!=len(positive) or len({a['role'] for a in i['externalAccounts']})!=len(i['externalAccounts']) or any(not safe_id(a['accountId']) or a['accountId']==i['accountId'] for a in i['externalAccounts']):raise ValueError('Mortgage fee settlement inventory invalid')
    for fee in positive:
        x=next((x for x in i['feeSettlements'] if x['occurrenceId']==fee['id']),None);account=next((a for a in i['externalAccounts'] if a['role']==fee['externalAccountRole']),None)
        if x is None or account is None or x['externalAccountId']!=account['accountId'] or x['date']!=fee['dueDate'] or Fraction(money(x['amount']))!=Fraction(money(fee['amount'])):raise ValueError('Mortgage external fee settlement differs')
    definitions={d['field']:d for d in p['inputDefinitions']}
    if len({f['field'] for f in i['customerFacts']})!=len(i['customerFacts']) or any(definitions.get(f['field'],{}).get('binding')!='customer_fact' or (f['state']=='known')!=(f['value'] is not None) for f in i['customerFacts']):raise ValueError('Mortgage customer fact binding invalid')
    return obligations


def facts(subject,inputs,profile):
    if not isinstance(profile,dict) or not isinstance(profile.get('answers'),dict):raise ValueError('Mortgage profile invalid')
    scenario={'opening_principal':dict(type='decimal',unit='AUD',value=inputs['openingComponents']['principal']),'obligation_amount':dict(type='decimal',unit='AUD',value=inputs['obligationAmount']),
              'from_date':dict(type='date',value=inputs['from']),'to_exclusive_date':dict(type='date',value=inputs['toExclusive']),'confirmed_annual_rate':dict(type='decimal',unit='fraction',value=inputs['confirmedAnnualRate'])}
    for role,key in (('offer_purpose','purpose'),('offer_security','security'),('repayment_type','repaymentType')):
        if key in inputs['confirmedOfferFacts']:scenario[role]=dict(type='text',value=inputs['confirmedOfferFacts'][key])
    result={};answers={}
    for d in subject['policy']['inputDefinitions']:
        value=scenario.get(d['binding'])
        if d['binding']=='customer_fact':
            direct=next((f for f in inputs['customerFacts'] if f['field']==d['field']),None);key='mort_'+digest([subject['id'],d['field']]);answer=profile['answers'].get(key)
            if direct is not None:value=direct['value'] if direct['state']=='known' else None
            elif answer is not None:
                answers[key]=answer;provenance=answer.get('provenance',{})
                if answer.get('state')=='known' and provenance.get('productKey')==subject['scope']['productKey'] and (not provenance.get('effectiveFrom') or inputs['from']>=provenance['effectiveFrom']) and (not provenance.get('effectiveToExclusive') or inputs['toExclusive']<=provenance['effectiveToExclusive']):value=answer.get('fact')
        if valid_fact(value) and value['type']==d['type'] and (value['type']!='decimal' or value['unit']==d['unit']):result[d['field']]=value
    return result,answers


def require_offer_facts(subject,derived):
    """Same decisive-branch discovery as the shared customer-input controller."""
    definitions={d['field']:d for d in subject['policy']['inputDefinitions']}
    def visit(rule):
        if verify_eligibility(rule,derived)['status']!='needs_information':return
        if rule['op']=='compare':
            if definitions[rule['field']]['binding']!='customer_fact':raise ValueError('Mortgage relevant offer confirmation missing')
        elif rule['op']=='not':visit(rule['rule'])
        else:
            for child in rule['rules']:visit(child)
    visit(subject['policy']['eligibility'])
