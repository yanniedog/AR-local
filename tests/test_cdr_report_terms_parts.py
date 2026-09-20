"""Multipart transport controls; fixtures are not bank acceptance evidence."""
import gzip
import json

import pytest

import cdr_report_terms_parts as parts
from cdr_product_report import read_bundle
from cdr_report_terms import bundle_binding, encoded, sha, export_evidence, admit_evidence
from tests.test_cdr_report_terms import evidence, bundle


def source_with_unknowns(tmp_path, evidence):
    source = bundle(tmp_path, evidence)
    manifest = json.loads((source / 'manifest.json').read_bytes())
    descriptor = manifest['files']['details']
    data = json.loads(gzip.decompress((source / descriptor['name']).read_bytes()))
    data['products'].update({'technical-unknown-a': {}, 'technical-unknown-b': {}})
    raw = gzip.compress(encoded(data))
    (source / descriptor['name']).write_bytes(raw)
    descriptor.update(bytes=len(raw), sha256=sha(raw))
    (source / 'manifest.json').write_bytes(encoded(manifest))
    return source


def binding_keys(source):
    return bundle_binding(*read_bundle(source))


def test_complete_parts_match_single_export_and_preserve_unknowns(tmp_path, evidence, monkeypatch):
    source = source_with_unknowns(tmp_path, evidence)
    binding, keys = binding_keys(source)
    monkeypatch.setattr(parts, 'PART_PRODUCTS', 1)
    export_evidence(source, evidence[0].root, tmp_path / 'single')
    expected, _ = admit_evidence(tmp_path / 'single', binding, keys)
    result = parts.export_parts(source, evidence[0].root, tmp_path / 'parts')
    index = parts.verify_parts(tmp_path / 'parts', binding, keys)
    actual = {}
    for part in index['parts']:
        value, _ = admit_evidence(tmp_path / 'parts' / part['name'], binding, part['keys'])
        actual.update(value['products'])
    assert actual == expected['products']
    assert result['products'] == result['parts'] == 3
    assert actual['technical-unknown-a']['status'] == 'unavailable'
    assert all(row['bank_approved'] is None for row in actual.values())


@pytest.mark.parametrize('mutation', ['omit', 'duplicate', 'reorder', 'binding', 'traversal', 'metrics', 'corrupt'])
def test_partial_or_tampered_inventory_refuses(tmp_path, evidence, monkeypatch, mutation):
    source = source_with_unknowns(tmp_path, evidence)
    binding, keys = binding_keys(source)
    monkeypatch.setattr(parts, 'PART_PRODUCTS', 1)
    root = tmp_path / 'parts'
    parts.export_parts(source, evidence[0].root, root)
    index = json.loads((root / 'parts.json').read_bytes())
    if mutation == 'omit':
        index['parts'].pop()
    elif mutation == 'duplicate':
        index['parts'][1]['keys'] = index['parts'][0]['keys']
    elif mutation == 'reorder':
        index['parts'].reverse()
    elif mutation == 'binding':
        index['binding']['manifest_sha256'] = 'a' * 64
    elif mutation == 'traversal':
        index['parts'][0]['name'] = '../single'
    elif mutation == 'metrics':
        index['parts'][0]['metrics']['row_bytes'] += 1
    else:
        (root / 'part-0003' / 'evidence.json').write_bytes(b'{}')
    (root / 'parts.json').write_bytes(encoded(index))
    with pytest.raises(ValueError):
        parts.verify_parts(root, binding, keys)


@pytest.mark.parametrize('failure', ['aggregate', 'late', 'part'])
def test_failures_never_admit_partial_directory(tmp_path, evidence, monkeypatch, failure):
    source = source_with_unknowns(tmp_path, evidence)
    monkeypatch.setattr(parts, 'PART_PRODUCTS', 1)
    if failure == 'aggregate':
        monkeypatch.setitem(parts.LIMITS, 'bytes', 1)
    elif failure == 'part':
        import cdr_report_terms_store
        monkeypatch.setattr(cdr_report_terms_store, 'MAX_ROW_BYTES', 1)
    else:
        original = parts._export_selected
        def late(*args, **kwargs):
            if args[4].name == 'part-0003':
                raise ValueError('late failure')
            return original(*args, **kwargs)
        monkeypatch.setattr(parts, '_export_selected', late)
    with pytest.raises(ValueError):
        parts.export_parts(source, evidence[0].root, tmp_path / 'parts')
    assert not (tmp_path / 'parts').exists()
    assert not list(tmp_path.glob('.report-parts-*'))


def test_hash_reuse_has_no_body_cache_and_detects_changed_file(evidence):
    from cdr_report_terms_store import Snapshot
    store, _, _, _, _, body, _ = evidence
    identity = sha(body)
    view = Snapshot(store.root, reuse_verified=True)
    try:
        assert view.verify_blob(identity) == len(body)
        used = view.processed_io_bytes
        parts._reset_part(view)
        assert view.verify_blob(identity) == used
        assert view.processed_io_bytes == 0
        assert view.blobs[identity] == len(body)
        assert view.receipt()['raw_blob_cache_bytes'] == 0
        (store.root / 'blobs' / identity[:2] / identity).write_bytes(body + b'changed')
        with pytest.raises(ValueError, match='changed'):
            view.verify_blob(identity)
    finally:
        view.close()


def test_parts_keep_one_snapshot_when_writer_commits(tmp_path, evidence, monkeypatch):
    source = source_with_unknowns(tmp_path, evidence)
    store, _, key, _, _, body, record = evidence
    monkeypatch.setattr(parts, 'PART_PRODUCTS', 1)
    original, connections = parts._export_selected, []
    def concurrent(view, *args, **kwargs):
        connections.append(view.view.db)
        seal = original(view, *args, **kwargs)
        if len(connections) == 1:
            store.observe(provider=record['brand'], product_key=key, record=json.loads(body),
                          source_bytes=body, observed_at='2026-09-21T00:00:00Z', ingest_id='concurrent')
        assert view.execute('SELECT observation_id FROM observations WHERE ingest_id=?',
                            ('concurrent',)).fetchone() is None
        return seal
    monkeypatch.setattr(parts, '_export_selected', concurrent)
    parts.export_parts(source, store.root, tmp_path / 'parts')
    assert len(connections) == 3 and all(db is connections[0] for db in connections)
    assert store.db.execute('SELECT 1 FROM observations WHERE ingest_id=?', ('concurrent',)).fetchone()
