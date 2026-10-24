"""Deterministic unencrypted tar.zst recovery packs with streaming verification."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import tarfile
import stat

import zstandard

from pi_drive_backup_manifest import encoded
from pi_drive_backup_source import digest, fingerprint, regular, sqlite_checks
from pi_drive_backup_read import chunks, discard_created_cache
from pi_laptop_backup_source import validate_archive_path

MANIFEST = '.ar-local-pack-manifest.json'
SCHEMA = 'ar-local-plain-pack-v1'
BLOCK = 1024 * 1024


def metadata(row):
    value = {k: row[k] for k in ('logical_path', 'sha256', 'size', 'mode', 'uid', 'gid', 'sqlite')}
    value['mtime_ns'] = row['source_identity'][1]
    value['sqlite_original'] = bool(row.get('sqlite_original', False))
    return value


def group_for(logical):
    parts = PurePosixPath(logical).parts
    if parts and parts[0] == 'sqlite-original':
        parts = parts[1:]
    if len(parts) > 3 and parts[:2] == ('data', 'runs'):
        if len(parts) > 5 and parts[3] in ('_observations', '_revisions'):
            return '/'.join((parts[3][1:], parts[2], parts[4]))
        return 'dates/' + parts[2] + '/base'
    if len(parts) > 3 and parts[:2] == ('data', 'runs-archive'):
        return 'archive/' + parts[2]
    return 'control'


class PackIndex:
    def __init__(self, path, rows, guard, data=None):
        with Path(path).open('xb'):
            pass
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA cache_size=-2048')
        self.db.execute('PRAGMA temp_store=FILE')
        self.db.execute('CREATE TABLE rows (group_key TEXT, logical TEXT PRIMARY KEY, value TEXT)')
        self.db.execute('CREATE INDEX grouped ON rows(group_key,logical)')
        self.db.execute('CREATE TABLE source_dirs (path TEXT PRIMARY KEY, identity TEXT)')
        self.db.execute('CREATE TABLE verified_packs (group_key TEXT PRIMARY KEY, pack_id TEXT)')
        for number, row in enumerate(rows):
            guard()
            validate_archive_path(row['logical_path'], {})
            if len(row['logical_path'].encode('utf-8')) > 4096 or type(row['size']) is not int or row['size'] < 0:
                raise ValueError('invalid archive path/size')
            self.db.execute('INSERT INTO rows VALUES(?,?,?)',
                (group_for(row['logical_path']), row['logical_path'], encoded(row).decode()))
            if row.get('direct') and data is not None:
                parent = Path(row['source_path']).parent
                while parent != data:
                    if data not in parent.parents:
                        raise ValueError('direct source escaped authoritative data')
                    info = parent.lstat()
                    if not stat.S_ISDIR(info.st_mode):
                        raise ValueError('direct source ancestor is not a real directory')
                    value = [info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns]
                    self.db.execute('INSERT OR IGNORE INTO source_dirs VALUES(?,?)', (str(parent), json.dumps(value)))
                    parent = parent.parent
            if number % 256 == 0:
                self.db.commit()
        self.db.commit()

    def groups(self):
        yield from (v[0] for v in self.db.execute('SELECT DISTINCT group_key FROM rows ORDER BY group_key'))

    def rows(self, group):
        for (raw,) in self.db.execute('SELECT value FROM rows WHERE group_key=? ORDER BY logical', (group,)):
            yield json.loads(raw)

    def identity(self, group, guard):
        sha = hashlib.sha256()
        sha.update(encoded({'group': group, 'schema': SCHEMA}) + b'\n')
        count = size = 0
        for row in self.rows(group):
            guard()
            sha.update(encoded(metadata(row)) + b'\n')
            count += 1
            size += row['size']
        return dict(pack_id=sha.hexdigest(), group=group, files=count, source_bytes=size)

    def close(self):
        self.db.close()

    def verify_directories(self, guard):
        for name, value in self.db.execute('SELECT path,identity FROM source_dirs'):
            guard()
            info = Path(name).lstat()
            if not stat.S_ISDIR(info.st_mode) or [info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns] != json.loads(value):
                raise ValueError('immutable source directory membership changed')

    def registered(self, group, pack_id):
        self.db.execute('INSERT INTO verified_packs VALUES(?,?)', (group, pack_id))
        self.db.commit()

    def file_index(self, path, data, guard):
        count = 0
        with path.open('xb') as output:
            output.write(encoded({'schema': 'ar-local-plain-file-index-v1', 'data_root': data.as_posix()}) + b'\n')
            query = '''SELECT r.value,v.pack_id FROM rows r JOIN verified_packs v
                       ON r.group_key=v.group_key ORDER BY r.logical'''
            for raw, pack_id in self.db.execute(query):
                guard()
                row = json.loads(raw)
                source = Path(row['source_path'])
                if data not in source.parents:
                    continue  # Non-secret external controls stay in their packs.
                value = metadata(row)
                value.update(source_relative=source.relative_to(data).as_posix(), pack_id=pack_id,
                    representation='sqlite_committed_view' if row['sqlite'] and not row['direct']
                    and not row.get('sqlite_original') else 'exact_source_bytes')
                output.write(encoded(value) + b'\n')
                count += 1
            discard_created_cache(output)
        sha = digest(path, guard)
        return dict(path='manifests/' + sha + '.jsonl', sha256=sha,
            bytes=path.stat().st_size, records=count, schema='ar-local-plain-file-index-v1', data_root=data.as_posix())


class Guarded:
    def __init__(self, stream, guard, limit=None):
        self.stream, self.guard, self.limit, self.count = stream, guard, limit, 0

    def read(self, size=-1):
        self.guard()
        if size < 0 or size > BLOCK:
            raise ValueError('unbounded archive read')
        value = self.stream.read(size)
        self.count += len(value)
        if self.limit is not None and self.count > self.limit:
            raise ValueError('archive decompression exceeds manifest bound')
        self.guard()
        return value

    def write(self, value):
        self.guard()
        result = self.stream.write(value)
        self.guard()
        return result


class ColdReader:
    """Adapt bounded cache-advised chunks to tar/zstd's smaller read requests."""
    def __init__(self, stream):
        self.blocks, self.pending = iter(chunks(stream)), b''

    def read(self, size):
        if not 0 <= size <= BLOCK:
            raise ValueError('unbounded cold archive read')
        result = bytearray()
        while len(result) < size:
            if not self.pending:
                self.pending = next(self.blocks, b'')
                if not self.pending:
                    break
            count = min(size - len(result), len(self.pending))
            result.extend(self.pending[:count])
            self.pending = self.pending[count:]
        return bytes(result)


def write_manifest(path, index, group, identity, guard):
    with path.open('xb') as output:
        output.write(b'{"identity":' + encoded(identity) + b',"schema":' + encoded(SCHEMA) + b',"files":[')
        for number, row in enumerate(index.rows(group)):
            guard()
            if number:
                output.write(b',')
            output.write(encoded(metadata(row)))
        output.write(b']}\n')
        discard_created_cache(output)


def header(name, row):
    info = tarfile.TarInfo(name)
    info.size, info.mode = row['size'], int(row['mode'], 8)
    info.uid, info.gid = row['uid'], row['gid']
    ns = row['mtime_ns']
    info.mtime = ns // 10**9
    info.pax_headers = {'mtime': f'{ns // 10**9}.{ns % 10**9:09d}'}
    return info


def build_pack(index, group, directory, guard):
    identity = index.identity(group, guard)
    manifest = directory / 'manifest.json'
    write_manifest(manifest, index, group, identity, guard)
    archive = directory / 'archive.tar.zst'
    with archive.open('xb') as output:
        compressor = zstandard.ZstdCompressor(level=15, threads=0, write_checksum=True, write_content_size=False)
        with compressor.stream_writer(Guarded(output, guard), closefd=False) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.PAX_FORMAT) as tar:
                with manifest.open('rb') as source:
                    info = tarfile.TarInfo(MANIFEST)
                    info.size, info.mode = manifest.stat().st_size, 0o600
                    tar.addfile(info, Guarded(source, guard))
                for row in index.rows(group):
                    guard()
                    path = Path(row['backup_path'])
                    regular(path)
                    before = fingerprint(path)
                    with path.open('rb') as source:
                        tar.addfile(header(row['logical_path'], metadata(row)), Guarded(ColdReader(source), guard))
                    if fingerprint(path) != before:
                        raise RuntimeError('pack source changed during compression')
        discard_created_cache(output)
    descriptor = dict(identity, schema=SCHEMA, compression='zstd-lossless-no-encryption',
        archive_sha256=digest(archive, guard), archive_bytes=archive.stat().st_size,
        manifest_sha256=digest(manifest, guard), manifest_bytes=manifest.stat().st_size)
    return descriptor


def validate_frame(path, guard):
    """Require one complete checksummed frame, including its final four bytes.

    stream_reader can return EOF on a truncated frame; tar EOF must not hide a
    missing Zstd checksum or an additional frame. Payload CRC is checked by the
    actual decoder below; this bounded parser checks framing/completeness.
    """
    with path.open('rb') as source:
        guard()
        first = source.read(18)
        parameters = zstandard.get_frame_parameters(first)
        if parameters.window_size > 128 * 1024 * 1024 or not parameters.has_checksum or parameters.dict_id:
            raise ValueError('unexpected recovery compression frame')
        source.seek(zstandard.frame_header_size(first))
        cold = ColdReader(source)
        while True:
            guard()
            raw = cold.read(3)
            if len(raw) != 3:
                raise ValueError('truncated Zstd block header')
            value = int.from_bytes(raw, 'little')
            last, kind, size = value & 1, (value >> 1) & 3, value >> 3
            if kind == 3 or size > 128 * 1024:
                raise ValueError('invalid Zstd block')
            length = 1 if kind == 1 else size
            if len(cold.read(length)) != length:
                raise ValueError('truncated Zstd block payload')
            if last:
                break
        if len(cold.read(4)) != 4 or cold.read(1):
            raise ValueError('missing checksum or extra Zstd frame/trailing bytes')


def verify_pack(archive, descriptor, index, group, scratch, guard):
    expected = index.identity(group, guard)
    keys = {*expected, 'schema', 'compression', 'archive_sha256', 'archive_bytes', 'manifest_sha256', 'manifest_bytes'}
    if (not isinstance(descriptor, dict) or set(descriptor) != keys
            or descriptor.get('schema') != SCHEMA or descriptor.get('compression') != 'zstd-lossless-no-encryption'
            or any(descriptor.get(k) != v for k, v in expected.items())
            or type(descriptor.get('archive_bytes')) is not int or descriptor['archive_bytes'] <= 0
            or type(descriptor.get('manifest_bytes')) is not int or descriptor['manifest_bytes'] <= 0
            or archive.stat().st_size != descriptor['archive_bytes']
            or digest(archive, guard) != descriptor['archive_sha256']):
        raise ValueError('cloud recovery pack identity or compressed bytes differ')
    # Independently reconstruct the manifest, instead of trusting its cloud digest.
    expected_manifest = scratch / 'expected-manifest.json'
    write_manifest(expected_manifest, index, group, expected, guard)
    if (expected_manifest.stat().st_size != descriptor['manifest_bytes']
            or digest(expected_manifest, guard) != descriptor['manifest_sha256']):
        raise ValueError('cloud manifest identity differs from frozen source')
    limit = expected['source_bytes'] + descriptor['manifest_bytes'] + (expected['files'] + 1) * 8192 + 65536
    checked = databases = 0
    sqlite_digest = hashlib.sha256()
    validate_frame(archive, guard)
    with archive.open('rb') as source:
        # zstandard's native binding enforces this argument against frame bytes.
        decoder = zstandard.ZstdDecompressor(max_window_size=128 * 1024 * 1024)
        with decoder.stream_reader(Guarded(ColdReader(source), guard), read_across_frames=True) as decoded:
            bounded = Guarded(decoded, guard, limit)
            with tarfile.open(fileobj=bounded, mode='r|') as tar:
                member = tar.next()
                if member is None or member.name != MANIFEST or not member.isfile() or member.size != descriptor['manifest_bytes']:
                    raise ValueError('pack manifest is absent or unsafe')
                manifest_hash = hashlib.sha256()
                with tar.extractfile(member) as stream:
                    for block in iter(lambda: stream.read(BLOCK), b''):
                        guard(); manifest_hash.update(block)
                if manifest_hash.hexdigest() != descriptor['manifest_sha256']:
                    raise ValueError('embedded manifest bytes differ')
                for row in index.rows(group):
                    guard()
                    member = tar.next()
                    value = metadata(row)
                    expected_header = header(row['logical_path'], value)
                    if (member is None or not member.isfile() or member.name != row['logical_path']
                            or (member.size, member.mode, member.uid, member.gid) !=
                            (expected_header.size, expected_header.mode, expected_header.uid, expected_header.gid)
                            or member.pax_headers.get('mtime') != expected_header.pax_headers['mtime']
                            or set(member.pax_headers) - {'mtime', 'path'} or member.linkname):
                        raise ValueError('tar member order/type/path/metadata differs')
                    sha = hashlib.sha256()
                    temporary = scratch / 'database.sqlite'
                    output = temporary.open('xb') if row['sqlite'] else None
                    try:
                        with tar.extractfile(member) as stream:
                            for block in iter(lambda: stream.read(BLOCK), b''):
                                guard(); sha.update(block)
                                if output:
                                    output.write(block)
                        if output:
                            discard_created_cache(output); output.close(); output = None
                        if sha.hexdigest() != row['sha256']:
                            raise ValueError('restored member SHA-256 differs')
                        if row['sqlite']:
                            check = sqlite_checks(temporary)
                            sqlite_digest.update(encoded({'logical_path': row['logical_path'], **check}) + b'\n')
                            databases += 1
                    finally:
                        if output:
                            output.close()
                        if row['sqlite']:
                            temporary.unlink(missing_ok=True)
                    checked += 1
                if tar.next() is not None:
                    raise ValueError('pack contains an extra unselected member')
            # Drain through the frame checksum; tar's end marker alone is insufficient.
            for block in iter(lambda: bounded.read(BLOCK), b''):
                if any(block):
                    raise ValueError('nonzero trailing bytes after tar archive')
    return dict(files_verified=checked, databases_verified=databases,
        sqlite_checks_sha256=sqlite_digest.hexdigest(), archive_sha256=descriptor['archive_sha256'])
