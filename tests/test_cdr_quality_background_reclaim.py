"""Background reclaim is context; allocation pressure remains fail closed."""
import hashlib
import json
from pathlib import Path

import pytest

import pi_cdr_quality_pressure as pressure
from tests.test_cdr_quality_pressure import host, next_host


BACKGROUND_COUNTERS = tuple(
    key for key in pressure.ACTIVITY_COUNTERS if key not in pressure.REFAULT_COUNTERS
)


@pytest.mark.parametrize('counter', BACKGROUND_COUNTERS)
@pytest.mark.parametrize('pages', [1, 1152, 10**12])
def test_low_background_reclaim_has_no_amount_allowance(counter, pages):
    first = host()
    last = next_host(first)
    last['pressure']['zones'][0]['pages free'] = 201
    last['pressure']['counters'][counter] += pages
    tracker = pressure.PressureTracker(first)
    tracker.observe(last)
    receipt = tracker.receipt()
    assert receipt['low_with_activity_samples'] == 1
    assert receipt['low_with_refault_samples'] == 0
    assert receipt['minimum_zone_margins']['0:Normal']['min'] == 1
    assert receipt['cumulative'][counter] == pages
    pressure.require_pressure_receipt(receipt, first, last)


def background_receipt():
    first = host()
    middle = next_host(first)
    middle['pressure']['zones'][0]['pages free'] = 250
    middle['pressure']['counters']['pgscan_kswapd'] += 1
    last = next_host(middle)
    tracker = pressure.PressureTracker(first)
    tracker.observe(middle)
    tracker.observe(last)
    return tracker.receipt(), first, last


@pytest.mark.parametrize('fault', [
    'activity_bool', 'activity_negative', 'activity_over_intervals',
    'activity_over_counter_total', 'refault_bool', 'refault_negative',
    'refault_over_activity', 'refault_without_counter', 'refault_positive',
    'activity_without_low_zone', 'activity_only_refault_hidden',
])
def test_context_counts_are_bounded_and_consistent(fault):
    receipt, first, last = background_receipt()
    pressure.require_pressure_receipt(receipt, first, last)
    if fault == 'activity_bool':
        receipt['low_with_activity_samples'] = True
    elif fault == 'activity_negative':
        receipt['low_with_activity_samples'] = -1
    elif fault == 'activity_over_intervals':
        receipt['low_with_activity_samples'] = 3
    elif fault == 'activity_over_counter_total':
        receipt['low_with_activity_samples'] = 2
    elif fault == 'refault_bool':
        receipt['low_with_refault_samples'] = False
    elif fault == 'refault_negative':
        receipt['low_with_refault_samples'] = -1
    elif fault == 'refault_over_activity':
        receipt['low_with_refault_samples'] = 2
    elif fault in ('refault_without_counter', 'refault_positive'):
        receipt['low_with_refault_samples'] = 1
        if fault == 'refault_positive':
            last['pressure']['counters']['workingset_refault_file'] += 1
            receipt['cumulative']['workingset_refault_file'] = 1
            receipt['maximum_interval']['workingset_refault_file'] = 1
            receipt['last_sha256'] = pressure.fingerprint(last['pressure'])
    elif fault == 'activity_without_low_zone':
        last['pressure']['zones'][0]['pages free'] = 5000
        receipt['minimum_zone_margins'] = pressure.margins(last['pressure']['zones'])
        receipt['last_sha256'] = pressure.fingerprint(last['pressure'])
    elif fault == 'activity_only_refault_hidden':
        last['pressure']['counters']['pgscan_kswapd'] -= 1
        last['pressure']['counters']['workingset_refault_file'] += 1
        for name in ('cumulative', 'maximum_interval'):
            receipt[name]['pgscan_kswapd'] = 0
            receipt[name]['workingset_refault_file'] = 1
        receipt['last_sha256'] = pressure.fingerprint(last['pressure'])
    with pytest.raises(ValueError):
        pressure.require_pressure_receipt(receipt, first, last)


def test_one_interval_context_cannot_be_hidden():
    first = host()
    last = next_host(first)
    last['pressure']['zones'][0]['pages free'] = 250
    last['pressure']['counters']['pgscan_file'] += 1
    tracker = pressure.PressureTracker(first)
    tracker.observe(last)
    receipt = tracker.receipt()
    receipt['low_with_activity_samples'] = 0
    with pytest.raises(ValueError, match='low_activity_context'):
        pressure.require_pressure_receipt(receipt, first, last)


def test_background_context_survives_later_above_low_sample():
    receipt, first, last = background_receipt()
    last = next_host(last)
    last['pressure']['zones'][0]['pages free'] = 5000
    tracker = pressure.PressureTracker(first)
    middle = next_host(first)
    middle['pressure']['zones'][0]['pages free'] = 250
    middle['pressure']['counters']['pgscan_kswapd'] += 1
    tracker.observe(middle)
    tracker.observe(last)
    receipt = tracker.receipt()
    assert receipt['low_with_activity_samples'] == 1
    assert receipt['low_with_refault_samples'] == 0
    pressure.require_pressure_receipt(receipt, first, last)


def test_retained_r11_failure_cannot_be_reinterpreted():
    # Exact extracted host evidence, not a synthesized enhanced receipt.
    path = Path(__file__).parent / 'fixtures' / 'pressure-r11-v1-failed.json'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        'be572994aa044b069ca289c0acdcabafa3f40097b831fad4c00e2b943cf3a3f8'
    )
    evidence = json.loads(path.read_text(encoding='utf-8'))
    assert evidence['source_observation_sha256'] == (
        'e27229790b14ce028b7d39e2510059eab2b6365e307ac0b0dbc1d651de1447a2'
    )
    receipt = evidence['host_receipt']
    assert evidence['resources_result'] == receipt['result'] == 'FAIL'
    assert receipt['profile'] == 'ar-local-host-pressure-v1'
    assert receipt['failure'] == 'host_zone_low_with_reclaim_or_refault'
    assert receipt['low_with_activity_samples'] == 1
    assert receipt['cumulative']['pgscan_kswapd'] == 1152
    with pytest.raises(ValueError, match='pressure_profile_or_boot'):
        pressure.require_pressure_receipt(
            receipt, evidence['baseline_host'], evidence['last_host']
        )
    # Merely relabeling result cannot make the old evidence acceptable.
    relabelled = {**receipt, 'result': 'PASS', 'failure': None}
    with pytest.raises(ValueError):
        pressure.require_pressure_receipt(
            relabelled, evidence['baseline_host'], evidence['last_host']
        )


def test_old_host_summary_rejected_with_new_valid_snapshots():
    receipt, first, last = background_receipt()
    receipt['profile'] = 'ar-local-host-pressure-v1'
    with pytest.raises(ValueError, match='successful_pressure_profile_required'):
        pressure.require_pressure_receipt(receipt, first, last)


def refault_receipt(*, final_low=False):
    first = host()
    middle = next_host(first)
    middle['pressure']['counters']['workingset_refault_file'] += 1
    last = next_host(middle)
    last['pressure']['counters']['workingset_refault_file'] += 1
    last['pressure']['counters']['pgscan_file'] += 1
    if final_low:
        last['pressure']['zones'][0]['pages free'] = 250
    tracker = pressure.PressureTracker(first)
    tracker.observe(middle)
    if final_low:
        with pytest.raises(ValueError, match='low_with_refault'):
            tracker.observe(last)
    else:
        tracker.observe(last)
    return tracker.receipt(), first, last


def test_multi_interval_refault_cannot_be_hidden_by_zeroing_summary():
    receipt, first, last = refault_receipt(final_low=True)
    assert receipt['cumulative']['workingset_refault_file'] == 2
    assert receipt['maximum_interval']['workingset_refault_file'] == 1
    receipt.update(result='PASS', failure=None, low_with_refault_samples=0)
    # The old aggregate checks alone accepted this exact combination.
    pressure.require_low_activity_counts(receipt, pressure.margins(last['pressure']['zones']), 3)
    with pytest.raises(ValueError, match='refault_event_low_conjunction'):
        pressure.require_pressure_receipt(receipt, first, last)


def test_intermediate_low_refault_cannot_be_hidden_by_healthy_endpoint():
    receipt, first, failed = refault_receipt(final_low=True)
    last = next_host(failed)
    last['pressure']['zones'][0]['pages free'] = 5000
    # A live tracker is latched and cannot produce this forged continuation.
    # Independent receipt validation must also reject the retained bad interval.
    receipt.update(result='PASS', failure=None, low_with_refault_samples=0,
                   observations=4, last_monotonic_ns=last['pressure']['monotonic_ns'],
                   last_sha256=pressure.fingerprint(last['pressure']))
    with pytest.raises(ValueError, match='refault_event_low_conjunction'):
        pressure.require_pressure_receipt(receipt, first, last)


@pytest.mark.parametrize('fault', [
    'omitted', 'duplicate', 'reordered', 'shape', 'zero_delta', 'negative_delta',
    'missing_delta', 'bool_sequence', 'sequence_gap', 'time_reversed',
    'time_after_terminal', 'terminal_low', 'below_minimum_low', 'altered_delta',
])
def test_sparse_refault_evidence_rejects_tampering(fault):
    receipt, first, last = refault_receipt()
    pressure.require_pressure_receipt(receipt, first, last)
    rows = receipt['refault_events']
    if fault == 'omitted':
        rows.pop(0)
    elif fault == 'duplicate':
        rows[1] = list(rows[0])
    elif fault == 'reordered':
        rows.reverse()
    elif fault == 'shape':
        rows[0] = {}
    elif fault == 'zero_delta':
        rows[0][3:] = [0, 0]
    elif fault == 'negative_delta':
        rows[0][4] = -1
    elif fault == 'missing_delta':
        rows[0].pop()
    elif fault == 'bool_sequence':
        rows[0][0] = True
    elif fault == 'sequence_gap':
        rows[1][0] = 3
    elif fault == 'time_reversed':
        rows[1][1] = rows[0][1]
    elif fault == 'time_after_terminal':
        rows[1][1] += 1
    elif fault == 'terminal_low':
        rows[1][2] += 1
    elif fault == 'below_minimum_low':
        rows[0][2] -= 1
    elif fault == 'altered_delta':
        rows[0][4] += 1
    with pytest.raises(ValueError):
        pressure.require_pressure_receipt(receipt, first, last)


def test_refault_evidence_has_no_row_for_zero_delta_intervals():
    first = host()
    tracker = pressure.PressureTracker(first)
    current = first
    for index in range(1, 8):
        current = next_host(current)
        if index in (2, 5):
            current['pressure']['counters']['workingset_refault_anon'] += 3
        tracker.observe(current)
    receipt = tracker.receipt()
    assert [row[0] for row in receipt['refault_events']] == [2, 5]
    pressure.require_pressure_receipt(receipt, first, current)
    receipt['refault_events'][0][4] = 99
    assert tracker.receipt()['refault_events'][0][4] == 0


def test_refault_evidence_capacity_fails_closed_without_truncation(monkeypatch):
    monkeypatch.setattr(pressure, 'MAX_REFAULT_EVENTS', 2)
    first = host()
    tracker = pressure.PressureTracker(first)
    current = first
    for _ in range(2):
        current = next_host(current)
        current['pressure']['counters']['workingset_refault_file'] += 1
        tracker.observe(current)
    current = next_host(current)
    current['pressure']['counters']['workingset_refault_file'] += 1
    with pytest.raises(ValueError, match='evidence_capacity'):
        tracker.observe(current)
    assert len(tracker.receipt()['refault_events']) == 2
    assert tracker.receipt()['result'] == 'FAIL'
    with pytest.raises(ValueError, match='latched'):
        tracker.observe(next_host(current))


def test_refault_record_size_budget_matches_receipt_serialization():
    row = [pressure.MAX_VALUE, pressure.MAX_VALUE, -pressure.MAX_VALUE,
           pressure.MAX_VALUE, pressure.MAX_VALUE]
    def encoded(rows):
        return json.dumps({'pressure_evidence': {'host': {'refault_events': rows}}}, indent=2)
    per_row = len(encoded([row, row])) - len(encoded([row]))
    assert per_row <= 256
    assert pressure.MAX_REFAULT_EVENTS * per_row < 32 * 1024**2
    assert pressure.MAX_REFAULT_EVENTS > 5400 / .1 + 2


def test_refault_event_inventory_capacity_checked_before_iteration(monkeypatch):
    receipt, first, last = refault_receipt()
    monkeypatch.setattr(pressure, 'MAX_REFAULT_EVENTS', 1)
    with pytest.raises(ValueError, match='event_inventory'):
        pressure.require_pressure_receipt(receipt, first, last)


def test_refault_event_peaks_bound_independently_of_matching_totals():
    first = host()
    middle = next_host(first)
    middle['pressure']['counters']['workingset_refault_file'] += 1
    last = next_host(middle)
    last['pressure']['counters']['workingset_refault_file'] += 3
    tracker = pressure.PressureTracker(first)
    tracker.observe(middle)
    tracker.observe(last)
    receipt = tracker.receipt()
    pressure.require_pressure_receipt(receipt, first, last)
    assert receipt['cumulative']['workingset_refault_file'] == 4
    assert receipt['maximum_interval']['workingset_refault_file'] == 3
    for row in receipt['refault_events']:
        row[4] = 2
    with pytest.raises(ValueError, match='event_counter_binding'):
        pressure.require_pressure_receipt(receipt, first, last)
