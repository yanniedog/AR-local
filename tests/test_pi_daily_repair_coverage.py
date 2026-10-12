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
        dry_run=False, launch=w.run_recovery_ingest, daily_pass=True)


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
