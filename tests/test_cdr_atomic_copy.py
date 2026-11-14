import hashlib
import tracemalloc
from pathlib import Path

import pytest

import cdr_atomic_copy as copying
from cdr_atomic import ImmutablePathError
from cdr_attempt_evidence_promotion import install_tree_create_once


def test_trusted_installer_copies_and_hashes_streaming_dependency():
    text = (Path(__file__).resolve().parents[1] / 'deploy/pi/install-backup-foundation.sh').read_text()
    assert text.count('cdr_atomic_copy.py') == text.count('cdr_attempt_evidence_promotion.py') == 2


def test_large_export_install_has_bounded_allocation_and_exact_replay(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    artifact = source / 'banks.json'
    block = b'evidence' * 131072
    with artifact.open('wb') as output:
        for _ in range(32):
            output.write(block)
    expected = copying.hash_file(artifact)
    tracemalloc.start()
    try:
        assert install_tree_create_once(source, tmp_path / 'installed')
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    # Shared hashing uses 4 MiB blocks; two live blocks plus metadata fit here.
    # The former whole-file copy allocated at least the full 32 MiB artifact.
    assert peak < 12 * 1024**2
    assert copying.hash_file(tmp_path / 'installed/banks.json') == expected
    assert not install_tree_create_once(source, tmp_path / 'installed')


@pytest.mark.parametrize('size,digest', [(4, 'wrong'), (5, 'wrong')])
def test_wrong_source_never_installs(tmp_path, size, digest):
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.write_bytes(b'data')
    with pytest.raises(ValueError):
        copying.copy_verified(source, target, size=size, sha256=digest)
    assert not target.exists()
    assert not list(tmp_path.glob('.*.copy-*'))


def test_source_mutation_during_stream_never_installs(tmp_path, monkeypatch):
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.write_bytes(b'data')
    original = copying.chunks
    def mutate(reader, size):
        yield from original(reader, size)
        source.write_bytes(b'changed')
    monkeypatch.setattr(copying, 'chunks', mutate)
    with pytest.raises(ValueError, match='changed while reading'):
        copying.copy_verified(source, target, size=4, sha256=hashlib.sha256(b'data').hexdigest())
    assert not target.exists()


@pytest.mark.parametrize('existing', [b'data', b'keep'])
def test_create_once_collision_preserves_existing_bytes(tmp_path, existing):
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.write_bytes(b'data')
    target.write_bytes(existing)
    kwargs = dict(size=4, sha256=hashlib.sha256(b'data').hexdigest())
    if existing == b'data':
        copying.copy_verified(source, target, **kwargs)
    else:
        with pytest.raises(ImmutablePathError):
            copying.copy_verified(source, target, **kwargs)
    assert target.read_bytes() == existing


def test_interrupted_stream_never_installs_partial_file(tmp_path, monkeypatch):
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.write_bytes(b'data')
    def interrupted(*args):
        yield b'da'
        raise TimeoutError('deadline')
    monkeypatch.setattr(copying, 'chunks', interrupted)
    with pytest.raises(TimeoutError):
        copying.copy_verified(source, target, size=4, sha256=hashlib.sha256(b'data').hexdigest())
    assert not target.exists()
    assert source.read_bytes() == b'data'
    assert not list(tmp_path.glob('.*.copy-*'))


def test_verified_existing_target_needs_no_second_temporary_copy(tmp_path, monkeypatch):
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.write_bytes(b'exact byte-copy control'); target.write_bytes(source.read_bytes())
    original = copying.os.open
    def no_create(path, flags, *args, **kwargs):
        if flags & copying.os.O_CREAT:
            pytest.fail('existing verified destination must not allocate another copy')
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(copying.os, 'open', no_create)
    copying.copy_verified(source, target, size=source.stat().st_size,
                          sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    source.write_bytes(b'changed-source')
    with pytest.raises(ValueError, match='source changed'):
        copying.copy_verified(source, target, size=target.stat().st_size,
                              sha256=hashlib.sha256(target.read_bytes()).hexdigest())


def test_promotion_copy_preserves_budget_timeout_type(tmp_path, monkeypatch):
    from cdr_attempt_evidence_promotion import _copy_record_create_once
    source = tmp_path / 'source'; source.mkdir(); (source / 'evidence').write_bytes(b'bytes')
    error = TimeoutError('original copy deadline')
    def expired(*args, **kwargs): raise error
    monkeypatch.setattr(copying, 'copy_verified', expired)
    with pytest.raises(TimeoutError) as caught:
        _copy_record_create_once(source, tmp_path / 'target',
                                 {'path': 'evidence', 'bytes': 5, 'sha256': 'a' * 64})
    assert caught.value is error


def test_successful_copy_flushes_directory_after_sidecar_removal(tmp_path, monkeypatch):
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.write_bytes(b'copy durability control')
    synchronizations = []
    monkeypatch.setattr(copying, '_fsync_directory',
        lambda parent: synchronizations.append(sorted(p.name for p in parent.glob('.*.copy-*'))))
    copying.copy_verified(source, target, size=source.stat().st_size,
                          sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    assert synchronizations and synchronizations[-1] == []


@pytest.mark.parametrize('cleanup', ['unlink', 'fsync'])
def test_copy_deadline_survives_cleanup_failure(tmp_path, monkeypatch, cleanup):
    from cdr_attempt_evidence_promotion import _copy_record_create_once
    source = tmp_path / 'source'; source.mkdir()
    (source / 'evidence').write_bytes(b'original evidence')
    original = TimeoutError('copy deadline reached')
    secondary = OSError('cleanup storage failure')
    def interrupted(*args):
        yield b'original'
        raise original
    def broken(*args, **kwargs):
        raise secondary
    monkeypatch.setattr(copying, 'chunks', interrupted)
    if cleanup == 'fsync':
        monkeypatch.setattr(copying, '_fsync_directory', broken)
    else:
        unlink = Path.unlink
        def cleanup_unlink(path, *args, **kwargs):
            if '.copy-' in path.name: raise secondary
            return unlink(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'unlink', cleanup_unlink)
    with pytest.raises(TimeoutError) as caught:
        _copy_record_create_once(source, tmp_path / 'target', {'path': 'evidence',
            'bytes': 17, 'sha256': hashlib.sha256(b'original evidence').hexdigest()})
    assert caught.value is original and caught.value.__cause__ is secondary
    assert (source / 'evidence').read_bytes() == b'original evidence'
    assert not (tmp_path / 'target/evidence').exists()
    remnants = list((tmp_path / 'target').glob('.*.copy-*'))
    assert bool(remnants) == (cleanup == 'unlink')


def test_successful_copy_cleanup_failure_is_not_success(tmp_path, monkeypatch):
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.write_bytes(b'complete copy'); calls = []
    def fail_cleanup(parent):
        calls.append(parent)
        if len(calls) == 2: raise OSError('cleanup durability failure')
    monkeypatch.setattr(copying, '_fsync_directory', fail_cleanup)
    with pytest.raises(OSError, match='cleanup durability failure'):
        copying.copy_verified(source, target, size=13,
                              sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    assert target.read_bytes() == source.read_bytes()
    assert not list(tmp_path.glob('.*.copy-*'))
