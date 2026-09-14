"""Bootstrap cache protocol fixtures; never open retained banking sources."""
from dataclasses import replace
import io
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

import cdr_historical_fee_plan as planmod
import cdr_historical_fee_plan_candidate as controller
import cdr_historical_fee_ledger_io as ledgerio
from cdr_historical_fee_ledger_io import canonical, read_control
from cdr_historical_fee_plan_budget import CONTROL, ControlBudget
from tests.test_cdr_historical_fee_plan import protocol_inputs, protocol_candidate, protocol_verifier


def prepare(tmp_path, monkeypatch):
    plan, approval, reviewed = protocol_inputs(tmp_path)
    original = Path(planmod.__file__).parent
    root = tmp_path / 'disposable-code'
    for name in (*planmod.CODE_FILES, planmod.REGISTRY):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((original / name).read_bytes())
    monkeypatch.setattr(planmod, '__file__', str(root / 'cdr_historical_fee_plan.py'))
    control = ControlBudget(deadline=time.monotonic() + 30)
    bodies = {name: read_control(root / name, control, limit=1024**2) for name in planmod.CODE_FILES}
    cache = planmod.seal_bootstrap_code(plan, control, bodies)
    return plan, approval, control, cache, root, bodies


def verifier(a, b, *, control, bootstrap_cache):
    assert bootstrap_cache._meter is control
    return replace(protocol_verifier(a, b, control=control), bootstrap_cache_sha256=bootstrap_cache.sha256)


def test_cached_first_pass_has_no_read_then_one_physical_final(tmp_path, monkeypatch):
    plan, _, meter, cache, root, bodies = prepare(tmp_path, monkeypatch)
    before = dict(meter.counts)
    original = planmod.read_control
    monkeypatch.setattr(planmod, 'read_control', lambda *a, **k: pytest.fail('cached physical reread'))
    assert planmod.verify_code(plan, meter, bootstrap_cache=cache) == bodies
    assert meter.counts['read_checksum'] > before['read_checksum']
    assert all(meter.reads[str(root / name)] == 1 for name in planmod.CODE_FILES)
    monkeypatch.setattr(planmod, 'read_control', original)
    assert planmod.verify_code(plan, meter) == bodies
    assert all(meter.reads[str(root / name)] == 2 for name in planmod.CODE_FILES)
    with pytest.raises(ValueError, match='reread'):
        planmod.verify_code(plan, meter)


def test_execute_uses_same_budget_cache_and_original_deadline(tmp_path, monkeypatch):
    plan, approval, meter, cache, root, bodies = prepare(tmp_path, monkeypatch)
    deadline, before = meter.deadline, meter.counts['read_checksum']
    def candidate(paths, plan, approval, phase, schema):
        assert phase.deadline == deadline and meter.deadline == deadline
        assert meter.counts['read_checksum'] > before
        assert schema == bodies['contracts/historical-fees/reviewed-plan-admission-v2.schema.json']
        assert all(meter.reads[str(root / name)] == 1 for name in planmod.CODE_FILES)
        return protocol_candidate(paths, plan, approval, phase, schema)
    monkeypatch.setattr(controller, '_candidate', candidate)
    result = controller.execute(canonical(plan), canonical(approval), trusted_verifier=verifier,
                                control_budget=meter, bootstrap_cache=cache)
    assert result['status'] == 'SEALED_UNREVIEWED'
    assert all(meter.reads[str(root / name)] == 2 for name in planmod.CODE_FILES)
    assert meter.deadline == deadline and meter.counts['read_checksum'] > before


@pytest.mark.parametrize('bad', ['foreign_meter', 'renewed_deadline', 'dict_cache', 'wrong_attestation',
                                'no_attestation', 'omitted_meter'])
def test_foreign_or_unattested_cache_never_runs_body(tmp_path, monkeypatch, bad):
    plan, approval, meter, cache, _, _ = prepare(tmp_path, monkeypatch)
    original_meter = meter
    verify = verifier
    if bad == 'foreign_meter': meter = ControlBudget(deadline=meter.deadline)
    if bad == 'renewed_deadline': meter.deadline += 1
    if bad == 'dict_cache': cache = {'sha256': cache.sha256}
    if bad == 'wrong_attestation':
        def verify(a, b, **kw): return replace(verifier(a, b, **kw), bootstrap_cache_sha256='0' * 64)
    if bad == 'no_attestation':
        def verify(a, b, **kw): return protocol_verifier(a, b)
    if bad == 'omitted_meter': meter = None
    monkeypatch.setattr(controller, '_candidate', lambda *a: pytest.fail('body ran without exact cache grant'))
    with pytest.raises(ValueError):
        controller.execute(canonical(plan), canonical(approval), trusted_verifier=verify,
                           control_budget=meter, bootstrap_cache=cache)
    assert not list(Path(plan['paths']['ledger']).iterdir())
    assert original_meter.counts['read_checksum'] > 0


@pytest.mark.parametrize('change', ['missing', 'extra', 'wrong_body', 'mutable_body', 'read_two',
                                   'missing_receipt', 'changed_file', 'foreign_path'])
def test_cache_construction_rejects_incomplete_or_mismatched_original_reads(tmp_path, monkeypatch, change):
    plan, _, meter, _, root, bodies = prepare(tmp_path, monkeypatch)
    name = sorted(planmod.CODE_FILES)[0]
    path = root / name
    if change == 'missing': bodies.pop(name)
    if change == 'extra': bodies['extra.py'] = b'pass'
    if change == 'wrong_body': bodies[name] = b'x' * len(bodies[name])
    if change == 'mutable_body': bodies[name] = bytearray(bodies[name])
    if change == 'read_two': read_control(path, meter, limit=1024**2)
    if change == 'missing_receipt': meter.completed_reads.pop(str(path))
    if change == 'changed_file': path.write_bytes(bodies[name] + b'\n')
    if change == 'foreign_path': meter.completed_reads[str(path) + '-foreign'] = meter.completed_reads.pop(str(path))
    before = meter.counts['read_checksum']
    with pytest.raises(ValueError): planmod.seal_bootstrap_code(plan, meter, bodies)
    assert meter.counts['read_checksum'] >= before


def test_changed_source_after_cache_stops_before_body_and_preserves_claim(tmp_path, monkeypatch):
    plan, approval, meter, cache, root, _ = prepare(tmp_path, monkeypatch)
    (root / sorted(planmod.CODE_FILES)[0]).write_bytes(b'changed')
    monkeypatch.setattr(controller, '_candidate', lambda *a: pytest.fail('body ran after code change'))
    with pytest.raises(ValueError, match='first_read_receipt'):
        controller.execute(canonical(plan), canonical(approval), trusted_verifier=verifier,
                           control_budget=meter, bootstrap_cache=cache)
    assert (Path(plan['paths']['ledger']) / plan['work_id']).exists()


def test_final_pass_cannot_reuse_cache_after_body_changes_source(tmp_path, monkeypatch):
    plan, approval, meter, cache, root, _ = prepare(tmp_path, monkeypatch)
    name = sorted(planmod.CODE_FILES)[0]
    def candidate(*args):
        result = protocol_candidate(*args)
        (root / name).write_bytes(b'changed after body')
        return result
    monkeypatch.setattr(controller, '_candidate', candidate)
    with pytest.raises(ValueError, match='code_identity'):
        controller.execute(canonical(plan), canonical(approval), trusted_verifier=verifier,
                           control_budget=meter, bootstrap_cache=cache)
    assert meter.reads[str(root / name)] == 2
    assert (Path(plan['paths']['ledger']) / plan['work_id']).exists()


def test_expired_original_budget_never_renews_for_execute(tmp_path, monkeypatch):
    plan, approval, meter, cache, _, _ = prepare(tmp_path, monkeypatch)
    original_deadline = meter.deadline
    monkeypatch.setattr(time, 'monotonic', lambda: original_deadline)
    monkeypatch.setattr(controller, '_candidate', lambda *a: pytest.fail('expired body'))
    with pytest.raises(ValueError, match='deadline'):
        controller.execute(canonical(plan), canonical(approval), trusted_verifier=verifier,
                           control_budget=meter, bootstrap_cache=cache)
    assert meter.deadline == original_deadline and not list(Path(plan['paths']['ledger']).iterdir())


def test_cached_hash_exhaustion_keeps_charges_and_consumes_cache(tmp_path, monkeypatch):
    plan, _, meter, cache, _, _ = prepare(tmp_path, monkeypatch)
    meter.counts['read_checksum'] = CONTROL
    with pytest.raises(ValueError, match='bound'):
        planmod.verify_code(plan, meter, bootstrap_cache=cache)
    assert meter.counts['read_checksum'] == CONTROL
    with pytest.raises(ValueError, match='lifetime'):
        planmod.verify_code(plan, meter, bootstrap_cache=cache)


def test_cache_cannot_cross_owner_thread(tmp_path, monkeypatch):
    plan, _, meter, cache, _, _ = prepare(tmp_path, monkeypatch)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(ValueError, match='owner'):
            pool.submit(planmod.verify_code, plan, meter, bootstrap_cache=cache).result()


def test_short_or_failed_read_is_not_registered_success(tmp_path, monkeypatch):
    from contextlib import contextmanager
    path = tmp_path / 'protocol-source'
    path.write_bytes(b'abcd')
    meter = ControlBudget(deadline=time.monotonic() + 30)
    real = ledgerio.stable_file
    @contextmanager
    def short(path):
        with real(path) as stream:
            class Read:
                def fileno(self): return stream.fileno()
                def read(self, size): return stream.read(1)
            yield Read()
    monkeypatch.setattr(ledgerio, 'stable_file', short)
    with pytest.raises(ValueError, match='short_read'): read_control(path, meter)
    assert meter.counts['read_checksum'] == 4 and meter.reads[str(path)] == 1
    assert str(path) not in meter.completed_reads


def test_trusted_bootstrap_bridge_preserves_all_debits_and_first_identity(tmp_path, monkeypatch):
    plan, _, old, _, root, bodies = prepare(tmp_path, monkeypatch)
    meter = ControlBudget(deadline=old.deadline)
    meter.counts.update(old.counts)
    meter.reads.update(old.reads)
    failed = 'failed-bootstrap-control'
    meter.admit_read(failed, 65536)  # failed maximum stays reserved, no receipt
    for name in planmod.CODE_FILES:
        path = str(root / name)
        _, identity, size = old.completed_reads[path]
        meter.note_completed_read(path, identity, size)
    before = meter.counts['read_checksum']
    cache = planmod.seal_bootstrap_code(plan, meter, bodies)
    assert cache._meter is meter and meter.deadline == old.deadline
    assert meter.counts['read_checksum'] > before and meter.reads[failed] == 1
    assert failed not in meter.completed_reads


@pytest.mark.parametrize('deadline', [float('nan'), float('inf'), True])
def test_nonfinite_or_boolean_original_deadline_refuses_cache(tmp_path, monkeypatch, deadline):
    plan, _, meter, _, _, bodies = prepare(tmp_path, monkeypatch)
    meter.deadline = deadline
    with pytest.raises(ValueError): planmod.seal_bootstrap_code(plan, meter, bodies)


@pytest.mark.parametrize('read_count', [True, 0, 3])
def test_bootstrap_receipt_requires_exact_admitted_read_count(read_count):
    meter = ControlBudget(deadline=time.monotonic() + 30)
    meter.counts['read_checksum'] = 4
    meter.reads['protocol'] = read_count
    with pytest.raises(ValueError, match='successful_metered'):
        meter.note_completed_read('protocol', (1, 1, 4, 1), 4)
    assert not meter.completed_reads and meter.counts['read_checksum'] == 4
