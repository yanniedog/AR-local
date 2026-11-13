"""Qualify an already downloaded daily raw archive in a NEW private workspace.

No network, production writes, archive-progress updates or input cleanup. Bind the
exact retained PASS row by SHA256 and require its explicit observation generation.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tarfile
import time

import zstandard

from ar_local_restore_io import pinned_reader
from cdr_sqlite_budget import audit_budget
from cdr_export_contract import load_contract
from pi_daily_cdr_day_archive_ingest import require_generation
from pi_daily_cdr_day_archive_scope import require_day
from pi_daily_raw_restore_sqlite import verify_databases
from pi_plain_backup_restore import (
    BLOCK, BoundedTarInfo, Guarded, PRODUCTION_ROOTS, digest, frame, hexadecimal, no_duplicates,
    object_arrays, outside_production, private_file, private_workspace, regular,
    safe_relative, write_member,
)

SCHEMA = 'ar-local-daily-cdr-raw-record-v1'
SERIES = 'daily-cdr-raw-records'
RESULT_SCHEMA = 'ar-local-daily-raw-restore-v1'
ROW_KEYS = {'logical_path', 'sha256', 'size', 'mode', 'uid', 'gid', 'mtime_ns'}


@dataclass(frozen=True)
class Limits:
    archive_bytes: int = 16 * 1024**3
    unpacked_bytes: int = 64 * 1024**3
    manifest_bytes: int = 256 * 1024**2
    files: int = 500000
    seconds: int = 3600
    free_space_floor: int = 1024**3


class Budget:
    def __init__(self, work, limits):
        for name, value in asdict(limits).items():
            if type(value) is not int or value < (0 if name == 'free_space_floor' else 1):
                raise ValueError('invalid restore budget')
        self.work, self.limits = work, limits
        self.deadline, self.next_space_check = time.monotonic() + limits.seconds, 0

    def __call__(self):
        now = time.monotonic()
        if now >= self.deadline:
            raise TimeoutError('daily raw restore deadline exceeded')
        if now >= self.next_space_check:
            if shutil.disk_usage(self.work).free < self.limits.free_space_floor:
                raise ValueError('daily raw restore free-space floor reached')
            self.next_space_check = now + 1


def _receipt(path, expected, generation):
    hexadecimal(expected); regular(path)
    if path.stat().st_size > 1024**2:
        raise ValueError('archive receipt is too large')
    with pinned_reader(path) as (stream, _):
        raw = stream.read(1024**2 + 1)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('archive receipt SHA256 differs')
    row = json.loads(raw, object_pairs_hook=no_duplicates)
    if not isinstance(row, dict):
        raise ValueError('single archive progress row required')
    day = require_day(row.get('date', ''))
    if (not generation or require_generation(generation) != row.get('generation_id')
            or not generation.startswith('obs-' + day + '-')
            or row.get('schema') != SCHEMA or row.get('series') != SERIES
            or row.get('result') != 'PASS' or row.get('kind') != 'day'
            or type(row.get('bytes')) is not int or row['bytes'] <= 0
            or row.get('remote_name') not in {day + '.tar.zst', day + '.' + generation + '.tar.zst'}):
        raise ValueError('archive receipt generation/schema/object binding differs')
    hexadecimal(row.get('sha256')); hexadecimal(row.get('source_fingerprint'))
    return row, raw


def _metadata(row):
    if not isinstance(row, dict) or set(row) != ROW_KEYS:
        raise ValueError('unsupported daily archive file metadata')
    name = safe_relative(row['logical_path']); hexadecimal(row['sha256'])
    if not name.startswith(('data/', 'journal/')):
        raise ValueError('daily archive member is outside data/journal scope')
    for key in ('size', 'uid', 'gid', 'mtime_ns'):
        if type(row[key]) is not int:
            raise ValueError('invalid daily archive integer metadata')
    if (row['size'] < 0 or not all(0 <= row[k] < 2**32 for k in ('uid', 'gid'))
            or not -2**63 < row['mtime_ns'] < 2**63
            or not isinstance(row['mode'], str) or not re.fullmatch('0o[0-7]{1,4}', row['mode'])):
        raise ValueError('daily archive metadata outside supported bounds')


def _manifest(path, receipt, index, guard):
    count = size = 0
    previous = ''
    def row(item):
        nonlocal count, size, previous
        guard(); _metadata(item)
        name = item['logical_path']
        if name <= previous:
            raise ValueError('duplicate or unordered daily archive paths')
        previous = name; count += 1; size += item['size']
        if count > guard.limits.files or size > guard.limits.unpacked_bytes:
            raise ValueError('daily archive declared file/byte budget exceeded')
        index.execute('INSERT INTO files VALUES (?,?,?)', (name, name.casefold(), json.dumps(item)))
    result = object_arrays(path, {'files': row}, guard)
    if (result.get('schema') != SCHEMA or result.get('series') != SERIES
            or result.get('scope_schema') != 'ar-local-daily-cdr-day-archive-scope-v1'
            or result.get('compression') != 'zstd-lossless-no-encryption-level-19'
            or result.get('date') != receipt['date']
            or result.get('source_fingerprint') != receipt['source_fingerprint']
            or type(result.get('file_count')) is not int or result['file_count'] != count
            or type(result.get('total_bytes')) is not int or result['total_bytes'] != size
            or count == 0):
        raise ValueError('daily archive manifest identity/counts differ')
    index.commit()
    return result


def _extract(source, receipt, work, index, guard):
    decoder = zstandard.ZstdDecompressor(max_window_size=128 * 1024**2)
    limits = guard.limits
    bound = limits.unpacked_bytes + limits.manifest_bytes + (limits.files + 1) * 32768 + 65536
    with decoder.stream_reader(Guarded(source, guard), read_across_frames=True, closefd=False) as stream:
        bounded = Guarded(stream, guard, bound)
        with tarfile.open(fileobj=bounded, mode='r|', tarinfo=BoundedTarInfo) as tar:
            member = tar.next()
            if member is None or member.name != 'MANIFEST.json':
                raise ValueError('daily archive must begin with MANIFEST.json')
            manifest_path = work / 'MANIFEST.json'
            manifest_sha = write_member(tar, member, manifest_path, guard, limit=limits.manifest_bytes)
            manifest = _manifest(manifest_path, receipt, index, guard)
            # Tighten after reading actual manifest; permit bounded PAX/padding overhead.
            bounded.limit = manifest['total_bytes'] + member.size + (manifest['file_count'] + 1) * 32768 + 65536
            tar.members.clear()
            for (raw,) in index.execute('SELECT value FROM files ORDER BY logical'):
                guard(); row = json.loads(raw); member = tar.next()
                stamp = row['mtime_ns']; seconds, nanos = divmod(abs(stamp), 10**9)
                mtime = f'{"-" if stamp < 0 else ""}{seconds}.{nanos:09d}'
                if (member is None or member.name != row['logical_path']
                        or (member.size, member.mode, member.uid, member.gid) !=
                        (row['size'], int(row['mode'], 8), row['uid'], row['gid'])
                        or member.pax_headers.get('mtime') != mtime
                        or set(member.pax_headers) - {'mtime', 'path'}):
                    raise ValueError('daily archive member metadata/order differs')
                target = private_file(work, 'exact/' + row['logical_path'])
                if write_member(tar, member, target, guard, limit=row['size']) != row['sha256']:
                    raise ValueError('daily archive member SHA256 differs')
                tar.members.clear()
            if tar.next() is not None:
                raise ValueError('extra daily archive member')
            tar.members.clear()
        for block in iter(lambda: bounded.read(BLOCK), b''):
            if any(block):
                raise ValueError('nonzero trailing archive content')
    return manifest, manifest_sha


def _archived_contract(receipt, work, index, guard):
    logical = f"data/state/export-contracts-v2/{receipt['date']}/{receipt['generation_id']}.json"
    item = index.execute('SELECT value FROM files WHERE logical=?', (logical,)).fetchone()
    if item is None:
        return {'status': 'not_present', 'binding': 'retained_receipt_and_manifest_fingerprint'}
    contract = load_contract(work / 'exact' / logical, budget=lambda **_: guard())
    if (contract.get('generation_id') != receipt['generation_id']
            or contract.get('observation_date') != receipt['date']):
        raise ValueError('archived export contract generation differs')
    return dict(status='verified', logical_path=logical, sha256=json.loads(item[0])['sha256'],
                contract_digest=contract['contract_digest'])


def qualify(archive, receipt_path, receipt_sha256, generation, workspace, *, limits=Limits()):
    archive, receipt_path, work = map(Path, (archive, receipt_path, workspace))
    outside_production(work, roots=(*PRODUCTION_ROOTS, Path('/var/lib/ar-local-day-archives')))
    if (work.resolve() != work or work.exists() or work.is_symlink()
            or not work.parent.is_dir() or any(work in path.parents for path in (archive, receipt_path))):
        raise ValueError('new canonical workspace outside input paths required')
    regular(archive)
    receipt, receipt_raw = _receipt(receipt_path, receipt_sha256, generation)
    if archive.stat().st_size != receipt['bytes'] or receipt['bytes'] > limits.archive_bytes:
        raise ValueError('compressed archive byte count/budget differs')
    privacy = private_workspace(work)
    guard = Budget(work, limits)
    result = dict(schema=RESULT_SCHEMA, result='FAIL', generation_id=generation,
                  date=receipt['date'], remote_name=receipt['remote_name'],
                  source_fingerprint=receipt['source_fingerprint'], archive_sha256=receipt['sha256'],
                  archive_bytes=receipt['bytes'], receipt_sha256=receipt_sha256,
                  workspace_privacy=privacy, budgets=asdict(limits))
    try:
        (work / 'archive-receipt.json').write_bytes(receipt_raw)
        with audit_budget(guard.deadline), closing(sqlite3.connect(work / 'restore-index.sqlite')) as index:
            index.execute('PRAGMA cache_size=-4096'); index.execute('PRAGMA temp_store=FILE')
            index.execute('CREATE TABLE files(logical TEXT PRIMARY KEY, folded TEXT UNIQUE, value TEXT)')
            with pinned_reader(archive) as (source, _):
                sha = hashlib.sha256()
                for block in iter(lambda: source.read(BLOCK), b''):
                    guard(); sha.update(block)
                if sha.hexdigest() != receipt['sha256']:
                    raise ValueError('compressed archive SHA256 differs')
                frame(archive, guard); source.seek(0)
                manifest, manifest_sha = _extract(source, receipt, work, index, guard)
            contract = _archived_contract(receipt, work, index, guard)
            checks = verify_databases(index, work, guard)
            # Re-hash exact extracted evidence after all semantic work.
            for logical, raw in index.execute('SELECT logical,value FROM files'):
                if digest(work / 'exact' / logical, guard) != json.loads(raw)['sha256']:
                    raise ValueError('exact restored evidence changed during semantic verification')
            if digest(archive, guard) != receipt['sha256'] or digest(receipt_path, guard) != receipt_sha256:
                raise ValueError('archive inputs changed during qualification')
            guard()
        result.update(result='PASS', manifest_sha256=manifest_sha,
                      files_verified=manifest['file_count'], bytes_verified=manifest['total_bytes'],
                      coverage=manifest.get('coverage'), sqlite_checks=checks,
                      archived_export_contract=contract,
                      metadata='VERIFIED_IN_ARCHIVE_RESTORED_PRIVATE_MODE',
                      scope='generation_bound_local_archive_restore_only')
        return result
    except Exception as error:
        result.update(error=type(error).__name__, reason=str(error)[:1000])
        raise
    finally:
        with (work / 'restore-result.json').open('x', encoding='utf-8') as output:
            json.dump(result, output, indent=2, sort_keys=True); output.write('\n')
            output.flush(); os.fsync(output.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'receipt', 'workspace'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--receipt-sha256', required=True)
    parser.add_argument('--generation-id', required=True)
    for name, value in asdict(Limits()).items():
        parser.add_argument('--max-' + name.replace('_', '-'), type=int, default=value)
    args = parser.parse_args(argv)
    limits = Limits(**{name: getattr(args, 'max_' + name) for name in asdict(Limits())})
    try:
        result = qualify(args.archive, args.receipt, args.receipt_sha256, args.generation_id, args.workspace, limits=limits)
    except Exception as error:
        print(json.dumps({'result': 'FAIL', 'error': type(error).__name__, 'reason': str(error)[:1000]}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
