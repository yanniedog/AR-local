"""Retained CDR detail acceptance and protocol controls for comparable facts."""
from copy import deepcopy
from pathlib import Path
import json

from app_payload_criteria import criteria_facts, decimal_text
from app_payload_details import build_details
from app_payload_feature_facts import feature_facts
from cdr_clean_export import detail_json


FIXTURE = Path(__file__).parent / 'fixtures/product_facts_real_2026-05-19.json'


def captured():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))['products']


def test_retained_up_eligibility_constraints_and_rates_reach_common_fact_model():
    record = captured()[0]['record']
    product = {'product_key': 'up-home', 'details_json': detail_json(record)}
    detail = build_details([product], include_criteria=True)['up-home']
    kinds = {fact['kind'] for fact in detail['facts']}
    assert {'feature', 'eligibility', 'constraint', 'rate'} <= kinds
    assert any(fact['sourceType'] == 'MAX_LVR' and fact['unit'] == 'fraction'
               and fact['valueType'] == 'decimal' for fact in detail['facts'])
    rates = [fact for fact in detail['facts'] if fact['kind'] == 'rate']
    assert rates and all(fact['evidenceState'] in {'conditional', 'unknown'} for fact in rates)
    assert any(fact.get('value') == '0.057' for fact in rates)
    # Keep the existing conservative feature semantics exactly; a new detail
    # channel cannot grant previously unverified feature eligibility.
    cleaned = json.loads(product['details_json'])
    assert [fact for fact in detail['facts'] if fact['kind'] == 'feature'] == feature_facts(cleaned, 'up-home')


def test_retained_fee_and_tier_products_are_no_longer_empty_fact_arrays():
    fee, tiered = [item['record'] for item in captured()[1:]]
    fees = criteria_facts(json.loads(detail_json(fee)), 'basic-access')
    assert any(fact['kind'] == 'fee' for fact in fees)
    tiers = criteria_facts(json.loads(detail_json(tiered)), 'basic-home')
    assert any(fact['kind'] == 'tier' and ('minValue' in fact or 'maxValue' in fact) for fact in tiers)
    assert all(fact.get('parentId') for fact in tiers if fact['kind'] == 'tier')


def test_source_pointer_is_preserved_across_real_record_compaction():
    raw = deepcopy(captured()[0]['record'])
    # Empty-entry fault control; financial values and source declarations unchanged.
    raw['constraints'].insert(0, {})
    cleaned = json.loads(detail_json(raw))
    facts = criteria_facts(cleaned, 'up-home')
    original = raw['constraints'][1]['constraintType']
    fact = next(item for item in facts if item['kind'] == 'constraint' and item['sourceType'] == original)
    assert fact['sourcePath'] == '/constraints/1'
    assert fact['sourcePathBasis'] == 'raw-cdr'
    del cleaned['_sourcePaths']
    legacy = next(item for item in criteria_facts(cleaned, 'up-home')
                  if item['kind'] == 'constraint' and item['sourceType'] == original)
    assert legacy['sourcePath'] == '/constraints/0'
    assert legacy['sourcePathBasis'] == 'cleaned-cdr'


def test_missing_bound_never_becomes_boolean_eligible():
    raw = deepcopy(captured()[0]['record'])
    constraint = raw['constraints'][0]
    constraint.pop('additionalValue', None)
    fact = next(item for item in criteria_facts(raw, 'up-home')
                if item['kind'] == 'constraint' and item['sourceType'] == constraint['constraintType'])
    assert 'value' not in fact
    assert fact['evidenceState'] == 'unknown'


def test_external_qualification_and_effective_dates_never_become_unconditional_filters():
    raw = deepcopy(captured()[0]['record'])
    code = raw['constraints'][0]['constraintType']
    # URI-only protocol qualification leaves every retained financial value intact.
    raw['constraints'][0]['additionalInfoUri'] = 'https://up.com.au/docs/Up-Home-Loan-Booklet.pdf'
    cleaned = json.loads(detail_json(raw))
    fact = next(item for item in criteria_facts(cleaned, 'up-home')
                if item['kind'] == 'constraint' and item['sourceType'] == code)
    assert fact['evidenceState'] == 'conditional'
    raw['effectiveFrom'] = '2099-01-01T00:00:00Z'  # Future-boundary protocol control.
    dated = criteria_facts(json.loads(detail_json(raw)), 'up-home')
    assert all(item['evidenceState'] != 'observed' for item in dated)
    assert all(item['effectiveFrom'] == raw['effectiveFrom'] for item in dated)


def test_retained_arab_bank_uri_only_constraint_stays_conditional():
    payload = json.loads((FIXTURE.parent / 'arab-bank-constraint-doc-real-20260519.json').read_bytes())
    raw = payload.get('data', payload)
    assert raw['constraints'][0]['additionalValue'] == '50000.00'
    fact = next(item for item in criteria_facts(json.loads(detail_json(raw)), 'arab-bank-real')
                if item['canonicalKey'] == 'constraint.min_limit')
    assert fact['value'] == '50000.00' and fact['unit'] == 'AUD'
    assert fact['evidenceState'] == 'conditional'
    assert fact['sourcePath'] == '/constraints/0'


def test_retained_amp_additional_value_is_not_invented_loan_term():
    payload = json.loads((FIXTURE.parent / 'amp-rate-scope-real-20260519.json').read_bytes())
    raw = payload.get('data', payload)
    facts = criteria_facts(json.loads(detail_json(raw)), 'amp-real')
    loc = next(item for item in facts if str(item.get('value', '')).strip() == 'Line of Credit')
    assert loc['canonicalKey'].endswith('.additional_value')
    assert loc['unit'] == loc['valueType'] == 'text'
    assert loc['evidenceState'] == 'conditional'


def test_retained_macquarie_minimum_income_is_money_with_source_qualification():
    payload = json.loads((FIXTURE.parent / 'macquarie-income-real-20260519.json').read_bytes())
    raw = payload.get('data', payload)
    fact = next(item for item in criteria_facts(json.loads(detail_json(raw)), 'macquarie-real')
                if item['canonicalKey'] == 'eligibility.min_income')
    assert fact['value'] == '50000.00'
    assert fact['unit'] == 'AUD' and fact['valueType'] == 'decimal'
    assert fact['evidenceState'] == 'conditional'
    assert fact['sourcePath'] == '/eligibility/0'
    assert 'per annum' in fact['condition']


def test_exact_decimal_conversion_and_invalid_protocol_values():
    assert decimal_text('9007199254740993.000000000001') == '9007199254740993.000000000001'
    assert decimal_text('5.70000000000000000001', 100) == '0.0570000000000000000001'
    for value in (True, 'NaN', 'Infinity', '1e999999', '', 'not-a-number'):
        assert decimal_text(value) is None


def test_fact_ids_survive_entity_reordering_without_losing_occurrences():
    raw = deepcopy(captured()[0]['record'])
    before = criteria_facts(json.loads(detail_json(raw)), 'up-home')
    raw['constraints'].reverse()
    after = criteria_facts(json.loads(detail_json(raw)), 'up-home')
    assert {fact['id'] for fact in before} == {fact['id'] for fact in after}
    raw['constraints'].append(deepcopy(raw['constraints'][0]))
    duplicated = criteria_facts(json.loads(detail_json(raw)), 'up-home')
    assert len({fact['id'] for fact in duplicated}) == len(duplicated)
    assert {fact['id'] for fact in before} <= {fact['id'] for fact in duplicated}
