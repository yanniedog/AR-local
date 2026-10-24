"""Generic byte/SQLite protocol fixtures; no simulated rate business records."""
from dataclasses import asdict
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tarfile
from unittest.mock import patch
from types import SimpleNamespace

import pytest
import zstandard

import pi_drive_backup_source as source
from pi_plain_backup_attestation import AttestedHostLease
from pi_plain_backup_packs import (Guarded, PackIndex, build_pack, group_for, verify_pack)
from pi_plain_backup_transport import Rclone
import pi_plain_backup_transport as remote_transport
import pi_plain_drive_backup as pipeline


class Drive:
    def __init__(self):
        self.objects, self.uploads, self.reads = {}, [], []
        self.corrupt = False

    def upload(self, relative, path):
        self.uploads.append(relative)
        self.objects.setdefault(relative, path.read_bytes())
        if self.corrupt and relative.endswith('.tar.zst'):
            self.objects[relative] = self.objects[relative][:-4]

    def download(self, relative, path):
        self.reads.append(relative)
        if relative not in self.objects:
            return False
        with path.open('xb') as output:
            output.write(self.objects[relative])
        return True


@pytest.fixture
def layout(tmp_path, monkeypatch):
    data = tmp_path / 'data'
    raw = data / 'runs/2026-10-24/raw'
    raw.mkdir(parents=True)
    (raw / 'bytes.bin').write_bytes(bytes(range(256)) * 32)
    (data / 'state').mkdir()
    (data / 'state/log.txt').write_bytes(b'generic backup protocol fixture\n')
    database = data / 'state/control.sqlite'
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE captured_bytes (value BLOB)')
        db.execute('INSERT INTO captured_bytes VALUES (?)', (b'preserve exact bytes',))
    lease = AttestedHostLease.__new__(AttestedHostLease)
    monkeypatch.setattr(AttestedHostLease, 'verify', lambda *args: None)
    return data.resolve(), lease


def frozen_index(tmp_path, layout):
    data, lease = layout
    manifest = source.freeze(data, tmp_path / 'freeze', controls=[], guard=lambda: None, inherited_lease=lease)
    return manifest, PackIndex(tmp_path / 'packs.sqlite', manifest['files'], lambda: None, data=data)


def test_real_zstd_lossless_complete_backup_and_fresh_readback_resume(tmp_path, layout):
    data, lease = layout
    drive = Drive()
    before = {p.relative_to(data).as_posix(): p.read_bytes() for p in data.rglob('*') if p.is_file()}
    result = pipeline.run(data, tmp_path / 'first', drive, controls=[], inherited_lease=lease, guard=lambda: None)
    assert result['encrypted'] is False
    assert result['resource_acceptance'] == 'EXTERNAL_REQUIRED'
    assert result['files_verified'] == 4  # raw, text, consistent SQLite + original SQLite
    catalog = json.loads(drive.objects[result['catalog_path']])
    assert sum(v['verification']['files_verified'] for v in catalog['packs']) == 4
    assert sum(v['verification']['databases_verified'] for v in catalog['packs']) == 1
    assert catalog['excluded_count'] == result['excluded_paths']
    first_objects = dict(drive.objects)
    uploaded = len(drive.uploads)
    drive.reads.clear()
    second = pipeline.run(data, tmp_path / 'second', drive, controls=[], inherited_lease=lease, guard=lambda: None)
    assert second['catalog_sha256'] == result['catalog_sha256']
    assert drive.objects == first_objects
    assert len(drive.uploads) == uploaded + 2  # same create-only file index/catalog; no pack uploads
    assert sum(v.endswith('.tar.zst') for v in drive.reads) == 2
    assert {p.relative_to(data).as_posix(): p.read_bytes() for p in data.rglob('*') if p.is_file()} == before
    lines = drive.objects[result['file_index']['path']].splitlines()
    records = [json.loads(value) for value in lines[1:]]
    assert len(records) == result['file_index']['records'] == 4
    original = next(v for v in records if v['sqlite_original'])
    assert original['source_relative'] == 'state/control.sqlite'
    assert original['representation'] == 'exact_source_bytes'
    assert next(v for v in records if v['sqlite'])['representation'] == 'sqlite_committed_view'


def test_default_freeze_keeps_original_production_lock_and_typed_inheritance(tmp_path, layout):
    data, lease = layout
    with patch.object(source, 'production_lock', side_effect=RuntimeError('native occupied')):
        with pytest.raises(RuntimeError, match='native occupied'):
            source.freeze(data, tmp_path / 'ordinary', controls=[], guard=lambda: None)
        manifest = source.freeze(data, tmp_path / 'inherited', controls=[], guard=lambda: None, inherited_lease=lease)
        manifest['files'].index.close()
    with pytest.raises(ValueError, match='typed verified'):
        source.freeze(data, tmp_path / 'untyped', controls=[], guard=lambda: None, inherited_lease=object())


def test_corrupt_cloud_upload_never_publishes_descriptor_or_catalog(tmp_path, layout):
    data, lease = layout
    drive = Drive(); drive.corrupt = True
    with pytest.raises(ValueError, match='compressed bytes'):
        pipeline.run(data, tmp_path / 'operation', drive, controls=[], inherited_lease=lease, guard=lambda: None)
    assert not any(v.endswith('descriptor.json') or v.startswith('catalogs/') for v in drive.objects)
    assert not (tmp_path / 'operation/candidate.json').exists()


def test_partial_upload_resume_reuses_exact_archive_without_replacement(tmp_path, layout):
    data, lease = layout
    drive = Drive()
    pipeline.run(data, tmp_path / 'first', drive, controls=[], inherited_lease=lease, guard=lambda: None)
    for key in list(drive.objects):
        if key.endswith('descriptor.json') or key.startswith('catalogs/'):
            del drive.objects[key]  # Test an interrupted remote, not application deletion.
    originals = dict(drive.objects)
    pipeline.run(data, tmp_path / 'second', drive, controls=[], inherited_lease=lease, guard=lambda: None)
    assert all(drive.objects[key] == value for key, value in originals.items())


def test_unknown_source_namespace_refuses_before_cloud_io(tmp_path, layout):
    data, lease = layout
    (data / 'unknown').mkdir()
    drive = Drive()
    with pytest.raises(ValueError, match='unclassified'):
        pipeline.run(data, tmp_path / 'operation', drive, controls=[], inherited_lease=lease, guard=lambda: None)
    assert drive.uploads == drive.reads == []


def test_no_plain_run_without_host_admission(tmp_path, layout):
    data, _ = layout
    with pytest.raises(ValueError, match='host admission'):
        pipeline.run(data, tmp_path / 'operation', Drive(), controls=[], inherited_lease=None, guard=lambda: None)
    assert not (tmp_path / 'operation').exists()


def test_guard_interrupt_retains_sources_and_no_catalog(tmp_path, layout):
    data, lease = layout
    drive = Drive()
    count = 0
    def guard():
        nonlocal count
        count += 1
        if count > 25:
            raise RuntimeError('owned runtime deadline')
    with pytest.raises(RuntimeError, match='deadline'):
        pipeline.run(data, tmp_path / 'operation', drive, controls=[], inherited_lease=lease, guard=guard)
    assert not any(v.startswith('catalogs/') for v in drive.objects)
    assert (data / 'runs/2026-10-24/raw/bytes.bin').stat().st_size == 8192


def test_pack_ids_and_bytes_ignore_private_staging_paths(tmp_path, layout):
    manifest, index = frozen_index(tmp_path, layout)
    try:
        group = next(index.groups())
        a, b = tmp_path / 'a', tmp_path / 'b'; a.mkdir(); b.mkdir()
        first, second = build_pack(index, group, a, lambda: None), build_pack(index, group, b, lambda: None)
        assert first == second
        assert (a / 'archive.tar.zst').read_bytes() == (b / 'archive.tar.zst').read_bytes()
    finally:
        index.close(); manifest['files'].index.close()


def test_source_directory_addition_is_not_silently_omitted(tmp_path, layout):
    manifest, index = frozen_index(tmp_path, layout)
    try:
        (layout[0] / 'runs/2026-10-24/raw/late.bin').write_bytes(b'late input')
        with pytest.raises(ValueError, match='membership'):
            index.verify_directories(lambda: None)
    finally:
        index.close(); manifest['files'].index.close()


def test_frame_checksum_truncation_refused_even_if_descriptor_hash_is_updated(tmp_path, layout):
    manifest, index = frozen_index(tmp_path, layout)
    try:
        group = next(index.groups()); packed = tmp_path / 'packed'; packed.mkdir()
        desc = build_pack(index, group, packed, lambda: None)
        archive = packed / 'archive.tar.zst'
        archive.write_bytes(archive.read_bytes()[:-1])
        desc.update(archive_bytes=archive.stat().st_size, archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
        scratch = tmp_path / 'scratch'; scratch.mkdir()
        with pytest.raises(ValueError, match='checksum'):
            verify_pack(archive, desc, index, group, scratch, lambda: None)
    finally:
        index.close(); manifest['files'].index.close()


def test_tar_metadata_tamper_refused_independent_of_compressed_digest(tmp_path, layout):
    manifest, index = frozen_index(tmp_path, layout)
    try:
        group = next(index.groups()); packed = tmp_path / 'packed'; packed.mkdir()
        desc = build_pack(index, group, packed, lambda: None)
        archive = packed / 'archive.tar.zst'
        with zstandard.ZstdDecompressor().stream_reader(archive.open('rb')) as reader:
            raw = reader.read()
        # Rebuild a valid compressed archive with altered ownership metadata.
        altered = io.BytesIO()
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as old, tarfile.open(fileobj=altered, mode='w', format=tarfile.PAX_FORMAT) as new:
            for n, member in enumerate(old):
                if n == 1: member.uid += 1
                new.addfile(member, old.extractfile(member))
        archive.write_bytes(zstandard.ZstdCompressor(write_checksum=True).compress(altered.getvalue()))
        desc.update(archive_bytes=archive.stat().st_size, archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
        scratch = tmp_path / 'scratch'; scratch.mkdir()
        with pytest.raises(ValueError, match='metadata'):
            verify_pack(archive, desc, index, group, scratch, lambda: None)
    finally:
        index.close(); manifest['files'].index.close()


def test_classification_retains_failed_observation_and_revision_identity():
    assert group_for('data/runs/2026-10-24/_observations/obs-a/raw/failure.json') == 'observations/2026-10-24/obs-a'
    assert group_for('data/runs/2026-10-24/_revisions/rev-b/raw.json') == 'revisions/2026-10-24/rev-b'
    assert group_for('sqlite-original/data/runs/2026-10-24/_exports/a.sqlite-wal') == 'dates/2026-10-24/base'
    assert group_for('data/runs-archive/_broken-day/error.bin') == 'archive/_broken-day'


@pytest.mark.skipif(os.name != 'posix', reason='private credential mode proof is Linux-only')
def test_transport_rejects_other_folders_scopes_and_mutating_object_paths(tmp_path):
    config = tmp_path / 'rclone.conf'
    config.write_text('[approved]\ntype=drive\nscope=drive.file\ntoken={"refresh_token":"test-only"}\n')
    config.chmod(0o600)
    transport = Rclone(config.resolve(), 'approved:plaintext-recovery', 'root-folder-id-for-protocol-test', lambda: None)
    for path in ('../restic/config', 'packs/evil', 'catalogs/latest.json'):
        with pytest.raises(ValueError): transport.path(path)
    for remote in ('approved:AR-local Pi Backups/restic', 'approved:other/../plaintext-recovery'):
        with pytest.raises(ValueError): Rclone(config.resolve(), remote, 'root-folder-id-for-protocol-test', lambda: None)
    config.write_text(config.read_text().replace('drive.file', 'drive'))
    with pytest.raises(ValueError, match='drive.file'):
        Rclone(config.resolve(), 'approved:plaintext-recovery', 'root-folder-id-for-protocol-test', lambda: None)


def test_bounded_stream_rejects_unbounded_and_excess_output():
    guarded = Guarded(io.BytesIO(b'0123456789'), lambda: None, limit=5)
    with pytest.raises(ValueError, match='unbounded'): guarded.read()
    with pytest.raises(ValueError, match='manifest bound'): guarded.read(10)


def test_inherited_guard_revalidates_and_never_unlinks(layout, monkeypatch):
    _, lease = layout
    calls = []
    monkeypatch.setattr(AttestedHostLease, 'verify', lambda *args: calls.append('verified'))
    with lease.hold(layout[0]): calls.append('work')
    assert calls == ['verified', 'work', 'verified']


def test_transport_uses_fixed_executable_and_clean_environment(monkeypatch, tmp_path):
    monkeypatch.setenv('LD_PRELOAD', 'untrusted-library')
    monkeypatch.setenv('RCLONE_CONFIG_PASS', 'untrusted-hook')
    monkeypatch.setattr(remote_transport, 'protected_file', lambda *_: None)
    monkeypatch.setattr(remote_transport, 'Path', lambda value: SimpleNamespace(resolve=lambda **kwargs: '/usr/bin/rclone')
                        if str(value) == '/usr/bin/rclone' else Path(value))
    observed = {}
    class Child:
        returncode = 0
        def poll(self): return 0
    def spawn(args, **kwargs):
        observed.update(args=args, **kwargs)
        return Child()
    monkeypatch.setattr(remote_transport.subprocess, 'Popen', spawn)
    transport = Rclone.__new__(Rclone)
    transport.guard = lambda: None
    transport.executable = '/usr/bin/rclone'
    transport.config = tmp_path / 'private.conf'
    transport.remote = 'approved:plaintext-recovery'
    transport.root_folder_id = 'root-folder-id-for-protocol-test'
    local = tmp_path / 'source'; local.write_bytes(b'protocol fixture')
    assert transport.upload('catalogs/' + 'a' * 64 + '.json', local)
    assert observed['args'][0] == '/usr/bin/rclone'
    assert '--immutable' in observed['args'] and '--ignore-existing' in observed['args']
    assert observed['args'][-3:] == ['--', str(local), transport.remote + '/catalogs/' + 'a' * 64 + '.json']
    assert observed['args'][observed['args'].index('--drive-root-folder-id') + 1] == transport.root_folder_id
    assert 'LD_PRELOAD' not in observed['env'] and 'RCLONE_CONFIG_PASS' not in observed['env']


def test_exact_exclusion_paths_and_digest_are_offsite(tmp_path, layout):
    data, lease = layout
    (data / 'runs/2026-10-24/raw/omitted.key').write_bytes(b'generic excluded material')
    drive = Drive()
    receipt = pipeline.run(data, tmp_path / 'operation', drive, controls=[], inherited_lease=lease, guard=lambda: None)
    catalog = json.loads(drive.objects[receipt['catalog_path']])
    assert catalog['excluded_paths'] == ['runs/2026-10-24/raw/omitted.key']
    expected = hashlib.sha256(b'"runs/2026-10-24/raw/omitted.key"\n').hexdigest()
    assert catalog['excluded_sha256'] == receipt['excluded_sha256'] == expected
