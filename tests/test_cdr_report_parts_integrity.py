"""Regression controls for report bounds and lossless source inventory."""
import gzip
import json

import pytest

import cdr_product_report_parts as report
import cdr_report_parts_io as report_io
import cdr_report_terms_parts as parts
from cdr_report_terms import encoded, sha
from tests.test_cdr_report_terms import evidence
from tests.test_cdr_product_report_parts import prepared


def test_detail_budget_is_shared_across_parts(tmp_path, evidence, monkeypatch):
    monkeypatch.setattr(parts, 'PART_PRODUCTS', 1)
    source, terms, _ = prepared(tmp_path, evidence)
    monkeypatch.setattr(report, 'MAX_LEAVES', 6)
    with pytest.raises(ValueError, match='detail row budget'):
        report.generate(source, terms, tmp_path / 'report')
    assert not (tmp_path / 'report').exists()
    assert not list(tmp_path.glob('.combined-report-*'))


def test_empty_rate_section_is_distinct_from_absence():
    rows = list(report.metadata_rows({'core': {'sections': {
        'empty': {'rates': []}, 'absent': {}, 'populated': {'rates': [{'rate': '0.01'}]}}}}))
    assert rows == [
        {'asset': 'core', 'source_pointer': '/sections/empty/rates', 'value': []},
        {'asset': 'core', 'source_pointer': '/sections/absent', 'value': {}}]


def test_original_manifest_bytes_match_bound_identity(tmp_path, evidence):
    source, _, _ = prepared(tmp_path, evidence)
    original = json.dumps(json.loads((source / 'manifest.json').read_bytes()), indent=3).encode() + b'\n'
    (source / 'manifest.json').write_bytes(original)
    terms = tmp_path / 'resealed'
    parts.export_parts(source, evidence[0].root, terms)
    output = tmp_path / 'report'
    receipt = report.generate(source, terms, output)
    assert (output / 'source-manifest.json').read_bytes() == original
    assert sha(original) == receipt['source_evidence']['manifest_sha256'] == receipt['binding']['manifest_sha256']


def optional_bundle(tmp_path, evidence, version):
    source, _, _ = prepared(tmp_path, evidence)
    manifest = json.loads((source / 'manifest.json').read_bytes())
    capability = 'savings_calculation' if version == 3 else 'savings_activity_calculation'
    prefix = 'executable_v2' if version == 2 else f'monetary_v{version}_{capability}'
    payloads, entries = {}, {}
    for suffix in ('index', 'shard_000'):
        kind = prefix + '_' + suffix
        value = {'technical': True, 'run_date': manifest['run_date'], 'values': [None, False, [], -1]}
        raw = gzip.compress(encoded(value), mtime=0)
        name = f"{kind}-{manifest['run_date']}-{sha(raw)[:12]}.json.gz"
        (source / name).write_bytes(raw)
        entries[kind] = {'name': name, 'bytes': len(raw), 'sha256': sha(raw)}
        payloads[kind] = value
    route = {'index': entries[prefix + '_index'], 'shards': {prefix + '_shard_000': entries[prefix + '_shard_000']}}
    manifest[f'executable_v{version}'] = {'schema_version': version, **(route if version == 2 else {'capabilities': {capability: route}})}
    (source / 'manifest.json').write_bytes(encoded(manifest))
    return source, payloads, entries


@pytest.mark.parametrize('version', [2, 3, 4])
def test_optional_assets_have_complete_verified_metadata(tmp_path, evidence, version):
    source, expected, descriptors = optional_bundle(tmp_path, evidence, version)
    result = report_io.read_bundle(source)
    payloads, proof = result[1:3]
    for kind, value in expected.items():
        assert payloads.get(kind) == value
        assert proof['assets'][kind] == descriptors[kind]
    rows = list(report.metadata_rows({kind: payloads[kind] for kind in expected}))
    assert len(rows) == 12
    assert proof['input_bytes'] == sum(p['bytes'] for p in proof['assets'].values())


@pytest.mark.parametrize('failure', ['hash', 'compressed_budget', 'expanded_budget'])
def test_optional_assets_share_transport_limits(tmp_path, evidence, monkeypatch, failure):
    source, _, descriptors = optional_bundle(tmp_path, evidence, 4)
    manifest = json.loads((source / 'manifest.json').read_bytes())
    if failure == 'hash':
        item = next(iter(descriptors.values()))
        (source / item['name']).write_bytes(b'X' * item['bytes'])
    elif failure == 'compressed_budget':
        monkeypatch.setattr(report_io, 'MAX_INPUT', sum(item['bytes'] for item in manifest['files'].values()))
    else:
        size = sum(len(gzip.decompress((source / item['name']).read_bytes())) for item in manifest['files'].values())
        monkeypatch.setattr(report_io, 'MAX_PLAIN', size)
    with pytest.raises(ValueError):
        report_io.read_bundle(source)
