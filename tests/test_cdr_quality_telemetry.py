"""Kernel-control fixtures and offline failure diagnostics; no CDR data."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import pi_cdr_quality_resources as resources
import pi_cdr_quality_telemetry as telemetry
from tests.test_cdr_quality_resources import host, receipt


ZONE = "Node 1, zone DMA\n  pages free 1659\n  boost 2048\n  min 2177\n  low 2242\n  high 2307\n  managed 65279\n"


def test_optional_counters_are_allowlisted_and_invalid_values_never_become_zero():
    result = telemetry.counter_context("pgscan_kswapd 10\npgscan_direct -1\nsecret_path 9\n", telemetry.VM_FIELDS)
    assert result["values"] == {"pgscan_kswapd": 10}
    assert result["unavailable"]["pgscan_direct"] == "malformed"
    assert result["unavailable"]["pgsteal_anon"] == "missing"
    assert "secret_path" not in json.dumps(result)
    for raw in ("pgscan_kswapd 1\npgscan_kswapd 2", "pgscan_kswapd " + str(2**64), "pgscan_kswapd nope"):
        assert "pgscan_kswapd" not in telemetry.counter_context(raw, telemetry.VM_FIELDS)["values"]
    assert telemetry.counter_context("x" * (telemetry.MAX_COUNTER_TEXT + 1), telemetry.VM_FIELDS)["status"] == "unavailable"
    memory = telemetry.counter_context("MemFree: 25 kB\nShmem: -1 kB", telemetry.MEMORY_FIELDS, kib=True)
    assert memory["values"] == {"MemFree": 25600}


def test_zone_snapshot_is_bounded_and_missing_or_malformed_data_stays_unavailable(tmp_path):
    assert telemetry.zone_snapshot(tmp_path, stage="test")["status"] == "unavailable"
    path = tmp_path / "zoneinfo"
    path.write_text(ZONE)
    result = telemetry.zone_snapshot(tmp_path, stage="after_workload_cleanup")
    assert result["stage"] == "after_workload_cleanup"
    assert result["zones"] == [{"node": 1, "zone": "DMA", "pages free": 1659,
                                "boost": 2048, "min": 2177, "low": 2242, "high": 2307, "managed": 65279}]
    for raw in (ZONE.replace("low 2242", "low bad"), ZONE.replace("low 2242\n", ""),
                ZONE + "  low 1\n", ZONE + ZONE, ZONE.replace("managed 65279", "managed 0"),
                "".join(ZONE.replace("Node 1", f"Node {i}") for i in range(telemetry.MAX_ZONES + 1)),
                "x" * (telemetry.MAX_ZONE_TEXT + 1)):
        path.write_text(raw)
        assert telemetry.zone_snapshot(tmp_path, stage="test")["status"] == "unavailable"
    path.unlink()
    path.mkdir()
    assert telemetry.zone_snapshot(tmp_path, stage="test")["status"] == "unavailable"


def test_native_host_sample_reuses_existing_reads_for_optional_reclaim_context(tmp_path, monkeypatch):
    (tmp_path / "meminfo").write_text("MemAvailable: 6000000 kB\nMemFree: 400000 kB\nShmem: 80000 kB")
    (tmp_path / "vmstat").write_text("pswpin 10\npswpout 20\npgscan_kswapd 800\npgscan_direct 0")
    original, reads = Path.read_text, []
    def read(path, *args, **kwargs):
        reads.append(path.name)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", read)
    result = resources.host_sample(tmp_path, page_size_bytes=16384)
    assert reads == ["meminfo", "vmstat"]
    assert result["diagnostics"]["vmstat"]["values"]["pgscan_kswapd"] == 800
    assert result["diagnostics"]["memory_bytes"]["values"]["Shmem"] == 80000 * 1024
    assert resources.host_violation(result, result, resources.Limits()) is None


def sample(swap_out, reclaimed):
    value = host(swap_out=swap_out)
    value["diagnostics"] = {"vmstat": {"values": {"pgscan_kswapd": reclaimed, "pgscan_direct": 0}}}
    return value


def test_failure_keeps_exact_triggering_sample_and_original_strict_swap_reason(monkeypatch):
    initial, previous, failure = sample(100, 1000), sample(100, 1010), sample(102, 1020)
    initial["admission_sample"] = previous
    monkeypatch.setattr(resources, "aggregate", lambda _: {"rss_bytes": 530 * 1024**2, "swap_bytes": 0, "processes": 5})
    monkeypatch.setattr(resources, "host_sample", lambda: failure)
    monkeypatch.setattr(resources, "utc_now", lambda: "2026-10-12T10:06:33+00:00")
    clock = iter([50.0, 50.1])
    monkeypatch.setattr(resources.time, "monotonic", lambda: next(clock))
    value = receipt()
    value.update(samples=0, peak_processes=0)
    with pytest.raises(RuntimeError, match="^host_swap_out_activity$"):
        resources.monitor(SimpleNamespace(poll=lambda: pytest.fail("failure must precede child poll")),
                          Path("unused"), resources.Limits(), initial, value)
    captured = value["failure_sample"]
    assert captured["host"] == failure and captured["previous_host"] == previous
    assert captured["sample_number"] == 1 and captured["elapsed_seconds"] == pytest.approx(0.1)
    assert captured["at_utc"] == "2026-10-12T10:06:33+00:00"
    assert captured["reclaim_since_admission"]["values"]["pgscan_kswapd"] == 20
    assert captured["reclaim_since_previous"]["values"]["pgscan_kswapd"] == 10
    assert resources.swap_progress(failure, initial)["swap_out_bytes"] == 32768
    assert telemetry.reclaim_delta(previous, failure)["unavailable"]["pgscan_kswapd"] == "counter_reset"
    with pytest.raises(ValueError, match="successful bounded-resource receipt"):
        resources.require_receipt(value)


def test_optional_zone_reads_follow_cleanup_and_cannot_turn_failure_into_pass(tmp_path, monkeypatch):
    events = []
    group = tmp_path / "group"
    group.mkdir()
    monkeypatch.setattr(resources, "own_cgroup", lambda: group)
    monkeypatch.setattr(resources, "members", lambda _: {os.getpid()})
    monkeypatch.setattr(resources.signal, "signal", lambda *_: 0)
    monkeypatch.setattr(resources, "preflight", lambda *_a, **_kw: events.append("preflight") or {**host(), "admission_sample": host()})
    monkeypatch.setattr(resources.subprocess, "Popen", lambda *_a, **_kw: events.append("start") or object())
    def monitor(*_):
        events.append("monitor")
        raise RuntimeError("host_swap_out_activity")
    monkeypatch.setattr(resources, "monitor", monitor)
    monkeypatch.setattr(resources, "terminate", lambda *_: events.append("cleanup") or True)
    def zones(*, stage):
        events.append(stage)
        return {"status": "unavailable", "stage": stage, "reason": "missing"}
    monkeypatch.setattr(resources, "zone_snapshot", zones)
    output = tmp_path / "resources.json"
    result = resources.supervise(["unused"], output, resources.Limits())
    assert events == ["before_resource_preflight", "preflight", "start", "monitor", "cleanup", "after_workload_cleanup"]
    assert result["result"] == "FAIL" and result["group_clean"] is True
    assert result["reason"] == "RuntimeError: host_swap_out_activity"
    assert result["post_cleanup_zones"]["status"] == "unavailable"
    assert json.loads(output.read_bytes()) == result
