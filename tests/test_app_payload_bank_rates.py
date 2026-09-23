from copy import deepcopy
import json
from app_payload_bank_rates import embed_bank_rate_history
from app_payload_bank_rates import attach_history


def row(rate, **extra):
    return dict(provider='Alpha', product_key='a', product_name='Loan', rate=rate, rate_type='VARIABLE', **extra)


def core(rows):
    return {'run_date': '2026-09-22', 'sections': {
        section: {'rates': rows if section == 'Mortgage' else []}
        for section in ('Mortgage', 'Savings', 'TD')}}


def test_exact_tiers_rle_zero_missing_dates_and_duplicates():
    current = core([row('0.06'), row('0.07')])
    observed = [('2026-09-19', {'Mortgage': [row('0'), row('0.02'), row('0.9', account_class='non_standard')]}),
                ('2026-09-20', {'Mortgage': [row('0'), row('0.02')]}),
                ('2026-09-22', {'Mortgage': [row('0.06'), row('0.07')]})]
    attach_history(current, observed, ['2026-09-19', '2026-09-20', '2026-09-21', '2026-09-22'])
    assert current['bank_rate_history']['row_tiers']['Mortgage'] == [0, 0]
    assert all('bank_rate_tier' not in r for r in current['sections']['Mortgage']['rates'])
    assert current['bank_rate_history']['sections']['Mortgage'] == [[[0, 2, [0.0, 2.0]], [3, 1, [6.0, 7.000000000000001]]]]


def test_changed_attributes_break_membership_and_sections_stay_separate():
    current = core([row('0.06')])
    current['sections']['Savings']['rates'] = [row('0.03')]
    attach_history(current, [('2026-09-21', {'Mortgage': [row('0.99', product_id='other')], 'Savings': [row('3')]})], ['2026-09-21', '2026-09-22'])
    assert current['bank_rate_history']['sections']['Mortgage'] == [[]]
    assert current['bank_rate_history']['sections']['Savings'] == [[[0, 1, [3.0]]]]


def test_observation_metadata_is_not_tier_identity_and_output_is_deterministic():
    first = core([row('0.06', last_updated='today', rate_index=9)])
    second = deepcopy(first)
    days = [('2026-09-21', {'Mortgage': [row('0.05', last_updated='yesterday', rate_index=1)]})]
    for value in (first, second):
        attach_history(value, days, ['2026-09-21', '2026-09-22'])
    assert first == second
    assert first['bank_rate_history']['sections']['Mortgage'] == [[[0, 1, [5.0]]]]


def test_export_packaging_keeps_missing_days_and_rejects_other_rate_families(tmp_path):
    current = core([row('0.06')])
    for day in ('2026-09-20', '2026-09-22'):
        folder = tmp_path / 'dashboard-cache' / day
        folder.mkdir(parents=True)
        rates = [dict(row('0.05'), dataset='Mortgage', rate_family='lending'),
                 dict(row('0.99'), dataset='Mortgage', rate_family='deposit')]
        (folder / 'banks.json').write_text(json.dumps({'rates': rates}))
    embed_bank_rate_history(current, tmp_path)
    assert current['bank_rate_history']['run_dates'] == ['2026-09-20', '2026-09-21', '2026-09-22']
    assert current['bank_rate_history']['sections']['Mortgage'] == [[[0, 1, [5.0]], [2, 1, [5.0]]]]
