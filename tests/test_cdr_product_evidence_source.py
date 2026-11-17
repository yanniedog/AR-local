"""Read-only finalized-source proof over captured bodies and technical controls."""
import json
from pathlib import Path
import pytest

from app_payload_product_evidence_contract import canonical
from cdr_product_evidence_source import SourceUnavailable, SourceUnsupported, SourceBudgetExceeded, ReadBudget, safe_path
from tests.product_evidence_finalized_fixture import finalized, open_source


def test_selected_source_verifies_without_lock_or_writes(tmp_path, monkeypatch):
    fixture = finalized(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    from cdr_file_lock import FileLock
    def forbidden(*args, **kwargs): pytest.fail('read-only proof attempted mutation')
    monkeypatch.setattr(FileLock, '__enter__', forbidden); monkeypatch.setattr(Path, 'write_bytes', forbidden)
    source = open_source(fixture); source.recheck()
    assert source.source['observation_state'] == 'partial'
    assert source.database == fixture['exports'] / 'local-cdr.sqlite'
    assert {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('fault,reason', [('missing', 'source_unavailable'), ('pin', 'source_superseded'),
    ('failed', 'source_failed'), ('artifact', 'source_unverified'), ('orphan', 'source_unverified'),
    ('base-pin', 'source_unverified'), ('base-asset', 'source_unverified')])
def test_source_failure_is_explicit_without_adoption(tmp_path, fault, reason):
    f = finalized(tmp_path); pins = {}
    if fault == 'missing': f['pointer'].unlink()
    elif fault == 'pin': pins['pointer'] = '0'*64
    elif fault == 'base-pin': pins['manifest'] = '0'*64
    elif fault == 'failed':
        f['base']['source_observation']['observation_state'] = 'failed'
        (f['root'] / 'manifest.json').write_bytes(canonical(f['base']))
    elif fault == 'artifact':
        db = f['exports'] / 'local-cdr.sqlite'; db.write_bytes(db.read_bytes()+b'changed')
    elif fault == 'base-asset':
        (f['root'] / f['base']['files']['core']['name']).write_bytes(b'x')
    else:
        path = next((f['state'] / 'ledger-v2/events').glob('*/*.json'))
        (path.parent / 'unbound.json').write_bytes(b'{}')
    # Pin retrieval here is itself caller-side I/O, not part of the source helper.
    if fault == 'missing': pins['pointer'] = '0'*64
    with pytest.raises(SourceUnavailable) as caught: open_source(f, **pins)
    assert caught.value.reason == reason


@pytest.mark.parametrize('target', ['pointer', 'base', 'contract'])
def test_future_schema_is_unsupported_not_ready(tmp_path, target):
    f = finalized(tmp_path)
    path = f['pointer'] if target == 'pointer' else f['contract'] if target == 'contract' else f['root'] / 'manifest.json'
    value = json.loads(path.read_bytes()); value['schema_version'] = 999; path.write_bytes(canonical(value))
    with pytest.raises(SourceUnsupported): open_source(f)


def test_recheck_never_rebaselines_changed_selection(tmp_path):
    f = finalized(tmp_path); source = open_source(f)
    f['pointer'].write_bytes(f['pointer'].read_bytes()+b' ')
    for _ in range(2):
        with pytest.raises(SourceUnavailable, match='superseded'): source.recheck()


@pytest.mark.parametrize('field', ['base', 'source', 'pointer', 'selection', 'contract'])
def test_caller_cannot_mutate_verified_binding_in_place(tmp_path, field):
    source = open_source(finalized(tmp_path)); getattr(source, field)['unbound'] = True
    with pytest.raises(SourceUnavailable, match='superseded'): source.recheck()


@pytest.mark.parametrize('target', ['pointer', 'base', 'contract'])
@pytest.mark.parametrize('raw', [b'[]', b'['*2000+b'0'+b']'*2000])
def test_malformed_or_deep_controls_are_explicitly_unverified(tmp_path, target, raw):
    f = finalized(tmp_path)
    path = f['pointer'] if target == 'pointer' else f['contract'] if target == 'contract' else f['root'] / 'manifest.json'
    path.write_bytes(raw)
    with pytest.raises(SourceUnavailable, match='unverified'): open_source(f)


def test_complete_pointer_fallback_is_explicit_and_pinned(tmp_path):
    f = finalized(tmp_path)
    # The selected helper follows current daily policy, but mismatched complete
    # metadata cannot reuse this partial contract even with a new pointer pin.
    observed = json.loads(f['pointer'].read_bytes()); observed['observation_state'] = 'failed'
    f['pointer'].write_bytes(canonical(observed))
    complete = {**observed, 'observation_state': 'complete'}
    (f['pointer'].parent / 'latest-complete.json').write_bytes(canonical(complete))
    from app_payload_product_evidence_contract import digest
    with pytest.raises(SourceUnavailable, match='unverified'): open_source(f, pointer=digest(canonical(complete)))


def test_failed_latest_observation_uses_verified_complete_source_only(tmp_path):
    from app_payload_product_evidence_contract import digest
    f = finalized(tmp_path, observation_state='complete')
    complete_pin = digest(f['pointer'].read_bytes())
    failed = json.loads(f['pointer'].read_bytes()); failed['observation_state'] = 'failed'
    f['pointer'].write_bytes(canonical(failed))
    source = open_source(f, pointer=complete_pin)
    assert source.source['observation_state'] == 'complete'
    failed['schema_version'] = 3; f['pointer'].write_bytes(canonical(failed))
    with pytest.raises(SourceUnsupported): open_source(f, pointer=complete_pin)


def test_latest_complete_cannot_hide_a_partial_contract(tmp_path):
    from app_payload_product_evidence_contract import digest
    f = finalized(tmp_path); original = f['pointer'].read_bytes()
    failed = json.loads(original); failed['observation_state'] = 'failed'
    f['pointer'].write_bytes(canonical(failed))
    (f['pointer'].parent / 'latest-complete.json').write_bytes(original)
    with pytest.raises(SourceUnavailable, match='unverified'): open_source(f, pointer=digest(original))


@pytest.mark.parametrize('path', ['../other', '/absolute', 'a\\b', 'a/./b', 'a//b', 'C:drive', ''])
def test_selected_paths_cannot_escape_or_alias(tmp_path, path):
    with pytest.raises(ValueError): safe_path(tmp_path, path)


def test_source_budget_is_finite_and_not_swallowed(monkeypatch, tmp_path):
    budget = ReadBudget(); budget(size=16*1024**3)
    with pytest.raises(SourceBudgetExceeded): budget(reserve_bytes=1)
    budget = ReadBudget(); budget(entries=100000)
    with pytest.raises(SourceBudgetExceeded): budget(entries=1)
    budget = ReadBudget(); budget.deadline = 0
    with pytest.raises(SourceBudgetExceeded): budget()
    f = finalized(tmp_path)
    monkeypatch.setattr(ReadBudget, '__call__', lambda *a, **k: (_ for _ in ()).throw(SourceBudgetExceeded('bounded stop')))
    with pytest.raises(SourceBudgetExceeded): open_source(f)


def test_actual_retained_count_fits_five_finite_proof_phases_without_renewing_deadline():
    # Measured Nov13 contract: 9,959 artifacts, 2,932,257,882 bytes. Four entry
    # charges/artifact bound capture/hash/sweeps in each normal proof phase.
    # Accounting control only: this does not claim actual I/O/resource acceptance.
    budget = ReadBudget(); deadline = budget.deadline
    for phase in range(1, 6):
        if phase > 1: budget.begin_proof()
        for _ in range(9959): budget(entries=4)
        budget(size=2932257882)
        assert budget.phase == phase and budget.deadline == deadline
    with pytest.raises(SourceBudgetExceeded, match='phase count'): budget.begin_proof()
    assert budget.phase == 5 and budget.deadline == deadline


def test_expired_or_overrun_phase_cannot_reset_its_limit():
    budget = ReadBudget(); budget.deadline = 0
    with pytest.raises(SourceBudgetExceeded): budget.begin_proof()
    assert budget.phase == 1 and budget.deadline == 0
    for charges in [dict(entries=100001), dict(size=16*1024**3+1), dict(reserve_bytes=16*1024**3+1)]:
        budget = ReadBudget()
        with pytest.raises(SourceBudgetExceeded): budget(**charges)
        with pytest.raises(SourceBudgetExceeded): budget.begin_proof()
        assert budget.phase == 1


def test_failed_source_proof_still_consumes_phase_allowance(tmp_path):
    f = finalized(tmp_path); source = open_source(f)
    f['pointer'].write_bytes(f['pointer'].read_bytes()+b' ')
    for phase in range(2, 6):
        with pytest.raises(SourceUnavailable): source.recheck()
        assert source.budget.phase == phase
    with pytest.raises(SourceBudgetExceeded, match='phase count'): source.recheck()
