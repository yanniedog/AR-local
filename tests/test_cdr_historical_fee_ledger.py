"""Adversarial disposable journal and retained-fixture metering regressions."""
from __future__ import annotations

import copy
import io
import json
import os
import time
from pathlib import Path

import pytest

import cdr_historical_fee_plan_candidate as controller
from cdr_historical_fee_archive import inspect_archive, read_exact
from cdr_historical_fee_exact import decode, encode, sha
from cdr_historical_fee_ledger import Ledger
from cdr_historical_fee_ledger_io import canonical, digest, read_control, write_record
from cdr_historical_fee_plan_budget import CONTROL, LIMITS, ControlBudget, PhaseBudget, exact_meter
from tests.test_cdr_historical_fee_plan import protocol_inputs, protocol_candidate, protocol_verifier, budget


def sealed(tmp_path, monkeypatch):
    plan, approval, reviewed = protocol_inputs(tmp_path)
    monkeypatch.setattr(controller, '_candidate', protocol_candidate)
    result = controller.execute(canonical(plan), canonical(approval), trusted_verifier=protocol_verifier)
    return plan, approval, reviewed, result


@pytest.mark.parametrize('fault', ['extra', 'remove_head', 'rewrite', 'replace_link', 'reorder'])
def test_journal_corruption_never_reenters_body(tmp_path, monkeypatch, fault):
    plan, approval, _, _ = sealed(tmp_path, monkeypatch)
    directory = Path(plan['paths']['ledger']) / plan['work_id']
    head = directory / '002.head'
    if fault == 'extra': (directory / 'unknown').write_bytes(b'preserve')
    if fault == 'remove_head': head.rename(directory / 'lost.head')
    if fault == 'rewrite': head.write_bytes(b'{"malformed":true}\n')
    if fault == 'replace_link':
        body = head.read_bytes()
        head.rename(directory / 'saved-original')
        head.write_bytes(body)
    if fault == 'reorder': (directory / '000.head').write_bytes((directory / '001.head').read_bytes())
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    monkeypatch.setattr(controller, '_candidate', lambda *_: pytest.fail('body admitted after corruption'))
    with pytest.raises((OSError, ValueError)):
        controller.execute(canonical(plan), canonical(approval), trusted_verifier=protocol_verifier)
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}


def test_inventory_bound_precedes_any_record_read(tmp_path, monkeypatch):
    plan, approval, _ = protocol_inputs(tmp_path)
    directory = Path(plan['paths']['ledger']) / plan['work_id']
    directory.mkdir()
    for index in range(385): (directory / str(index)).touch()
    import cdr_historical_fee_ledger as ledger
    monkeypatch.setattr(ledger, 'read_control', lambda *_: pytest.fail('unbounded record read'))
    with pytest.raises(ValueError, match='inventory_bound'):
        controller.replay(canonical(plan), canonical(approval))


@pytest.mark.parametrize('target', ['cache', 'output'])
def test_collision_before_claim_preserves_unrelated_paths(tmp_path, monkeypatch, target):
    plan, approval, _ = protocol_inputs(tmp_path)
    path = Path(plan['paths'][target])
    path.mkdir()
    (path / 'existing').write_bytes(b'untouched')
    monkeypatch.setattr(controller, '_candidate', lambda *_: pytest.fail('body admitted after collision'))
    with pytest.raises(ValueError, match='collision'):
        controller.execute(canonical(plan), canonical(approval), trusted_verifier=protocol_verifier)
    assert (path / 'existing').read_bytes() == b'untouched'
    assert not list(Path(plan['paths']['ledger']).iterdir())


def test_new_plan_does_not_resume_even_a_verified_disposable_cache(tmp_path):
    from tests.test_cdr_historical_fee_archive import archive
    from cdr_historical_fee_archive import Budget
    path, identity, files = archive(tmp_path)
    cache = tmp_path / 'cache'
    inspect_archive(path, identity, files, {'source': files[0]['path']}, cache, Budget())
    before = {p.name: p.read_bytes() for p in cache.iterdir()}
    with pytest.raises(ValueError, match='cache_collision'):
        inspect_archive(path, identity, files, {'source': files[0]['path']}, cache, budget(), allow_resume=False)
    assert before == {p.name: p.read_bytes() for p in cache.iterdir()}


def test_exact_claimed_directory_replacement_refused(tmp_path):
    phase = budget()
    path = tmp_path / 'owned'
    phase.claim_directory(path)
    path.rename(tmp_path / 'retained-original')
    path.mkdir()
    with pytest.raises(ValueError, match='directory_identity_changed'):
        phase.read(io.BytesIO(b'x'), 1, 'verified_read')
    assert not phase.counts


def test_code_mismatch_keeps_reservation_before_no_body(tmp_path, monkeypatch):
    plan, approval, _ = protocol_inputs(tmp_path)
    plan['code']['cdr_historical_fee_exact.py']['sha256'] = '0' * 64
    approval['plan_sha256'] = digest(canonical(plan))
    monkeypatch.setattr(controller, '_candidate', lambda *_: pytest.fail('body admitted under changed code'))
    with pytest.raises(ValueError, match='code_identity'):
        controller.execute(canonical(plan), canonical(approval), trusted_verifier=protocol_verifier)
    assert controller.replay(canonical(plan), canonical(approval))['status'] == 'ACCOUNTING_UNKNOWN'


def test_record_size_preflight_writes_nothing(tmp_path):
    meter = ControlBudget(deadline=time.monotonic() + 30)
    with pytest.raises(ValueError, match='record_byte_bound'):
        write_record(tmp_path, 0, {'too_large': 'x' * 65536}, meter)
    assert not list(tmp_path.iterdir())


def test_bootstrap_and_authentication_share_control_allowance(tmp_path, monkeypatch):
    plan, approval, _ = protocol_inputs(tmp_path)
    meter = ControlBudget(deadline=time.monotonic() + 30)
    meter.charge('read_checksum', CONTROL - 10)
    monkeypatch.setattr(controller, '_candidate', lambda *_: pytest.fail('body over control allowance'))
    with pytest.raises(ValueError, match='control_read_checksum_bound'):
        controller.execute(canonical(plan), canonical(approval), trusted_verifier=protocol_verifier, control_budget=meter)
    assert not list(Path(plan['paths']['ledger']).iterdir())


def test_retained_may13_fee_writer_bytes_identical_under_new_meter():
    from cdr_historical_fee_archive_candidate import _payloads
    from cdr_historical_fee_archive import Budget
    from cdr_historical_fee_exact import gzip_bytes
    path = Path(__file__).parent / 'fixtures/historical-fees-may13/embedded-excerpt.json'
    original = path.read_bytes()
    assert sha(original) == '9e4bc07d29cc32e21d28db638f9298d351f252f121fd44f8c94ef0e4521f8541'
    retained = decode(original)
    loaded = {**retained, 'core_bytes': gzip_bytes(encode(retained['core']))}
    old, old_audit = _payloads(loaded, Budget())
    phase = budget()
    with exact_meter(phase):
        new, new_audit = _payloads(loaded, phase)
    assert new == old and encode(new_audit) == encode(old_audit)
    assert phase.counts['verified_read'] > 0
    assert path.read_bytes() == original


def test_schema_rejects_arbitrary_parent_or_new_authority():
    from jsonschema import Draft202012Validator
    from tests.test_cdr_historical_fee_archive import schema_protocol_value
    path = Path(controller.__file__).parent / 'contracts/historical-fees/reviewed-plan-admission-v2.schema.json'
    schema = json.loads(path.read_bytes())
    value = schema_protocol_value(schema)
    # Pure schema protocol generation is not a real candidate or financial fixture.
    validator = Draft202012Validator(schema)
    # The protocol helper does not populate code's minProperties: bind names here.
    shape = {'bytes': 1, 'sha256': 'a'*64, 'lf_sha256': 'b'*64}
    from cdr_historical_fee_plan import CODE_FILES
    value['source_code'] = {name: dict(shape) for name in CODE_FILES}
    validator.validate(value)
    for target, replacement in (('parent', {'kind': 'candidate'}), ('publication', 'PUBLISHED'),
                                 ('observation_date', '2026-05-24')):
        bad = copy.deepcopy(value)
        bad[target] = replacement
        assert list(validator.iter_errors(bad))


def test_terminal_counter_snapshot_has_no_live_alias(tmp_path, monkeypatch):
    plan, approval, _ = protocol_inputs(tmp_path)
    phases = []
    def candidate(*args):
        phases.append(args[3])
        return protocol_candidate(*args)
    monkeypatch.setattr(controller, '_candidate', candidate)
    result = controller.execute(canonical(plan), canonical(approval), trusted_verifier=protocol_verifier)
    frozen = canonical(result)
    phases[0].counts['verified_read'] += 999
    assert canonical(result) == frozen
    assert canonical(controller.replay(canonical(plan), canonical(approval))) == frozen


def test_pending_fee_dependency_refuses_actual_adapter_before_source_io(monkeypatch):
    import cdr_historical_fee_embedded as fees
    monkeypatch.setattr(fees, 'VARIABLE_ZERO_RULE', 'variable_zero_placeholder_v2')
    monkeypatch.setattr(controller, 'load', lambda *_a, **_kw: pytest.fail('source opened before v3 review'))
    with pytest.raises(ValueError, match='reviewed_fee_v3_dependency_required'):
        controller._candidate({}, {}, {}, budget(), b'{}')
