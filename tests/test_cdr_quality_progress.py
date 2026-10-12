"""Prove private canary progress exists before work finishes, without Pi calls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

import pi_cdr_quality_activate as activate


@pytest.fixture
def worker_command(tmp_path, monkeypatch):
    roots = {name: tmp_path / name for name in ("source", "production", "data", "operation")}
    for path in roots.values():
        path.mkdir()
    args = SimpleNamespace(source=roots["source"], production=roots["production"], data_root=roots["data"],
                           operation=roots["operation"], python=sys.executable, verified_cache=None,
                           verified_cache_sha256=None)
    monkeypatch.setattr(activate, "os", SimpleNamespace(name="posix", access=lambda *_: False, W_OK=os.W_OK, fsync=os.fsync))
    monkeypatch.setattr(activate, "clean_commit", lambda _: "a" * 40)
    for name in ("protected_files", "source_files", "control_state", "rollback_contract"):
        monkeypatch.setattr(activate, name, lambda *_: {})
    monkeypatch.setattr(activate, "require_controls", lambda *_: None)
    monkeypatch.setattr(activate, "current_state", lambda _: ("2026-10-12", "unused-control", roots["data"]))
    captured = {}
    class ReachedPytest(Exception):
        pass
    def stop_at_pytest(command, **kwargs):
        captured.update(command=command, **kwargs)
        raise ReachedPytest()
    monkeypatch.setattr(activate, "run", stop_at_pytest)
    with pytest.raises(ReachedPytest):
        activate.canary_worker(args)
    return roots, captured


def test_phase_markers_are_create_once_and_precede_pytest(worker_command):
    roots, captured = worker_command
    phases = sorted(roots["operation"].glob("phase-*.json"))
    assert [path.name for path in phases] == ["phase-01-source-snapshot.json", "phase-02-pytest.json"]
    first, second = [json.loads(path.read_bytes()) for path in phases]
    assert first["monotonic_ns"] <= second["monotonic_ns"] and first["started_at"] <= second["started_at"]
    original = phases[1].read_bytes()
    with pytest.raises(FileExistsError):
        activate.canary_phase(roots["operation"], "02-pytest")
    assert phases[1].read_bytes() == original
    assert captured["output"] == roots["operation"] / "pytest.txt"
    assert "-u" in captured["command"] and "-v" in captured["command"] and "-q" not in captured["command"]


def test_native_pytest_progress_identifies_test_while_its_body_is_still_running(worker_command):
    roots, captured = worker_command
    tests = roots["source"] / "tests"
    tests.mkdir()
    (tests / "test_progress_control.py").write_text(
        "from pathlib import Path\nimport time\n"
        "def test_waiting_for_release():\n"
        "    Path('ready').write_text('ready')\n"
        "    deadline = time.monotonic() + 15\n"
        "    while not Path('release').exists() and time.monotonic() < deadline:\n"
        "        time.sleep(0.02)\n"
        "    assert Path('release').exists(), 'bounded progress test timed out'\n")
    log = captured["output"]
    with log.open("xb") as stream:
        child = subprocess.Popen(list(map(str, captured["command"])), cwd=captured["cwd"],
                                 stdout=stream, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 10
            while not (roots["source"] / "ready").exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            assert (roots["source"] / "ready").exists(), log.read_text(errors="replace")
            active_log = log.read_text(errors="replace")
            assert "test_progress_control.py::test_waiting_for_release" in active_log
            assert "PASSED" not in active_log and child.poll() is None
        finally:
            (roots["source"] / "release").write_text("release")
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()  # Only this test-owned child; never a shared console signal.
                child.wait(timeout=5)
    assert child.returncode == 0, log.read_text(errors="replace")
    assert "1 passed" in log.read_text(errors="replace")
