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
