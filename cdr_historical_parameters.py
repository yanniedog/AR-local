"""Lossless observed detail-field changes; no legal validity or gap filling."""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from cdr_report_io import MAX_ASSET_BYTES, decode_json


def flatten(value, pointer=''):
    if isinstance(value, dict) and value:
        for key, item in value.items():
            yield from flatten(item, pointer + '/' + key.replace('~', '~0').replace('/', '~1'))
    elif isinstance(value, list) and value:
        for index, item in enumerate(value):
            yield from flatten(item, pointer + '/' + str(index))
    else:
        yield pointer, value


def fields(record):
    return dict(flatten(record))


def changed_parameters(before, after, *, baseline, before_present=True, after_present=True):
    """Explicit presence avoids confusing null/false/zero with an absent field."""
    previous = {} if baseline or not before_present else fields(before)
    current = fields(after) if after_present else {}
    for pointer in sorted(set(previous) | set(current)):
        old, new = previous.get(pointer), current.get(pointer)
        was, now = pointer in previous, pointer in current
        if was == now and type(old) is type(new) and old == new:
            continue
        yield {'source_pointer': pointer, 'before_state': 'not_compared' if baseline else ('reported' if was else 'unreported'),
               'before_json': json.dumps(old, ensure_ascii=False, separators=(',', ':')) if was else '',
               'after_state': 'reported' if now else 'unreported',
               'after_json': json.dumps(new, ensure_ascii=False, separators=(',', ':')) if now else '',
               'event': 'baseline_observation' if baseline else 'observed_field_change'}


def rows(root, summary):
    previous, previous_date = {}, None
    for audit in summary['results']:
        if audit['status'] != 'PASS' or not audit.get('details_sha256'):
            previous, previous_date = {}, None
            continue
        observed = date.fromisoformat(audit['run_date'])
        path = root / audit['run_date'] / 'details.json.gz'
        if path.stat().st_size > MAX_ASSET_BYTES:
            raise ValueError('dated detail input exceeds bound')
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != audit['details_sha256']:
            raise ValueError('dated detail bytes differ from audit')
        payload = decode_json(body, compressed=True)
        if payload['run_date'] != audit['run_date']:
            raise ValueError('dated detail body differs from audit')
        current = payload['products']
        baseline = previous_date is None or observed != previous_date + timedelta(days=1)
        if baseline:
            previous = {}
        for key in sorted(set(previous) | set(current)):
            old, new = previous.get(key, {}), current.get(key, {})
            for change in changed_parameters(old, new, baseline=baseline or key not in previous,
                                              before_present=key in previous, after_present=key in current):
                yield {'observation_date': audit['run_date'], 'product_key': key,
                       'provider': key.split('|', 1)[0],
                       'detail_product_present': key in current, **change,
                       'details_sha256': audit['details_sha256'],
                       'legal_effective_date': 'unknown'}
        previous, previous_date = current, observed
