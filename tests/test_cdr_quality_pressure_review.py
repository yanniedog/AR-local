"""Regressions for PR1064 source-evidence and legacy dispatch findings."""
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pi_cdr_quality_pressure as pressure
import pi_cdr_quality_activate_evidence as evidence
from tests.test_cdr_quality_pressure import proc_fixture, next_host
from tests.test_cdr_quality_refault_nodes import two_nodes, delta, positive_receipt


def forged_recovered_receipt():
    first = two_nodes(); bad = next_host(first)
    bad['pressure']['zones'][0]['pages free'] = 250
    delta(bad, 0, file=6)
    tracker = pressure.PressureTracker(first)
    tracker.observe(bad)
    last = next_host(bad); last['pressure']['zones'][0]['pages free'] = 5000
    summary = tracker.receipt()
    summary.update(result='PASS', failure=None, low_with_refault_samples=0, observations=3,
                   last_monotonic_ns=last['pressure']['monotonic_ns'],
                   last_sha256=pressure.fingerprint(last['pressure']))
    for row in summary['refault_events']:
        row[3] = row[6] = 4700
    return summary, first, last


def test_intermediate_low_cannot_be_raised_after_recovery():
    summary, first, last = forged_recovered_receipt()
    with pytest.raises(ValueError): pressure.require_pressure_receipt(summary, first, last)


def test_closing_node_reset_offset_by_other_node_is_not_invisible(tmp_path, monkeypatch):
    memory, vm = proc_fixture(tmp_path); sysfs = tmp_path/'sysfs'
    vm = vm.replace('workingset_refault_file 0', 'workingset_refault_file 10')
    (tmp_path/'vmstat').write_bytes(vm.encode())
    zone = (tmp_path/'zoneinfo').read_text()
    (tmp_path/'zoneinfo').write_text(zone + zone.replace('Node 0,', 'Node 1,'))
    (sysfs/'devices/system/node/online').write_bytes(b'0-1\n')
    first = sysfs/'devices/system/node/node0/vmstat'
    second = sysfs/'devices/system/node/node1/vmstat'; second.parent.mkdir()
    first.write_bytes(b'workingset_refault_anon 0\nworkingset_refault_file 10\n')
    second.write_bytes(b'workingset_refault_anon 0\nworkingset_refault_file 0\n')
    original = pressure.bounded_text; mutated = []
    def reader(path, limit):
        value = original(path, limit)
        # Mutation after the first complete node pass, global sum unchanged.
        if path == second and not mutated:
            first.write_bytes(b'workingset_refault_anon 0\nworkingset_refault_file 9\n')
            second.write_bytes(b'workingset_refault_anon 0\nworkingset_refault_file 1\n')
            mutated.append(True)
        return value
    monkeypatch.setattr(pressure, 'bounded_text', reader)
    monkeypatch.setattr(pressure.os, 'sysconf', lambda name:16384, raising=False)
    with pytest.raises(ValueError): pressure.sample_pressure(tmp_path, memory, vm, sysfs=sysfs)
    assert mutated == [True]


def manifest_fixture(tmp_path, monkeypatch, resource_schema, profile='legacy'):
    """Actual manifest validator, unrelated evidence providers replaced at seams."""
    import pi_cdr_quality_runtime_state as state
    import app_payload_revisions_state as payload
    now = datetime.now(timezone.utc); digest = 'a'*64; commit = 'b'*40
    root, production, data, operation = [tmp_path/name for name in ('source','production','data','operation')]
    for path in (root,production,data,operation): path.mkdir()
    (root/'worker.py').write_text('# protocol fixture\n')
    records = {}
    def entry(name, value):
        path = operation/name; records[path] = value
        return {'path':str(path),'sha256':digest}
    rollback = {'candidate_file_sha256':digest,'candidate_helpers_sha256':digest,
                'previous_file_sha256':digest,'previous_helpers_sha256':digest,'queue_compatible':True}
    files = {'worker.py':digest}; protected = {'data':digest}; controls = {}
    canary = {'schema':evidence.CANARY_SCHEMA,'result':'PASS','target_commit':commit,
              'source_files':files,'protected_files':protected,'publication_controls':controls,
              'rollback_contract':rollback,'pressure_profile':profile,
              'tests':entry('pytest.xml',{}),'resources':entry('resources.json',{'schema':resource_schema}),
              'source_audit':entry('source-audit.json',{}),'generation_id':'fixture','dispositions':{},
              'candidate_manifest':entry('candidate.json',{'run_date':'2026-11-03'}),'run_date':'2026-11-03'}
    value = {'schema':evidence.SCHEMA,'authority':'D-027','target_commit':commit,'previous_commit':'c'*40,
             'created_at':now.isoformat(),'expires_at':(now+timedelta(hours=1)).isoformat(),
             'source_root':str(root),'production_root':str(production),'data_root':str(data),'operation_root':str(operation),
             'source_files':files,'changed_files':files,'protected_files':protected,'publication_controls':controls,
             'rollback_contract':rollback,'evidence':{'ci':entry('ci.json',{}),'canary':entry('canary.json',canary),'app':entry('app.json',{})}}
    path = operation/'activation.json';records[path]=value
    monkeypatch.setattr(evidence,'sha',lambda path:digest)
    monkeypatch.setattr(evidence,'read',lambda path:records[path])
    monkeypatch.setattr(evidence,'checked',lambda entry:Path(entry['path']))
    monkeypatch.setattr(evidence,'ci_binding',lambda *a:None)
    monkeypatch.setattr(evidence,'app_binding',lambda *a:None)
    monkeypatch.setattr(evidence,'canary_test_result',lambda *a,**k:canary['tests'])
    monkeypatch.setattr(evidence,'source_acceptance',lambda *a:None)
    monkeypatch.setattr(state,'_pending_helpers',lambda *a:(digest,digest,True))
    monkeypatch.setattr(payload,'validate_manifest',lambda *a:None)
    return path, digest, now


@pytest.mark.parametrize('schema', ['ar-local-quality-resources-v3','ar-local-quality-resources-v4',
                                    'ar-local-quality-resources-v5','unknown',None])
def test_activation_legacy_label_cannot_bypass_unknown_resource_schema(tmp_path, monkeypatch, schema):
    path, digest, now = manifest_fixture(tmp_path, monkeypatch, schema)
    with pytest.raises(ValueError): evidence.validate_manifest(path,digest,current=now)


def test_known_v2_still_requires_complete_resource_validation(tmp_path, monkeypatch):
    from dataclasses import asdict
    from pi_cdr_quality_resources import Limits, GIB
    path, digest, now = manifest_fixture(tmp_path, monkeypatch, 'ar-local-quality-resources-v2')
    resources = evidence.read(path.parent/'resources.json')
    host = {'available_bytes':6*GIB,'swap_in_pages':0,'swap_out_pages':0,'page_size_bytes':16384,'psi_avg10':None}
    resources.update(result='PASS',mode='sampled_cgroup_rss',limits=asdict(Limits()),group_clean=True,
                     workload_exit_code=0,samples=2,peak_rss_bytes=1000,minimum_available_bytes=6*GIB,
                     maximum_sample_gap_seconds=.1,page_size_bytes=16384,cold_swap_in_bytes=0,
                     peak_workload_swap_bytes=0,baseline=host,last_host_sample=host)
    evidence.validate_manifest(path,digest,current=now)
    # Canary evidence records workload swap (owner decision 2026-11-07/08).
    resources['peak_workload_swap_bytes'] = 67715072
    evidence.validate_manifest(path,digest,current=now)
    resources['peak_workload_swap_bytes'] = -1
    with pytest.raises(ValueError): evidence.validate_manifest(path,digest,current=now)
    resources['peak_workload_swap_bytes'] = 0
    resources['pressure_evidence'] = {}
    with pytest.raises(ValueError): evidence.validate_manifest(path,digest,current=now)


@pytest.mark.parametrize('fault', ['omitted','duplicate','reordered','sequence','fingerprint','raw_low',
    'raw_node_counter','raw_allocation','raw_cache','raw_mode','raw_minimum','source_without_event','byte_count'])
def test_retained_source_snapshot_tampering_is_rejected(fault):
    summary, first, last = positive_receipt(); sources = summary['refault_snapshots']
    source = sources[0]; raw = source['pressure']
    if fault == 'omitted': sources.pop(0)
    elif fault == 'duplicate': sources[1] = copy.deepcopy(source)
    elif fault == 'reordered': sources.reverse()
    elif fault == 'sequence': source['sequence'] += 1
    elif fault == 'fingerprint': source['sha256'] = '0'*64
    elif fault == 'raw_low': raw['zones'][0]['pages free'] -= 1
    elif fault == 'raw_node_counter': raw['node_refaults'][0][2] += 1;raw['counters']['workingset_refault_file'] += 1
    elif fault == 'raw_allocation': raw['counters']['allocstall_normal'] += 1
    elif fault == 'raw_cache': raw['cache_bytes']['Cached'] += 1
    elif fault == 'raw_mode': raw['lru_gen_enabled'] = 0
    elif fault == 'raw_minimum': raw['zones'][0]['pages free'] = raw['zones'][0]['min']
    elif fault == 'source_without_event':
        raw['node_refaults'] = copy.deepcopy(first['pressure']['node_refaults'])
        for key in pressure.REFAULT_COUNTERS: raw['counters'][key] = first['pressure']['counters'][key]
    elif fault == 'byte_count': summary['refault_evidence_bytes'] -= 1
    if fault.startswith('raw_') or fault == 'source_without_event':
        # Self-hashes are not the external trust anchor; even a consistent
        # recomputed self-hash must not defeat independently derived fields.
        source['sha256'] = pressure.fingerprint(raw)
    with pytest.raises(ValueError): pressure.require_pressure_receipt(summary,first,last)


def test_snapshot_is_independent_of_event_and_receipt_caller_mutation():
    first = two_nodes(); last = next_host(first); delta(last,1,file=3)
    tracker = pressure.PressureTracker(first);tracker.observe(last)
    summary = tracker.receipt()
    summary['refault_snapshots'][0]['pressure']['zones'][1]['pages free'] = 0
    last['pressure']['zones'][1]['pages free'] = 1
    assert tracker.receipt()['refault_snapshots'][0]['pressure']['zones'][1]['pages free'] == 5000


def test_combined_byte_cap_rejects_before_partial_interval_append(monkeypatch):
    first = two_nodes(); last = next_host(first);delta(last,0,file=1);delta(last,1,file=2)
    probe = pressure.PressureTracker(first);probe.observe(last)
    exact = probe.receipt()['refault_evidence_bytes']
    monkeypatch.setattr(pressure,'MAX_REFAULT_EVIDENCE_BYTES',exact)
    tracker = pressure.PressureTracker(first);tracker.observe(last)
    pressure.require_pressure_receipt(tracker.receipt(),first,last)
    monkeypatch.setattr(pressure,'MAX_REFAULT_EVIDENCE_BYTES',exact-1)
    failing = pressure.PressureTracker(first)
    with pytest.raises(ValueError,match='source_evidence_capacity'): failing.observe(last)
    summary = failing.receipt()
    assert summary['refault_events'] == summary['refault_snapshots'] == []
    assert summary['refault_evidence_bytes'] == pressure.REFAULT_EVIDENCE_OVERHEAD
    with pytest.raises(ValueError): pressure.require_pressure_receipt(tracker.receipt(),first,last)


def test_64_node_64_zone_maximum_width_indented_bytes_are_bounded():
    import json
    value = two_nodes()['pressure']; maximum = pressure.MAX_VALUE
    value['monotonic_ns'] = maximum
    value['cache_bytes'] = {key:maximum for key in pressure.CACHE_FIELDS}
    value['counters'] = {key:maximum for key in pressure.COUNTERS}
    value['zones'] = [dict(node=node,zone='Normal',managed=maximum,boost=0,
                          **{'pages free':maximum,'min':maximum-3,'low':maximum-2,'high':maximum-1})
                      for node in range(9936,10000)]
    value['node_refaults'] = [[node,maximum//64,maximum//64] for node in range(9936,10000)]
    for key in pressure.REFAULT_COUNTERS:value['counters'][key] = 64*(maximum//64)
    value['capture'] = {'global_before': value['counters'], 'global_after': value['counters'],
                        'nodes_before': value['node_refaults'], 'nodes_after': value['node_refaults']}
    pressure.validate_snapshot(value)
    source = {'sequence':maximum,'sha256':pressure.fingerprint(value),'pressure':value}
    rows = [[maximum,maximum,node,2,maximum//64,maximum//64,2] for node in range(9936,10000)]
    interval = [maximum,maximum,-maximum,maximum,maximum,maximum,maximum,maximum,maximum]
    assert pressure.evidence_item_bytes(interval) <= 384
    evidence_bytes = (pressure.REFAULT_EVIDENCE_OVERHEAD + pressure.evidence_item_bytes(source)
                      + sum(map(pressure.evidence_item_bytes,rows)) + pressure.evidence_item_bytes(interval))
    actual = len(json.dumps({'pressure_evidence':{'host':{'refault_events':rows,'refault_snapshots':[source],
                                                         'refault_intervals':[interval],
                                                       'refault_evidence_bytes':evidence_bytes}}},indent=2).encode())
    assert actual <= evidence_bytes <= pressure.MAX_REFAULT_EVIDENCE_BYTES
    assert pressure.MAX_REFAULT_EVIDENCE_BYTES == 32*1024**2
