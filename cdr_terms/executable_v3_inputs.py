"""Verification of the actual savings adapter projection; never source approval."""
import re
from datetime import date
from decimal import Decimal
from fractions import Fraction
from .identity import digest
from .executable_v2_inputs import exact_object,valid_fact
from .executable_v2_contract import validate_review_time
from .executable_eligibility import verify_eligibility

FIELDS=('accountId','startDate','endDateExclusive','openingBalance','confirmedAnnualRates','confirmedAt','openingAccrualZero','openingFundsCleared','noMovements','noWithholding')


def money(value):
    if not isinstance(value,str) or len(value)>72 or not re.fullmatch(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,24})?',value):raise ValueError('Savings opening amount invalid')
    cents=Fraction(value)*100
    if cents<0 or cents.denominator!=1:raise ValueError('Savings opening amount invalid')
    number=int(cents)
    return str(number//100)+'.'+str(number%100).zfill(2)


def check_inputs(subject,inputs):
    exact_object(inputs,FIELDS,'savings local inputs')
    if not isinstance(inputs['accountId'],str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.:-]{0,179}',inputs['accountId']) or inputs['accountId'] in ('constructor','prototype'):
        raise ValueError('Confirm the complete local account period and withholding treatment')
    if any(inputs[k] is not True for k in ('openingAccrualZero','noMovements','noWithholding')) or not (inputs['openingFundsCleared'] is None or type(inputs['openingFundsCleared']) is bool):
        raise ValueError('Confirm the complete local account period and withholding treatment')
    if not isinstance(inputs['confirmedAt'],str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z',inputs['confirmedAt']):
        raise ValueError('Confirm the complete local account period and withholding treatment')
    validate_review_time(inputs['confirmedAt'])
    start,end=inputs['startDate'],inputs['endDateExclusive']
    for value in (start,end):
        if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value) or not '1900-01-01'<=value<='2200-12-31':raise ValueError('Savings local date invalid')
    days=(date.fromisoformat(end)-date.fromisoformat(start)).days
    if not 0<days<=subject['policy']['maxHorizonDays'] or start<subject['scope']['from'] or end>min(subject['scope']['toExclusive'],subject['authorityGraph']['completedPeriod']['completedThroughExclusive']):
        raise ValueError('Account period is outside source-reviewed historical coverage')
    money(inputs['openingBalance'])
    intervals=[x for x in subject['policy']['intervals'] if x['from']<end and start<x['toExclusive']]
    if any(x['interest']['depositSettlementBasis']=='cleared_only' for x in intervals) and inputs['openingFundsCleared'] is not True:
        raise ValueError('All opening funds must be confirmed cleared for this policy')
    expected={(i['id'],t['id']):t['annualRate'] for i in intervals for t in i['tiers']}
    rates=inputs['confirmedAnnualRates'];seen=set()
    if not isinstance(rates,list) or len(rates)!=len(expected):raise ValueError('Confirm every applicable account rate tier')
    for item in rates:
        exact_object(item,('intervalId','tierId','annualRate'),'rate confirmation')
        value=item['annualRate'];key=(item['intervalId'],item['tierId'])
        if not isinstance(value,str) or len(value)>72 or not re.fullmatch(r'(?:0|[1-9][0-9]*)(?:\.[0-9]{1,12})?',value):raise ValueError('Account rate confirmation invalid')
        if key in seen or key not in expected or Decimal(value)!=Decimal(expected[key]):raise ValueError('Confirmed account rates differ from the reviewed historical schedule')
        seen.add(key)
    return intervals


def facts(subject,inputs,profile):
    if not isinstance(profile,dict) or not isinstance(profile.get('answers'),dict):raise ValueError('Savings profile invalid')
    result={};answers={}
    for definition in subject['policy']['inputDefinitions']:
        role,key=definition['binding'],definition['key']
        if role=='opening_balance':value=dict(type='decimal',value=inputs['openingBalance'],unit='AUD')
        elif role in ('calculation_start_date','calculation_end_date'):
            value=dict(type='date',value=inputs['startDate' if role=='calculation_start_date' else 'endDateExclusive'])
        else:
            identity='sav_'+digest([subject['id'],key]);answer=profile['answers'].get(identity)
            if answer is None:continue
            answers[identity]=answer
            if not isinstance(answer,dict) or answer.get('state')!='known':continue
            provenance=answer.get('provenance',{})
            if provenance.get('productKey')!=subject['scope']['productKey'] or provenance.get('effectiveFrom') and inputs['startDate']<provenance['effectiveFrom'] or provenance.get('effectiveToExclusive') and inputs['endDateExclusive']>provenance['effectiveToExclusive']:continue
            value=answer.get('fact')
        if valid_fact(value) and value['type']==definition['type'] and (value['type']!='decimal' or value['unit']==definition['unit']):result[key]=value
    return result,answers


def projection(subject,inputs,binding,approval,derived):
    intervals=check_inputs(subject,inputs);policy=subject['policy'];scope=subject['scope']
    start,end=inputs['startDate'],inputs['endDateExclusive'];first=intervals[0]['interest']
    refs=list(dict.fromkeys(e['id'] for e in subject['evidence']))
    dependencies=list(dict.fromkeys([binding[k] for k in ('manifestSha256','edition','indexSha256','shardSha256','assetSha256','coreSha256','detailsSha256','authorityGraphSha256')]+subject['documentVersionIds']+subject['termRevisionIds']))
    contract=dict(schemaVersion=1,evaluatorVersion=subject['evaluatorVersion'],id=subject['id'],productId=scope['productKey'],direction='asset',currency='AUD',
        review=dict(applicability='verified',materialTerms='verified',feeCoverage='verified',rateSchedule='verified',benchmarkSha256=approval['benchmarkResultSha256']),
        applicability=dict(cohortKey=scope['cohortKey'],**{'from':start,'toExclusive':end}),evidence=subject['evidence'],dependencyIds=dependencies,
        unsupportedTerms=[],eligibility=policy['eligibility'],initialAnnualRate='0',initialRateEvidenceIds=intervals[0]['fieldEvidenceIds']['rates'])
    contract['interest']={k:first[k] for k in ('dayCount','balanceBasis','eventOrder','dailyAccrualScale','dailyRateRounding','accrualRounding','postingRounding')}
    contract['interest'].update(postingDates=[d for d in policy['postingInventory']['dueDates'] if start<=d<end],offset='none',evidenceIds=refs)
    contract['savingsSchedule']=dict(schemaVersion=1,dailyAccrualRounding=first['dailyAccrualRounding'],intervals=[dict(id=i['id'],**{'from':max(start,i['from']),'toExclusive':min(end,i['toExclusive'])},
        evidenceIds=list(dict.fromkeys(r for refs in i['fieldEvidenceIds'].values() for r in refs)),components=[dict(id=i['id']+':base',kind='base',allocation=i['allocation'],rateMeaning='additive',tiers=i['tiers'],qualification=None,evidenceIds=i['fieldEvidenceIds']['rates'])]) for i in intervals])
    contract['feeSchedule']=dict(schemaVersion=1,accountId=inputs['accountId'],**{'from':start,'toExclusive':end},inventoryCoverage='reviewed_complete',deferredObligations='none_confirmed',evidenceIds=policy['fees']['evidenceIds'],
        inventory=[dict(categoryId=f['categoryId'],state='none_applicable',feeIds=[],evidenceIds=f['evidenceIds']) for f in policy['fees']['inventory']],ordering='before_scenario_events',fees=[])
    scenario=dict(accountId=inputs['accountId'],productId=scope['productKey'],cohortKey=scope['cohortKey'],startDate=start,endDateExclusive=end,openingBalance=money(inputs['openingBalance']),initialOffset='0',facts=derived,events=[],assumptions=[])
    return dict(contract=contract,scenario=scenario)


def validate_result(result,subject,raw):
    exact_object(raw,('target','inputs','profile'),'savings raw call')
    exact_object(result,('schemaVersion','evaluationKind','adapterVersion','evaluatorVersion','verificationScope','basis','adapterInputs','inputSha256','calculationInputs','receipt'),'savings result')
    if result['schemaVersion']!=1 or result['evaluationKind']!=subject['capability'] or any(result[k]!=subject[k] for k in ('adapterVersion','evaluatorVersion')):raise ValueError('Savings result version differs')
    value=result['adapterInputs'];exact_object(value,('subject','approval','binding','target','inputs','customerAnswers','facts'),'savings adapter input')
    derived,answers=facts(subject,raw['inputs'],raw['profile'])
    if value['subject']!=subject or value['target']!=raw['target'] or value['inputs']!=raw['inputs'] or value['facts']!=derived or value['customerAnswers']!=answers or result['inputSha256']!=digest(value):raise ValueError('Savings raw adapter input propagation differs')
    expected=projection(subject,raw['inputs'],value['binding'],value['approval'],derived)
    if result['calculationInputs']!=expected:raise ValueError('Savings actual contract/scenario projection differs')
    receipt=result['receipt']
    if receipt['inputSha256']!=digest(dict(evaluatorVersion=subject['evaluatorVersion'],**expected)) or receipt['contractId']!=subject['id'] or receipt['dependencies']!=expected['contract']['dependencyIds'] or receipt['eligibility']!=verify_eligibility(subject['policy']['eligibility'],derived):raise ValueError('Savings evaluator input/eligibility differs')
