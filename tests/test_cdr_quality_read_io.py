"""Read-policy/byte contracts; syscall controls do not claim kernel cache proof."""
import errno
import hashlib
import io
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import pi_cdr_quality_activate as activate
import pi_cdr_quality_digest as digest
import pi_cdr_quality_read_io as read_io


def reader(monkeypatch, body, *, short=3, error=None):
    calls = []
    def preadv(fd, vectors, offset, flags):
        calls.append((fd, offset, flags, len(vectors[0])))
        if error:
            raise error
        count = min(len(vectors[0]), short, max(0, len(body) - offset))
        vectors[0][:count] = body[offset:offset + count]
        return count
    monkeypatch.setattr(read_io, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(read_io, "os", SimpleNamespace(preadv=preadv))
    monkeypatch.setattr(read_io, "READ_BYTES", 7)
    return calls


@pytest.mark.parametrize("capture", [False, True])
@pytest.mark.parametrize("size", [0, 1, 6, 7, 8, 31])
def test_short_reads_capture_and_eof_probe(monkeypatch, capture, size):
    body = bytes(range(size))
    calls = reader(monkeypatch, body)
    actual, captured = read_io.hash_dropbehind(42, size, capture)
    assert actual == hashlib.sha256(body).hexdigest()
    assert captured == (body if capture else None)
    assert calls[-1] == (42, size, 0x80, 1)
    assert all(row[2] == 0x80 and 0 < row[3] <= 7 for row in calls)


@pytest.mark.parametrize("size", [3, 5])
@pytest.mark.parametrize("capture", [False, True])
def test_growth_and_truncation_reject(monkeypatch, size, capture):
    reader(monkeypatch, b"four")
    with pytest.raises(ValueError, match="size changed"):
        read_io.hash_dropbehind(42, size, capture)


@pytest.mark.parametrize("size", [0, 3])
@pytest.mark.parametrize("number", [errno.EOPNOTSUPP, errno.ENOSYS, errno.EIO])
def test_errors_never_retry_or_fall_back(monkeypatch, size, number):
    calls = reader(monkeypatch, b"one", error=OSError(number, "read refused"))
    with pytest.raises(OSError) as caught:
        read_io.hash_dropbehind(42, size, False)
    assert caught.value.errno == number and len(calls) == 1


@pytest.mark.parametrize("platform,api", [("win32", True), ("linux", False)])
def test_missing_platform_or_api_is_explicit(monkeypatch, platform, api):
    monkeypatch.setattr(read_io, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(read_io, "os", SimpleNamespace(preadv=lambda *_: pytest.fail("must not read")) if api else SimpleNamespace())
    with pytest.raises(RuntimeError, match="needs Linux preadv2"):
        read_io.hash_dropbehind(42, 0, False)


def test_required_routing_nested_context_and_exception_cleanup(monkeypatch):
    body = b"bounded control bytes"
    calls = reader(monkeypatch, body)
    stream = SimpleNamespace(fileno=lambda: 42)
    assert not read_io.dropbehind_required()
    with read_io.require_dropbehind_reads():
        with pytest.raises(RuntimeError, match="inner"):
            with read_io.require_dropbehind_reads():
                assert digest._hash_stream(stream, len(body), True) == (hashlib.sha256(body).hexdigest(), body)
                raise RuntimeError("inner")
        assert read_io.dropbehind_required()
    assert not read_io.dropbehind_required() and calls
    calls.clear()
    assert digest._hash_stream(io.BytesIO(body), len(body), False) == (hashlib.sha256(body).hexdigest(), None)
    assert not calls  # Standalone portable helpers make no cache qualification claim.


def test_required_policy_is_not_inherited_by_child_python():
    with read_io.require_dropbehind_reads():
        result = subprocess.check_output([sys.executable, "-B", "-c",
            "import pi_cdr_quality_read_io as r; print(r.dropbehind_required())"],
            cwd=Path(read_io.__file__).parent, text=True, timeout=10)
    assert result.strip() == "False"


@pytest.mark.parametrize("entry", [activate.canary_worker, activate.seal])
def test_direct_worker_and_seal_require_policy_and_reset(monkeypatch, entry):
    class Stop(Exception):
        pass
    def layout(*_):
        assert read_io.dropbehind_required()
        raise Stop()
    monkeypatch.setattr(activate, "layout", layout)
    args = SimpleNamespace(source=Path("source"), production=Path("production"),
                           data_root=Path("data"), operation=Path("operation"))
    with pytest.raises(Stop):
        entry(args)
    assert not read_io.dropbehind_required()


def test_forward_runtime_snapshots_are_required(monkeypatch):
    calls = []
    monkeypatch.setattr(activate, "clean_commit", lambda _: "target")
    def source(_):
        calls.append(("source", read_io.dropbehind_required()))
        return {}
    def protected(_):
        calls.append(("protected", read_io.dropbehind_required()))
        return {}
    monkeypatch.setattr(activate, "source_files", source)
    monkeypatch.setattr(activate, "protected_files", protected)
    monkeypatch.setattr(activate, "active", lambda _: "inactive")
    with pytest.raises(RuntimeError, match="not active"):
        activate.verify_runtime(Path("production"), "target", {}, Path("data"), {},
                                operation=Path("op"), verifier_source=Path("source"))
    assert calls == [("source", True), ("protected", True)]
    assert not read_io.dropbehind_required()


@pytest.mark.parametrize("phase,required", [("pre-switch", True), ("post-switch", True), ("rollback", False)])
def test_smoke_snapshot_policy_preserves_rollback_reader(monkeypatch, phase, required):
    import pi_cdr_quality_smoke as smoke
    import pi_deploy_verify
    calls = []
    files = {"verify_local.py": "sealed-hash"}
    monkeypatch.setattr(activate, "clean_commit", lambda _: "target")
    def source(_):
        calls.append(read_io.dropbehind_required())
        return files
    monkeypatch.setattr(activate, "source_files", source)
    monkeypatch.setattr(smoke, "smoke_phase", lambda operation, name, check, **_: check(Path("output")))
    monkeypatch.setattr(smoke, "capture_readiness", lambda output, check: check())
    monkeypatch.setattr(pi_deploy_verify, "wait_for_http_smoke", lambda *_, **__: 0)
    monkeypatch.setattr(activate, "run", lambda *_, **__: "")
    activate.smoke(Path("source"), operation=Path("operation"), phase=phase, commit="target", files=files)
    assert calls == [required] * 4
    assert not read_io.dropbehind_required()


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor mutation controls; byte routing is tested on all platforms")
@pytest.mark.parametrize("change", ["append", "truncate", "overwrite", "replace", "hardlink"])
def test_required_reader_preserves_outer_mutation_guards(tmp_path, monkeypatch, change):
    # Emulate only the flag's syscall seam on CI kernels/filesystems that do not
    # support it. Actual descriptor reads and all production identity checks run.
    path, replacement = tmp_path / "evidence", tmp_path / "replacement"
    path.write_bytes(b"original"); replacement.write_bytes(b"replaced")
    calls = []
    def preadv(fd, vectors, offset, flags):
        assert flags == 0x80
        block = os.pread(fd, len(vectors[0]), offset)
        vectors[0][:len(block)] = block
        calls.append(offset)
        if len(calls) == 1:
            if change == "replace":
                os.replace(replacement, path)
            elif change == "hardlink":
                os.link(path, tmp_path / "alias")
            else:
                path.write_bytes({"append": b"original-extra", "truncate": b"x", "overwrite": b"changed!"}[change])
        return len(block)
    monkeypatch.setattr(read_io, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(read_io, "os", SimpleNamespace(preadv=preadv))
    with read_io.require_dropbehind_reads(), pytest.raises(ValueError, match="changed"):
        digest.read_digest(path, root=tmp_path)
    assert calls
