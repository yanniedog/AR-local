"""Resource-policy and process-accounting faults; no synthetic CDR fixtures."""
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

import pi_cdr_quality_resources as resources


def host(available=6 * resources.GIB, swap=0, psi=None, swap_out=0, page_size=16384):
    return {"available_bytes": available, "swap_in_pages": swap, "swap_out_pages": swap_out,
            "page_size_bytes": page_size, "psi_avg10": psi}


def receipt():
    return {"schema": resources.SCHEMA, "result": "PASS", "mode": "sampled_cgroup_rss", "limits": asdict(resources.Limits()),
        "samples": 2, "peak_rss_bytes": 1000, "minimum_available_bytes": 6 * resources.GIB,
        "maximum_sample_gap_seconds": 0.1, "group_clean": True, "workload_exit_code": 0,
        "page_size_bytes": 16384, "cold_swap_in_bytes": 0, "peak_workload_swap_bytes": 0,
        "baseline": host(), "last_host_sample": host()}


def test_missing_psi_is_disclosed_and_swap_counters_are_required(tmp_path):
    (tmp_path / "meminfo").write_text("MemAvailable: 6000000 kB\n")
    (tmp_path / "vmstat").write_text("pswpin 10\npswpout 20\n")
    value = resources.host_sample(tmp_path, page_size_bytes=16384)
    assert value == {"available_bytes": 6000000 * 1024, "swap_in_pages": 10, "swap_out_pages": 20, "page_size_bytes": 16384, "psi_avg10": None}
    (tmp_path / "vmstat").write_text("pswpin 10\n")
    with pytest.raises(ValueError):
        resources.host_sample(tmp_path, page_size_bytes=16384)


def test_admission_reserves_entire_budget_and_runtime_stops_above_host_floor():
    limits = resources.Limits()
    assert resources.host_violation(host(5 * resources.GIB), host(), limits, admission=True) == "host_reserve_headroom"
    assert resources.host_violation(host(2 * resources.GIB), host(), limits) == "host_reserve_headroom"
    assert resources.host_violation(host(swap_out=1), host(), limits) == "host_swap_out_activity"
    assert resources.host_violation(host(psi=10), host(), limits) == "host_memory_pressure"
    assert resources.host_violation(host(), host(), limits) is None


@pytest.mark.parametrize("change", [{"reserve_bytes": resources.GIB}, {"workload_bytes": 4 * resources.GIB},
    {"address_space_bytes": 4 * resources.GIB}, {"sample_seconds": 1}, {"runtime_seconds": 6000}, {"cold_swap_in_bytes": 17 * 1024**2}])
def test_limits_cannot_weaken_the_reviewed_boundary(change):
    with pytest.raises(ValueError):
        resources.Limits(**change).validate()


def test_aggregate_counts_every_cgroup_process_including_detached_descendants(tmp_path):
    group = tmp_path / "group"
    group.mkdir()
    (group / "cgroup.procs").write_text("101\n202\n202\n303\n")
    proc = tmp_path / "proc"
    for pid, rss in ((101, 10), (202, 20), (303, 30)):
        (proc / str(pid)).mkdir(parents=True)
        (proc / str(pid) / "smaps_rollup").write_text(f"Rss: {rss} kB\nSwap: 0 kB\n")
    assert resources.aggregate(group, proc=proc) == {"rss_bytes": 60 * 1024, "swap_bytes": 0, "processes": 3}
    (proc / "202/smaps_rollup").unlink()
    with pytest.raises(RuntimeError, match="no readable memory"):
        resources.aggregate(group, proc=proc)


@pytest.mark.parametrize("change", [{"group_clean": False}, {"samples": 0}, {"result": "FAIL"},
    {"workload_exit_code": 1}, {"peak_rss_bytes": 3 * resources.GIB}, {"maximum_sample_gap_seconds": 3},
    {"minimum_available_bytes": resources.GIB}, {"last_host_sample": host(swap_out=1)},
    {"peak_workload_swap_bytes": 16384}, {"page_size_bytes": 4096}, {"cold_swap_in_bytes": 1}])
def test_failed_or_incomplete_supervision_receipt_cannot_pass(change):
    value = receipt()
    value.update(change)
    with pytest.raises(ValueError):
        resources.require_receipt(value)


def test_monitor_stops_on_aggregate_growth_even_when_each_child_is_small(monkeypatch):
    monkeypatch.setattr(resources, "aggregate", lambda _: {"rss_bytes": 3 * resources.GIB, "swap_bytes": 0, "processes": 5})
    monkeypatch.setattr(resources, "host_sample", host)
    value = receipt()
    value.update(samples=0, peak_processes=0)
    with pytest.raises(RuntimeError, match="aggregate_rss_early_stop"):
        resources.monitor(SimpleNamespace(poll=lambda: None), Path("unused"), resources.Limits(), host(), value)
    assert value["peak_processes"] == 5 and value["samples"] == 1


def test_zero_exit_with_orphaned_descendant_is_failure(monkeypatch):
    monkeypatch.setattr(resources, "aggregate", lambda _: {"rss_bytes": 100, "swap_bytes": 0, "processes": 2})
    monkeypatch.setattr(resources, "host_sample", host)
    monkeypatch.setattr(resources, "members", lambda _: {resources.os.getpid(), 12345})
    value = receipt()
    value.update(peak_processes=0)
    with pytest.raises(RuntimeError, match="left_descendants"):
        resources.monitor(SimpleNamespace(poll=lambda: 0), Path("unused"), resources.Limits(), host(), value)


def test_slow_first_accounting_sample_cannot_be_accepted_as_zero_gap(monkeypatch):
    clock = iter([0, 3])
    monkeypatch.setattr(resources.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(resources, "aggregate", lambda _: {"rss_bytes": 100, "swap_bytes": 0, "processes": 1})
    monkeypatch.setattr(resources, "host_sample", host)
    value = receipt()
    value.update(peak_processes=0)
    with pytest.raises(RuntimeError, match="sample_gap"):
        resources.monitor(SimpleNamespace(poll=lambda: 0), Path("unused"), resources.Limits(), host(), value)


def test_preexisting_group_is_not_killed_when_admission_rejects(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, "own_cgroup", lambda: tmp_path)
    monkeypatch.setattr(resources, "members", lambda _: {resources.os.getpid(), 99999})
    monkeypatch.setattr(resources, "terminate", lambda *_: pytest.fail("must not signal a group it did not admit"))
    value = resources.supervise(["unused"], tmp_path / "receipt.json", resources.Limits())
    assert value["result"] == "BLOCKED" and value["workload_exit_code"] is None


def test_signal_uses_stable_pidfd_and_never_signals_self(monkeypatch):
    current = resources.os.getpid()
    events = []
    monkeypatch.setattr(resources, "members", lambda _: {current, 101})
    monkeypatch.setattr(resources.os, "pidfd_open", lambda pid, flags: events.append(("open", pid, flags)) or 42, raising=False)
    monkeypatch.setattr(resources.signal, "pidfd_send_signal", lambda fd, sig: events.append(("signal", fd, sig)), raising=False)
    monkeypatch.setattr(resources.os, "close", lambda fd: events.append(("close", fd)))
    resources.signal_members(Path("unused"), 15)
    assert events == [("open", 101, 0), ("signal", 42, 15), ("close", 42)]


@pytest.mark.parametrize("page_size", [4096, 16384, 65536])
def test_cold_swap_readback_budget_uses_actual_page_size_and_total_since_admission(page_size):
    limit = resources.Limits()
    baseline = host(swap=1000, page_size=page_size)
    cap_pages = limit.cold_swap_in_bytes // page_size
    within = host(swap=1000 + cap_pages, page_size=page_size)
    assert resources.host_violation(within, baseline, limit) is None
    assert resources.swap_progress(within, baseline)["swap_in_bytes"] == 16 * 1024**2
    excess = host(swap=1001 + cap_pages, page_size=page_size)
    assert resources.host_violation(excess, baseline, limit, previous=within) == "host_cold_swap_in_budget"


def test_valid_bounded_cold_read_receipt_passes_without_upgrading_an_old_failure():
    value = receipt()
    value["last_host_sample"] = host(swap=3)
    value["cold_swap_in_bytes"] = 3 * 16384
    resources.require_receipt(value)
    value["result"] = "FAIL"
    with pytest.raises(ValueError):
        resources.require_receipt(value)
    value["result"] = "PASS"
    value["last_host_sample"] = host(swap=1025)
    value["cold_swap_in_bytes"] = 1025 * 16384
    with pytest.raises(ValueError):
        resources.require_receipt(value)


@pytest.mark.parametrize("field,value", [("swap_in_pages", None), ("swap_in_pages", -1), ("swap_in_pages", True),
    ("swap_out_pages", "0"), ("page_size_bytes", 0), ("page_size_bytes", 4096)])
def test_missing_malformed_or_changed_counter_metadata_fails(field, value):
    sample = host()
    sample[field] = value
    with pytest.raises(ValueError):
        resources.host_violation(sample, host(), resources.Limits())


def test_counter_reset_above_baseline_is_detected_against_previous_sample():
    with pytest.raises(ValueError, match="counter reset"):
        resources.host_violation(host(swap=120), host(swap=100), resources.Limits(), previous=host(swap=150))
    with pytest.raises(ValueError, match="counter reset"):
        resources.host_violation(host(swap=99), host(swap=100), resources.Limits())


def test_preflight_does_not_reset_the_operation_readback_budget(monkeypatch):
    samples = iter([host(swap=1000), host(swap=2000)])
    monkeypatch.setattr(resources.sys, "platform", "linux")
    monkeypatch.setattr(resources.os, "pidfd_open", lambda *_: None, raising=False)
    monkeypatch.setattr(resources.signal, "pidfd_send_signal", lambda *_: None, raising=False)
    monkeypatch.setattr(resources, "host_sample", lambda: next(samples))
    monkeypatch.setattr(resources.time, "sleep", lambda _: None)
    baseline = resources.preflight()
    assert baseline["swap_in_pages"] == 1000
    assert baseline["admission_sample"]["swap_in_pages"] == 2000
    assert resources.host_violation(host(swap=2025), baseline, resources.Limits(), previous=baseline["admission_sample"]) == "host_cold_swap_in_budget"


@pytest.mark.parametrize("text", ["pswpin nope\npswpout 0", "pswpin 1\npswpin 2\npswpout 0", "pswpin -1\npswpout 0"])
def test_malformed_kernel_counter_text_is_not_silently_accepted(tmp_path, text):
    path = tmp_path / "vmstat"
    path.write_text(text)
    with pytest.raises(ValueError):
        resources.swap_counters(path)


def test_workload_swap_is_rejected_even_with_bounded_host_readback(monkeypatch):
    monkeypatch.setattr(resources, "aggregate", lambda _: {"rss_bytes": 100, "swap_bytes": 16384, "processes": 2})
    monkeypatch.setattr(resources, "host_sample", lambda: host(swap=3))
    value = receipt()
    value.update(peak_processes=0)
    with pytest.raises(RuntimeError, match="workload_swapped"):
        resources.monitor(SimpleNamespace(poll=lambda: None), Path("unused"), resources.Limits(), host(), value)
    assert value["peak_workload_swap_bytes"] == 16384 and value["cold_swap_in_bytes"] == 49152
