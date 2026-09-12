"""Process lifecycle fault tests, never simulated financial acceptance data."""
from __future__ import annotations

import errno
import os
import subprocess
import sys
from pathlib import Path

import pytest

import pi_cdr_quality_resources as resources


@pytest.fixture
def accounting(tmp_path, monkeypatch):
    group, proc = tmp_path / "group", tmp_path / "proc"
    group.mkdir()
    (group / "cgroup.procs").write_text("101\n")
    (proc / "101").mkdir(parents=True)
    (proc / "101/stat").write_text("101 (private process name) S " + "0 " * 18 + "987\n")
    (proc / "101/smaps_rollup").write_text("Rss: 100 kB\nSwap: 0 kB\n")
    closed = []
    monkeypatch.setattr(resources.os, "pidfd_open", lambda pid, _: pid + 1000, raising=False)
    monkeypatch.setattr(resources.os, "close", closed.append)
    monkeypatch.setattr(resources, "pidfd_exited", lambda *_: False)
    return group, proc, closed


def test_mm_teardown_requires_kernel_exit_proof_before_omission(accounting, monkeypatch):
    group, proc, closed = accounting
    (proc / "101/smaps_rollup").unlink()
    events = []
    def exited(descriptor, wait_ms=0):
        events.append((descriptor, wait_ms))
        (group / "cgroup.procs").write_text("")
        return True
    monkeypatch.setattr(resources, "pidfd_exited", exited)
    assert resources.aggregate(group, proc=proc) == {"rss_bytes": 0, "swap_bytes": 0, "processes": 0}
    assert events == [(1101, 5)] and closed == [1101]


@pytest.mark.parametrize("state", ["R", "S", "Z"])
def test_even_zombie_state_cannot_hide_unreadable_live_pidfd(accounting, monkeypatch, state):
    group, proc, closed = accounting
    (proc / "101/smaps_rollup").unlink()
    (proc / "101/stat").write_text(f"101 (hidden) {state} " + "0 " * 18 + "987\n")
    with pytest.raises(resources.MemoryAccountingError) as caught:
        resources.aggregate(group, proc=proc)
    assert caught.value.details == {"pid": 101, "state": state, "start_ticks": 987,
        "error": "FileNotFoundError", "errno": errno.ENOENT}
    assert "hidden" not in str(caught.value) and closed == [1101]


def test_recycled_numeric_pid_is_reopened_and_accounted(accounting, monkeypatch):
    group, proc, closed = accounting
    handles = iter([1101, 2101])
    monkeypatch.setattr(resources.os, "pidfd_open", lambda *_: next(handles))
    (proc / "101/smaps_rollup").unlink()
    def exited(descriptor, wait_ms=0):
        if descriptor == 1101:
            (proc / "101/smaps_rollup").write_text("Rss: 300 kB\nSwap: 16 kB\n")
            return True
        return False
    monkeypatch.setattr(resources, "pidfd_exited", exited)
    assert resources.aggregate(group, proc=proc) == {"rss_bytes": 300 * 1024, "swap_bytes": 16 * 1024, "processes": 1}
    assert closed == [1101, 2101]


def test_repeated_identity_churn_fails_instead_of_omitting_a_member(accounting, monkeypatch):
    group, proc, closed = accounting
    (proc / "101/smaps_rollup").unlink()
    monkeypatch.setattr(resources, "pidfd_exited", lambda *_: True)
    with pytest.raises(resources.MemoryAccountingError):
        resources.aggregate(group, proc=proc)
    assert closed == [1101, 1101]


def test_successful_high_rss_and_swap_observation_is_retained_after_exit(accounting, monkeypatch):
    group, proc, closed = accounting
    (proc / "101/smaps_rollup").write_text(f"Rss: {3 * resources.GIB // 1024} kB\nSwap: 16 kB\n")
    original = resources.numeric_fields
    def read_then_exit(path):
        observed = original(path)
        (group / "cgroup.procs").write_text("")
        return observed
    monkeypatch.setattr(resources, "numeric_fields", read_then_exit)
    monkeypatch.setattr(resources, "pidfd_exited", lambda *_: True)
    assert resources.aggregate(group, proc=proc) == {"rss_bytes": 3 * resources.GIB, "swap_bytes": 16384, "processes": 1}
    assert closed == [1101]


@pytest.mark.parametrize("failure", ["permission", "missing_rss", "missing_swap"])
def test_permission_and_malformed_accounting_fail_even_if_process_then_exits(accounting, monkeypatch, failure):
    group, proc, closed = accounting
    def invalid(_):
        if failure == "permission":
            raise PermissionError(errno.EACCES, "denied")
        return {"Rss": 1} if failure == "missing_swap" else {"Swap": 0}
    monkeypatch.setattr(resources, "numeric_fields", invalid)
    monkeypatch.setattr(resources, "pidfd_exited", lambda *_: pytest.fail("must not ignore malformed/forbidden accounting"))
    with pytest.raises(resources.MemoryAccountingError) as caught:
        resources.aggregate(group, proc=proc)
    assert caught.value.details["error"] == ("PermissionError" if failure == "permission" else "KeyError")
    assert closed == [1101]


def test_process_gone_before_pidfd_open_is_confirmed_absent(accounting, monkeypatch):
    group, proc, closed = accounting
    def gone(*_):
        (group / "cgroup.procs").write_text("")
        raise ProcessLookupError(errno.ESRCH, "gone")
    monkeypatch.setattr(resources.os, "pidfd_open", gone)
    assert resources.aggregate(group, proc=proc)["processes"] == 0
    assert closed == []


def test_failure_receipt_retains_pid_state_and_errno(accounting, monkeypatch, tmp_path):
    group, proc, _ = accounting
    error = resources.MemoryAccountingError(101, proc, PermissionError(errno.EACCES, "denied"))
    monkeypatch.setattr(resources, "own_cgroup", lambda: group)
    monkeypatch.setattr(resources, "members", lambda _: {os.getpid()})
    monkeypatch.setattr(resources, "preflight", lambda *_args, **_kwargs: (_ for _ in ()).throw(error))
    monkeypatch.setattr(resources, "terminate", lambda *_: True)
    receipt = resources.supervise(["never-started"], tmp_path / "receipt.json", resources.Limits())
    assert receipt["result"] == "BLOCKED" and receipt["accounting_error"] == error.details


@pytest.mark.skipif(sys.platform != "linux" or not hasattr(os, "pidfd_open"), reason="real Linux pidfd lifecycle")
@pytest.mark.parametrize("attempt", range(8))
def test_real_linux_exit_between_membership_and_accounting(monkeypatch, attempt):
    # The child holds no application data. Its actual kernel pidfd, procfs mm
    # teardown and exit are exercised; only the dedicated cgroup inventory is a
    # test stand-in so CI does not need privileged cgroup creation.
    child = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.buffer.read(1)"], stdin=subprocess.PIPE)
    proof = os.pidfd_open(child.pid, 0)
    original = resources.numeric_fields
    def exiting(path):
        if path.name == "smaps_rollup":
            child.stdin.write(b"x")
            child.stdin.flush()
            assert resources.pidfd_exited(proof, 1000)
        return original(path)
    monkeypatch.setattr(resources, "numeric_fields", exiting)
    monkeypatch.setattr(resources, "members", lambda _: set() if resources.pidfd_exited(proof) else {child.pid})
    try:
        assert resources.process_memory(child.pid, Path("unused"), Path("/proc")) is None
        assert child.wait(timeout=2) == 0
    finally:
        child.stdin.close()
        if child.poll() is None:
            child.kill()
            child.wait(timeout=2)
        os.close(proof)


@pytest.mark.skipif(sys.platform != "linux" or not hasattr(os, "pidfd_open"), reason="real Linux pidfd lifecycle")
def test_real_linux_live_handle_with_unreadable_accounting_fails(monkeypatch):
    child = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.buffer.read(1)"], stdin=subprocess.PIPE)
    def unreadable(_):
        raise ProcessLookupError(errno.ESRCH, "injected unavailable accounting on an actually live child")
    monkeypatch.setattr(resources, "numeric_fields", unreadable)
    monkeypatch.setattr(resources, "members", lambda _: {child.pid})
    try:
        with pytest.raises(resources.MemoryAccountingError) as caught:
            resources.process_memory(child.pid, Path("unused"), Path("/proc"))
        assert caught.value.details["pid"] == child.pid and caught.value.details["errno"] == errno.ESRCH
        assert child.poll() is None
    finally:
        child.stdin.close()
        child.wait(timeout=2)
