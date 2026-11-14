"""Exact new-writer provenance and already-published coordinator crash recovery."""
import pytest
from app_payload_product_evidence_contract import decode
from tests.test_product_evidence_optional_retry import optional,source
from tests.product_evidence_finalized_fixture import WRITER


@pytest.mark.parametrize('delegated',[False,True])
def test_completed_optional_retry_rechecks_without_another_reservation(optional,monkeypatch,delegated):
    import ar_local_pi_runtime,pi_daily_sync,pi_payload_retry_policy,app_payload_build
    from app_payload_revisions import publish_revision_bundle
    from tests.test_app_payload_revisions import CONSUMER
    from pi_product_evidence_retry import publish_optional_retry_owned,publish_optional_retry_delegated,OptionalRetry
    (fixture,_,_),store,state,published,sha=optional
    monkeypatch.setattr(ar_local_pi_runtime,'data_state_root',lambda _:fixture['state'])
    monkeypatch.setattr(pi_daily_sync,'payload_publication_pending',lambda _:False)
    monkeypatch.setattr(pi_payload_retry_policy,'payload_retry_window_reason',lambda:'')
    def build(_,*,state_dir,optional_evidence):
        root,_=optional_evidence.resume()
        publication=publish_revision_bundle(root,state_dir=state,repo='yanniedog/AR-local',enabled=True,
            consumer_commit=CONSUMER,store=store,expected_predecessor=optional_evidence.expected_predecessor)
        return publication.manifest,True,True  # Alias lifecycle is independently covered; no network here.
    monkeypatch.setattr(app_payload_build,'build_and_publish_dual',build)
    binding=dict(commit=WRITER,tree='b'*40,source_closure_sha256='c'*64,runtime_sha256='d'*64,profile_sha256='e'*64)
    checks=[]
    def invoke():
        if not delegated:return publish_optional_retry_owned(fixture['state'].parent,sha,validate_owner=lambda:checks.append('owner'),completion_writer=binding)
        import pi_product_evidence_worker as child
        # Native descriptor admission is tested separately; this control proves
        # the admitted path does not attempt a nested production lock.
        monkeypatch.setattr(child,'validate',lambda value:checks.append('owner'))
        monkeypatch.setattr(pi_daily_sync,'DailyIngestLock',lambda path:pytest.fail('delegated worker reacquired production lock'))
        return publish_optional_retry_delegated(dict(production=str(fixture['state'].parent),request={'phase':'publish'}),sha,completion_writer=binding)
    first=invoke()
    assert first['status']=='published'
    result=decode((fixture['state']/first['completion']['file']).read_bytes())
    assert result['writer']==binding and result['original_financial_writer'] is None
    assert result['selected_head']['revision']==published.head['revision']+1
    assert result['predecessor']==published.head
    progress=OptionalRetry(fixture['state'],sha).progress()
    assert progress['status']=='published'
    second=invoke()
    assert second==first and store.promotions==2
    assert OptionalRetry(fixture['state'],sha).progress()==progress and len(checks)>=6


def test_new_completion_requires_exact_writer_closure():
    from pi_product_evidence_completion import validate_writer
    with pytest.raises(ValueError):validate_writer(dict(commit=WRITER))


def test_delegated_entry_requires_exact_worker_validation_before_any_retry(monkeypatch):
    import pi_product_evidence_worker as worker
    import pi_product_evidence_retry as retry
    monkeypatch.setattr(worker,'validate',lambda value:(_ for _ in ()).throw(ValueError('parent descriptor changed')))
    monkeypatch.setattr(retry,'_publish_optional_retry',lambda *a,**k:pytest.fail('unverified delegation reached publication'))
    with pytest.raises(ValueError,match='descriptor changed'):
        retry.publish_optional_retry_delegated({},'a'*64,completion_writer={})
