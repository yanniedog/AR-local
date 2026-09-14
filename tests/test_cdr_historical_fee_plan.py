"""Disposable plan/ledger mechanisms only; no May23 banking acceptance."""
from __future__ import annotations

import copy
import io
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

import cdr_historical_fee_plan as planmod
import cdr_historical_fee_plan_candidate as controller
from cdr_historical_fee_archive import read_exact, inspect_archive
from cdr_historical_fee_exact import decode, encode, sha
from cdr_historical_fee_ledger import Ledger
from cdr_historical_fee_ledger_io import canonical, digest, read_control
from cdr_historical_fee_plan_budget import CONTROL, LIMITS, ControlBudget, PhaseBudget, exact_meter


def budget():
    return PhaseBudget(deadline=time.monotonic() + 30)


def protocol_inputs(tmp_path):
    meter = ControlBudget(deadline=time.monotonic() + 30)
    reviewed = planmod.registry(meter)
    root = Path(planmod.__file__).parent
    code = {}
    for name in planmod.CODE_FILES:
        body = (root / name).read_bytes()
        code[name] = {'bytes': len(body), 'sha256': digest(body), 'lf_sha256': digest(body.replace(b'\r\n', b'\n'))}
    paths = {key: str(tmp_path / key) for key in planmod.PATHS}
    for key in ('ledger', 'archive', 'anchor'):
        Path(paths[key]).mkdir()
    plan = {'schema_version': 1, 'registry_sha256': planmod.REGISTRY_SHA,
            'work_id': planmod.work_id(reviewed), 'code': code, 'paths': paths,
            'limits': copy.deepcopy(reviewed['budgets']), 'dependency_commits': dict(planmod.DEPENDENCIES)}
    approval = {'schema_version': 1, 'kind': 'ROOT_APPROVED_SINGLE_LOCAL_ATTEMPT',
                'plan_sha256': digest(canonical(plan)), 'work_id': plan['work_id'],
                'attempt_id': str(uuid4()), 'budget_scope_id': str(uuid4()), 'approval_id': str(uuid4()),
                'owner': {'instance_id': str(uuid4()), 'boot_id': str(uuid4()), 'pid': os.getpid(),
                          'process_start': 'DISPOSABLE_PROTOCOL_ONLY', 'executable_sha256': 'a' * 64},
                'prior_scopes': []}
    return plan, approval, reviewed


def protocol_verifier(plan_body, approval_body, *, control=None):
    """Deliberate local trust stub; never acceptance of an operator grant."""
    plan, approval = json.loads(plan_body), json.loads(approval_body)
    return planmod.TrustedAttestation(digest(plan_body), digest(approval_body), plan['paths']['ledger'],
                                      digest(canonical(approval['owner'])), 'b' * 64, 660)


def protocol_candidate(paths, plan, approval, phase, schema):
    phase.read(io.BytesIO(b'transport only'), 14, 'verified_read')
    receipt = {'work_id': plan['work_id'], 'plan_sha256': approval['plan_sha256'],
               'observation_date': '2026-05-23', 'publication': 'NOT_ATTEMPTED',
               'result': 'CANDIDATE_SEALED_UNREVIEWED'}
    body = encode(receipt)
    return {'candidate_receipt': {'bytes': len(body), 'sha256': digest(body)},
            'candidate_receipt_value': receipt, 'phase_counters_final': phase.snapshot()}


def test_no_authority_never_opens_source_or_claims_work(tmp_path, monkeypatch):
    plan, approval, _ = protocol_inputs(tmp_path)
    monkeypatch.setattr(controller, '_paths', lambda *_: pytest.fail('admitted paths without authority'))
    with pytest.raises(ValueError, match='trusted_root_canary_verifier_required'):
        controller.execute(canonical(plan), canonical(approval))
    assert not list(Path(plan['paths']['ledger']).iterdir())


@pytest.mark.parametrize('change', ['date', 'parent', 'manifest', 'limit', 'boolean', 'code_extra', 'prior', 'owner'])
def test_strict_registry_plan_and_authority(tmp_path, change):
    plan, approval, reviewed = protocol_inputs(tmp_path)
    if change == 'date': plan['work_id'] = '0' * 64
    if change == 'parent': plan['parent'] = {'kind': 'candidate'}
    if change == 'manifest': plan['registry_sha256'] = '0' * 64
    if change == 'limit': plan['limits']['verified_read_checksum_bytes'] += 1
    if change == 'boolean': plan['schema_version'] = True
    if change == 'code_extra': plan['code']['extra.py'] = next(iter(plan['code'].values()))
    if change == 'prior': approval['prior_scopes'] = [{'unknown': True}]
    if change == 'owner': approval['owner']['boot_id'] = 'malformed'
    approval['plan_sha256'] = digest(canonical(plan))
    with pytest.raises(ValueError):
        planmod.admit(canonical(plan), canonical(approval), reviewed, protocol_verifier)


@pytest.mark.parametrize('field,value', [('outer_timeout_seconds', 659), ('owner_sha256', '0'*64),
                                        ('approval_sha256', '0'*64), ('ledger_root', 'elsewhere')])
def test_trusted_launcher_attestation_is_exact(tmp_path, field, value):
    from dataclasses import replace
    plan, approval, reviewed = protocol_inputs(tmp_path)
    def wrong(a, b, **kwargs):
        return replace(protocol_verifier(a, b), **{field: value})
    with pytest.raises(ValueError, match='attestation'):
        planmod.admit(canonical(plan), canonical(approval), reviewed, wrong)


def test_successful_mechanism_replay_is_metadata_only(tmp_path, monkeypatch):
    plan, approval, _ = protocol_inputs(tmp_path)
    monkeypatch.setattr(controller, '_candidate', protocol_candidate)
    first = controller.execute(canonical(plan), canonical(approval), trusted_verifier=protocol_verifier)
    assert first['status'] == 'SEALED_UNREVIEWED' and not first['due']
    assert first['result']['phase_counters_final'] == {'verified_read': 14}
    monkeypatch.setattr(controller, '_candidate', lambda *_: pytest.fail('body reread on replay'))
    monkeypatch.setattr(controller, '_paths', lambda *_: pytest.fail('source path inspected on replay'))
    assert controller.replay(canonical(plan), canonical(approval)) == first
    assert controller.execute(canonical(plan), canonical(approval), trusted_verifier=protocol_verifier) == first


def test_failure_and_output_rename_cannot_replenish_grant(tmp_path, monkeypatch):
    plan, approval, _ = protocol_inputs(tmp_path)
    def poison(*args):
        args[3].read(io.BytesIO(b'x'), 1, 'verified_read')
        raise RuntimeError('protocol interrupted')
    monkeypatch.setattr(controller, '_candidate', poison)
    with pytest.raises(RuntimeError):
        controller.execute(canonical(plan), canonical(approval), trusted_verifier=protocol_verifier)
    status = controller.replay(canonical(plan), canonical(approval))
    assert status['status'] == 'ACCOUNTING_UNKNOWN' and status['upper_bounds'] == LIMITS and not status['due']
    monkeypatch.setattr(controller, '_candidate', lambda *_: pytest.fail('reused unknown grant'))
    assert controller.execute(canonical(plan), canonical(approval), trusted_verifier=protocol_verifier) == status
    plan['paths']['output'] += '-renamed'
    approval['plan_sha256'] = digest(canonical(plan))
    with pytest.raises(ValueError, match='identity'):
        controller.execute(canonical(plan), canonical(approval), trusted_verifier=protocol_verifier)
    assert len(list(Path(plan['paths']['ledger']).iterdir())) == 1


@pytest.mark.parametrize('failure', ['mkdir', 'pending', 'record', 'head', 'terminal'])
def test_crash_boundaries_preserve_unknown_and_never_retry(tmp_path, monkeypatch, failure):
    import cdr_historical_fee_ledger_io as ledgerio
    plan, approval, _ = protocol_inputs(tmp_path)
    monkeypatch.setattr(controller, '_candidate', protocol_candidate)
    actual_link = ledgerio.os.link
    def fail_link(source, target, **kwargs):
        target = Path(target)
        if ((failure == 'pending' and target.suffix == '.record')
                or (failure == 'record' and target.suffix == '.head')
                or (failure == 'head' and target.name == '002.head')
                or (failure == 'terminal' and target.name == '004.head')):
            raise OSError('protocol link interruption')
        return actual_link(source, target, **kwargs)
    monkeypatch.setattr(ledgerio.os, 'link', fail_link)
    if failure == 'mkdir':
        (Path(plan['paths']['ledger']) / plan['work_id']).mkdir()
    with pytest.raises((OSError, ValueError)):
        controller.execute(canonical(plan), canonical(approval), trusted_verifier=protocol_verifier)
    monkeypatch.setattr(controller, '_candidate', lambda *_: pytest.fail('body execution after crash'))
    with pytest.raises((OSError, ValueError)):
        controller.execute(canonical(plan), canonical(approval), trusted_verifier=protocol_verifier)


def test_pre_read_budget_and_partial_error_charge():
    phase = budget()
    phase.limits['verified_read'] = 3
    assert phase.read(io.BytesIO(b'ab'), 3, 'verified_read') == b'ab'
    assert phase.counts['verified_read'] == 2
    class MustNotRead:
        def read(self, size): pytest.fail('read over budget')
    with pytest.raises(ValueError, match='verified_read_bound'):
        phase.read(MustNotRead(), 2, 'verified_read')
    class FailedRead:
        def read(self, size): raise OSError('unknown amount read')
    with pytest.raises(OSError):
        phase.read(FailedRead(), 1, 'verified_read')
    assert phase.counts['verified_read'] == 3


def test_hash_passes_and_decoded_gzip_count_and_restore():
    from cdr_historical_fee_exact import gzip_bytes
    phase = budget()
    with exact_meter(phase):
        sha(b'abc')
        sha(b'abc')
        assert decode(gzip_bytes(b'{}'), compressed=True, limit=100) == {}
    assert phase.counts['verified_read'] == 8
    sha(b'outside context')
    assert phase.counts['verified_read'] == 8


def test_meter_nested_thread_and_exception_isolation():
    phase = budget()
    with pytest.raises(RuntimeError):
        with exact_meter(phase):
            with pytest.raises(ValueError, match='nested'):
                with exact_meter(budget()): pass
            with ThreadPoolExecutor(max_workers=1) as pool:
                assert pool.submit(sha, b'unrelated thread').result()
            assert not phase.counts
            raise RuntimeError('scope exit')
    with exact_meter(budget()):
        sha(b'another context')


def test_read_exact_reserves_before_actual_archive_stream():
    phase = budget()
    phase.limits['compressed'] = 1
    class NoRead:
        def read(self, size): pytest.fail('archive read before reservation')
    with pytest.raises(ValueError, match='compressed_bound'):
        read_exact(NoRead(), 2, phase, 'compressed')


@pytest.mark.parametrize('kind', ['read_checksum', 'output'])
def test_control_exact_limit_and_one_over(kind):
    meter = ControlBudget(deadline=time.monotonic() + 30)
    meter.charge(kind, CONTROL)
    with pytest.raises(ValueError, match='control_'):
        meter.charge(kind, 1)
    assert meter.counts[kind] == CONTROL


def test_control_reread_bound(tmp_path):
    path = tmp_path / 'metadata'
    path.write_bytes(b'{}\n')
    meter = ControlBudget(deadline=time.monotonic() + 30)
    assert read_control(path, meter) == read_control(path, meter)
    with pytest.raises(ValueError, match='reread'):
        read_control(path, meter)


@pytest.mark.parametrize('value', [True, -1, 0.1])
def test_counter_wrong_types_refused_before_work(value):
    with pytest.raises(ValueError):
        budget().check('output', value)


def test_phase_shared_deadline_and_closed_owner():
    phase = PhaseBudget(deadline=0)
    with pytest.raises(ValueError, match='deadline'):
        phase.read(io.BytesIO(b'x'), 1, 'verified_read')
    phase = budget()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(ValueError, match='owner'):
            pool.submit(phase.check).result()
    phase.closed = True
    with pytest.raises(ValueError, match='lifetime'):
        phase.check()


def test_actual_disposable_archive_uses_one_counted_phase(tmp_path):
    from tests.test_cdr_historical_fee_archive import archive
    path, identity, files = archive(tmp_path)
    phase = budget()
    with exact_meter(phase):
        record = inspect_archive(path, identity, files, {'source': files[0]['path']}, tmp_path / 'cache', phase)
    assert record['status'] == 'MEMBER_VERIFIED'
    assert phase.counts['compressed'] == 2 * identity['bytes']
    assert phase.counts['decoded'] >= sum(row['size'] for row in files)
    assert phase.counts['verified_read'] >= phase.counts['compressed'] + phase.counts['decoded']


@pytest.mark.parametrize('stamp,valid', [('2026-05-22T15:00:00Z', True),
                                        ('2026-05-23T14:00:00Z', False), ('2026-05-23T12:00:00', False)])
def test_may23_generation_uses_hobart_instant_not_public_backfill(stamp, valid):
    from cdr_historical_fee_archive_admission import source_generation
    source = {'sector': 'banks', 'run_date': '2026-05-23', 'generated_at': stamp}
    if valid:
        assert source_generation(source, date='2026-05-23') == stamp
    else:
        with pytest.raises(ValueError):
            source_generation(source, date='2026-05-23')


def test_profile_cannot_be_used_without_admitted_context():
    with pytest.raises(ValueError, match='active_plan'):
        planmod.archive_profile('may23-reviewed-original-anchor-fees-v2')
    with pytest.raises(ValueError, match='unreviewed'):
        planmod.archive_profile({'date': '2026-05-23'})


def test_exact_work_identity_matches_reviewed_design_metadata():
    reviewed = planmod.registry(ControlBudget(deadline=time.monotonic() + 30))
    assert planmod.work_id(reviewed) == '44dac615597cb90dfb36dce84527a62341f22ead6b13aa29216279b7302c7a88'
