"""Bounded create-once control records; no deletion, replacement or recovery."""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from cdr_historical_fee_archive import safe_path, stable_file

RECORD_LIMIT = 65536
_CONTROL = ContextVar('historical_fee_control_work', default=None)


@contextmanager
def control_work(meter):
    if _CONTROL.get() is not None:
        raise ValueError('nested_control_work_refused')
    token = _CONTROL.set(meter)
    try:
        yield
    finally:
        _CONTROL.reset(token)


def canonical(value):
    def visit(item, depth):
        if depth > 32:
            raise ValueError('control_nesting_bound')
        if item is None or type(item) in (str, bool):
            return
        if type(item) is int and 0 <= item <= 2**53 - 1:
            return
        if isinstance(item, list):
            for child in item:
                visit(child, depth + 1)
            return
        if isinstance(item, dict) and all(type(key) is str for key in item):
            for child in item.values():
                visit(child, depth + 1)
            return
        raise ValueError('unsupported_control_value')
    visit(value, 0)
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False) + '\n').encode('utf-8')


def digest(body):
    if _CONTROL.get() is not None:
        _CONTROL.get().charge('read_checksum', len(body))
    return hashlib.sha256(body).hexdigest()


def parse(body):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate_control_key')
            result[key] = value
        return result
    value = json.loads(body, object_pairs_hook=unique)
    if canonical(value) != body:
        raise ValueError('noncanonical_control_record')
    return value


def read_control(path, meter, *, limit=RECORD_LIMIT):
    path = safe_path(path)
    size = path.stat().st_size
    if size > limit:
        raise ValueError('control_file_byte_bound')
    # One reservation covers this read and its immediate SHA check.
    meter.admit_read(str(path), size)
    with stable_file(path) as stream:
        info = os.fstat(stream.fileno())
        body = stream.read(size)
    meter.check()
    if len(body) != size:
        raise ValueError('control_short_read')
    recorder = getattr(meter, 'note_completed_read', None)
    if recorder is not None:
        recorder(str(path), (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns), size)
    return body


def write_record(directory, sequence, value, meter):
    body = canonical(value)
    if len(body) > RECORD_LIMIT:
        raise ValueError('ledger_record_byte_bound')
    meter.charge('read_checksum', len(body))
    identity = digest(body)
    pending = directory / f'{sequence:03}.pending'
    final = directory / (identity + '.record')
    head = directory / f'{sequence:03}.head'
    meter.charge('output', len(body))
    with pending.open('xb') as stream:
        if stream.write(body) != len(body):
            raise ValueError('control_short_write')
        stream.flush()
        meter.check()
        os.fsync(stream.fileno())
        meter.check()
    if read_control(pending, meter) != body:
        raise ValueError('control_readback_mismatch')
    safe_path(directory, directory=True)
    meter.check()
    os.link(pending, final, follow_symlinks=False)
    meter.check()
    # This create-once expected sequence is the commit point. Orphans from any
    # earlier interruption are preserved and refuse the next writer/reader.
    os.link(final, head, follow_symlinks=False)
    return identity


def names(directory, maximum):
    result = set()
    with os.scandir(safe_path(directory, directory=True)) as entries:
        for entry in entries:
            if len(result) >= maximum:
                raise ValueError('ledger_inventory_bound')
            safe_path(Path(directory) / entry.name)
            result.add(entry.name)
    return result


def same_links(directory, sequence, identity):
    paths = (directory / f'{sequence:03}.pending', directory / f'{sequence:03}.head',
             directory / (identity + '.record'))
    stats = [safe_path(path).stat() for path in paths]
    if any(not row.st_ino or not os.path.samestat(stats[0], row) for row in stats[1:]):
        raise ValueError('ledger_link_identity_mismatch')
