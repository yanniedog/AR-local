"""Real private-file writes and controlled syscall edges, not backup acceptance."""
import errno
import hashlib
import os

import pytest

import pi_drive_backup_source as source
import pi_drive_backup_write as writer


@pytest.fixture
def writev(monkeypatch):
    calls = []

    def actual(fd, buffers, offset, flags):
        calls.append((fd, offset, len(buffers[0]), flags))
        os.lseek(fd, offset, os.SEEK_SET)
        return os.write(fd, buffers[0])

    monkeypatch.setattr(writer, 'LINUX', True)
    monkeypatch.setattr(writer.os, 'pwritev', actual, raising=False)
    return calls, actual


def test_copy_uses_advised_bounded_private_writes_and_preserves_source(tmp_path, writev):
    original, target = tmp_path / 'original', tmp_path / 'target'
    body = bytes(range(256)) * 9000 + b'tail'
    original.write_bytes(body)
    before = source.fingerprint(original)
    source._copy(original, target, lambda: None)
    assert writev[0] and all(size <= writer.CHUNK_BYTES and flag == 0x80 for _, _, size, flag in writev[0])
    assert target.read_bytes() == body
    assert source.fingerprint(original) == before


def test_short_writes_preserve_byte_order_offsets_and_guard(tmp_path, writev, monkeypatch):
    calls, actual = writev

    def short(fd, buffers, offset, flags):
        return actual(fd, [buffers[0][:113]], offset, flags)

    monkeypatch.setattr(writer.os, 'pwritev', short)
    body = bytes(range(251)) * 100
    target = tmp_path / 'target'
    guards = []
    with target.open('xb') as stream:
        copied = writer.CreatedWriter(stream)
        copied.write(body, lambda: guards.append(True))
        assert copied.offset == stream.tell() == len(body)
    assert target.read_bytes() == body
    assert [call[1] for call in calls] == list(range(0, len(body), 113))
    assert len(guards) == len(calls)


@pytest.mark.parametrize('number', [errno.EOPNOTSUPP, errno.ENOSYS, errno.EINVAL])
@pytest.mark.parametrize('partial', [False, True])
def test_unsupported_write_resumes_exactly_and_stays_buffered(tmp_path, writev, monkeypatch, number, partial):
    calls, actual = writev

    def unsupported(fd, buffers, offset, flags):
        if partial and not offset:
            return actual(fd, [buffers[0][:113]], offset, flags)
        raise OSError(number, 'controlled unsupported write hint')

    monkeypatch.setattr(writer.os, 'pwritev', unsupported)
    target = tmp_path / 'target'
    with target.open('xb') as stream:
        copied = writer.CreatedWriter(stream)
        with pytest.warns(RuntimeWarning, match='unchanged resource guards'):
            copied.write(b'a' * 1500, lambda: None)
        copied.write(b'b' * 80, lambda: None)
        assert copied.writev is None
    assert target.read_bytes() == b'a' * 1500 + b'b' * 80
    assert len(calls) == int(partial)


@pytest.mark.parametrize('failure', ['io', 'zero', 'invalid', 'guard'])
def test_failed_write_stops_without_final_cache_release(tmp_path, writev, monkeypatch, failure):
    calls, actual = writev

    def fail(fd, buffers, offset, flags):
        if failure == 'io':
            raise OSError(errno.EIO, 'controlled disk failure')
        if failure == 'zero':
            return 0
        if failure == 'invalid':
            return len(buffers[0]) + 1
        return actual(fd, [buffers[0][:17]], offset, flags)

    monkeypatch.setattr(writer.os, 'pwritev', fail)
    monkeypatch.setattr(source, 'discard_created_cache', lambda *_: pytest.fail('failed copy released cache'))
    path, target = tmp_path / 'source', tmp_path / 'target'
    path.write_bytes(b'x' * 1000)

    def guard():
        if failure == 'guard' and calls:
            raise RuntimeError('controlled write interruption')

    with pytest.raises((OSError, RuntimeError)):
        source._copy(path, target, guard)
    if failure == 'guard':
        assert target.read_bytes() == b'x' * 17
        with pytest.raises(OSError):
            os.fstat(calls[0][0])


@pytest.mark.parametrize('mode', ['rb', 'ab'])
def test_source_and_reopened_handles_rejected_before_write(tmp_path, writev, mode):
    path = tmp_path / 'existing'
    path.write_bytes(b'unchanged')
    with path.open(mode) as stream, pytest.raises(ValueError, match='exclusively created'):
        writer.CreatedWriter(stream)
    assert path.read_bytes() == b'unchanged' and not writev[0]


def test_new_link_after_creation_rejected_before_next_write(tmp_path, writev):
    target = tmp_path / 'target'
    with target.open('xb') as stream:
        copied = writer.CreatedWriter(stream)
        os.link(target, tmp_path / 'alias')
        with pytest.raises(ValueError, match='exclusively created'):
            copied.write(b'not written', lambda: None)
    assert target.read_bytes() == b'' and not writev[0]


@pytest.mark.parametrize('platform', ['other', 'missing', 'no_flags'])
def test_other_platform_or_python_without_flags_preserves_bytes(tmp_path, monkeypatch, platform):
    monkeypatch.setattr(writer, 'LINUX', platform != 'other')
    def unsupported(*_):
        if platform == 'other':
            pytest.fail('native write called on non-Linux')
        raise NotImplementedError('Python built without pwritev2')
    monkeypatch.setattr(writer.os, 'pwritev', unsupported, raising=False)
    if platform == 'missing':
        monkeypatch.delattr(writer.os, 'pwritev')
    target = tmp_path / 'target'
    with target.open('xb') as stream:
        copied = writer.CreatedWriter(stream)
        if platform == 'no_flags':
            with pytest.warns(RuntimeWarning):
                copied.write(b'portable', lambda: None)
        else:
            copied.write(b'portable', lambda: None)
    assert target.read_bytes() == b'portable'


@pytest.mark.parametrize('size', [0, writer.CHUNK_BYTES + 1])
def test_invalid_block_bounds_rejected_before_native_write(tmp_path, writev, size):
    with (tmp_path / 'target').open('xb') as stream:
        copied = writer.CreatedWriter(stream)
        with pytest.raises(ValueError, match='bounded and nonempty'):
            copied.write(b'x' * size, lambda: None)
    assert not writev[0]


def test_already_written_exclusive_stream_rejected(tmp_path, writev):
    path = tmp_path / 'target'
    with path.open('xb') as stream:
        stream.write(b'previous data')
        with pytest.raises(ValueError, match='new empty destination'):
            writer.CreatedWriter(stream)
    assert path.read_bytes() == b'previous data' and not writev[0]


@pytest.mark.skipif(not writer.LINUX or not hasattr(os, 'pwritev'), reason='native Linux pwritev required')
def test_real_linux_private_write_has_exact_byte_identity(tmp_path):
    original, target = tmp_path / 'original', tmp_path / 'target'
    original.write_bytes(bytes(range(256)) * 8193)
    source._copy(original, target, lambda: None)
    assert hashlib.sha256(target.read_bytes()).digest() == hashlib.sha256(original.read_bytes()).digest()
