"""Fault tests for real resource policy, never simulated business acceptance."""
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest
import pi_drive_backup_resources as resources


def host(**changes):
    return {"available_bytes": 6 * 1024**3, "swap_in_pages": 0, "swap_out_pages": 0,
            "page_size_bytes": 16384, "psi_avg10": None, **changes}


def receipt(**changes):
    return {"schema": resources.SCHEMA, "result": "PASS", "mode": "sampled_cgroup_rss",
        "limits": asdict(resources.Limits()), "samples": 2, "peak_rss_bytes": 1000, "peak_processes": 2,
        "minimum_available_bytes": host()["available_bytes"], "maximum_sample_gap_seconds": .1,
        "group_clean": True, "workload_exit_code": 0, "page_size_bytes": 16384,
        "cold_swap_in_bytes": 0, "peak_workload_swap_bytes": 0, "elapsed_seconds": 1,
        "baseline": host(), "last_host_sample": host(), **changes}


@pytest.mark.parametrize("changes", [{"workload_bytes": 769 * resources.MIB}, {"reserve_bytes": 1024**3},
    {"sample_seconds": 1}, {"max_sample_gap_seconds": 3}, {"runtime_seconds": 21 * 3600},
    {"cold_swap_in_bytes": 17 * resources.MIB}])
def test_limits_cannot_weaken_bounds(changes):
    with pytest.raises(ValueError):
        resources.Limits(**changes).validate()


@pytest.mark.parametrize("changes", [{"group_clean": False}, {"samples": 0}, {"workload_exit_code": True},
    {"peak_rss_bytes": 640 * resources.MIB}, {"minimum_available_bytes": 2559 * resources.MIB},
    {"maximum_sample_gap_seconds": 2.1}, {"elapsed_seconds": 20 * 3600}, {"peak_workload_swap_bytes": 16384},
    {"last_host_sample": host(swap_out_pages=1)}, {"cold_swap_in_bytes": 1},
    {"result": "FAIL"}, {"page_size_bytes": 4096}])
def test_incomplete_failed_or_over_budget_receipt_rejected(changes):
    with pytest.raises(ValueError):
        resources.require_receipt(receipt(**changes))


def test_small_cold_readback_is_bounded_over_entire_operation():
    resources.require_receipt(receipt(last_host_sample=host(swap_in_pages=3), cold_swap_in_bytes=49152))
    with pytest.raises(ValueError):
        resources.require_receipt(receipt(last_host_sample=host(swap_in_pages=1025), cold_swap_in_bytes=1025 * 16384))


@pytest.mark.parametrize("sample,host_changes,reason", [
    ({"rss_bytes": 650 * resources.MIB}, {}, "aggregate_rss_early_stop"),
    ({"swap_bytes": 16384}, {}, "workload_swapped"),
    ({}, {"swap_out_pages": 1}, "host_swap_out_activity"),
    ({}, {"available_bytes": 2500 * resources.MIB}, "host_reserve_headroom")])
def test_monitor_stops_actual_bad_samples(monkeypatch, sample, host_changes, reason):
    monkeypatch.setattr(resources, "aggregate", lambda _: {"rss_bytes": 1000, "swap_bytes": 0, "processes": 4, **sample})
    monkeypatch.setattr(resources, "process_peaks", lambda *_: None)
    monkeypatch.setattr(resources, "host_sample", lambda: host(**host_changes))
    with pytest.raises(RuntimeError, match=reason):
        resources.monitor(SimpleNamespace(poll=lambda: None), Path("unused"), resources.Limits(), host(), receipt(), lambda: None)


def test_quiet_window_guard_interrupts_entire_worker(monkeypatch):
    def guard():
        raise RuntimeError("quiet window")
    monkeypatch.setattr(resources, "aggregate", lambda _: pytest.fail("guard must run first"))
    with pytest.raises(RuntimeError, match="quiet window"):
        resources.monitor(SimpleNamespace(poll=lambda: None), Path("unused"), resources.Limits(), host(), receipt(), guard)


def test_zero_exit_with_detached_child_is_failure(monkeypatch):
    monkeypatch.setattr(resources, "aggregate", lambda _: {"rss_bytes": 1000, "swap_bytes": 0, "processes": 2})
    monkeypatch.setattr(resources, "process_peaks", lambda *_: None)
    monkeypatch.setattr(resources, "host_sample", host)
    monkeypatch.setattr(resources, "members", lambda _: {resources.os.getpid(), 12345})
    with pytest.raises(RuntimeError, match="left_descendants"):
        resources.monitor(SimpleNamespace(poll=lambda: 0), Path("unused"), resources.Limits(), host(), receipt(), lambda: None)


def test_unowned_group_is_never_signalled(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, "own_cgroup", lambda: tmp_path)
    monkeypatch.setattr(resources, "members", lambda _: {resources.os.getpid(), 12345})
    monkeypatch.setattr(resources, "terminate", lambda *_: pytest.fail("preexisting processes must not be signalled"))
    result = resources.supervise(["unused"], tmp_path / "resources.json")
    assert result["result"] == "BLOCKED"


def test_go_process_spawn_has_soft_hint_and_no_address_space_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, "own_cgroup", lambda: tmp_path)
    monkeypatch.setattr(resources, "members", lambda _: {resources.os.getpid()})
    monkeypatch.setattr(resources, "preflight", lambda *_a, **_kw: {**host(), "admission_sample": host()})
    monkeypatch.setattr(resources, "terminate", lambda *_: True)
    recorded = {}
    def spawn(command, **kwargs):
        recorded.update(kwargs)
        return SimpleNamespace()
    monkeypatch.setattr(resources.subprocess, "Popen", spawn)
    monkeypatch.setattr(resources, "monitor", lambda child, group, limits, baseline, result, guard: result.update(receipt()))
    result = resources.supervise(["restic"], tmp_path / "resources.json")
    assert result["result"] == "PASS"
    assert recorded["env"]["GOMEMLIMIT"] == "192MiB"
    assert "preexec_fn" not in recorded
