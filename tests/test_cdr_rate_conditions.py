"""Real source regression plus adversarial protocol-shape checks."""
import copy
import gzip
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError

from app_payload_details import build_details
from cdr_clean_export import parse_banks_run
from cdr_rate_conditions import encoded, extract_rate_conditions, validate_rate_conditions

FIXTURE = Path(__file__).parent / 'fixtures/rate_conditions/macquarie-digital-2026-09-15.json'


def export(tmp_path, source):
    path = tmp_path / 'banks/TD/Macquarie/product/product-detail.json'
    path.parent.mkdir(parents=True)
    path.write_bytes(source)
    return parse_banks_run(tmp_path)


def test_real_macquarie_eight_scoped_conditions_reach_details(tmp_path):
    source = FIXTURE.read_bytes()
    assert len(source) == 5018
    assert hashlib.sha256(source).hexdigest() == 'd387b14ea2d803cb6e8b52acacf9d0e0089623d345fa390c1d05cc047f5feb64'
    result = export(tmp_path, source)
    product = result['products'][0]
    value = build_details([product])[product['product_key']]['rateConditions']
    validate_rate_conditions(value)
    assert value == json.loads(FIXTURE.with_name(FIXTURE.stem + '.rate-conditions.json').read_bytes())
    assert [entry['rateIndex'] for entry in value['entries']] == list(range(1, 9))
    assert [row['rate_index'] for row in result['rates']] == list(range(1, 9))
    for index, entry in enumerate(value['entries']):
        assert entry['sourcePointer'] == f'/data/depositRates/{index}/tiers/0/applicabilityConditions/additionalInfo'
        assert entry['text'] == ('For balances of 1 million dollars and under' if index < 4 else 'For balances of over 1 million dollars')
    assert len({entry['id'] for entry in value['entries']}) == 8
    assert (tmp_path / 'banks/TD/Macquarie/product/product-detail.json').read_bytes() == source


def test_original_indices_and_filtered_ordinals_survive_empty_items(tmp_path):
    record = json.loads(FIXTURE.read_bytes())['data']
    rate = copy.deepcopy(record['depositRates'][0])
    rate['additionalInfo'] = '  Exact source quote  '
    rate['applicabilityConditions'] = [None, {}, {'additionalInfo': 'Rate condition'}]
    rate['tiers'] = [None, {}, rate['tiers'][0]]
    record['depositRates'] = [None, {}, rate]
    source = encoded(record)  # Unwrapped response also has original-byte identity.
    result = export(tmp_path, source)
    value = json.loads(result['products'][0]['rate_conditions_json'])
    validate_rate_conditions(value)
    assert [row['rate_index'] for row in result['rates']] == [1, 2]
    assert {entry['rateIndex'] for entry in value['entries']} == {2}
    assert {entry['rateSourcePointer'] for entry in value['entries']} == {'/depositRates/2'}
    assert [entry['sourcePointer'] for entry in value['entries']] == [
        '/depositRates/2/additionalInfo', '/depositRates/2/applicabilityConditions/2/additionalInfo',
        '/depositRates/2/tiers/2/applicabilityConditions/additionalInfo']
    assert value['entries'][0]['text'] == '  Exact source quote  '


def test_legacy_absence_and_cdr_metadata_cannot_impersonate_capture(tmp_path):
    record = json.loads(FIXTURE.read_bytes())['data']
    record['rate_conditions_json'] = 'injected'
    result = export(tmp_path, encoded(record))
    product = result['products'][0]
    assert product['rate_conditions_json'] != 'injected'
    product.pop('rate_conditions_json')
    assert 'rateConditions' not in build_details([product])[product['product_key']]
    product['rate_conditions_json'] = 'injected'
    with pytest.raises(ValueError):
        build_details([product])


def test_lending_family_and_list_tier_conditions_keep_exact_scope():
    record = json.loads(FIXTURE.read_bytes())['data']
    rate = copy.deepcopy(record['depositRates'][0])
    rate['tiers'][0]['applicabilityConditions'] = [None, {'additionalInfo': 'Same quote'},
                                                 {'additionalInfo': 'Same quote'}]
    record['lendingRates'] = [rate]
    value = extract_rate_conditions(encoded({'data': record}), 'Mortgage')
    validate_rate_conditions(value)
    assert {entry['rateFamily'] for entry in value['entries']} == {'lending'}
    assert len({entry['id'] for entry in value['entries']}) == 2
    assert [entry['sourcePointer'] for entry in value['entries']] == [
        f'/data/lendingRates/0/tiers/0/applicabilityConditions/{i}/additionalInfo' for i in (1, 2)]


def test_export_retains_oversized_quotes_but_packaging_rejects(tmp_path):
    record = json.loads(FIXTURE.read_bytes())
    quote = '\u00e9' * 8193
    record['data']['depositRates'][0]['additionalInfo'] = quote
    result = export(tmp_path, encoded(record))
    product = result['products'][0]
    assert json.loads(product['rate_conditions_json'])['entries'][0]['text'] == quote
    with pytest.raises(ValueError, match='text_byte_bound'):
        build_details([product])


@pytest.mark.parametrize('mutation', ['id', 'family', 'tier', 'duplicate', 'version', 'unknown', 'utf8'])
def test_invalid_contract_is_terminal_not_silently_dropped(mutation):
    value = extract_rate_conditions(FIXTURE.read_bytes(), 'TD')
    entry = value['entries'][0]
    if mutation == 'id': entry['id'] = '0' * 64
    if mutation == 'family': entry['rateFamily'] = 'lending'
    if mutation == 'tier': entry['tierSourcePointer'] = '/data/depositRates/1/tiers/0'
    if mutation == 'duplicate': value['entries'].append(copy.deepcopy(entry))
    if mutation == 'version': value['schemaVersion'] = 2
    if mutation == 'unknown': value['numericBalance'] = 1000000
    if mutation == 'utf8': entry['text'] = '\u00e9' * 8193
    with pytest.raises((ValueError, ValidationError)):
        build_details([{'product_key': 'p', 'rate_conditions_json': encoded(value).decode()}])


def test_actual_details_package_fails_budget_without_dropping_quotes(tmp_path, monkeypatch):
    from app_payload_build import _package
    import app_payload_network_budget
    result = export(tmp_path / 'run', FIXTURE.read_bytes())
    details = {'run_date': '2026-09-15', 'products': build_details(result['products'])}
    out = tmp_path / 'package'
    monkeypatch.setattr(app_payload_network_budget, 'DETAILS_MAX_BYTES', 1)
    with pytest.raises(ValueError, match='details bytes'):
        _package({}, details, '2026-09-15', out, repo='test/test', tag='test', counts={})
    assert not (out / 'manifest.json').exists()
    asset = next(out.glob('*details*.gz'))
    assert json.loads(gzip.decompress(asset.read_bytes())) == details
