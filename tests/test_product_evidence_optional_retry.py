"""Offline captured-body publication/retry controls; no public selection proof."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import shutil

import pytest

import app_payload_product_evidence_daily as daily
import pi_product_evidence_retry as retry
import pi_daily_sync as sync
from app_payload_product_evidence_contract import canonical, decode, digest
from app_payload_common import DEFAULT_REPO, DEFAULT_TAG
from app_payload_revisions import publish_revision_bundle
from app_payload_revisions_state import RevisionError
from cdr_product_evidence_delivery_policy import apply_status, pending_outcomes
from tests.product_evidence_finalized_fixture import ENABLED
from tests.product_evidence_daily_fixture import ready_source
from tests.test_product_evidence_daily_intent import source
from tests.test_app_payload_complete_publication import Store
from tests.test_app_payload_revisions import build_payload, CONSUMER


@pytest.fixture
def optional(source, tmp_path):
    fixture, _, _ = source
    # Replace only the explicit technical base control with retained real rates
    # and details before freezing. Original source/contract bytes are untouched.
    real = tmp_path/'real-base'; base = build_payload(real); base['repo'] = DEFAULT_REPO
    base['source_observation'] = fixture['base']['source_observation']
    for row in base['files'].values():
        row['url'] = f'https://github.com/{DEFAULT_REPO}/releases/download/{DEFAULT_TAG}/{row["name"]}'
    (real/'manifest.json').write_bytes(canonical(base)); fixture['root'] = real; fixture['base'] = base
    values = ready_source(source); fixture, pointer, contract = values
    pending = tmp_path/'pending-financial'; shutil.copytree(fixture['root'], pending)
    (pending/'manifest.json').write_bytes(canonical(apply_status(base, ENABLED, pending_outcomes(ENABLED))))
    store = Store(); publication_state = fixture['state']/'app-payload/v1/revision-history'
    published = publish_revision_bundle(pending,state_dir=publication_state,repo=DEFAULT_REPO,
        enabled=True,consumer_commit=CONSUMER,store=store)
    index = store.objects[(DEFAULT_TAG,'dates-index.json')]
    sha = retry.register_optional_retry(fixture['state'],pointer,published_root=published.archive_dir,
                                       index_raw=index,expected_index_sha256=digest(index))
    return values, store, publication_state, published, sha


def test_explicit_retry_separate_state_resumes_exact_ready_and_preserves_financial_pending(optional):
    (fixture,pointer,contract),_,_,published,sha = optional
    path = sync.payload_publication_pending_path(fixture['state'].parent); before = path.read_bytes()
    owner = retry.OptionalRetry(fixture['state'],sha)
    assert owner.expected_predecessor == published.head
    worker = daily.FinancialEvidence(fixture['state'].parent,fixture['state'],pointer,contract,pin_store=owner)
    root, manifest = worker.resume()
    assert set(manifest['optional_product_evidence_status']['lanes'][lane]['state'] for lane in ENABLED) == {'available'}
    assert daily.FinancialEvidence(fixture['state'].parent,fixture['state'],pointer,contract,pin_store=owner).resume()[0] == root
    assert path.read_bytes() == before


def test_optional_attempt_cooldown_failure_and_completion_cas(optional):
    (fixture,_,_),_,_,_,sha = optional; owner=retry.OptionalRetry(fixture['state'],sha)
    now=datetime(2026,5,19,tzinfo=timezone.utc); first=owner.begin(now)
    assert first and owner.begin(now+timedelta(seconds=1)) is None
    later=now+timedelta(days=1); second=owner.begin(later)
    assert second != first and not owner.finish(first,'published',later)
    assert owner.finish(second,'failed',later,'control')
    assert not owner.finish(second,'published',later)
    third=owner.begin(later+timedelta(days=1))
    assert owner.finish(third,'published',later+timedelta(days=1))
    assert owner.begin(later+timedelta(days=10)) is None


@pytest.mark.parametrize('fault',['index','manifest','financial','request'])
def test_optional_retry_rejects_predecessor_and_external_pin_drift(optional,fault):
    (fixture,pointer,_),store,_,published,sha = optional
    index=store.objects[(DEFAULT_TAG,'dates-index.json')]; index_sha=digest(index)
    if fault=='index': index += b' '
    elif fault=='manifest':
        p=published.archive_dir/'manifest.json';p.write_bytes(p.read_bytes()+b' ')
    elif fault=='financial':
        p=fixture['root']/'manifest.json';p.write_bytes(p.read_bytes()+b' ')
    else:
        p=fixture['state']/retry.DIRECTORY/'requests'/f'{sha}.json';p.write_bytes(p.read_bytes()+b' ')
        with pytest.raises(ValueError):retry.OptionalRetry(fixture['state'],sha)
        return
    with pytest.raises((ValueError,RevisionError)):
        retry.register_optional_retry(fixture['state'],pointer,published_root=published.archive_dir,
                                      index_raw=index,expected_index_sha256=index_sha)


def test_explicit_call_defers_financial_work_without_reserving_or_mutating(optional,monkeypatch):
    import ar_local_pi_runtime, pi_deploy_queue_claim, pi_payload_retry_policy
    (fixture,_,_),_,_,_,sha=optional;state=fixture['state'];path=sync.payload_publication_pending_path(state.parent)
    before=path.read_bytes()
    monkeypatch.setattr(ar_local_pi_runtime,'data_state_root',lambda _:state)
    monkeypatch.setattr(pi_deploy_queue_claim,'inherited_queue_admission',lambda:'reuse')
    monkeypatch.setattr(pi_payload_retry_policy,'payload_retry_window_reason',lambda:'')
    assert retry.publish_optional_retry(state.parent,sha)=={'status':'deferred','reason':'financial_publication_pending'}
    assert path.read_bytes()==before and not retry.OptionalRetry(state,sha).progress()


def test_actual_revision_retry_recovers_after_alias_failure_without_new_reservation(optional,monkeypatch):
    import app_payload, app_payload_build as build, app_payload_revisions as revisions
    (fixture,pointer,contract),store,publication_state,published,sha=optional
    owner=retry.OptionalRetry(fixture['state'],sha)
    def worker(): return daily.FinancialEvidence(fixture['state'].parent,fixture['state'],pointer,contract,pin_store=owner)
    monkeypatch.setattr(build,'_load_json',lambda _: {'run_date':contract['observation_date']})
    monkeypatch.setattr(app_payload,'_live_manifest_status',lambda *_:('missing',None))
    monkeypatch.setattr(app_payload,'_compute_payload',lambda *a,**k:pytest.fail('ready retry rebuilt financial data'))
    monkeypatch.setattr(revisions,'revision_mode_enabled',lambda:True)
    original=revisions.publish_revision_bundle
    monkeypatch.setattr(revisions,'publish_revision_bundle',lambda *a,**k:original(*a,**k,consumer_commit=CONSUMER,store=store))
    calls=[]
    def alias(*a,**k):
        calls.append(a)
        if len(calls)==1: raise RuntimeError('controlled alias failure after selection')
        return True
    monkeypatch.setattr(build,'publish_payload',alias)
    with pytest.raises(RuntimeError,match='controlled alias'):
        build.build_and_publish_dual(fixture['exports'],state_dir=publication_state.parent,optional_evidence=worker())
    assert store.promotions==2  # Financial predecessor plus its optional child.
    reservations=list((publication_state/'revisions').glob('*/r*/reservation.json'))
    result,dated,_=build.build_and_publish_dual(fixture['exports'],state_dir=publication_state.parent,optional_evidence=worker())
    assert dated and result['payload_revision']['parent_revision']==published.head['revision']
    assert store.promotions==2 and list((publication_state/'revisions').glob('*/r*/reservation.json'))==reservations


def test_actual_optional_candidate_cannot_replace_a_different_selected_predecessor(optional,monkeypatch):
    (fixture,pointer,contract),store,state,published,sha=optional
    owner=retry.OptionalRetry(fixture['state'],sha)
    worker=daily.FinancialEvidence(fixture['state'].parent,fixture['state'],pointer,contract,pin_store=owner)
    root,_=worker.resume(); expected=deepcopy(published.head); expected['manifest_sha256']='0'*64
    with pytest.raises(RevisionError,match='predecessor'):
        publish_revision_bundle(root,state_dir=state,repo=DEFAULT_REPO,enabled=True,
            consumer_commit=CONSUMER,store=store,expected_predecessor=expected)
    assert store.promotions==1


def test_legacy_predecessor_actual_bytes_are_verified_before_request_creation(optional,tmp_path):
    (fixture,pointer,_),_,_,_,_=optional
    legacy=publish_revision_bundle(fixture['root'],state_dir=tmp_path/'legacy-state',repo=DEFAULT_REPO,
        enabled=True,consumer_commit=CONSUMER,store=(store:=Store()))
    index=store.objects[(DEFAULT_TAG,'dates-index.json')]
    assert retry.register_optional_retry(fixture['state'],pointer,published_root=legacy.archive_dir,
                                         index_raw=index,expected_index_sha256=digest(index))
    entry=legacy.manifest['files']['core'];(legacy.archive_dir/entry['name']).write_bytes(b'changed')
    with pytest.raises((ValueError,RevisionError)):
        retry.register_optional_retry(fixture['state'],pointer,published_root=legacy.archive_dir,
                                      index_raw=index,expected_index_sha256=digest(index))


def test_optional_retry_cannot_silently_remove_previously_available_lane(optional):
    (fixture,pointer,contract),store,state,_,sha=optional
    owner=retry.OptionalRetry(fixture['state'],sha)
    worker=daily.FinancialEvidence(fixture['state'].parent,fixture['state'],pointer,contract,pin_store=owner)
    root,_=worker.resume()
    published=publish_revision_bundle(root,state_dir=state,repo=DEFAULT_REPO,
        enabled=True,consumer_commit=CONSUMER,store=store,expected_predecessor=owner.expected_predecessor)
    index=store.objects[(DEFAULT_TAG,'dates-index.json')]
    next_sha=retry.register_optional_retry(fixture['state'],pointer,published_root=published.archive_dir,
                                          index_raw=index,expected_index_sha256=digest(index))
    next_owner=retry.OptionalRetry(fixture['state'],next_sha)
    with pytest.raises(ValueError,match='new immutable revision'):next_owner.validate_candidate(published.manifest)
    with pytest.raises(ValueError,match='remove an available lane'):next_owner.validate_candidate(fixture['base'])


def test_optional_admission_is_rechecked_after_lock_wait(optional,monkeypatch):
    import ar_local_pi_runtime, pi_deploy_queue_claim, pi_payload_retry_policy
    (fixture,_,_),_,_,_,sha=optional;state=fixture['state']
    monkeypatch.setattr(ar_local_pi_runtime,'data_state_root',lambda _:state)
    monkeypatch.setattr(pi_deploy_queue_claim,'inherited_queue_admission',lambda:'reuse')
    reasons=iter(['','protected_natural_ingest_window'])
    monkeypatch.setattr(pi_payload_retry_policy,'payload_retry_window_reason',lambda:next(reasons))
    assert retry.publish_optional_retry(state.parent,sha)['reason']=='protected_natural_ingest_window'
    assert not retry.OptionalRetry(state,sha).progress()


def test_optional_rolling_alias_failure_is_retained_as_failed_retry(optional,monkeypatch):
    import ar_local_pi_runtime, pi_deploy_queue_claim, pi_payload_retry_policy, app_payload, app_payload_build
    (fixture,_,_),_,_,published,sha=optional;state=fixture['state']
    sync.clear_payload_publication_pending(state.parent,sync.pending_publication_pointer(state.parent))
    monkeypatch.setattr(ar_local_pi_runtime,'data_state_root',lambda _:state)
    monkeypatch.setattr(pi_deploy_queue_claim,'inherited_queue_admission',lambda:'reuse')
    monkeypatch.setattr(pi_payload_retry_policy,'payload_retry_window_reason',lambda:'')
    monkeypatch.setattr(app_payload_build,'build_and_publish_dual',lambda *a,**k:(published.manifest,True,False))
    monkeypatch.setattr(app_payload,'_live_manifest_status',lambda *a:('missing',None))
    with pytest.raises(ValueError,match='rolling alias'):retry.publish_optional_retry(state.parent,sha)
    assert retry.OptionalRetry(state,sha).progress()['status']=='failed'
    assert not sync.payload_publication_pending(state.parent)
