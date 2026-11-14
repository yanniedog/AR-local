"""Captured source fixtures; base gzip/selection controls are not deployment proof."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

import app_payload_product_evidence_daily as daily
import pi_product_evidence_intent as intent
import pi_daily_sync as sync
from app_payload_product_evidence_contract import canonical, decode, digest
from cdr_product_evidence_delivery_policy import STATUS
from pi_payload_retry_policy import publication_source_key
from tests.product_evidence_finalized_fixture import finalized, WRITER, ENABLED


@pytest.fixture
def source(tmp_path, monkeypatch):
    value=finalized(tmp_path);state=value['state']
    pointer=intent.enrich_pointer(tmp_path,decode(value['pointer'].read_bytes()),enabled=ENABLED,revision=WRITER)
    monkeypatch.setattr(sync,'data_state_root',lambda _:state)
    monkeypatch.setattr(daily,'writer_revision',lambda _:WRITER)
    sync.mark_payload_publication_pending(tmp_path,'publication_started',pointer)
    return value,pointer,decode(value['contract'].read_bytes())


def session(source):
    value,pointer,contract=source
    return daily.FinancialEvidence(value['state'].parent,value['state'],pointer,contract)


def test_default_disabled_preserves_pointer_and_never_reads_optional_code_or_paths(tmp_path,monkeypatch):
    pointer={'technical':'unchanged legacy'}
    for flag in ('AR_LOCAL_PRODUCT_EVIDENCE_DELIVERY','AR_LOCAL_PRODUCT_RESPONSE_EVIDENCE_DELIVERY'):
        monkeypatch.delenv(flag,raising=False)
    monkeypatch.setattr(intent,'writer_revision',lambda _:pytest.fail('disabled code lookup'))
    assert intent.enrich_pointer(tmp_path,pointer) is pointer


def test_initial_pointer_and_external_freeze_pin_survive_pending_roundtrip(source):
    value,pointer,_=source;before=canonical(pointer);key=publication_source_key({'pointer':pointer})
    worker=session(source);assert worker.resume() is None
    root,manifest=worker.freeze(value['root'])
    pin=intent.candidate_pin(value['state'].parent,pointer)
    assert pin and (value['state']/pin['file']).is_file()
    assert canonical(pointer)==before and publication_source_key({'pointer':pointer})==key
    assert sync.pending_publication_pointer(value['state'].parent)==pointer
    assert all(row['state']=='pending' for row in manifest[STATUS]['lanes'].values())
    assert root!=value['root'] and (value['root']/'manifest.json').read_bytes()==canonical(value['base'])


def test_retry_reuses_all_frozen_bytes_despite_new_packages_and_changed_build_inputs(source,monkeypatch):
    value,pointer,_=source;root,manifest=session(source).freeze(value['root'])
    before={p.name:p.read_bytes() for p in root.iterdir()}
    (value['state']/'newly-ready-package.json').write_text('{}')
    (value['root']/'manifest.json').write_bytes(b'changed mutable staging')
    monkeypatch.setattr(daily.FinancialEvidence,'_ready',lambda *_:pytest.fail('pending retry adopted package'))
    again,observed=session(source).resume()
    assert again==root and observed==manifest
    assert {p.name:p.read_bytes() for p in again.iterdir()}==before


@pytest.mark.parametrize('fault',['receipt','candidate','base','writer','pointer'])
def test_exact_retry_rejects_frozen_input_and_authority_drift(source,monkeypatch,fault):
    value,pointer,_=source;worker=session(source);root,_=worker.freeze(value['root'])
    if fault=='receipt':
        pin=intent.candidate_pin(value['state'].parent,pointer);path=value['state']/pin['file'];path.write_bytes(path.read_bytes()+b' ')
    elif fault=='candidate':(root/'manifest.json').write_bytes((root/'manifest.json').read_bytes()+b' ')
    elif fault=='base':(root.parent/'base/manifest.json').write_bytes(b'{}')
    elif fault=='writer':monkeypatch.setattr(daily,'writer_revision',lambda _:'b'*40)
    else:pointer['generation_id']='changed'
    with pytest.raises(ValueError):session(source).resume()


def test_freeze_interruption_cannot_leave_an_authorised_candidate_pin(source,monkeypatch):
    value,pointer,_=source
    monkeypatch.setattr(daily,'bind_candidate_pin',lambda *_:(_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):session(source).freeze(value['root'])
    assert intent.candidate_pin(value['state'].parent,pointer) is None
    assert list((value['state']/daily.DIRECTORY).glob('*/*/freeze.json'))  # retained interrupted evidence


def test_pending_clear_cas_does_not_clear_a_different_source(source):
    value,pointer,_=source;session(source).freeze(value['root'])
    other=deepcopy(pointer);other.pop(intent.KEY);other['observation_date']='2026-05-20'
    sync.mark_payload_publication_pending(value['state'].parent,'other',other)
    sync.clear_payload_publication_pending(value['state'].parent,other)
    assert sync.pending_publication_pointer(value['state'].parent)==pointer
    assert intent.candidate_pin(value['state'].parent,pointer)


def test_builder_freezes_before_reservation_and_resume_never_recomputes(source,monkeypatch,tmp_path):
    import app_payload_build as build
    import app_payload
    import app_payload_revisions
    value,pointer,contract=source;state=value['state']/'app-payload/v1'
    (value['root']/'dashboard-cache').mkdir()
    (value['root']/'dashboard-cache/latest.json').write_text(json.dumps({'run_date':contract['observation_date']}))
    monkeypatch.setattr(app_payload,'_live_manifest_status',lambda *_:('missing',None))
    monkeypatch.setattr(app_payload_revisions,'revision_mode_enabled',lambda:True)
    monkeypatch.setattr(build,'_attach_terms',lambda *_:None)
    monkeypatch.setattr(app_payload,'_compute_payload',lambda *a,**k:{})
    def package(data,out_dir,**kwargs):
        out_dir.mkdir(parents=True,exist_ok=True)
        for path in value['root'].iterdir():
            if path.is_file():shutil.copyfile(path,out_dir/path.name)
        return value['base']
    monkeypatch.setattr(build,'_package_payload',package)
    calls=[]
    def publish(root,**kwargs):
        assert intent.candidate_pin(value['state'].parent,pointer)
        kwargs['pre_promotion_guard']();calls.append(root)
        return SimpleNamespace(archive_dir=root,manifest=decode((root/'manifest.json').read_bytes()))
    monkeypatch.setattr(app_payload_revisions,'publish_revision_bundle',publish)
    monkeypatch.setattr(build,'publish_payload',lambda *a,**k:True)
    build.build_and_publish_dual(value['root'],state_dir=state,optional_evidence=session(source))
    monkeypatch.setattr(app_payload,'_compute_payload',lambda *a,**k:pytest.fail('retry recomputed financial data'))
    monkeypatch.setattr(build,'_package_payload',lambda *a,**k:pytest.fail('retry rebuilt candidate'))
    build.build_and_publish_dual(value['root'],state_dir=state,optional_evidence=session(source))
    assert len(calls)==2 and calls[0]==calls[1]
