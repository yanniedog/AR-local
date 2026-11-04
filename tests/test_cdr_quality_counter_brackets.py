"""Published counter brackets; telemetry fixtures are not business acceptance."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

import pi_cdr_quality_pressure as p
from tests.test_cdr_quality_closing_capture import raw_capture
from tests.test_cdr_quality_pressure import next_host
from tests.test_cdr_quality_refault_nodes import two_nodes


def step(previous, *, known=(0, 0), prefix=(0, 0), tail=(0, 0)):
    """Settle prior tails into healthy node 1 before the next opening read."""
    value = next_host(previous); q = value['pressure']
    before = copy.deepcopy(previous['pressure']['counters'])
    for i in range(2):
        q['node_refaults'][1][i + 1] += p.refault_tail(previous['pressure'])[i] + prefix[i]
    opening = copy.deepcopy(q['node_refaults'])
    for i, key in enumerate(p.REFAULT_COUNTERS):
        q['node_refaults'][1][i + 1] += known[i]
        q['counters'][key] = sum(row[i + 1] for row in q['node_refaults']) + tail[i]
    return raw_capture(value, opening, before)


def checked(*samples):
    tracker = p.PressureTracker(samples[0])
    for sample in samples[1:]: tracker.observe(sample)
    result = tracker.receipt()
    p.require_pressure_receipt(result, samples[0], samples[-1])
    return result


def test_actual_r17_bytes_remain_failed_old_profile_new_bracket_is_local_only():
    path = Path(__file__).parent/'fixtures/pressure-r17-failed-capture.json'
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == 'a6b534492ba88248294544abc07195fcc1474fbe0c67da7d215655c71d053482'
    original = json.loads(raw)
    with pytest.raises(ValueError, match='profile'): p.validate_snapshot(original)
    value = copy.deepcopy(original); value['profile'] = p.PROFILE
    p.validate_snapshot(value)
    capture = value['capture']; key = 'workingset_refault_file'
    assert [capture['global_before'][key], sum(row[2] for row in capture['nodes_before']),
            sum(row[2] for row in capture['nodes_after']), capture['global_after'][key]] == [183983,183983,183988,184005]
    assert p.refault_tail(value) == [0,17]
    p.require_initial_capture(value)
    value['zones'][0]['pages free'] = value['zones'][0]['low']
    with pytest.raises(ValueError, match='initial_refault'): p.require_initial_capture(value)
    assert original['profile'] == 'ar-local-host-pressure-v4'


@pytest.mark.parametrize('tail', [(17,0),(0,17),(13,17)])
def test_tail_only_then_settlement_keeps_distinct_global_and_node_totals(tail):
    first = raw_capture(two_nodes()); middle = step(first, tail=tail); last = step(middle)
    result = checked(first, middle, last)
    assert len(result['refault_snapshots']) == len(result['refault_intervals']) == 2
    assert len(result['refault_events']) == 1
    assert result['refault_intervals'][0][3:5] == list(tail)
    assert result['refault_intervals'][1][3:5] == [0,0]
    assert result['node_cumulative']['1'] == list(tail)
    initial_tail = checked(middle, last)
    assert [initial_tail['cumulative'][k] for k in p.REFAULT_COUNTERS] == [0,0]
    assert initial_tail['node_cumulative']['1'] == list(tail)
    assert initial_tail['node_maximum_interval']['1'] == list(tail)
    assert [initial_tail['maximum_interval'][k] for k in p.REFAULT_COUNTERS] == [0,0]


@pytest.mark.parametrize('mask',[0,1,2,3,4,5,6,7])
@pytest.mark.parametrize('phase',['initial_prefix','initial_tail','tail_only','settlement'])
def test_unknown_attribution_fails_any_low_zone_even_with_zero_global_delta(mask, phase):
    first = raw_capture(two_nodes(mask)); tail = (0,17)
    if phase.startswith('initial'):
        value = step(first, prefix=tail if phase=='initial_prefix' else (0,0),
                     tail=tail if phase=='initial_tail' else (0,0))
        value['pressure']['zones'][0]['pages free'] = 300
        with pytest.raises(p.PressureCaptureError,match='initial_refault') as error:
            p.PressureTracker(value)
    else:
        if phase=='settlement': first = step(first,tail=tail)
        value = step(first,tail=tail if phase=='tail_only' else (0,0))
        value['pressure']['zones'][0]['pages free'] = 300
        tracker = p.PressureTracker(first)
        with pytest.raises(p.PressureCaptureError,match='low_with_refault') as error: tracker.observe(value)
        assert tracker.receipt()['low_with_activity_samples'] == 1
        assert tracker.receipt()['low_with_refault_samples'] == 1
    assert error.value.capture == value['pressure']


@pytest.mark.parametrize('fault',['before_above_A','after_below_B','node_reset_offset','global_reset',
                                  'missing_node','duplicate_node','mode','clock','hard'])
def test_outside_bracket_and_existing_safeguards_fail_closed(fault):
    first = raw_capture(two_nodes()); last = step(first,known=(3,5),tail=(4,17))
    q=last['pressure']; c=q['capture']
    if fault=='before_above_A': c['global_before']['workingset_refault_file'] += 1
    elif fault=='after_below_B':
        q['counters']['workingset_refault_file'] -= 18
        c['global_after']['workingset_refault_file'] -= 18
    elif fault=='node_reset_offset': c['nodes_before'][0][2]+=1;c['nodes_before'][1][2]-=1
    elif fault=='global_reset': c['global_before']['pgmajfault']+=1
    elif fault=='missing_node': c['nodes_before'].pop()
    elif fault=='duplicate_node': c['nodes_before'][1][0]=0
    elif fault=='mode':q['lru_gen_enabled']=0
    elif fault=='clock':q['read_elapsed_ns']=200_000_000
    else:q['counters']['oom_kill']+=1;c['global_after']['oom_kill']+=1
    with pytest.raises(ValueError):p.PressureTracker(first).observe(last)


@pytest.mark.parametrize('fault',['omit_interval','omit_source','omit_both','reverse','duplicate','negative',
                                  'bool','carry','global','global_peak','node_peak','source_tail','orphan','skip_carry'])
def test_uncertainty_ledger_and_raw_source_tampering_rejected(fault):
    first=raw_capture(two_nodes()); middle=step(first,tail=(3,17)); last=step(middle)
    result=checked(first,middle,last); rows=result['refault_intervals']; sources=result['refault_snapshots']
    if fault=='omit_interval':rows.pop(0)
    elif fault=='omit_source':sources.pop(0)
    elif fault=='omit_both':rows.pop(0);sources.pop(0)
    elif fault=='reverse':rows.reverse();sources.reverse()
    elif fault=='duplicate':rows.append(copy.deepcopy(rows[0]));sources.append(copy.deepcopy(sources[0]))
    elif fault=='negative':rows[0][7]=-1
    elif fault=='bool':rows[0][5]=False
    elif fault=='carry':rows[1][6]=0
    elif fault=='global':result['cumulative']['workingset_refault_file']+=1
    elif fault=='global_peak':result['maximum_interval']['workingset_refault_file']=16
    elif fault=='node_peak':result['node_maximum_interval']['1'][1]=16
    elif fault=='source_tail':
        q=sources[0]['pressure'];q['counters']['workingset_refault_file']-=1;q['capture']['global_after']['workingset_refault_file']-=1
        sources[0]['sha256']=p.fingerprint(q)
    elif fault=='orphan':
        rows[0][5:]=[0,0,0,0]
    else:
        result['observations']+=1
        sources[1]['sequence']=3;rows[1][0]=3;result['refault_events'][0][0]=3
    with pytest.raises(ValueError):p.require_pressure_receipt(result,first,last)


def test_tail_low_cannot_be_relabelled_pass_after_terminal_recovery():
    first=raw_capture(two_nodes()); middle=step(first,tail=(0,17)); last=step(middle)
    result=checked(first,middle,last)
    source=result['refault_snapshots'][0];source['pressure']['zones'][0]['pages free']=300
    source['sha256']=p.fingerprint(source['pressure'])
    # Forge a healthy row but leave the actual raw low evidence: exact replay rejects.
    result['minimum_zone_margins']['0:Normal']={'min':100,'low':0,'high':-100}
    with pytest.raises(ValueError):p.require_pressure_receipt(result,first,last)
    result['refault_intervals'][0][2]=0
    result['refault_evidence_bytes'] = p.REFAULT_EVIDENCE_OVERHEAD + sum(
        p.evidence_item_bytes(row) for key in ('refault_snapshots','refault_events','refault_intervals') for row in result[key])
    with pytest.raises(ValueError,match='low_conjunction'):p.require_pressure_receipt(result,first,last)


def test_tail_only_capacity_is_checked_before_partial_append_and_receipt_is_independent(monkeypatch):
    first=raw_capture(two_nodes()); last=step(first,tail=(0,17)); result=checked(first,last)
    monkeypatch.setattr(p,'MAX_REFAULT_EVIDENCE_BYTES',result['refault_evidence_bytes']-1)
    tracker=p.PressureTracker(first)
    with pytest.raises(p.PressureCaptureError,match='capacity'):tracker.observe(last)
    assert tracker.refault_snapshots == tracker.refault_intervals == tracker.refault_events == []
    assert tracker.failure
    monkeypatch.setattr(p,'MAX_REFAULT_EVIDENCE_BYTES',result['refault_evidence_bytes'])
    tracker=p.PressureTracker(first);tracker.observe(last)
    altered=tracker.receipt();altered['refault_intervals'][0][7]=99
    assert tracker.receipt()==result
    p.require_pressure_receipt(result,first,last)
