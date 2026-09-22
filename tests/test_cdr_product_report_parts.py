"""Complete multipart report controls; protocol fixtures do not grant bank acceptance."""
import csv
import gzip
import json
import re

import pytest

import cdr_product_report_parts as report
import cdr_report_parts_io as report_io
from cdr_report_parts_html import document
from cdr_report_terms import encoded, sha
from cdr_report_terms_parts import export_parts
from tests.test_cdr_report_terms import evidence, bundle


def prepared(tmp_path, evidence, *, null_detail=False):
    source = bundle(tmp_path, evidence)
    manifest = json.loads((source / 'manifest.json').read_bytes())
    key = evidence[2]
    changes = {
        'core': {'run_date': manifest['run_date'], 'sections': {'Savings': {'rates': [
            {'product_key': key, 'provider': '=BANK()', 'product_name': '</script><script>bad()</script>',
             'rate': 0, 'unknown': None, 'false': False, 'empty': '', 'tier': {'minimum': 0}}]}},
             'coverage': {'provider_failures': []}},
        'details': {'run_date': manifest['run_date'], 'products': {key: {'fees': [], 'empty': {}, 'zero': 0,
                    'unknown': None, 'false': False, 'negative': -0.5}, 'unreported-product': None if null_detail else {}}},
        'bank_history': {'run_date': manifest['run_date'], 'values': [0, None, False, -1.25], 'empty': []}}
    for kind, value in changes.items():
        name = kind + '.json.gz'
        raw = gzip.compress(encoded(value))
        (source / name).write_bytes(raw)
        manifest['files'][kind] = {'name': name, 'bytes': len(raw), 'sha256': sha(raw), 'url': 'https://example.test/' + name}
    (source / 'manifest.json').write_bytes(encoded(manifest))
    terms = tmp_path / 'terms'
    export_parts(source, evidence[0].root, terms)
    return source, terms, changes


def read_csv(path):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def test_all_fields_formats_metadata_and_unknowns_preserved(tmp_path, evidence):
    source, terms, original = prepared(tmp_path, evidence)
    output = tmp_path / 'report'
    receipt = report.generate(source, terms, output)
    assert receipt['products'] == 2 and receipt['rate_rows'] == 1
    report.verify_report(output, receipt)
    part = json.loads(gzip.decompress((output / 'part-0001/product-data.json.gz').read_bytes()))
    body = (output / 'part-0001/report.html').read_text(encoding='utf-8')
    embedded = json.loads(re.search(r'id="data">(.*?)</script>', body, re.S).group(1))
    assert embedded == part
    key = evidence[2]
    product = part['products'][key]
    assert product['detail'] == original['details']['products'][key]
    assert product['terms_evidence']['bank_approved'] is None
    assert product['summary']['document_capture'] == 'reported'
    assert part['products']['unreported-product']['terms_evidence']['status'] == 'unavailable'
    rate = json.loads(read_csv(output / 'part-0001/rates.csv')[0]['record_json'])
    assert rate == product['rates'][0]
    assert rate == {'section': 'Savings', 'published_row_index': 0, **original['core']['sections']['Savings']['rates'][0]}
    parameters = {r['source_pointer']: json.loads(r['value_json']) for r in read_csv(output / 'part-0001/parameters.csv.gz') if r['product_key'] == key}
    assert parameters == dict(report.leaves(product['detail']))
    terms_csv = {r['product_key']: json.loads(r['evidence_json']) for r in read_csv(output / 'part-0001/terms.csv.gz')}
    assert terms_csv == {k: r['terms_evidence'] for k, r in part['products'].items()}
    rows = json.loads(gzip.decompress((output / 'metadata/part-0001.json.gz').read_bytes()))
    key_of = lambda row: (row['asset'], row['source_pointer'])
    assert sorted(rows, key=key_of) == sorted(report.metadata_rows(original), key=key_of)
    assert not any(r['source_pointer'] == '/sections/Savings' for r in rows)
    assert {(r['source_pointer'], encoded(r['value'])) for r in rows if r['asset'] == 'bank_history'} == {
        ('/run_date', b'"2026-09-07"'), ('/values/0', b'0'), ('/values/1', b'null'),
        ('/values/2', b'false'), ('/values/3', b'-1.25'), ('/empty', b'[]')}
    csv_rows = read_csv(output / 'metadata/part-0001.csv.gz')
    assert [{'asset': r['asset'], 'source_pointer': r['source_pointer'], 'value': json.loads(r['value_json'])} for r in csv_rows] == rows
    assert read_csv(output / 'part-0001/products.csv')[0]['provider'] == "'=BANK()"
    assert '</script><script>bad()' not in body
    assert receipt['bank_approval'] is None and receipt['financial_acceptance'] == 'unverified'


@pytest.mark.parametrize('kind', ['file', 'aggregate', 'late', 'corrupt'])
def test_refusal_leaves_no_partial_report(tmp_path, evidence, monkeypatch, kind):
    source, terms, _ = prepared(tmp_path, evidence)
    if kind == 'file':
        monkeypatch.setattr(report_io, 'MAX_FILE', 100)
    elif kind == 'aggregate':
        monkeypatch.setattr(report_io, 'MAX_OUTPUT', 100)
    elif kind == 'late':
        monkeypatch.setattr(report, 'verify_report', lambda *_: (_ for _ in ()).throw(ValueError('late verification')))
    else:
        (terms / 'part-0001/evidence.json').write_bytes(b'{}')
    with pytest.raises(ValueError):
        report.generate(source, terms, tmp_path / 'report')
    assert not (tmp_path / 'report').exists()
    assert not list(tmp_path.glob('.combined-report-*'))


def test_existing_output_and_overlapping_inputs_remain_intact(tmp_path, evidence):
    source, terms, _ = prepared(tmp_path, evidence)
    output = tmp_path / 'report'
    output.mkdir()
    (output / 'keep').write_text('keep')
    for destination in (output, source, source / 'nested', terms, tmp_path):
        with pytest.raises(ValueError):
            report.generate(source, terms, destination)
    assert (output / 'keep').read_text() == 'keep'


def test_expanded_input_aggregate_refuses_before_admission(tmp_path, evidence, monkeypatch):
    source, terms, _ = prepared(tmp_path, evidence)
    monkeypatch.setattr(report_io, 'MAX_PLAIN', 10)
    with pytest.raises(ValueError, match='expanded'):
        report.generate(source, terms, tmp_path / 'report')
    assert not (tmp_path / 'report').exists()


def test_source_asset_escape_is_refused(tmp_path, evidence):
    source, terms, _ = prepared(tmp_path, evidence)
    manifest = json.loads((source / 'manifest.json').read_bytes())
    manifest['files']['core']['name'] = '../escape.json'
    (source / 'manifest.json').write_bytes(encoded(manifest))
    with pytest.raises(ValueError, match='Unsafe'):
        report.generate(source, terms, tmp_path / 'report')


def test_hostile_text_stays_in_inert_json():
    hostile = '</script><img src=x onerror=bad()>\u2028\u2029&'
    raw = document(hostile, '', {'hostile': hostile}, '').decode()
    assert hostile not in raw
    assert json.loads(re.search(r'id="data">(.*?)</script>', raw, re.S).group(1)) == {'hostile': hostile}


def test_symlink_asset_is_refused(tmp_path, evidence):
    source, terms, _ = prepared(tmp_path, evidence)
    target = source / 'bank_history.json.gz'
    other = tmp_path / 'elsewhere.gz'
    other.write_bytes(target.read_bytes())
    target.unlink()
    try:
        target.symlink_to(other)
    except OSError:
        pytest.skip('Symlink creation unavailable')
    with pytest.raises(ValueError, match='Unsafe'):
        report.generate(source, terms, tmp_path / 'report')


def test_output_reservation_race_does_not_overwrite(tmp_path, evidence, monkeypatch):
    source, terms, _ = prepared(tmp_path, evidence)
    original = report.admit_new_directory
    def reserve(stage, target):
        target.mkdir()
        (target / 'other-owner').write_text('keep')
        original(stage, target)
    monkeypatch.setattr(report, 'admit_new_directory', reserve)
    with pytest.raises(OSError):
        report.generate(source, terms, tmp_path / 'report')
    assert (tmp_path / 'report/other-owner').read_text() == 'keep'


def test_metadata_splits_without_omitting_values(tmp_path, monkeypatch):
    monkeypatch.setattr(report, 'CHUNK_ROWS', 2)
    writer = report_io.Writer(tmp_path)
    descriptors, counts = report.write_metadata(writer, {'history': {'values': [0, False, None, '', [], {}]}})
    rows = []
    for item in descriptors:
        if item['file'].endswith('.json.gz'):
            rows.extend(json.loads(gzip.decompress((tmp_path / item['file']).read_bytes())))
    assert counts == {'history': 6}
    assert [r['value'] for r in rows] == [0, False, None, '', [], {}]


def test_explicit_null_detail_preserves_presence_and_inventory_denominator(tmp_path, evidence):
    source, terms, _ = prepared(tmp_path, evidence, null_detail=True)
    output = tmp_path / 'report'
    receipt = report.generate(source, terms, output)
    assert receipt['products'] == 2
    part = json.loads(gzip.decompress((output / 'part-0001/product-data.json.gz').read_bytes()))
    product = part['products']['unreported-product']
    assert product['published_detail_present'] is True and product['detail'] is None
    parameters = [row for row in read_csv(output / 'part-0001/parameters.csv.gz')
                  if row['product_key'] == 'unreported-product']
    assert parameters == [{'product_key': 'unreported-product', 'source_pointer': '', 'value_json': 'null'}]
    fields = json.loads(gzip.decompress((output / 'fields.json.gz').read_bytes()))
    details = [row for row in fields if row['record_type'] == 'product_detail']
    assert details and all(row['denominator'] == 2 and row['present_records'] == 1 for row in details)
