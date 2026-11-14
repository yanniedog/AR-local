"""Real captured fact/body phases over a technical local published selection."""
from datetime import datetime,timedelta,timezone

import pytest

from app_payload_product_evidence_contract import canonical,decode,digest
from app_payload_common import DEFAULT_TAG
from pi_product_evidence_dispatch_state import Work,register
import pi_product_evidence_prepare as prepare
from pi_product_evidence_intent import KEY
from tests.test_product_evidence_optional_retry import optional,source
from tests.product_evidence_finalized_fixture import ENABLED,WRITER

NOW=datetime(2026,5,19,8,tzinfo=timezone.utc)


@pytest.fixture
def work(optional,monkeypatch):
    (fixture,pointer,_),store,_,published,_=optional
    index=store.objects[(DEFAULT_TAG,'dates-index.json')]
    pointer={k:v for k,v in pointer.items() if k!=KEY}
    pin=register(fixture['state'],pointer,published_root=published.archive_dir,index_raw=index,
                 expected_index_sha256=digest(index),enabled=ENABLED,writer_revision=WRITER,writer_tree='b'*40)
    monkeypatch.setattr(prepare,'checkout_binding',lambda _:dict(head=WRITER,tree='b'*40,clean=True))
    return Work(fixture['state'],pin),fixture,store,published


def complete(work,fixture,now=NOW):
    attempt=work.begin(now);assert attempt
    result=prepare.run_phase(fixture['state'].parent,work.state,work.pin,attempt)
    assert result['publication_authorized'] is False and result['selection_verified'] is False
    assert work.finish(attempt,now=now,status='complete')
    return attempt,result


def test_all_real_phases_create_separate_ready_retry_without_rewriting_financial(work):
    from app_payload_product_evidence_daily import FinancialEvidence
    from pi_product_evidence_retry import OptionalRetry
    from app_payload_revisions import publish_revision_bundle
    from tests.test_app_payload_revisions import CONSUMER
    owner,fixture,store,published=work
    originals={p:p.read_bytes() for p in published.archive_dir.iterdir() if p.is_file()}
    for expected in ('snapshot','facts','responses','delivery'):
        assert owner.next_phase()==expected;complete(owner,fixture)
    sha=prepare.ready_retry(fixture['state'].parent,owner)
    assert prepare.ready_retry(fixture['state'].parent,owner)==sha
    retry=OptionalRetry(owner.state,sha)
    financial=FinancialEvidence(owner.state.parent,owner.state,retry.request['pointer'],retry.request['source'],pin_store=retry)
    candidate,manifest=financial.resume()
    assert all(manifest['optional_product_evidence_status']['lanes'][lane]['state']=='available' for lane in ENABLED)
    next_publication=publish_revision_bundle(candidate,state_dir=owner.state/'app-payload/v1/revision-history',
        repo='yanniedog/AR-local',enabled=True,consumer_commit=CONSUMER,store=store,expected_predecessor=published.head)
    assert next_publication.head['revision']==published.head['revision']+1
    assert all(p.read_bytes()==raw for p,raw in originals.items())
    assert owner.next_phase()=='publish'  # No local stage grants actual remote publication.


def test_failed_attempt_preserved_new_nonce_and_stale_cas_refused(work):
    owner,fixture,_,_=work;attempt=owner.begin(NOW)
    root=owner.root/'attempts'/attempt['attempt_id'];(root/'partial').write_bytes(b'preserve')
    assert owner.begin(NOW+timedelta(seconds=1800)) is None
    assert owner.finish(attempt,now=NOW,status='failed',reason='bounded failure')
    second=owner.begin(NOW+timedelta(hours=2));assert second['attempt_id']!=attempt['attempt_id']
    assert not owner.finish(attempt,now=NOW,status='complete')
    assert (root/'partial').read_bytes()==b'preserve'
    result=prepare.run_phase(fixture['state'].parent,owner.state,owner.pin,second)
    assert result['phase']=='snapshot'


@pytest.mark.parametrize('fault',['pointer','writer','published','attempt'])
def test_changed_binding_never_commits(work,monkeypatch,fault):
    owner,fixture,_,published=work;attempt=owner.begin(NOW)
    if fault=='pointer':fixture['pointer'].write_bytes(fixture['pointer'].read_bytes()+b' ')
    elif fault=='writer':monkeypatch.setattr(prepare,'checkout_binding',lambda _:dict(head='b'*40,tree='b'*40,clean=True))
    elif fault=='published':
        path=published.archive_dir/'manifest.json';path.write_bytes(path.read_bytes()+b' ')
    else:attempt=dict(attempt,attempt_id='f'*32)
    with pytest.raises(ValueError):prepare.run_phase(owner.state.parent,owner.state,owner.pin,attempt)
    assert not list((owner.root/'attempts').glob('*/result.json'))
    assert owner.progress()['stages']=={}


def test_result_pin_cannot_be_reused_for_another_attempt(work):
    owner,fixture,_,_=work;attempt=owner.begin(NOW)
    result=prepare.run_phase(owner.state.parent,owner.state,owner.pin,attempt)
    path=owner.root/'attempts'/attempt['attempt_id']/'result.json'
    path.write_bytes(canonical(dict(result,attempt_id='f'*32)))
    with pytest.raises(ValueError,match='this attempt'):owner.finish(attempt,now=NOW,status='complete')
    assert not owner.progress()['stages']


def test_committed_snapshot_corruption_does_not_discover_other_snapshot(work):
    owner,fixture,_,_=work;_,result=complete(owner,fixture)
    path=owner.root/result['outputs']['preparation']['file'];path.write_bytes(path.read_bytes()+b' ')
    attempt=owner.begin(NOW)
    with pytest.raises(ValueError,match='phase bytes'):prepare.run_phase(owner.state.parent,owner.state,owner.pin,attempt)
    assert set(owner.progress()['stages'])=={'snapshot'}
