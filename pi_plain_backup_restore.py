"""Restore unencrypted Drive recovery packs into a NEW private local workspace.

This tool reads a downloaded object mirror; it has no upload, device, overwrite,
or production-root mode. Exact SQLite/WAL bytes and committed views stay separate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import tarfile
import time
from contextlib import closing

import zstandard

from pi_drive_backup_manifest import _Reader, encoded
from pi_laptop_backup_source import validate_archive_path

BLOCK = 1024 * 1024
PACK_SCHEMA = 'ar-local-plain-pack-v1'
MANIFEST = '.ar-local-pack-manifest.json'
META_KEYS = {'logical_path', 'sha256', 'size', 'mode', 'mtime_ns', 'uid', 'gid', 'sqlite', 'sqlite_original'}


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON field')
        result[key] = value
    return result


def safe_relative(value):
    if not isinstance(value, str) or '\\' in value or len(value.encode('utf-8')) > 4096:
        raise ValueError('invalid recovery relative path')
    validate_archive_path(value, {})
    if str(PurePosixPath(value)) != value:
        raise ValueError('noncanonical recovery path')
    return value


def hexadecimal(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('invalid recovery SHA-256')
    return value


def regular(path):
    path = Path(path)
    info = path.lstat()
    if path.resolve() != path or not stat.S_ISREG(info.st_mode):
        raise ValueError('recovery input must be a canonical regular file')
    return info


def digest(path, guard):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(BLOCK), b''):
            guard(); value.update(block)
    return value.hexdigest()


class Guarded:
    def __init__(self, stream, guard, limit=None):
        self.stream, self.guard, self.limit, self.count = stream, guard, limit, 0

    def read(self, size):
        self.guard()
        if not 0 <= size <= BLOCK:
            raise ValueError('unbounded recovery read')
        value = self.stream.read(size)
        self.count += len(value)
        if self.limit is not None and self.count > self.limit:
            raise ValueError('recovery exceeds declared byte bound')
        self.guard()
        return value


class BoundedTarInfo(tarfile.TarInfo):
    def _proc_member(self, archive):
        # tarfile otherwise buffers an entire extension before returning its
        # member, even in stream mode. Our producer needs only small local PAX.
        if self.type == tarfile.XHDTYPE:
            if self.size > 16384:
                raise ValueError('oversized recovery PAX header')
        elif self.type not in (tarfile.REGTYPE, tarfile.AREGTYPE):
            raise ValueError('unsupported recovery tar header type')
        return super()._proc_member(archive)


def object_arrays(path, handlers, guard):
    """Stream top-level arrays to disk; each JSON record is bounded to 16 MiB."""
    document = {}
    with Path(path).open(encoding='utf-8') as stream:
        reader = _Reader(Guarded(stream, guard))
        reader.decoder = json.JSONDecoder(object_pairs_hook=no_duplicates)
        reader.expect('{')
        while reader.peek() != '}':
            key = reader.value()
            if not isinstance(key, str) or key in document:
                raise ValueError('duplicate or invalid recovery document field')
            reader.expect(':')
            if key in handlers:
                reader.expect('[')
                count = 0
                while reader.peek() != ']':
                    guard(); handlers[key](reader.value()); count += 1
                    if reader.peek() != ']':
                        reader.expect(',')
                reader.expect(']')
                document[key] = count
            else:
                document[key] = reader.value()
            if reader.peek() != '}':
                reader.expect(',')
        reader.expect('}')
        if reader.peek():
            raise ValueError('trailing recovery document content')
    return document


def check_metadata(row):
    if not isinstance(row, dict) or set(row) != META_KEYS:
        raise ValueError('unsupported recovery file metadata')
    safe_relative(row['logical_path']); hexadecimal(row['sha256'])
    for field in ('size', 'uid', 'gid', 'mtime_ns'):
        if type(row[field]) is not int:
            raise ValueError('invalid integer recovery metadata')
    if row['size'] < 0 or not all(0 <= row[k] < 2**32 for k in ('uid', 'gid')) or not -2**63 < row['mtime_ns'] < 2**63:
        raise ValueError('out of range recovery metadata')
    if not isinstance(row['mode'], str) or not re.fullmatch('0o[0-7]{1,4}', row['mode']):
        raise ValueError('invalid octal recovery mode')
    if type(row['sqlite']) is not bool or type(row['sqlite_original']) is not bool:
        raise ValueError('invalid SQLite representation flag')


def sqlite_proof(path, guard):
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        db.execute('PRAGMA cache_size=-4096')
        db.set_progress_handler(lambda: (guard(), 0)[1], 10000)
        integrity = db.execute('PRAGMA integrity_check').fetchmany(2)
        foreign = db.execute('PRAGMA foreign_key_check').fetchmany(1)
        if integrity != [('ok',)] or foreign:
            raise ValueError('restored SQLite integrity or foreign-key failure')
        tables = []
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            guard(); tables.append(row[0])
            if len(tables) > 100000:
                raise ValueError('SQLite table inventory exceeds restore bound')
    return {'integrity_check': 'ok', 'foreign_key_check': 'ok', 'tables': tables}


def database(work):
    db = sqlite3.connect(work / 'restore-index.sqlite')
    db.execute('PRAGMA cache_size=-4096')
    db.execute('PRAGMA temp_store=FILE')
    db.execute('CREATE TABLE packs(id TEXT PRIMARY KEY, value TEXT)')
    db.execute('CREATE TABLE mappings(logical TEXT PRIMARY KEY, destination TEXT UNIQUE, value TEXT, restored INTEGER DEFAULT 0)')
    db.execute('CREATE TABLE files(logical TEXT PRIMARY KEY, folded TEXT UNIQUE, value TEXT)')
    return db


def load_catalog(path, expected, db, work, guard):
    regular(path)
    if digest(path, guard) != hexadecimal(expected):
        raise ValueError('catalog differs from independently recorded SHA-256')
    excluded = hashlib.sha256()
    with (work / 'excluded-paths.jsonl').open('xb') as output:
        def omitted(value):
            if not isinstance(value, str):
                raise ValueError('invalid exclusion evidence')
            raw = encoded(value) + b'\n'; output.write(raw); excluded.update(raw)
        def pack(value):
            descriptor = value['descriptor']
            hexadecimal(descriptor['pack_id'])
            db.execute('INSERT INTO packs VALUES (?,?)', (descriptor['pack_id'], encoded(value).decode()))
        result = object_arrays(path, {'packs': pack, 'excluded_paths': omitted}, guard)
    if (result.get('schema') != 'ar-local-plain-catalog-v1' or not result.get('packs')
            or result.get('excluded_paths') != result.get('excluded_count')
            or result.get('excluded_sha256') != excluded.hexdigest()):
        raise ValueError('catalog schema, pack set or exclusion proof differs')
    db.commit()
    return result


def mirror_object(root, relative):
    safe_relative(relative)
    path = root / relative
    regular(path)
    if root not in path.parents:
        raise ValueError('object escaped downloaded mirror')
    return path


def load_index(root, catalog, db, guard):
    descriptor = catalog['file_index']
    hexadecimal(descriptor['sha256'])
    if (descriptor['schema'] != 'ar-local-plain-file-index-v1'
            or descriptor['path'] != 'manifests/' + descriptor['sha256'] + '.jsonl'):
        raise ValueError('unsupported file-index descriptor')
    path = mirror_object(root, descriptor['path'])
    if path.stat().st_size != descriptor['bytes'] or digest(path, guard) != descriptor['sha256']:
        raise ValueError('file-index bytes differ from catalog')
    with path.open(encoding='utf-8') as stream:
        header = json.loads(stream.readline(65537), object_pairs_hook=no_duplicates)
        if header != {'schema': descriptor['schema'], 'data_root': descriptor['data_root']}:
            raise ValueError('file-index header differs')
        count = 0
        for line in iter(lambda: stream.readline(65537), ''):
            guard()
            if len(line) > 65536:
                raise ValueError('oversized file-index row')
            row = json.loads(line, object_pairs_hook=no_duplicates)
            if set(row) != META_KEYS | {'source_relative', 'pack_id', 'representation'}:
                raise ValueError('unsupported file-index row')
            check_metadata({k: row[k] for k in META_KEYS})
            relative = safe_relative(row['source_relative'])
            if not db.execute('SELECT 1 FROM packs WHERE id=?', (row['pack_id'],)).fetchone():
                raise ValueError('file-index refers to an absent pack')
            kind = row['representation']
            if kind not in ('exact_source_bytes', 'sqlite_committed_view'):
                raise ValueError('unknown file-index representation')
            if kind == 'sqlite_committed_view' and (not row['sqlite'] or row['sqlite_original']):
                raise ValueError('invalid committed SQLite mapping')
            expected = ('sqlite-original/data/' if row['sqlite_original'] else 'data/') + relative
            if row['logical_path'] != expected:
                raise ValueError('logical path differs from exact source mapping')
            destination = ('data/' if kind == 'exact_source_bytes' else 'committed-view/') + relative
            db.execute('INSERT INTO mappings(logical,destination,value) VALUES (?,?,?)',
                       (row['logical_path'], destination.casefold(), encoded(row).decode()))
            count += 1
    if count != descriptor['records']:
        raise ValueError('file-index record count differs')
    db.commit()
    return count


def frame(path, guard):
    """Require exactly one complete checksummed, dictionary-free Zstd frame."""
    with path.open('rb') as source:
        guard(); header = source.read(18)
        parameters = zstandard.get_frame_parameters(header)
        if parameters.window_size > 128 * 1024**2 or not parameters.has_checksum or parameters.dict_id:
            raise ValueError('unsupported recovery compression frame')
        source.seek(zstandard.frame_header_size(header))
        while True:
            guard(); raw = source.read(3)
            if len(raw) != 3:
                raise ValueError('truncated compression header')
            value = int.from_bytes(raw, 'little')
            last, kind, size = value & 1, value >> 1 & 3, value >> 3
            if kind == 3 or size > 128 * 1024:
                raise ValueError('invalid compression block')
            length = 1 if kind == 1 else size
            if len(source.read(length)) != length:
                raise ValueError('truncated compression block')
            if last:
                break
        if len(source.read(4)) != 4 or source.read(1):
            raise ValueError('missing compression checksum or extra frame')


def private_file(root, relative):
    safe_relative(relative)
    path = root / relative
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.resolve() != path or root not in path.parents:
        raise ValueError('restore output traverses a symlink')
    return path


def write_member(tar, member, target, guard, *, limit):
    if not member.isfile() or member.size > limit or member.size < 0 or member.linkname:
        raise ValueError('unsupported recovery member type/size')
    sha = hashlib.sha256()
    with tar.extractfile(member) as stream, target.open('xb') as output:
        os.chmod(target, 0o600)
        total = 0
        for block in iter(lambda: stream.read(BLOCK), b''):
            guard(); total += len(block)
            if total > member.size:
                raise ValueError('member exceeds declared length')
            output.write(block); sha.update(block)
        output.flush(); os.fsync(output.fileno())
    if total != member.size:
        raise ValueError('truncated recovery member')
    return sha.hexdigest()


def manifest_rows(path, descriptor, db, guard):
    identity = hashlib.sha256(encoded({'group': descriptor['group'], 'schema': PACK_SCHEMA}) + b'\n')
    counts = {'files': 0, 'source_bytes': 0, 'previous': ''}
    def row(value):
        check_metadata(value)
        logical = value['logical_path']
        if logical <= counts['previous']:
            raise ValueError('manifest paths are duplicated or unordered')
        counts['previous'] = logical
        identity.update(encoded(value) + b'\n')
        counts['files'] += 1; counts['source_bytes'] += value['size']
        db.execute('INSERT INTO files VALUES (?,?,?)', (logical, logical.casefold(), encoded(value).decode()))
    result = object_arrays(path, {'files': row}, guard)
    expected = {k: descriptor[k] for k in ('pack_id', 'group', 'files', 'source_bytes')}
    if (result.get('schema') != PACK_SCHEMA or result.get('identity') != expected
            or counts['files'] != expected['files'] or counts['source_bytes'] != expected['source_bytes']
            or identity.hexdigest() != expected['pack_id']):
        raise ValueError('embedded manifest content identity differs')
    db.commit()


def restore_pack(root, descriptor, db, work, guard):
    if descriptor['schema'] != PACK_SCHEMA or descriptor['compression'] != 'zstd-lossless-no-encryption':
        raise ValueError('unsupported recovery pack')
    for field in ('archive_sha256', 'manifest_sha256', 'pack_id'):
        hexadecimal(descriptor[field])
    for field in ('archive_bytes', 'manifest_bytes', 'source_bytes', 'files'):
        if type(descriptor[field]) is not int or descriptor[field] < (1 if field != 'source_bytes' else 0):
            raise ValueError('invalid pack byte/count bound')
    archive = mirror_object(root, 'packs/' + descriptor['pack_id'] + '/archive.tar.zst')
    if archive.stat().st_size != descriptor['archive_bytes'] or digest(archive, guard) != descriptor['archive_sha256']:
        raise ValueError('compressed pack SHA-256/size differs')
    frame(archive, guard)
    limit = descriptor['source_bytes'] + descriptor['manifest_bytes'] + (descriptor['files'] + 1) * 8192 + 65536
    checked = databases = 0
    sql = hashlib.sha256()
    with archive.open('rb') as source:
        decoder = zstandard.ZstdDecompressor(max_window_size=128 * 1024**2)
        with decoder.stream_reader(Guarded(source, guard), read_across_frames=True) as stream:
            bounded = Guarded(stream, guard, limit)
            with tarfile.open(fileobj=bounded, mode='r|', tarinfo=BoundedTarInfo) as tar:
                member = tar.next()
                if member is None or member.name != MANIFEST or member.size != descriptor['manifest_bytes']:
                    raise ValueError('missing recovery manifest')
                manifest = work / ('manifest-' + descriptor['pack_id'] + '.json')
                if write_member(tar, member, manifest, guard, limit=descriptor['manifest_bytes']) != descriptor['manifest_sha256']:
                    raise ValueError('embedded manifest SHA-256 differs')
                manifest_rows(manifest, descriptor, db, guard)
                for (raw,) in db.execute('SELECT value FROM files ORDER BY logical'):
                    row = json.loads(raw); member = tar.next()
                    stamp = row['mtime_ns']
                    seconds, nanos = divmod(abs(stamp), 10**9)
                    expected_mtime = f'{"-" if stamp < 0 else ""}{seconds}.{nanos:09d}'
                    if (member is None or member.name != row['logical_path']
                            or (member.size, member.mode, member.uid, member.gid) !=
                            (row['size'], int(row['mode'], 8), row['uid'], row['gid'])
                            or member.pax_headers.get('mtime') != expected_mtime
                            or set(member.pax_headers) - {'mtime', 'path'}):
                        raise ValueError('recovery member path/order/metadata differs')
                    target = private_file(work, 'logical/' + row['logical_path'])
                    if write_member(tar, member, target, guard, limit=row['size']) != row['sha256']:
                        raise ValueError('restored file SHA-256 differs')
                    os.utime(target, ns=(row['mtime_ns'], row['mtime_ns']))
                    mapping = db.execute('SELECT value FROM mappings WHERE logical=?', (row['logical_path'],)).fetchone()
                    if mapping:
                        mapped = json.loads(mapping[0])
                        if mapped['pack_id'] != descriptor['pack_id'] or any(mapped[k] != row[k] for k in META_KEYS):
                            raise ValueError('file-index metadata differs from restored pack')
                        db.execute('UPDATE mappings SET restored=1 WHERE logical=?', (row['logical_path'],))
                    elif row['logical_path'].startswith(('data/', 'sqlite-original/data/')):
                        raise ValueError('data member is absent from file-index')
                    if row['sqlite']:
                        check = sqlite_proof(target, guard)
                        sql.update(encoded({'logical_path': row['logical_path'], **check}) + b'\n'); databases += 1
                    checked += 1
                    tar.members.clear()
                if tar.next() is not None:
                    raise ValueError('extra unselected recovery member')
                tar.members.clear()
            for block in iter(lambda: bounded.read(BLOCK), b''):
                if any(block):
                    raise ValueError('nonzero bytes after recovery tar')
    db.execute('DELETE FROM files'); db.commit()
    return {'files_verified': checked, 'databases_verified': databases,
            'sqlite_checks_sha256': sql.hexdigest(), 'archive_sha256': descriptor['archive_sha256']}


def materialize(db, work, guard, apply_metadata):
    count = 0
    with (work / 'restored-files.jsonl').open('xb') as receipt:
        for logical, raw, restored in db.execute('SELECT logical,value,restored FROM mappings ORDER BY logical'):
            guard()
            if not restored:
                raise ValueError('file-index references a missing restored member')
            row = json.loads(raw)
            relative = ('data/' if row['representation'] == 'exact_source_bytes' else 'committed-view/') + row['source_relative']
            target = private_file(work, relative)
            original = work / 'logical' / logical
            os.link(original, target)  # Links exist only within this new private workspace.
            if apply_metadata:
                os.chown(target, row['uid'], row['gid'], follow_symlinks=False)
                os.chmod(target, int(row['mode'], 8), follow_symlinks=False)
                actual = target.stat()
                if (actual.st_uid, actual.st_gid, stat.S_IMODE(actual.st_mode), actual.st_mtime_ns) != (
                        row['uid'], row['gid'], int(row['mode'], 8), row['mtime_ns']):
                    raise ValueError('output filesystem cannot preserve exact mapped metadata')
            receipt.write(encoded(dict(row, restored_relative=relative)) + b'\n')
            count += 1
        receipt.flush(); os.fsync(receipt.fileno())
    return count


def windows_private_directory(path):
    """Atomically create only this new directory with a protected user/SYSTEM DACL."""
    import ctypes as ct
    from ctypes import wintypes as wt
    kernel, security = ct.WinDLL('kernel32', use_last_error=True), ct.WinDLL('advapi32', use_last_error=True)
    def api(dll, name, result, args):
        method = getattr(dll, name); method.restype = result; method.argtypes = args
        return method
    class Attributes(ct.Structure):
        _fields_ = [('length', wt.DWORD), ('descriptor', wt.LPVOID), ('inherit', wt.BOOL)]
    current = api(kernel, 'GetCurrentProcess', wt.HANDLE, [])
    token_open = api(security, 'OpenProcessToken', wt.BOOL, [wt.HANDLE, wt.DWORD, ct.POINTER(wt.HANDLE)])
    token_info = api(security, 'GetTokenInformation', wt.BOOL, [wt.HANDLE, ct.c_int, wt.LPVOID, wt.DWORD, ct.POINTER(wt.DWORD)])
    sid_text = api(security, 'ConvertSidToStringSidW', wt.BOOL, [wt.LPVOID, ct.POINTER(wt.LPWSTR)])
    descriptor = api(security, 'ConvertStringSecurityDescriptorToSecurityDescriptorW', wt.BOOL,
                     [wt.LPCWSTR, wt.DWORD, ct.POINTER(wt.LPVOID), ct.POINTER(wt.DWORD)])
    free = api(kernel, 'LocalFree', wt.LPVOID, [wt.LPVOID])
    close = api(kernel, 'CloseHandle', wt.BOOL, [wt.HANDLE])
    volume_path = api(kernel, 'GetVolumePathNameW', wt.BOOL, [wt.LPCWSTR, wt.LPWSTR, wt.DWORD])
    volume_info = api(kernel, 'GetVolumeInformationW', wt.BOOL,
        [wt.LPCWSTR, wt.LPWSTR, wt.DWORD, ct.POINTER(wt.DWORD), ct.POINTER(wt.DWORD), ct.POINTER(wt.DWORD), wt.LPWSTR, wt.DWORD])
    create = api(kernel, 'CreateDirectoryW', wt.BOOL, [wt.LPCWSTR, ct.POINTER(Attributes)])
    token, needed, text, sd = wt.HANDLE(), wt.DWORD(), wt.LPWSTR(), wt.LPVOID()
    root, flags = ct.create_unicode_buffer(32768), wt.DWORD()
    if not volume_path(str(path.parent), root, len(root)) or not volume_info(root.value, None, 0, None, None, ct.byref(flags), None, 0):
        raise ct.WinError(ct.get_last_error())
    if not flags.value & 0x8:  # FS_PERSISTENT_ACLS, required for descriptor enforcement.
        raise ValueError('restore output volume must support persistent Windows ACLs')
    if not token_open(current(), 0x8, ct.byref(token)):
        raise ct.WinError(ct.get_last_error())
    try:
        token_info(token, 1, None, 0, ct.byref(needed))  # TokenUser size query.
        if not 0 < needed.value <= 65536:
            raise ValueError('invalid Windows token user buffer')
        buffer = ct.create_string_buffer(needed.value)
        if not token_info(token, 1, buffer, needed, ct.byref(needed)) or not sid_text(ct.c_void_p.from_buffer(buffer), ct.byref(text)):
            raise ct.WinError(ct.get_last_error())
        sddl = f'D:P(A;OICI;FA;;;{text.value})(A;OICI;FA;;;SY)'
        if not descriptor(sddl, 1, ct.byref(sd), None):
            raise ct.WinError(ct.get_last_error())
        attributes = Attributes(ct.sizeof(Attributes), sd, False)
        if not create(str(path), ct.byref(attributes)):
            raise ct.WinError(ct.get_last_error())
    finally:
        if sd: free(sd)
        if text: free(ct.cast(text, wt.LPVOID))
        close(token)


def private_workspace(path):
    if os.name == 'nt':
        windows_private_directory(path)
        return 'WINDOWS_PROTECTED_USER_SYSTEM_DACL'
    path.mkdir(mode=0o700)
    return 'POSIX_0700'


def restore(mirror, catalog, catalog_sha256, workspace, *, guard, apply_metadata=False):
    mirror, catalog, work = Path(mirror), Path(catalog), Path(workspace)
    if not mirror.is_dir() or mirror.resolve() != mirror:
        raise ValueError('canonical downloaded object mirror required')
    if work.resolve() != work or work.exists() or work.is_symlink() or mirror == work or mirror in work.parents or work in mirror.parents:
        raise ValueError('new canonical workspace outside downloaded mirror required')
    if apply_metadata and (os.name != 'posix' or os.geteuid() != 0):
        raise ValueError('exact ownership/mode restoration requires explicit POSIX root invocation')
    guard(); privacy = private_workspace(work)
    os.environ['SQLITE_TMPDIR'] = str(work)
    db = database(work)
    try:
        document = load_catalog(catalog, catalog_sha256, db, work, guard)
        index_count = load_index(mirror, document, db, guard)
        files = packs = 0
        for (raw,) in db.execute('SELECT value FROM packs ORDER BY id'):
            guard(); pack = json.loads(raw)
            proof = restore_pack(mirror, pack['descriptor'], db, work, guard)
            if proof != pack['verification']:
                raise ValueError('independent restore proof differs from accepted catalog')
            files += proof['files_verified']; packs += 1
        mapped = materialize(db, work, guard, apply_metadata)
        if mapped != index_count:
            raise ValueError('restored mapping total differs')
        guard()
        result = dict(schema='ar-local-plain-restored-v1', result='FILES_RESTORED_VERIFIED',
            catalog_sha256=catalog_sha256, files_verified=files, packs_verified=packs,
            mapped_files=mapped, metadata='EXACT_MAPPED_FILE_OWNERSHIP_MODE' if apply_metadata else 'RECORDED_SAFE_MODE_0600',
            mtime='EXACT' if apply_metadata else 'APPLIED_WITH_PLATFORM_PRECISION_AND_RECORDED',
            workspace_privacy=privacy,
            directories='CREATED_PRIVATE_0700_OR_UMASK', xattrs='SYSTEM_IMAGE_RESTORE_MAP_REQUIRED',
            system_image='SEPARATE_REQUIRED', encrypted=False)
        with (work / 'restore-result.json').open('xb') as output:
            output.write(encoded(result) + b'\n'); output.flush(); os.fsync(output.fileno())
        return result
    finally:
        db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mirror', type=Path, required=True)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--catalog-sha256', required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--apply-metadata', action='store_true')
    parser.add_argument('--max-hours', type=float, default=24)
    parser.add_argument('--free-space-floor-mib', type=int, default=1024)
    args = parser.parse_args(argv)
    if not 0 < args.max_hours <= 48 or args.free_space_floor_mib < 64:
        raise ValueError('restore requires bounded duration and free-space floor')
    deadline = time.monotonic() + args.max_hours * 3600
    def guard():
        if time.monotonic() >= deadline:
            raise RuntimeError('restore deadline reached')
        disk = args.workspace if args.workspace.exists() else args.workspace.parent
        if shutil.disk_usage(disk).free < args.free_space_floor_mib * 1024**2:
            raise RuntimeError('restore free-space floor reached')
    result = restore(args.mirror, args.catalog, args.catalog_sha256, args.workspace,
                     guard=guard, apply_metadata=args.apply_metadata)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'result': 'FAIL', 'error_type': type(error).__name__}))
        raise SystemExit(2)
