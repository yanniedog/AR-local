"""Acceptance against retained public CDR bytes plus deliberate fault controls."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from cdr_domain.public_pricing import condition_state, fraction_text, fraction_value
from cdr_domain.public_pricing_resolver import resolve_public_rate
from cdr_domain.public_pricing_validation import validate_programme
from cdr_public_rates_cdr import compile_record, compile_export_products, inventory_from_compiled
from cdr_public_rates_legacy import legacy_disposition

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/public_rates'
GOLDEN = ROOT / 'contracts/public_rates/fixtures/resolver-golden-v1.json'


@pytest.fixture(scope='module')
def goldens():
    return json.loads(GOLDEN.read_bytes())['cases']


@pytest.fixture(scope='module')
def nab_compiled():
    return compile_fixture('nab-tailored-cdr-20261013.json', 'NAB', 'Mortgage')


def compile_fixture(filename, provider, section, record=None):
    raw = (FIXTURES / filename).read_bytes()
    metadata = json.loads((FIXTURES / (filename + '.metadata.json')).read_bytes())
    assert metadata['public'] is True
    assert hashlib.sha256(raw).hexdigest() == metadata['sha256']
    record = record or json.loads(raw)['data']
    return compile_record(record, provider_name=provider, section=section,
                          source_url=metadata['sourceUrl'], source_sha256=metadata['sha256'],
                          checked_at=metadata['checkedAt'], product_key=provider + '|' + record['productId'])


def high_lvr(compiled):
    return next(p for p in compiled['programmes'] if p['sourceBindings'][0]['rateIndex'] == 7)


def scenario():
    return {'amount': '500000', 'lvr': '0.94', 'purpose': 'OWNER_OCCUPIED', 'repayment': 'PRINCIPAL_AND_INTEREST'}


def test_all_categories_match_independent_decimal_source_oracles(goldens):
    assert {case['programme']['section'] for case in goldens} == {'Mortgage', 'Savings', 'TD'}
    for case in goldens:
        source = (FIXTURES / case['publicSource']['fixture']).read_bytes()
        assert hashlib.sha256(source).hexdigest() == case['publicSource']['sha256']
        actual = resolve_public_rate(case['programme'], case['scenario'], case['asOf'])
        for field, expected in case['expected'].items():
            assert actual[field] == expected
        assert actual['origin'] == ('publicly_calculated' if case['programme']['section'] == 'Savings' else 'published')
        if case['programme']['section'] == 'Savings':
            rates = json.loads(source)['data']['depositRates']
            assert Decimal(actual['payableRate']) == Decimal(rates[0]['rate']) + Decimal(rates[1]['rate'])


@pytest.mark.parametrize('lvr', ['0.8001', '0.85', '0.8501', '0.90', '0.95'])
def test_nab_open_lvr_tier_keeps_public_range_through_genuine_cap(nab_compiled, goldens, lvr):
    result = resolve_public_rate(high_lvr(nab_compiled), {**scenario(), 'lvr': lvr}, goldens[0]['asOf'])
    assert result['status'] == 'range'
    assert (result['minimumRate'], result['maximumRate']) == ('0.0684', '0.0724')
    assert result['verifiedCurrent'] is False


@pytest.mark.parametrize('changes', [{'lvr': '0.8'}, {'lvr': '0.9501'}, {'amount': '19999'},
                                     {'purpose': 'INVESTMENT'}, {'repayment': 'INTEREST_ONLY'}])
def test_nab_scenarios_do_not_cross_public_scope(nab_compiled, goldens, changes):
    result = resolve_public_rate(high_lvr(nab_compiled), {**scenario(), **changes}, goldens[0]['asOf'])
    assert result['status'] == 'unresolved'
    assert 'payableRate' not in result and 'minimumRate' not in result


def test_open_lvr_and_maximum_product_constraint_remain_separate(nab_compiled):
    programme = high_lvr(nab_compiled)
    tier = programme['formula']['minimum']['tiers'][0]
    assert tier['minimum'] == '0.8001' and 'maximum' not in tier
    maximum = [c for c in programme['conditions'] if c['field'] == 'lvr']
    assert maximum[0]['maximum'] == '0.95'
    constraint_ref = next(e for e in nab_compiled['evidence'] if e['evidenceId'] == maximum[0]['evidenceIds'][0])
    assert constraint_ref['locator'] == '/data/constraints'


def test_source_reordering_and_price_change_do_not_change_semantic_selection(nab_compiled):
    raw = json.loads((FIXTURES / 'nab-tailored-cdr-20261013.json').read_bytes())['data']
    reordered = deepcopy(raw)
    reordered['lendingRates'].reverse()
    newer = compile_fixture('nab-tailored-cdr-20261013.json', 'NAB', 'Mortgage', reordered)
    assert {p['programmeId'] for p in nab_compiled['programmes']} == {p['programmeId'] for p in newer['programmes']}
    previous = high_lvr(nab_compiled)
    changed = deepcopy(raw)
    changed['lendingRates'][6]['rate'] = '0.0685'  # Deliberate parser change control, not acceptance pricing.
    revised = high_lvr(compile_fixture('nab-tailored-cdr-20261013.json', 'NAB', 'Mortgage', changed))
    assert revised['programmeId'] == previous['programmeId']
    assert revised['offerId'] == previous['offerId']
    assert revised['components'][0]['source']['rawValue'] == '0.0685'


def test_range_grouping_retains_verbatim_material_notes_and_review_binding(nab_compiled):
    from cdr_public_rates_publication import programme_structure_sha256
    raw = json.loads((FIXTURES / 'nab-tailored-cdr-20261013.json').read_bytes())['data']
    original = high_lvr(nab_compiled)
    notes = [raw['lendingRates'][index - 1]['additionalInfo'] for index in (7, 8)]
    assert original['materialFootnotes'] == sorted(set(notes))
    raw['lendingRates'][6]['additionalInfo'] += ' Only available to bank staff.'  # Structural review control.
    revised = high_lvr(compile_fixture('nab-tailored-cdr-20261013.json', 'NAB', 'Mortgage', raw))
    assert revised['programmeId'] == original['programmeId']
    assert revised['formula']['op'] == original['formula']['op'] == 'range'
    assert programme_structure_sha256(revised) != programme_structure_sha256(original)


def test_duplicate_conflicting_scope_becomes_unresolved_not_rebound():
    raw = json.loads((FIXTURES / 'nab-tailored-cdr-20261013.json').read_bytes())['data']
    raw['lendingRates'].append(deepcopy(raw['lendingRates'][0]))
    result = compile_fixture('nab-tailored-cdr-20261013.json', 'NAB', 'Mortgage', raw)
    duplicate = next(p for p in result['programmes'] if any(s['rateIndex'] == 1 for s in p['sourceBindings']))
    assert 'conflicting_source_rates' in duplicate['reasonCodes']
    assert 'formula' not in duplicate
    validate_programme(duplicate)


def test_unknown_source_role_and_blank_numerical_value_are_not_absolute(goldens):
    case = deepcopy(goldens[2])
    programme = case['programme']
    programme['components'][0].pop('value')
    actual = resolve_public_rate(programme, case['scenario'], case['asOf'])
    assert actual['status'] == 'unresolved' and 'payableRate' not in actual
    raw = json.loads((FIXTURES / 'anz-term-deposit-cdr-20261014.json').read_bytes())['data']
    raw['depositRates'][1]['depositRateType'] = 'UNSUPPORTED_TYPE_CONTROL'
    result = compile_fixture('anz-term-deposit-cdr-20261014.json', 'ANZ', 'TD', raw)
    programme = next(p for p in result['programmes'] if p['sourceBindings'][0]['rateIndex'] == 2)
    assert 'unsupported_cdr_rate_type' in programme['reasonCodes'] and 'formula' not in programme


def test_customer_relationship_without_public_definition_stays_unresolved():
    result = compile_fixture('nab-term-deposit-cdr-20261014.json', 'NAB', 'TD')
    assert all('formula' not in p for p in result['programmes'])
    assert any('uninterpreted_material_condition' in p['reasonCodes'] for p in result['programmes'])


@pytest.mark.parametrize('changes', [{'monthlyDeposit': '9.99'}, {'withdrawals': '1'}, {'noFeesOrCharges': False},
                                     {'qualificationPeriodSatisfied': False}])
def test_bonus_qualifications_cannot_be_ignored(goldens, changes):
    case = goldens[1]
    result = resolve_public_rate(case['programme'], {**case['scenario'], **changes}, case['asOf'])
    assert result['status'] == 'unresolved'


def test_unknown_bonus_qualification_does_not_become_false_or_zero(goldens):
    case = goldens[1]
    scenario_without_qualification = {key: value for key, value in case['scenario'].items() if key != 'noFeesOrCharges'}
    result = resolve_public_rate(case['programme'], scenario_without_qualification, case['asOf'])
    assert result['status'] == 'unresolved'
    assert any(c['value'] == 'noFeesOrCharges' for c in result['conditions']['unknown'])
    assert 'payableRate' not in result


def test_disclosed_bonus_base_is_reference_only_and_base_only_products_still_resolve(goldens):
    compiled = compile_fixture('anz-progress-saver-cdr-20261014.json', 'ANZ', 'Savings')
    base = next(p for p in compiled['programmes'] if p['sourceBindings'][0]['rateIndex'] == 1)
    assert base['components'][0]['role'] == 'reference'
    assert 'base_component_requires_adjustment_resolution' in base['reasonCodes']
    adjusted = next(p for p in compiled['programmes'] if any(c['role'] == 'bonus' for c in p['components']))
    assert resolve_public_rate(adjusted, goldens[1]['scenario'], goldens[1]['asOf'])['payableRate'] == '0.04'
    for scenario_input in (goldens[1]['scenario'], {}):
        result = resolve_public_rate(base, scenario_input, goldens[1]['asOf'])
        assert result['status'] == 'unresolved' and 'payableRate' not in result
    raw = json.loads((FIXTURES / 'anz-progress-saver-cdr-20261014.json').read_bytes())['data']
    raw['depositRates'] = raw['depositRates'][:1]  # Structural adapter control using the actual public base.
    only = compile_fixture('anz-progress-saver-cdr-20261014.json', 'ANZ', 'Savings', raw)['programmes'][0]
    assert resolve_public_rate(only, goldens[1]['scenario'], goldens[1]['asOf'])['payableRate'] == '0.0001'


def test_failed_and_stale_checks_require_explicit_historical_selection(goldens):
    case = goldens[1]
    programme = deepcopy(case['programme'])
    programme['freshness']['state'] = 'failed'
    assert resolve_public_rate(programme, case['scenario'], case['asOf'])['status'] == 'unresolved'
    historical = resolve_public_rate(programme, {**case['scenario'], 'allowHistorical': True}, case['asOf'])
    assert historical['payableRate'] == '0.04' and historical['verifiedCurrent'] is False
    source_check = datetime.fromisoformat(programme['freshness']['lastSuccessAt'])
    programme['freshness']['state'] = 'current'
    stale_time = (source_check + timedelta(hours=48, seconds=1)).isoformat()
    stale = resolve_public_rate(programme, case['scenario'], stale_time)
    assert stale['status'] == 'unresolved' and stale['freshness']['state'] == 'stale'
    at_limit = resolve_public_rate(programme, case['scenario'], (source_check + timedelta(hours=48)).isoformat())
    assert at_limit['freshness']['state'] == 'current'


def test_future_and_expired_programmes_are_not_applied_early(goldens):
    case = goldens[1]
    programme = deepcopy(case['programme'])
    programme['effectiveFrom'] = '2026-10-15'
    assert resolve_public_rate(programme, case['scenario'], case['asOf'])['status'] == 'unresolved'
    programme.pop('effectiveFrom')
    programme['effectiveTo'] = '2026-10-14'
    assert resolve_public_rate(programme, case['scenario'], case['asOf'])['status'] == 'unresolved'


def test_unknown_fee_methods_and_event_costs_are_visible(goldens):
    mortgage = goldens[0]['programme']
    assert mortgage['feeCoverage']['status'] == 'partial'
    assert any(fee['amount'] == '0' for fee in mortgage['fees'] if 'amount' in fee)
    assert any(fee['role'] == 'recurring' and fee['amount'] == '12' and fee['frequencyMonths'] == 1 for fee in mortgage['fees'])
    assert 'fee_amount_or_method_unknown' in mortgage['feeCoverage']['reasonCodes']
    td = goldens[2]['programme']
    assert td['feeCoverage']['status'] == 'partial' and td['metadata']['interestPayment']['type'] == 'maturity'


def test_old_editions_discover_products_without_creating_pricing_from_normalized_rows():
    product = {'dataset': 'Savings', 'provider': 'ANZ', 'product_id': 'retained-product-identity-control',
               'product_key': 'retained-product-identity-control', 'product_name': 'Retained public identity',
               'details_json': '{}'}
    result = compile_export_products([product])
    assert len(result['products']) == 1 and result['products'][0]['programmeIds'] == []
    assert 'original_source_url_unavailable' in result['products'][0]['reasonCodes']
    assert 'sourceEvidence' not in result['products'][0]
    assert result['products'][0]['freshness']['state'] == 'unknown'
    inventory = inventory_from_compiled(result, ['Additional registered provider control'])
    assert len(inventory) == 6 and all(item['resolutionStatus'] == 'unresolved' for item in inventory)


def test_unit_arithmetic_does_not_guess_magnitude():
    assert fraction_value('9.02', 'percentage_points') == Fraction(Decimal('0.0902'))
    assert fraction_value('902', 'basis_points') == Fraction(Decimal('0.0902'))
    assert fraction_value('0.0902', 'fraction_per_annum') == Fraction(Decimal('0.0902'))
    assert fraction_text(Fraction(1, 3)) == ('0.333333333333333333333333', True)
    assert condition_state({'field': 'termMonths', 'operator': 'eq', 'value': '1'}, {'termMonths': '1.00'}) == 'met'


def test_negative_derived_rates_and_phases_remain_unresolved(goldens):
    case = goldens[1]
    programme = deepcopy(case['programme'])
    programme['formula']['op'] = 'subtract'
    programme['phases'] = [{'phaseId': 'invalid-negative-control', 'startMonth': 0,
                            'formula': programme['formula'], 'conditions': [], 'evidenceIds': programme['evidenceIds']}]
    result = resolve_public_rate(programme, case['scenario'], case['asOf'])
    assert result['status'] == 'unresolved' and 'payableRate' not in result
    assert 'payable_rate_out_of_bounds' in result['reasonCodes']
    programme['formula'] = deepcopy(case['programme']['formula'])
    result = resolve_public_rate(programme, case['scenario'], case['asOf'])
    assert result['status'] == 'exact' and result['phases'][0]['status'] == 'unresolved'
    assert 'payableRate' not in result['phases'][0]


def test_standalone_reference_origin_is_publicly_calculated(goldens):
    case = goldens[2]
    programme = deepcopy(case['programme'])
    programme['components'][0]['role'] = 'reference'
    result = resolve_public_rate(programme, case['scenario'], case['asOf'])
    assert result['status'] == 'exact' and result['origin'] == 'publicly_calculated'


def test_comparison_rate_requires_the_same_offer_and_met_conditions(goldens):
    case = goldens[0]
    programme = deepcopy(case['programme'])
    comparisons = [component for component in programme['components'] if component['role'] == 'comparison']
    comparisons[1]['scopeId'] = 'different-offer-identity-control'
    comparisons[0]['conditions'] = [{'conditionId': 'ineligible-purpose-control', 'field': 'purpose', 'operator': 'eq',
                                     'value': 'INVESTMENT', 'evidenceIds': comparisons[0]['evidenceIds']}]
    result = resolve_public_rate(programme, case['scenario'], case['asOf'])
    assert 'comparisonRate' not in result and 'comparison_rate_conflicting' not in result['reasonCodes']
    comparisons[0]['conditions'] = []
    result = resolve_public_rate(programme, case['scenario'], case['asOf'])
    expected = fraction_text(fraction_value(comparisons[0]['value'], comparisons[0]['unit']))[0]
    assert result['comparisonRate'] == expected


def test_legacy_source_roles_and_bounds_are_never_standalone_payable():
    raw = json.loads((FIXTURES / 'nab-tailored-cdr-20261013.json').read_bytes())['data']
    assert legacy_disposition(raw['lendingRates'][0], 'lending') == 'from'
    assert legacy_disposition(raw['lendingRates'][1], 'lending') == 'range'
    for kind in ['DISCOUNT', 'BUNDLE_DISCOUNT_VARIABLE', 'INTRODUCTORY']:
        assert legacy_disposition({'lendingRateType': kind, 'rate': '0.01'}, 'lending') == 'adjustment'
    assert legacy_disposition({'depositRateType': 'BONUS', 'rate': '0.0399'}, 'deposit') == 'adjustment'
    assert legacy_disposition({'lendingRateType': 'VARIABLE', 'rate': '0.629'}, 'lending', '0.0629') == 'unsupported'


def test_public_source_and_guard_columns_migrate_existing_history_without_reset():
    import cdr_outputs
    connection = sqlite3.connect(':memory:')
    cdr_outputs.ensure_db(connection)
    connection.execute("INSERT INTO runs VALUES ('2026-10-13', '2026-10-13T12:00:00Z', '{}')")
    connection.execute('ALTER TABLE bank_products DROP COLUMN public_pricing_source_json')
    connection.execute('ALTER TABLE bank_rates DROP COLUMN public_rate_disposition')
    cdr_outputs.ensure_db(connection)
    assert connection.execute('SELECT run_date FROM runs').fetchall() == [('2026-10-13',)]
    assert 'public_pricing_source_json' in cdr_outputs.table_column_names(connection, 'bank_products')
    assert 'public_rate_disposition' in cdr_outputs.table_column_names(connection, 'bank_rates')
    cdr_outputs.ensure_db(connection)
    assert connection.execute('SELECT count(*) FROM runs').fetchone()[0] == 1


def test_public_capture_flags_tailored_pricing_without_declared_bounds():
    raw = json.loads((FIXTURES / 'anz-term-deposit-cdr-20261014.json').read_bytes())['data']
    raw['isTailored'] = True
    result = compile_fixture('anz-term-deposit-cdr-20261014.json', 'ANZ', 'TD', raw)
    assert all('formula' not in programme for programme in result['programmes'])
    assert all('tailored_pricing_scope_unavailable' in programme['reasonCodes'] for programme in result['programmes'])


@pytest.mark.parametrize('scalar', [0.0005, 0, True])
def test_non_string_cdr_rates_require_reviewed_provider_adapters(scalar):
    raw = json.loads((FIXTURES / 'anz-term-deposit-cdr-20261014.json').read_bytes())['data']
    raw['depositRates'][1]['rate'] = scalar
    result = compile_fixture('anz-term-deposit-cdr-20261014.json', 'ANZ', 'TD', raw)
    programme = next(p for p in result['programmes'] if p['sourceBindings'][0]['rateIndex'] == 2)
    assert 'non_string_cdr_rate' in programme['reasonCodes'] and 'formula' not in programme
    assert 'value' not in programme['components'][0]


@pytest.mark.parametrize('nonconforming', ['6.84', '684'])
def test_percent_style_cdr_values_need_an_explicit_provider_unit_adapter(nonconforming):
    raw = json.loads((FIXTURES / 'nab-tailored-cdr-20261013.json').read_bytes())['data']
    raw['isTailored'] = False
    raw['lendingRates'] = [{**raw['lendingRates'][0], 'rate': nonconforming, 'additionalInfo': '', 'tiers': []}]
    result = compile_fixture('nab-tailored-cdr-20261013.json', 'NAB', 'Mortgage', raw)
    programme = result['programmes'][0]
    assert 'nonconforming_cdr_rate_unit' in programme['reasonCodes'] and 'formula' not in programme
    assert 'value' not in programme['components'][0]
    assert programme['components'][0]['source']['rawValue'] == nonconforming
    assert programme['components'][0]['unit'] == 'fraction_per_annum'
    assert legacy_disposition(raw['lendingRates'][0], 'lending', nonconforming) == 'unsupported'


def test_legacy_absolute_validation_preserves_explicit_cdr_fraction_units():
    assert legacy_disposition({'lendingRateType': 'VARIABLE', 'rate': '0.0684'}, 'lending', '0.0684') == 'absolute'
    assert legacy_disposition({'lendingRateType': 'VARIABLE', 'rate': 0.0684}, 'lending', '0.0684') == 'unsupported'


def test_unit_invalid_bonus_cannot_regain_a_formula_during_base_binding():
    raw = json.loads((FIXTURES / 'anz-progress-saver-cdr-20261014.json').read_bytes())['data']
    bonus = next(rate for rate in raw['depositRates'] if rate['depositRateType'] == 'BONUS')
    bonus['rate'] = '3.99'
    result = compile_fixture('anz-progress-saver-cdr-20261014.json', 'ANZ', 'Savings', raw)
    programme = next(p for p in result['programmes'] if any(c['role'] == 'bonus' for c in p['components']))
    assert 'nonconforming_cdr_rate_unit' in programme['reasonCodes'] and 'formula' not in programme
    assert next(c for c in programme['components'] if c['role'] == 'bonus')['source']['rawValue'] == '3.99'


def test_negative_cdr_bonus_cannot_invert_the_published_adjustment_relationship():
    raw = json.loads((FIXTURES / 'anz-progress-saver-cdr-20261014.json').read_bytes())['data']
    next(rate for rate in raw['depositRates'] if rate['depositRateType'] == 'BONUS')['rate'] = '-0.00001'
    result = compile_fixture('anz-progress-saver-cdr-20261014.json', 'ANZ', 'Savings', raw)
    programme = next(p for p in result['programmes'] if any(c['role'] == 'bonus' for c in p['components']))
    assert 'negative_cdr_adjustment' in programme['reasonCodes'] and 'formula' not in programme
    assert 'value' not in next(c for c in programme['components'] if c['role'] == 'bonus')


@pytest.mark.parametrize('material', ['Rates from the displayed interest rate', 'Minimum interest rate subject to assessment',
                                     'Maximum interest rate determined at our discretion', 'Negotiated reference rate before discounts',
                                     'Indicator rate less applicable discount', 'The rate depends on the borrower circumstances'])
def test_unfamiliar_material_pricing_prose_does_not_become_absolute(material):
    raw = json.loads((FIXTURES / 'anz-term-deposit-cdr-20261014.json').read_bytes())['data']
    raw['depositRates'][1]['additionalInfo'] = material
    result = compile_fixture('anz-term-deposit-cdr-20261014.json', 'ANZ', 'TD', raw)
    programme = next(p for p in result['programmes'] if p['sourceBindings'][0]['rateIndex'] == 2)
    assert 'uninterpreted_material_pricing' in programme['reasonCodes'] and 'formula' not in programme


def test_malformed_non_record_array_entries_cannot_shift_legacy_offer_binding():
    raw = json.loads((FIXTURES / 'anz-term-deposit-cdr-20261014.json').read_bytes())['data']
    raw['depositRates'].insert(1, None)
    result = compile_fixture('anz-term-deposit-cdr-20261014.json', 'ANZ', 'TD', raw)
    second = next(p for p in result['programmes'] if p['sourceBindings'][0]['rateIndex'] == 2)
    assert second['sourceBindings'][0]['pointer'] == '/data/depositRates/2'
    original = json.loads((FIXTURES / 'anz-term-deposit-cdr-20261014.json').read_bytes())['data']['depositRates'][1]
    assert second['components'][0]['source']['rawValue'] == original['rate']


@pytest.mark.parametrize('field,limit,nested', [
    ('lendingRates', 512, False), ('fees', 256, False), ('constraints', 64, False),
    ('eligibility', 64, False), ('tiers', 128, True), ('applicabilityConditions', 128, True),
])
def test_pathological_public_record_counts_preserve_unresolved_discovery(field, limit, nested):
    raw = json.loads((FIXTURES / 'nab-tailored-cdr-20261013.json').read_bytes())['data']
    target = raw['lendingRates'][0] if nested else raw
    retained_item = (target.get(field) or [{}])[0]
    target[field] = [retained_item] * (limit + 1)
    result = compile_fixture('nab-tailored-cdr-20261013.json', 'NAB', 'Mortgage', raw)
    assert result['product']['name'] == raw['name']
    assert result['product']['sourceEvidence']['locator'] == '/data'
    assert result['product']['reasonCodes'] == ['public_pricing_record_budget_exceeded']
    assert not result['programmes']


def test_product_fees_compile_once_for_the_actual_nab_offer_inventory(monkeypatch):
    import cdr_public_rates_cdr as compiler
    from unittest.mock import Mock
    once = Mock(wraps=compiler.compile_fees)
    monkeypatch.setattr(compiler, 'compile_fees', once)
    result = compile_fixture('nab-tailored-cdr-20261013.json', 'NAB', 'Mortgage')
    assert len(json.loads((FIXTURES / 'nab-tailored-cdr-20261013.json').read_bytes())['data']['lendingRates']) == 172
    assert len(result['programmes']) > 50
    once.assert_called_once()
    assert all(fee['scopeId'] == result['product']['productId'] for p in result['programmes'] for fee in p['fees'])


def test_material_notes_utf16_limit_preserves_unresolved_public_discovery():
    raw = json.loads((FIXTURES / 'nab-tailored-cdr-20261013.json').read_bytes())['data']
    raw['lendingRates'][0]['additionalInfo'] = '\U0001f30f' * 8193
    result = compile_fixture('nab-tailored-cdr-20261013.json', 'NAB', 'Mortgage', raw)
    assert result['product']['reasonCodes'] == ['public_pricing_record_budget_exceeded']
    assert result['product']['sourceEvidence']['locator'] == '/data' and not result['programmes']


def test_compiled_byte_ceiling_blocks_product_fee_amplification_before_storage():
    """Real source with enlarged fee text is a resource fault, not pricing acceptance."""
    raw = json.loads((FIXTURES / 'nab-tailored-cdr-20261013.json').read_bytes())['data']
    original_fee = raw['fees'][0]
    raw['fees'] = [{**original_fee, 'name': original_fee['name'] + str(index) + 'x' * 900,
                   'additionalInfo': 'subject to ' + 'x' * 3900} for index in range(128)]
    assert len(json.dumps(raw).encode('utf-8')) < 16 * 1024 * 1024
    result = compile_fixture('nab-tailored-cdr-20261013.json', 'NAB', 'Mortgage', raw)
    assert result['product']['reasonCodes'] == ['public_pricing_compiled_product_budget_exceeded']
    assert not result['programmes'] and result['product']['sourceEvidence']['locator'] == '/data'


def test_nested_oversized_source_values_fail_before_semantic_offer_grouping():
    raw = json.loads((FIXTURES / 'nab-tailored-cdr-20261013.json').read_bytes())['data']
    raw['fees'][0]['fixedAmount'] = {'amount': 'x' * 65536}
    result = compile_fixture('nab-tailored-cdr-20261013.json', 'NAB', 'Mortgage', raw)
    assert result['product']['reasonCodes'] == ['public_pricing_record_budget_exceeded']
    assert not result['programmes']
