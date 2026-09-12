"""Real child-process diagnostics; fixture text is transport data, never rates."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

import pi_drive_backup as backup
import pi_drive_backup_diagnostics as diagnostics


@pytest.fixture
def spool(tmp_path):
    path = tmp_path / "spool"
    path.mkdir(mode=0o700)
    return path.resolve()


def report(spool):
    paths = list((spool / "diagnostics").glob("*/result.json"))
    assert len(paths) == 1
    return paths[0], json.loads(paths[0].read_text())


def real_child(monkeypatch, spool, code):
    original = subprocess.Popen
    monkeypatch.setattr(backup.subprocess, "Popen", lambda _command, **kwargs:
                        original([sys.executable, "-c", code], **kwargs))
    monkeypatch.setattr(backup, "guard_window", lambda: None)
    return backup.Restic(backup.Config(spool / "unused-data", spool, "unused-repository",
                        spool / "unused-password", spool / "unused-rclone", []))


def test_failed_restic_preserves_private_bound_evidence_without_disclosing_text(monkeypatch, spool):
    private = "Bearer private-token-marker https://provider.invalid/?token=private-token-marker"
    client = real_child(monkeypatch, spool,
        f"import sys;sys.stderr.write('rateLimitExceeded {private}');sys.exit(1)")
    with pytest.raises(RuntimeError) as failed:
        client.run("backup", "--json")
    assert "API_RATE_LIMIT" in str(failed.value) and "diagnostic=" in str(failed.value)
    assert "private-token-marker" not in str(failed.value) and "provider.invalid" not in str(failed.value)
    path, value = report(spool)
    assert value["exit_code"] == 1 and value["reader_complete"] and value["category"] == "API_RATE_LIMIT"
    assert private.encode() in (path.parent / "stderr.head").read_bytes()
    assert value["stderr_head_sha256"] == hashlib.sha256((path.parent / "stderr.head").read_bytes()).hexdigest()
    assert all("private-token-marker" not in item.read_text() for item in path.parent.glob("*.json"))
    assert not (spool / "latest-verified.json").exists()
    if os.name == "posix":
        assert path.parent.stat().st_mode & 0o777 == 0o700
        assert all(item.stat().st_mode & 0o777 == 0o600 for item in path.parent.iterdir())


def test_large_stderr_keeps_head_and_final_cause_with_fixed_disk_bound(spool):
    code = "import sys;sys.stderr.buffer.write(b'BEGIN'+b'x'*(2*1024*1024)+b'END storageQuotaExceeded');sys.exit(1)"
    with diagnostics.StderrCapture(spool, "backup") as capture:
        process = subprocess.Popen([sys.executable, "-c", code], stderr=subprocess.PIPE)
        capture.attach(process.stderr, process.pid)
        assert process.wait(timeout=20) == 1
        summary = capture.finish(process.returncode)
    assert summary["category"] == "REMOTE_STORAGE_QUOTA"
    path, value = report(spool)
    assert (path.parent / "stderr.head").read_bytes().startswith(b"BEGIN")
    assert (path.parent / "stderr.tail").read_bytes().endswith(b"END storageQuotaExceeded")
    assert (path.parent / "stderr.head").stat().st_size == diagnostics.HEAD_BYTES
    assert (path.parent / "stderr.tail").stat().st_size == diagnostics.TAIL_BYTES
    assert not (path.parent / "stderr.tail.pending").exists()
    assert value["stderr_truncated"] and value["stderr_bytes_observed"] > 2 * 1024 * 1024


@pytest.mark.parametrize(("message", "category"), [
    (b"invalid_grant token=private", "AUTHORIZATION"),
    (b"storageQuotaExceeded", "REMOTE_STORAGE_QUOTA"),
    (b"rateLimitExceeded: quota metric Queries", "API_RATE_LIMIT"),
    (b"userRateLimitExceeded", "API_RATE_LIMIT"),
    (b"permission denied", "PERMISSION"),
    (b"connection reset by peer", "NETWORK"),
    (b"repository is already locked", "REPOSITORY_LOCK"),
    (b"no space left on device", "DISK_SPACE"),
    (b"out of memory", "MEMORY"),
    (b"ciphertext verification failed", "REPOSITORY_INTEGRITY"),
    (b"unrecognized private provider message", "UNCLASSIFIED"),
])
def test_only_fixed_categories_leave_private_raw_text(message, category):
    assert diagnostics.classify(message, 1) == category
    assert diagnostics.classify(message, 0) == "NONE"
    assert diagnostics.classify(message, 11) == "REPOSITORY_LOCK"
    assert diagnostics.classify(message, -15, interrupted=True) == "INTERRUPTED"


def test_success_stdout_contract_and_lock_refusal_remain_intact(monkeypatch, spool):
    client = real_child(monkeypatch, spool, "import sys;sys.stdout.buffer.write(b'unchanged-stdout-contract\\n')")
    assert client.run("stats", "--json") == "unchanged-stdout-contract\n"
    _, value = report(spool)
    assert value["exit_code"] == 0 and value["category"] == "NONE"


def test_repository_lock_retains_blocked_semantics(monkeypatch, spool):
    client = real_child(monkeypatch, spool, "import sys;sys.stderr.write('locked by private-owner');sys.exit(11)")
    with pytest.raises(backup.Blocked, match="no automatic unlock performed") as failed:
        client.run("backup", "--json")
    assert "private-owner" not in str(failed.value)
    _, value = report(spool)
    assert value["category"] == "REPOSITORY_LOCK" and value["exit_code"] == 11


def test_guard_interruption_terminates_child_and_retains_diagnostics(monkeypatch, spool):
    ready = spool / "ready"
    code = ("import pathlib,sys,time;sys.stderr.write('private-before-stop');sys.stderr.flush();"
            f"pathlib.Path({str(ready)!r}).touch();time.sleep(30)")
    client = real_child(monkeypatch, spool, code)
    def guard():
        if ready.exists():
            raise backup.Blocked("test quiet-window stop")
    monkeypatch.setattr(backup, "guard_window", guard)
    with pytest.raises(backup.Blocked, match="test quiet-window stop"):
        client.run("backup")
    path, value = report(spool)
    assert value["exit_code"] != 0 and value["category"] == "INTERRUPTED" and value["reader_complete"]
    assert b"private-before-stop" in (path.parent / "stderr.tail").read_bytes()


def test_worker_operation_and_request_hash_are_bound_without_config_text(spool):
    operation = spool / "resource-runs" / ("a" * 32)
    operation.mkdir(parents=True, mode=0o700)
    raw = b'{"supervisor_pid":123,"config":{"private":"credential-marker"}}'
    (operation / "request.json").write_bytes(raw)
    with diagnostics.operation_scope(operation), diagnostics.StderrCapture(spool, "check") as capture:
        process = subprocess.Popen([sys.executable, "-c", "pass"], stderr=subprocess.PIPE)
        capture.attach(process.stderr, process.pid)
        process.wait(timeout=5)
        capture.finish(process.returncode)
    value = json.loads((capture.path / "result.json").read_text())
    assert value["operation_id"] == "a" * 32 and value["request_sha256"] == hashlib.sha256(raw).hexdigest()
    assert "credential-marker" not in json.dumps(value)
    assert capture.path.parent == operation / "diagnostics"


def test_operation_cannot_redirect_diagnostics_outside_spool(spool):
    with diagnostics.operation_scope(spool.parent), pytest.raises(ValueError, match="protected operation"):
        diagnostics.StderrCapture(spool, "backup")
    assert not (spool.parent / "diagnostics").exists()


@pytest.mark.parametrize("fault", ["reader", "result"])
@pytest.mark.parametrize("error_type", [backup.Blocked, RuntimeError])
def test_diagnostic_failure_preserves_primary_blocked_interruption(monkeypatch, spool, fault, error_type):
    ready = spool / "ready"
    code = ("import pathlib,sys,time;sys.stderr.write('private-before-stop');sys.stderr.flush();"
            f"pathlib.Path({str(ready)!r}).touch();time.sleep(30)")
    client = real_child(monkeypatch, spool, code)
    original = diagnostics._private_file
    def fail_capture(path, raw):
        if path.name == ("stderr.tail.pending" if fault == "reader" else "result.json"):
            raise OSError("fixture diagnostic filesystem failure")
        return original(path, raw)
    monkeypatch.setattr(diagnostics, "_private_file", fail_capture)
    def guard():
        if ready.exists():
            raise error_type("original guard interruption")
    monkeypatch.setattr(backup, "guard_window", guard)
    with pytest.raises(error_type, match="original guard interruption"):
        client.run("backup")
    command = next((spool / "diagnostics").iterdir())
    assert (command / "started.json").is_file()
    if fault == "reader":
        value = json.loads((command / "result.json").read_text())
        assert value["result"] == "INCOMPLETE" and value["reader_error"]
        assert value["category"] == "DIAGNOSTIC_CAPTURE_INCOMPLETE"
        assert value["stderr_tail_sha256"] == hashlib.sha256((command / "stderr.tail").read_bytes()).hexdigest()
    else:
        assert not (command / "result.json").exists()
    assert not (spool / "latest-verified.json").exists()


def test_reader_failure_terminates_a_child_that_ignores_closed_stderr(monkeypatch, spool):
    client = real_child(monkeypatch, spool,
        "import os,time;os.write(2,b'private transport marker');time.sleep(30)")
    original = diagnostics._private_file
    def fail_capture(path, raw):
        if path.name == "stderr.tail.pending":
            raise OSError("fixture reader failure")
        return original(path, raw)
    monkeypatch.setattr(diagnostics, "_private_file", fail_capture)
    began = time.monotonic()
    def guard():
        if time.monotonic() - began > 6:
            raise backup.Blocked("test-only fallback deadline")
    monkeypatch.setattr(backup, "guard_window", guard)
    with pytest.raises(RuntimeError, match="diagnostic reader failed"):
        client.run("backup")
    assert time.monotonic() - began < 5
    _, value = report(spool)
    assert value["reader_error"] and value["exit_code"] != 0
    assert value["result"] == "INCOMPLETE"


@pytest.mark.parametrize("returncode", [0, 1, 11])
def test_nonzero_exit_semantics_survive_final_receipt_failure(monkeypatch, spool, returncode):
    client = real_child(monkeypatch, spool, f"import sys;sys.stderr.write('private text');sys.exit({returncode})")
    original = diagnostics._private_file
    def fail_capture(path, raw):
        if path.name == "result.json":
            raise OSError("fixture final receipt failure")
        return original(path, raw)
    monkeypatch.setattr(diagnostics, "_private_file", fail_capture)
    if returncode == 11:
        error_type, match = backup.Blocked, "repository lock prevents backup.*no automatic unlock"
    elif returncode:
        error_type, match = RuntimeError, "restic backup failed with exit 1;.*DIAGNOSTIC_CAPTURE_INCOMPLETE"
    else:
        error_type, match = OSError, "fixture final receipt failure"
    with pytest.raises(error_type, match=match):
        client.run("backup")
    command = next((spool / "diagnostics").iterdir())
    assert (command / "started.json").exists() and not (command / "result.json").exists()
    assert not (spool / "latest-verified.json").exists()


def test_noncontiguous_stderr_cannot_invent_a_failure_signature(spool):
    code = ("import sys;sys.stderr.buffer.write(b'x'*" + str(diagnostics.HEAD_BYTES - 8)
            + "+b'invalid_'+b'discarded'*(32*1024)+b'grant'+b'x'*"
            + str(diagnostics.TAIL_BYTES - 5) + ");sys.exit(1)")
    with diagnostics.StderrCapture(spool, "backup") as capture:
        process = subprocess.Popen([sys.executable, "-c", code], stderr=subprocess.PIPE)
        capture.attach(process.stderr, process.pid)
        assert process.wait(timeout=20) == 1
        value = capture.finish(process.returncode)
    assert value["category"] == "UNCLASSIFIED"
    path, receipt = report(spool)
    assert receipt["stderr_truncated"]
    assert (path.parent / "stderr.head").read_bytes().endswith(b"invalid_")
    assert (path.parent / "stderr.tail").read_bytes().startswith(b"grant")


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group exit race")
def test_child_exit_race_during_cleanup_keeps_primary_guard_failure(monkeypatch, spool):
    ready = spool / "ready"
    client = real_child(monkeypatch, spool,
        f"import pathlib,time;pathlib.Path({str(ready)!r}).touch();time.sleep(30)")
    original = os.killpg
    def exited_between_poll_and_signal(pid, sig):
        original(pid, sig)
        raise ProcessLookupError("fixture already-exited process group")
    monkeypatch.setattr(os, "killpg", exited_between_poll_and_signal)
    def guard():
        if ready.exists():
            raise backup.Blocked("original guard failure")
    monkeypatch.setattr(backup, "guard_window", guard)
    with pytest.raises(backup.Blocked, match="original guard failure"):
        client.run("backup")
    _, value = report(spool)
    assert value["category"] == "INTERRUPTED" and value["exit_code"] != 0


def test_diagnostic_failure_without_primary_error_still_fails_closed(monkeypatch, spool):
    client = real_child(monkeypatch, spool, "import sys;sys.stderr.write('transport fixture')")
    original = diagnostics._private_file
    def fail_capture(path, raw):
        if path.name == "stderr.tail.pending":
            raise OSError("fixture diagnostic filesystem failure")
        return original(path, raw)
    monkeypatch.setattr(diagnostics, "_private_file", fail_capture)
    with pytest.raises(RuntimeError, match="Restic diagnostic capture incomplete"):
        client.run("stats")
    _, value = report(spool)
    assert value["result"] == "INCOMPLETE" and value["exit_code"] == 0
    assert not (spool / "latest-verified.json").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX abrupt-wrapper and mode proof")
def test_killed_wrapper_preserves_raw_prefix_tail_without_inventing_completion(spool):
    ready = spool / "wrapper-ready"
    code = ("import pathlib,subprocess,sys,time;from pi_drive_backup_diagnostics import StderrCapture;"
        f"c=StderrCapture(pathlib.Path({str(spool)!r}),'backup');"
        "p=subprocess.Popen([sys.executable,'-c',\"import sys;sys.stderr.write('retained-before-wrapper-kill')\"],stderr=subprocess.PIPE);"
        "c.attach(p.stderr,p.pid);p.wait(timeout=5);c.thread.join(timeout=5);"
        f"pathlib.Path({str(ready)!r}).touch();time.sleep(60)")
    wrapper = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 8
        while not ready.exists() and wrapper.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists()
        wrapper.kill()
        wrapper.wait(timeout=5)
    finally:
        if wrapper.poll() is None:
            wrapper.kill()
            wrapper.wait(timeout=5)
    command = next((spool / "diagnostics").iterdir())
    assert b"retained-before-wrapper-kill" in (command / "stderr.tail").read_bytes()
    assert json.loads((command / "started.json").read_text())["result"] == "STARTED"
    assert not (command / "result.json").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink proof")
def test_symlink_diagnostic_destination_refused(spool):
    outside = spool.parent / "outside"
    outside.mkdir()
    (spool / "diagnostics").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="unsafe diagnostic directory"):
        diagnostics.StderrCapture(spool, "backup")
    assert not list(outside.iterdir())
