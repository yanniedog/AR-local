"""Technical namespace/read-boundary controls; no new product approval."""
import gzip
import json
import sqlite3
from pathlib import Path

import pytest

from cdr_report_terms import delivered, encoded, sha, asset_reader
from cdr_report_terms_store import Snapshot
from cdr_terms.identity import digest
from tests.executable_protocol_fixture import protocol  # noqa: F401

ROOT = Path(__file__).parent / 'fixtures'


def write(root, name, value):
    raw = gzip.compress(encoded(value))
    (root / name).write_bytes(raw)
    return dict(name=name, bytes=len(raw), sha256=sha(raw))


def test_populated_td_selected_row_keeps_index_inventory(protocol, tmp_path):
    _, template, core, source = protocol
    approval = dict(reviewId='a'*64, reviewEvidenceSha256='b'*64, benchmarkResultSha256='c'*64,
                    reviewedAt='2026-01-01T01:00:00Z', templateId=template['id'],
                    review={key: 'verified' for key in ('applicability', 'materialTerms', 'feeCoverage', 'rateSchedule')})
    key = template['productKey']
    asset = dict(schemaVersion=1, productKey=key, sourceGenerationId=template['sourceGenerationId'],
                 runDate=template['runDate'], coreAssetSha256=template['selectedRate']['coreAssetSha256'],
                 approvalPolicy='as_of_adopted_edition', templates=[dict(template=template, approval=approval)])
    asset['identitySha256'] = digest(asset)
    header = dict(run_date=template['runDate'], core_asset_sha256=asset['coreAssetSha256'])
    shard = write(tmp_path, 'td-shard.json.gz', dict(header, products={key: asset}))
    index = write(tmp_path, 'td-index.json.gz', dict(header, products={key: 'executable_shard_000'}))
    manifest = dict(run_date=template['runDate'], source_observation=source, files={
        'core': {'sha256': asset['coreAssetSha256']}, 'executable_index': index, 'executable_shard_000': shard})
    result = delivered(tmp_path, manifest, {'core': core})
    assert result[key][0]['subject_ids'] == [template['id']]


@pytest.mark.parametrize('family', ['monetary-v3', 'mortgage-v3'])
def test_actual_retained_monetary_namespaces_use_capability_dispatch(family, tmp_path):
    bridge = json.loads((ROOT / family / 'actual-bridge.json').read_bytes())
    for descriptor in bridge['assets']:
        raw = (ROOT / family / 'blobs' / descriptor['sha256']).read_bytes()
        assert sha(raw) == descriptor['sha256']
        (tmp_path / descriptor['name']).write_bytes(raw)
    result = delivered(tmp_path, bridge['context']['manifest'], bridge['context'])
    subject = bridge['selection']['subject']
    entry = result[subject['scope']['productKey']][0]
    assert entry['capability'] == subject['capability'] and entry['subject_ids'] == [subject['id']]
    assert entry['bank_acceptance'] == 'unclassified'


def test_mixed_registry_capabilities_and_unknown_future_wire_are_separate(tmp_path):
    root = tmp_path / 'store'
    root.mkdir()
    db = sqlite3.connect(root / 'evidence.sqlite3')
    db.executescript('CREATE TABLE executable_registry_subjects(subject_id,wire_version,capability,scope_id,product_key,observation_id);'
                     'CREATE TABLE executable_reviews_v3(sequence,review_id,decision,reviewed_at,evidence_sha256,subject_id);')
    for number, capability, version in [(1, 'savings_calculation', 3), (2, 'mortgage_calculation', 3), (3, 'future', 99)]:
        db.execute('INSERT INTO executable_registry_subjects VALUES (?,?,?,?,?,?)',
                   (str(number), version, capability, str(number), 'p', 'o'))
    db.commit()
    db.close()
    view = Snapshot(root)
    try:
        subjects = view.executables({'product_key': 'p', 'observation_id': 'o'})['subjects']
        assert [s['capability'] for s in subjects] == ['savings_calculation', 'mortgage_calculation', 'future']
        assert subjects[2]['unavailable_reason'] == 'unsupported registry wire version'
    finally:
        view.close()


def test_single_snapshot_does_not_adopt_concurrent_append(tmp_path):
    root = tmp_path / 'store'
    root.mkdir()
    db = sqlite3.connect(root / 'evidence.sqlite3')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE values_seen(identity)')
    db.execute('INSERT INTO values_seen VALUES (?)', ('before',))
    db.commit()
    view = Snapshot(root)
    try:
        assert view.execute('SELECT * FROM values_seen').fetchall()[0][0] == 'before'
        db.execute('INSERT INTO values_seen VALUES (?)', ('after',))
        db.commit()
        assert [r[0] for r in view.execute('SELECT * FROM values_seen').fetchall()] == ['before']
    finally:
        view.close()
        db.close()


def test_true_inflated_whitespace_counts_across_assets(tmp_path, monkeypatch):
    import cdr_report_terms as terms
    monkeypatch.setattr(terms, 'MAX_BYTES', 100)
    read = asset_reader(tmp_path)
    for i in range(2):
        raw = gzip.compress(b' ' * 55 + b'{}')
        name = f'{i}.json.gz'
        (tmp_path / name).write_bytes(raw)
        descriptor = dict(name=name, bytes=len(raw), sha256=sha(raw))
        if i == 0:
            assert read(descriptor) == {}
        else:
            with pytest.raises(ValueError, match='budget'):
                read(descriptor)


def test_streamed_multiblob_verification_separates_io_from_retained_memory(tmp_path, monkeypatch):
    import hashlib
    import cdr_report_terms_store as module
    root = tmp_path / 'stream-store'
    root.mkdir()
    sqlite3.connect(root / 'evidence.sqlite3').close()
    files = []
    for i in range(4):
        chunk = bytes([i]) * (1024 * 1024)
        checksum = hashlib.sha256()
        for _ in range(7):
            checksum.update(chunk)
        identity = checksum.hexdigest()
        path = root / 'blobs' / identity[:2] / identity
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('wb') as stream:
            for _ in range(7):
                stream.write(chunk)
        files.append((identity, path))
    view = Snapshot(root)
    try:
        for identity, _ in files:
            assert view.verify_blob(identity) == 7 * 1024 * 1024
        receipt = view.receipt()
        assert receipt['processed_io_bytes'] == 28 * 1024 * 1024 > module.MAX_ROW_BYTES
        assert receipt['raw_blob_cache_bytes'] == receipt['max_materialized_blob'] == 0
        assert receipt['max_read_request'] == 65536
        assert all(type(size) is int for size in view.blobs.values())
        # Every reread verifies the actual file, even for an already recorded SHA.
        identity, path = files[-1]
        with path.open('r+b') as stream:
            stream.seek(-1, 2)
            stream.write(b'changed'[0:1])
        with pytest.raises(ValueError, match='identity'):
            view.verify_blob(identity)
        assert view.processed_io_bytes == 35 * 1024 * 1024
        monkeypatch.setattr(module, 'MAX_BLOB_WORK', view.processed_io_bytes + 7 * 1024 * 1024 - 1)
        with pytest.raises(ValueError, match='budget'):
            view.verify_blob(files[0][0])
        assert view.processed_io_bytes == 35 * 1024 * 1024
        monkeypatch.setattr(module, 'MAX_BLOB_WORK', 512 * 1024 * 1024)
        monkeypatch.setattr(module, 'MAX_BLOB', 7 * 1024 * 1024 - 1)
        with pytest.raises(ValueError, match='budget'):
            view.read_blob(files[0][0])
    finally:
        view.close()
