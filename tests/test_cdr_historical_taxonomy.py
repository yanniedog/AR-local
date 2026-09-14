"""Retained-source examples plus explicit adversarial copies; no live sources."""
import copy
import gzip
import json
from pathlib import Path

import pytest

import cdr_historical_taxonomy as repair
import cdr_historical_taxonomy_rules as rules

FIXTURE = Path(__file__).parent / 'fixtures' / 'historical-taxonomy-may13'


@pytest.fixture
def cases():
    return {case['label']: case for case in json.loads(gzip.decompress((FIXTURE / 'cases.json.gz').read_bytes()))}


def classify(case):
    return rules.classify(json.loads(case['product']['details_json']), case['source_rate']['rate_family'],
                          case['source_rate']['rate_index'] - 1)


def corpus(cases):
    products = {case['product']['product_key']: case['product'] for case in cases.values()}
    source = {'run_date': repair.OBSERVATION_DATE, 'products': list(products.values()),
              'rates': [case['source_rate'] for case in cases.values()]}
    core = {'run_date': repair.OBSERVATION_DATE, 'schema_version': 1,
            'sections': {section: {'rates': [case['public_row'] for case in cases.values()
                         if case['public_section'] == section]} for section in ('Mortgage', 'Savings', 'TD')}}
    details = {'run_date': repair.OBSERVATION_DATE, 'schema_version': 1,
               'products': {case['product']['product_key']: case['public_detail'] for case in cases.values()}}
    return copy.deepcopy((source, core, details))


def test_fixture_bytes_and_exact_parent_record_hashes(cases):
    provenance = json.loads((FIXTURE / 'provenance.json').read_bytes())
    body = (FIXTURE / 'cases.json.gz').read_bytes()
    assert repair.sha(body) == provenance['fixture_sha256']
    assert len(body) == provenance['fixture_bytes']
    assert provenance['source_export_sha256'] == repair.SOURCE_SHA
    assert provenance['public_core_sha256'] == repair.ASSET_SHA['core.json.gz']
    for case in cases.values():
        for name in ('product', 'source_rate', 'public_row'):
            assert rules.digest(case[name]) == case[f'{name}_sha256']


@pytest.mark.parametrize(('label', 'expected'), [
    ('amp_variable', 'HOME_LOAN.OO.PI.VARIABLE.LVR_LE60'),
    ('amp_fixed', 'HOME_LOAN.OO.PI.FIXED.12M.LVR_85_90'),
    ('bank_australia_holdout', 'HOME_LOAN.OO.PI.VARIABLE.LVR_LE60'),
    ('bank_first_holdout', 'HOME_LOAN.INV.IO.FIXED.12M.LVR_70_80'),
    ('td_maturity', 'TERM_DEPOSIT.1M.AT_MATURITY.TIERED'),
])
def test_retained_supported_patterns_and_cross_bank_holdouts(cases, label, expected):
    result = classify(cases[label])
    assert result['taxonomy_path'] == expected
    assert result['unresolved_reasons'] == []
    raw = json.loads(cases[label]['product']['details_json'])
    for dimension in result['dimensions']:
        for evidence in dimension['evidence']:
            selected = raw
            for component in evidence['pointer'].strip('/').split('/'):
                selected = selected[int(component)] if isinstance(selected, list) else selected[component]
            assert repair.exact(selected, evidence['value'])
            assert rules.digest(selected) == evidence['value_sha256']


@pytest.mark.parametrize(('label', 'reason'), [
    ('td_conflicting_period', 'term_or_payment_conflicts_with_tier_text'),
    ('savings_farm_range', 'savings_account_kind_and_component_semantics_unreviewed'),
    ('td_month_range', 'term_range_day_unit_or_conflicting_bounds'),
])
def test_real_ambiguous_terms_do_not_become_exact_paths(cases, label, reason):
    result = classify(cases[label])
    assert result['taxonomy_path'] is None
    assert reason in result['unresolved_reasons']


@pytest.mark.parametrize('field', ['loanPurpose', 'repaymentType', 'lendingRateType'])
def test_no_enum_defaults_despite_name_or_existing_ribbon(cases, field):
    raw = json.loads(cases['amp_variable']['product']['details_json'])
    del raw['lendingRates'][0][field]
    assert rules.classify(raw, 'lending', 0)['taxonomy_path'] is None


def test_zero_lvr_lower_bound_is_evidence_not_absence(cases):
    result = classify(cases['amp_variable'])
    lvr = next(item for item in result['dimensions'] if item['dimension'] == 'lvr_upper_boundary_bucket')
    assert lvr['minimum_percent'] == '0'
    assert lvr['maximum_percent'] == '50'
    assert lvr['numeric_scale_corroborated_by_text'] == '100'


@pytest.mark.parametrize('value', [True, None, '', 'NaN', 'Infinity', '-1', '50'])
def test_lvr_invalid_or_conflicting_numeric_bound_refuses_path(cases, value):
    raw = json.loads(cases['amp_variable']['product']['details_json'])
    raw['lendingRates'][0]['tiers'][1]['minimumValue'] = value
    assert rules.classify(raw, 'lending', 0)['taxonomy_path'] is None


def test_plain_percent_tier_is_not_a_scale_guess(cases):
    raw = json.loads(cases['amp_variable']['product']['details_json'])
    raw['lendingRates'][0]['tiers'][1]['name'] = 'LVR'
    assert rules.classify(raw, 'lending', 0)['taxonomy_path'] is None


def test_lvr_material_exception_text_is_not_ignored(cases):
    raw = json.loads(cases['amp_variable']['product']['details_json'])
    raw['lendingRates'][0]['additionalInfo'] = 'For government backed loans maximum LVR may differ.'
    result = rules.classify(raw, 'lending', 0)
    assert result['taxonomy_path'] is None
    assert 'mortgage_additional_info_requires_review' in result['unresolved_reasons']


@pytest.mark.parametrize('value', [None, '', 'P0M', 'P1D', 'P1.5Y', '12', True])
def test_no_term_fallback_from_rate_payment_or_legacy_twelve_months(cases, value):
    raw = json.loads(cases['td_maturity']['product']['details_json'])
    raw['depositRates'][0]['additionalValue'] = value
    assert rules.classify(raw, 'deposit', 0)['taxonomy_path'] is None


def test_maturity_does_not_mean_monthly_merely_because_frequency_is_monthly(cases):
    assert classify(cases['td_maturity'])['taxonomy_path'] == 'TERM_DEPOSIT.1M.AT_MATURITY.TIERED'


@pytest.mark.parametrize('index', [22, 23])
def test_retained_thirteen_month_tier_payment_exception_is_unresolved(cases, index):
    raw = json.loads(cases['td_maturity']['product']['details_json'])
    rate = raw['depositRates'][index]
    clause = rate['tiers'][0]['applicabilityConditions'][0]
    assert rate['additionalValue'] == 'P13M' and rate['applicationType'] == 'MATURITY'
    assert clause['rateApplicabilityType'] == 'OTHER'
    assert 'the first interest payment is made after 12 months' in clause['additionalInfo']
    result = rules.classify(raw, 'deposit', index)
    assert result['taxonomy_path'] is None
    assert 'rate_or_tier_applicability_requires_review' in result['unresolved_reasons']
    proof = next(d for d in result['dimensions'] if d['dimension'] == 'unreviewed_applicability_context')
    assert proof['value'] == 'UNKNOWN'
    assert proof['evidence'][0]['pointer'] == f'/depositRates/{index}/tiers/0/applicabilityConditions/0'
    assert proof['evidence'][0]['value_sha256'] == rules.digest(clause)


@pytest.mark.parametrize('location', ['rate', 'tier'])
def test_payment_exception_at_either_level_cannot_be_ignored(cases, location):
    raw = json.loads(cases['td_maturity']['product']['details_json'])
    clause = raw['depositRates'][22]['tiers'][0]['applicabilityConditions'][0]
    target = raw['depositRates'][0] if location == 'rate' else raw['depositRates'][0]['tiers'][0]
    target['applicabilityConditions'] = [copy.deepcopy(clause)]
    assert rules.classify(raw, 'deposit', 0)['taxonomy_path'] is None


def test_only_exact_retained_new_accounts_context_is_reviewed(cases):
    raw = json.loads(cases['amp_variable']['product']['details_json'])
    result = rules.classify(raw, 'lending', 0)
    assert result['taxonomy_path'] == 'HOME_LOAN.OO.PI.VARIABLE.LVR_LE60'
    proof = next(d for d in result['dimensions'] if d['dimension'] == 'reviewed_applicability_context')
    assert proof['value'] == 'NEW_ACCOUNTS_CONTEXT_ONLY'
    raw['lendingRates'][0]['applicabilityConditions'][0]['additionalValue'] = 'unreviewed extra condition'
    assert rules.classify(raw, 'lending', 0)['taxonomy_path'] is None


@pytest.mark.parametrize('conditions', [None, False, {}, ['NEW_ACCOUNTS'], [{'rateApplicabilityType': 'NEW_ACCOUNTS'}]])
def test_unknown_applicability_shape_or_abbreviated_context_does_not_pass(cases, conditions):
    raw = json.loads(cases['amp_variable']['product']['details_json'])
    raw['lendingRates'][0]['applicabilityConditions'] = conditions
    assert rules.classify(raw, 'lending', 0)['taxonomy_path'] is None


def test_missing_tier_does_not_become_flat(cases):
    raw = json.loads(cases['td_maturity']['product']['details_json'])
    del raw['depositRates'][0]['tiers']
    assert rules.classify(raw, 'deposit', 0)['taxonomy_path'] is None


def test_transform_preserves_prices_details_rows_order_and_existing_normalization_examples(cases):
    source, core, details = corpus(cases)
    originals = copy.deepcopy((source, core, details))
    candidate, rows, summary = repair.transform(source, core, details)
    assert repair.verify_invariants(core, candidate) == 5
    assert repair.exact((source, core, details), originals)
    assert len(rows) == len(cases)
    assert summary['existing_rate_transformations_preserved'] == 2
    bos = next(row for row in rows if row['product_key'] == cases['normalized_bos_rate']['product']['product_key'])
    assert bos['published_rate_preserved'] == '0.0649'
    assert bos['embedded_rate_value'] == '0.00649'
    assert [row['status'] for row in rows].count('ADDED') == 5


@pytest.mark.parametrize('mutation', ['remove', 'duplicate', 'price', 'product_key', 'bool_index'])
def test_source_membership_and_value_tamper_rejected(cases, mutation):
    source, core, details = corpus(cases)
    if mutation == 'remove':
        source['rates'].pop(0)
    elif mutation == 'duplicate':
        source['rates'].append(copy.deepcopy(source['rates'][0]))
    elif mutation == 'price':
        core['sections']['Mortgage']['rates'][0]['rate'] = '0.06340001'
    elif mutation == 'product_key':
        core['sections']['Mortgage']['rates'][0]['product_key'] += '|wrong'
    else:
        core['sections']['Mortgage']['rates'][0]['rate_index'] = True
    with pytest.raises(ValueError):
        repair.transform(source, core, details)


@pytest.mark.parametrize('mutation', ['reorder', 'remove', 'price', 'new_field', 'false_to_zero'])
def test_non_taxonomy_invariant_guard_is_independent_of_classifier(cases, mutation):
    _, core, _ = corpus(cases)
    candidate = copy.deepcopy(core)
    rates = candidate['sections']['Mortgage']['rates']
    if mutation == 'reorder':
        rates.reverse()
    elif mutation == 'remove':
        rates.pop()
    elif mutation == 'price':
        rates[0]['rate'] = '9'
    elif mutation == 'new_field':
        rates[0]['new'] = None
    else:
        core['sections']['Mortgage']['rates'][0]['flag'] = False
        rates[0]['flag'] = 0
    with pytest.raises(ValueError):
        repair.verify_invariants(core, candidate)


def test_existing_taxonomy_including_null_and_blank_remains_unchanged(cases):
    source, core, details = corpus(cases)
    for row, value in zip(core['sections']['Mortgage']['rates'], [None, '', 'EXISTING']):
        row['taxonomy_path'] = value
    candidate, rows, _ = repair.transform(source, core, details)
    assert [row['status'] for row in rows[:3]] == ['EXISTING_TAXONOMY_PRESERVED'] * 3
    assert [row['taxonomy_path'] for row in candidate['sections']['Mortgage']['rates'][:3]] == [None, '', 'EXISTING']


def test_original_input_hash_is_mandatory_before_any_output(tmp_path):
    source = tmp_path / 'source' / 'banks.json'
    source.parent.mkdir()
    source.write_text('{}')
    output = tmp_path / 'candidate'
    with pytest.raises(ValueError, match='input hash mismatch'):
        repair.prepare(source, tmp_path / 'released', output)
    assert not output.exists()


@pytest.mark.parametrize('body', [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'])
def test_ambiguous_json_is_rejected(body):
    with pytest.raises(ValueError):
        repair.decode(body)


def test_decoder_bound_applies_to_gzip_expansion(monkeypatch):
    monkeypatch.setattr(repair, 'SOURCE_LIMIT', 10)
    with pytest.raises(ValueError, match='exceeds byte bound'):
        repair.decode(gzip.compress(b' ' * 100), compressed=True)
