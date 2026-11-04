"""Operational state fixtures only; no provider data or live notification tests."""
from datetime import datetime, timedelta, timezone
import json
import subprocess

import pytest

from scripts import ingest_notification_snapshot as snapshot


NOW = datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc)
DAY, DUE = snapshot._schedule(NOW)


def pi_state(status="COMPLETE", now=NOW):
    return {"available": True, "value": {
        "schema_version": 1, "read_only": True, "checked_at": now.isoformat(),
        "units": [{"unit": unit, "ActiveState": "inactive", "Result": "success",
                   "ExecMainStatus": "0", "started_at": DUE.isoformat()} for unit in snapshot.UNITS],
        "ingest": {"status": status, "date": DAY}, "health_facets": [],
        "recovery": {"available": False}, "publication_pending": {"exists": False, "dates": []},
    }}


def public(current=True):
    return {"available": True, "value": {
        "publication_current": current, "manifest_run_date": DAY,
        "dates_index_latest_date": DAY, "verification_scope": "public_ciphertext_receipt"}}


def test_complete_and_public_current_is_healthy():
    result = snapshot.summarize(NOW, pi_state(), public())
    assert result["status"] == "HEALTHY"
    assert result["incident_key"] == "AR-INGEST-2026-10-11"
    assert not result["notification_required"]


@pytest.mark.parametrize("status", ["PARTIAL", "MISSING", "INVALID", "STUCK", "UNVERIFIED_METADATA_LIMIT"])
def test_current_publication_cannot_hide_ingest_failure(status):
    result = snapshot.summarize(NOW, pi_state(status), public())
    assert result["status"] == "FAILURE"
    assert "ingest_" + status.lower() in result["failing_facets"]


def test_running_does_not_hide_failed_daily_attempt():
    pi = pi_state("RUNNING")
    pi["value"]["units"][0].update(ActiveState="failed", Result="exit-code", ExecMainStatus="1")
    pi["value"]["units"][1].update(ActiveState="active")
    assert snapshot.summarize(NOW, pi, public())["failing_facets"] == ["same_day_unit_failed:" + snapshot.UNITS[0]]
    pi["value"]["units"][0].update(ActiveState="inactive", Result="success", ExecMainStatus="0")
    assert snapshot.summarize(NOW, pi, public())["status"] == "RUNNING"


def test_prior_day_failure_not_assigned_to_today_but_missed_start_is():
    pi = pi_state()
    pi["value"]["units"][0].update(ActiveState="failed", Result="exit-code",
                                  started_at=(DUE - timedelta(days=1)).isoformat())
    result = snapshot.summarize(NOW, pi, public())
    assert result["failing_facets"] == ["scheduled_ingest_not_started"]
    assert result["recovered_after_failure"] and not result["ongoing_failure"]


def test_retained_failure_is_still_notifiable_after_verified_recovery():
    pi = pi_state()
    pi["value"]["units"][0].update(ActiveState="failed", Result="exit-code", ExecMainStatus="1")
    result = snapshot.summarize(NOW, pi, public())
    assert result["status"] == "RECOVERED_AFTER_FAILURE"
    assert result["notification_required"]
    assert result["terminal_capture_complete"]
    assert result["recovered_after_failure"] and not result["ongoing_failure"]
    assert result["failing_facets"] == result["recovered_facets"] == ["same_day_unit_failed:" + snapshot.UNITS[0]]


def test_full_capture_without_current_publication_does_not_resolve_failure():
    pi = pi_state()
    pi["value"]["units"][0].update(ActiveState="failed", Result="exit-code", ExecMainStatus="1")
    result = snapshot.summarize(NOW, pi, public(False))
    assert result["status"] == "FAILURE"
    assert result["ongoing_failure"] and not result["recovered_after_failure"]
    assert result["terminal_capture_complete"]


@pytest.mark.parametrize("minutes, expected_status", [(-20, "GRACE"), (29, "GRACE"), (30, "FAILURE")])
def test_current_calendar_day_start_grace(minutes, expected_status):
    now = DUE + timedelta(minutes=minutes)
    pi = pi_state("MISSING", now)
    pi["value"]["units"][0]["started_at"] = (DUE - timedelta(days=1)).isoformat()
    result = snapshot.summarize(now, pi, public(False))
    assert result["run_date"] == DAY
    assert result["status"] == expected_status


@pytest.mark.parametrize("minutes, fails", [(89, False), (90, True)])
def test_publication_grace(minutes, fails):
    now = DUE + timedelta(minutes=minutes)
    result = snapshot.summarize(now, pi_state(now=now), public(False))
    assert ("publication_unavailable_or_inconsistent" in result["failing_facets"]) is fails


def test_unreachable_pi_is_unverified_even_with_current_publication():
    result = snapshot.summarize(NOW, {"available": False, "error": "worker_timeout"}, public())
    assert result["status"] == "MONITORING_UNVERIFIED"
    assert result["notification_required"]
    assert result["unknown"] == ["pi_monitoring_unverified"]
    assert "router" not in " ".join(result["unknown"])


def test_stale_or_malformed_remote_snapshot_cannot_report_healthy():
    for mutate in [lambda v: v.update(checked_at=(NOW - timedelta(minutes=3)).isoformat()),
                   lambda v: v.update(units=[]), lambda v: v.update(read_only=False)]:
        pi = pi_state()
        mutate(pi["value"])
        assert snapshot.summarize(NOW, pi, public())["status"] == "MONITORING_UNVERIFIED"


def test_failed_unit_without_start_identity_is_unverified():
    pi = pi_state()
    pi["value"]["units"][0].update(ActiveState="failed", Result="exit-code", started_at=None)
    result = snapshot.summarize(NOW, pi, public())
    assert "unit_state_unverified:" + snapshot.UNITS[0] in result["unknown"]


def test_worker_failure_never_exposes_subprocess_diagnostics(monkeypatch):
    monkeypatch.setattr(snapshot.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "secret", "secret"))
    assert snapshot._worker(["unused"]) == {"available": False, "error": "worker_failed"}


def test_ssh_is_fixed_readonly_stdin_and_bounded(monkeypatch):
    captured = {}
    def run(command, **kwargs):
        captured.update(command=command, **kwargs)
        return subprocess.CompletedProcess(command, 0, "{}", "")
    monkeypatch.setattr(snapshot.subprocess, "run", run)
    snapshot.collect_pi()
    assert captured["command"][-2:] == ["ar-local-pi5", "python3 -B -"]
    assert "BatchMode=yes" in captured["command"] and "ConnectTimeout=10" in captured["command"]
    assert captured["timeout"] <= 35 and captured["shell"] is False
    source = captured["input"]
    compile(source, "remote-read-only", "exec")
    assert "ingest_checks(Observer()" in source
    assert "signal.alarm(25)" in source
    assert not any(text in source for text in ["configured_store(", "deliver(", "watch.main(", "probe(", "sqlite", "notify.env"])


def test_recovery_summary_excludes_provider_and_secret_fields():
    class Watch:
        @staticmethod
        def read_json(*args, **kwargs):
            assert kwargs == {"maximum": 65536}
            return {"run_date": DAY, "checked_at": NOW.isoformat(), "selected_generation_id": "obs-2026-10-11-abcd",
                    "failure_records": 18, "provider_failures": {"private": 18}, "secret": "never-output"}
    value = snapshot._remote_recovery(Watch, None)
    assert value["failure_records"] == 18
    assert "private" not in json.dumps(value) and "never-output" not in json.dumps(value)


def test_hobart_dst_schedule():
    winter = datetime(2026, 6, 26, 9, tzinfo=timezone.utc)
    assert snapshot._schedule(winter) == ("2026-06-26", datetime(2026, 6, 25, 15, tzinfo=timezone.utc))
    assert DUE == datetime(2026, 10, 10, 14, tzinfo=timezone.utc)


def test_remote_collects_only_ingest_with_memory_observer(monkeypatch):
    import signal
    import pi_issue_watchdog as watch
    calls = []
    monkeypatch.setattr(signal, "alarm", lambda seconds: calls.append(seconds), raising=False)
    monkeypatch.setattr(watch, "unit_state", lambda name: {
        "ActiveState": "inactive", "Result": "success", "ExecMainStatus": "0", "started_at": DUE,
        "private": "not-returned"})
    def ingest(store, root, now, *, units):
        assert set(units) == set(snapshot.UNITS)
        store.observe("ingest:" + DAY, "private title", "INGEST_PARTIAL", healthy=False)
        return {"status": "PARTIAL", "date": DAY, "private": "not-returned"}
    monkeypatch.setattr(watch, "ingest_checks", ingest)
    monkeypatch.setattr(watch, "read_json", lambda *a, **k: {})
    monkeypatch.setattr(watch, "configured_store", lambda: pytest.fail("spool must not be created"))
    monkeypatch.setattr(watch, "backup_check", lambda *a, **k: pytest.fail("Drive must not be checked"))
    monkeypatch.setattr(watch, "deliver", lambda *a, **k: pytest.fail("notification must not be sent"))
    result = snapshot.remote_snapshot()
    assert calls == [25]
    assert result["health_facets"] == [{"key": "ingest:" + DAY, "category": "INGEST_PARTIAL", "healthy": False}]
    assert "private" not in json.dumps(result) and "not-returned" not in json.dumps(result)


@pytest.mark.parametrize("capture_status", ["PARTIAL", "COMPLETE"])
def test_remote_observer_accepts_real_watchdog_recovery_without_hiding_capture(monkeypatch, capture_status):
    import signal
    import pi_issue_watchdog as watch

    monkeypatch.setattr(signal, "alarm", lambda _: None, raising=False)
    units = {unit: {"ActiveState": "inactive", "Result": "success", "ExecMainStatus": "0",
                    "started_at": DUE, "private": "not-returned"} for unit in snapshot.UNITS}
    units[snapshot.UNITS[2]].update(ExecMainPID="123", started_at=DUE + timedelta(minutes=1),
                                  finished_at=DUE + timedelta(minutes=2))
    monkeypatch.setattr(watch, "unit_state", lambda name: units[name])
    original_checks = watch.ingest_checks

    def fixed_time_checks(store, root, now, *, units):
        return original_checks(store, root, NOW, units=units)

    monkeypatch.setattr(watch, "ingest_checks", fixed_time_checks)
    monkeypatch.setattr(watch, "completion", lambda *_: capture_status)
    monkeypatch.setattr(watch, "read_json", lambda *a, **k: {})
    monkeypatch.setattr(watch, "configured_store", lambda: pytest.fail("spool must not be created"))
    monkeypatch.setattr(watch, "backup_check", lambda *a, **k: pytest.fail("Drive must not be checked"))
    monkeypatch.setattr(watch, "deliver", lambda *a, **k: pytest.fail("notification must not be sent"))

    result = snapshot.remote_snapshot()

    assert result["ingest"] == {"status": capture_status, "date": DAY}
    assert result["health_facets"] == [
        {"key": "ingest-schedule:" + DAY, "category": "SCHEDULED_INGEST_NOT_STARTED", "healthy": True},
        {"key": "ingest-watchdog:" + DAY, "category": "INGEST_WATCHDOG_FAILED", "healthy": True},
        {"key": "ingest:" + DAY, "category": "INGEST_" + capture_status, "healthy": capture_status == "COMPLETE"},
    ]
    serialized = json.dumps(result)
    assert "recovery_started_at" not in serialized and "observation_at" not in serialized
    assert "not-returned" not in serialized


def test_public_timeout_is_not_healthy(monkeypatch):
    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired("unused", 35, output="private")
    monkeypatch.setattr(snapshot.subprocess, "run", run)
    result = snapshot.summarize(NOW, pi_state(), snapshot.collect_public(DAY))
    assert result["status"] == "MONITORING_UNVERIFIED"
    assert result["unknown"] == ["public_monitoring_unverified"]


def pending_summary(value):
    class Watch:
        @staticmethod
        def read_json(*args, **kwargs):
            assert kwargs["maximum"] == 1048576
            return value
    return snapshot._remote_pending(Watch, None)


def test_current_pending_under_historical_head_is_ongoing_despite_current_receipt():
    pi = pi_state()
    pi["value"]["publication_pending"] = pending_summary({
        "run_date": "2026-10-01", "pointer": {"observation_date": "2026-10-01"},
        "queued_pointers": [{"observation_date": DAY, "private": "never-output"}]})
    pi["value"]["units"][0].update(ActiveState="failed", Result="exit-code", ExecMainStatus="1")
    result = snapshot.summarize(NOW, pi, public())
    assert result["terminal_capture_complete"] and result["publication_date_current"]
    assert result["ongoing_failure"] and not result["recovered_after_failure"]
    assert "publication_pending" in result["failing_facets"]
    assert result["exact_selected_generation_publication_verified"] is False
    assert "never-output" not in json.dumps(result)


def test_historical_pending_alone_does_not_alert_for_today():
    pi = pi_state()
    pi["value"]["publication_pending"] = pending_summary({
        "run_date": "2026-10-01", "pointer": {"observation_date": "2026-10-01"},
        "queued_pointers": [{"observation_date": "2026-10-02"}]})
    result = snapshot.summarize(NOW, pi, public())
    assert result["status"] == "HEALTHY" and not result["notification_required"]
    assert result["exact_selected_generation_publication_verified"] is False


@pytest.mark.parametrize("marker", [{}, {"pointer": {"observation_date": "bad"}},
    {"pointer": {"observation_date": DAY}, "queued_pointers": [None]},
    {"pointer": {"observation_date": DAY}, "run_date": "2026-10-01"},
    {"pointer": {"observation_date": DAY}, "queued_pointers": [{}] * 129},
    {"pointer": {"observation_date": DAY}, "selection_retry": {}}])
def test_malformed_pending_is_unverified(marker):
    pi = pi_state()
    pi["value"]["publication_pending"] = pending_summary(marker)
    result = snapshot.summarize(NOW, pi, public())
    assert result["status"] == "MONITORING_UNVERIFIED"
    assert result["unknown"] == ["publication_pending_unverified"]


def test_pending_respects_publication_grace():
    now = DUE + timedelta(minutes=89)
    pi = pi_state(now=now)
    pi["value"]["publication_pending"] = pending_summary({"pointer": {"observation_date": DAY}})
    assert snapshot.summarize(now, pi, public())["status"] == "GRACE"


def count_status():
    return {"total": 4, "failure_provenance_complete": True, "unresolved_requests_complete": True,
            "unresolved_request_sample_count": 4, "by_provider": {"a": 2, "b": 1, "c": 1},
            "unresolved_requests": [
                {"provider_dir": "a", "provider_uid": "pa", "phase": "product_detail", "product_id": "p1"},
                {"provider_dir": "a", "provider_uid": "pa", "phase": "classification_detail", "product_id": "p1"},
                {"provider_dir": "b", "provider_uid": "pb", "phase": "product_detail", "product_id": "p1"},
                {"provider_dir": "c", "provider_uid": "pc", "phase": "products_index", "product_id": ""}]}


def test_count_distinct_provider_product_pairs_and_unknown_index_population():
    assert snapshot._count_failures(count_status()) == {
        "failed_request_records": 4, "known_failed_products": 2, "failed_providers": 3,
        "providers_with_unknown_product_population": 1, "product_count_is_lower_bound": True}


@pytest.mark.parametrize("change", [
    lambda s: s.update(unresolved_requests_complete=False),
    lambda s: s.update(failure_provenance_complete=False),
    lambda s: s.update(unresolved_request_sample_count=3),
    lambda s: s.update(total=6),
    lambda s: s["unresolved_requests"][0].update(product_id=""),
    lambda s: s["unresolved_requests"][1].update(provider_uid="different"),
    lambda s: s["unresolved_requests"][3].update(product_id="unknown-index-product"),
])
def test_unverified_count_is_never_converted_to_zero(change):
    status = count_status()
    change(status)
    with pytest.raises(ValueError):
        snapshot._count_failures(status)


def test_verified_zero_has_explicit_complete_evidence():
    status = {"total": 0, "failure_provenance_complete": True, "unresolved_requests_complete": True,
              "unresolved_request_sample_count": 0, "by_provider": {}, "unresolved_requests": []}
    counts = snapshot._count_failures(status)
    assert counts["known_failed_products"] == 0 and counts["failed_providers"] == 0
    assert counts["product_count_is_lower_bound"] is False


def count_source(tmp_path, monkeypatch):
    import hashlib
    import cdr_export_contract as contracts
    import cdr_ledger_v2 as ledger
    root = tmp_path / "state"
    root.mkdir()
    relative = "runs/" + DAY + "/_exports"
    export = tmp_path / relative
    export.mkdir(parents=True)
    raw = json.dumps(count_status()).encode()
    path = export / "ingest-status.json"
    path.write_bytes(raw)
    generation = "obs-" + DAY + "-" + "a" * 16
    pointer = {"observation_date": DAY, "generation_id": generation, "observation_state": "partial",
               "marker_path": DAY + ".done.json", "export_path": relative, "ledger_event_digest": "event"}
    marker = {"generation_id": generation, "observation_state": "partial", "run_date": DAY,
              "ledger_state": "finalized", "finalization_schema_version": 2, "export_contract_digest": "contract",
              "export_contract_path": "contract.json", "ledger_event_digest": "event"}
    contract = {"generation_id": generation, "observation_date": DAY, "observation_state": "partial",
                "contract_digest": "contract", "source_generation_digest": "source", "source_path": relative,
                "completion_marker_path": pointer["marker_path"], "artifacts": [{"path": "ingest-status.json",
                "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}]}
    event = {"generation_id": generation, "observation_date": DAY, "observation_state": "partial",
             "ledger_state": "finalized", "contract_digest": "contract", "event_digest": "event", "contract_path": "contract.json"}
    values = {"observation-pointers-v2/latest-observation.json": pointer,
              pointer["marker_path"]: marker, "contract.json": contract,
              f"ledger-v2/events/{DAY}/{generation}.json": event}
    class Watch:
        @staticmethod
        def read_json(root, relative, *, maximum=1048576):
            assert maximum <= 8 * 1024 * 1024
            return values[relative]
    monkeypatch.setattr(contracts, "validate_contract", lambda value: None)
    monkeypatch.setattr(contracts, "contract_digest", lambda value: "contract")
    monkeypatch.setattr(contracts, "source_generation_digest", lambda value: "source")
    monkeypatch.setattr(ledger, "event_digest", lambda value: "event")
    return Watch, root, path, values


def test_remote_count_binds_hash_and_selected_generation(tmp_path, monkeypatch):
    watch, root, path, values = count_source(tmp_path, monkeypatch)
    result = snapshot._remote_failure_counts(watch, root, DAY)
    assert result["available"] and result["known_failed_products"] == 2
    assert result["generation_id"] == values["contract.json"]["generation_id"]
    assert result["source_sha256"] == values["contract.json"]["artifacts"][0]["sha256"]
    path.write_bytes(path.read_bytes() + b" ")
    unknown = snapshot._remote_failure_counts(watch, root, DAY)
    assert not unknown["available"] and unknown["unverified"]
    assert "known_failed_products" not in unknown


def test_remote_count_rejects_marker_generation_mismatch(tmp_path, monkeypatch):
    watch, root, path, values = count_source(tmp_path, monkeypatch)
    values[DAY + ".done.json"]["generation_id"] = "different-generation"
    result = snapshot._remote_failure_counts(watch, root, DAY)
    assert not result["available"] and "known_failed_products" not in result
