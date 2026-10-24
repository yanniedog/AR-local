"""Portable pure accounting/admission tests; no process signals or Pi effects."""
import threading
import time

import pytest

import pi_ci_resources as resources


def host(**changes):
    return {'available': 3000 * resources.MIB, 'in': 100, 'out': 20, 'page': 4096} | changes


@pytest.mark.parametrize('current,rss,swapped,gap,reason', [
    (host(out=21), 1, 0, .1, 'host_swap_out_activity'),
    (host(out=19), 1, 0, .1, 'swap_counter_reset'),
    (host(page=8192), 1, 0, .1, 'page_size_changed'),
    (host(**{'in': 100 + 4097}), 1, 0, .1, 'cold_swap_in_budget'),
    (host(available=2559 * resources.MIB), 1, 0, .1, 'host_memory_reserve'),
    (host(), 640 * resources.MIB, 0, .1, 'aggregate_rss_early_stop'),
    (host(), 1, 4096, .1, 'workload_swapped'),
    (host(), 1, 0, 2.001, 'supervision_sample_gap'),
    (host(**{'in': 100 + 4096}), 639 * resources.MIB, 0, 2, None),
])
def test_exact_resource_boundaries(current, rss, swapped, gap, reason):
    assert resources.violation(current, host(), host(), rss, swapped, gap) == reason


def observer(monkeypatch):
    value = resources.Observer.__new__(resources.Observer)
    value.group = '/system.slice/ar-local-ci-activate-' + 'a' * 64 + '.service'
    value.baseline = value.previous = host(); value.reason = None
    value.last = time.monotonic(); value.samples = 0
    value.peak_rss = value.peak_swap = value.max_gap = 0
    value.stop = threading.Event(); value.thread = None; value.worker_active = False
    value.excluded = {10: 100, 20: 200}
    monkeypatch.setattr(resources, 'members', lambda group: {10, 20, 30})
    monkeypatch.setattr(resources, 'process', lambda pid, group: {'ticks': pid * 10, 'rss': 1024, 'swap': 0})
    return value


def test_independent_observer_detects_swap_between_workers_without_reset(monkeypatch):
    value = observer(monkeypatch); current = host()
    monkeypatch.setattr(resources, 'host_sample', lambda: current.copy())
    value.start()
    try:
        # No worker is active: this represents root materialization/service work.
        current['out'] += 1
        limit = time.monotonic() + 2
        while value.reason is None and time.monotonic() < limit: time.sleep(.01)
        with pytest.raises(RuntimeError, match='host_swap_out_activity'): value.check()
        assert value.baseline['out'] == 20
    finally:
        receipt = value.close()
    assert receipt['result'] == 'FAIL' and receipt['last_host']['out'] == 21


def test_every_process_counts_toward_aggregate_and_swap(monkeypatch):
    value = observer(monkeypatch)
    monkeypatch.setattr(resources, 'host_sample', host)
    monkeypatch.setattr(resources, 'process', lambda pid, group: {'ticks': pid * 10, 'rss': 220 * resources.MIB, 'swap': 0})
    with pytest.raises(RuntimeError, match='aggregate_rss'): value.sample()
    assert value.peak_rss == 660 * resources.MIB


def test_live_accounting_errors_are_not_treated_as_exited_processes(monkeypatch):
    value = observer(monkeypatch)
    monkeypatch.setattr(resources, 'process', lambda *args: (_ for _ in ()).throw(PermissionError('live smaps denied')))
    with pytest.raises(PermissionError): value.sample()


def test_sample_gap_and_reused_trusted_pid_fail(monkeypatch):
    value = observer(monkeypatch); monkeypatch.setattr(resources, 'host_sample', host)
    value.last = time.monotonic() - 3
    with pytest.raises(RuntimeError, match='supervision_sample_gap'): value.sample()
    monkeypatch.setattr(resources, 'process', lambda pid, group: {'ticks': 999, 'rss': 1, 'swap': 0})
    with pytest.raises(RuntimeError, match='PID reused'): value.sample()
