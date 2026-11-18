"""Captured product round trips and mechanical dictionary grammar controls."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

import app_payload_criteria_wire as wire

PAIR = json.loads((Path(__file__).parent / 'fixtures/product-criteria-wire-v2-real-20260519.json').read_bytes())


def test_every_retained_fact_and_scoped_citation_round_trips_exactly():
    assert wire.encode_products(PAIR['products']) == PAIR['encoded']
    assert wire.decode_products(PAIR['encoded']) == PAIR['products']
    assert wire.node_count(PAIR['encoded']['products']) == wire.node_count(PAIR['products'])


def test_literal_escape_is_not_a_recursive_dictionary_reference():
    # Protocol-only strings; no product assertions are invented.
    products = {'route': {'literal': '~0', 'double': '~~hello', 'zero': None, 'flag': False, 'number': 0,
                          'list': ['repeated protocol string'] * 20}}
    encoded = wire.encode_products(products)
    assert encoded['stringTable']
    assert wire.decode_products(encoded) == products


@pytest.mark.parametrize('token', ['00', '01', '-1', 'A', '1.0', ' 0', 'zzzzzzzzzzz'])
def test_noncanonical_field_indices_are_rejected(token):
    with pytest.raises(ValueError):
        wire.decode_products({'keyTable': ['value'], 'stringTable': [], 'products': {'route': {token: 1}}})


@pytest.mark.parametrize('fault', ['duplicate-key', 'dangerous-key', 'duplicate-string', 'bad-reference', 'bad-string-token'])
def test_invalid_dictionary_controls_are_rejected(fault):
    encoded = {'keyTable': ['value'], 'stringTable': ['text'], 'products': {'route': {'0': '~0'}}}
    if fault == 'duplicate-key': encoded['keyTable'] *= 2
    if fault == 'dangerous-key': encoded['keyTable'] = ['__proto__']
    if fault == 'duplicate-string': encoded['stringTable'] *= 2
    if fault == 'bad-reference': encoded['products']['route']['0'] = '~1'
    if fault == 'bad-string-token': encoded['products']['route']['0'] = '~00'
    with pytest.raises(ValueError): wire.decode_products(encoded)


def test_detail_node_budget_includes_products_root(monkeypatch):
    products = {'route': {'value': 1}}
    assert wire.node_count(products) == 3
    monkeypatch.setattr(wire, 'MAX_NODES', 2)
    with pytest.raises(ValueError, match='budget'): wire.encode_products(products)
    with pytest.raises(ValueError, match='budget'):
        wire.decode_products({'keyTable': ['value'], 'stringTable': [], 'products': {'route': {'0': 1}}})


@pytest.mark.parametrize('field', ['', '__proto__', 'constructor', 'prototype'])
def test_empty_or_hostile_dictionary_names_and_routes_are_rejected(field):
    with pytest.raises(ValueError): wire.encode_products({'route': {field: 'control'}})
    with pytest.raises(ValueError): wire.decode_products({'keyTable': [field], 'stringTable': [], 'products': {'route': {'0': 'control'}}})
    if field:
        with pytest.raises(ValueError): wire.encode_products({field: {'value': 'control'}})
        with pytest.raises(ValueError): wire.decode_products({'keyTable': ['value'], 'stringTable': [], 'products': {field: {'0': 'control'}}})
