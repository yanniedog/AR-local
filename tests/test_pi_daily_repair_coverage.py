"""One daily repair must disclose and reach beyond a frequent tick's batch."""
from unittest.mock import Mock

import pytest

import pi_cdr_recovery as recovery
from pi_daily_repair_work import repair
from tests.test_pi_same_day_recovery import DATE, NOW, PROVIDER, stage


@pytest.mark.parametrize("daily_pass,expected", [(False, 4), (True, 8)])
def test_single_pass_reaches_recoverable_eighth_provider(monkeypatch, tmp_path, daily_pass, expected):
    state, observation = stage(monkeypatch, tmp_path)
    providers = [dict(PROVIDER, provider_dir=f"Bank {n}", brand_name=f"Bank {n}",
                      provider_uid=f"bank-{n}") for n in range(8)]
    observation["status"].update(
        provider_states=providers, by_provider={p["provider_dir"]: 1 for p in providers}, total=8,
        unresolved_requests=[dict(provider_dir=p["provider_dir"], product_id="p1",
                                 phase="product_detail", url=p["endpoint_url"] + "/p1", status=500)
                             for p in providers])
    monkeypatch.setattr(recovery, "probe_register", lambda **k: ({"ok": True}, providers))
    monkeypatch.setattr(recovery, "current_target_url", lambda req, *a: req["provider_dir"])
    seen = []
    def probe(url, **kwargs):
        seen.append(url)
        return {"ok": url == "Bank 7", "body_sha256": "a" * 64,
                "attempts": [{"status": 200 if url == "Bank 7" else 500}]}
    monkeypatch.setattr(recovery, "probe_request", probe)
    launch = Mock()
    result = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False,
                                           launch=launch, daily_pass=daily_pass)
    assert len(seen) == expected
    assert result["providers_probed"] == expected
    assert result["provider_probe_coverage_complete"] is daily_pass
    assert result["providers_not_probed"] == ([] if daily_pass else [f"Bank {n}" for n in range(4, 8)])
    assert launch.call_count == int(daily_pass)
    if daily_pass:
        assert result["failure_records"] == 8  # A probe alone never repairs capture.
        assert result["selection_advanced"] is False
    reservations = recovery._history(state / "cdr-recovery-v1" / DATE, DATE)
    assert sum(row["kind"] == "capture" for row in reservations) == int(daily_pass)


def test_daily_owner_selects_single_bounded_daily_pass():
    w, r = Mock(), Mock()
    r.recovery_block_reason.return_value = ""
    w.read_payload_publication_pending.return_value = None
    repair(w, r, DATE, NOW)
    r.run_same_day_recovery.assert_called_once_with(w.REPO_ROOT, now_utc=NOW,
        dry_run=False, launch=w.run_recovery_ingest, daily_pass=True, execution_deadline=None)


@pytest.mark.parametrize("failure", ["missing_identity", "deadline"])
def test_unattempted_provider_is_not_reported_as_probed(monkeypatch, tmp_path, failure):
    stage(monkeypatch, tmp_path)
    monkeypatch.setattr(recovery, "probe_register", lambda **k: ({"ok": True}, [PROVIDER]))
    if failure == "missing_identity":
        def reject(*args):
            raise ValueError("fresh register provider identity is missing or ambiguous")
        monkeypatch.setattr(recovery, "current_target_url", reject)
    else:
        monkeypatch.setattr(recovery, "current_target_url", lambda *a: PROVIDER["endpoint_url"])
        monkeypatch.setattr(recovery, "probe_request", lambda *a, **k: {"ok": False, "attempts": []})
    launch = Mock()
    result = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False,
                                           launch=launch, daily_pass=True)
    assert result["providers_probed"] == 0
    assert result["providers_not_probed"] == [PROVIDER["provider_dir"]]
    assert result["provider_probe_coverage_complete"] is False
    launch.assert_not_called()


def test_daily_provider_batch_stays_bounded_and_preserves_cooldown():
    requests = [{"provider_dir": f"Bank {n:02}", "request_key": str(n)} for n in range(100)]
    history = [{"kind": "probe", "provider_dir": "Bank 00", "request_key": "0", "reserved_at": NOW.isoformat()}]
    due = recovery._due_requests(requests, history, NOW, probe_limit=recovery.DAILY_PROBE_LIMIT)
    assert len(due) == 32 and all(row["provider_dir"] != "Bank 00" for row in due)


def test_daily_rotation_reaches_later_providers_with_new_empty_day_history():
    requests = [{"provider_dir": f"Bank {n:02}", "request_key": str(n)} for n in range(64)]
    first = recovery._due_requests(requests, [], NOW, probe_limit=32, rotation=32 * 123)
    second = recovery._due_requests(requests, [], NOW, probe_limit=32, rotation=32 * 124)
    assert len(first) == len(second) == 32
    assert {r["provider_dir"] for r in first + second} == {r["provider_dir"] for r in requests}


@pytest.mark.parametrize("remaining,expected_probe", [(1100, 155), (1060, 115)])
def test_probe_and_capture_share_service_deadline(monkeypatch, tmp_path, remaining, expected_probe):
    stage(monkeypatch, tmp_path)
    clock = [0.0]
    monkeypatch.setattr(recovery.time, "monotonic", lambda: clock[0])
    def probes(*args, probe_budget_seconds):
        assert probe_budget_seconds == expected_probe
        clock[0] += probe_budget_seconds
        proof = {"request_key": "p1", "body_sha256": "a" * 64}
        return [proof], [{"provider_dir": PROVIDER["provider_dir"], "attempts": [{"status": 200}]}]
    monkeypatch.setattr(recovery, "_probe_due", probes)
    launch = Mock()
    result = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False,
        launch=launch, daily_pass=True, execution_deadline=remaining)
    launch.assert_called_once_with(DATE, 900, "g1")
    assert clock[0] + launch.call_args.args[1] + recovery.CLEANUP_SECONDS == remaining
    assert result["capture_attempted"] is True


def test_short_service_budget_does_not_spend_capture_reservation(monkeypatch, tmp_path):
    state, _ = stage(monkeypatch, tmp_path)
    monkeypatch.setattr(recovery.time, "monotonic", lambda: 200)
    probe = Mock()
    monkeypatch.setattr(recovery, "_probe_due", probe)
    launch = Mock()
    result = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False,
        launch=launch, daily_pass=True, execution_deadline=1100)
    assert result["status"] == "insufficient_service_budget"
    probe.assert_not_called()
    launch.assert_not_called()
    assert recovery._history(state / "cdr-recovery-v1" / DATE, DATE) == []


def test_worker_uses_original_service_start_including_queue_delay(monkeypatch):
    import pi_daily_repair_work as work
    run = Mock(return_value=Mock(stdout="123000000\n"))
    monkeypatch.setattr(work.subprocess, "run", run)
    assert work.service_deadline() == 1223
    assert "--property=ExecMainStartTimestampMonotonic" in run.call_args.args[0]
