from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import pi_cdr_recovery as recovery
import pi_cdr_recovery_probe as probe
import pi_daily_sync
import pi_daily_watchdog as watchdog
from cdr_recovery_queue import add_recovery_requests
import cdr_recovery_queue

NOW = datetime(2026, 9, 7, 10, tzinfo=recovery.HOBART).astimezone(timezone.utc)
DATE = "2026-09-07"
PROVIDER = {"brand_name": "Provider", "legal_entity_name": "Provider Ltd",
            "provider_uid": "provider-1", "provider_dir": "Provider",
            "endpoint_url": "https://bank.example/cds-au/v1/banking/products",
            "state": "partial", "failure_records": 1}


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


def stage(monkeypatch, tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    observation = {
        "contract": {"generation_id": "g1", "observation_date": DATE, "observation_state": "partial"},
        "event": {"event_digest": "e1"},
        "status": {"total": 1, "failure_provenance_complete": True, "by_provider": {"Provider": 1},
                   "provider_states": [dict(PROVIDER)], "unresolved_requests_complete": True,
                   "unresolved_requests": [{"provider_dir": "Provider", "product_id": "p1",
                      "phase": "product_detail", "url": PROVIDER["endpoint_url"] + "/p1", "status": 404}]},
    }
    monkeypatch.setattr(recovery, "datetime", FixedDatetime)
    monkeypatch.setattr(recovery, "data_state_root", lambda _: state)
    monkeypatch.setattr(recovery, "recovery_block_reason", lambda *a, **k: "")
    monkeypatch.setattr(recovery, "selected_observation", lambda *a: observation)
    monkeypatch.setattr(recovery, "probe_register", lambda **k: ({"ok": True, "body_sha256": "a" * 64}, [dict(PROVIDER)]))
    return state, observation


@pytest.mark.parametrize("hour,minute,allowed", [(0, 29, False), (0, 30, False), (1, 0, False),
    (3, 29, False), (3, 30, True), (21, 59, True), (22, 0, False), (23, 59, False)])
def test_recovery_window_uses_hobart_not_host_timezone(hour, minute, allowed):
    local = datetime(2026, 9, 7, hour, minute, tzinfo=recovery.HOBART)
    assert recovery.recovery_window(local.astimezone(timezone.utc)) is allowed


def test_capture_deadline_reserves_cleanup_before_quiet_hours():
    assert recovery.capture_timeout(NOW) == 1800
    late = datetime(2026, 9, 7, 21, 58, tzinfo=recovery.HOBART)
    assert recovery.capture_timeout(late) == 75
    assert recovery.capture_timeout(late + timedelta(minutes=1)) == 15


@pytest.mark.parametrize("status", [403, 404, 406, 429, 500, "invalid_response", "circuit_open"])
def test_every_failure_category_remains_eligible_for_later_probe(tmp_path, status):
    requests = [{"provider_dir": "Provider", "phase": "product_detail", "product_id": "p1",
                 "request_key": "r1", "url": "https://bank.example/p1", "status": status}]
    reserved = recovery._reserve(tmp_path, DATE, "g1", "probe", NOW,
                                  provider_dir="Provider", request_key="r1")
    history = recovery._history(tmp_path, DATE)  # No result file: simulate interruption.
    assert history == [reserved]
    assert recovery._due_requests(requests, history, NOW + timedelta(minutes=5)) == []
    assert recovery._due_requests(requests, history, NOW + timedelta(minutes=16))[0]["product_id"] == "p1"


def test_round_robin_missing_ids_and_compatibility_versions(tmp_path):
    requests = [{"provider_dir": "Provider", "request_key": key, "product_id": key}
                for key in ("a", "b")]
    history = [recovery._reserve(tmp_path, DATE, "g1", "probe", NOW,
                                provider_dir="Provider", request_key="a")]
    due = recovery._due_requests(requests, history, NOW + timedelta(minutes=16))
    assert due[0]["product_id"] == "b"
    assert due[0]["version_offset"] == 2


def test_failed_probe_never_builds_a_revision(monkeypatch, tmp_path):
    state, _ = stage(monkeypatch, tmp_path)
    monkeypatch.setattr(recovery, "probe_request", lambda *a, **k: {"ok": False, "attempts": [{"status": 500}]})
    launch = Mock()
    result = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=launch)
    assert result["status"] == "upstream_gaps_remain"
    assert result["failure_records"] == 1
    launch.assert_not_called()
    assert json.loads((state / "cdr-recovery-status.json").read_text())["provider_failures"] == {"Provider": 1}


def test_success_reserves_revision_before_launch_and_preserves_failed_attempt(monkeypatch, tmp_path):
    state, _ = stage(monkeypatch, tmp_path)
    monkeypatch.setattr(recovery, "probe_request", lambda *a, **k: {"ok": True, "body_sha256": "b" * 64, "data": {"private": "not persisted"}})
    def launch(day, timeout, generation):
        assert (day, timeout, generation) == (DATE, 1800, "g1")
        history = recovery._history(state / "cdr-recovery-v1" / DATE, DATE)
        assert sum(row["kind"] == "capture" for row in history) == 1
        raise subprocess.TimeoutExpired("capture", timeout)
    result = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=launch)
    assert result["status"] == "capture_failed"
    assert result["selected_generation_id"] == "g1"
    assert result["selection_advanced"] is False
    assert "not persisted" not in json.dumps(result)
    blocked = recovery.run_same_day_recovery(tmp_path, now_utc=NOW + timedelta(minutes=2),
                                             dry_run=False, launch=Mock(side_effect=AssertionError))
    assert blocked["status"] == "register_probe_cooldown"


def test_dry_run_writes_nothing_and_never_probes(monkeypatch, tmp_path):
    monkeypatch.setattr(recovery, "recovery_block_reason", Mock(side_effect=AssertionError))
    result = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=True, launch=Mock())
    assert result["status"] == "dry_run"
    assert list(tmp_path.iterdir()) == []


def test_daily_capture_and_unchanged_proof_budgets():
    proof = {"request_key": "r", "body_sha256": "b" * 64}
    old = {"kind": "capture", "reserved_at": NOW.isoformat(), "proofs": [proof]}
    assert recovery._capture_allowed([old], [proof], NOW + timedelta(minutes=61)) == (False, "unchanged_successful_probe_cooldown")
    assert recovery._capture_allowed([old], [dict(proof, body_sha256="c" * 64)], NOW + timedelta(minutes=61)) == (True, "")
    assert recovery._capture_allowed([old] * 4, [proof], NOW + timedelta(hours=4)) == (False, "daily_capture_budget_exhausted")


def test_dead_pid_lock_does_not_disable_all_later_recovery(monkeypatch, tmp_path):
    path = tmp_path / "daily-ingest.lock"
    path.write_text("pid=987654321\n")
    monkeypatch.setattr(recovery.os, "kill", Mock(side_effect=ProcessLookupError))
    assert recovery._lock_owner_may_be_active(path) is False
    assert path.read_text() == "pid=987654321\n"  # Outer preflight never reclaims.
    path.write_text("unknown owner\n")
    assert recovery._lock_owner_may_be_active(path) is True


def test_guarded_restore_rechecks_foreign_activity_inside_shared_lock(monkeypatch, tmp_path):
    monkeypatch.setattr(recovery, "datetime", FixedDatetime)
    monkeypatch.setattr(recovery, "data_state_root", lambda _: tmp_path)
    monkeypatch.setattr(recovery, "recovery_block_reason", Mock(side_effect=["", "backup_source_active"]))
    entered = []
    class Lock:
        def __init__(self, path):
            self.path = path
        def __enter__(self):
            entered.append(self.path)
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(pi_daily_sync, "DailyIngestLock", Lock)
    command = Mock()
    monkeypatch.setattr(recovery.subprocess, "run", command)
    assert recovery.restore_dashboard_if_idle(tmp_path)["reason"] == "backup_source_active"
    assert entered == [tmp_path / "daily-ingest.lock"]
    command.assert_not_called()


@pytest.mark.parametrize("returncode", [0, 75, 1])
def test_success_or_rejected_child_does_not_restart_another_ingests_dashboard(monkeypatch, returncode):
    result = Mock(side_effect=None if returncode == 0 else subprocess.CalledProcessError(returncode, "capture"))
    monkeypatch.setattr(watchdog, "run_ingest_process_group", result)
    restore = Mock()
    monkeypatch.setattr(watchdog, "restore_dashboard_if_idle", restore)
    if returncode:
        with pytest.raises(subprocess.CalledProcessError):
            watchdog.run_recovery_ingest(DATE, 120, "g1")
    else:
        watchdog.run_recovery_ingest(DATE, 120, "g1")
    restore.assert_not_called()
    assert result.call_args.kwargs["env"][recovery.EXPECTED_GENERATION_ENV] == "g1"


def test_child_timeout_restores_only_through_guarded_helper(monkeypatch):
    monkeypatch.setattr(watchdog, "run_ingest_process_group", Mock(side_effect=subprocess.TimeoutExpired("capture", 120)))
    restore = Mock(return_value={"status": "deferred", "reason": "foreign_ingest"})
    monkeypatch.setattr(watchdog, "restore_dashboard_if_idle", restore)
    with pytest.raises(subprocess.TimeoutExpired):
        watchdog.run_recovery_ingest(DATE, 120, "g1")
    restore.assert_called_once_with(watchdog.REPO_ROOT)


def test_queue_survives_reconciliation_without_bank_work(tmp_path):
    status = {"provider_states": [dict(PROVIDER)]}
    (tmp_path / "failures.jsonl").write_text(json.dumps({"bank": "Provider", "phase": "product_detail", "product_id": "p1", "status": 404}) + "\n")
    add_recovery_requests(status, tmp_path, [])
    assert status["unresolved_requests_complete"] is True
    assert status["unresolved_requests"][0]["product_id"] == "p1"
    assert status["unresolved_requests"][0]["provider_uid"] == "provider-1"


def test_bounded_queue_keeps_every_provider_eligible(monkeypatch, tmp_path):
    monkeypatch.setattr(cdr_recovery_queue, "MAX_RECOVERY_REQUESTS", 4)
    providers = [dict(PROVIDER, provider_dir=name, brand_name=name, provider_uid=name) for name in ("A", "B", "C")]
    rows = [{"bank": "A", "phase": "product_detail", "product_id": f"a{i}", "status": 404} for i in range(5)]
    rows += [{"bank": name, "phase": "products_index", "status": 503} for name in ("B", "C")]
    (tmp_path / "failures.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
    status = {"provider_states": providers}
    add_recovery_requests(status, tmp_path, [(row, row["provider_dir"]) for row in providers])
    assert {row["provider_dir"] for row in status["unresolved_requests"]} == {"A", "B", "C"}
    assert len(status["unresolved_requests"]) == 4
    assert status["unresolved_requests_complete"] is False


def test_probe_negotiates_advertised_version_with_small_budget(monkeypatch):
    calls = []
    def fetch(url, headers, **kwargs):
        calls.append((headers, kwargs))
        if len(calls) == 1:
            return SimpleNamespace(status=406, body=b'{"errors":[{"code":"urn:au-cds:error:cds-all:Header/UnsupportedVersion","detail":"Supported versions: 8"}]}')
        return SimpleNamespace(status=200, body=b'{"data":{"productId":"p1","depositRates":[{"rate":"0.04"}]}}')
    monkeypatch.setattr(probe, "request_https", fetch)
    result = probe.probe_request("https://bank.example/products/p1", phase="product_detail", product_id="p1", deadline=probe.time.monotonic() + 60)
    assert result["ok"] is True
    assert len(calls) == 2
    assert calls[1][0]["x-v"] == "8"
    assert calls[0][1]["policy"].max_body_bytes == 2 * 1024 * 1024
    assert result["complete_capture"] is False


@pytest.mark.parametrize("body", [b'{"data":{"productId":"wrong"}}', b'{"errors":[{"code":"bad"}]}', b'null'])
def test_probe_never_accepts_wrong_identity_or_error_envelope(monkeypatch, body):
    monkeypatch.setattr(probe, "request_https", lambda *a, **k: SimpleNamespace(status=200, body=body))
    assert probe.probe_request("https://bank.example/products/p1", phase="product_detail", product_id="p1", deadline=probe.time.monotonic() + 60)["ok"] is False


def test_fresh_register_endpoint_change_preserves_failed_page_and_identity():
    fresh = dict(PROVIDER, endpoint_url="https://new-bank.example/products")
    request = {"phase": "products_index", "url": PROVIDER["endpoint_url"] + "?page=2"}
    assert probe.current_target_url(request, PROVIDER, [fresh]) == "https://new-bank.example/products?page=2"
    with pytest.raises(ValueError, match="ambiguous"):
        probe.current_target_url(request, PROVIDER, [fresh, fresh])
