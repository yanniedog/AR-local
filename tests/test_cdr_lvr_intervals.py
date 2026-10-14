"""Replay public NAB CDR through the producer; mutate only bound protocols."""
from __future__ import annotations

import copy
import gzip
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from app_payload_common import CORE_RATE_FIELDS, compact
from cdr_lvr import interval_tier
from cdr_outputs import build_outputs
from cdr_ribbon_normalize import resolve_lvr_tier

FIXTURE = Path(__file__).parent / 'fixtures' / 'nab_tailored_public_2026-10-14.json.gz'


@pytest.fixture
def raw():
    return json.loads(gzip.decompress(FIXTURE.read_bytes()))['data']


def high_rate(raw):
    return copy.deepcopy(next(rate for rate in raw['lendingRates'] if
        rate['lendingRateType'] == 'VARIABLE' and rate['loanPurpose'] == 'OWNER_OCCUPIED' and
        rate['repaymentType'] == 'PRINCIPAL_AND_INTEREST' and rate['tiers'][0]['minimumValue'] == '0.8001'))


def test_public_nab_open_tier_uses_real_product_limit(raw):
    rate = high_rate(raw)
    assert rate['tiers'][0]['name'] == 'LVR 80.01% or more'
    assert 'maximumValue' not in rate['tiers'][0]
    assert next(c for c in raw['constraints'] if c['constraintType'] == 'MAX_LVR')['additionalValue'] == '0.95'
    assert resolve_lvr_tier(raw['name'], rate, raw['constraints']) == ('lvr_>=80.01-95%', 'rate_structured')


@pytest.mark.parametrize(('lo', 'hi', 'expected'), [
    (0, .6, 'lvr_=60%'), (.6001, .7, 'lvr_60-70%'), (.7001, .8, 'lvr_70-80%'),
    (.8001, .85, 'lvr_80-85%'), (.8501, .9, 'lvr_85-90%'), (.9001, .95, 'lvr_90-95%'),
    (.8001, None, 'lvr_>=80.01%'), (.8001, .95, 'lvr_>=80.01-95%'),
    (.8001, .9, 'lvr_>=80.01-90%'), (.8001, .92, 'lvr_>=80.01-92%'),
    (.8, .95, 'lvr_>=80-95%'), (None, .95, 'lvr_=95%'), (None, None, 'lvr_unspecified'),
    (.95, .9, 'lvr_unspecified'), (.95, .95, 'lvr_>=95-95%'),
    (True, .95, 'lvr_unspecified'), (.8, float('nan'), 'lvr_unspecified'),
])
def test_bound_protocols_preserve_intervals_and_do_not_invent_maximums(lo, hi, expected):
    assert interval_tier(lo, hi) == expected


@pytest.mark.parametrize(('rate_max', 'product_max', 'expected'), [
    (None, .95, 'lvr_>=80.01-95%'), (None, .9, 'lvr_>=80.01-90%'),
    (.85, .95, 'lvr_80-85%'), (.9, .95, 'lvr_>=80.01-90%'),
    (.95, .92, 'lvr_>=80.01-92%'), (None, None, 'lvr_>=80.01%'),
])
def test_rate_and_product_bounds_intersect_without_widening(raw, rate_max, product_max, expected):
    rate = high_rate(raw)
    if rate_max is not None:
        rate['tiers'][0]['maximumValue'] = str(rate_max)
    constraints = [] if product_max is None else [{'constraintType': 'MAX_LVR', 'additionalValue': str(product_max)}]
    assert resolve_lvr_tier('', rate, constraints)[0] == expected


def test_multiple_constraints_and_tier_limits_use_the_tightest_cap(raw):
    rate = high_rate(raw)
    caps = [{'constraintType': 'MAX_LVR', 'additionalValue': value} for value in ('0.9', '95')]
    assert resolve_lvr_tier('', rate, caps)[0] == 'lvr_>=80.01-90%'
    assert resolve_lvr_tier('', rate, list(reversed(caps)))[0] == 'lvr_>=80.01-90%'
    caps.append({'constraintType': 'OTHER', 'additionalInfo': 'LVR', 'additionalValue': '.95'})
    assert resolve_lvr_tier('', rate, caps)[0] == 'lvr_>=80.01-90%'
    rate['constraints'] = [{'constraintType': 'MAX_LVR', 'additionalValue': '0.85'}]
    assert resolve_lvr_tier('', rate, caps)[0] == 'lvr_80-85%'


@pytest.mark.parametrize('name', ['LVR', 'LTV', 'Loan to value', 'LVR80', 'LVR_80'])
def test_shared_lender_tier_names_use_the_same_generic_conversion(raw, name):
    rate = high_rate(raw)
    rate['tiers'][0]['name'] = name
    assert resolve_lvr_tier('', rate, raw['constraints'])[0] == 'lvr_>=80.01-95%'


@pytest.mark.parametrize(('context', 'expected'), [
    ('LVR 80.01% or more', 'lvr_>=80.01-95%'), ('over 80% LVR', 'lvr_>80-95%'),
    ('LTV at least 80', 'lvr_>=80-95%'), ('loan to value 80.01% or more', 'lvr_>=80.01-95%'),
    ('LVR 70-80%', 'lvr_70-80%'), ('CLASSIC HOME LOAN VARIABLE <60 LVR IO', 'lvr_=60%'),
])
def test_named_lower_bounds_survive_product_caps(context, expected, raw):
    assert resolve_lvr_tier(context, {}, raw['constraints'])[0] == expected


def test_stricter_structured_product_minimum_is_inclusive():
    constraints = [{'constraintType': 'MIN_LVR', 'additionalValue': '.8325'},
                   {'constraintType': 'MAX_LVR', 'additionalValue': '.95'}]
    assert resolve_lvr_tier('over 80% LVR', {}, constraints)[0] == 'lvr_>=83.25-95%'


@pytest.mark.parametrize('maximum', [None, ''])
def test_empty_optional_maximum_is_not_zero_or_a_new_cap(raw, maximum):
    rate = high_rate(raw)
    rate['tiers'][0]['maximumValue'] = maximum
    assert resolve_lvr_tier('', rate, raw['constraints'])[0] == 'lvr_>=80.01-95%'


@pytest.mark.parametrize(('name', 'minimum', 'maximum', 'expected'), [
    ('LVR 80.01% or more', None, '.95', 'lvr_>=80.01-95%'),
    ('over 80% LVR', None, '.95', 'lvr_>80-95%'),
    ('LVR 80.01-90%', '.8001', None, 'lvr_>=80.01-90%'),
    ('LVR 80.01% - 90%', '.8001', None, 'lvr_>=80.01-90%'),
    ('80.01% or more LVR', None, '.95', 'lvr_>=80.01-95%'),
])
def test_missing_numeric_bounds_can_use_named_evidence_without_widening(raw, name, minimum, maximum, expected):
    rate = high_rate(raw)
    rate['tiers'][0].update(name=name, minimumValue=minimum, maximumValue=maximum)
    assert resolve_lvr_tier('', rate, raw['constraints'])[0] == expected


@pytest.mark.parametrize('bad', [True, 'NaN', 'Infinity', '-0.1', '200'])
def test_malformed_explicit_maximum_fails_closed(raw, bad):
    rate = high_rate(raw)
    rate['tiers'][0]['maximumValue'] = bad
    assert resolve_lvr_tier('', rate, raw['constraints'])[0] == 'lvr_unspecified'


def test_unrelated_percentages_and_absent_lvr_remain_unknown():
    assert resolve_lvr_tier('Basic Home Loan', {'additionalInfo': 'Rate 5.99%, redraw up to $20000'}, []) == ('lvr_unspecified', 'none')
    assert resolve_lvr_tier('Bridging Loan', {}, [])[0] == 'lvr_unspecified'


def test_captured_raw_product_flows_through_json_sqlite_and_compact_app_contract(tmp_path, raw):
    run = tmp_path / '2026-10-14'
    path = run / 'banks' / 'Mortgage' / 'NAB' / raw['productId'] / 'product-detail.json'
    path.parent.mkdir(parents=True)
    source = json.dumps({'data': raw}).encode()
    path.write_bytes(source)
    result = build_outputs(run)
    banks = json.loads((run / '_exports' / 'dashboard-cache' / run.name / 'banks.json').read_bytes())
    assert len(banks['rates']) == len(raw['lendingRates']) == 172
    assert path.read_bytes() == source
    highs = [r for r in banks['rates'] if r['rate_type'] == 'VARIABLE' and r['loan_purpose'] == 'OWNER_OCCUPIED'
             and r['repayment_type'] == 'PRINCIPAL_AND_INTEREST' and r['lvr_tier'] == 'lvr_>=80.01-95%']
    assert len(highs) == 2
    assert all(r['taxonomy_path'].endswith('LVR_GE80p01_95') for r in highs)
    for row in highs:
        assert compact({key: row.get(key) for key in CORE_RATE_FIELDS})['lvr_tier'] == 'lvr_>=80.01-95%'
    projected = [compact({key: row.get(key) for key in CORE_RATE_FIELDS}) for row in banks['rates']
                 if row['rate_type'] == 'VARIABLE' and row['loan_purpose'] == 'OWNER_OCCUPIED'
                 and row['repayment_type'] == 'PRINCIPAL_AND_INTEREST']
    contract = json.loads((FIXTURE.parent / 'nab_lvr_app_contract_2026-10-14.json').read_bytes())
    assert projected == contract['rates']
    with sqlite3.connect(run / '_exports' / 'local-cdr.sqlite') as connection:
        assert connection.execute("SELECT COUNT(*) FROM bank_rates WHERE lvr_tier='lvr_>=80.01-95%'").fetchone()[0] > 0
    assert result


def test_dashboard_fallback_matches_producer_for_captured_nab_rates(raw):
    node = shutil.which('node')
    assert node, 'Node is a repository verification prerequisite'
    expected = [resolve_lvr_tier(raw['name'], rate, raw['constraints'])[0] for rate in raw['lendingRates']]
    script = """
const fs=require('node:fs'), vm=require('node:vm');
const raw=JSON.parse(fs.readFileSync(0,'utf8')); const window={};
vm.runInNewContext(fs.readFileSync('dashboard/cdr-ribbon-map.js','utf8'),{window});
const rows=raw.lendingRates.map(item=>({provider:raw.brand,product_name:raw.name,
  details_json:JSON.stringify({...item,productLvrConstraints:raw.constraints})}));
process.stdout.write(JSON.stringify(window.LocalCdrRibbonMap.toRibbonProducts(rows,'Mortgage').map(x=>x.row.lvr_tier)));
"""
    completed = subprocess.run([node, '-e', script], input=json.dumps(raw), text=True,
                               capture_output=True, check=True, timeout=20)
    assert json.loads(completed.stdout) == expected
