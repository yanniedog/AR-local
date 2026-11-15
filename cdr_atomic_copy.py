"""Bounded, verified create-once copies of immutable evidence."""
import hashlib
import os
from pathlib import Path

from ar_local_restore_io import chunks, hash_file, pinned_reader, regular_identity
from cdr_atomic import ImmutablePathError, _fsync_directory


def copy_verified(source: Path, target: Path, *, size: int, sha256: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        existing = regular_identity(target)
        if existing[3] != size or hash_file(target, expected=existing) != sha256:
            raise ImmutablePathError('immutable copy destination differs')
        original = regular_identity(source)
        if original[3] != size or hash_file(source, expected=original) != sha256:
            raise ValueError('source changed while verifying existing copy')
        if regular_identity(target) != existing:
            raise ValueError('existing copy changed during verification')
        _fsync_directory(target.parent)
        return
    temporary = target.parent / f'.{target.name}.copy-{os.getpid()}-{os.urandom(8).hex()}'
    try:
        with pinned_reader(source) as (reader, before):
            if before[3] != size:
                raise ValueError('source size changed while copying')
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            digest = hashlib.sha256()
            with os.fdopen(descriptor, 'wb') as writer:
                for block in chunks(reader, size):
                    writer.write(block)
                    digest.update(block)
                if digest.hexdigest() != sha256:
                    raise ValueError('source digest changed while copying')
                writer.flush()
                os.fsync(writer.fileno())
        # The pinned reader checks the source identity before any installation.
        try:
            os.link(temporary, target)
        except FileExistsError as error:
            existing = regular_identity(target)
            if existing[3] != size or hash_file(target, expected=existing) != sha256:
                raise ImmutablePathError('immutable copy destination differs') from error
        _fsync_directory(target.parent)
    finally:
        temporary.unlink(missing_ok=True)
        _fsync_directory(target.parent)
