"""Caller-required profiles cannot be erased by zero-swap legacy relabeling."""
import ast
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest
import pi_cdr_quality_activate as activate
import pi_cdr_quality_pressure as pressure
import pi_cdr_quality_resources as resources
from tests.test_cdr_quality_resources import receipt
from tests.test_cdr_quality_pressure import host, next_host
from tests.test_cdr_quality_pressure_integration import scenario, complete


@pytest.mark.parametrize('profile', [None, 'legacy'])
def test_known_zero_swap_legacy_remains_valid_when_not_requested_as_enhanced(profile):
    resources.require_receipt(receipt(), expected_profile=profile)


@pytest.mark.parametrize('profile', ['', 'unknown', True, {}])
def test_unknown_expected_profile_is_not_an_unspecified_profile(profile):
    with pytest.raises(ValueError, match='unsupported expected'):
        resources.require_receipt(receipt(), expected_profile=profile)


def test_zero_swap_enhanced_receipt_cannot_be_downgraded(scenario):
    value = complete(scenario)
    value['last_host_sample']['swap_out_pages'] = 0
    context = dict(expected_operation=scenario[0], expected_commit='a'*40)
    resources.require_receipt(value, expected_profile='allocation-v1', **context)
    downgraded = copy.deepcopy(value); downgraded['schema'] = resources.SCHEMA
    del downgraded['pressure_evidence']
    resources.require_receipt(downgraded)  # Valid legacy checks alone are insufficient context.
    with pytest.raises(ValueError, match='expected pressure profile'):
        resources.require_receipt(downgraded, expected_profile='allocation-v1', **context)
    with pytest.raises(ValueError, match='expected pressure profile'):
        resources.require_receipt(value, expected_profile='legacy', **context)
    del value['pressure_evidence']
    with pytest.raises((ValueError, KeyError)):
        resources.require_receipt(value, expected_profile='allocation-v1', **context)


@pytest.mark.parametrize('caller', ['canary', 'seal'])
def test_actual_caller_validation_forwards_its_requested_profile_before_writing(caller):
    # Execute the actual finalization/validation statements, substituting only
    # filesystem artifact providers. No systemd/HTTP/Pi process is launched.
    tree = ast.parse(Path(activate.__file__).read_bytes())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == caller)
    start = next(i for i,n in enumerate(function.body)
                 if isinstance(n, ast.ImportFrom) and n.module == 'pi_cdr_quality_resources')
    nodes = function.body[start:-1] if caller == 'canary' else function.body[start:start+2]
    writes = []; value = receipt()
    environment = {'args':SimpleNamespace(operation=Path('/bound-operation'),expected_commit='a'*40),
                   'target':'a'*40,'pressure_profile':'allocation-v1',
                   'canary_result':{'pressure_profile':'allocation-v1','resources':{'path':'/bound-operation/resources.json'}},
                   'checked':lambda entry:Path(entry['path']),
                   'read':lambda path:copy.deepcopy(value) if path.name == 'resources.json' else {'result':'PASS'},
                   'record':lambda path:{'path':str(path),'sha256':'b'*64},
                   'write':lambda path,result:writes.append((path,result))}
    with pytest.raises(ValueError, match='expected pressure profile'):
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'actual-profile-finalization','exec'),environment)
    assert not writes


def in_range_sequence_gap():
    first = host(); tracker = pressure.PressureTracker(first); current = first
    for seq in range(1,5):
        current = next_host(current)
        if seq in (1,3):
            current['pressure']['counters']['workingset_refault_file'] += 1
            current['pressure']['node_refaults'][0][2] += 1
        tracker.observe(current)
    summary = tracker.receipt();pressure.require_pressure_receipt(summary,first,current)
    # Sequence 2 is within 1..4, but its unchanged timestamp spans two sample
    # intervals after sequence 1. Keep source/event sequence bindings aligned
    # so the target timing-coverage predicate, not an unrelated bound, rejects it.
    summary['refault_events'][1][0] = 2
    summary['refault_snapshots'][1]['sequence'] = 2
    return summary, first, current


def test_in_range_sequence_time_gap_reaches_coverage_predicate():
    summary, first, last = in_range_sequence_gap()
    assert 1 < summary['refault_events'][1][0] <= summary['observations']-1
    with pytest.raises(ValueError, match='pressure_refault_event_coverage'):
        pressure.require_pressure_receipt(summary,first,last)


def test_sequence_gap_control_detects_removal_of_target_predicate(monkeypatch):
    tree = ast.parse(Path(pressure.__file__).read_bytes())
    function = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name == 'require_refault_events')
    changes = 0
    for node in ast.walk(function):
        if isinstance(node,ast.If) and isinstance(node.test,ast.BoolOp) and 'intervals > 0' in ast.unparse(node.test):
            node.test = ast.parse('not intervals > 0',mode='eval').body;changes += 1
    assert changes == 1
    namespace = dict(vars(pressure))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),
                 'coverage-mutation-control','exec'),namespace)
    summary, first, last = in_range_sequence_gap()
    monkeypatch.setattr(pressure,'require_refault_events',namespace['require_refault_events'])
    pressure.require_pressure_receipt(summary,first,last)
