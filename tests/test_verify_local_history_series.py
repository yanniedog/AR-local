"""Actual HTTP body admission for the Pi's lossless history smoke path."""
import json
from pathlib import Path

import pytest

import verify_local
import tests.test_verify_local_compact_response as fixtures
from tests.test_verify_local_compact_response import transport as http_transport
from cdr_dashboard_history_transport import encode, validate


@pytest.fixture
def series(http_transport, monkeypatch):
    original = fixtures.responses

    def responses(section, **kwargs):
        result = original(section, **kwargs)
        result['section']['rates'].append({**result['section']['rates'][0], 'product_key': 'fixture-2'})
        result['section']['counts']['rates'] = len(result['section']['rates'])
        for index, row in enumerate(result['section']['rates']):
            row['rate_index'] = index
        result['series'] = json.loads(encode({
            'run_dates': [fixtures.DAY], 'section': section, 'carry_forward_count': 0,
            'rates': [{**{k:v for k,v in row.items() if k != 'rate_index'},
                       'run_date': fixtures.DAY, 'comparison_rate': '0.0301'}
                      for row in result['section']['rates']]}))
        return result

    monkeypatch.setattr(fixtures, 'responses', responses)
    return http_transport


def smoke(series):
    return verify_local.main(['--base-url='+series['base'], '--history-mode=series',
                              '--expect-run-date='+fixtures.DAY, '--require-banks-rates'])


def test_three_complete_series_bodies_pass(series, capsys):
    assert smoke(series) == 0
    assert series['paths'].count('/api/banks/history/section/series') == 3
    assert 'history=series' in capsys.readouterr().out
    package=json.loads((Path(__file__).resolve().parents[1]/'package.json').read_bytes())
    assert '--history-mode=series' in package['scripts']['verify:pi']


def test_extra_carried_current_row_is_fatal_even_with_consistent_counts(series):
    def mutate(payload):
        if '1' not in payload['values']:
            payload['values'].append('1')
        carried_id = payload['values'].index('1')
        template_id, day_id, _ = payload['observations'][0]
        payload['observations'].append([template_id, day_id, carried_id])
        payload['row_count'] += 1
        payload['carry_forward_count'] += 1
        validate(payload, payload['section'], fixtures.DAY)
        return payload
    series['changes']['series'] = mutate
    assert smoke(series) == 1


@pytest.mark.parametrize('mutation', [lambda p:b'{', lambda p:{},
    lambda p:{**p, 'row_count':0}, lambda p:{**p, 'section':'wrong'},
    lambda p:{**p, 'run_dates':['2000-01-01']}, lambda p:{**p, 'carry_forward_count':1}])
def test_http200_incomplete_or_mismatched_series_is_fatal(series, mutation, capsys):
    series['changes']['series'] = mutation
    assert smoke(series) == 1
    assert '/series' in capsys.readouterr().err


@pytest.mark.parametrize('kind', ['omit', 'duplicate', 'changed_value'])
def test_self_consistent_series_must_match_every_current_row(series, kind):
    def mutate(payload):
        if kind == 'omit':
            payload['observations'].pop()
            payload['row_count'] -= 1
        elif kind == 'duplicate':
            payload['observations'][1] = payload['observations'][0].copy()
        else:
            payload['values'][payload['values'].index('fixture-2')] = 'wrong-product'
        return payload
    series['changes']['series'] = mutate
    assert smoke(series) == 1


def test_wrong_current_envelope_cannot_prove_history(series):
    series['changes']['section'] = lambda p: {**p, 'section': 'wrong'}
    assert smoke(series) == 1


def test_history_only_field_projection_matches_actual_server_contract():
    from cdr_dashboard_server import BANK_SECTION_COLUMNS, BANK_HISTORY_COLUMNS
    assert set(BANK_HISTORY_COLUMNS) - set(BANK_SECTION_COLUMNS) == {
        'run_date', 'dataset', 'rate_family', 'comparison_rate'}
    assert set(BANK_SECTION_COLUMNS) - set(BANK_HISTORY_COLUMNS) == {'rate_index'}
