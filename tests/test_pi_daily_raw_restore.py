"""Archive-format replay of retained CDR evidence; no production acceptance claim."""
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tarfile

import pytest
import zstandard

import pi_daily_raw_restore as restore
from pi_daily_cdr_day_archive import build_day_archive

DAY = '2026-11-13'
GENERATION = 'obs-' + DAY + '-1111111111111111'
FINGERPRINT = hashlib.sha256(b'local retained-fixture format replay, not production').hexdigest()
LIMITS = replace(restore.Limits(), free_space_floor=0)
FIXTURE = Path(__file__).parent / 'fixtures/cdr-september7/defence.json'


def receipt_for(archive, root):
    receipt = root / 'receipt.json'
    row = dict(schema=restore.SCHEMA, series=restore.SERIES, date=DAY,
               generation_id=GENERATION, source_fingerprint=FINGERPRINT,
               kind='day', result='PASS', remote_name=DAY + '.tar.zst',
               bytes=archive.stat().st_size, sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
    receipt.write_text(json.dumps(row), encoding='utf-8')
    return receipt, hashlib.sha256(receipt.read_bytes()).hexdigest()


def make_archive(root, *, wal=False, broken_wal=False):
    data = root / 'source'
    run = data / 'runs' / DAY
    product = json.loads(FIXTURE.read_bytes())['product_detail']['body']
    raw = run / 'banks' / 'TD' / 'Defence Bank' / 'Fixed' / product['data']['productId'] / 'product-detail.json'
    raw.parent.mkdir(parents=True)
    raw.write_text(json.dumps(product), encoding='utf-8')
    db_path = run / '_exports' / 'local-cdr.sqlite'
    db_path.parent.mkdir()
    db = sqlite3.connect(db_path)
    try:
        db.execute('CREATE TABLE captured_cdr(body TEXT NOT NULL)')
        db.commit()
        if wal:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA wal_autocheckpoint=0')
        db.execute('INSERT INTO captured_cdr VALUES (?)', (json.dumps(product),))
        db.commit()
        if broken_wal:
            path = Path(str(db_path) + '-wal')
            value = bytearray(path.read_bytes()); value[-1] ^= 1; path.write_bytes(value)
        built = build_day_archive(data, DAY, root / 'built', include_journals=False,
                                  source_fingerprint=FINGERPRINT)
    finally:
        db.close()
    archive = Path(built['local_path'])
    receipt, receipt_sha = receipt_for(archive, root)
    return archive, receipt, receipt_sha


def qualify(root, inputs, **kwargs):
    archive, receipt, sha = inputs
    return restore.qualify(archive, receipt, sha, GENERATION, root / 'restored', limits=kwargs.pop('limits', LIMITS), **kwargs)


def rewrite_archive(inputs, change, root):
    archive, _, _ = inputs
    with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(archive.read_bytes())) as decoded:
        raw = decoded.read()
    with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
        members = [(item, tar.extractfile(item).read()) for item in tar]
    change(members)
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w', format=tarfile.PAX_FORMAT) as tar:
        for item, body in members:
            item.size = len(body); tar.addfile(item, io.BytesIO(body))
    archive.write_bytes(zstandard.ZstdCompressor(write_checksum=True).compress(output.getvalue()))
    receipt, sha = receipt_for(archive, root)
    return archive, receipt, sha


def test_real_retained_product_restores_with_committed_wal_and_preserves_inputs(tmp_path):
    inputs = make_archive(tmp_path, wal=True)
    before = [path.read_bytes() for path in inputs[:2]]
    result = qualify(tmp_path, inputs)
    assert result['result'] == 'PASS' and result['generation_id'] == GENERATION
    assert result['sqlite_checks'][0]['tables'] == {'captured_cdr': 1}
    assert result['sqlite_checks'][0]['wal']['committed_frame'] > 0
    check = result['sqlite_checks'][0]
    original = tmp_path / 'restored/exact' / check['logical_path']
    # Original DB alone lacks the WAL insertion; committed copy contains it.
    with sqlite3.connect(original.as_uri() + '?immutable=1', uri=True) as db:
        assert db.execute('SELECT COUNT(*) FROM captured_cdr').fetchone()[0] == 0
    with sqlite3.connect(tmp_path / 'restored' / check['committed_relative']) as db:
        body = json.loads(db.execute('SELECT body FROM captured_cdr').fetchone()[0])
    assert body == json.loads(FIXTURE.read_bytes())['product_detail']['body']
    assert before == [path.read_bytes() for path in inputs[:2]]
    assert json.loads((tmp_path / 'restored/restore-result.json').read_text()) == result


@pytest.mark.parametrize('fault', ['receipt_hash', 'generation', 'archive_hash', 'archive_size', 'fingerprint', 'receipt_duplicate'])
def test_binding_faults_never_pass(tmp_path, fault):
    archive, receipt, sha = make_archive(tmp_path)
    generation = GENERATION
    if fault == 'receipt_hash':
        sha = '0' * 64
    elif fault == 'generation':
        generation = 'obs-' + DAY + '-0000000000000000'
    elif fault == 'receipt_duplicate':
        receipt.write_text(receipt.read_text()[:-1] + ',"result":"PASS"}')
        sha = hashlib.sha256(receipt.read_bytes()).hexdigest()
    else:
        row = json.loads(receipt.read_bytes())
        row[{'archive_hash': 'sha256', 'archive_size': 'bytes', 'fingerprint': 'source_fingerprint'}[fault]] = (
            row['bytes'] + 1 if fault == 'archive_size' else '0' * 64)
        receipt.write_text(json.dumps(row)); sha = hashlib.sha256(receipt.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        restore.qualify(archive, receipt, sha, generation, tmp_path / 'restored', limits=LIMITS)
    result = tmp_path / 'restored/restore-result.json'
    if result.exists():
        assert json.loads(result.read_text())['result'] == 'FAIL'


@pytest.mark.parametrize('fault', ['traversal', 'absolute', 'symlink', 'hardlink', 'device', 'duplicate', 'body_hash', 'metadata', 'count', 'extra'])
def test_unsafe_or_mismatched_archive_members_fail(tmp_path, fault):
    inputs = make_archive(tmp_path)
    def change(members):
        member, body = members[1]
        if fault == 'traversal': member.name = '../escape'
        elif fault == 'absolute': member.name = '/escape'
        elif fault in {'symlink', 'hardlink', 'device'}:
            member.type = {'symlink': tarfile.SYMTYPE, 'hardlink': tarfile.LNKTYPE, 'device': tarfile.CHRTYPE}[fault]
            member.linkname = '../escape'
        elif fault in {'duplicate', 'extra'}: members.append((member, body))
        elif fault == 'body_hash': members[1] = (member, b'x' * len(body))
        elif fault == 'metadata': member.uid += 1
        elif fault == 'count':
            manifest = json.loads(members[0][1]); manifest['file_count'] += 1
            members[0] = (members[0][0], json.dumps(manifest).encode())
    inputs = rewrite_archive(inputs, change, tmp_path)
    with pytest.raises((ValueError, tarfile.TarError, sqlite3.DatabaseError)):
        qualify(tmp_path, inputs)
    assert not (tmp_path / 'escape').exists()
    assert json.loads((tmp_path / 'restored/restore-result.json').read_text())['result'] == 'FAIL'


@pytest.mark.parametrize('fault', ['truncated', 'extra_frame'])
def test_compression_frame_faults_fail_even_with_matching_receipt(tmp_path, fault):
    archive, _, _ = make_archive(tmp_path)
    body = archive.read_bytes()
    archive.write_bytes(body[:-8] if fault == 'truncated' else body + body)
    receipt, sha = receipt_for(archive, tmp_path)
    with pytest.raises(ValueError):
        qualify(tmp_path, (archive, receipt, sha))


@pytest.mark.parametrize('limits', [replace(LIMITS, files=1), replace(LIMITS, unpacked_bytes=1), replace(LIMITS, manifest_bytes=1)])
def test_resource_bounds_fail_closed(tmp_path, limits):
    with pytest.raises(ValueError):
        qualify(tmp_path, make_archive(tmp_path), limits=limits)


def test_corrupt_wal_cannot_silently_drop_committed_changes(tmp_path):
    with pytest.raises(ValueError, match='WAL frame checksum'):
        qualify(tmp_path, make_archive(tmp_path, wal=True, broken_wal=True))


@pytest.mark.parametrize('fault', ['case_collision', 'manifest_duplicate', 'orphan_wal', 'corrupt_database'])
def test_additional_manifest_and_sqlite_faults_fail(tmp_path, fault):
    inputs = make_archive(tmp_path)
    def change(members):
        manifest = json.loads(members[0][1])
        if fault == 'manifest_duplicate':
            members[0] = (members[0][0], members[0][1][:-2] + b',"file_count":2}')
            return
        position = next(i for i, row in enumerate(manifest['files']) if row['logical_path'].endswith('.sqlite'))
        row = manifest['files'][position]
        item, body = members[position + 1]
        if fault == 'orphan_wal':
            item.name += '-wal'; row['logical_path'] += '-wal'
        elif fault == 'corrupt_database':
            body = b'not a database' + bytes(len(body) - len(b'not a database'))
            row['sha256'] = hashlib.sha256(body).hexdigest()
        elif fault == 'case_collision':
            other = dict(manifest['files'][0]); other['logical_path'] = other['logical_path'].upper()
            # A collision is rejected by path scope or the casefold unique key.
            manifest['files'].append(other)
        members[position + 1] = (item, body)
        members[0] = (members[0][0], json.dumps(manifest).encode())
    inputs = rewrite_archive(inputs, change, tmp_path)
    with pytest.raises((ValueError, sqlite3.DatabaseError)):
        qualify(tmp_path, inputs)


def test_disk_floor_and_deadline_are_enforced(tmp_path, monkeypatch):
    budget = restore.Budget(tmp_path, replace(LIMITS, free_space_floor=2**63))
    with pytest.raises(ValueError, match='free-space'):
        budget()
    budget = restore.Budget(tmp_path, LIMITS)
    monkeypatch.setattr(restore.time, 'monotonic', lambda: budget.deadline)
    with pytest.raises(TimeoutError):
        budget()


def test_sqlite_result_budget_is_checked_before_retaining_tables(tmp_path, monkeypatch):
    import pi_daily_raw_restore_sqlite as semantic
    monkeypatch.setattr(semantic, 'MAX_RESULT_BYTES', 8)
    with pytest.raises(ValueError, match='result inventory'):
        qualify(tmp_path, make_archive(tmp_path))


def test_present_archived_contract_must_match_generation(tmp_path, monkeypatch):
    with sqlite3.connect(':memory:') as index:
        index.execute('CREATE TABLE files(logical TEXT,value TEXT)')
        logical = f'data/state/export-contracts-v2/{DAY}/{GENERATION}.json'
        index.execute('INSERT INTO files VALUES (?,?)', (logical, json.dumps({'sha256': 'a' * 64})))
        receipt = {'date': DAY, 'generation_id': GENERATION}
        metadata = {'generation_id': GENERATION, 'observation_date': DAY, 'contract_digest': 'b' * 64}
        called = []
        def load(path, *, budget):
            called.append(path); budget(); return metadata
        monkeypatch.setattr(restore, 'load_contract', load)
        assert restore._archived_contract(receipt, tmp_path, index, lambda: None)['status'] == 'verified'
        assert called == [tmp_path / 'exact' / logical]
        metadata['generation_id'] = 'wrong-generation'
        with pytest.raises(ValueError, match='contract generation'):
            restore._archived_contract(receipt, tmp_path, index, lambda: None)


def test_existing_workspace_and_production_root_are_refused(tmp_path):
    inputs = make_archive(tmp_path)
    (tmp_path / 'restored').mkdir()
    marker = tmp_path / 'restored/preserve'; marker.write_text('existing evidence')
    with pytest.raises(ValueError, match='new canonical workspace'):
        qualify(tmp_path, inputs)
    assert marker.read_text() == 'existing evidence'
    with pytest.raises(ValueError, match='outside production'):
        restore.outside_production(Path('/srv/ar-local/recovery'))
