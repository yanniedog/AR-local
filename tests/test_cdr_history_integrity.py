"""Malformed input and retained-table tamper boundaries, not business fixtures."""
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

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
    summary = {'index_sha256':'pinned', 'dates_passed':1,
               'results':[{'run_date':'2026-09-14', 'status':'PASS'}]}
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


def test_cached_asset_size_is_refused_before_open(tmp_path, monkeypatch):
    path = tmp_path / 'oversized'
    path.write_bytes(b'x' * 65)
    monkeypatch.setattr(Path, 'open', lambda *_a, **_k: pytest.fail('oversized cache was opened'))
    with pytest.raises(ValueError, match='cached asset exceeds byte limit'):
        history.read_cached(path, 64)


def test_cached_asset_growth_is_still_a_bounded_read(tmp_path, monkeypatch):
    path = tmp_path / 'changed-after-stat'
    path.write_bytes(b'x' * 128)
    original_open, reads = Path.open, []

    class TrackedReader:
        def __enter__(self):
            self.handle = original_open(path, 'rb')
            return self

        def read(self, size=-1):
            reads.append(size)
            return self.handle.read(size)

        def __exit__(self, *_):
            self.handle.close()

    monkeypatch.setattr(Path, 'stat', lambda *_a, **_k: SimpleNamespace(st_size=1))
    monkeypatch.setattr(Path, 'open', lambda *_a, **_k: TrackedReader())
    with pytest.raises(ValueError, match='cached asset exceeds byte limit'):
        history.read_cached(path, 64)
    assert reads == [65]


def test_cached_asset_exact_limit_is_preserved(tmp_path):
    path = tmp_path / 'bounded'
    path.write_bytes(b'x' * 64)
    assert history.read_cached(path, 64) == b'x' * 64


@pytest.mark.parametrize('status', ['FAIL', 'PARTIAL', None])
def test_failed_selected_date_cannot_authorize_partial_history_totals(tmp_path, monkeypatch, status):
    import copy
    import cdr_history_validation
    source, output, instance = audit_source(tmp_path)
    before = copy.deepcopy(instance)
    summary = json.loads((source / 'summary.json').read_text())
    summary['results'][0]['status'] = status
    summary['dates_passed'] = 0
    (source / 'summary.json').write_text(json.dumps(summary))
    monkeypatch.setattr(cdr_history_validation, 'verified_exports',
                        lambda *_: pytest.fail('failed audit was used to read tables'))
    with pytest.raises(ValueError, match='failed selected dates'):
        report.attach_history(instance, source, output)
    assert instance == before and list(output.iterdir()) == []


def test_late_details_failure_leaves_report_and_outputs_unchanged(tmp_path, monkeypatch):
    import copy
    import cdr_historical_parameters
    source, output, instance = audit_source(tmp_path)
    before = copy.deepcopy(instance)
    sentinel = output / 'existing-current-table.csv'
    sentinel.write_bytes(b'preserve current output')
    summary = json.loads((source / 'summary.json').read_text())
    summary['assets_checked_per_date'] = ['core', 'details']
    (source / 'summary.json').write_text(json.dumps(summary))

    def fails_after_streaming_row(*_):
        yield {'source': 'protocol-only-before-later-hash-failure'}
        raise ValueError('retained detail hash mismatch')

    monkeypatch.setattr(cdr_historical_parameters, 'rows', fails_after_streaming_row)
    with pytest.raises(ValueError, match='retained detail hash mismatch'):
        report.attach_history(instance, source, output)
    assert instance == before
    assert list(output.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b'preserve current output'
    assert sorted(path.name for path in tmp_path.iterdir()) == ['audit', 'output']


@pytest.mark.parametrize('failure_at', [1, 2, 3, 4])
def test_link_admission_reports_incomplete_output_and_safe_retry(tmp_path, monkeypatch, failure_at):
    import copy
    source, output, instance = audit_source(tmp_path)
    before = copy.deepcopy(instance)
    source_bytes = {p.name: p.read_bytes() for p in source.iterdir()}
    link, admitted = report.os.link, []

    def fails_once(path, destination):
        if len(admitted) + 1 == failure_at:
            # A replaced earlier destination is never removed during failure handling.
            if admitted:
                admitted[0].unlink()
                admitted[0].write_bytes(b'preserve replacement')
            raise OSError('injected link failure')
        link(path, destination)
        admitted.append(destination)

    monkeypatch.setattr(report.os, 'link', fails_once)
    with pytest.raises(OSError, match='retry with a new output directory') as error:
        report.attach_history(instance, source, output)
    assert isinstance(error.value.__cause__, OSError)
    assert f'{failure_at - 1} files linked' in str(error.value)
    assert instance == before
    assert {p.name: p.read_bytes() for p in source.iterdir()} == source_bytes
    assert set(output.iterdir()) == set(admitted)
    if admitted:
        assert admitted[0].read_bytes() == b'preserve replacement'
    preserved = {p.name: p.read_bytes() for p in output.iterdir()}
    monkeypatch.setattr(report.os, 'link', link)
    fresh = tmp_path / 'retry-output'
    fresh.mkdir()
    report.attach_history(instance, source, fresh)
    assert 'historical_banks' in instance
    assert {p.name: p.read_bytes() for p in output.iterdir()} == preserved
