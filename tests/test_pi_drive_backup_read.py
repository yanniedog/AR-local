"""Real file/SQLite controls for the backup read adapter, not CDR acceptance."""
from __future__ import annotations

import errno
import hashlib
import os
import sqlite3
from pathlib import Path

import pytest

import pi_drive_backup_read as reader
import pi_drive_backup_source as source


@pytest.fixture
def readv(monkeypatch):
    calls = []

    def actual(fd, buffers, offset, flags):
        calls.append((fd, offset, len(buffers[0]), flags))
        # Windows lacks preadv: exercise real descriptor reads without changing
        # global os.name or pretending this measures the Linux page cache.
        os.lseek(fd, offset, os.SEEK_SET)
        body = os.read(fd, len(buffers[0]))
        buffers[0][:len(body)] = body
        return len(body)

    monkeypatch.setattr(reader, "LINUX", True)
    monkeypatch.setattr(reader.os, "preadv", actual, raising=False)
    return calls, actual


def test_hash_copy_and_existing_guards_use_bounded_advised_reads(tmp_path, readv):
    calls, _ = readv
    original = tmp_path / "source.bin"
    original.write_bytes(bytes(range(256)) * (reader.CHUNK_BYTES // 256 * 3) + b"tail")
    before = source.fingerprint(original)
    expected = hashlib.sha256(original.read_bytes()).hexdigest()
    guarded = []
    assert source.digest(original, lambda: guarded.append(True)) == expected
    assert len(guarded) == 4
    assert calls and {call[3] for call in calls} == {0x80}
    assert max(call[2] for call in calls) == reader.CHUNK_BYTES
    calls.clear()
    copy = tmp_path / "copied.bin"
    source._copy(original, copy, lambda: guarded.append(True))
    assert calls and {call[3] for call in calls} == {0x80}
    assert copy.read_bytes() == original.read_bytes()
    assert source.fingerprint(original) == before


def test_short_reads_retain_every_byte_in_order(tmp_path, readv, monkeypatch):
    calls, actual = readv
    path = tmp_path / "short.bin"
    body = bytes(range(251)) * 80
    path.write_bytes(body)

    def short(fd, buffers, offset, flags):
        return actual(fd, [memoryview(buffers[0])[:113]], offset, flags)

    monkeypatch.setattr(reader.os, "preadv", short)
    with path.open("rb") as stream:
        assert b"".join(reader.chunks(stream)) == body
    assert [call[1] for call in calls] == list(range(0, len(body), 113)) + [len(body)]


@pytest.mark.parametrize("error_number", [errno.ENOSYS, errno.EOPNOTSUPP, errno.EINVAL])
@pytest.mark.parametrize("after_first", [False, True])
def test_unsupported_hint_resumes_without_duplicate_or_missing_bytes(tmp_path, readv, monkeypatch,
                                                                  error_number, after_first):
    _, actual = readv
    path = tmp_path / "fallback.bin"
    body = b"a" * reader.CHUNK_BYTES + b"remaining"
    path.write_bytes(body)

    def unsupported(fd, buffers, offset, flags):
        if not after_first or offset:
            raise OSError(error_number, "controlled capability failure")
        return actual(fd, buffers, offset, flags)

    monkeypatch.setattr(reader.os, "preadv", unsupported)
    with path.open("rb") as stream, pytest.warns(RuntimeWarning, match="unchanged resource guards"):
        assert b"".join(reader.chunks(stream)) == body


def test_real_read_error_is_not_hidden_as_capability_fallback(tmp_path, readv, monkeypatch):
    path = tmp_path / "read-error.bin"
    path.write_bytes(b"unreadable test content")

    def fail(*_):
        raise OSError(errno.EIO, "controlled read error")

    monkeypatch.setattr(reader.os, "preadv", fail)
    with pytest.raises(OSError) as error:
        source.digest(path)
    assert error.value.errno == errno.EIO


@pytest.mark.parametrize("operation", ["digest", "copy"])
def test_guard_interruption_still_stops_and_closes_read_handles(tmp_path, readv, operation):
    calls, _ = readv
    path = tmp_path / "guard.bin"
    path.write_bytes(b"x" * (reader.CHUNK_BYTES + 1))

    def stop():
        raise RuntimeError("resource guard stopped")

    with pytest.raises(RuntimeError, match="resource guard stopped"):
        if operation == "digest":
            source.digest(path, stop)
        else:
            source._copy(path, tmp_path / "partial.bin", stop)
    assert len(calls) == 1
    with pytest.raises(OSError):
        os.fstat(calls[0][0])


def test_other_platform_preserves_existing_read_path(tmp_path, monkeypatch):
    monkeypatch.setattr(reader, "LINUX", False)
    monkeypatch.setattr(reader.os, "preadv", lambda *_: pytest.fail("non-Linux preadv"), raising=False)
    path = tmp_path / "portable.bin"
    path.write_bytes(b"portable file content")
    assert source.digest(path) == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("available", [False, True])
def test_python_without_preadv2_flags_keeps_byte_parity(tmp_path, monkeypatch, available):
    monkeypatch.setattr(reader, "LINUX", True)
    path = tmp_path / "legacy-python.bin"
    path.write_bytes(b"existing Python without preadv2 flags")
    if available:
        def unsupported(*_):
            raise NotImplementedError("preadv2 unavailable in this Python build")
        monkeypatch.setattr(reader.os, "preadv", unsupported, raising=False)
        with pytest.warns(RuntimeWarning, match="unchanged resource guards"):
            assert source.digest(path) == hashlib.sha256(path.read_bytes()).hexdigest()
    else:
        monkeypatch.delattr(reader.os, "preadv", raising=False)
        assert source.digest(path) == hashlib.sha256(path.read_bytes()).hexdigest()


def test_sqlite_snapshot_preserves_live_wal_and_source_identity(tmp_path, readv):
    path = tmp_path / "live.sqlite"
    live = sqlite3.connect(path)
    try:
        live.execute("PRAGMA journal_mode=WAL")
        live.execute("CREATE TABLE recorded (id INTEGER PRIMARY KEY)")
        live.execute("INSERT INTO recorded VALUES (17)")
        live.commit()
        components = [path, Path(str(path) + "-wal"), Path(str(path) + "-shm")]
        before = {p: (source.fingerprint(p), hashlib.sha256(p.read_bytes()).hexdigest()) for p in components}
        target = tmp_path / "snapshot" / "live.sqlite"
        originals = source.sqlite_snapshot(path, target, lambda: None, tmp_path / "originals" / path.name)
        assert len(originals) == 2
        with sqlite3.connect(target) as copied:
            assert copied.execute("SELECT id FROM recorded").fetchall() == [(17,)]
        assert before == {p: (source.fingerprint(p), hashlib.sha256(p.read_bytes()).hexdigest()) for p in components}
        assert live.execute("SELECT id FROM recorded").fetchall() == [(17,)]
        assert readv[0]
    finally:
        live.close()


@pytest.mark.skipif(not reader.LINUX or not hasattr(os, "preadv"), reason="real Linux preadv required")
def test_real_linux_advisory_or_unsupported_fallback_has_exact_digest(tmp_path):
    path = tmp_path / "native.bin"
    path.write_bytes(bytes(range(256)) * 32769)
    assert source.digest(path) == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def release_cache(monkeypatch):
    calls = []
    synced = []
    real_sync = os.fsync

    def sync(fd):
        real_sync(fd)
        synced.append((os.fstat(fd).st_dev, os.fstat(fd).st_ino))

    def release(fd, offset, length, advice):
        identity = (os.fstat(fd).st_dev, os.fstat(fd).st_ino)
        assert identity in synced
        assert (offset, length, advice) == (0, 0, 4)
        calls.append(identity)

    monkeypatch.setattr(reader, "LINUX", True)
    monkeypatch.setattr(reader.os, "fsync", sync)
    monkeypatch.setattr(reader.os, "posix_fadvise", release, raising=False)
    monkeypatch.setattr(reader.os, "POSIX_FADV_DONTNEED", 4, raising=False)
    return calls


def test_verified_copy_releases_only_its_created_destination(tmp_path, readv, release_cache):
    original = tmp_path / "original.bin"
    target = tmp_path / "new.bin"
    original.write_bytes(b"verified private copy" * 1000)
    source._copy(original, target, lambda: None)
    info = target.stat()
    assert release_cache == [(info.st_dev, info.st_ino)]
    assert original.read_bytes() == target.read_bytes()
    assert (original.stat().st_dev, original.stat().st_ino) not in release_cache


@pytest.mark.parametrize("failure", ["guard", "source_changed", "copy_corrupted"])
def test_failed_copy_never_releases_cache(tmp_path, readv, release_cache, monkeypatch, failure):
    original = tmp_path / "original.bin"
    target = tmp_path / "failed.bin"
    original.write_bytes(b"initial source contents")
    real_copystat = source.shutil.copystat

    def copystat(src, dst):
        real_copystat(src, dst)
        if failure == "source_changed":
            original.write_bytes(b"changed source contents")
        elif failure == "copy_corrupted":
            target.write_bytes(b"corrupted copy contents")

    def guard():
        if failure == "guard":
            raise RuntimeError("controlled guard stop")

    monkeypatch.setattr(source.shutil, "copystat", copystat)
    with pytest.raises(RuntimeError):
        source._copy(original, target, guard)
    assert release_cache == []


@pytest.mark.parametrize("mode", ["rb", "ab"])
def test_source_or_reopened_handle_cannot_release_cache(tmp_path, release_cache, mode):
    path = tmp_path / "existing.bin"
    path.write_bytes(b"preserve this existing file")
    with path.open(mode) as stream, pytest.raises(ValueError, match="exclusively created"):
        reader.discard_created_cache(stream)
    assert path.read_bytes() == b"preserve this existing file"
    assert release_cache == []


def test_linked_destination_cannot_release_shared_cache(tmp_path, release_cache):
    path = tmp_path / "new.bin"
    with path.open("xb") as stream:
        stream.write(b"new content")
        os.link(path, tmp_path / "second-name.bin")
        with pytest.raises(ValueError, match="exclusively created"):
            reader.discard_created_cache(stream)
    assert release_cache == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX allows renaming an open exclusive writer")
def test_replaced_destination_name_cannot_release_cache(tmp_path, release_cache):
    path = tmp_path / "new.bin"
    with path.open("xb") as stream:
        stream.write(b"created inode")
        path.rename(tmp_path / "retained.bin")
        path.write_bytes(b"different inode")
        with pytest.raises(ValueError, match="identity changed"):
            reader.discard_created_cache(stream)
    assert release_cache == []


def test_sqlite_created_output_is_checked_before_release(tmp_path, readv, release_cache, monkeypatch):
    original = tmp_path / "original.sqlite"
    with sqlite3.connect(original) as db:
        db.execute("CREATE TABLE recorded (id INTEGER PRIMARY KEY)")
        db.execute("INSERT INTO recorded VALUES (17)")
    target = tmp_path / "new.sqlite"
    real_release = source.discard_created_cache
    verified = []

    def release(stream):
        if Path(stream.name) == target:
            # All SQLite writers have closed before release of the reserved fd.
            with sqlite3.connect(target, timeout=0) as db:
                db.execute("BEGIN EXCLUSIVE")
                assert db.execute("PRAGMA quick_check").fetchone() == ("ok",)
                assert db.execute("SELECT id FROM recorded").fetchall() == [(17,)]
            verified.append(True)
        real_release(stream)

    monkeypatch.setattr(source, "discard_created_cache", release)
    source.sqlite_snapshot(original, target, lambda: None)
    assert verified == [True]
    assert (original.stat().st_dev, original.stat().st_ino) not in release_cache
    before = target.read_bytes()
    with pytest.raises(FileExistsError):
        source.sqlite_snapshot(original, target, lambda: None)
    assert target.read_bytes() == before


@pytest.mark.parametrize("number", [errno.EOPNOTSUPP, errno.EIO])
def test_private_cache_advisory_unsupported_or_real_error(tmp_path, release_cache, monkeypatch, number):
    def failure(*_):
        raise OSError(number, "controlled private descriptor advice failure")

    monkeypatch.setattr(reader.os, "posix_fadvise", failure)
    target = tmp_path / "new.bin"
    with target.open("xb") as stream:
        stream.write(b"completed private bytes")
        if number == errno.EOPNOTSUPP:
            with pytest.warns(RuntimeWarning, match="resource guards remain unchanged"):
                reader.discard_created_cache(stream)
        else:
            with pytest.raises(OSError) as error:
                reader.discard_created_cache(stream)
            assert error.value.errno == errno.EIO
    assert target.read_bytes() == b"completed private bytes"
