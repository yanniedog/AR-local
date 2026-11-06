"""Moving telemetry is permitted only with coherent, replayable closing reads."""
import copy

import pytest

import pi_cdr_quality_pressure as p
from tests.test_cdr_quality_pressure import next_host, proc_fixture
from tests.test_cdr_quality_refault_nodes import two_nodes, delta


def raw_capture(value, opening=None, global_before=None):
    q = value['pressure']
    q['capture'] = {
        'global_before': copy.deepcopy(global_before if global_before is not None else q['counters']),
        'nodes_before': copy.deepcopy(opening if opening is not None else q['node_refaults']),
        'nodes_after': copy.deepcopy(q['node_refaults']),
        'global_after': copy.deepcopy(q['counters']),
    }
    return value


def moving(first, node=1, count=5):
    last = next_host(first)
    opening = copy.deepcopy(last['pressure']['node_refaults'])
    before = copy.deepcopy(last['pressure']['counters'])
    delta(last, node, file=count)
    return raw_capture(last, opening, before)


def verify(first, last):
    tracker = p.PressureTracker(first)
    tracker.observe(last)
    receipt = tracker.receipt()
    p.require_pressure_receipt(receipt, first, last)
    return receipt


def test_closing_reads_accept_monotone_motion_without_quiescence():
    first = raw_capture(two_nodes())
    last = moving(first)
    last['pressure']['zones'][0]['pages free'] = 250
    receipt = verify(first, last)
    assert receipt['node_cumulative']['1'] == [0, 5]
    assert receipt['cumulative']['workingset_refault_file'] == 5
    assert receipt['refault_snapshots'][0]['pressure']['capture'] == last['pressure']['capture']


@pytest.mark.parametrize('mask,node', [(3, 0), (0, 1)])
def test_closing_motion_low_refault_is_recorded_not_fatal(mask, node):
    first = raw_capture(two_nodes(mask))
    last = moving(first, node)
    last['pressure']['zones'][0]['pages free'] = 250
    tracker = p.PressureTracker(first)
    tracker.observe(last)
    assert tracker.receipt()['result'] == 'PASS'
    assert tracker.receipt()['low_with_refault_samples'] >= 1


@pytest.mark.parametrize('fault', ['sum', 'node_reset_offset', 'global_reset', 'hard_increment',
                                  'node_binding', 'global_binding', 'missing_raw', 'old_profile'])
def test_invalid_closing_capture_rejected_independently(fault):
    first = raw_capture(two_nodes())
    last = moving(first)
    q = last['pressure']; raw = q['capture']
    if fault == 'sum':
        q['counters']['workingset_refault_file'] -= 1
        raw['global_after']['workingset_refault_file'] -= 1
    elif fault == 'node_reset_offset':
        raw['nodes_before'][0][2] += 1
        raw['nodes_before'][1][2] = 0
    elif fault == 'global_reset': raw['global_before']['pgmajfault'] += 1
    elif fault == 'hard_increment': raw['global_before']['allocstall_normal'] -= 1
    elif fault == 'node_binding': raw['nodes_after'][1][2] += 1
    elif fault == 'global_binding': raw['global_after']['pgmajfault'] += 1
    elif fault == 'missing_raw': del q['capture']
    elif fault == 'old_profile': q['profile'] = 'ar-local-host-pressure-v3'
    with pytest.raises(ValueError): p.validate_snapshot(q)
    with pytest.raises(ValueError): p.PressureTracker(first).observe(last)


@pytest.mark.parametrize('field', ['node', 'global', 'hard'])
def test_opening_reset_cannot_be_hidden_by_closing_recovery(field):
    first = raw_capture(two_nodes()); last = moving(first)
    raw = last['pressure']['capture']
    if field == 'node':
        raw['nodes_before'][0][2] -= 1
        raw['nodes_before'][1][2] += 1
    elif field == 'global': raw['global_before']['pgmajfault'] -= 1
    else:
        raw['global_before']['allocstall_normal'] += 1
        raw['global_after']['allocstall_normal'] += 1
        last['pressure']['counters']['allocstall_normal'] += 1
    p.validate_snapshot(last['pressure'])
    with pytest.raises(ValueError): p.PressureTracker(first).observe(last)


@pytest.mark.parametrize('kind', ['same_node', 'classic', 'pre_A_unknown'])
def test_initial_low_movement_is_recorded_not_fatal(kind):
    initial = raw_capture(two_nodes(0 if kind == 'classic' else 3))
    initial['pressure']['zones'][0]['pages free'] = 250
    initial = moving(initial, 0 if kind == 'same_node' else 1)
    if kind == 'pre_A_unknown':
        # G0 precedes the event, but A already sees it on the healthy node.
        initial['pressure']['capture']['nodes_before'] = copy.deepcopy(initial['pressure']['node_refaults'])
    p.validate_snapshot(initial['pressure'])
    assert p.require_initial_capture(initial['pressure']) is True
    tracker = p.PressureTracker(initial)
    assert tracker.receipt()['initial_low_with_refault'] is True


def test_initial_healthy_motion_and_terminal_only_motion_are_replayed():
    initial = moving(raw_capture(two_nodes()))
    initial['pressure']['zones'][0]['pages free'] = 250
    last = moving(initial, 1, 3)
    receipt = verify(initial, last)
    assert receipt['node_cumulative']['1'] == [0, 3]
    assert initial['pressure']['capture']['nodes_before'][1][2] == 0
    # Replacing initial evidence with unknown attribution is independently rejected.
    initial['pressure']['capture']['nodes_before'] = copy.deepcopy(initial['pressure']['node_refaults'])
    receipt['baseline_sha256'] = p.fingerprint(initial['pressure'])
    assert p.require_initial_capture(initial['pressure']) is True
    # The recorded initial flag is recomputed from the bound baseline.
    assert receipt['initial_low_with_refault'] is False
    with pytest.raises(ValueError, match='initial_low_refault'):
        p.require_pressure_receipt(receipt, initial, last)


@pytest.mark.parametrize('fault', ['opening_node', 'opening_global', 'closing_node', 'closing_global', 'omit', 'reorder'])
def test_intermediate_raw_capture_replay_rejects_forgery(fault):
    first = raw_capture(two_nodes()); middle = moving(first); last = moving(middle)
    tracker = p.PressureTracker(first); tracker.observe(middle); tracker.observe(last)
    receipt = tracker.receipt(); sources = receipt['refault_snapshots']
    raw = sources[0]['pressure']['capture']
    if fault == 'opening_node': raw['nodes_before'][0][2] -= 1
    elif fault == 'opening_global': raw['global_before']['pgmajfault'] -= 1
    elif fault == 'closing_node': raw['nodes_after'][0][2] += 1
    elif fault == 'closing_global': raw['global_after']['pgmajfault'] += 1
    elif fault == 'omit': sources.pop(0)
    elif fault == 'reorder': sources.reverse()
    # A self-hash is not authority to rewrite a sealed artifact.
    for source in sources: source['sha256'] = p.fingerprint(source['pressure'])
    with pytest.raises(ValueError): p.require_pressure_receipt(receipt, first, last)


def test_no_event_gap_still_checks_next_opening_against_prior_closing():
    first = raw_capture(two_nodes()); middle = moving(first)
    quiet = raw_capture(next_host(middle)); last = moving(quiet)
    last['pressure']['capture']['nodes_before'][1][2] -= 1
    last['pressure']['capture']['nodes_before'][0][2] += 1
    delta(last,0,file=1)
    last['pressure']['capture']['nodes_after'] = copy.deepcopy(last['pressure']['node_refaults'])
    last['pressure']['capture']['global_after'] = copy.deepcopy(last['pressure']['counters'])
    tracker = p.PressureTracker(first); tracker.observe(middle); tracker.observe(quiet)
    with pytest.raises(ValueError, match='between_captures'): tracker.observe(last)


def test_closing_times_cannot_hide_overlapping_capture_windows():
    first = raw_capture(two_nodes()); last = moving(first)
    last['pressure']['read_elapsed_ns'] = 200_000_000
    with pytest.raises(ValueError, match='windows_overlap'): p.PressureTracker(first).observe(last)


def test_sampler_order_and_monotone_closing_capture(tmp_path, monkeypatch):
    memory, vm = proc_fixture(tmp_path)
    original = p.bounded_text; calls = []; node_reads = []; global_reads = []
    def reader(path, limit):
        text = original(path, limit)
        if path == tmp_path/'vmstat':
            calls.append('G'); global_reads.append(True)
            if len(global_reads) == 2: text = text.replace('workingset_refault_file 0', 'workingset_refault_file 3')
        elif path == tmp_path/'zoneinfo': calls.append('zones')
        elif path == tmp_path/'sysfs/devices/system/node/node0/vmstat':
            calls.append('N'); node_reads.append(True)
            if len(node_reads) == 2: text = text.replace('workingset_refault_file 0', 'workingset_refault_file 3')
        return text
    monkeypatch.setattr(p, 'bounded_text', reader)
    monkeypatch.setattr(p.os, 'sysconf', lambda _: 16384, raising=False)
    q = p.sample_pressure(tmp_path, memory, vm, sysfs=tmp_path/'sysfs')
    assert calls == ['G', 'zones', 'N', 'N', 'G']
    assert q['capture']['nodes_before'] == [[0, 0, 0]]
    assert q['node_refaults'] == [[0, 0, 3]]
    assert q['counters']['workingset_refault_file'] == 3


def test_failed_complete_capture_retains_bounded_raw_proof(tmp_path, monkeypatch):
    memory, vm = proc_fixture(tmp_path)
    original = p.bounded_text
    def reader(path, limit):
        text = original(path, limit)
        if path == tmp_path/'sysfs/devices/system/node/node0/vmstat':
            return text.replace('workingset_refault_file 0', 'workingset_refault_file 1')
        return text
    monkeypatch.setattr(p, 'bounded_text', reader)
    monkeypatch.setattr(p.os, 'sysconf', lambda _: 16384, raising=False)
    with pytest.raises(p.PressureCaptureError, match='bracket') as result:
        p.sample_pressure(tmp_path, memory, vm, sysfs=tmp_path/'sysfs')
    assert result.value.capture['capture']['nodes_after'] == [[0, 0, 1]]
    assert p.evidence_item_bytes(result.value.capture) < p.MAX_REFAULT_EVIDENCE_BYTES


def test_supervisor_retains_failed_raw_capture_and_cleans_owned_group(tmp_path, monkeypatch):
    import pi_cdr_quality_resources as resources
    cleaned = []
    raw = raw_capture(two_nodes())['pressure']
    monkeypatch.setattr(resources, 'own_cgroup', lambda: tmp_path/'group')
    monkeypatch.setattr(resources, 'members', lambda _: {resources.os.getpid()})
    monkeypatch.setattr(resources, 'zone_snapshot', lambda **_: {})
    def fail(*args, **kwargs): raise p.PressureCaptureError('injected_capture_failure', raw)
    monkeypatch.setattr(resources, 'preflight', fail)
    monkeypatch.setattr(resources, 'terminate', lambda group, child: cleaned.append((group, child)) or True)
    result = resources.supervise(['/not/launched'], tmp_path/'resources.json', resources.Limits())
    assert result['result'] == 'BLOCKED' and result['workload_started'] is False
    assert result['failed_pressure_capture'] == raw
    assert cleaned == [(tmp_path/'group', None)] and result['group_clean'] is True


def test_failed_capture_diagnostic_cannot_accompany_relabelled_success():
    import pi_cdr_quality_resources as resources
    from tests.test_cdr_quality_resources import receipt
    value = receipt()
    resources.require_receipt(value)
    value['failed_pressure_capture'] = {}
    with pytest.raises(ValueError, match='failed pressure capture'):
        resources.require_receipt(value)
