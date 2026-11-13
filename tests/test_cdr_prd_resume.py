"""Unavailable-PRD resume guards retain real cached evidence without false claims."""
from collections import defaultdict
import json
from pathlib import Path

import pytest

import cdr_ingest_lib as ingest
import cdr_outputs as outputs
from cdr_clean_export import app_coverage_aliases, coverage_summary, parse_banks_run
from cdr_ingest_support import allocate_bank_dir


def retained_products():
    path = Path(__file__).parent / 'fixtures/ingest-capture-20261015/westpac-prior-page1.json'
    products = json.loads(path.read_bytes())['data']['products']
    return [row for row in products if row['productCategory'] == 'TRANS_AND_SAVINGS_ACCOUNTS'][:2]


def raw_detail(run, provider, record):
    path = run / 'banks/Savings' / provider / record['productId'] / 'product-detail.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'data': record}), encoding='utf-8')
    return path


def test_partial_resume_keeps_cached_product_but_not_attempts_or_withdrawals(tmp_path, monkeypatch):
    # Routing/availability metadata varies; both business records are retained
    # Westpac source records. A differing display name tests canonical-dir use.
    brand_name = 'Westpac / Banking'
    provider = allocate_bank_dir(brand_name, 'Westpac', 'https://digital-api.westpac.com.au', set())
    assert provider != brand_name
    previous, current = tmp_path / '2026-10-14', tmp_path / '2026-10-15'
    records = retained_products()
    assert len(records) == 2
    for record in records:
        raw_detail(previous, provider, record)
    cached = raw_detail(current, provider, records[0])
    before = cached.read_bytes()
    status = {'provider_states': [{'provider_uid': 'routing-control', 'provider_dir': provider,
        'brand_name': brand_name, 'state': 'not_attempted', 'population_known': False,
        'prd_availability': 'UNAVAILABLE'}]}
    (current / 'banks/ingest-status.json').write_text(json.dumps(status), encoding='utf-8')
    (current / 'banks/failures.jsonl').write_bytes(b'')

    def forbidden(*args, **kwargs):
        pytest.fail('unavailable resume must not request provider HTTP data')

    monkeypatch.setattr(ingest, 'fetch_cdr_json', forbidden)
    ingest.ingest_brand({'brand_name': brand_name, 'endpoint_url': '', 'prd_availability': 'UNAVAILABLE'},
        date_root=current / 'banks', resume=True, sleep_ms=0, timeout=1, max_retries=0,
        max_pages=None, max_products=None, fetch_unknown_detail=True,
        bank_dir_name=provider, detail_workers=1, log=lambda _: None)
    parsed = parse_banks_run(current)
    assert cached.read_bytes() == before
    assert parsed['failures'] == parsed['holder_attempts'] == []
    assert [row['product_id'] for row in parsed['products']] == [records[0]['productId']]
    assert parsed['prd_unavailable'][0]['provider_dir'] == provider
    assert parsed['prd_unavailable'][0]['population_known'] is False
    coverage = coverage_summary(parsed, current.name)
    assert coverage['counts']['brands_observed'] == 1
    assert coverage['counts']['providers_registered'] == coverage['counts']['providers_prd_unavailable'] == 1
    for name in ('providers_attempted', 'providers_succeeded'):
        assert coverage['counts'][name] == coverage[name] == 0
    assert coverage['counts']['providers_failed'] == coverage['counts']['providers_partial'] == 0

    previous_facts = parse_banks_run(previous)['product_facts']
    grouped = defaultdict(list)
    for row in previous_facts:
        grouped[(row['provider'], row['product_id'], row['dataset'])].append(row)
    monkeypatch.setattr(outputs, 'iter_run_fact_groups', lambda _: iter(grouped.items()))
    outputs.build_outputs(current, previous_run_root=previous)
    exported = json.loads((current / '_exports' / f'banks-{current.name}.json').read_bytes())
    assert exported['product_changes'] == exported['failures'] == []
    assert exported['product_change_summary']['suppressed_incomplete_products'] == 1
    assert exported['product_change_summary']['suppression_reasons'] == {'provider_prd_unavailable': 1}
    assert cached.read_bytes() == before


def test_cached_failure_does_not_readd_unavailable_provider_to_attempt_counts():
    banks = {'products': [{'provider': 'Retained_dir'}, {'provider': 'Available'}],
        'rates': [], 'holder_attempts': ['Retained_dir', 'Available'],
        'failures': [{'bank': 'Retained_dir', 'phase': 'product_detail', 'status': 503}],
        'prd_unavailable': [{'provider_dir': 'Retained_dir', 'brand_name': 'Different display',
                             'population_known': False, 'prd_availability': 'UNAVAILABLE'}]}
    coverage = coverage_summary(banks, '2026-10-15')
    assert coverage['counts']['providers_registered'] == 2
    assert coverage['counts']['providers_attempted'] == coverage['providers_attempted'] == 1
    assert coverage['counts']['providers_succeeded'] == coverage['providers_succeeded'] == 1
    assert coverage['counts']['providers_failed'] == coverage['counts']['providers_partial'] == 0
    assert coverage['counts']['failure_records'] == 1  # Retained evidence is not erased.


@pytest.mark.parametrize('explicit', [False, True])
def test_aliases_preserve_explicit_zero_but_keep_legacy_fallback(explicit):
    counts = {'brands_observed': 4}
    if explicit:
        counts.update(providers_attempted=0, providers_succeeded=0)
    result = app_coverage_aliases({'counts': counts})
    assert result['providers_attempted'] == result['providers_succeeded'] == (0 if explicit else 4)


@pytest.mark.parametrize('unavailable', [False, True])
def test_flat_and_grouped_guards_keep_normal_removal_when_provider_available(unavailable):
    from tests.test_cdr_product_change_coverage import westpac_groups
    previous = westpac_groups()
    current = previous[1][1]
    options = {'current_providers': ['Westpac'], 'unavailable_providers': ['Westpac'] if unavailable else []}
    groups, counters = outputs._exclude_failed_missing_product_groups(iter(previous), current, [], **options)
    retained_groups = list(groups)
    flat, count = outputs._exclude_failed_missing_products(
        [row for _, rows in previous for row in rows], current, [], **options)
    assert counters['suppressed'] == count == int(unavailable)
    assert len(retained_groups) == (1 if unavailable else 2)
    assert flat == [row for _, rows in retained_groups for row in rows]
