"""Malformed input and retained-table tamper boundaries, not business fixtures."""
import gzip
import json
from pathlib import Path

import pytest

import cdr_product_report as report
import cdr_public_history_audit as history


@pytest.mark.parametrize('dates', [
    ['2026-09-13', '2026-09-13'], ['2026-09-14', '2026-09-13'],
    ['2026-02-30'], ['2026-9-1'], [], '2026-09-13', [None],
])
def test_report_refuses_ambiguous_or_invalid_calendar_index(tmp_path, dates):
    (tmp_path / 'dates-index.json').write_text(json.dumps({'dates': dates}))
    with pytest.raises(ValueError):
        report.date_coverage(tmp_path, {'run_date': '2026-09-14'})


@pytest.mark.parametrize('manifest', [[], None, {'files': []}, {'files': {'core': None}},
    {'run_date': '2026-09-14', 'files': []},
    {'run_date': '2026-09-14', 'files': {'core': []}},
])
def test_malformed_manifest_is_a_per_date_failure(tmp_path, monkeypatch, manifest):
    monkeypatch.setattr(history, 'fetch', lambda *_: json.dumps(manifest).encode())
    result, rows = history.audit_date('2026-09-14', None, tmp_path)
    assert result['status'] == 'FAIL' and rows == []
    assert result['reason'] == 'ValueError'


@pytest.mark.parametrize('core', [[], None, {'run_date':'2026-09-14','sections':[]},
    {'run_date':'2026-09-14','sections':{key:[] for key in ('Mortgage','Savings','TD')}},
    {'run_date':'2026-09-14','sections':{key:{'rates':[None]} for key in ('Mortgage','Savings','TD')}},
])
def test_malformed_core_does_not_abort_other_dates(tmp_path, monkeypatch, core):
    body = gzip.compress(json.dumps(core).encode())
    manifest = {'run_date':'2026-09-14', 'files':{'core':{
        'bytes':len(body), 'sha256':history.sha(body), 'url':'https://example.test/core'}}}
    calls = iter([json.dumps(manifest).encode(), body])
    monkeypatch.setattr(history, 'fetch', lambda *_: next(calls))
    result, rows = history.audit_date('2026-09-14', None, tmp_path)
    assert result['status'] == 'FAIL' and rows == []
    assert result['reason'] == 'ValueError'


def audit_source(tmp_path, *, sealed=True):
    source, output = tmp_path / 'audit', tmp_path / 'output'
    source.mkdir(); output.mkdir()
    rows = [{'provider':'protocol-fixture', 'run_date':'2026-09-14',
             'product_key':'protocol-only', 'rate_rows':0}]
    report.write_csv(source / 'bank-product-dates.csv', rows)
    report.write_csv(source / 'dates.csv', [{'run_date':'2026-09-14', 'status':'PASS'}])
    summary = {'index_sha256':'pinned', 'results':[{'run_date':'2026-09-14'}]}
    if sealed:
        summary['exports'] = {name:{'bytes':(source/name).stat().st_size,
            'sha256':report.digest((source/name).read_bytes())}
            for name in ('bank-product-dates.csv','dates.csv')}
    (source/'summary.json').write_text(json.dumps(summary))
    instance = {'historical_coverage':{'index_sha256':'pinned','dates':['2026-09-14']}, 'export_row_counts':{}}
    return source, output, instance


@pytest.mark.parametrize('name', ['bank-product-dates.csv','dates.csv'])
def test_history_table_tamper_refused_before_report_mutation(tmp_path, name):
    source, output, instance = audit_source(tmp_path)
    (source/name).write_bytes((source/name).read_bytes().replace(b'2026-09-14', b'2026-09-13'))
    with pytest.raises(ValueError, match='audit export'):
        report.attach_history(instance, source, output)
    assert 'historical_banks' not in instance and list(output.iterdir()) == []


def test_unsealed_legacy_audit_is_not_silently_resealed(tmp_path):
    source, output, instance = audit_source(tmp_path, sealed=False)
    with pytest.raises(ValueError, match='audit export'):
        report.attach_history(instance, source, output)
    assert 'historical_banks' not in instance and list(output.iterdir()) == []


def test_sealed_history_uses_the_verified_snapshot(tmp_path):
    source, output, instance = audit_source(tmp_path)
    report.attach_history(instance, source, output)
    assert instance['historical_banks'][0]['rate_row_observations'] == 0
    assert (output/'historical-products.csv').read_bytes() == (source/'bank-product-dates.csv').read_bytes()
