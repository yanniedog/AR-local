"""Lossless bounded dictionary encoding for optional criteria detail trees."""
from collections import Counter
import json
import re

MAX_KEYS = 256
MAX_STRINGS = 65536
MAX_NODES = 500000
MAX_TOTAL_NODES = 4000000
MAX_DEPTH = 64
FORBIDDEN = {'__proto__', 'constructor', 'prototype'}
TOKEN = re.compile(r'(?:0|[1-9a-z][0-9a-z]*)\Z')


def require(value, message):
    if not value:
        raise ValueError(message)


def base36(number):
    result = ''
    while number:
        number, digit = divmod(number, 36)
        result = '0123456789abcdefghijklmnopqrstuvwxyz'[digit] + result
    return result or '0'


def _token(value, length):
    require(isinstance(value, str) and len(value) <= 10 and TOKEN.fullmatch(value), 'invalid criteria dictionary token')
    index = int(value, 36)
    require(index < length, 'criteria dictionary index out of range')
    return index


def _walk(value, visit, depth=0, counter=None):
    counter = counter if counter is not None else [0]
    counter[0] += 1
    require(depth <= MAX_DEPTH and counter[0] <= MAX_NODES, 'criteria detail traversal budget')
    visit(value)
    children = value.values() if isinstance(value, dict) else value if isinstance(value, list) else ()
    for child in children:
        _walk(child, visit, depth + 1, counter)
    return counter[0]


def node_count(products):
    return _walk(products, lambda _: None)


def encode_products(products):
    require(isinstance(products, dict) and all(isinstance(key, str) and key and len(key) <= 2048
            and key not in FORBIDDEN for key in products), 'invalid criteria product routes')
    keys, strings = set(), Counter()
    def collect(value):
        if isinstance(value, dict) and value is not products:
            keys.update(value)
        elif isinstance(value, str):
            strings[value] += 1
    # Route keys are identity, not part of the detail dictionary.
    count = _walk(products, collect)
    require(count <= MAX_NODES, 'criteria detail traversal budget')
    key_table = sorted(keys)
    require(len(keys) <= MAX_KEYS and all(isinstance(key, str) and key and key not in FORBIDDEN
            and len(key.encode('utf-8')) <= 256 for key in keys), 'invalid criteria key table')
    key_indices = {key: base36(index) for index, key in enumerate(key_table)}
    # A conservative fixed reference cost (up to four base36 digits) accounts
    # for the table entry too. Do not pool one-off or unprofitable strings.
    candidates = sorted(value for value, copies in strings.items() if copies > 1
        and len(value.encode('utf-8')) <= 8192
        and copies * (len(json.dumps(value, ensure_ascii=False).encode('utf-8')) - 7)
            > len(json.dumps(value, ensure_ascii=False).encode('utf-8')) + 1)
    require(len(candidates) <= MAX_STRINGS, 'criteria string dictionary budget')
    string_indices = {value: '~' + base36(index) for index, value in enumerate(candidates)}
    def encode(value):
        if isinstance(value, dict):
            return {key_indices[key]: encode(child) for key, child in value.items()}
        if isinstance(value, list):
            return [encode(child) for child in value]
        if isinstance(value, str):
            return string_indices.get(value, '~' + value if value.startswith('~') else value)
        return value
    return {'keyTable': key_table, 'stringTable': candidates,
            'products': {key: encode(detail) for key, detail in products.items()}}


def decode_products(shard):
    keys, strings = shard.get('keyTable'), shard.get('stringTable')
    require(isinstance(keys, list) and len(keys) <= MAX_KEYS
        and all(isinstance(key, str) and key and key not in FORBIDDEN and len(key.encode('utf-8')) <= 256 for key in keys)
        and len(set(keys)) == len(keys), 'invalid criteria key table')
    require(isinstance(strings, list) and len(strings) <= MAX_STRINGS
        and all(isinstance(value, str) and len(value.encode('utf-8')) <= 8192 for value in strings)
        and len(set(strings)) == len(strings), 'invalid criteria string table')
    products = shard.get('products')
    require(isinstance(products, dict) and all(isinstance(key, str) and key and len(key) <= 2048
            and key not in FORBIDDEN for key in products), 'invalid criteria product routes')
    nodes = 1
    def decode(value, depth=0):
        nonlocal nodes
        nodes += 1
        require(depth <= MAX_DEPTH and nodes <= MAX_NODES, 'criteria detail traversal budget')
        if isinstance(value, dict):
            return {keys[_token(key, len(keys))]: decode(child, depth + 1) for key, child in value.items()}
        if isinstance(value, list):
            return [decode(child, depth + 1) for child in value]
        if isinstance(value, str) and value.startswith('~'):
            if value.startswith('~~'):
                return value[1:]
            return strings[_token(value[1:], len(strings))]
        return value
    return {key: decode(detail, 1) for key, detail in products.items()}
