"""Retained May13 business evidence; injected faults test protocol boundaries only."""
from __future__ import annotations

import copy
import gzip
import json
from decimal import Decimal
from pathlib import Path

import pytest

import cdr_historical_fee_embedded as builder
from cdr_historical_fee_admission import Inputs, verify_parent
from cdr_historical_fee_exact import decode, encode, exact, gzip_bytes, read_bound, sha
from cdr_historical_fee_membership import account, fee_array_binding, product_evidence

FIXTURE = Path(__file__).parent / 'fixtures/historical-fees-may13/embedded-excerpt.json'


@pytest.fixture
def retained():
    body = FIXTURE.read_bytes()
    assert sha(body) == '9e4bc07d29cc32e21d28db638f9298d351f252f121fd44f8c94ef0e4521f8541'
    return decode(body)


def first(retained):
    product = retained['source']['products'][0]
    raw = decode(product['details_json'].encode())
    old = retained['details']['products'][product['product_key']]['fees'][0]
    return product, raw, old


def test_real_excerpt_preserves_every_old_field_and_conflict(retained):
    before = copy.deepcopy(retained)
    candidate, audit = builder.transform(retained['source'], retained['core'], retained['details'])
    assert exact(retained, before)
    assert len([row for row in audit['fees'] if row.get('reason') == 'published_fee_conflicts_with_retained_projection']) == 47
    assert sum(row.get('preexisting_numeric_rate_variant', False) for row in audit['rates']) == 38
    rebuilt = copy.deepcopy(candidate)
    for change in audit['changes']:
        key, index = change['product_key'], change['fee_index']
        old, new = retained['details']['products'][key]['fees'][index], candidate['products'][key]['fees'][index]
        for field, value in old.items():
            if field == 'value' and change['rule_id'] == 'variable_zero_placeholder_v2':
                assert field not in new
            else:
                assert field in new and exact(value, new[field])
        rebuilt['products'][key]['fees'][index] = old
    assert exact(rebuilt, retained['details'])
    assert exact(decode(encode(candidate)), candidate)


def test_direct_union_nested_unknowns_and_two_stage_pointer(retained):
    product, raw, old = first(retained)
    new, disposition = builder.enrich(old, raw['fees'][0])
    assert new['fixedAmount'] == {'amount': '250'}
    assert new['value'] == '250' and disposition['status'] == 'REPAIRED'
    new, _ = builder.enrich(retained['details']['products'][product['product_key']]['fees'][1], raw['fees'][1])
    assert exact(new['variable'], raw['fees'][1]['variable'])
    assert 'null' in new['variable'].values()
    binding = product_evidence(0, product, raw)
    assert binding['embedded_string_pointer'] == '/products/0/details_json'
    assert binding['embedded_string_utf8_sha256'] == sha(product['details_json'].encode())
    assert binding['source_file_reference']['status'] == 'UNVERIFIED_STRING_NOT_DEREFERENCED'
    assert not {'raw_sha256', 'relative_raw_path'} & binding.keys()


@pytest.mark.parametrize('label', ['VARIABLE', 'TRANSACTION', 'WITHDRAWAL'])
def test_real_variable_zero_discriminator_includes_method(retained, label):
    original_index, fee_index = retained['examples_original_indices']['zero_' + label]
    local_index = retained['source_product_indices'].index(original_index)
    product = retained['source']['products'][local_index]
    fee = decode(product['details_json'].encode())['fees'][fee_index]
    old = retained['details']['products'][product['product_key']]['fees'][fee_index]
    new, rule = builder.enrich(old, fee)
    assert rule['rule_id'] == 'variable_zero_placeholder_v2'
    assert rule['removed_fields'] == ['value'] and 'value' not in new
    assert exact(new['amount'], fee['amount']) and new['amountStatus'] == 'variable'


@pytest.mark.parametrize('field,value', [('feeMethodUType', ' VARIABLE '), ('feeMethodUType', 'VaRiAbLe'),
    ('feeMethodUType', 'variable '), ('feeType', 'variable'), ('feeType', ' VARIABLE ')])
def test_normalized_variable_zero_uses_guarded_transform_and_keeps_source_spelling(retained, field, value):
    name = 'zero_TRANSACTION' if field == 'feeMethodUType' else 'zero_VARIABLE'
    pi, index = retained['examples_original_indices'][name]
    product = retained['source']['products'][retained['source_product_indices'].index(pi)]
    key = product['product_key']
    raw = decode(product['details_json'].encode())
    fee = raw['fees'][index]
    old = retained['details']['products'][key]['fees'][index]
    fee[field] = value
    if field == 'feeType':
        old['label'] = value  # Fault fixture's legacy label keeps the same source spelling.
    product['details_json'] = encode(raw).decode()
    flat = [row for row in retained['source']['fees'] if row['product_key'] == key and row['item_index'] == index + 1]
    assert len(flat) == 1
    flat[0]['details_json'], flat[0]['item_type'] = encode(fee).decode(), fee['feeType']
    before = copy.deepcopy(retained)
    candidate, audit = builder.transform(retained['source'], retained['core'], retained['details'])
    assert exact(before, retained)
    change = next((row for row in audit['changes'] if row['product_key'] == key and row['fee_index'] == index), None)
    assert change is not None
    assert change['rule_id'] == 'variable_zero_placeholder_v2'
    assert change['removed_fields'] == ['value']
    new = candidate['products'][key]['fees'][index]
    assert 'value' not in new and new['amountStatus'] == 'variable'
    assert new['label'] == old['label'] and new['amount'] == fee['amount']
    if field == 'feeMethodUType':
        assert new[field] == value
    assert change['field_sources']['amountStatus']['inputs'][field] == {'present': True, 'value': value}
    restored = copy.deepcopy(candidate)
    for row in audit['changes']:
        restored['products'][row['product_key']]['fees'][row['fee_index']] = row['before']
    assert exact(restored, retained['details'])


@pytest.mark.parametrize('field,value', [('provider', ['invalid']), ('provider', {'invalid': True}), ('product_key', 7)])
def test_malformed_text_identity_is_refused_before_sorting_or_bank_tabulation(retained, field, value):
    retained['source']['products'][0][field] = value
    before = copy.deepcopy(retained)
    with pytest.raises(ValueError, match='source_identity_type_invalid'):
        builder.transform(retained['source'], retained['core'], retained['details'])
    assert exact(before, retained)


@pytest.mark.parametrize('array,field,value', [('rates', 'provider', 7), ('fees', 'product_key', 7),
    ('rates', 'rate_family', 7), ('products', 'provider', False), ('products', 'product_name', None)])
def test_text_identity_types_are_distinct_from_integer_indices(retained, array, field, value):
    retained['source'][array][0][field] = value
    with pytest.raises(ValueError, match='source_identity_type_invalid'):
        builder.transform(retained['source'], retained['core'], retained['details'])


@pytest.mark.parametrize('array,field', [('rates', 'rate_index'), ('fees', 'item_index')])
@pytest.mark.parametrize('value', [False, '1', Decimal('1'), None])
def test_row_indices_require_actual_integers_without_coercion(retained, array, field, value):
    retained['source'][array][0][field] = value
    with pytest.raises(ValueError, match='source_identity_type_invalid'):
        builder.transform(retained['source'], retained['core'], retained['details'])


@pytest.mark.parametrize('guard', ['second_conflict', 'additional_value', 'source_nonzero', 'lower_bound',
                                  'old_bool', 'source_bool', 'source_missing'])
def test_normalized_variable_rule_keeps_all_other_zero_guards(retained, guard):
    pi, index = retained['examples_original_indices']['zero_TRANSACTION']
    product = retained['source']['products'][retained['source_product_indices'].index(pi)]
    fee = decode(product['details_json'].encode())['fees'][index]
    old = retained['details']['products'][product['product_key']]['fees'][index]
    fee['feeMethodUType'] = ' VARIABLE '
    if guard == 'second_conflict':
        old['unreviewedExistingField'] = None
    elif guard == 'additional_value':
        fee['additionalValue'] = '0'
    elif guard == 'source_nonzero':
        fee['amount'] = '1'
    elif guard == 'lower_bound':
        fee['variable'] = {'conditions': [{'minimumAmount': '0.0000000000000000001'}]}
    elif guard == 'old_bool':
        old['value'] = False
    elif guard == 'source_bool':
        fee['amount'] = False
    else:
        fee.pop('amount')
    before = copy.deepcopy(old)
    new, disposition = builder.enrich(old, fee)
    assert disposition['status'] == 'WITHHELD' and exact(new, before)


def test_versioned_zero_rule_preserves_legacy_reconstruction_and_rejects_unknown(retained):
    candidate, audit = builder.transform(retained['source'], retained['core'], retained['details'])
    zero_changes = [row for row in audit['changes'] if row['removed_fields']]
    assert zero_changes and {row['rule_id'] for row in zero_changes} == {'variable_zero_placeholder_v2'}
    legacy = copy.deepcopy(audit['changes'])
    for row in legacy:
        if row['removed_fields']:
            row['rule_id'] = 'variable_zero_placeholder_v1'
    # Structural restoration is backward compatible; it does not reclassify
    # original evidence or claim that a v1 receipt used v2 source semantics.
    builder.verify_changes(retained['details'], candidate, legacy)
    next(row for row in legacy if row['removed_fields'])['rule_id'] = 'variable_zero_placeholder_v999'
    with pytest.raises(ValueError, match='unapproved_fee_field_deletion'):
        builder.verify_changes(retained['details'], candidate, legacy)


@pytest.mark.parametrize('value', [False, True, '0.00000000000000000000000001', '1', 'NaN', 'Infinity', None])
def test_zero_exception_rejects_nonzero_bool_or_unknown(retained, value):
    pi, fi = retained['examples_original_indices']['zero_VARIABLE']
    product = retained['source']['products'][retained['source_product_indices'].index(pi)]
    fee = decode(product['details_json'].encode())['fees'][fi]
    old = copy.deepcopy(retained['details']['products'][product['product_key']]['fees'][fi])
    old['value'] = value
    new, result = builder.enrich(old, fee)
    assert result['status'] == 'WITHHELD' and exact(new, old)


def test_nonzero_lower_bound_and_unknown_existing_field_are_not_replaced(retained):
    pi, fi = retained['examples_original_indices']['zero_VARIABLE']
    product = retained['source']['products'][retained['source_product_indices'].index(pi)]
    fee = decode(product['details_json'].encode())['fees'][fi]
    old = retained['details']['products'][product['product_key']]['fees'][fi]
    fee['variable'] = {'minimumAmount': '2'}
    assert builder.enrich(old, fee)[1]['status'] == 'WITHHELD'
    product, raw, old = first(retained)
    old = {**old, 'amountStatus': None, 'unknownExtension': False}
    assert builder.enrich(old, raw['fees'][0]) == (old, {
        'status': 'WITHHELD', 'reason': 'published_fee_conflicts_with_retained_projection',
        'conflicting_fields': ['amountStatus', 'unknownExtension']})


@pytest.mark.parametrize('body', [b'{"a":1,"a":2}', b'{"x":NaN}', b'{"x":Infinity}', b'\xff'])
def test_strict_json_rejects_ambiguous_or_invalid_bytes(body):
    with pytest.raises((ValueError, UnicodeError)):
        decode(body)


def test_exact_numbers_keep_precision_and_json_types():
    original = decode(b'{"n":12345678901234567890.00000000000000000001,"zero":0,"bool":false,"null":null,"s":"0"}')
    assert exact(decode(encode(original)), original)
    assert original['n'] == Decimal('12345678901234567890.00000000000000000001')
    assert not exact(original['zero'], original['bool']) and not exact(original['zero'], original['s'])
    with pytest.raises(ValueError, match='unsupported_exact_json_type'):
        encode({'amount': 0.1})
    assert gzip_bytes(encode(original)) == gzip_bytes(encode(original))
    assert exact(decode(gzip_bytes(encode(original)), compressed=True), original)


def test_reads_are_bounded_and_hash_fingerprints_checked(tmp_path):
    path = tmp_path / 'input.json'
    path.write_bytes(b'{"a":1}')
    with pytest.raises(ValueError):
        read_bound(path, sha(path.read_bytes()), limit=2)
    with pytest.raises(ValueError):
        read_bound(path, '0' * 64)
    with pytest.raises(ValueError):
        decode(gzip.compress(b' ' * 100), compressed=True, limit=20)
    inputs = Inputs()
    inputs.read('source', path, sha(path.read_bytes()))
    path.write_bytes(b'{"a":2}')
    with pytest.raises(ValueError):
        inputs.recheck()


@pytest.mark.parametrize('field', ['name', 'productCategory', 'lastUpdated', 'brand'])
def test_enclosing_embedded_identity_conflicts_withhold_product(retained, field):
    product, raw, _ = first(retained)
    raw[field] = 'protocol-identity-mutation'
    product['details_json'] = encode(raw).decode()
    _, audit = builder.transform(retained['source'], retained['core'], retained['details'])
    assert all(row['product_key'] != product['product_key'] for row in audit['changes'])


def test_duplicate_product_scope_never_chooses_similar_fees(retained):
    product = retained['source']['products'][0]
    retained['source']['products'].append(copy.deepcopy(product))
    candidate, audit = builder.transform(retained['source'], retained['core'], retained['details'])
    assert exact(candidate['products'][product['product_key']], retained['details']['products'][product['product_key']])
    assert not any(row['product_key'] == product['product_key'] for row in audit['changes'])


@pytest.mark.parametrize('mutation', ['zero_index', 'bool_index', 'price', 'duplicate_rate', 'fee_order', 'fee_length', 'flat_index', 'flat_scope', 'nested_duplicate'])
def test_rate_and_full_array_membership_fail_closed(retained, mutation):
    product, raw, _ = first(retained)
    key = product['product_key']
    source = retained['source']
    detail = retained['details']['products'][key]
    if mutation == 'zero_index':source['rates'][0]['rate_index'] = 0
    elif mutation == 'bool_index':source['rates'][0]['rate_index'] = True
    elif mutation == 'price':retained['core']['sections']['Mortgage']['rates'][0]['rate'] = '0.1'
    elif mutation == 'duplicate_rate':source['rates'].append(copy.deepcopy(source['rates'][0]))
    elif mutation == 'fee_order':detail['fees'][0], detail['fees'][1] = detail['fees'][1], detail['fees'][0]
    elif mutation == 'fee_length':detail['fees'].pop()
    elif mutation == 'flat_index':source['fees'][0]['item_index'] = 999
    elif mutation == 'flat_scope':source['fees'][0]['provider'] = 'other-provider'
    else:product['details_json'] = '{"fees":[],"fees":[]}'
    if mutation in ('bool_index', 'nested_duplicate'):
        with pytest.raises(ValueError):builder.transform(source, retained['core'], retained['details'])
    else:
        candidate, audit = builder.transform(source, retained['core'], retained['details'])
        assert not any(row['product_key'] == key for row in audit['changes'])


def test_parent_rate_or_extension_change_is_rejected(retained):
    parent = copy.deepcopy(retained['core'])
    parent['sections']['Mortgage']['rates'][0]['rate'] = '0.1'
    with pytest.raises(ValueError, match='parent_changed'):
        verify_parent(retained['core'], parent, [], retained['source'])


def test_output_collision_refused_before_source_reads(tmp_path, monkeypatch):
    output = tmp_path / 'candidate'; output.mkdir(); marker = output / 'keep'; marker.write_bytes(b'unchanged')
    monkeypatch.setattr(builder, 'load_inputs', lambda *args: pytest.fail('must not read inputs'))
    with pytest.raises(ValueError, match='new_separate'):
        builder.prepare(*(tmp_path / str(i) for i in range(5)), output)
    assert marker.read_bytes() == b'unchanged'


@pytest.mark.parametrize('value', [None, False, [], {}])
def test_missing_and_unknown_arrays_do_not_create_fees(retained, value):
    product, _, _ = first(retained)
    key = product['product_key']
    retained['details']['products'][key]['fees'] = value
    candidate, audit = builder.transform(retained['source'], retained['core'], retained['details'])
    assert exact(candidate['products'][key]['fees'], value)
    assert not any(row['product_key'] == key for row in audit['changes'])


def test_short_write_and_symlink_input_fail_closed(tmp_path):
    class ShortStream:
        def __enter__(self):return self
        def __exit__(self, *args):pass
        def write(self, body):return len(body) - 1
    class ShortPath:
        def open(self, mode):return ShortStream()
    with pytest.raises(OSError, match='short_write'):
        builder._write(ShortPath(), b'abc')
    target = tmp_path / 'target'; target.write_bytes(b'{}')
    link = tmp_path / 'link'
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip('Ordinary-user symlink creation unavailable; no elevation attempted')
    with pytest.raises(ValueError, match='not_regular'):
        read_bound(link, sha(b'{}'))


def test_interrupted_candidate_has_no_seal_and_cannot_overwrite_on_retry(retained, tmp_path, monkeypatch):
    # Isolate the output controller after admission. This technical stub is not
    # an admitted source or acceptance claim; all business fields are retained.
    inputs = Inputs()
    inputs.read('test_excerpt', FIXTURE, sha(FIXTURE.read_bytes()))
    schema = decode((Path(__file__).resolve().parents[1] / 'contracts/historical-fees/embedded-export-v1.schema.json').read_bytes())
    props = schema['properties']['container']['properties']
    container = {key: value.get('const', '0' * 64) for key, value in props.items()}
    loaded = {'inputs': inputs, 'source': retained['source'], 'anchor_core': retained['core'],
              'details': retained['details'], 'core_bytes': gzip_bytes(encode(retained['core'])),
              'anchor_manifest': {'files': {}}, 'container': container,
              'source_generation_time': retained['source']['generated_at'],
              'parent_lineage': {'rows': sum(len(s['rates']) for s in retained['core']['sections'].values()),
                                'taxonomy_additions_preserved': 0, 'taxonomy_source_proofs_rechecked': 0,
                                'all_existing_rate_values_order_and_multiplicity_preserved': True}}
    monkeypatch.setattr(builder, 'load_inputs', lambda *args: loaded)
    write = builder._write
    def interrupted(path, body):
        if path.name == 'admission.json':raise OSError('injected_interruption_before_seal')
        write(path, body)
    monkeypatch.setattr(builder, '_write', interrupted)
    output = tmp_path / 'candidate'
    with pytest.raises(OSError, match='injected_interruption'):
        builder.prepare(*(tmp_path / ('source-' + str(i)) for i in range(5)), output)
    assert output.exists() and not (output / 'receipt.json').exists()
    preserved = {path.name: path.read_bytes() for path in output.iterdir()}
    with pytest.raises(ValueError, match='new_separate'):
        builder.prepare(*(tmp_path / ('source-' + str(i)) for i in range(5)), output)
    assert preserved == {path.name: path.read_bytes() for path in output.iterdir()}


def test_publication_and_unsupported_operational_fields_rejected_by_schema():
    from jsonschema import Draft202012Validator
    path = Path(__file__).resolve().parents[1] / 'contracts/historical-fees/embedded-export-v1.schema.json'
    schema = decode(path.read_bytes())
    assert schema['additionalProperties'] is False
    assert schema['properties']['publication'] == {'const': 'NOT_ATTEMPTED'}
    assert schema['properties']['container']['properties']['image_read_this_run'] == {'const': False}
    Draft202012Validator.check_schema(schema)
