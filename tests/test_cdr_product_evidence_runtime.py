"""Captured product facts/bodies with explicit local selection controls only."""
from pathlib import Path
import pytest

from app_payload_product_evidence_contract import canonical, digest
from cdr_product_evidence_delivery_policy import MalformedReady
from cdr_product_evidence_runtime import freeze_delivery, resume_delivery
from cdr_product_evidence_source import SourceUnavailable, SourceBudgetExceeded
from tests.test_cdr_product_evidence_preparation import prepared
from tests.product_evidence_finalized_fixture import open_source, WRITER, FACTS, RESPONSES, ENABLED


def freeze(values, root, packages=None):
    fixture, source, snapshot, declared = values
    return freeze_delivery(source, snapshot, ENABLED, declared if packages is None else packages,
        evidence_root=root, writer_revision=WRITER, expected_preparation_sha256=snapshot.sha256)


def resume(fixture, frozen, root, **kwargs):
    return resume_delivery(open_source(fixture), frozen.raw, frozen.sha256, evidence_root=root,
        enabled=kwargs.get('enabled', ENABLED), writer_revision=kwargs.get('writer', WRITER))


def test_actual_prepared_intent_resumes_readonly_without_marker_authority(prepared, tmp_path, monkeypatch):
    fixture, source, snapshot, packages = prepared
    before={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    frozen=freeze(prepared,tmp_path)
    assert source.budget.phase==5
    mutable=frozen.document();mutable['snapshot_root']='changed'
    assert frozen.document()['snapshot_root']=='new-snapshot'
    from cdr_file_lock import FileLock
    monkeypatch.setattr(FileLock,'__enter__',lambda *a:pytest.fail('write lock acquired'))
    monkeypatch.setattr(Path,'write_bytes',lambda *a:pytest.fail('resume wrote bytes'))
    fresh=open_source(fixture)
    result=resume_delivery(fresh,frozen.raw,frozen.sha256,evidence_root=tmp_path,enabled=ENABLED,writer_revision=WRITER)
    assert fresh.budget.phase==3
    assert all(value['state']=='available' for value in result.document()['lanes'].values())
    assert result.document()['publication_authorized'] is False
    assert {str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}==before
    assert snapshot.document()['selection_verified'] is False


def test_disabled_freeze_never_touches_paths_or_source():
    assert freeze_delivery(None,None,(),{},evidence_root=object(),writer_revision=None,
        expected_preparation_sha256=None) is None


def test_frozen_pending_lane_does_not_adopt_newly_present_package(prepared,tmp_path):
    fixture,_,_,packages=prepared
    frozen=freeze(prepared,tmp_path,{FACTS:packages[FACTS]})
    assert (Path(packages[RESPONSES]['root'])/'prepared.json').is_file()
    candidate=resume(fixture,frozen,tmp_path).document()
    assert candidate['lanes'][RESPONSES]==dict(state='pending',reason='not_prepared')
    assert candidate['lanes'][FACTS]['state']=='available'


@pytest.mark.parametrize('fault',['pin','traversal','absolute','lane','receipt','authority','schema'])
def test_modified_or_rehashed_frozen_intent_cannot_change_authority(prepared,tmp_path,fault):
    fixture,_,_,_=prepared;frozen=freeze(prepared,tmp_path);value=frozen.document()
    if fault=='traversal':value['snapshot_root']='../new-snapshot'
    elif fault=='absolute':value['snapshot_root']=str(tmp_path/'new-snapshot')
    elif fault=='lane':value['packages'].pop(FACTS)
    elif fault=='receipt':value['preparation']['sha256']='0'*64
    elif fault=='authority':value['publication_authorized']=True
    elif fault=='schema':value['schema']='future-v2'
    raw=canonical(value);pin='0'*64 if fault=='pin' else digest(raw)
    with pytest.raises(MalformedReady):
        resume_delivery(open_source(fixture),raw,pin,evidence_root=tmp_path,enabled=ENABLED,writer_revision=WRITER)


@pytest.mark.parametrize('change',['writer','flags','source','shard','marker'])
def test_resume_revalidates_fresh_source_code_flags_and_ready_bytes(prepared,tmp_path,change):
    fixture,_,_,packages=prepared;frozen=freeze(prepared,tmp_path)
    if change=='source':fixture['pointer'].write_bytes(fixture['pointer'].read_bytes()+b' ')
    elif change=='shard':
        path=next(Path(packages[FACTS]['root']).glob('*shard*.gz'));path.write_bytes(path.read_bytes()+b'changed')
    elif change=='marker':(Path(packages[FACTS]['root'])/'prepared.json').unlink()
    with pytest.raises((MalformedReady,SourceUnavailable)):
        resume(fixture,frozen,tmp_path,enabled=(FACTS,) if change=='flags' else ENABLED,
               writer='b'*40 if change=='writer' else WRITER)


def test_resume_cannot_renew_exhausted_same_source_budget(prepared,tmp_path):
    _,source,_,_=prepared;frozen=freeze(prepared,tmp_path)
    with pytest.raises(SourceBudgetExceeded):
        resume_delivery(source,frozen.raw,frozen.sha256,evidence_root=tmp_path,enabled=ENABLED,writer_revision=WRITER)
    assert source.budget.exceeded


@pytest.mark.parametrize('raw',[b' '*262145,b'['*2000+b'0'+b']'*2000],ids=['oversize','deep'])
def test_descriptor_parser_bounds_fail_closed_before_any_path_adoption(prepared,tmp_path,raw):
    fixture,_,_,_=prepared
    with pytest.raises(MalformedReady):
        resume_delivery(open_source(fixture),raw,digest(raw),evidence_root=tmp_path,enabled=ENABLED,writer_revision=WRITER)


@pytest.mark.parametrize('target',['snapshot','package'])
def test_post_adoption_location_change_stays_fatal_claimed_ready(prepared,tmp_path,monkeypatch,target):
    import cdr_product_evidence_runtime as runtime
    original=runtime.adopt_prepared
    def mutate_after_proof(*args,**kwargs):
        candidate=original(*args,**kwargs)
        path=prepared[2].root if target=='snapshot' else Path(prepared[3][FACTS]['root'])
        path.rename(path.with_name(path.name+'-retained'))
        return candidate
    monkeypatch.setattr(runtime,'adopt_prepared',mutate_after_proof)
    with pytest.raises(MalformedReady,match='prepared locations changed'):
        freeze(prepared,tmp_path)
