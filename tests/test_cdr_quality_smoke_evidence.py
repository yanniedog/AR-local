"""Real child-output fixtures test diagnostic transport, not CDR acceptance."""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

import pi_cdr_quality_activate as activate
import pi_cdr_quality_smoke as smoke
from cdr_quality_accounting import canonical_digest


def sealed_source(tmp_path, program="print('verified')\n"):
    source = tmp_path / "source"
    source.mkdir()
    (source / "verify_local.py").write_text(program)
    (source / "smoke_helper.py").write_text("VALUE = 'sealed'\n")
    activate.git(source, "init", "--quiet")
    activate.git(source, "add", ".")
    activate.git(source, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "--quiet", "-m", "source integrity fixture")
    return source, activate.clean_commit(source), activate.source_files(source)


def test_live_verifier_output_and_failed_endpoint_survive(tmp_path, monkeypatch):
    import pi_deploy_verify
    monkeypatch.setattr(pi_deploy_verify, "wait_for_http_smoke", lambda *_args, **_kwargs: 0)
    source, commit, files = sealed_source(tmp_path,
        "import sys,time\nprint('stdout-live',flush=True)\n"
        "print('verify_local: 0 http://test.invalid/api/banks/history/section',file=sys.stderr,flush=True)\n"
        "time.sleep(1.5)\nraise SystemExit(1)\n")
    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(activate.smoke, source, operation=tmp_path, phase="post-switch", commit=commit, files=files)
        output = tmp_path / "smoke/post-switch-verify-local.log"
        deadline = time.monotonic() + 1.25
        while time.monotonic() < deadline and (not output.exists() or "stdout-live" not in output.read_text()):
            time.sleep(0.02)
        assert "stdout-live" in output.read_text() and "history/section" in output.read_text()
        assert not future.done()
        with pytest.raises(RuntimeError, match="post-switch-verify-local failed") as error:
            future.result(timeout=5)
    assert "history/section" in str(error.value)
    result = json.loads((tmp_path / "smoke/post-switch-verify-local.json").read_text())
    assert result["result"] == "FAIL" and result["started_at"] < result["completed_at"]
    assert result["output"] == activate.record(output)
    assert result["check"] == {"verifier": activate.record(source / "verify_local.py"),
                               "sealed_commit": commit, "source_files_sha256": canonical_digest(files),
                               "timeout_seconds": 300, "history_timeout_seconds": 90}
    assert "command started" in output.read_text() and "command finished" in output.read_text()


def test_readiness_failure_retains_both_streams_and_blocks_verifier(tmp_path, monkeypatch):
    import pi_deploy_verify
    def unready(*_args, **kwargs):
        assert kwargs == {"require_rates": True, "budget_seconds": 120}
        print("retrying readiness")
        print("HTTP readiness failure", file=sys.stderr)
        return 1
    monkeypatch.setattr(pi_deploy_verify, "wait_for_http_smoke", unready)
    source, commit, files = sealed_source(tmp_path)
    real_run = activate.run
    def run(argv, **kwargs):
        assert not kwargs.get("output"), "verifier must not run"
        return real_run(argv, **kwargs)
    monkeypatch.setattr(activate, "run", run)
    with pytest.raises(RuntimeError, match="HTTP readiness failure"):
        activate.smoke(source, operation=tmp_path, phase="pre-switch", commit=commit, files=files)
    log = tmp_path / "smoke/pre-switch-readiness.log"
    assert "retrying readiness" in log.read_text() and "HTTP readiness failure" in log.read_text()
    assert not (tmp_path / "smoke/pre-switch-verify-local.log").exists()


def test_timed_out_child_keeps_output_and_timed_phase_receipt(tmp_path):
    with pytest.raises(RuntimeError, match="TimeoutExpired"):
        smoke.smoke_phase(tmp_path, "post-switch-verify-local", lambda output: activate.run(
            [sys.executable, "-u", "-c", "import time; print('before-timeout',flush=True); time.sleep(30)"],
            output=output, timeout=0.6))
    result = json.loads((tmp_path / "smoke/post-switch-verify-local.json").read_text())
    assert result["result"] == "FAIL" and result["error_type"] == "TimeoutExpired"
    assert "before-timeout" in result["output_tail"]


def test_phase_evidence_never_overwrites_and_rollback_is_separate(tmp_path):
    def fail(output):
        output.write_text("actual failed check\n")
        raise RuntimeError("fixture failure")
    for phase in ("pre-switch-readiness", "post-switch-verify-local", "rollback-readiness"):
        with pytest.raises(RuntimeError, match="fixture failure"):
            smoke.smoke_phase(tmp_path, phase, fail)
    before = {path: path.read_bytes() for path in (tmp_path / "smoke").iterdir()}
    with pytest.raises(FileExistsError):
        smoke.smoke_phase(tmp_path, "post-switch-verify-local", fail)
    assert before == {path: path.read_bytes() for path in before}
    assert len(smoke.smoke_records(tmp_path)) == 3


def test_failure_tail_read_is_bounded(tmp_path):
    output = tmp_path / "large.log"
    output.write_bytes(b"x" * (2 * 1024 * 1024) + b"\nfinal failed endpoint")
    tail = smoke.output_tail(output)
    assert len(tail.encode()) <= 8192 and tail.endswith("final failed endpoint")


@pytest.mark.parametrize("phase", ["pre-switch", "post-switch", "rollback"])
@pytest.mark.parametrize("filename", ["verify_local.py", "smoke_helper.py"])
def test_each_phase_rejects_changed_source_even_when_git_status_ignores_it(tmp_path, monkeypatch, phase, filename):
    import pi_deploy_verify
    source, commit, files = sealed_source(tmp_path)
    activate.git(source, "update-index", "--assume-unchanged", filename)
    (source / filename).write_text("raise SystemExit('unsealed program')\n")
    assert activate.clean_commit(source) == commit
    monkeypatch.setattr(pi_deploy_verify, "wait_for_http_smoke", lambda *_a, **_kw: pytest.fail("must not execute"))
    with pytest.raises(RuntimeError, match="complete source inventory"):
        activate.smoke(source, operation=tmp_path, phase=phase, commit=commit, files=files)
    result = json.loads((tmp_path / f"smoke/{phase}-readiness.json").read_text())
    assert result["result"] == "FAIL" and result["check"]["sealed_commit"] == commit
    assert not (tmp_path / f"smoke/{phase}-verify-local.log").exists()


@pytest.mark.parametrize("when", ["readiness", "between-checks", "verifier"])
def test_source_change_during_smoke_cannot_produce_pass(tmp_path, monkeypatch, when):
    import pi_deploy_verify
    source, commit, files = sealed_source(tmp_path)
    def mutate():
        (source / "smoke_helper.py").write_text("VALUE = 'unsealed'\n")
    def readiness(*_a, **_kw):
        if when == "readiness":
            mutate()
        return 0
    monkeypatch.setattr(pi_deploy_verify, "wait_for_http_smoke", readiness)
    original_phase = smoke.smoke_phase
    def phase(*args, **kwargs):
        original_phase(*args, **kwargs)
        if when == "between-checks" and args[1].endswith("-readiness"):
            mutate()
    monkeypatch.setattr(smoke, "smoke_phase", phase)
    real_run = activate.run
    def run(argv, **kwargs):
        if kwargs.get("output"):
            assert when == "verifier", "changed verifier must never launch"
            kwargs["output"].write_text("command reported success\n")
            mutate()
            return ""
        return real_run(argv, **kwargs)
    monkeypatch.setattr(activate, "run", run)
    with pytest.raises(RuntimeError, match="checkout contains uncommitted"):
        activate.smoke(source, operation=tmp_path, phase="post-switch", commit=commit, files=files)
    failed = "readiness" if when == "readiness" else "verify-local"
    result = json.loads((tmp_path / f"smoke/post-switch-{failed}.json").read_text())
    assert result["result"] == "FAIL"
