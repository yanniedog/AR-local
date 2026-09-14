"""Bounded, exact JSON primitives for private historical fee candidates only."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import stat
from decimal import Decimal
from pathlib import Path

JSON_LIMIT = 96 * 1024**2


def sha(body: bytes) -> str:
    from cdr_historical_fee_plan_budget import account_exact
    account_exact('checksum', len(body))
    return hashlib.sha256(body).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_json_key')
        result[key] = value
    return result


def decode(body: bytes, *, compressed=False, limit=JSON_LIMIT):
    if compressed:
        from cdr_historical_fee_plan_budget import read_exact_work
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
            body = read_exact_work(stream, limit + 1)
    if len(body) > limit:
        raise ValueError('json_byte_bound_exceeded')
    return json.loads(body.decode('utf-8', errors='strict'), object_pairs_hook=_pairs,
                      parse_float=Decimal,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite_json')))


def encode(value) -> bytes:
    """Keep JSON numbers numeric without binary float or decimal context rounding."""
    def emit(item):
        if item is None:
            return 'null'
        if type(item) is bool:
            return 'true' if item else 'false'
        if type(item) is int:
            return str(item)
        if isinstance(item, Decimal):
            if not item.is_finite():
                raise ValueError('nonfinite_decimal')
            return str(item)
        if isinstance(item, str):
            return json.dumps(item, ensure_ascii=False)
        if isinstance(item, list):
            return '[' + ','.join(emit(child) for child in item) + ']'
        if isinstance(item, dict) and all(isinstance(key, str) for key in item):
            return '{' + ','.join(emit(key) + ':' + emit(item[key]) for key in sorted(item)) + '}'
        raise ValueError('unsupported_exact_json_type')
    return emit(value).encode('utf-8')


def exact(left, right):
    if type(left) is bool or type(right) is bool:
        return type(left) is type(right) and left == right
    if isinstance(left, (int, Decimal)) and isinstance(right, (int, Decimal)):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(exact(value, right[key]) for key, value in left.items())
    if isinstance(left, list):
        return len(left) == len(right) and all(exact(a, b) for a, b in zip(left, right))
    return left == right


def canonical_sha(value):
    return sha(encode(value))


def fingerprint(info):
    return {'device': info.st_dev, 'inode': info.st_ino, 'bytes': info.st_size,
            'mtime_ns': info.st_mtime_ns}


def read_bound(path: Path, expected_sha: str, *, limit=JSON_LIMIT, expected_bytes=None):
    """Read named regular files only and detect replacement/truncation during read."""
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
        raise ValueError('input_not_regular_or_byte_bound_exceeded')
    if expected_bytes is not None and info.st_size != expected_bytes:
        raise ValueError('input_size_mismatch')
    before = fingerprint(info)
    with path.open('rb') as stream:
        if fingerprint(os.fstat(stream.fileno())) != before:
            raise ValueError('input_replaced_before_read')
        body = stream.read(limit + 1)
        if fingerprint(os.fstat(stream.fileno())) != before:
            raise ValueError('input_changed_during_read')
    if fingerprint(path.lstat()) != before:
        raise ValueError('input_replaced_after_read')
    if len(body) != info.st_size or len(body) > limit or sha(body) != expected_sha:
        raise ValueError('input_hash_or_size_mismatch')
    return body, before


def gzip_bytes(body):
    # GzipFile fixes the OS header to255 across Windows/Linux; no embedded path.
    target = io.BytesIO()
    with gzip.GzipFile(filename='', mode='wb', compresslevel=9, mtime=0, fileobj=target) as stream:
        stream.write(body)
    return target.getvalue()


def pointer_get(value, pointer):
    for token in pointer.lstrip('/').split('/') if pointer else []:
        token = token.replace('~1', '/').replace('~0', '~')
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def pointer_escape(value):
    return value.replace('~', '~0').replace('/', '~1')
