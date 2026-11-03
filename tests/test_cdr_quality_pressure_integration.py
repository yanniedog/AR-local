"""Composition controls: real validators, no Pi, HTTP or business fixtures."""
import copy
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import pi_cdr_quality_resources as resources
import pi_cdr_quality_pressure_runtime as runtime
import pi_cdr_quality_service as service
import pi_cdr_quality_activate as activate
import pi_cdr_quality_pressure as pressure

BOOT = 'cf36b73c-1111-4111-8111-111111111111'


def host(t):
    cache = {key: 1024 for key in pressure.CACHE_FIELDS}
    cache.update(MemTotal=8*resources.GIB, MemAvailable=7*resources.GIB)
    return {'page_size_bytes':16384, 'available_bytes':7*resources.GIB,
        'swap_in_pages':0, 'swap_out_pages':0, 'psi_avg10':None,
        'pressure':{'profile':pressure.PROFILE, 'boot_id':BOOT, 'page_size_bytes':16384,
            'monotonic_ns':t, 'read_elapsed_ns':1000000,
            'counters':{key:10 for key in pressure.COUNTERS}, 'cache_bytes':cache,
            'zones':[{'node':0,'zone':'Normal','managed':10000,'pages free':5000,
                      'boost':100,'min':200,'low':300,'high':400}]}}


def snapshot(binding):
    return {'schema':service.SNAPSHOT_SCHEMA, 'binding_sha256':service._binding(binding),
        'seq':1, 'started_monotonic':100., 'finished_monotonic':101.,
        'initial_pass_finished_monotonic':101., 'probe_count':2, 'failed_probe_count':0,
        'failure_latched':False, 'max_latency_s':.5, 'max_round_gap_s':0., 'max_pair_duration_s':1.,
        'probes':[{'endpoint':name, 'status':'PASS', 'http_status':200,
                   'run_date':'2026-11-03','rate_count':1,'latency_s':.5} for name in service.ENDPOINTS]}


def files(binding, value):
    directory = Path(binding['operation'])/'pressure'; directory.mkdir()
    service._write(directory,'binding.json',binding)
    service._write(directory,'snapshot.json',value,replace=True)
    return directory


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    operation = tmp_path / 'operation'; operation.mkdir()
    binding = {'schema': service.SCHEMA, 'source_sha256': service.source_sha256(),
        'source_commit': 'a'*40, 'operation': str(operation),
        'unit': 'ar-local-quality-canary-abcdef.service', 'boot_id': BOOT, 'nonce': 'b'*64}
    monkeypatch.setattr(service, '_boot_id', lambda: BOOT)
    directory = files(binding, snapshot(binding))
    clock = [102.01]
    monkeypatch.setattr(service, '_monotonic', lambda: clock[0])
    monkeypatch.setattr(runtime.time, 'monotonic', lambda: clock[0])
    context = runtime.PressureContext(directory, service._binding(binding),
                                      unit=binding['unit'], operation=operation)
    values = []
    for seconds in (102., 102.2, 102.3):
        value = host(int(seconds*1e9)); value['pressure']['boot_id'] = BOOT
        values.append(value)
    return operation, binding, context, clock, values


def complete(scenario):
    operation, binding, context, clock, values = scenario
    values[-1]['swap_out_pages'] = 41
    for value in values:
        clock[0] = value['pressure']['monotonic_ns']/1e9 + .01
        context.observe(value)
    baseline = {**values[0], 'admission_sample': values[1]}
    receipt = {'schema': resources.PRESSURE_SCHEMA, 'result': 'PASS', 'mode': 'sampled_cgroup_rss',
        'limits': asdict(resources.Limits()), 'samples': 1, 'peak_rss_bytes': 1000,
        'minimum_available_bytes': 7*resources.GIB, 'maximum_sample_gap_seconds': .1,
        'group_clean': True, 'workload_exit_code': 0, 'page_size_bytes': 16384,
        'cold_swap_in_bytes': 0, 'peak_workload_swap_bytes': 0,
        'baseline': baseline, 'last_host_sample': values[-1],
        'cgroup': '/sys/fs/cgroup/system.slice/'+binding['unit'],
        'pressure_evidence': context.receipt()}
    return receipt


def require(receipt, scenario):
    resources.require_receipt(receipt, expected_operation=scenario[0], expected_commit='a'*40)


def test_background_swap_needs_complete_bound_pressure_and_service_proof(scenario):
    receipt = complete(scenario)
    require(receipt, scenario)
    assert receipt['pressure_evidence']['service']['last_observed_monotonic'] > 102.3
    assert receipt['pressure_evidence']['host']['observations'] == 3
    with pytest.raises(ValueError, match='external operation'):
        resources.require_receipt(receipt)
    legacy = copy.deepcopy(receipt); legacy['schema'] = resources.SCHEMA
    with pytest.raises(ValueError, match='relabelled'):
        resources.require_receipt(legacy)
    del legacy['pressure_evidence']
    with pytest.raises(ValueError): resources.require_receipt(legacy)


@pytest.mark.parametrize('fault', ['old_failure','rss','reserve','workload_swap','gap','cold_readback',
    'cleanup','descendants','count','service_latch','pressure_count','pressure_counter','psi_peak','binding'])
def test_enhanced_proof_does_not_waive_existing_or_new_guards(scenario, fault):
    receipt = complete(scenario)
    if fault == 'old_failure': receipt['result'] = 'FAIL'
    elif fault == 'rss': receipt['peak_rss_bytes'] = 3*resources.GIB
    elif fault == 'reserve': receipt['minimum_available_bytes'] = resources.GIB
    elif fault == 'workload_swap': receipt['peak_workload_swap_bytes'] = 1
    elif fault == 'gap': receipt['maximum_sample_gap_seconds'] = 2.01
    elif fault == 'cold_readback': receipt['last_host_sample']['swap_in_pages'] = 1025
    elif fault == 'cleanup': receipt['group_clean'] = False
    elif fault == 'descendants': receipt['workload_exit_code'] = 1
    elif fault == 'count': receipt['samples'] = 2
    elif fault == 'service_latch': receipt['pressure_evidence']['service']['last_snapshot']['failure_latched'] = True
    elif fault == 'pressure_count': receipt['pressure_evidence']['host']['observations'] = 2
    elif fault == 'pressure_counter': receipt['pressure_evidence']['host']['cumulative']['allocstall_normal'] = 1
    elif fault == 'psi_peak': receipt['pressure_evidence']['peak_psi_avg10'] = 0
    elif fault == 'binding': receipt['pressure_evidence']['service']['binding']['source_commit'] = 'c'*40
    with pytest.raises((ValueError, KeyError)): require(receipt, scenario)


def test_context_latches_transient_pressure_and_rejects_later_healthy_state(scenario):
    _, _, context, clock, values = scenario
    context.observe(values[0]); clock[0] = 102.21
    values[1]['pressure']['counters']['allocstall_movable'] += 1
    with pytest.raises(ValueError, match='allocation_pressure'): context.observe(values[1])
    clock[0] = 102.31
    with pytest.raises(ValueError, match='latched'): context.observe(values[2])
    assert context.receipt()['failure'] is not None


@pytest.mark.parametrize('psi', [None, 0., 2.])
def test_profile_selection_is_independent_of_psi_value(tmp_path, monkeypatch, psi):
    (tmp_path/'meminfo').write_text('MemAvailable: 6000000 kB\n')
    (tmp_path/'vmstat').write_text('pswpin 0\npswpout 0\n')
    if psi is not None:
        (tmp_path/'pressure').mkdir()
        (tmp_path/'pressure/memory').write_text(f'some avg10={psi} avg60=0 avg300=0 total=0\n')
    import pi_cdr_quality_pressure as pressure
    calls = []
    monkeypatch.setattr(pressure, 'sample_pressure', lambda *a: calls.append(a) or {'profile':'test'})
    selected = resources.host_sample(tmp_path, page_size_bytes=16384, pressure=True)
    assert selected['pressure'] == {'profile':'test'} and selected['psi_avg10'] == psi
    legacy = resources.host_sample(tmp_path, page_size_bytes=16384)
    assert 'pressure' not in legacy and len(calls) == 1


def test_initial_service_read_skew_is_bounded(scenario):
    _, _, context, clock, values = scenario
    clock[0] = 104.01
    with pytest.raises(ValueError, match='skew'): context.observe(values[0])


def test_monitor_retains_pressure_trigger_and_preceding_sample(scenario, monkeypatch):
    _, _, context, clock, values = scenario
    context.observe(values[0]); clock[0] = 102.21; context.observe(values[1])
    bad = values[2]; bad['pressure']['counters']['pgscan_direct'] += 1
    clock[0] = 102.31
    monkeypatch.setattr(resources, 'host_sample', lambda **_: bad)
    monkeypatch.setattr(resources, 'aggregate', lambda _: {'rss_bytes':100,'swap_bytes':0,'processes':1})
    receipt = {'samples':0,'peak_rss_bytes':0,'peak_processes':0,'minimum_available_bytes':7*resources.GIB,
        'maximum_sample_gap_seconds':0,'peak_workload_swap_bytes':0}
    baseline = {**values[0],'admission_sample':values[1]}
    with pytest.raises(RuntimeError, match='allocation_pressure'):
        resources.monitor(SimpleNamespace(poll=lambda:None), Path('unused'), resources.Limits(),
                          baseline, receipt, pressure_context=context)
    failure = receipt['failure_sample']
    assert failure['host'] == bad and failure['previous_host'] == values[1]
    assert context.receipt()['failure'] is not None


def test_summary_failure_cannot_skip_owned_cleanup(tmp_path, monkeypatch):
    cleaned = []
    class Context:
        def __init__(self, *a, **k): pass
        def receipt(self): raise ValueError('injected serialization failure')
    monkeypatch.setattr(runtime, 'PressureContext', Context)
    monkeypatch.setattr(resources, 'own_cgroup', lambda: tmp_path/'group')
    monkeypatch.setattr(resources, 'members', lambda _: {resources.os.getpid()})
    monkeypatch.setattr(resources, 'zone_snapshot', lambda **_: {})
    first = host(102_000_000_000)
    monkeypatch.setattr(resources, 'preflight', lambda *a, **k: {**first,'admission_sample':first})
    monkeypatch.setattr(resources.subprocess, 'Popen', lambda *a, **k: object())
    monkeypatch.setattr(resources.signal, 'signal', lambda *a: None)
    monkeypatch.setattr(resources, 'monitor', lambda child, group, limits, baseline, receipt, *a:
                        receipt.update(workload_exit_code=0))
    monkeypatch.setattr(resources, 'terminate', lambda group, child: cleaned.append((group,child)) or True)
    receipt = resources.supervise(['/reviewed/worker'], tmp_path/'resources.json', resources.Limits(),
                                  pressure_binding_sha256='a'*64)
    assert len(cleaned) == 1 and receipt['group_clean'] is True
    assert receipt['result'] == 'FAIL' and receipt['pressure_receipt_error'] == 'ValueError'


@pytest.mark.parametrize('remaining,expected', [(376,300),(375,None),(600,524)])
def test_ready_time_recomputes_workload_and_cleanup_window(monkeypatch, remaining, expected):
    now = datetime(2026,11,3,21,50,tzinfo=activate.TZ)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return now
    monkeypatch.setattr(activate, 'datetime', Clock)
    command = ['--property=RuntimeMaxSec=5400s','--runtime-seconds','5385']
    if expected is None:
        with pytest.raises(ValueError, match='after service readiness'):
            activate.pressure_launch_budget(command, now+timedelta(seconds=remaining))
    else:
        assert activate.pressure_launch_budget(command, now+timedelta(seconds=remaining)) == expected
        assert command == [f'--property=RuntimeMaxSec={expected}s','--runtime-seconds',str(expected-15)]
