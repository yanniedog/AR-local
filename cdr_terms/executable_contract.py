"""Closed source-neutral TD templates; no customer scenarios or inferred approval."""
from __future__ import annotations

import json
import re
from decimal import Decimal
from datetime import date
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from .identity import byte_digest, canonical_json, digest, exact_value

SCHEMAS = Path(__file__).resolve().parents[1] / 'contracts/product_terms'
MAX_TEMPLATE_BYTES = 256 * 1024
MAX_ASSET_BYTES = 512 * 1024
REVIEW_CHECKS = frozenset(('source_alignment', 'applicability', 'material_terms', 'fee_coverage',
                         'rate_schedule', 'calendar_rounding', 'input_bindings', 'variant_binding'))


def _schema(name):
    return json.loads((SCHEMAS / name).read_bytes())


def _bounded(value, limit):
    pending, nodes = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > 40 or nodes > 20000:
            raise ValueError('Executable structure depth/node bound exceeded')
        if isinstance(item, dict):
            if any(type(k) is not str or not k.isascii() for k in item):
                raise ValueError('Executable schema keys must be ASCII strings')
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif type(item) not in (str, int, bool, type(None)):
            raise ValueError('Executable values require exact JSON primitives')
        elif isinstance(item, str) and len(item) > limit:
            raise ValueError('Executable text byte bound exceeded')
    exact_value(value)
    if len(canonical_json(value).encode('utf-8')) > limit:
        raise ValueError('Executable evidence byte bound exceeded')


def _inputs(value, known):
    definitions, bindings = {}, set()
    for item in value['inputDefinitions']:
        key, binding = item['key'], item['binding']
        if key in definitions or key in {'constructor', 'prototype', '__proto__'}:
            raise ValueError('Duplicate or unsafe executable input key')
        definitions[key] = item
        if not set(item['clauseIds']) <= known:
            raise ValueError('Input has no source clause')
        if binding != 'customer_fact':
            if binding in bindings:
                raise ValueError('Duplicate scenario input binding')
            bindings.add(binding)
            expected = ('decimal', 'AUD') if binding == 'deposit_principal' else ('date', None)
            if (item['type'], item['unit']) != expected:
                raise ValueError('Scenario input binding type mismatch')
        elif ((item['type'] == 'decimal' and not item['unit'])
              or (item['type'] != 'decimal' and item['unit'] is not None)):
            raise ValueError('Only decimal input definitions carry units')
    if bindings != {'deposit_principal', 'funded_date', 'maturity_date'}:
        raise ValueError('Required scenario input bindings missing')
    return definitions


def _rules(rule, definitions, known, seen, depth=0):
    if depth > 16 or len(seen) >= 512 or rule['id'] in seen:
        raise ValueError('Eligibility rule identity/depth bound exceeded')
    seen.add(rule['id'])
    if rule['op'] in {'and', 'or'}:
        for child in rule['rules']:
            _rules(child, definitions, known, seen, depth + 1)
    elif rule['op'] == 'not':
        _rules(rule['rule'], definitions, known, seen, depth + 1)
    else:
        definition = definitions.get(rule['field'])
        fact = rule['expected']
        if (not definition or definition['type'] != fact['type']
                or definition['unit'] != fact.get('unit') or not set(rule['evidenceIds']) <= known):
            raise ValueError('Eligibility input type/unit/source mismatch')
        if fact['type'] == 'date':
            if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', fact['value']):
                raise ValueError('Eligibility date must use exact ISO calendar syntax')
            date.fromisoformat(fact['value'])
        if fact['type'] in {'boolean', 'text'} and rule['comparison'] not in {'eq', 'ne'}:
            raise ValueError('Ordered comparison requires date or decimal')


def validate_template(value):
    _bounded(value, MAX_TEMPLATE_BYTES)
    Draft202012Validator(_schema('executable-template-v1.schema.json'), format_checker=FormatChecker()).validate(value)
    if value['id'] != digest({k: v for k, v in value.items() if k != 'id'}):
        raise ValueError('Executable template identity mismatch')
    if value['effectiveFrom'] >= value['effectiveToExclusive']:
        raise ValueError('Executable effective interval inverted')
    lower, upper = (value['principalBounds'][k] for k in ('minimum', 'maximum'))
    if 'value' in lower and 'value' in upper:
        left, right = Decimal(lower['value']), Decimal(upper['value'])
        if left > right or (left == right and not (lower['inclusive'] and upper['inclusive'])):
            raise ValueError('Executable principal bounds are empty or inverted')
    known = set()
    for evidence in value['evidence']:
        if (evidence['id'] != evidence['clauseId'] or evidence['id'] in known
                or byte_digest(evidence['quote'].encode()) != evidence['quoteSha256']):
            raise ValueError('Executable source occurrence identity mismatch')
        known.add(evidence['id'])
    if sorted({x['documentVersionId'] for x in value['evidence']}) != value['documentVersionIds']:
        raise ValueError('Executable document inventory mismatch')
    if sorted(set(value['termRevisionIds'])) != value['termRevisionIds']:
        raise ValueError('Executable revision inventory is not canonical')
    for refs in value['fieldClauseIds'].values():
        if not set(refs) <= known:
            raise ValueError('Executable field has no source clause')
    _rules(value['eligibility'], _inputs(value, known), known, set())


def validate_asset(value):
    _bounded(value, MAX_ASSET_BYTES)
    schema = _schema('executable-asset-v1.schema.json')
    schema['properties']['templates']['items']['properties']['template'] = {}
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    if value['identitySha256'] != digest({k: v for k, v in value.items() if k != 'identitySha256'}):
        raise ValueError('Executable asset identity mismatch')
    seen = set()
    for item in value['templates']:
        template = item['template']
        validate_template(template)
        if item['approval']['templateId'] != template['id']:
            raise ValueError('Executable approval template mismatch')
        slot = (template['cohortKey'], template['selectedRate']['rateIndex'])
        if slot in seen:
            raise ValueError('Duplicate executable variant')
        seen.add(slot)
        if any(template[k] != value[k] for k in ('productKey', 'runDate', 'sourceGenerationId')) or template['selectedRate']['coreAssetSha256'] != value['coreAssetSha256']:
            raise ValueError('Executable asset source scope mismatch')
