"""Archive control-plane tests: no synthetic banking observations."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import pi_payload_daily_archive as archive
from cdr_atomic import atomic_write_json

DIGEST = "a" * 64
DAY = "2026-10-29"
NOW = datetime(2026, 10, 29, 23, tzinfo=timezone.utc)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setattr(archive, "data_state_root", lambda _: state)
    monkeypatch.setattr(archive, "data_runs_root", lambda _: tmp_path / "runs")
    monkeypatch.setattr(archive, "window_reason", lambda _: "")
    monkeypatch.setattr(archive, "ingest_clearance", lambda *a, **kw: "")
    monkeypatch.setattr(archive, "selected_source", lambda *a: ({"contract_digest": DIGEST}, tmp_path))
    return tmp_path, state / archive.STATE_DIRECTORY


def receipt(day=DAY, digest=DIGEST):
    return {"schema_version": 1, "status": "archived", "selected_for_app": False,
            "contract_digest": digest, "day": day, "manifest_url": "https://github.com/archive"}


def test_bounded_launch_is_reserved_before_child_and_verified_after(runtime, monkeypatch):
    repo, root = runtime
    def child(command, **kwargs):
        reserved = json.loads((root / "attempts" / (DAY + ".json")).read_bytes())
        assert reserved["status"] == "running"
        assert reserved["contract_digest"] == DIGEST
        assert command[-4:] == ["--worker-date", DAY, "--expected-contract", DIGEST]
        assert kwargs["timeout_seconds"] == 1800
        atomic_write_json(root / "receipts" / (DIGEST + ".json"), receipt())
    monkeypatch.setattr(archive, "run_process_group", child)
    result = archive.run_once(repo, day=DAY)
    assert result["status"] == "archived"
    assert result["receipt"]["selected_for_app"] is False
    assert sorted(p.name for p in (repo / "state").iterdir()) == [archive.STATE_DIRECTORY]


@pytest.mark.parametrize("failure", [subprocess.TimeoutExpired("child", 1800),
                                    subprocess.CalledProcessError(1, "child")])
def test_failure_keeps_durable_cooldown_and_no_success_receipt(runtime, monkeypatch, failure):
    repo, root = runtime
    child = Mock(side_effect=failure)
    monkeypatch.setattr(archive, "run_process_group", child)
    assert archive.run_once(repo, day=DAY)["status"] == "failed"
    record = json.loads((root / "attempts" / (DAY + ".json")).read_bytes())
    assert record["status"] == "failed" and record["attempts"] == 1
    assert archive.run_once(repo, day=DAY)["status"] == "blocked"
    assert child.call_count == 1
    assert not (root / "receipts").exists()


def test_zero_exit_without_receipt_is_failure(runtime, monkeypatch):
    repo, _ = runtime
    monkeypatch.setattr(archive, "run_process_group", lambda *a, **kw: None)
    assert archive.run_once(repo, day=DAY)["status"] == "failed"


def test_existing_verified_source_receipt_skips_new_upload(runtime, monkeypatch):
    repo, root = runtime
    atomic_write_json(root / "receipts" / (DIGEST + ".json"), receipt())
    monkeypatch.setattr(archive, "run_process_group", lambda *a, **kw: pytest.fail("duplicate upload"))
    assert archive.run_once(repo, day=DAY)["status"] == "already_archived"
    assert not (root / "attempts").exists()


def test_dry_run_creates_no_state(runtime, monkeypatch):
    repo, root = runtime
    monkeypatch.setattr(archive, "run_process_group", lambda *a, **kw: pytest.fail("dry-run uploaded"))
    assert archive.run_once(repo, day=DAY, dry_run=True)["status"] == "dry_run"
    assert not root.exists()


def test_latest_first_and_failed_source_does_not_starve_backlog(runtime, monkeypatch):
    repo, root = runtime
    for day in ("2026-10-28", DAY):
        (repo / "state" / "export-contracts-v2" / day).mkdir(parents=True)
    monkeypatch.setattr(archive, "selected_source", lambda _, day: (
        {"contract_digest": DIGEST if day == DAY else "b" * 64}, repo))
    assert archive.run_once(repo, dry_run=True)["day"] == DAY
    archive._reserve(root, DAY, DIGEST, datetime.now(timezone.utc))
    assert archive.run_once(repo, dry_run=True)["day"] == "2026-10-28"


@pytest.mark.parametrize("guard", ["window_reason", "ingest_clearance"])
def test_guard_refusal_has_no_archive_writes(runtime, monkeypatch, guard):
    repo, root = runtime
    monkeypatch.setattr(archive, guard, lambda *a, **kw: "not_clear")
    assert archive.run_once(repo, day=DAY) == {"status": "deferred", "reason": "not_clear"}
    assert not root.exists()


@pytest.mark.parametrize("hour,minute,expected", [(3, 29, "protected_natural_ingest_window"),
    (3, 30, ""), (21, 29, ""), (21, 30, "insufficient_publication_window"),
    (22, 0, "protected_natural_ingest_window")])
def test_window_reserves_full_child_and_cleanup_budget(hour, minute, expected):
    assert archive.window_reason(datetime(2026, 10, 30, hour, minute, tzinfo=archive.HOBART)) == expected


def test_systemd_failure_is_not_idle(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "data_state_root", lambda _: tmp_path)
    monkeypatch.setattr(archive.subprocess, "run", Mock(side_effect=FileNotFoundError()))
    assert archive.ingest_clearance(tmp_path, NOW) == "ingest_terminal_state_unavailable"


def test_native_lease_is_never_reclaimed_by_admission(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "data_state_root", lambda _: tmp_path)
    (tmp_path / "daily-ingest.lock").write_text("unknown owner")
    assert archive.ingest_clearance(tmp_path, NOW) == "natural_ingest_lease_present"
    assert (tmp_path / "daily-ingest.lock").read_text() == "unknown owner"


@pytest.mark.parametrize("member", ["1234", ""])
def test_cgroup_survivors_block_even_with_zero_main_pid(tmp_path, monkeypatch, member):
    monkeypatch.setattr(archive, "data_state_root", lambda _: tmp_path / "state")
    monkeypatch.setattr(archive.time, "monotonic", lambda: 10000)
    output = "\n".join(["LoadState=loaded", "ActiveState=inactive", "MainPID=0", "ControlPID=0",
        "ControlGroup=", "ExecMainStartTimestampMonotonic=5000000000",
        "ExecMainExitTimestampMonotonic=6000000000", "InactiveEnterTimestampMonotonic=7000000000"])
    monkeypatch.setattr(archive.subprocess, "run", Mock(return_value=SimpleNamespace(stdout=output)))
    group = tmp_path / "cgroups" / "system.slice" / archive.UNITS[0]
    group.mkdir(parents=True)
    (group / "cgroup.procs").write_text(member)
    expected = "ingest_cgroup_not_clear" if member else ""
    assert archive.ingest_clearance(tmp_path, NOW, cgroup_root=tmp_path / "cgroups") == expected


def test_source_digest_is_rechecked_under_native_lease(runtime, monkeypatch):
    repo, root = runtime
    monkeypatch.setattr(archive, "selected_source", lambda *a: ({"contract_digest": "b" * 64}, repo))
    with pytest.raises(ValueError, match="changed after admission"):
        archive.archive_worker(repo, DAY, DIGEST)
    assert not (repo / "state" / "daily-ingest.lock").exists()
    assert not root.exists()


def test_unverified_source_artifacts_never_reach_uploader(runtime, monkeypatch):
    repo, root = runtime
    contract = {"contract_digest": DIGEST, "generation_id": "control-plane-test",
                "observation_state": "partial", "completion_marker_path": "marker.json"}
    monkeypatch.setattr(archive, "selected_source", lambda *a: (contract, repo))
    marker = repo / "state" / "marker.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({"export_contract_digest": DIGEST,
        "generation_id": contract["generation_id"], "observation_state": "partial",
        "export_contract_path": "marker.json"}))
    monkeypatch.setattr(archive, "load_contract", lambda _: contract)
    verifier = Mock(return_value=False)
    monkeypatch.setattr(archive, "verify_completion_marker", verifier)
    with pytest.raises(ValueError, match="artifact verification failed"):
        archive.archive_worker(repo, DAY, DIGEST)
    assert verifier.call_count == 1
    assert not root.exists()


def test_templates_preserve_queue_bounds_and_existing_credentials():
    root = Path(__file__).resolve().parents[1]
    service = (root / "deploy/pi/ar-local-payload-daily-archive.service").read_text()
    assert "EnvironmentFile=/etc/ar-local/app-payload.env" in service
    assert "--resource ar-local" in service and "--max-runtime 1800" in service
    assert "Type=notify" in service and "RuntimeMaxSec=1800s" in service
    assert "TimeoutStopSec=45s" in service and "KillMode=control-group" in service
    assert "pi_payload_daily_archive.py --once" in service
    assert "--once --since {{AR_LOCAL_ARCHIVE_START_DATE}}" in service
    assert "pi_daily_watchdog.py" not in service and "pi_daily_sync.py" not in service


def test_since_excludes_older_sources_and_restart_catches_remaining_dates(runtime, monkeypatch):
    repo, root = runtime
    days = ["2026-10-27", "2026-10-28", DAY, "2026-10-30"]
    for day in days:
        (repo / "state" / "export-contracts-v2" / day).mkdir(parents=True)
    inspected = []
    def source(_, day):
        inspected.append(day)
        assert day >= DAY, "pre-boundary source must not be opened"
        return {"contract_digest": DIGEST if day == DAY else "b" * 64}, repo
    monkeypatch.setattr(archive, "selected_source", source)
    assert archive.run_once(repo, since=DAY, dry_run=True)["day"] == "2026-10-30"
    atomic_write_json(root / "receipts" / ("b" * 64 + ".json"),
                      receipt("2026-10-30", "b" * 64))
    # A fresh invocation derives backlog from retained source plus durable receipts.
    assert archive.run_once(repo, since=DAY, dry_run=True)["day"] == DAY
    atomic_write_json(root / "receipts" / (DIGEST + ".json"), receipt())
    assert archive.run_once(repo, since=DAY, dry_run=True)["status"] == "up_to_date"
    assert set(inspected) == {DAY, "2026-10-30"}


@pytest.mark.parametrize("since", ["2026-1-2", "2026-02-30", "../2026-10-29", ""])
def test_invalid_since_is_rejected_without_writes(runtime, since):
    repo, root = runtime
    with pytest.raises(ValueError):
        archive.run_once(repo, since=since)
    assert not root.exists()


def test_since_cannot_be_combined_with_explicit_date(runtime):
    repo, root = runtime
    with pytest.raises(ValueError, match="only to --once"):
        archive.run_once(repo, day=DAY, since=DAY)
    with pytest.raises(SystemExit) as stopped:
        archive.main(["--date", DAY, "--since", DAY])
    assert stopped.value.code == 2
    assert not root.exists()


def test_termination_handlers_restore_and_allow_owned_cleanup():
    previous = {number: signal.getsignal(number) for number in (signal.SIGTERM, signal.SIGINT)}
    cleaned = []
    with pytest.raises(archive.ArchiveInterrupted):
        with archive.archive_signals():
            try:
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            finally:
                cleaned.append(True)
                assert signal.getsignal(signal.SIGTERM) == signal.SIG_IGN
    assert cleaned == [True]
    assert {number: signal.getsignal(number) for number in previous} == previous


def _signal_worker(tmp_path):
    script = tmp_path / "signal_worker.py"
    script.write_text("\n".join([
        "import sys, time", "from pathlib import Path",
        f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})",
        "from pi_payload_daily_archive import archive_signals, ArchiveInterrupted",
        "from ar_local_operation_lock import production_lock",
        f"root = Path({str(tmp_path)!r})", "try:",
        "    with archive_signals():",
        "        with production_lock(root / 'daily-ingest.lock', 'daily-payload-archive'):",
        "            (root / 'ready').write_text('ready')",
        "            time.sleep(60)", "except ArchiveInterrupted:",
        "    (root / 'cleaned').write_text('cleaned')", "    sys.exit(2)",
    ]))
    return script


def _wait_ready(process, path):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and process.poll() is None:
        if path.exists():
            return
        time.sleep(0.02)
    raise AssertionError("signal canary did not acquire its test lock")


@pytest.mark.skipif(os.name != "posix", reason="requires actual POSIX process-group signals")
def test_actual_timeout_unwinds_worker_lock(tmp_path, monkeypatch):
    import pi_process_group as groups
    script = _signal_worker(tmp_path)
    original = subprocess.Popen
    children = []
    def start(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        _wait_ready(child, tmp_path / "ready")
        return child
    monkeypatch.setattr(groups.subprocess, "Popen", start)
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            groups.run_process_group([sys.executable, str(script)], cwd=tmp_path,
                timeout_seconds=0.1, terminate_grace_seconds=3, kill_wait_seconds=2)
        assert (tmp_path / "cleaned").exists()
        assert not (tmp_path / "daily-ingest.lock").exists()
        assert children[0].poll() == 2
    finally:
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=5)


@pytest.mark.skipif(os.name != "posix", reason="requires actual POSIX process-group signals")
def test_actual_parent_sigterm_reaps_worker_and_releases_lock(tmp_path):
    worker = _signal_worker(tmp_path)
    parent_script = tmp_path / "signal_parent.py"
    parent_script.write_text("\n".join([
        "import sys", "from pathlib import Path",
        f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})",
        "import pi_payload_daily_archive as archive",
        "def launch(*args, **kwargs):",
        f"    archive.run_process_group([sys.executable, {str(worker)!r}], cwd=Path({str(tmp_path)!r}), timeout_seconds=60)",
        "archive.run_once = launch", "sys.exit(archive.main(['--once']))",
    ]))
    parent = subprocess.Popen([sys.executable, str(parent_script)], cwd=tmp_path,
                              start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        _wait_ready(parent, tmp_path / "ready")
        os.kill(parent.pid, signal.SIGTERM)
        output, errors = parent.communicate(timeout=10)
        assert parent.returncode == 1, (output, errors)
        assert b"ArchiveInterrupted" in output
        assert (tmp_path / "cleaned").exists()
        assert not (tmp_path / "daily-ingest.lock").exists()
    finally:
        if parent.poll() is None:
            os.killpg(parent.pid, signal.SIGKILL)
            parent.wait(timeout=5)
