"""Closed monetary wire semantics. Structured source claims are not approval."""
import calendar
import json
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlsplit
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from .identity import digest, byte_digest
from .executable_contract import _bounded, _rules
from .executable_v2_contract import _offline, validate_review_time
from .executable_v3_migration import ROOT

CAPABILITY = 'savings_calculation'
KIND = 'aud_savings_base_period_v1'
ADAPTER = 'aud-savings-base-v1'
EVALUATOR = 'product-terms-engine-v8'
ROLES = {'opening_balance':('decimal','AUD'),'calculation_start_date':('date',None),'calculation_end_date':('date',None)}


def schema_validate(value,name,limit=256*1024):
    _bounded(value,limit,ascii_keys=False)
    schemas={p.name:json.loads(p.read_bytes()) for p in (ROOT/'schemas').glob('*.schema.json')}
    registry=Registry(retrieve=_offline)
    for filename,schema in schemas.items():
        resource=Resource.from_contents(schema)
        registry=registry.with_resource(filename,resource).with_resource(schema['$id'],resource)
    Draft202012Validator(schemas[name+'.schema.json'],registry=registry,format_checker=FormatChecker()).validate(value)


def identity(value,field='id'):
    return digest({k:v for k,v in value.items() if k!=field})


def _range(lower,upper):
    a,b=date.fromisoformat(lower),date.fromisoformat(upper)
    if a>=b or not '1900-01-01'<=lower<upper<='2200-12-31':
        raise ValueError('Monetary interval invalid')
    return a,b


def _refs(value,known):
    pending=[value]
    while pending:
        node=pending.pop()
        if isinstance(node,dict):
            for key,item in node.items():
                if key.endswith('EvidenceIds') or key=='evidenceIds' or key=='datedRateAndPolicyClauseIds':
                    refs = [ref for values in item.values() for ref in values] if isinstance(item,dict) else item
                    if not set(refs)<=known: raise ValueError('Monetary evidence reference missing')
                pending.append(item)
        elif isinstance(node,list): pending.extend(node)


def _evidence(subject):
    known=set()
    for item in subject['evidence']:
        parsed=urlsplit(item['sourceUrl'])
        if (parsed.scheme!='https' or not parsed.hostname or parsed.username is not None or parsed.password is not None
            or any(ord(c)<=32 for c in item['sourceUrl']) or chr(92) in item['sourceUrl']):
            raise ValueError('Monetary source URL invalid')
        parsed.port
        if item['id']!=item['clauseId'] or item['id'] in known or byte_digest(item['quote'].encode('utf8'))!=item['quoteSha256']:
            raise ValueError('Monetary evidence identity differs')
        known.add(item['id'])
    if subject['documentVersionIds']!=sorted({e['documentVersionId'] for e in subject['evidence']}):
        raise ValueError('Monetary document inventory differs')
    if subject['termRevisionIds']!=sorted(set(subject['termRevisionIds'])):
        raise ValueError('Monetary revision inventory differs')
    _refs(subject,known)
    return known


def _inputs(policy,known):
    definitions,bindings={},set()
    for item in policy['inputDefinitions']:
        key,role=item['key'],item['binding']
        if key in definitions or key in {'constructor','prototype','__proto__'} or not item['label'].strip():
            raise ValueError('Monetary input key/label invalid')
        definitions[key]=item
        if role!='customer_fact':
            if role in bindings or (item['type'],item['unit'])!=ROLES[role]:
                raise ValueError('Monetary scenario binding differs')
            bindings.add(role)
        elif (item['type']=='decimal' and (not item['unit'] or not item['unit'].strip())) or (item['type']!='decimal' and item['unit'] is not None):
            raise ValueError('Monetary input unit invalid')
    if bindings!=set(ROLES): raise ValueError('Monetary required local bindings missing')
    _rules(policy['eligibility'],definitions,known,set())


def posting_dates(policy,scope):
    inventory=policy['postingInventory']
    if (inventory['from'],inventory['toExclusive'])!=(scope['from'],scope['toExclusive']):
        raise ValueError('Monetary posting inventory coverage differs')
    start,end=_range(inventory['from'],inventory['toExclusive'])
    if (end-start).days>366: raise ValueError('Monetary source scope exceeds horizon bound')
    rule=inventory['rule']
    if rule['kind']=='calendar_month_end':
        expected=[]; current=start
        while current<end:
            if current.day==calendar.monthrange(current.year,current.month)[1]: expected.append(current.isoformat())
            current+=timedelta(days=1)
    else:
        if rule['sourceFrom']>scope['from'] or rule['sourceToExclusive']<scope['toExclusive']:
            raise ValueError('Monetary explicit posting coverage incomplete')
        _range(rule['sourceFrom'],rule['sourceToExclusive'])
        dates=rule['sourceDueDates']
        if dates!=sorted(set(dates)) or any(not rule['sourceFrom']<=d<rule['sourceToExclusive'] for d in dates):
            raise ValueError('Monetary source due dates invalid')
        expected=[d for d in dates if scope['from']<=d<scope['toExclusive']]
    if inventory['dueDates']!=expected: raise ValueError('Monetary due posting inventory incomplete')
    return expected


def _policy(subject):
    policy,scope=subject['policy'],subject['scope']
    due=posting_dates(policy,scope)
    previous=scope['from']; identifiers=set(); dates=[]; common=None
    for interval in policy['intervals']:
        _range(interval['from'],interval['toExclusive'])
        if interval['id'] in identifiers or interval['from']!=previous or interval['toExclusive']>scope['toExclusive']:
            raise ValueError('Monetary policy intervals overlap or gap')
        identifiers.add(interval['id']);previous=interval['toExclusive']
        interest=interval['interest']; dates.extend(interest['postingDates'])
        if interest['postingDates']!=[d for d in due if interval['from']<=d<interval['toExclusive']]:
            raise ValueError('Monetary interval posting dates differ')
        settings={k:v for k,v in interest.items() if k not in {'postingDates','evidenceIds'}}
        if common is not None and common!=settings: raise ValueError('Monetary global interest policy changes unsupported')
        common=settings
        upper=Decimal(0); tiers=set()
        for index,tier in enumerate(interval['tiers']):
            if tier['id'] in tiers: raise ValueError('Monetary duplicate tier')
            tiers.add(tier['id']); boundary=tier['upperInclusive']
            if boundary is None:
                if index!=len(interval['tiers'])-1: raise ValueError('Monetary unlimited tier must be last')
            elif Decimal(boundary)<=upper or Decimal(boundary)!=Decimal(boundary).quantize(Decimal('.01')):
                raise ValueError('Monetary tier edge not ascending cents')
            else: upper=Decimal(boundary)
        if interval['tiers'][-1]['upperInclusive'] is not None: raise ValueError('Monetary final unlimited tier required')
    if previous!=scope['toExclusive'] or dates!=due: raise ValueError('Monetary policy coverage incomplete')
    categories=[x['categoryId'] for x in policy['fees']['inventory']]
    if len(categories)!=len(set(categories)): raise ValueError('Monetary duplicate fee category')


def validate_subject(subject):
    schema_validate(subject,'subject')
    if subject['id']!=identity(subject) or subject['scopeId']!=digest(['monetary-scope-v3',subject['capability'],subject['scope']]):
        raise ValueError('Monetary subject/scope identity differs')
    if subject['scope']['productKey']!=subject['routing']['productKey']:
        raise ValueError('Monetary routing product differs')
    _range(subject['scope']['from'],subject['scope']['toExclusive'])
    known=_evidence(subject);_inputs(subject['policy'],known);_policy(subject)
    from .executable_v3_graph import validate_graph
    validate_graph(subject)


def validate_asset(asset,product_key=None):
    schema_validate(asset,'asset',512*1024)
    if asset['identitySha256']!=identity(asset,'identitySha256') or (product_key is not None and asset['productKey']!=product_key):
        raise ValueError('Monetary asset identity differs')
    subjects,scopes=set(),set()
    for item in asset['subjects']:
        subject,approval=item['subject'],item['approval'];validate_subject(subject)
        validate_review_time(approval['reviewedAt'])
        if subject['id'] in subjects or subject['scopeId'] in scopes: raise ValueError('Monetary duplicate subject/scope')
        subjects.add(subject['id']);scopes.add(subject['scopeId'])
        if (subject['routing']!=asset['routing'] or subject['capability']!=asset['capability']
            or subject['scope']['productKey']!=asset['productKey'] or approval['subjectId']!=subject['id']
            or approval['authorityGraphSha256']!=subject['authorityGraph']['identitySha256']):
            raise ValueError('Monetary asset association differs')
