"""Real captured rows: legacy list oracle versus disk-backed export pipeline."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import zipfile
import pytest

import cdr_clean_export
import cdr_outputs as outputs
from cdr_product_changes import _index, _product_key, _fact_key, diff_normalized_product_fact_groups
from cdr_product_change_stream import diff_current_store
from cdr_replay_rows import ReplayStore
from tests.test_cdr_sqlite_streaming import database_rows


def real_run(parent):
    root = parent / '2026-05-19'
    captured = json.loads((Path(__file__).parent / 'fixtures/product_facts_real_2026-05-19.json').read_bytes())
    for product in captured['products']:
        path = root / 'banks' / product['dataset'] / product['provider'] / product['record']['productId'] / 'product-detail.json'
        path.parent.mkdir(parents=True)
        path.write_bytes(json.dumps({'data': product['record']}, ensure_ascii=False).encode())
    return root


@pytest.mark.parametrize('with_previous', [False, True])
def test_every_export_matches_legacy_list_oracle_and_sources_remain_unchanged(tmp_path, monkeypatch, with_previous):
    monkeypatch.setattr(cdr_clean_export, 'utc_now', lambda: '2026-05-19T00:00:00Z')
    monkeypatch.setattr(outputs, 'utc_now', lambda: '2026-05-19T00:00:00Z')
    run = real_run(tmp_path); original = {p: p.read_bytes() for p in run.rglob('*') if p.is_file()}
    banks = outputs.parse_banks_run(run); grouped = _index(banks['product_facts'])
    previous = list(grouped.items())[:-1]  # Real prior subset; technical product-addition scenario.
    prior_path = tmp_path / '2026-05-18' if with_previous else None
    if with_previous:
        monkeypatch.setattr(outputs, 'iter_run_fact_groups', lambda _: iter(previous))
        report = diff_normalized_product_fact_groups(iter(previous), banks['product_facts'],
                    previous_run_date='2026-05-18', current_run_date=run.name)
    else:
        report = dict(schema_version=1, normalization_version=outputs.NORMALIZATION_VERSION,
            previous_run_date=None, run_date=run.name, change_count=0,
            products=dict(previous=0, current=len(banks['products']), joined=0), events=[])
    banks['product_changes'] = outputs.product_change_rows(report)
    banks['product_change_summary'] = {key: report[key] for key in (
        'schema_version', 'normalization_version', 'previous_run_date', 'run_date', 'change_count', 'products')}
    banks['product_change_summary'].update(suppressed_incomplete_products=0, suppression_reasons={})
    expected = tmp_path / 'reference'; expected.mkdir()
    with (expected / f'banks-{run.name}.json').open('w', encoding='utf-8') as stream:
        json.dump(banks, stream, ensure_ascii=False, indent=2)
    outputs.write_sector_workbooks(expected, run.name, banks)
    outputs.rebuild_run_db(expected / 'local-cdr.sqlite', run.name, banks)
    outputs.write_dashboard_cache(expected, run.name, banks)
    actual = tmp_path / 'actual'; custom = tmp_path / 'custom.sqlite'
    result = outputs.build_outputs(run, actual, custom, previous_run_root=prior_path)
    assert (actual / f'banks-{run.name}.json').read_bytes() == (expected / f'banks-{run.name}.json').read_bytes()
    assert result['banks'] == outputs.summary_counts(banks)
    assert database_rows(actual / 'local-cdr.sqlite') == database_rows(expected / 'local-cdr.sqlite') == database_rows(custom)
    with zipfile.ZipFile(actual / f'banks-{run.name}.xlsx') as a, zipfile.ZipFile(expected / f'banks-{run.name}.xlsx') as b:
        assert a.namelist() == b.namelist()
        assert {name: a.read(name) for name in a.namelist()} == {name: b.read(name) for name in b.namelist()}
    for path in (expected / 'dashboard-cache').rglob('*.json'):
        assert path.read_bytes() == (actual / path.relative_to(expected)).read_bytes()
    assert {p: p.read_bytes() for p in original} == original
    assert not list(tmp_path.glob('.cdr-facts-*'))


def test_stream_diff_matches_unchanged_pure_oracle_for_real_fact_mutation_controls(tmp_path):
    rows = outputs.parse_banks_run(real_run(tmp_path))['product_facts']
    old = deepcopy(rows); current = deepcopy(rows)
    # Technical controls deliberately exercise missing/new facts and metadata;
    # financial values remain the captured values, not fabricated acceptance data.
    old.pop(0); current.pop(-1)
    current[0]['product_name'] = current[0]['product_name'].upper()
    key = _product_key(current[0])
    for row in current:
        if _product_key(row) == key: row['product_name'] = current[0]['product_name']
    groups = list(_index(old).items())
    expected = diff_normalized_product_fact_groups(iter(groups), current,
                    previous_run_date='2026-05-18', current_run_date='2026-05-19')
    with ReplayStore(tmp_path, key_of=_product_key, validate_fact=_fact_key) as spool:
        spool.facts.extend(current); spool.facts.seal()
        report = diff_current_store(iter(groups), spool, previous_run_date='2026-05-18', current_run_date='2026-05-19',
            convert=lambda event: outputs.product_change_rows(dict(events=[event], run_date='2026-05-19', previous_run_date='2026-05-18'))[0])
        assert list(spool.changes) == outputs.product_change_rows(expected)
        assert report == {k: v for k, v in expected.items() if k not in ('events', 'changes')}


def test_fact_replay_does_not_mask_authoritative_duplicate_failure_or_rollback(tmp_path, monkeypatch):
    banks = outputs.parse_banks_run(real_run(tmp_path)); target = tmp_path / 'prior.sqlite'
    monkeypatch.setattr(outputs, 'utc_now', lambda: 'fixed')
    outputs.rebuild_run_db(target, '2026-05-19', banks); before = database_rows(target)
    with ReplayStore(tmp_path, key_of=_product_key, validate_fact=_fact_key) as spool:
        spool.facts.extend(banks['product_facts']); spool.facts.append(banks['product_facts'][0]); spool.facts.seal()
        assert len(spool.facts) == len(banks['product_facts'])+1
        with pytest.raises(sqlite3.IntegrityError): outputs.rebuild_run_db(target, '2026-05-19', {**banks, 'product_facts': spool.facts})
    assert database_rows(target) == before


def test_presence_suppression_retains_raw_field_semantics_separate_from_diff_identity(tmp_path):
    from tests.test_cdr_replay_rows import fact
    current = [{**fact(), 'provider': ' Bank ', 'product_id': ' ID '},
               {**fact(), 'provider': 'bank', 'productId': 'alias', 'product_id': ''}]
    # Second row's diff alias resolves, but suppression intentionally sees the
    # exact canonical raw field used by the existing implementation.
    groups = [(('Bank', 'ID', 'Savings'), [current[0]]), (('bank', 'missing', 'Savings'), [current[0]])]
    failures = [{'bank': 'bank', 'phase': 'products_index'}]
    expected_groups, expected_summary = outputs._exclude_failed_missing_product_groups(iter(groups), current, failures)
    expected_groups = list(expected_groups)
    with ReplayStore(tmp_path, key_of=_product_key, validate_fact=_fact_key) as spool:
        spool.facts.extend(current); spool.facts.seal()
        actual_groups, actual_summary = outputs._exclude_failed_missing_product_groups(iter(groups), spool.facts, failures)
        assert list(actual_groups) == expected_groups and actual_summary == expected_summary
        assert set(spool.facts.product_presence()) == {(' bank ', ' ID ', 'Savings'), ('bank', '', 'Savings')}
