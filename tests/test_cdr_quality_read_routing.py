"""Supervised audit routing, with real retained rows and portable syscall seams."""
import errno
import os
from types import SimpleNamespace

import pytest

import cdr_quality_sources as sources
import pi_cdr_quality_read_io as read_io
from tests.cdr_dropbehind_helpers import dropbehind_syscall_contract


def test_audit_hash_routing_preserves_budget_and_portable_default(monkeypatch):
    calls, path = [], "path"
    budget = lambda **_: None
    def required(given, **kwargs):
        calls.append(("required", given, kwargs))
        return SimpleNamespace(sha256="strict"), None
    def portable(given, **kwargs):
        calls.append(("portable", given, kwargs))
        return "portable"
    monkeypatch.setattr(sources, "read_digest", required)
    monkeypatch.setattr(sources, "portable_hash_file", portable)
    assert sources.hash_file(path, budget=budget) == "portable"
    with read_io.require_dropbehind_reads():
        assert sources.hash_file(path, budget=budget) == "strict"
    assert calls == [("portable", path, {"budget": budget}), ("required", path, {"budget": budget})]


@pytest.mark.skipif(os.name != "posix", reason="Existing descriptor identity contract requires POSIX test filesystem")
def test_supervised_retained_source_audit_uses_required_reader(tmp_path, monkeypatch):
    from tests.test_cdr_quality_sources import retained_partition
    source, _ = retained_partition(tmp_path)
    original, calls = read_io.os.preadv, []
    def preadv(fd, vectors, offset, flags):
        calls.append(flags)
        return original(fd, vectors, offset, flags)
    monkeypatch.setattr(read_io, "os", SimpleNamespace(preadv=preadv))
    with read_io.require_dropbehind_reads():
        result = sources.audit_source(tmp_path, source)
    assert result["sqlite_to_export"]["status"] == "PASS"
    assert calls and set(calls) == {0x80}
    def unsupported(*_):
        raise OSError(errno.EOPNOTSUPP, "unsupported required read")
    monkeypatch.setattr(read_io, "os", SimpleNamespace(preadv=unsupported))
    with read_io.require_dropbehind_reads(), pytest.raises(OSError) as error:
        sources.audit_source(tmp_path, source)
    assert error.value.errno == errno.EOPNOTSUPP


@pytest.mark.skipif(os.name != "posix", reason="Existing descriptor identity contract requires POSIX test filesystem")
def test_audit_contract_budget_rejects_before_file_read(tmp_path, monkeypatch):
    path = tmp_path / "contract"
    path.write_bytes(b"contract-control")
    charges = []
    def budget(**kw):
        charges.append(kw)
        if "reserve_bytes" in kw:
            raise ValueError("contract exceeds bounded read limit")
    monkeypatch.setattr(read_io, "os", SimpleNamespace(preadv=lambda *_: pytest.fail("budget must reject first")))
    with read_io.require_dropbehind_reads(), pytest.raises(ValueError, match="bounded read limit"):
        sources.hash_file(path, budget=budget)
    assert charges == [{"entries": 1}, {"reserve_bytes": len(b"contract-control")}]
