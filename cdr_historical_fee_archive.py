"""Bounded read-only single-frame zstd/tar admission; never restore an archive."""
from __future__ import annotations

import hashlib
import os
import re
import stat
import tarfile
import time
from contextlib import contextmanager
from pathlib import Path

from cdr_historical_fee_exact import decode, encode, fingerprint, sha

MIB = 1024**2
CHUNK = 64 * 1024
POLICY = 'fee-archive-reader-v2'


class Budget:
    """One operation; all passes share counters and a cooperative deadline."""
    def __init__(self, *, deadline=None):
        self.started = time.monotonic()
        self.deadline = self.started + 600 if deadline is None else min(deadline, self.started + 600)
        self.counts = {}
        self.limits = {'compressed': 64 * MIB, 'decoded': 512 * MIB,
                       'metadata': MIB, 'headers': 1024, 'output': 512 * MIB}

    def check(self, kind=None, amount=0):
        if time.monotonic() >= self.deadline:
            raise ValueError('archive_deadline_exceeded')
        if kind is not None:
            self.counts[kind] = self.counts.get(kind, 0) + amount
            if kind in self.limits and self.counts[kind] > self.limits[kind]:
                raise ValueError('archive_' + kind + '_bound_exceeded')


def safe_member(name):
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name or '\x00' in name
            or any(part in ('', '.', '..') for part in name.split('/'))):
        raise ValueError('unsafe_archive_member_path')
    return name


def safe_path(path, *, directory=False):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('input_reparse_or_symlink_refused')
    info = path.stat()
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise ValueError('regular_input_required')
    return path.resolve(strict=True)


def private_path(path):
    path = Path(path).absolute()
    if path.name in ('', '.', '..'):
        raise ValueError('exact_named_private_directory_required')
    return safe_path(path.parent, directory=True) / path.name


@contextmanager
def stable_file(path):
    path = safe_path(path)
    before = fingerprint(path.stat())
    with path.open('rb') as stream:
        if fingerprint(os.fstat(stream.fileno())) != before:
            raise ValueError('input_changed_before_open')
        yield stream
        if fingerprint(os.fstat(stream.fileno())) != before or fingerprint(safe_path(path).stat()) != before:
            raise ValueError('input_changed_during_operation')


def read_exact(stream, size, budget, kind=None):
    parts, remaining = [], size
    while remaining:
        budget.check()
        body = stream.read(min(CHUNK, remaining))
        if not body:
            raise ValueError('truncated_archive')
        if kind:
            budget.check(kind, len(body))
        parts.append(body)
        remaining -= len(body)
    return b''.join(parts)


def verify_frame(stream, identity, budget):
    """Hash every compressed byte and reject concatenation before decompression."""
    import zstandard
    if zstandard.__version__ != '0.25.0':
        raise ValueError('pinned_zstandard_0_25_0_required')
    digest = hashlib.sha256()

    def take(size):
        body = read_exact(stream, size, budget, 'compressed')
        digest.update(body)
        return body

    prefix = take(5)
    if prefix[:4] != b'\x28\xb5\x2f\xfd' or prefix[4] & 0x18:
        raise ValueError('unsupported_zstd_frame_header')
    descriptor = prefix[4]
    single = bool(descriptor & 0x20)
    count = (0 if single else 1) + (0, 1, 2, 4)[descriptor & 3]
    count += (1 if single else 0, 2, 4, 8)[descriptor >> 6]
    params = zstandard.get_frame_parameters(prefix + take(count))
    if params.dict_id or params.window_size > 512 * MIB:
        raise ValueError('unsupported_zstd_dictionary_or_window')
    if params.content_size not in (zstandard.CONTENTSIZE_UNKNOWN, zstandard.CONTENTSIZE_ERROR) and params.content_size > budget.limits['decoded']:
        raise ValueError('archive_decoded_bound_exceeded')
    while True:
        header = int.from_bytes(take(3), 'little')
        last, kind, size = header & 1, (header >> 1) & 3, header >> 3
        if kind == 3 or size > 128 * 1024:
            raise ValueError('unsupported_zstd_block')
        remaining = 1 if kind == 1 else size
        while remaining:
            block = min(CHUNK, remaining)
            take(block)
            remaining -= block
        if last:
            break
    if descriptor & 4:
        take(4)
    budget.check()
    if stream.tell() != identity['bytes'] or stream.read(1) or digest.hexdigest() != identity['sha256']:
        raise ValueError('container_hash_size_or_frame_boundary_mismatch')


class CountedSource:
    def __init__(self, stream, budget):
        self.stream, self.budget = stream, budget

    def read(self, size):
        self.budget.check()
        body = self.stream.read(min(size, CHUNK))
        self.budget.check('compressed', len(body))
        return body


def _pax(body):
    """Only local, unique timestamps or an identical path; no implicit overrides."""
    result, offset = {}, 0
    while offset < len(body):
        end = body.find(b' ', offset)
        if end < 0 or not re.fullmatch(rb'[1-9][0-9]*', body[offset:end]):
            raise ValueError('invalid_pax_length')
        size = int(body[offset:end])
        item = body[end + 1:offset + size]
        if size <= end + 1 - offset or offset + size > len(body) or not item.endswith(b'\n') or b'=' not in item:
            raise ValueError('invalid_pax_record')
        key, value = item[:-1].decode('utf-8', errors='strict').split('=', 1)
        if key in result or key not in ('path', 'mtime', 'atime', 'ctime'):
            raise ValueError('ambiguous_or_unsupported_pax_key')
        if key != 'path' and not re.fullmatch(r'-?[0-9]+(?:\.[0-9]+)?', value):
            raise ValueError('invalid_pax_timestamp')
        result[key] = value
        offset += size
    return result


def _member_body(stream, size, budget, output=None, hashed=False):
    digest = hashlib.sha256() if hashed else None
    remaining = size
    while remaining:
        body = read_exact(stream, min(CHUNK, remaining), budget, 'decoded')
        if digest:
            digest.update(body)
        if output is not None:
            budget.check('output', len(body))
            if output.write(body) != len(body):
                raise ValueError('cache_short_write')
        remaining -= len(body)
    padding = read_exact(stream, (-size) % 512, budget, 'decoded')
    if any(padding):
        raise ValueError('nonzero_tar_member_padding')
    return digest.hexdigest() if digest else None


def _tar(stream, files, selected, cache, budget, resume):
    expected = {row['path']: row for row in files}
    selected_by_path = {path: role for role, path in selected.items()}
    seen, folded, pending, records = set(), set(), None, {}
    while True:
        body = read_exact(stream, 512, budget, 'decoded')
        if not any(body):
            if pending is not None or any(read_exact(stream, 512, budget, 'decoded')):
                raise ValueError('invalid_tar_end_records')
            while True:
                budget.check()
                padding = stream.read(CHUNK)
                budget.check('decoded', len(padding))
                if not padding:
                    break
                if len(padding) % 512 or any(padding):
                    raise ValueError('invalid_tar_trailing_padding')
            break
        budget.check('headers', 1)
        try:
            item = tarfile.TarInfo.frombuf(body, 'utf-8', 'strict')
        except (tarfile.TarError, UnicodeError) as exc:
            raise ValueError('invalid_tar_header') from exc
        if item.size < 0:
            raise ValueError('negative_tar_member_size')
        if item.type == tarfile.XHDTYPE:
            if item.name != '././@PaxHeader':
                safe_member(item.name)
            if pending is not None:
                raise ValueError('ambiguous_pax_sequence')
            budget.check('metadata', item.size)
            pending = _pax(read_exact(stream, item.size, budget, 'decoded'))
            if any(read_exact(stream, (-item.size) % 512, budget, 'decoded')):
                raise ValueError('nonzero_pax_padding')
            continue
        name = safe_member(item.name.rstrip('/') if item.isdir() else item.name)
        if pending is not None:
            if pending.get('path', name) != name:
                raise ValueError('pax_path_override_requires_review')
            pending = None
        if name.casefold() in folded:
            raise ValueError('duplicate_or_case_colliding_tar_member')
        folded.add(name.casefold())
        if item.isdir() and item.size == 0:
            continue
        if item.type not in (tarfile.REGTYPE, tarfile.AREGTYPE) or name not in expected or item.size != expected[name]['size']:
            raise ValueError('tar_member_inventory_mismatch')
        seen.add(name)
        role = selected_by_path.get(name)
        output = None
        try:
            if role is not None and not resume:
                output = (cache / (role + '.bin')).open('xb')
            digest = _member_body(stream, item.size, budget, output, role is not None)
            if output is not None:
                output.flush()
                os.fsync(output.fileno())
        finally:
            if output is not None:
                output.close()
        if role is not None:
            if digest != expected[name]['sha256']:
                raise ValueError('selected_member_hash_mismatch')
            records[role] = {'path': name, 'bytes': item.size, 'sha256': digest, 'cache_file': role + '.bin'}
    if seen != set(expected) or set(records) != set(selected):
        raise ValueError('incomplete_tar_inventory')
    return records


def _validate_inputs(identity, files, selected, budget):
    if type(identity.get('bytes')) is not int or not 0 < identity['bytes'] <= 64 * MIB:
        raise ValueError('compressed_container_size_bound')
    if not re.fullmatch('[0-9a-f]{64}', identity.get('sha256', '')) or not files or len(files) > 1024:
        raise ValueError('invalid_archive_identity')
    folded = set()
    for row in files:
        name = safe_member(row['path'])
        if (name.casefold() in folded or row.get('type') != 'file' or type(row.get('size')) is not int
                or row['size'] < 0 or not re.fullmatch('[0-9a-f]{64}', row.get('sha256', ''))):
            raise ValueError('invalid_or_ambiguous_manifest_inventory')
        folded.add(name.casefold())
    paths = {row['path']: row for row in files}
    if not selected or len(set(selected.values())) != len(selected):
        raise ValueError('ambiguous_selected_members')
    for role, name in selected.items():
        if not re.fullmatch('[a-z][a-z0-9_]{0,31}', role) or name not in paths or paths[name]['size'] > 256 * MIB:
            raise ValueError('selected_member_bound_or_identity')
    budget.limits['decoded'] = min(budget.limits['decoded'], sum(row['size'] for row in files) + 2 * MIB + CHUNK * (len(files) + 1))


def read_verified(path, identity, budget, *, limit, capture=True, budget_kind='verified_read'):
    if type(identity['bytes']) is not int or identity['bytes'] > limit:
        raise ValueError('selected_file_size_bound')
    with stable_file(path) as stream:
        if os.fstat(stream.fileno()).st_size != identity['bytes']:
            raise ValueError('selected_file_size_mismatch')
        parts, digest, remaining = [], hashlib.sha256(), identity['bytes']
        while remaining:
            chunk = read_exact(stream, min(CHUNK, remaining), budget, budget_kind)
            digest.update(chunk)
            if capture:
                parts.append(chunk)
            remaining -= len(chunk)
        if digest.hexdigest() != identity['sha256']:
            raise ValueError('selected_file_hash_mismatch')
    budget.check()
    return b''.join(parts) if capture else None


def write_exclusive(path, body, budget):
    budget.check('output', len(body))
    with path.open('xb') as stream:
        for offset in range(0, len(body), CHUNK):
            budget.check()
            chunk = body[offset:offset + CHUNK]
            if stream.write(chunk) != len(chunk):
                raise ValueError('output_short_write')
            budget.check()
        stream.flush()
        budget.check()
        os.fsync(stream.fileno())
        budget.check()
        identity = fingerprint(os.fstat(stream.fileno()))
    budget.check()
    return identity


def seal_exclusive(path, body, budget):
    """Publish only flushed, verified bytes; preserve all pending/collision files."""
    if len(body) > MIB:
        raise ValueError('pending_seal_byte_bound')
    pending = path.with_name(path.stem + '.pending' + path.suffix)
    identity = write_exclusive(pending, body, budget)
    read_verified(pending, {'bytes': len(body), 'sha256': sha(body)}, budget, limit=MIB, capture=False)
    if fingerprint(safe_path(pending).stat()) != identity:
        raise ValueError('pending_seal_identity_changed')
    budget.check()  # Includes completed flush, fsync, close, readback and stat calls.
    # This create-once link is the visibility point. No fallible work follows it.
    # OS-blocked link completion and power-loss directory durability are not bounded.
    os.link(pending, path, follow_symlinks=False)


def verify_pending_seal(path):
    pending = path.with_name(path.stem + '.pending' + path.suffix)
    first, second = safe_path(path).stat(), safe_path(pending).stat()
    if not first.st_ino or not second.st_ino or not os.path.samestat(first, second):
        raise ValueError('cache_pending_seal_hardlink_identity_mismatch')


def inspect_archive(path, identity, files, selected, cache, budget):
    """Cache only selected evidence; every resume revalidates the same archive."""
    import zstandard
    _validate_inputs(identity, files, selected, budget)
    path, cache = safe_path(path), private_path(cache)
    if cache == path or cache in path.parents or path.parent in cache.parents:
        raise ValueError('cache_must_be_separate_from_source')
    resume = cache.exists()
    binding = {'policy': POLICY, 'archive': identity, 'inventory_sha256': sha(encode(files)), 'selected_paths': selected}
    if resume:
        safe_path(cache, directory=True)
        if not (cache / 'receipt.json').is_file():
            raise ValueError('partial_cache_requires_separate_review')
        verify_pending_seal(cache / 'receipt.json')
        with stable_file(cache / 'receipt.json') as stream:
            old = decode(stream.read(MIB + 1), limit=MIB)
        if old.get('binding') != binding or old.get('status') != 'MEMBER_VERIFIED':
            raise ValueError('cache_identity_collision')
        if {p.name for p in cache.iterdir()} != {'receipt.json', 'receipt.pending.json'} | {role + '.bin' for role in selected}:
            raise ValueError('cache_contains_unknown_files')
    else:
        cache.mkdir()
    with stable_file(path) as stream:
        if os.fstat(stream.fileno()).st_size != identity['bytes']:
            raise ValueError('container_size_mismatch')
        verify_frame(stream, identity, budget)
        stream.seek(0)
        with zstandard.ZstdDecompressor().stream_reader(CountedSource(stream, budget), closefd=False, read_across_frames=False) as decoded:
            records = _tar(decoded, files, selected, cache, budget, resume)
    for row in records.values():
        read_verified(cache / row['cache_file'], row, budget, limit=256 * MIB, capture=False)
    receipt = {'status': 'MEMBER_VERIFIED', 'binding': binding, 'regular_files': len(files), 'selected': records}
    if resume:
        if old != receipt:
            raise ValueError('cache_receipt_content_mismatch')
        verify_pending_seal(cache / 'receipt.json')
        read_verified(cache / 'receipt.json', {'bytes': len(encode(receipt)), 'sha256': sha(encode(receipt))},
                      budget, limit=MIB, capture=False)
    else:
        seal_exclusive(cache / 'receipt.json', encode(receipt), budget)
    return receipt
