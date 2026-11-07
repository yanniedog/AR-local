"""Completed rejected telemetry survives admission; no real process is launched."""
import copy
import json
from types import SimpleNamespace

import pytest

import pi_cdr_quality_pressure as pressure
import pi_cdr_quality_resources as resources
import pi_cdr_quality_pressure_runtime as runtime
from tests.test_cdr_quality_pressure_integration import scenario as single_node_scenario


@pytest.fixture
def scenario(single_node_scenario):
    for value in single_node_scenario[4]:
        q = value['pressure']
        q['zones'].append(dict(q['zones'][0], node=1))
        q['node_refaults'].append([1,0,0])
    return single_node_scenario


def quiet_failure(value, fault):
    q = value['pressure']
    q['capture'] = copy.deepcopy(q['capture'])
    if fault == 'node_reset':
        q['capture']['nodes_before'] = copy.deepcopy(q['node_refaults'])
        q['capture']['nodes_before'][0][2] -= 1
        # Keep the ordered sums valid with real growth on the second node;
        # only the componentwise opening-vs-previous node check rejects this.
        q['capture']['nodes_before'][1][2] += 1
        q['node_refaults'][1][2] += 1
        q['counters']['workingset_refault_file'] += 1
        q['capture']['nodes_after'] = copy.deepcopy(q['node_refaults'])
        q['capture']['global_after'] = copy.deepcopy(q['counters'])
    elif fault == 'global_reset':
        q['capture']['global_before'] = copy.deepcopy(q['counters'])
        q['capture']['global_before']['pgmajfault'] -= 1
    else:
        q['read_elapsed_ns'] = 400_000_000
    # It is a complete coherent capture; only cross-capture checks reject it.
    pressure.validate_snapshot(q)
    return {'node_reset': 'pressure_node_counter_reset_between_captures',
            'global_reset': 'pressure_counter_reset_between_captures',
            'overlap': 'pressure_capture_windows_overlap'}[fault]


def sample_sequence(monkeypatch, scenario, samples):
    sequence = iter(samples)
    def sample(**kwargs):
        assert kwargs == {'pressure': True}
        value = next(sequence)
        scenario[3][0] = value['pressure']['monotonic_ns'] / 1e9 + .01
        return value
    monkeypatch.setattr(resources, 'host_sample', sample)
    monkeypatch.setattr(resources.sys, 'platform', 'linux')
    monkeypatch.setattr(resources.os, 'pidfd_open', lambda *_: pytest.fail('no child'), raising=False)
    monkeypatch.setattr(resources.signal, 'pidfd_send_signal', lambda *_: pytest.fail('no child'), raising=False)
    monkeypatch.setattr(resources.time, 'sleep', lambda _: None)


@pytest.mark.parametrize('fault', ['node_reset', 'global_reset', 'overlap'])
def test_real_preflight_retains_completed_capture_and_original_latch(scenario, monkeypatch, fault):
    context = scenario[2]; first, bad = scenario[4][:2]
    reason = quiet_failure(bad, fault)
    sample_sequence(monkeypatch, scenario, [first, bad])
    with pytest.raises(pressure.PressureCaptureError, match=reason) as result:
        resources.preflight(resources.Limits(), admission=True, pressure_context=context)
    assert str(result.value) == reason
    assert result.value.capture == bad['pressure']
    assert context.tracker.failure == reason and context.tracker.receipt()['result'] == 'FAIL'
    bad['pressure']['cache_bytes']['Cached'] += 1
    assert result.value.capture != bad['pressure']  # Independent preserved bytes.
    with pytest.raises(ValueError, match='latched'): context.observe(scenario[4][2])


@pytest.mark.parametrize('fault', ['node_reset', 'global_reset', 'overlap'])
def test_supervisor_admission_keeps_failed_raw_without_starting_child(scenario, monkeypatch, fault):
    operation, binding, context, _, values = scenario
    reason = quiet_failure(values[1], fault)
    sample_sequence(monkeypatch, scenario, values[:2])
    monkeypatch.setattr(runtime, 'PressureContext', lambda *a, **k: context)
    monkeypatch.setattr(resources, 'own_cgroup', lambda: operation/binding['unit'])
    monkeypatch.setattr(resources, 'members', lambda _: {resources.os.getpid()})
    monkeypatch.setattr(resources, 'zone_snapshot', lambda **_: {})
    monkeypatch.setattr(resources.subprocess, 'Popen', lambda *a, **k: pytest.fail('preflight must not launch a child'))
    cleaned = []
    monkeypatch.setattr(resources, 'terminate', lambda group, child: cleaned.append((group, child)) or True)
    path = operation/'resources.json'
    result = resources.supervise(['/not/launched'], path, resources.Limits(),
                                 pressure_binding_sha256=context.binding_sha256)
    assert result['result'] == 'BLOCKED' and result['workload_started'] is False
    assert result['reason'] == 'PressureCaptureError: ' + reason
    assert result['failed_pressure_capture'] == values[1]['pressure']
    assert json.loads(path.read_text()) == result
    assert cleaned == [(operation/binding['unit'], None)] and result['group_clean'] is True
    forged = dict(result, result='PASS')
    with pytest.raises(ValueError, match='failed pressure capture'):
        resources.require_receipt(forged)


@pytest.mark.parametrize('fault', ['node_reset', 'global_reset', 'overlap'])
def test_workload_monitor_still_retains_triggering_host_and_fail_latch(scenario, monkeypatch, fault):
    _, _, context, clock, values = scenario
    context.observe(values[0]); clock[0] = 102.21; context.observe(values[1])
    reason = quiet_failure(values[2], fault)
    sample_sequence(monkeypatch, scenario, [values[2]])
    monkeypatch.setattr(resources, 'aggregate', lambda _: {'rss_bytes': 100, 'swap_bytes': 0, 'processes': 1})
    receipt = {'samples': 0, 'peak_rss_bytes': 0, 'peak_processes': 0, 'minimum_available_bytes': 7*resources.GIB,
               'maximum_sample_gap_seconds': 0, 'peak_workload_swap_bytes': 0, 'workload_swap_in_bytes': 0}
    baseline = {**values[0], 'admission_sample': values[1]}
    with pytest.raises(RuntimeError, match=reason):
        resources.monitor(SimpleNamespace(poll=lambda: None), scenario[0]/'group', resources.Limits(),
                          baseline, receipt, pressure_context=context)
    assert receipt['failure_sample']['host'] == values[2]
    assert receipt['failure_sample']['previous_host'] == values[1]
    assert context.tracker.receipt()['result'] == 'FAIL'
    assert context.tracker.failure == reason


def test_invalid_uncompleted_host_is_not_promoted_to_complete_capture(scenario):
    context = scenario[2]
    context.observe(scenario[4][0])
    del scenario[4][1]['pressure']['capture']
    with pytest.raises(ValueError) as result:
        context.tracker.observe(scenario[4][1])
    assert not isinstance(result.value, pressure.PressureCaptureError)
    assert context.tracker.receipt()['result'] == 'FAIL'
