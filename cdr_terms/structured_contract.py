"""Closed, bounded private structure protocol; candidate text is not authority."""
from __future__ import annotations

import json
import re
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from jsonschema import Draft202012Validator, ValidationError

from .identity import canonical_json, byte_digest, require_sha

CONTRACT = 'structured-review-v1'
EXTRACTOR = 'reviewed-structure-v1'
MAX_JSON = 2 * 1024**2
CACHE_BYTES = 32 * 1024**2
CACHE_ENTRIES = 512
SCHEMA = Path(__file__).resolve().parents[1] / 'contracts/product_terms/structured-review-v1.json'
_READS = ContextVar('structured_immutable_reads', default=None)


def evidence_reads(function):
    """One bounded operation's immutable bytes only; never cache review decisions."""
    @wraps(function)
    def checked(store, *args, **kwargs):
        existing = _READS.get()
        if existing is not None and existing['store'] is store:
            return function(store, *args, **kwargs)
        token = _READS.set({'store': store, 'blobs': {}, 'bytes': 0})
        try:
            return function(store, *args, **kwargs)
        finally:
            _READS.reset(token)
    return checked


def bounded(value):
    pending, nodes, characters = [(value, 0)], 0, 0
    while pending:
        item, depth = pending.pop(); nodes += 1
        if depth > 20 or nodes > 30000:
            raise ValueError('Structured protocol structural limit')
        if isinstance(item, dict):
            if any(not isinstance(k, str) for k in item): raise ValueError('Structured object keys')
            characters += sum(len(k) for k in item)
            pending.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list): pending.extend((v, depth + 1) for v in item)
        elif isinstance(item, str): characters += len(item)
        elif item is not None and type(item) not in (int, bool): raise ValueError('Structured exact value required')
        if characters > MAX_JSON: raise ValueError('Structured protocol byte limit')
    raw = canonical_json(value).encode('utf-8')
    if len(raw) > MAX_JSON: raise ValueError('Structured protocol byte limit')
    return raw


def read(store, sha, maximum=MAX_JSON):
    # Check before EvidenceStore.read_blob allocates/verifies the retained bytes.
    require_sha(sha)
    cache = _READS.get()
    if cache is not None and cache['store'] is not store: cache = None
    if cache is not None and sha in cache['blobs']:
        raw = cache['blobs'].pop(sha)
        cache['blobs'][sha] = raw
        if len(raw) > maximum: raise ValueError('Structured retained blob limit')
        return raw
    path = Path(store.root) / 'blobs' / sha[:2] / sha
    size = path.stat().st_size
    if size > maximum: raise ValueError('Structured retained blob limit')
    if cache is not None:
        while cache['blobs'] and (len(cache['blobs']) >= CACHE_ENTRIES or cache['bytes'] + size > CACHE_BYTES):
            oldest = next(iter(cache['blobs']))
            cache['bytes'] -= len(cache['blobs'].pop(oldest))
    raw = store.read_blob(sha)
    if len(raw) > maximum: raise ValueError('Structured retained blob limit')
    if byte_digest(raw) != sha: raise ValueError('Structured retained blob identity differs')
    if cache is not None and len(raw) <= CACHE_BYTES:
        cache['blobs'][sha] = raw
        cache['bytes'] += len(raw)
    return raw


def load(store, sha):
    raw = read(store, sha)
    try: value = json.loads(raw)
    except (ValueError, RecursionError) as error: raise ValueError('Structured JSON invalid') from error
    bounded(value)
    return value


def keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected.split()):
        raise ValueError('Structured closed fields differ')


def actor(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 180:
        raise ValueError('Structured actor identity required')
    return value.strip()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.:-]{0,127}', value):
        raise ValueError('Structured region identity invalid')
    return value


def strings(values, maximum=128):
    if (not isinstance(values, list) or len(values) > maximum
            or any(not isinstance(x, str) or not x.strip() or len(x) > 2000 for x in values)):
        raise ValueError('Structured unresolved inventory invalid')


def pages(value, selected):
    if not isinstance(value, list) or not value or len(value) > 8:
        raise ValueError('Structured page inventory invalid')
    seen, total = set(), 0
    for page in value:
        keys(page, 'page text')
        number, text = page['page'], page['text']
        if type(number) is not int or number not in selected or number in seen:
            raise ValueError('Structured page binding invalid')
        if not isinstance(text, str) or len(text) > 100000:
            raise ValueError('Structured page text limit')
        seen.add(number); total += len(text)
    if total > 500000 or [p['page'] for p in value] != selected:
        raise ValueError('Structured page inventory differs')


def proposal(value, selected):
    validate('proposal', value)
    keys(value, 'schema_version candidate_id pages regions tables links unresolved')
    if value['schema_version'] != 1 or type(value['schema_version']) is not int:
        raise ValueError('Unsupported structured protocol')
    pages(value['pages'], selected); strings(value['unresolved'])
    text = {p['page']: p['text'] for p in value['pages']}
    if not isinstance(value['regions'], list) or not 1 <= len(value['regions']) <= 1024:
        raise ValueError('Structured region count')
    regions = {}
    for r in value['regions']:
        keys(r, 'id page start end role')
        rid = identifier(r['id'])
        if rid in regions or type(r['page']) is not int or r['page'] not in text:
            raise ValueError('Structured region page or duplicate identity')
        if type(r['start']) is not int or type(r['end']) is not int or not 0 <= r['start'] < r['end'] <= len(text[r['page']]):
            raise ValueError('Structured region outside reviewed transcription')
        if r['role'] not in ('clause', 'cell', 'header', 'unit', 'marker', 'footnote', 'definition'):
            raise ValueError('Unsupported structured region role')
        regions[rid] = r
    ordered = sorted(regions.values(), key=lambda r: (r['page'], r['start'], r['end']))
    for left, right in zip(ordered, ordered[1:]):
        if left['page'] == right['page'] and left['end'] > right['start']:
            raise ValueError('Overlapping structured regions require explicit separation')
    if not isinstance(value['tables'], list) or len(value['tables']) > 128:
        raise ValueError('Structured table count')
    if sum(len(t['cells']) for t in value['tables']) > 1024:
        raise ValueError('Structured aggregate cell count')
    used, table_ids = set(), set()
    for table in value['tables']:
        keys(table, 'id cells headers units continuation')
        tid = identifier(table['id'])
        if tid in table_ids: raise ValueError('Duplicate structured table')
        table_ids.add(tid)
        for field, roles in [('headers', {'header'}), ('units', {'unit'})]:
            refs = table[field]
            if not isinstance(refs, list) or not refs or len(refs) > 1024 or len(set(refs)) != len(refs):
                raise ValueError('Structured table references missing')
            for ref in refs:
                if not isinstance(ref, str) or ref not in regions or regions[ref]['role'] not in roles:
                    raise ValueError('Structured table orphan or role mismatch')
        occupied = set()
        for cell in table['cells']:
            ref = cell['region']
            if ref not in regions or regions[ref]['role'] != 'cell' or ref in used:
                raise ValueError('Cell assigned to multiple tables or orphan')
            used.add(ref)
            if not set(cell['headers']) <= set(table['headers']) or not set(cell['units']) <= set(table['units']):
                raise ValueError('Cell header or unit association missing')
            for row in range(cell['row'], cell['row'] + cell['rowSpan']):
                for column in range(cell['column'], cell['column'] + cell['columnSpan']):
                    if (row, column) in occupied: raise ValueError('Overlapping table cells')
                    occupied.add((row, column))
        if table['continuation'] is not None: identifier(table['continuation'])
    for table in value['tables']:
        if table['continuation'] is not None and (table['continuation'] not in table_ids or table['continuation'] == table['id']):
            raise ValueError('Structured continuation orphan')
    if used != {k for k, r in regions.items() if r['role'] == 'cell'}:
        raise ValueError('Structured cell missing table association')
    if not isinstance(value['links'], list) or len(value['links']) > 256:
        raise ValueError('Structured link count')
    seen = set()
    for link in value['links']:
        keys(link, 'id marker note targets relation')
        lid = identifier(link['id'])
        if lid in seen: raise ValueError('Duplicate structured link')
        seen.add(lid)
        if link['relation'] not in ('qualifies', 'exception', 'definition', 'precedence', 'cross_reference'):
            raise ValueError('Unsupported structured relation')
        if link['marker'] not in regions or regions[link['marker']]['role'] != 'marker' or link['note'] not in regions or regions[link['note']]['role'] not in ('footnote', 'definition'):
            raise ValueError('Structured footnote orphan')
        if not isinstance(link['targets'], list) or not link['targets'] or len(link['targets']) > 128 or len(set(link['targets'])) != len(link['targets']):
            raise ValueError('Structured link targets invalid')
        if any(t not in regions or regions[t]['role'] not in ('cell', 'clause', 'header') for t in link['targets']):
            raise ValueError('Structured target orphan')
    return regions


def schema_sha():
    return byte_digest(SCHEMA.read_bytes())


def validate(kind, value):
    bounded(value)
    schema = json.loads(SCHEMA.read_bytes())
    try:
        Draft202012Validator({'$defs': schema['$defs'], '$ref': '#/$defs/' + kind}).validate(value)
    except ValidationError as error:
        raise ValueError('Structured schema invalid: ' + error.message) from error
