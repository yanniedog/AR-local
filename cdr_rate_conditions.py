"""Raw source disclosures with per-document rate/tier occurrence identities."""
from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

MAX_ENTRIES = 1024
MAX_TEXT_BYTES = 16384
MAX_ENVELOPE_BYTES = 1024 * 1024
SCHEMA = Path(__file__).parent / 'contracts/product_terms/rate-conditions-v1.schema.json'
_RATE = re.compile(r'^(/data)?/(depositRates|lendingRates)/(0|[1-9][0-9]*)$')
_TIER = re.compile(r'^/tiers/(0|[1-9][0-9]*)$')
_SUFFIX = re.compile(r'^(?:/applicabilityConditions(?:/(0|[1-9][0-9]*))?)?/additionalInfo$')


def encoded(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def occurrence_id(source_sha: str, pointer: str) -> str:
    return hashlib.sha256(encoded([source_sha, pointer])).hexdigest()


def source_rates(record: Mapping[str, Any], dataset: str):
    """Keep as_items' filtered ordinal and the original unfiltered pointer index."""
    wanted = {'Mortgage': {'lending'}, 'Savings': {'deposit'}, 'TD': {'deposit'}}.get(
        dataset, {'deposit', 'lending'})
    for family, key in (('deposit', 'depositRates'), ('lending', 'lendingRates')):
        items = record.get(key)
        if family not in wanted or not isinstance(items, list):
            continue
        ordinal = 0
        for source_index, item in enumerate(items):
            if isinstance(item, dict):
                ordinal += 1  # An empty object still occupies an exported rate index.
                yield family, key, source_index, ordinal, item


def _information(record: Mapping[str, Any], pointer: str):
    text = record.get('additionalInfo')
    if isinstance(text, str) and text.strip():
        yield pointer + '/additionalInfo', text
    conditions = record.get('applicabilityConditions')
    if isinstance(conditions, dict):
        conditions = [(pointer + '/applicabilityConditions', conditions)]
    elif isinstance(conditions, list):
        conditions = [(pointer + f'/applicabilityConditions/{index}', condition)
                      for index, condition in enumerate(conditions) if isinstance(condition, dict)]
    else:
        conditions = []
    for source_pointer, condition in conditions:
        text = condition.get('additionalInfo')
        if isinstance(text, str) and text.strip():
            yield source_pointer + '/additionalInfo', text


def extract_rate_conditions(source: bytes, dataset: str) -> dict | None:
    """Capture before cleaning; bounds reject packaging, never truncate source exports."""
    payload = json.loads(source)
    wrapped = isinstance(payload, dict) and isinstance(payload.get('data'), dict)
    record = payload['data'] if wrapped else payload
    if not isinstance(record, dict):
        return None
    root = '/data' if wrapped else ''
    source_sha = hashlib.sha256(source).hexdigest()
    entries = []
    for family, key, index, ordinal, rate in source_rates(record, dataset):
        rate_pointer = f'{root}/{key}/{index}'
        scopes = [(rate_pointer, rate)]
        tiers = rate.get('tiers')
        if isinstance(tiers, list):
            scopes.extend((rate_pointer + f'/tiers/{i}', tier)
                          for i, tier in enumerate(tiers) if isinstance(tier, dict))
        for scope, item in scopes:
            for pointer, text in _information(item, scope):
                entry = {'id': occurrence_id(source_sha, pointer), 'rateFamily': family,
                         'rateIndex': ordinal, 'rateSourcePointer': rate_pointer,
                         'sourcePointer': pointer, 'text': text}
                if scope != rate_pointer:
                    entry['tierSourcePointer'] = scope
                entries.append(entry)
    return {'schemaVersion': 1, 'sourceSha256': source_sha, 'entries': entries} if entries else None


@lru_cache(maxsize=1)
def _validator():
    return Draft202012Validator(json.loads(SCHEMA.read_bytes()))


def validate_rate_conditions(value: Any) -> None:
    _validator().validate(value)
    if len(encoded(value)) > MAX_ENVELOPE_BYTES:
        raise ValueError('rate_conditions_envelope_byte_bound')
    seen, by_rate, by_pointer, roots = set(), {}, {}, set()
    for entry in value['entries']:
        pointer, rate_pointer = entry['sourcePointer'], entry['rateSourcePointer']
        if entry['id'] != occurrence_id(value['sourceSha256'], pointer) or pointer in seen:
            raise ValueError('rate_conditions_occurrence_identity_mismatch')
        seen.add(pointer)
        match = _RATE.fullmatch(rate_pointer)
        if not match or match[2] != ('depositRates' if entry['rateFamily'] == 'deposit' else 'lendingRates'):
            raise ValueError('rate_conditions_family_pointer_mismatch')
        roots.add(match[1] or '')
        rate_key = (entry['rateFamily'], entry['rateIndex'])
        if by_rate.setdefault(rate_key, rate_pointer) != rate_pointer or by_pointer.setdefault(rate_pointer, rate_key) != rate_key:
            raise ValueError('rate_conditions_ordinal_pointer_mismatch')
        scope = entry.get('tierSourcePointer', rate_pointer)
        if 'tierSourcePointer' in entry and (not scope.startswith(rate_pointer) or not _TIER.fullmatch(scope[len(rate_pointer):])):
            raise ValueError('rate_conditions_tier_pointer_mismatch')
        if not pointer.startswith(scope) or not _SUFFIX.fullmatch(pointer[len(scope):]):
            raise ValueError('rate_conditions_source_pointer_mismatch')
        if not entry['text'].strip() or len(entry['text'].encode('utf-8')) > MAX_TEXT_BYTES:
            raise ValueError('rate_conditions_text_byte_bound')
    if len(roots) != 1:
        raise ValueError('rate_conditions_mixed_source_roots')
