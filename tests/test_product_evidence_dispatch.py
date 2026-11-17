"""Financial-first coordinator controls; no root, network or service execution."""
from pathlib import Path
import pytest

from app_payload_product_evidence_contract import decode
from pi_product_evidence_dispatch_state import Work
import pi_product_evidence_dispatch as dispatch
from tests.test_product_evidence_optional_retry import optional,source
from tests.product_evidence_finalized_fixture import ENABLED,WRITER


@pytest.fixture
def configured(optional,monkeypatch):
    import ar_local_pi_runtime
    (fixture,_,_),store,_,published,_=optional
    monkeypatch.setattr(ar_local_pi_runtime,'data_state_root',lambda _:fixture['state'])
    monkeypatch.setattr(dispatch,'checkout_binding',lambda _:dict(head=WRITER,tree='b'*40,clean=True))
    return fixture,store,published


def test_enqueue_reuses_first_pin_after_writer_or_new_package_changes(configured,monkeypatch):
    fixture,store,published=configured;repo=fixture['state'].parent
    first=dispatch.enqueue_published(repo,published.manifest,enabled=ENABLED)
    assert first['status']=='queued' and not first['existing']
    owner=Work(fixture['state'],first['work']);before=(owner.root/'request.json').read_bytes()
    monkeypatch.setattr(dispatch,'checkout_binding',lambda _:pytest.fail('existing request rebound its writer'))
    second=dispatch.enqueue_published(repo,published.manifest,enabled=ENABLED[:1])
    assert second['work']==first['work'] and second['existing']
    assert (owner.root/'request.json').read_bytes()==before and owner.request['enabled']==list(ENABLED)


def test_default_disabled_returns_before_optional_state_profile_queue_or_network(monkeypatch):
    monkeypatch.delenv('AR_LOCAL_PRODUCT_EVIDENCE_DELIVERY',raising=False)
    monkeypatch.delenv('AR_LOCAL_PRODUCT_RESPONSE_EVIDENCE_DELIVERY',raising=False)
    monkeypatch.setattr(dispatch,'borrow',lambda:pytest.fail('disabled queue access'))
    class NoIO:
        def is_file(self):pytest.fail('disabled profile access')
    monkeypatch.setattr(dispatch,'PROFILE',NoIO())
    assert dispatch.dispatch(Path('/unused'))=={'status':'disabled'}
    assert dispatch.enqueue_published(Path('/unused'),{})=={'status':'disabled'}


def test_missing_commissioning_defers_without_claim_or_stage(monkeypatch,tmp_path):
    monkeypatch.setenv('AR_LOCAL_PRODUCT_EVIDENCE_DELIVERY','1')
    monkeypatch.setenv('AR_LOCAL_PRODUCT_RESPONSE_EVIDENCE_DELIVERY','0')
    monkeypatch.setattr(dispatch,'PROFILE',tmp_path/'absent-profile')
    monkeypatch.setattr(dispatch,'borrow',lambda:pytest.fail('uncommissioned queue access'))
    assert dispatch.dispatch(tmp_path)['reason']=='optional_launcher_uncommissioned'
    assert list(tmp_path.iterdir())==[]


def test_optional_enqueue_failure_is_reported_without_raising(configured,monkeypatch):
    fixture,_,published=configured
    monkeypatch.setenv('AR_LOCAL_PRODUCT_EVIDENCE_DELIVERY','invalid')
    result=dispatch.enqueue_after_financial(fixture['state'].parent,published.manifest)
    assert result=={'status':'failed','reason':'ValueError'}


def test_crash_reconcile_requires_original_committed_local_promotion(configured):
    fixture,store,published=configured;repo=fixture['state'].parent
    pointer=decode(fixture['pointer'].read_bytes())
    # Explicit flags are a test control; the untouched fixture store contains
    # genuine publication transaction bytes over captured financial/body data.
    import os
    prior={key:os.environ.get(key) for key in ('AR_LOCAL_PRODUCT_EVIDENCE_DELIVERY','AR_LOCAL_PRODUCT_RESPONSE_EVIDENCE_DELIVERY')}
    try:
        os.environ.update({key:'1' for key in prior})
        owner=dispatch._resume_or_enqueue(repo,fixture['state'],pointer,store)
        assert owner.request['predecessor']==published.head
    finally:
        for key,value in prior.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value
