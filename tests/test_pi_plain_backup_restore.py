"""Generic bytes and real SQLite recovery fixtures; no fabricated rate records."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tarfile
from contextlib import closing

import pytest
import zstandard

import pi_plain_backup_restore as restore
from pi_drive_backup_manifest import encoded
from pi_drive_backup_source import sqlite_checks


def sha(value):
    return hashlib.sha256(value).hexdigest()


def metadata(logical, data, *, sqlite=False, original=False):
    return dict(logical_path=logical, sha256=sha(data), size=len(data), mode='0o640',
                mtime_ns=1700000000123456789, uid=0, gid=0, sqlite=sqlite, sqlite_original=original)


def make_recovery(tmp_path, *, mutate=None):
    mirror = (tmp_path / 'downloaded').resolve(); mirror.mkdir()
    source = tmp_path / 'fixture.sqlite'
    connection = sqlite3.connect(source)
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('CREATE TABLE fixture_bytes (payload BLOB)')
    connection.execute('INSERT INTO fixture_bytes VALUES (?)', (b'generic recovery protocol',))
    connection.commit()
    target = tmp_path / 'consistent.sqlite'
    with sqlite3.connect(target) as view:
        connection.backup(view)
    values = {
        'data/runs/2026-10-24/raw/payload.bin': bytes(range(256)) * 17,
        'data/state/control.sqlite': target.read_bytes(),
        'sqlite-original/data/state/control.sqlite': source.read_bytes(),
        'sqlite-original/data/state/control.sqlite-wal': Path(str(source) + '-wal').read_bytes(),
        'control/000-status.txt': b'recovery control bytes\n',
    }
    connection.close()
    rows = [metadata(name, data, sqlite=name == 'data/state/control.sqlite',
                     original=name.startswith('sqlite-original/')) for name, data in sorted(values.items())]
    identity_sha = hashlib.sha256(encoded({'group': 'control', 'schema': restore.PACK_SCHEMA}) + b'\n')
    for row in rows:
        identity_sha.update(encoded(row) + b'\n')
    identity = dict(pack_id=identity_sha.hexdigest(), group='control', files=len(rows),
                    source_bytes=sum(row['size'] for row in rows))
    manifest = encoded(dict(identity=identity, schema=restore.PACK_SCHEMA, files=rows)) + b'\n'
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w', format=tarfile.PAX_FORMAT) as tar:
        header = tarfile.TarInfo(restore.MANIFEST); header.size = len(manifest)
        tar.addfile(header, io.BytesIO(manifest))
        for row in rows:
            header = tarfile.TarInfo(row['logical_path'])
            header.size, header.mode, header.uid, header.gid = row['size'], int(row['mode'], 8), row['uid'], row['gid']
            seconds, nanos = divmod(row['mtime_ns'], 10**9)
            header.mtime = seconds; header.pax_headers = {'mtime': f'{seconds}.{nanos:09d}'}
            if mutate:
                mutate(row, header)
            tar.addfile(header, io.BytesIO(values[row['logical_path']]) if header.isfile() else None)
    compressed = zstandard.ZstdCompressor(level=3, write_checksum=True).compress(buffer.getvalue())
    descriptor = dict(identity, schema=restore.PACK_SCHEMA, compression='zstd-lossless-no-encryption',
                      archive_sha256=sha(compressed), archive_bytes=len(compressed),
                      manifest_sha256=sha(manifest), manifest_bytes=len(manifest))
    pack = mirror / 'packs' / identity['pack_id']; pack.mkdir(parents=True)
    (pack / 'archive.tar.zst').write_bytes(compressed)
    index = encoded({'schema': 'ar-local-plain-file-index-v1', 'data_root': '/srv/ar-local/data'}) + b'\n'
    for row in rows:
        if row['logical_path'].startswith('control/'):
            continue
        relative = row['logical_path'].removeprefix('sqlite-original/').removeprefix('data/')
        index += encoded(dict(row, source_relative=relative, pack_id=identity['pack_id'],
            representation='sqlite_committed_view' if row['sqlite'] else 'exact_source_bytes')) + b'\n'
    index_descriptor = dict(path='manifests/' + sha(index) + '.jsonl', sha256=sha(index), bytes=len(index),
                            records=len(rows)-1, schema='ar-local-plain-file-index-v1', data_root='/srv/ar-local/data')
    (mirror / 'manifests').mkdir(); (mirror / index_descriptor['path']).write_bytes(index)
    proof = dict(files_verified=len(rows), databases_verified=1,
                 sqlite_checks_sha256=sha(encoded({'logical_path': 'data/state/control.sqlite', **sqlite_checks(target)}) + b'\n'),
                 archive_sha256=sha(compressed))
    catalog = dict(schema='ar-local-plain-catalog-v1', scope={'fixture': 'generic-bytes'},
                   packs=[dict(descriptor=descriptor, verification=proof)], file_index=index_descriptor,
                   excluded_paths=['state/private.key'], excluded_count=1,
                   excluded_sha256=sha(encoded('state/private.key') + b'\n'))
    catalog_path = mirror / 'catalog.json'; catalog_path.write_bytes(encoded(catalog) + b'\n')
    return mirror, catalog_path, values


def run(tmp_path, mirror, catalog, **kwargs):
    return restore.restore(mirror, catalog, restore.digest(catalog, lambda: None),
                           (tmp_path / 'restored').resolve(), guard=lambda: None, **kwargs)


def test_complete_restore_keeps_original_sqlite_wal_and_committed_view_separate(tmp_path):
    mirror, catalog, values = make_recovery(tmp_path)
    before = {p.relative_to(mirror): p.read_bytes() for p in mirror.rglob('*') if p.is_file()}
    result = run(tmp_path, mirror, catalog)
    assert result['result'] == 'FILES_RESTORED_VERIFIED' and result['files_verified'] == 5
    work = tmp_path / 'restored'
    for name, expected in values.items():
        assert (work / 'logical' / name).read_bytes() == expected
    assert (work / 'data/state/control.sqlite').read_bytes() == values['sqlite-original/data/state/control.sqlite']
    assert (work / 'data/state/control.sqlite-wal').read_bytes() == values['sqlite-original/data/state/control.sqlite-wal']
    assert (work / 'committed-view/state/control.sqlite').read_bytes() == values['data/state/control.sqlite']
    assert sqlite_checks(work / 'committed-view/state/control.sqlite')['integrity_check'] == 'ok'
    # Opening a separate copy of the exact DB/WAL pair replays the retained WAL.
    drill = tmp_path / 'drill'; shutil.copytree(work / 'data/state', drill)
    with closing(sqlite3.connect(drill / 'control.sqlite')) as database:
        assert database.execute('SELECT payload FROM fixture_bytes').fetchone()[0] == b'generic recovery protocol'
    assert {p.relative_to(mirror): p.read_bytes() for p in mirror.rglob('*') if p.is_file()} == before
    assert json.loads((work / 'excluded-paths.jsonl').read_text()) == 'state/private.key'


def test_existing_workspace_never_overwritten(tmp_path):
    mirror, catalog, _ = make_recovery(tmp_path)
    work = tmp_path / 'restored'; work.mkdir(); (work / 'keep').write_bytes(b'untracked work')
    with pytest.raises(ValueError, match='new canonical workspace'):
        run(tmp_path, mirror, catalog)
    assert (work / 'keep').read_bytes() == b'untracked work'


def test_independent_catalog_hash_required(tmp_path):
    mirror, catalog, _ = make_recovery(tmp_path)
    with pytest.raises(ValueError, match='independently recorded'):
        restore.restore(mirror, catalog, '0'*64, (tmp_path / 'restored').resolve(), guard=lambda: None)
    assert not (tmp_path / 'restored/restore-result.json').exists()


@pytest.mark.parametrize('change', ['archive', 'manifest', 'proof', 'index', 'exclusions'])
def test_corruption_never_publishes_restore_success(tmp_path, change):
    mirror, path, _ = make_recovery(tmp_path)
    catalog = json.loads(path.read_text())
    if change == 'archive':
        archive = next(mirror.glob('packs/*/archive.tar.zst')); archive.write_bytes(archive.read_bytes()[:-4])
    elif change == 'manifest':
        catalog['packs'][0]['descriptor']['manifest_sha256'] = '0'*64
    elif change == 'proof':
        catalog['packs'][0]['verification']['files_verified'] += 1
    elif change == 'index':
        (mirror / catalog['file_index']['path']).write_bytes(b'{}\n')
    else:
        catalog['excluded_sha256'] = '0'*64
    path.write_bytes(encoded(catalog) + b'\n')
    with pytest.raises(ValueError):
        run(tmp_path, mirror, path)
    assert not (tmp_path / 'restored/restore-result.json').exists()


@pytest.mark.parametrize('kind', [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE])
def test_nonregular_members_cannot_write_or_link_outside_workspace(tmp_path, kind):
    def mutate(row, header):
        if row['logical_path'].endswith('payload.bin'):
            header.type = kind; header.linkname = str(tmp_path / 'outside')
    mirror, catalog, _ = make_recovery(tmp_path, mutate=mutate)
    with pytest.raises(ValueError):
        run(tmp_path, mirror, catalog)
    assert not (tmp_path / 'outside').exists()


@pytest.mark.parametrize('value', ['../outside', '/root/file', 'a/../b', 'a//b', 'a\\b', 'C:escape', 'NUL', 'file.'])
def test_unsafe_recovery_names_rejected(value):
    with pytest.raises(ValueError):
        restore.safe_relative(value)


def test_file_index_cannot_redirect_original_to_another_data_path(tmp_path):
    mirror, path, _ = make_recovery(tmp_path)
    catalog = json.loads(path.read_text()); descriptor = catalog['file_index']
    old = mirror / descriptor['path']; lines = old.read_text().splitlines()
    row = json.loads(lines[1]); row['source_relative'] = 'state/wrong'
    lines[1] = encoded(row).decode(); content = ('\n'.join(lines) + '\n').encode()
    descriptor.update(sha256=sha(content), bytes=len(content), path='manifests/' + sha(content) + '.jsonl')
    (mirror / descriptor['path']).write_bytes(content); path.write_bytes(encoded(catalog) + b'\n')
    with pytest.raises(ValueError, match='exact source mapping'):
        run(tmp_path, mirror, path)


def test_guard_interrupt_leaves_no_success_and_keeps_downloads(tmp_path):
    mirror, catalog, _ = make_recovery(tmp_path)
    count = 0
    def guard():
        nonlocal count
        count += 1
        if count == 35:
            raise RuntimeError('bounded restore stop')
    with pytest.raises(RuntimeError, match='bounded restore stop'):
        restore.restore(mirror, catalog, restore.digest(catalog, lambda: None),
                        (tmp_path / 'restored').resolve(), guard=guard)
    assert not (tmp_path / 'restored/restore-result.json').exists()
    assert next(mirror.glob('packs/*/archive.tar.zst')).is_file()


def test_explicit_metadata_requires_posix_root_before_output(tmp_path, monkeypatch):
    mirror, catalog, _ = make_recovery(tmp_path)
    monkeypatch.setattr(restore.os, 'geteuid', lambda: 1234, raising=False)
    with pytest.raises(ValueError, match='POSIX root'):
        run(tmp_path, mirror, catalog, apply_metadata=True)
    assert not (tmp_path / 'restored').exists()


def test_duplicate_json_fields_rejected():
    with pytest.raises(ValueError, match='duplicate JSON'):
        json.loads('{"schema":1,"schema":2}', object_pairs_hook=restore.no_duplicates)


def test_large_tar_extension_rejected_before_buffering():
    header = restore.BoundedTarInfo('extension')
    header.type, header.size = tarfile.XHDTYPE, 2**40
    with pytest.raises(ValueError, match='oversized recovery PAX'):
        header._proc_member(None)


@pytest.mark.skipif(os.name != 'nt', reason='native Windows DACL qualification')
def test_windows_new_workspace_has_protected_user_system_dacl(tmp_path):
    import ctypes as ct
    from ctypes import wintypes as wt
    work = (tmp_path / 'private-restore').resolve()
    assert restore.private_workspace(work) == 'WINDOWS_PROTECTED_USER_SYSTEM_DACL'
    security = ct.WinDLL('advapi32', use_last_error=True)
    kernel = ct.WinDLL('kernel32', use_last_error=True)
    query = security.GetFileSecurityW
    query.argtypes = [wt.LPCWSTR, wt.DWORD, wt.LPVOID, wt.DWORD, ct.POINTER(wt.DWORD)]
    query.restype = wt.BOOL
    convert = security.ConvertSecurityDescriptorToStringSecurityDescriptorW
    convert.argtypes = [wt.LPVOID, wt.DWORD, wt.DWORD, ct.POINTER(wt.LPWSTR), ct.POINTER(wt.DWORD)]
    convert.restype = wt.BOOL
    kernel.LocalFree.argtypes = [wt.LPVOID]; kernel.LocalFree.restype = wt.LPVOID
    needed = wt.DWORD(); query(str(work), 4, None, 0, ct.byref(needed))
    buffer = ct.create_string_buffer(needed.value)
    assert query(str(work), 4, buffer, needed, ct.byref(needed))
    text = wt.LPWSTR()
    assert convert(buffer, 1, 4, ct.byref(text), None)
    try:
        value = text.value
        assert value.startswith('D:P') and value.count('(A;') == 2
        assert '(A;OICI;FA;;;SY)' in value and ';;;S-1-5-21-' in value
        assert ';;;WD)' not in value and ';;;AU)' not in value and ';;;BU)' not in value
    finally:
        kernel.LocalFree(ct.cast(text, wt.LPVOID))


@pytest.mark.parametrize('change', ['truncate', 'extra-frame', 'checksum'])
def test_frame_corruption_detected_even_if_compressed_hash_in_catalog_matches(tmp_path, change):
    mirror, catalog_path, _ = make_recovery(tmp_path)
    catalog = json.loads(catalog_path.read_text()); descriptor = catalog['packs'][0]['descriptor']
    archive = next(mirror.glob('packs/*/archive.tar.zst')); value = archive.read_bytes()
    if change == 'truncate':
        value = value[:-4]
    elif change == 'extra-frame':
        value += zstandard.ZstdCompressor(write_checksum=True).compress(b'')
    else:
        value = value[:-1] + bytes([value[-1] ^ 1])
    archive.write_bytes(value)
    descriptor.update(archive_sha256=sha(value), archive_bytes=len(value))
    catalog_path.write_bytes(encoded(catalog) + b'\n')
    with pytest.raises((ValueError, zstandard.ZstdError)):
        run(tmp_path, mirror, catalog_path)
    assert not (tmp_path / 'restored/restore-result.json').exists()
