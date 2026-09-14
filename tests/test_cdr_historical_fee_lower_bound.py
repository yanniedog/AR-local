"""Full-transform lower-bound protocol faults in retained May 13 evidence copies."""
from __future__ import annotations

import copy
from decimal import Decimal
from pathlib import Path

import pytest

import cdr_historical_fee_embedded as builder
from cdr_historical_fee_exact import decode, encode, exact, sha


@pytest.fixture(scope='session')
def retained():
    body = (Path(__file__).parent / 'fixtures/historical-fees-may13/embedded-excerpt.json').read_bytes()
    assert sha(body) == '9e4bc07d29cc32e21d28db638f9298d351f252f121fd44f8c94ef0e4521f8541'
    return decode(body)


def protocol(retained, method, nested):
    data = copy.deepcopy(retained)
    original, index = data['examples_original_indices']['zero_TRANSACTION']
    product = data['source']['products'][data['source_product_indices'].index(original)]
    key = product['product_key']
    raw = decode(product['details_json'].encode())
    fee = raw['fees'][index]
    assert fee['feeType'] == 'TRANSACTION'
    fee['feeMethodUType'] = method
    fee['variable'] = {'conditions': [{'nested': [nested]}]}
    product['details_json'] = encode(raw).decode()
    flat, = [row for row in data['source']['fees'] if row['product_key'] == key and row['item_index'] == index + 1]
    flat['details_json'], flat['item_type'] = encode(fee).decode(), fee['feeType']
    return data, key, index, fee


def transform_checked(data, key, index, fee, expected):
    before = encode(data)
    candidate, audit = builder.transform(data['source'], data['core'], data['details'])
    assert encode(data) == before
    restored = copy.deepcopy(candidate)
    for change in audit['changes']:
        restored['products'][change['product_key']]['fees'][change['fee_index']] = change['before']
    assert exact(restored, data['details'])
    builder.verify_changes(data['details'], candidate, audit['changes'])
    row, = [item for item in audit['fees'] if item.get('product_key') == key and item.get('fee_index') == index]
    output = candidate['products'][key]['fees'][index]
    assert row['status'] == expected
    if expected == 'WITHHELD':
        assert encode(output) == encode(data['details']['products'][key]['fees'][index])
        assert not any(item['product_key'] == key and item['fee_index'] == index for item in audit['changes'])
    else:
        assert row['rule_id'] == 'variable_zero_placeholder_v3'
        assert row['removed_fields'] == ['value'] and 'value' not in output
        assert output['amountStatus'] == 'variable'
        assert encode(output['variable']) == encode(fee['variable'])
        assert output['feeMethodUType'] == fee['feeMethodUType']
    return row


@pytest.mark.parametrize('method', ['variable', ' VARIABLE '], ids=['literal', 'normalized'])
@pytest.mark.parametrize('key', ['minimumAmount', 'minimumValue', 'minAmount', 'lowerBound', 'LOWERAMOUNT'])
def test_present_unknown_lower_bound_withholds_entire_fee(retained, method, key):
    data, product, index, fee = protocol(retained, method, {key: None})
    transform_checked(data, product, index, fee, 'WITHHELD')


@pytest.mark.parametrize('method', ['variable', ' VARIABLE '], ids=['literal', 'normalized'])
@pytest.mark.parametrize('value', [None, 'null', ' NULL ', 'none', '', ' \t', False, True,
    [], {}, {'minimumAmount': '0'}, ['0'], 'NaN', '-Infinity', 'Infinity', 'subject to review',
    '1e-1000', '-1e-1000', Decimal('0.00000000000000000001')])
def test_present_unproven_or_nonzero_bound_preserves_fee(retained, method, value):
    data, product, index, fee = protocol(retained, method, {'minimumAmount': value})
    transform_checked(data, product, index, fee, 'WITHHELD')


@pytest.mark.parametrize('method', ['variable', ' VARIABLE '], ids=['literal', 'normalized'])
@pytest.mark.parametrize('value', [0, Decimal('0.000'), ' -0.00 ', '0e-1000'])
def test_all_present_bounds_must_be_exact_zero(retained, method, value):
    nested = {key: value for key in ['minimumAmount', 'minimumValue', 'minAmount', 'lowerBound', 'LOWERAMOUNT']}
    nested['unrelatedUnknownMetadata'] = [None, '', 'none', False, {}, []]
    data, product, index, fee = protocol(retained, method, nested)
    transform_checked(data, product, index, fee, 'REPAIRED')


@pytest.mark.parametrize('method', ['variable', ' VARIABLE '], ids=['literal', 'normalized'])
def test_absent_bounds_and_unrelated_unknown_metadata_remain_distinct(retained, method):
    nested = {'unrelatedUnknownMetadata': [None, 'null', '', False, {}, []]}
    data, product, index, fee = protocol(retained, method, nested)
    transform_checked(data, product, index, fee, 'REPAIRED')


@pytest.mark.parametrize('method', ['variable', ' VARIABLE '], ids=['literal', 'normalized'])
def test_one_exact_zero_does_not_hide_another_unknown_bound(retained, method):
    nested = {'minimumAmount': '0', 'elsewhere': [{'lowerBound': None}]}
    data, product, index, fee = protocol(retained, method, nested)
    transform_checked(data, product, index, fee, 'WITHHELD')


@pytest.mark.parametrize('value', [Decimal('NaN'), Decimal('Infinity'), float('nan'), float('inf'), 0.0])
def test_non_json_numeric_or_float_lower_bound_never_authorizes_deletion(retained, value):
    # Direct boundary for values the exact JSON decoder never admits.
    data, key, index, fee = protocol(retained, ' VARIABLE ', {})
    fee['variable']['minimumAmount'] = value
    old = data['details']['products'][key]['fees'][index]
    before = encode(old)
    # The projection encoder can refuse non-JSON quantities before the guard;
    # either refusal or exact unchanged withholding must prevent deletion.
    try:
        result, disposition = builder.enrich(old, fee)
    except ValueError as exc:
        assert str(exc) in {'nonfinite_decimal', 'unsupported_exact_json_type'}
        assert encode(old) == before
        return
    assert disposition['status'] == 'WITHHELD' and exact(result, old) and encode(old) == before


def test_archive_payload_adapter_preserves_explicit_v3_changes_and_old_core(retained):
    # Exercise serialization only, without archive reads, source admission or seal.
    from cdr_historical_fee_archive import Budget
    from cdr_historical_fee_archive_candidate import _payloads
    from cdr_historical_fee_exact import gzip_bytes
    data, key, index, fee = protocol(retained, ' VARIABLE ', {'minimumAmount': '0'})
    core_bytes = gzip_bytes(encode(data['core']))
    loaded = {'source': data['source'], 'core': data['core'], 'details': data['details'], 'core_bytes': core_bytes}
    before = encode(data)
    payloads, audit = _payloads(loaded, Budget())
    changes = [decode(line) for line in payloads['changes.jsonl'].splitlines()]
    assert exact(changes, audit['changes'])
    changed, = [row for row in changes if row['product_key'] == key and row['fee_index'] == index]
    assert changed['rule_id'] == 'variable_zero_placeholder_v3'
    candidate = decode(payloads['details-candidate.json.gz'], compressed=True)
    builder.verify_changes(data['details'], candidate, changes)
    assert payloads['core.json.gz'] == core_bytes and encode(data) == before
    assert candidate['products'][key]['fees'][index]['feeMethodUType'] == fee['feeMethodUType']
