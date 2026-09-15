"""Reviewed structured monetary fields; source prose never becomes implicit policy."""
import json
import hashlib
from pathlib import Path
from datetime import date
from jsonschema import Draft202012Validator

SCHEMA=Path(__file__).resolve().parents[1]/'contracts/product_terms/drafts/material-fields-v1/savings-base-field.schema.json'
SCHEMA_SHA='ca1dc03ba73dffc5430f249a4e7968ea288adb053bfdb8d85b66a2d444286953'

def validate_field_value(value):
    from .executable_contract import _bounded
    _bounded(value,256*1024)
    raw=SCHEMA.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SCHEMA_SHA:raise ValueError('Monetary material schema identity differs')
    Draft202012Validator(json.loads(raw)).validate(value)
    if date.fromisoformat(value['from'])>=date.fromisoformat(value['toExclusive']):raise ValueError('Material interval invalid')

def _semantic(value):
    if isinstance(value,list):return [_semantic(x) for x in value]
    if isinstance(value,dict):return {k:_semantic(v) for k,v in value.items() if k not in ('evidenceIds','completenessEvidenceIds','fieldEvidenceIds','authorityId')}
    return value

def project_field(subject,period,field):
    policy=subject['policy'];interest=period['interest']
    def pick(source,*keys):return {key:source[key] for key in keys}
    values={
        'rates':dict(currency='AUD',rateUnit='fraction_per_year',amountUnit='AUD',**pick(period,'kind','rateMeaning','tiers')),
        'allocation':dict(allocation=period['allocation'],amountUnit='AUD',tiers=[pick(t,'id','upperInclusive') for t in period['tiers']]),
        'balanceBasis':dict(currency='AUD',**pick(interest,'balanceBasis'),**pick(policy,'externalMovements','withholding','initialUnpostedAccrual','calculationMode','maxHorizonDays')),
        'dailyRateRounding':dict(rateUnit='fraction_per_year',**pick(interest,'dailyRateRounding')),
        'dailyAccrualRounding':dict(amountUnit='AUD',**pick(interest,'dailyAccrualScale','accrualRounding','dailyAccrualRounding')),
        'postingRounding':dict(amountUnit='AUD',postingScale=2,**pick(interest,'postingRounding')),
        'postingResidue':dict(amountUnit='AUD',**pick(interest,'postingResidue')),
        'postingDates':dict(postingInventory=policy['postingInventory'],**pick(interest,'postingCalendar')),
        'depositSettlementBasis':dict(**pick(interest,'depositSettlementBasis'),**pick(policy,'openingClearedFunds')),
        'noBonusIntro':pick(policy,'bonus','intro'),
        'noOffsetLinkedAccounts':pick(policy,'offset','linkedAccounts'),
        'feeCoverage':dict(currency='AUD',**pick(policy['fees'],'coverage','inventory')),
        'noDeferredObligations':pick(policy['fees'],'deferredObligations'),
        'eligibility':pick(policy,'eligibility','inputDefinitions'),
    }
    for name in ('dayCount','eventOrder','postingDestination'):values[name]=pick(interest,name)
    return _semantic(values[field])

def field_value(subject,period,field):
    scope={k:subject['scope'][k] for k in ('productKey','cohortKey','tierKey','packageKey')}
    value=dict(schemaVersion=1,field=field,scope=scope,material=project_field(subject,period,field),
        **{'from':period['from'],'toExclusive':period['toExclusive']})
    validate_field_value(value)
    return value


def validate_material_coverage(store,subject,authority,coverage,revisions,operation):
    from .executable_v3_graph import _covers
    from .parameter_registry import validate_registry_context,VERSION,SAVINGS_VERSION
    from .executable_v3_sources import _json
    from .monetary_capabilities import periods
    parameter='monetary.savings_base_field_v1';versions=(VERSION,SAVINGS_VERSION);validate=validate_field_value
    project=lambda period,field:project_field(subject,period,field)
    if subject['capability']=='mortgage_calculation':
        from .mortgage_material_fields import project_field as mortgage_project,validate_field_value as mortgage_validate
        parameter='monetary.mortgage_field_v1';versions=(VERSION,);validate=mortgage_validate
        project=lambda period,field:mortgage_project(subject,field)
    scope={k:subject['scope'][k] for k in ('productKey','cohortKey','tierKey','packageKey')}
    for period in periods(subject):
        if period['authorityId']!=authority['id']:continue
        lower=max(period['from'],coverage['from']);upper=min(period['toExclusive'],coverage['toExclusive'])
        if lower>=upper:continue
        material=project(period,coverage['field'])
        for clause in coverage['evidenceIds']:
            ranges=[]
            for revision in revisions.values():
                row=revision['row']
                if clause not in revision['clauses'] or row['parameter_key']!=parameter or row['unit'] is not None:continue
                context=_json(operation,row['context_sha256'])
                validate_registry_context(context)
                if context.get('parameter_registry',{}).get('version') not in versions:continue
                cache=getattr(operation,'material_values',None)
                if cache is None:cache={};operation.material_values=cache
                key=(parameter,row['term_revision_id'],row['context_sha256'],row['value_json'])
                if key not in cache:
                    if len(cache)>=256 or len(row['value_json'].encode('utf8'))>256*1024:raise ValueError('Monetary material revision bound exceeded')
                    value=json.loads(row['value_json']);validate(value);cache[key]=value
                value=cache[key]
                if value['field']==coverage['field'] and value['scope']==scope and value['material']==material:
                    bounds=revision['applicability']
                    if bounds['effective_from'] is None or bounds['effective_to'] is None:continue
                    ranges.append((max(value['from'],bounds['effective_from']),min(value['toExclusive'],bounds['effective_to'])))
            if not _covers(ranges,lower,upper):raise ValueError('Monetary field lacks matching reviewed structured material')
