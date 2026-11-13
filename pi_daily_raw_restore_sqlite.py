"""Semantic SQLite checks on disposable copies of exact daily archive evidence."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import struct

from ar_local_restore_io import pinned_reader
from ar_local_restore_verification import _retained_journal_policy
from pi_plain_backup_restore import BLOCK, private_file

MAX_TABLES = 100000
MAX_RESULT_BYTES = 8 * 1024**2


def _checksum(data, state, endian):
    words = struct.unpack(endian + str(len(data) // 4) + 'I', data)
    a, b = state
    for pos in range(0, len(words), 2):
        a = (a + words[pos] + b) & 0xffffffff
        b = (b + words[pos + 1] + a) & 0xffffffff
    return a, b


def _wal_check(path, guard):
    """Verify complete current-salt frames; old-salt tail is retained, not replayed."""
    if not path.exists() or not path.stat().st_size:
        return None
    with path.open('rb') as stream:
        head = stream.read(32)
        endian = '<' if head[:4] == bytes.fromhex('377f0682') else '>'
        state = _checksum(head[:24], (0, 0), endian)
        if state != struct.unpack('>II', head[24:32]):
            raise ValueError('SQLite WAL header checksum differs')
        size = int.from_bytes(head[8:12], 'big')
        frames = committed = 0
        while True:
            guard(); frame = stream.read(24)
            if not frame:
                break
            if len(frame) != 24:
                raise ValueError('SQLite WAL has a truncated frame')
            if frame[8:16] != head[16:24]:
                return dict(frames=frames, committed_frame=committed,
                            recycled_tail_bytes=path.stat().st_size - stream.tell() + 24)
            page = stream.read(size)
            if len(page) != size or int.from_bytes(frame[:4], 'big') == 0:
                raise ValueError('SQLite WAL page is truncated or invalid')
            state = _checksum(frame[:8] + page, state, endian)
            if state != struct.unpack('>II', frame[16:24]):
                raise ValueError('SQLite WAL frame checksum differs')
            frames += 1
            if int.from_bytes(frame[4:8], 'big'):
                committed = frames
    return dict(frames=frames, committed_frame=committed, recycled_tail_bytes=0)


def _copy(source, target, expected, guard):
    value = hashlib.sha256()
    with pinned_reader(source) as (stream, _), target.open('xb') as output:
        for block in iter(lambda: stream.read(BLOCK), b''):
            guard(); output.write(block); value.update(block)
    if value.hexdigest() != expected:
        raise ValueError('extracted SQLite evidence changed before private copy')


def verify_databases(index, workspace, guard):
    """Originals stay under exact/; native journal recovery only sees sqlite-working/."""
    candidates = []
    for logical, raw in index.execute('SELECT logical,value FROM files ORDER BY logical'):
        guard(); row = json.loads(raw)
        path = workspace / 'exact' / logical
        with path.open('rb') as stream:
            header = stream.read(16)
        sqlite = header == b'SQLite format 3\0'
        if path.suffix in {'.sqlite', '.sqlite3'} and not sqlite:
            raise ValueError('named SQLite database has no valid header')
        if sqlite:
            candidates.append(logical)
            if len(candidates) > 10000:
                raise ValueError('SQLite database count exceeds limit')
    candidate_set = set(candidates)
    for (logical,) in index.execute('SELECT logical FROM files'):
        if any(logical.endswith(suffix) and logical[:-len(suffix)] not in candidate_set
               for suffix in ('-wal', '-shm', '-journal')):
            raise ValueError('orphan SQLite sidecar cannot be qualified')
    results = []
    result_bytes = table_count = 0
    for number, logical in enumerate(candidates):
        guard(); original = workspace / 'exact' / logical
        private = private_file(workspace, f'sqlite-working/{number}/{original.name}')
        hashes = {}
        for suffix in ('', '-wal', '-shm', '-journal'):
            item = index.execute('SELECT value FROM files WHERE logical=?', (logical + suffix,)).fetchone()
            if item is None:
                continue
            row = json.loads(item[0]); hashes[original.name + suffix] = row['sha256']
            _copy(Path(str(original) + suffix), Path(str(private) + suffix), row['sha256'], guard)
        policy = _retained_journal_policy(private)
        wal = _wal_check(Path(str(private) + '-wal'), guard)
        committed = private_file(workspace, f'committed/{number}.sqlite')
        with closing(sqlite3.connect(private, timeout=1)) as source, closing(sqlite3.connect(committed)) as target:
            source.execute('PRAGMA trusted_schema=OFF')
            source.set_progress_handler(lambda: (guard(), 0)[1], 1000)
            source.execute('PRAGMA schema_version').fetchone()
            source.backup(target, pages=256, progress=lambda *_: guard(), sleep=0.01)
            target.execute('PRAGMA trusted_schema=OFF')
            target.execute('PRAGMA cache_size=-4096')
            target.set_progress_handler(lambda: (guard(), 0)[1], 1000)
            if target.execute('PRAGMA integrity_check').fetchmany(2) != [('ok',)]:
                raise ValueError('restored SQLite integrity check failed')
            if target.execute('PRAGMA foreign_key_check').fetchone() is not None:
                raise ValueError('restored SQLite foreign key check failed')
            tables = {}
            pending_bytes = 0
            for (name,) in target.execute("SELECT substr(name,1,4097) FROM sqlite_schema WHERE type='table' ORDER BY name"):
                guard()
                table_count += 1
                if table_count > MAX_TABLES or len(name.encode('utf-8')) > 4096:
                    raise ValueError('SQLite table count exceeds limit')
                pending_bytes += len(json.dumps(name).encode('utf-8')) + 32
                if result_bytes + pending_bytes > MAX_RESULT_BYTES:
                    raise ValueError('SQLite result inventory exceeds bound')
                quoted = '"' + name.replace('"', '""') + '"'
                tables[name] = target.execute('SELECT COUNT(*) FROM ' + quoted).fetchone()[0]
        result = dict(logical_path=logical, source_files=hashes,
                      integrity_check='ok', foreign_key_check='ok', tables=tables,
                      retained_journals=policy, wal=wal,
                      committed_relative=committed.relative_to(workspace).as_posix())
        result_bytes += len(json.dumps(result).encode('utf-8'))
        if result_bytes > MAX_RESULT_BYTES:
            raise ValueError('SQLite result inventory exceeds bound')
        results.append(result)
    return results
