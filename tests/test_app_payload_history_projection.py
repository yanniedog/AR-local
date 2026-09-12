"""Actual eight-day retained-source regression; faults affect test copies only."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from app_payload_history_projection import digest, project_standard_history_rows
from app_payload_v2 import _moves, _standard_best_for_day, build_product_history

FIXTURE = Path(__file__).parent / 'fixtures/bankwest_history_real_2026-09-06_to_13.json'
KEY = 'Bankwest|d10438974ab8417bab388149da5053bb|TRANS_AND_SAVINGS_ACCOUNTS|Bankwest Easy Saver'


@pytest.fixture
def days():
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '79a2e923685ea9a7f021dc9a1572986c13edbf8c23e9e0eabec1cdc0db73c941'
    result = {}
    for item in json.loads(raw)['observations']:
        assert item['stat_unchanged'] and item['full_database_hash_rechecked'] is False
        products = item['queries']['bank_products']['rows']
        assert len(products) == 1 and products[0]['product_key'] == KEY
        # SQLite stores category on the parent product; banks.json stores this
        # exact same retained field on both product and rate. No price is made up.
        rates = [{'category': products[0]['category'], **row}
                 for row in item['queries']['bank_rates']['rows']]
        result[item['date']] = {'products': products, 'rates': rates}
    return result


def build(tmp_path, days):
    roots, original = {}, {}
    for day, banks in days.items():
        root = tmp_path / 'runs' / day / '_exports'
        path = root / 'dashboard-cache' / day / 'banks.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(banks), encoding='utf-8')
        roots[day], original[path] = root, path.read_bytes()
    payload = build_product_history(roots[max(days)], run_date=max(days))
    assert all(path.read_bytes() == raw for path, raw in original.items())
    return payload


def test_real_eight_day_projection_removes_false_650bp_move_without_rewriting_history(tmp_path, days):
    before = copy.deepcopy(days)
    legacy = [next(iter(_standard_best_for_day(banks['rates'])[0].values())) for banks in days.values()]
    assert legacy == [0.115] * 7 + [0.05]
    assert _moves(legacy, list(days)) == [
        {'date': '2026-09-13', 'from_rate': 0.115, 'to_rate': 0.05, 'bps': -650.0}]
    history = build(tmp_path, days)
    assert history['products'][KEY] == [0.05] * 8
    assert history['moves'].get(KEY, []) == []
    assert all(point['max'] == 0.05 for point in history['section_aggregates']['Savings']['points'])
    assert days == before
    changes = history['classification_projection']['records']
    assert len(changes) == 7 and {row['date'] for row in changes} == set(days) - {'2026-09-13'}
    for record in changes:
        assert record['action'] == 'exclude_winner_rate'
        assert record['source_rates'][0]['index'] == 5
        assert all(len(record[field]) == 64 for field in ('row_sha256', 'details_sha256'))
        assert len(record['source_rates'][0]['sha256']) == 64


def test_current_source_prices_and_existing_classification_are_unchanged(days):
    banks = days['2026-09-13']
    before = copy.deepcopy(banks)
    rows, report = project_standard_history_rows(banks, '2026-09-13')
    assert rows == banks['rates'] and report['changes'] == []
    assert len(report['restricted_products']) == 1 and report['unknown'] == {}
    assert banks == before


def test_a_day_with_only_the_prize_is_a_gap_not_an_ordinary_zero(tmp_path, days):
    days['2026-09-09']['rates'] = [row for row in days['2026-09-09']['rates'] if row['rate'] == '0.115']
    history = build(tmp_path, days)
    assert history['products'][KEY] == [0.05, 0.05, 0.05, None, 0.05, 0.05, 0.05, 0.05]
    assert history['moves'].get(KEY, []) == []


@pytest.mark.parametrize('fault', ['missing', 'bad_json', 'wrong_product', 'duplicate_product', 'wrong_index', 'unmatched_price'])
def test_unverifiable_day_of_restricted_product_is_a_gap(tmp_path, days, fault):
    day = days['2026-09-08']
    if fault == 'missing':
        day['products'] = []
    elif fault == 'bad_json':
        day['products'][0]['details_json'] = '{'
    elif fault == 'wrong_product':
        raw = json.loads(day['products'][0]['details_json'])
        raw['productId'] = 'different-product'
        day['products'][0]['details_json'] = json.dumps(raw)
    elif fault == 'duplicate_product':
        other = copy.deepcopy(day['products'][0])
        other['details_json'] = '{}'
        day['products'].append(other)
    else:
        prize = next(row for row in day['rates'] if row['rate'] == '0.115')
        if fault == 'wrong_index':
            prize['rate_index'] = 4  # Deliberately broken retained identity, not source acceptance data.
        else:
            prize['rate_type'] = 'VARIABLE'
    history = build(tmp_path, days)
    assert history['products'][KEY][2] is None
    assert history['moves'].get(KEY, []) == []
    records = history['classification_projection']['records']
    assert any(row['action'] == 'hold_unresolved_product_day' and row['date'] == '2026-09-08' for row in records)


def test_same_price_ordinary_and_prize_candidates_require_unambiguous_mapping(days):
    banks = days['2026-09-06']
    raw = json.loads(banks['products'][0]['details_json'])
    # Fault injection: same exported fields but contradictory eligibility. This
    # checks matcher rejection only; it does not claim a second real source tier.
    ambiguous = copy.deepcopy(raw['depositRates'][4])
    ambiguous.pop('additionalInfo', None)
    for tier in ambiguous.get('tiers', []):
        tier.pop('applicabilityConditions', None)
    raw['depositRates'].append(ambiguous)
    banks['products'][0]['details_json'] = json.dumps(raw)
    _, report = project_standard_history_rows(banks, '2026-09-06')
    assert any(row['reason'] == 'retained_rate_mapping_unresolved' for row in report['unknown'].values())


def test_retained_matching_array_position_does_not_select_ordinary_sibling(days):
    banks = days['2026-09-06']
    for index, row in enumerate(banks['rates'], 1):
        row['rate_index'] = index
    rows, report = project_standard_history_rows(banks, '2026-09-06')
    assert next(row for row in rows if row['rate'] == '0.115')['account_class'] == 'non_standard'
    assert next(row for row in rows if row['rate'] == '0.05')['account_class'] == 'standard'
    assert report['unknown'] == {}


@pytest.mark.parametrize('retain_unmatched_export', [True, False])
def test_no_winner_source_day_requires_matching_ordinary_rows(tmp_path, days, retain_unmatched_export):
    day = days['2026-09-08']
    raw = json.loads(day['products'][0]['details_json'])
    # Fault/control copies: remove only the real prize source item. A matching
    # ordinary day remains valid; a leftover prize export cannot borrow proof.
    raw['depositRates'].pop(4)
    day['products'][0]['details_json'] = json.dumps(raw)
    prize = next(row for row in day['rates'] if row['rate'] == '0.115')
    if not retain_unmatched_export:
        day['rates'].remove(prize)
    history = build(tmp_path, days)
    assert history['products'][KEY][2] == (None if retain_unmatched_export else 0.05)
    assert history['moves'].get(KEY, []) == []
    holds = [record for record in history['classification_projection']['records']
             if record['action'] == 'hold_unresolved_product_day']
    if retain_unmatched_export:
        assert len(holds) == 1 and holds[0]['date'] == '2026-09-08'
        assert holds[0]['unresolved_rows'] == [{'row_sha256': digest(prize),
            'reason': 'retained_rate_mapping_unresolved', 'details_sha256': digest(raw)}]
    else:
        assert holds == []
