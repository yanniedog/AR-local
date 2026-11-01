"""Focused A3 selective-diagnostic and process-safety tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from argparse import Namespace
from contextlib import ExitStack, contextmanager, nullcontext
from pathlib import Path

import pytest

import laptop_backup_scheduled as scheduled
import laptop_pull_backup as receiver


CANDIDATE = "c" * 40
PROTECTED = "9" * 40
# These subprocesses use only the standard library. A Windows venv executable
# can be a redirector whose PID/handle does not own the actual interpreter.
PROCESS_PYTHON = getattr(sys, "_base_executable", sys.executable)


def test_scheduled_receiver_selects_only_stale_diagnostics(tmp_path: Path) -> None:
    args = Namespace(
        target=tmp_path,
        host="192.168.20.19",
        ssh_user="pi",
        ssh_port=22,
        ssh_path=r"C:\Windows\System32\OpenSSH\ssh.exe",
        ssh_sha256="a" * 64,
        scp_path=r"C:\Windows\System32\OpenSSH\scp.exe",
        scp_sha256="b" * 64,
        ssh_identity=r"C:\Program Files\AR-local\ssh\id",
        ssh_known_hosts=r"C:\Program Files\AR-local\ssh\known_hosts",
        recovery_image=tmp_path / "image",
        candidate_code_sha=CANDIDATE,
        protected_code_sha=PROTECTED,
        plan_git_commit=receiver.PLAN_GIT_COMMIT,
        source_helper=None,
        operator="pytest",
    )
    values = scheduled.receiver_arguments(
        args,
        "backup-latest",
        include_diagnostic_dates=["2026-08-22"],
    )
    assert values[-3:] == [
        "--select-diagnostics", "--include-diagnostic-date", "2026-08-22"
    ]


def test_backup_jobs_can_exclude_already_verified_diagnostics() -> None:
    retained = [
        {"date": "2026-08-22", "status": "diagnostic"},
        {"date": "2026-08-29", "status": "completed"},
    ]
    _latest, selected = receiver.backup_jobs(
        retained,
        "backup-latest",
        "2026-05-21",
        include_diagnostic_dates=[],
    )
    assert selected == [
        ("observation", "2026-08-29"),
        ("control", None),
        ("macro", None),
    ]


def test_windows_process_liveness_probe_does_not_terminate_target() -> None:
    child = subprocess.Popen(
        [PROCESS_PYTHON, "-I", "-S", "-B", "-c",
         "import os,time; print(os.getpid(),flush=True); time.sleep(30)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert int(child.stdout.readline().strip()) == child.pid
        assert receiver.process_alive(child.pid)
        assert child.poll() is None
        assert receiver.process_descends_from(child.pid, os.getpid())
        assert child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=10)
        child.stdout.close()


@contextmanager
def grandchild_exit_witness(pid: int):
    """Retain kernel identity while alive; never signal a recycled numeric PID."""
    if os.name == "nt":
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        kernel.WaitForSingleObject.restype = ctypes.c_uint32
        kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
        handle = kernel.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE, no signal rights.
        assert handle, "cannot bind grandchild exit witness"
        try:
            yield lambda: kernel.WaitForSingleObject(handle, 5000) == 0
        finally:
            kernel.CloseHandle(handle)
    else:
        import select
        descriptor = os.pidfd_open(pid)
        try:
            yield lambda: bool(select.select([descriptor], [], [], 5)[0])
        finally:
            os.close(descriptor)


@pytest.mark.parametrize("cleanup_case", ["normal", "assertion", "timeout"])
def test_process_ancestry_accepts_live_grandchild_without_signalling(cleanup_case: str) -> None:
    # Unhandled termination of this Python bypasses finally and orphans p.
    # Closing its stdin instead lets its actual parent stop AND reap p.
    script = """
import json, os, signal, subprocess, sys, time
def stop(_number, _frame):
    raise SystemExit(0)
if os.name != 'nt':
    signal.signal(signal.SIGTERM, stop)
# Only this parent owns the writer. Killing it also closes the grandchild's
# stdin, so the grandchild exits even if this parent's finally cannot run.
p = subprocess.Popen([getattr(sys, '_base_executable', sys.executable), '-I', '-S', '-B', '-c',
                      'import os,sys; print(os.getpid(),flush=True); sys.stdin.read()'],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, close_fds=True)
try:
    actual_pid = int(p.stdout.readline().strip())
    print(json.dumps({'pid': os.getpid(), 'grandchild_pid': p.pid,
                      'grandchild_reported_pid': actual_pid}), flush=True)
    if sys.argv[1] == 'timeout':
        time.sleep(30)
    else:
        sys.stdin.read()
finally:
    try:
        p.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait(timeout=5)
    print(json.dumps({'reaped_pid': p.pid, 'returncode': p.returncode}), flush=True)
"""
    child = subprocess.Popen(
        [PROCESS_PYTHON, "-I", "-S", "-B", "-c", script, cleanup_case],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    expected = (pytest.raises(AssertionError, match="injected fixture assertion")
                if cleanup_case == "assertion" else nullcontext())
    wait_grandchild, timed_out = None, False
    with expected, ExitStack() as stack:
        try:
            assert child.stdout is not None
            ready = json.loads(child.stdout.readline())
            assert ready["pid"] == child.pid
            grandchild_pid = ready["grandchild_pid"]
            assert ready["grandchild_reported_pid"] == grandchild_pid
            assert receiver.process_descends_from(grandchild_pid, os.getpid())
            assert receiver.process_alive(grandchild_pid)
            wait_grandchild = stack.enter_context(grandchild_exit_witness(grandchild_pid))
            if cleanup_case == "assertion":
                raise AssertionError("injected fixture assertion")
        finally:
            try:
                stdout, stderr = child.communicate(timeout=0.05 if cleanup_case == "timeout" else 15)
            except subprocess.TimeoutExpired:
                timed_out = True
                # POSIX keeps the actual parent alive to reap its grandchild.
                # Windows terminates the bound interpreter; its private writer
                # closes and the grandchild exits (there are no POSIX zombies).
                child.terminate()
                try:
                    stdout, stderr = child.communicate(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()  # Emergency cleanup of only the Popen-owned intermediate.
                    child.communicate(timeout=5)
                    pytest.fail("intermediate cooperative cleanup did not complete")
            if wait_grandchild is not None:
                assert wait_grandchild(), "grandchild exit not proved"
            else:
                assert not timed_out, "forced teardown without grandchild exit witness"
            assert timed_out == (cleanup_case == "timeout"), "unexpected teardown timeout"
            if os.name != "nt" or not timed_out:
                assert child.returncode == 0, stderr
                # pidfd readiness proves exit, not wait/reaping. This receipt
                # comes only after the real parent's communicate/wait completed.
                assert json.loads(stdout) == {"reaped_pid": grandchild_pid, "returncode": 0}
