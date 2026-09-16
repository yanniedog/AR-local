"""Closed activity Savings wire. Validation is not source approval."""
import json
from fractions import Fraction
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from .identity import digest, byte_digest
from .executable_contract import _bounded
from .executable_v2_contract import _offline
from .executable_v3_contract import identity, _range, _evidence, _inputs, _policy

ROOT = Path(__file__).resolve().parents[1] / 'contracts/product_terms/savings-activity-v4'
INVENTORY_SHA = '33d79149edc454308ab77b295d86bb39708995b0ea598d229d092073833894a7'
CAPABILITY = 'savings_activity_calculation'
TUPLE = ('aud_savings_activity_period_v1', 'aud-savings-activity-v1', 'product-terms-engine-v9')


def validate_tuple(subject):
    if (subject.get('schemaVersion') != 4 or subject.get('capability') != CAPABILITY
        or tuple(subject.get(k) for k in ('kind', 'adapterVersion', 'evaluatorVersion')) != TUPLE):
        raise ValueError('Activity monetary capability tuple differs')


def schema_validate(value, name, limit=256 * 1024):
    _bounded(value, limit, ascii_keys=False)
    raw_inventory = (ROOT / 'integration-baseline.json').read_bytes()
    if byte_digest(raw_inventory) != INVENTORY_SHA:
        raise ValueError('Activity integration inventory identity differs')
    inventory = json.loads(raw_inventory)['files']
    registry = Registry(retrieve=_offline)
    schemas = {}
    for filename, expected in inventory.items():
        raw = (ROOT / 'schemas' / filename).read_bytes()
        if byte_digest(raw) != expected:
            raise ValueError('Activity integration schema identity differs')
        schema = json.loads(raw)
        resource = Resource.from_contents(schema)
        registry = registry.with_resource(filename, resource).with_resource(schema['$id'], resource)
        schemas[filename] = schema
    Draft202012Validator(schemas[name + '.schema.json'], registry=registry,
                         format_checker=FormatChecker()).validate(value)


def _bonus(policy, scope):
    bonus = policy['bonus']; assessment = bonus['assessment']
    start, end = _range(assessment['from'], assessment['toExclusive'])
    _, finish = _range(scope['from'], scope['toExclusive'])
    if end.isoformat() > scope['from'] or (finish - start).days > 366:
        raise ValueError('Activity preceding window or combined horizon differs')
    if (assessment['appliesFrom'], assessment['appliesToExclusive']) != (scope['from'], scope['toExclusive']):
        raise ValueError('Activity application window differs')
    metrics = assessment['metrics']; fields = [m['field'] for m in metrics]
    if len(set(fields)) != len(fields) or len({m['id'] for m in metrics}) != len(metrics):
        raise ValueError('Activity duplicate metric')
    for metric in metrics:
        if set(metric['includedClassifications']) & set(metric['excludedClassifications']):
            raise ValueError('Activity classification overlap')
    rule = assessment['rule']
    leaves = rule['rules'] if rule['op'] in ('and', 'or') else [rule]
    if sorted(x['field'] for x in leaves) != sorted(fields):
        raise ValueError('Activity metric rule inventory differs')
    seen = set(); previous = Fraction(0)
    for index, tier in enumerate(bonus['tiers']):
        edge = tier['upperInclusive']
        if tier['id'] in seen:
            raise ValueError('Activity duplicate bonus tier')
        seen.add(tier['id'])
        if edge is None:
            if index != len(bonus['tiers']) - 1:
                raise ValueError('Activity unlimited bonus tier must be last')
        else:
            value = Fraction(edge)
            if value <= previous or (value * 100).denominator != 1:
                raise ValueError('Activity bonus tier edge not ascending cents')
            previous = value
    if bonus['tiers'][-1]['upperInclusive'] is not None:
        raise ValueError('Activity final unlimited bonus tier required')


def validate_subject(subject):
    validate_tuple(subject)
    schema_validate(subject, 'subject')
    if (subject['id'] != identity(subject)
        or subject['scopeId'] != digest(['monetary-scope-v4', CAPABILITY, subject['scope']])):
        raise ValueError('Activity subject/scope identity differs')
    if subject['scope']['productKey'] != subject['routing']['productKey']:
        raise ValueError('Activity routing product differs')
    _range(subject['scope']['from'], subject['scope']['toExclusive'])
    known = _evidence(subject)
    _inputs(subject['policy'], known)
    _policy(subject)
    _bonus(subject['policy'], subject['scope'])
    from .executable_v4_graph import validate_graph
    validate_graph(subject)


def validate_asset(asset,product_key=None):
    from .executable_v2_contract import validate_review_time
    validate_schema=schema_validate
    validate_schema(asset,'asset',512*1024)
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
