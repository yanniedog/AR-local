"""Protocol telemetry controls only; no fabricated business/source evidence."""
import copy
import json

import pytest
import pi_cdr_quality_pressure as p
from tests.test_cdr_quality_pressure import host, next_host, proc_fixture


def two_nodes(mask=3):
    first = host()
    first['pressure']['lru_gen_enabled'] = mask
    zone = dict(first['pressure']['zones'][0], node=1)
    first['pressure']['zones'].append(zone)
    first['pressure']['node_refaults'].append([1, 0, 0])
    return first


def delta(value, node, anon=0, file=0):
    for index, count in enumerate((anon, file)):
        value['pressure']['node_refaults'][node][index + 1] += count
        value['pressure']['counters'][p.REFAULT_COUNTERS[index]] += count


@pytest.mark.parametrize('mask', [1, 3, 5, 7])
def test_mglru_low_other_node_does_not_claim_same_node_pressure(mask):
    first = two_nodes(mask); last = next_host(first)
    last['pressure']['zones'][0]['pages free'] = 250
    delta(last, 1, anon=8, file=512)
    tracker = p.PressureTracker(first); tracker.observe(last)
    receipt = tracker.receipt()
    assert receipt['refault_scope'] == 'mglru_same_node'
    assert receipt['low_with_activity_samples'] == 1
    assert receipt['low_with_refault_samples'] == 0
    assert receipt['refault_events'] == [[1, last['pressure']['monotonic_ns'], 1, 4700, 8, 512, -50]]
    p.require_pressure_receipt(receipt, first, last)


@pytest.mark.parametrize('mask', [0, 2, 4, 6])
def test_classic_lru_keeps_global_conservative_conjunction(mask):
    first = two_nodes(mask); last = next_host(first)
    last['pressure']['zones'][0]['pages free'] = 250
    delta(last, 1, file=1)
    tracker = p.PressureTracker(first)
    with pytest.raises(ValueError, match='low_with_refault'): tracker.observe(last)
    assert tracker.receipt()['refault_scope'] == 'classic_global'


@pytest.mark.parametrize('node,anon,file', [(0,1,0), (0,0,64), (1,16,32)])
def test_same_node_low_refault_always_fails(node, anon, file):
    first = two_nodes(); last = next_host(first)
    last['pressure']['zones'][node]['pages free'] = 300
    delta(last, node, anon, file)
    tracker = p.PressureTracker(first)
    with pytest.raises(ValueError, match='low_with_refault'): tracker.observe(last)
    forged = tracker.receipt(); forged.update(result='PASS', failure=None, low_with_refault_samples=0)
    with pytest.raises(ValueError): p.require_pressure_receipt(forged, first, last)


def positive_receipt():
    first = two_nodes(); middle = next_host(first)
    delta(middle, 0, 3, 7); delta(middle, 1, 5, 11)
    last = next_host(middle)
    delta(last, 0, 2, 1); delta(last, 1, 1, 3)
    tracker = p.PressureTracker(first); tracker.observe(middle); tracker.observe(last)
    return tracker.receipt(), first, last


def test_global_peak_is_sum_of_nodes_in_the_same_interval():
    receipt, first, last = positive_receipt()
    assert receipt['maximum_interval']['workingset_refault_file'] == 18
    assert receipt['maximum_interval']['workingset_refault_anon'] == 8
    assert receipt['node_maximum_interval'] == {'0':[3,7], '1':[5,11]}
    p.require_pressure_receipt(receipt, first, last)
    receipt['maximum_interval']['workingset_refault_file'] = 11
    with pytest.raises(ValueError): p.require_pressure_receipt(receipt, first, last)


@pytest.mark.parametrize('fault', ['omitted','duplicate','reordered','node_swap','node_missing','node_extra',
    'node_peak','node_total','global_peak','interval_timestamp','interval_global_low','terminal_node_low',
    'below_node_minimum','mode','old_profile','endpoint_counter','zero_delta','bool_node'])
def test_independent_node_evidence_rejects_tampering(fault):
    receipt, first, last = positive_receipt(); rows = receipt['refault_events']
    if fault == 'omitted': rows.pop(0)
    elif fault == 'duplicate': rows[1] = list(rows[0])
    elif fault == 'reordered': rows[0],rows[1] = rows[1],rows[0]
    elif fault == 'node_swap': rows[0][2] = 1
    elif fault == 'node_missing': del receipt['node_cumulative']['0']
    elif fault == 'node_extra': receipt['node_cumulative']['2'] = [0,0]
    elif fault == 'node_peak': receipt['node_maximum_interval']['0'][0] -= 1
    elif fault == 'node_total': receipt['node_cumulative']['0'][0] -= 1
    elif fault == 'global_peak': receipt['maximum_interval']['workingset_refault_anon'] -= 1
    elif fault == 'interval_timestamp': rows[1][1] += 1
    elif fault == 'interval_global_low': rows[1][6] += 1
    elif fault == 'terminal_node_low': rows[-1][3] += 1
    elif fault == 'below_node_minimum': rows[0][3] -= 1
    elif fault == 'mode': last['pressure']['lru_gen_enabled'] = 0
    elif fault == 'old_profile': receipt['profile'] = 'ar-local-host-pressure-v2'
    elif fault == 'endpoint_counter': delta(last, 0, file=1)
    elif fault == 'zero_delta': rows[0][4:6] = [0,0]
    elif fault == 'bool_node': rows[0][2] = False
    with pytest.raises(ValueError): p.require_pressure_receipt(receipt, first, last)


@pytest.mark.parametrize('fault', ['missing','duplicate','order','global_above','global_below','reset',
                                   'hotplug','mask_changed','unknown_mask','bool_mask'])
def test_tracker_rejects_invalid_node_snapshots_and_latches(fault):
    first = two_nodes(); last = next_host(first); value = last['pressure']
    if fault == 'missing': value['node_refaults'].pop()
    elif fault == 'duplicate': value['node_refaults'][1][0] = 0
    elif fault == 'order': value['node_refaults'].reverse()
    elif fault == 'global_above': value['counters']['workingset_refault_file'] += 1
    elif fault == 'global_below': value['node_refaults'][1][2] += 1
    elif fault == 'reset': delta(last, 0, file=-1); delta(last, 1, file=1)
    elif fault == 'hotplug': value['zones'].append(dict(value['zones'][0], node=2));value['node_refaults'].append([2,0,0])
    elif fault == 'mask_changed': value['lru_gen_enabled'] = 7
    elif fault == 'unknown_mask': value['lru_gen_enabled'] = 8
    elif fault == 'bool_mask': value['lru_gen_enabled'] = True
    tracker = p.PressureTracker(first)
    with pytest.raises(ValueError): tracker.observe(last)
    with pytest.raises(ValueError, match='latched'): tracker.observe(next_host(first))


@pytest.mark.parametrize('text', ['','0,0\n','1,0\n','0-64\n','2-1\n','0,,1\n','0-1,1-2\n','0\r\n','true'])
def test_online_inventory_is_bounded_and_canonical(text):
    with pytest.raises(ValueError): p.online_nodes(text)


@pytest.mark.parametrize('fault', ['node_above','node_below','after_refault','after_reset','mode_change',
    'hotplug','missing_node','missing_mode','unknown_mode','allocation_during_capture','node_zone_mismatch'])
def test_single_capture_never_masks_incoherence_or_pressure(tmp_path, monkeypatch, fault):
    memory, vm = proc_fixture(tmp_path)
    sysfs = tmp_path/'sysfs'
    monkeypatch.setattr(p.os, 'sysconf', lambda name:16384, raising=False)
    original = p.bounded_text; counts = {}
    def reader(path, limit):
        name = str(path).replace('\\','/'); counts[name] = counts.get(name,0) + 1
        text = original(path, limit)
        if name.endswith('node0/vmstat'):
            if fault == 'node_above': return text.replace('refault_file 0', 'refault_file 1')
            if fault == 'node_below': return text.replace('refault_file 0', 'refault_file -1')
        if name.endswith('/vmstat') and 'node0' not in name:
            if fault == 'after_refault': return text.replace('refault_file 0', 'refault_file 1')
            if fault == 'after_reset': return text.replace('pgmajfault 1', 'pgmajfault 0')
            if fault == 'allocation_during_capture': return text.replace('allocstall_dma 0', 'allocstall_dma 1')
        if name.endswith('/enabled') and counts[name] == 2 and fault == 'mode_change': return '0x0007\n'
        if name.endswith('/online') and counts[name] == 2 and fault == 'hotplug': return '0-1\n'
        return text
    if fault == 'after_reset':
        vm = vm.replace('pgmajfault 0','pgmajfault 1');(tmp_path/'vmstat').write_text(vm)
    if fault == 'missing_node': (sysfs/'devices/system/node/node0/vmstat').unlink()
    if fault == 'missing_mode': (sysfs/'kernel/mm/lru_gen/enabled').unlink()
    if fault == 'unknown_mode': (sysfs/'kernel/mm/lru_gen/enabled').write_bytes(b'0x0008\n')
    if fault == 'node_zone_mismatch': (sysfs/'devices/system/node/online').write_bytes(b'0-1\n')
    monkeypatch.setattr(p, 'bounded_text', reader)
    with pytest.raises((ValueError,OSError)): p.sample_pressure(tmp_path,memory,vm,sysfs=sysfs)
    assert all(n <= 2 for n in counts.values())  # No retry resets the capture deadline.


def test_capacity_is_node_rows_not_intervals_and_never_truncates(monkeypatch):
    monkeypatch.setattr(p,'MAX_REFAULT_EVENTS',1)
    first=two_nodes();last=next_host(first);delta(last,0,file=1);delta(last,1,file=1)
    tracker=p.PressureTracker(first)
    with pytest.raises(ValueError,match='capacity'):tracker.observe(last)
    assert tracker.receipt()['refault_events']==[] and tracker.receipt()['result']=='FAIL'


def test_worst_case_64_nodes_obeys_existing_receipt_byte_budget():
    rows=[[p.MAX_VALUE,p.MAX_VALUE,node,-p.MAX_VALUE,p.MAX_VALUE,p.MAX_VALUE,-p.MAX_VALUE] for node in range(64)]
    def size(value):return len(json.dumps({'pressure_evidence':{'host':{'refault_events':value}}},indent=2))
    assert size(rows)-size([]) <= 64*384
    assert p.MAX_REFAULT_EVENTS*384 <= 32*1024**2


@pytest.mark.parametrize('counter', p.PRESSURE_COUNTERS)
def test_closing_capture_read_cannot_hide_any_new_allocation_pressure(tmp_path, monkeypatch, counter):
    memory, vm = proc_fixture(tmp_path)
    monkeypatch.setattr(p.os, 'sysconf', lambda name:16384, raising=False)
    (tmp_path/'vmstat').write_bytes(vm.replace(counter+' 0\n', counter+' 1\n').encode('ascii'))
    with pytest.raises(ValueError, match='allocation_pressure_during_capture'):
        p.sample_pressure(tmp_path, memory, vm, sysfs=tmp_path/'sysfs')
