import hashlib
import tracemalloc

import pytest

import cdr_atomic_copy as copying
from cdr_atomic import ImmutablePathError
from cdr_attempt_evidence_promotion import install_tree_create_once


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
