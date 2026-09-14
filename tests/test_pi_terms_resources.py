"""Dedicated-unit and priority-yield regressions: all processes are stubbed."""
from pathlib import Path
from types import SimpleNamespace

import pytest

import pi_cdr_quality_resources as resources
from tests.test_cdr_quality_resources import host, receipt


@pytest.mark.parametrize('unit', ['ar-local-terms-worker.service', 'ar-local-quality-canary-a1.service',
                                 'ar-local-quality-resource-test-abc.service'])
def test_exact_worker_unit_is_admitted(unit):
    assert resources.UNIT.fullmatch(unit)


@pytest.mark.parametrize('unit', ['ar-local-daily.service', 'ar-local-terms-worker-extra.service',
                                 'ar-local-terms-worker.service/child', 'ar-local-terms-worker@a.service'])
def test_other_or_nested_units_are_not_admitted(unit):
    assert not resources.UNIT.fullmatch(unit)


def setup_supervisor(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, 'own_cgroup', lambda: tmp_path)
    monkeypatch.setattr(resources, 'members', lambda _: {resources.os.getpid()})
    baseline = host()
    baseline['admission_sample'] = host()
    monkeypatch.setattr(resources, 'preflight', lambda *_a, **_k: baseline)
    monkeypatch.setattr(resources.signal, 'signal', lambda *_: None)
    cleaned = []
    monkeypatch.setattr(resources, 'terminate', lambda group, child: cleaned.append((group, child)) or True)
    return cleaned


def test_priority_check_before_launch_makes_no_child_and_cleans_only_owned_group(tmp_path, monkeypatch):
    cleaned = setup_supervisor(tmp_path, monkeypatch)
    monkeypatch.setattr(resources.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('must not launch'))
    result = resources.supervise(['never'], tmp_path / 'resources.json', resources.Limits(),
                                 priority_guard=lambda: 'ingest_active')
    assert result['operational_outcome'] == 'PRIORITY_YIELD'
    assert result['result'] == 'BLOCKED' and result['workload_started'] is False
    assert cleaned == [(tmp_path, None)]
    with pytest.raises((ValueError, KeyError)):
        resources.require_receipt(result)


def test_runtime_priority_yield_stops_only_owned_child(tmp_path, monkeypatch):
    cleaned = setup_supervisor(tmp_path, monkeypatch)
    child = SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(resources.subprocess, 'Popen', lambda *_a, **_k: child)
    values = iter([None, 'ingest_started'])
    result = resources.supervise(['never'], tmp_path / 'resources.json', resources.Limits(),
                                 priority_guard=lambda: next(values))
    assert result['operational_outcome'] == 'PRIORITY_YIELD' and result['result'] == 'FAIL'
    assert result['workload_started'] is True and result['priority_checks'] == 2
    assert cleaned == [(tmp_path, child)]


def test_unreadable_priority_is_fail_closed(tmp_path, monkeypatch):
    setup_supervisor(tmp_path, monkeypatch)
    monkeypatch.setattr(resources.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('must not launch'))
    def unreadable():
        raise OSError('unavailable')
    result = resources.supervise(['never'], tmp_path / 'resources.json', resources.Limits(), priority_guard=unreadable)
    assert result['priority_reason'] == 'operational_priority_unavailable'


def test_slow_priority_guard_cannot_hide_a_resource_sample_gap(monkeypatch):
    times = iter([0, 3])
    monkeypatch.setattr(resources.time, 'monotonic', lambda: next(times))
    monkeypatch.setattr(resources, 'aggregate', lambda _: {'rss_bytes': 100, 'swap_bytes': 0, 'processes': 1})
    monkeypatch.setattr(resources, 'host_sample', host)
    value = receipt()
    value['peak_processes'] = 0
    with pytest.raises(RuntimeError, match='sample_gap'):
        resources.monitor(SimpleNamespace(poll=lambda: 0), Path('unused'), resources.Limits(), host(), value,
                          priority_guard=lambda: None)


def test_service_preserves_isolation_and_has_no_automatic_activation():
    root = Path(__file__).resolve().parents[1]
    service = (root / 'deploy/pi/ar-local-terms-worker.service').read_text()
    for directive in ('ConditionPathExists=/etc/ar-local/terms-worker-approved', 'CPUQuota=100%',
                      'MemoryHigh=2G', 'MemoryMax=3G', 'MemorySwapMax=0', 'TasksMax=128', 'IOWeight=10',
                      'KillMode=control-group', 'UMask=0077', 'ProtectSystem=strict', 'ProtectHome=true',
                      'ProtectControlGroups=true', 'NoNewPrivileges=true', 'RestrictNamespaces=true'):
        assert directive in service
    assert 'EnvironmentFile=' not in service and 'Conflicts=' not in service
    timer = (root / 'deploy/pi/ar-local-terms-worker.timer').read_text()
    assert 'Persistent=false' in timer and 'Australia/Hobart' in timer
