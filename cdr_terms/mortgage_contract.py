"""Mortgage capability semantics, sharing immutable wire-3 identity and storage."""
import calendar,json
from datetime import date,timedelta
from decimal import Decimal
from pathlib import Path
from jsonschema import Draft202012Validator,FormatChecker
from referencing import Registry,Resource
from .identity import digest
from .executable_contract import _bounded,_rules
from .executable_v2_contract import _offline
from .executable_v3_contract import identity,_range,_evidence
from .mortgage_material_fields import GROUPS

CAPABILITY='mortgage_calculation'
KIND='aud_mortgage_confirmed_obligations_v1'
ADAPTER='aud-mortgage-confirmed-obligations-v1'
EVALUATOR='product-terms-engine-v8'
ROOT=Path(__file__).resolve().parents[1]/'contracts/product_terms/monetary-v3'
ROLES={'opening_principal':('decimal','AUD'),'obligation_amount':('decimal','AUD'),
       'from_date':('date',None),'to_exclusive_date':('date',None),'confirmed_annual_rate':('decimal','fraction'),
       'offer_purpose':('text',None),'offer_security':('text',None),'repayment_type':('text',None)}


def schema_validate(value,name,limit=256*1024):
    _bounded(value,limit,ascii_keys=False)
    schemas={};registry=Registry(retrieve=_offline)
    for path in [ROOT/'schemas/common.schema.json',*(ROOT/'mortgage').glob('*.schema.json')]:
        schema=json.loads(path.read_bytes());schemas[path.name]=schema
        registry=registry.with_resource(schema['$id'],Resource.from_contents(schema))
    schema=schemas[('definitions' if name=='privateInput' else name)+'.schema.json']
    if name=='privateInput':schema={'$ref':schema['$id']+'#/$defs/privateInput'}
    Draft202012Validator(schema,registry=registry,format_checker=FormatChecker()).validate(value)


def periods(subject):
    """Exactly one selected winner per authority boundary segment."""
    scope=subject['scope'];graph=subject['authorityGraph'];selected=subject['policy']['authorityIds']
    authorities={a['id']:a for a in graph['authorities']};relations=graph['supersessions']
    points={scope['from'],scope['toExclusive']}
    for item in [*authorities.values(),*relations]:
        points.update(d for d in (item['from'],item['toExclusive']) if scope['from']<d<scope['toExclusive'])
    result=[];bounds=sorted(points);used=set()
    for lower,upper in zip(bounds,bounds[1:]):
        active=[a for a in authorities.values() if a['from']<=lower<upper<=a['toExclusive']]
        winners=[a for a in active if a['id'] in selected and all(a['id']==b['id'] or any(
            r['selectedAuthorityId']==a['id'] and r['supersededAuthorityId']==b['id'] and r['from']<=lower<upper<=r['toExclusive']
            for r in relations) for b in active)]
        if len(winners)!=1:raise ValueError('Mortgage authority conflict or gap')
        used.add(winners[0]['id'])
        result.append(dict(id=lower,authorityId=winners[0]['id'],**{'from':lower,'toExclusive':upper}))
    if used!=set(selected) or selected!=sorted(set(selected)):raise ValueError('Mortgage selected authority inventory differs')
    return result


def _policy(subject,known):
    policy=subject['policy'];scope=subject['scope'];definitions={}
    for item in policy['inputDefinitions']:
        field,role=item['field'],item['binding']
        if field in definitions or field in {'constructor','prototype','__proto__'} or not item['label'].strip():raise ValueError('Mortgage input definition differs')
        if role!='customer_fact':
            if field!=role or (item['type'],item['unit'])!=ROLES.get(role):raise ValueError('Mortgage scenario role differs')
        elif field in ROLES or (item['type']=='decimal' and (not item['unit'] or not item['unit'].strip())) or (item['type']!='decimal' and item['unit'] is not None):
            raise ValueError('Mortgage customer input cannot replace scenario role')
        definitions[field]=item
    _rules(policy['eligibility'],definitions,known,set())
    start,end=_range(scope['from'],scope['toExclusive'])
    if (end-start).days>policy['maxHorizonDays']:raise ValueError('Mortgage horizon exceeds policy')
    postings=[];current=start
    while current<end:
        if current.day==calendar.monthrange(current.year,current.month)[1]:postings.append(current.isoformat())
        current+=timedelta(days=1)
    inventory=policy['postingInventory']
    if inventory['dueDates']!=postings:raise ValueError('Mortgage posting inventory differs')
    seen=set();orders=set()
    for fee in policy['fees']['occurrences']:
        if fee['id'] in seen or (fee['dueDate'],fee['order']) in orders or not scope['from']<=fee['incurredDate']<=fee['dueDate']<scope['toExclusive']:
            raise ValueError('Mortgage fee occurrence or order differs')
        seen.add(fee['id']);orders.add((fee['dueDate'],fee['order']))


def validate_subject(subject):
    schema_validate(subject,'subject')
    if subject['id']!=identity(subject) or subject['scopeId']!=digest(['monetary-scope-v3',CAPABILITY,subject['scope']]):raise ValueError('Mortgage subject/scope identity differs')
    if subject['scope']['productKey']!=subject['routing']['productKey']:raise ValueError('Mortgage routing product differs')
    known=_evidence(subject);_policy(subject,known)
    from .mortgage_graph import validate_graph
    validate_graph(subject)
