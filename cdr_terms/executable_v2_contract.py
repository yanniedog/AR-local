"""Frozen capability-specific wire with bounded, offline semantic validation."""
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource

from .executable_contract import _bounded, _rules, MAX_TEMPLATE_BYTES, MAX_ASSET_BYTES
from .identity import digest, byte_digest

ROOT = Path(__file__).resolve().parents[1] / 'contracts/product_terms/drafts/eligibility-v2'
CHECKS = ('source_alignment', 'scope_coverage', 'input_bindings', 'rule_semantics', 'variant_binding')
ROLES = {'scenario_amount': ('decimal', 'AUD'), 'assessment_date': ('date', None),
         'scenario_security_value': ('decimal', 'AUD'), 'scenario_purpose': ('text', None),
         'scenario_security_type': ('text', None), 'scenario_ownership': ('text', None)}


def _offline(uri):
    raise NoSuchResource(ref=uri)


def schema_validate(value, name, limit=MAX_TEMPLATE_BYTES):
    _bounded(value, limit, ascii_keys=False)
    schemas = {p.name: json.loads(p.read_bytes()) for p in ROOT.glob('*.schema.json')}
    registry = Registry(retrieve=_offline)
    for filename, schema in schemas.items():
        resource = Resource.from_contents(schema)
        registry = registry.with_resource(filename, resource).with_resource(schema['$id'], resource)
    Draft202012Validator(schemas[name], registry=registry, format_checker=FormatChecker()).validate(value)


def scope_identity(value):
    return digest(['executable-scope-v2', value['capability'], value['scope']])


def validate_review_time(value):
    match = re.fullmatch(r'([0-9]{4}-[0-9]{2}-[0-9]{2})[Tt]([01][0-9]|2[0-3]):([0-5][0-9]):([0-5][0-9])(?:\.[0-9]+)?(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])', value)
    if match is None or not '1900-01-01' <= match[1] <= '2200-12-31':
        raise ValueError('Executable v2 review timestamp invalid')
    date.fromisoformat(match[1])


def validate_subject(value):
    schema_validate(value, 'executable-subject-v2.schema.json')
    if value['id'] != digest({k: v for k, v in value.items() if k != 'id'}) or value['scopeId'] != scope_identity(value):
        raise ValueError('Executable v2 subject/scope identity mismatch')
    scope, source = value['scope'], value['source']
    if scope['effectiveFrom'] >= scope['effectiveToExclusive']:
        raise ValueError('Executable v2 approval coverage inverted')
    indexes = scope['rateIndexes']
    rows = source['rateRows']
    if (indexes != sorted(set(indexes)) or indexes != sorted(r['rateIndex'] for r in rows)
            or len({r['coreRowIndex'] for r in rows}) != len(rows)):
        raise ValueError('Executable v2 variant inventory mismatch')
    known = set()
    for item in value['evidence']:
        url = item['sourceUrl']
        parsed = urlsplit(url)
        if (url != url.strip() or any(ord(c) <= 32 for c in url) or '\\' in url
                or parsed.scheme != 'https' or not parsed.hostname
                or parsed.username is not None or parsed.password is not None):
            raise ValueError('Executable v2 source URL invalid')
        parsed.port  # Reject malformed or out-of-range ports.
        if item['id'] != item['clauseId'] or item['id'] in known or byte_digest(item['quote'].encode('utf8')) != item['quoteSha256']:
            raise ValueError('Executable v2 clause identity mismatch')
        known.add(item['id'])
    if sorted({e['documentVersionId'] for e in value['evidence']}) != source['documentVersionIds']:
        raise ValueError('Executable v2 document inventory mismatch')
    if source['termRevisionIds'] != sorted(set(source['termRevisionIds'])):
        raise ValueError('Executable v2 revision inventory mismatch')
    if any(not set(refs) <= known for refs in value['fieldClauseIds'].values()):
        raise ValueError('Executable v2 field clause missing')
    definitions, bindings = {}, set()
    for item in value['inputDefinitions']:
        key, binding = item['key'], item['binding']
        if not item['label'].strip() or (isinstance(item['unit'], str) and not item['unit'].strip()):
            raise ValueError('Executable v2 input text is blank')
        if key in definitions or not set(item['clauseIds']) <= known:
            raise ValueError('Executable v2 input identity/source mismatch')
        definitions[key] = item
        if binding != 'customer_fact':
            if binding in bindings or (item['type'], item['unit']) != ROLES[binding]:
                raise ValueError('Executable v2 scenario role mismatch')
            bindings.add(binding)
        elif ((item['type'] == 'decimal' and not item['unit'])
              or (item['type'] != 'decimal' and item['unit'] is not None)):
            raise ValueError('Executable v2 input unit mismatch')
    if 'assessment_date' not in bindings:
        raise ValueError('Executable v2 assessment date binding required')
    _rules(value['eligibility'], definitions, known, set())
    pending, used = [value['eligibility']], set()
    while pending:
        rule = pending.pop()
        if rule['op'] in {'and', 'or'}:
            pending.extend(rule['rules'])
        elif rule['op'] == 'not':
            pending.append(rule['rule'])
        else:
            used.add(rule['field'])
            expected = rule['expected']
            if expected['type'] == 'date' and not '1900-01-01' <= expected['value'] <= '2200-12-31':
                raise ValueError('Executable v2 rule date outside evaluator bounds')
    if any(k not in used and d['binding'] != 'assessment_date' for k, d in definitions.items()):
        raise ValueError('Executable v2 unused input definition')


def validate_asset(value, *, product_key=None):
    schema_validate(value, 'executable-asset-v2.schema.json', MAX_ASSET_BYTES)
    if value['identitySha256'] != digest({k: v for k, v in value.items() if k != 'identitySha256'}):
        raise ValueError('Executable v2 asset identity mismatch')
    if product_key is not None and product_key != value['productKey']:
        raise ValueError('Executable v2 map product mismatch')
    subjects, scopes = set(), set()
    for item in value['subjects']:
        subject, approval = item['subject'], item['approval']
        validate_subject(subject)
        validate_review_time(approval['reviewedAt'])
        if subject['id'] in subjects or subject['scopeId'] in scopes:
            raise ValueError('Executable v2 duplicate subject/scope')
        subjects.add(subject['id']); scopes.add(subject['scopeId'])
        if approval['subjectId'] != subject['id'] or approval['capability'] != subject['capability']:
            raise ValueError('Executable v2 approval subject mismatch')
        if subject['scope']['productKey'] != value['productKey'] or any(subject['source'][inner] != value[outer] for inner, outer in (
                ('observationId', 'sourceObservationId'), ('generationId', 'sourceGenerationId'), ('runDate', 'runDate'),
                ('coreAssetSha256', 'coreAssetSha256'), ('detailsAssetSha256', 'detailsAssetSha256'))):
            raise ValueError('Executable v2 asset source mismatch')
