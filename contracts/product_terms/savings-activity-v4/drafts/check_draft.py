"""Bounded draft structural/cross-input controls; no source acceptance or engine run."""
import copy,json,hashlib
from pathlib import Path
from jsonschema import Draft202012Validator,FormatChecker,ValidationError
from referencing import Registry,Resource
from semantic_controls import validate
ROOT=Path(__file__).parent
schemas={json.loads(p.read_bytes())['$id']:json.loads(p.read_bytes()) for p in ROOT.glob('*.schema.json')}
registry=Registry().with_resources((k,Resource.from_contents(v)) for k,v in schemas.items())
for schema in schemas.values():Draft202012Validator.check_schema(schema)
def walk(node):
    if isinstance(node,dict):
        if '$ref' in node:yield node['$ref']
        for v in node.values():yield from walk(v)
    elif isinstance(node,list):
        for v in node:yield from walk(v)
for identity,schema in schemas.items():
    for ref in walk(schema):
        target,_,fragment=ref.partition('#');value=schemas[target or identity]
        for key in fragment.lstrip('/').split('/') if fragment else []:
            key=key.replace('~1','/').replace('~0','~');value=value[int(key)] if isinstance(value,list) else value[key]
example=json.loads((ROOT/'positive-technical-example.json').read_bytes());subject,private=example['subject'],example['privateInput'];results=[]
def structural(s,p):
    for name,value in [('subject',s),('private-input',p)]:
        Draft202012Validator(schemas['urn:ar-local:savings-activity-wire4-draft:'+name],registry=registry,format_checker=FormatChecker()).validate(value)
structural(subject,private);validate(subject,private);assert len(private['confirmedBonusAnnualRates'])==32;assert subject['evidence'][0]['id'][0].isdigit();results.append('positive32tiers_uppercase_dotted_ids_leading_digit_hash_decimal_amount_rate')
SCHEMA_REFUSALS = {
    'named_evidence_ref_refused': ('pattern', ['policy','bonus','evidenceIds',0]),
    '33_bonus_tiers_refused': ('maxItems', ['policy','bonus','tiers']),
    'mixed_event_bases': ('anyOf', []),
    'event_amount_subcent': ('pattern', ['activity','events',0,'amount']),
    'invalid_event_id': ('pattern', ['activity','events',0,'id']),
    'private_aggregate': ('additionalProperties', []),
    'missing_bonus_confirmation_property': ('required', []),
}

def case(name,change,stage='semantic',reason=None):
    s,p=copy.deepcopy(subject),copy.deepcopy(private);change(s,p)
    try:
        structural(s,p)
        if stage=='semantic':validate(s,p)
    except Exception as error:
        if stage=='schema':
            if not isinstance(error, ValidationError): raise
            expected_validator, expected_path = SCHEMA_REFUSALS[name]
            if error.validator != expected_validator or list(error.path) != expected_path: raise
        if stage=='semantic' and (type(error) is not ValueError or reason and str(error)!=reason):raise
        results.append(name);return
    raise AssertionError(name+' accepted')
case('named_evidence_ref_refused',lambda s,p:s['policy']['bonus']['evidenceIds'].__setitem__(0,'named_reference'),'schema')
case('33_bonus_tiers_refused',lambda s,p:s['policy']['bonus']['tiers'].append(copy.deepcopy(s['policy']['bonus']['tiers'][-1])),'schema')
case('missing_bonus_inventory',lambda s,p:p['confirmedBonusAnnualRates'].pop(),reason='missing_bonus_rates')
case('duplicate_bonus_key_different_rate',lambda s,p:p['confirmedBonusAnnualRates'].__setitem__(1,dict(p['confirmedBonusAnnualRates'][0],annualRate='0.02')),reason='duplicate_bonus_rates')
case('wrong_bonus_rate',lambda s,p:p['confirmedBonusAnnualRates'][0].update(annualRate='0.02'),reason='value_bonus_rates')
case('mixed_event_bases',lambda s,p:p['activity']['events'].append(dict(p['activity']['events'][0],id='Second',dateBasis='transaction')),'schema')
case('event_basis_differs_source',lambda s,p:p['activity']['events'][0].update(dateBasis='transaction'),reason='event_basis')
case('event_amount_subcent',lambda s,p:p['activity']['events'][0].update(amount='100.251'),'schema')
case('invalid_event_id',lambda s,p:p['activity']['events'][0].update(id='1 invalid'),'schema')
case('event_in_application',lambda s,p:p['activity']['events'][0].update(date='2026-01-01'),reason='event_window')
case('wrong_account',lambda s,p:p['activity']['events'][0].update(accountId='other'),reason='event_account')
case('duplicate_event',lambda s,p:p['activity']['events'].append(copy.deepcopy(p['activity']['events'][0])),reason='duplicate_event')
case('overlap_windows',lambda s,p:s['policy']['bonus']['assessment'].update(toExclusive='2026-01-02'),reason='preceding_window')
case('combined_horizon',lambda s,p:s['policy']['bonus']['assessment'].update(**{'from':'2024-01-01'}),reason='combined_horizon')
case('source_completion',lambda s,p:s['authorityGraph']['completedPeriod'].update(completedThroughExclusive='2026-01-10'),reason='source_completion')
case('classification_overlap',lambda s,p:s['policy']['bonus']['assessment']['metrics'][0]['excludedClassifications'].append('customer'),reason='classification_overlap')
case('undeclared_metric',lambda s,p:s['policy']['bonus']['assessment']['rule']['rules'][1].update(field='activity_deposit_total',expected=dict(type='decimal',value='0',unit='AUD')),reason='metric_rule_inventory')
case('private_aggregate',lambda s,p:p.update(deposit_total='9999'),'schema')
case('missing_bonus_confirmation_property',lambda s,p:p.pop('confirmedBonusAnnualRates'),'schema')
case('coverage_binding',lambda s,p:p['activity']['coverage'][0].update(accountId='other'),reason='coverage_binding')
p=copy.deepcopy(private);p['activity']['coverage'][0]['status']='unknown';structural(subject,p);validate(subject,p);results.append('unknown_coverage_retained_not_asserted_complete')
receipt={'status':'DRAFT_CONTROLS_PASS_NOT_FROZEN','schemas':len(schemas),'controls':len(results),'results':results,'limitations':['No actual SourceStore, engine execution or bank approval','Partial cross-input semantic checks only; full graph/material/migration/connected benchmark gates pending'],'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ROOT.iterdir()) if p.is_file() and p.name not in ['controls-receipt.json','schema-check.json']}}
(ROOT/'controls-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf8');print(json.dumps({'status':receipt['status'],'schemas':len(schemas),'controls':len(results)}))
