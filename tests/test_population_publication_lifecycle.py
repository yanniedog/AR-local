"""Exercise real marker/ledger/pending transitions without publishing or recapturing."""
import json
from unittest.mock import Mock

import pytest

import pi_daily_sync as sync
from cdr_atomic import atomic_write_json
from cdr_observation_selection import selected_observation
from tests.test_cdr_same_day_selection import DATE,make_export,finish


def held(root):
    # Protocol-shell fixture: test policy/pending control, not fabricated source counts.
    atomic_write_json(root/'provider-population-report.json',{'run_date':DATE,
        'provider_population':{'status':'WARN','findings':[{'provider':'Provider',
            'code':'provider_population_disappeared','population_known':False,
            'disposition':'UNVERIFIED_SOURCE_ABSENCE'}]}})


def runtime(tmp_path,monkeypatch,*,replacement_held=False,old_held=True,bad_source=False):
    state=tmp_path/'state';primary=tmp_path/'runs'/DATE/'_exports'
    make_export(primary,['p1','p2'],failures=0)
    if old_held:held(primary)
    finish(primary,state,'done');old=selected_observation(state,DATE)
    monkeypatch.setattr(sync,'data_state_root',lambda _:state)
    sync.mark_payload_publication_pending(tmp_path,'publication_started',old['pointer'])
    previous=sync.read_payload_publication_pending(tmp_path)
    revision=tmp_path/'runs'/DATE/'_revisions/recovered/_exports'
    status=make_export(revision,['p1','p2','p3'],failures=0)
    status['same_day_reuse']={'schema_version':1,'reconciled':True,'withdrawals':[],
        'baseline':{'generation_id':old['contract']['generation_id'],
            'ledger_event_digest':old['event']['event_digest'],
            'export_contract_digest':'0'*64 if bad_source else old['contract']['contract_digest']}}
    atomic_write_json(revision/'ingest-status.json',status)
    if replacement_held:held(revision)
    marker=finish(revision,state,'revision.recovered',old['contract']['generation_id'])
    new=selected_observation(state,DATE)
    assert new['contract']['generation_id']==marker['generation_id']
    monkeypatch.setattr(sync,'ensure_runtime_data_writable',lambda _:None)
    monkeypatch.setattr(sync,'pause_dashboard_for_ingest',lambda:False)
    monkeypatch.setattr(sync,'refresh_economic_data',lambda _:None)
    monkeypatch.setattr(sync,'queue_drive_backup',lambda _:None)
    monkeypatch.setattr(sync,'run_checked',Mock())
    monkeypatch.setattr(sync,'payload_retry_window_reason',lambda:'')
    monkeypatch.setenv('AR_LOCAL_APP_PAYLOAD','1')
    return state,previous,old,new


@pytest.mark.parametrize('outcome,replacement_held',[
    ('published',False),('failed',False),('withheld',True),('interrupted',False)])
@pytest.mark.parametrize('already_queued',[False,True])
def test_selected_recovery_supersedes_only_its_own_policy_hold_before_publication(tmp_path,monkeypatch,outcome,replacement_held,already_queued):
    state,previous,old,new=runtime(tmp_path,monkeypatch,replacement_held=replacement_held)
    if already_queued:
        previous['queued_pointers']=[new['pointer']]
        atomic_write_json(sync.payload_publication_pending_path(tmp_path),previous)
    original_events={p:p.read_bytes() for p in (state/'ledger-v2').rglob('*.json')}
    def publish(repo,pointer):
        assert pointer==new['pointer']
        assert sync.pending_publication_pointer(repo)==pointer
        if outcome=='interrupted':raise KeyboardInterrupt
        return outcome
    monkeypatch.setattr(sync,'maybe_publish_app_payload',publish)
    if outcome=='interrupted':
        with pytest.raises(KeyboardInterrupt):sync.main(['--banks-only'])
    else:assert sync.main(['--banks-only'])==0
    if outcome=='published':assert not sync.payload_publication_pending(tmp_path)
    else:assert sync.pending_publication_pointer(tmp_path)==new['pointer']
    receipts=list((state/'population-publication-supersessions-v1').glob('*.json'))
    assert len(receipts)==1
    receipt=json.loads(receipts[0].read_bytes())
    assert receipt['previous_pending']==previous
    assert receipt['replacement_pointer']==new['pointer']
    assert receipt['publication_confirmed'] is False  # Retirement is not an upload receipt.
    assert all(p.read_bytes()==raw for p,raw in original_events.items())
    if outcome=='failed':
        monkeypatch.setattr(sync,'maybe_publish_app_payload',lambda repo,pointer:
            'published' if pointer==new['pointer'] else pytest.fail('retry targeted superseded source'))
        assert sync.main(['--publish-existing-payload'])==0
        assert not sync.payload_publication_pending(tmp_path)


@pytest.mark.parametrize('fault',['other_queue','selection_retry','publishable_old','wrong_source'])
def test_other_or_unproven_pending_work_is_never_retired(tmp_path,monkeypatch,fault):
    state,previous,old,new=runtime(tmp_path,monkeypatch,old_held=fault!='publishable_old',
        bad_source=fault=='wrong_source')
    if fault=='other_queue':previous['queued_pointers']=[{'observation_date':'2026-09-06'}]
    elif fault=='selection_retry':previous['selection_retry']={}
    atomic_write_json(sync.payload_publication_pending_path(tmp_path),previous)
    sync.mark_payload_publication_pending(tmp_path,'publication_started',new['pointer'],
                                          allow_policy_supersession=True)
    pending=sync.read_payload_publication_pending(tmp_path)
    assert pending['pointer']==old['pointer']
    assert new['pointer'] in pending['queued_pointers']
    if fault=='other_queue':assert previous['queued_pointers'][0] in pending['queued_pointers']
    assert not (state/'population-publication-supersessions-v1').exists()


def test_crash_after_audit_receipt_before_pending_write_is_idempotent(tmp_path,monkeypatch):
    import pi_population_publication as policy
    state,previous,old,new=runtime(tmp_path,monkeypatch)
    before=sync.payload_publication_pending_path(tmp_path).read_bytes()
    original=policy.atomic_write_json
    def interrupted(*args,**kwargs):
        original(*args,**kwargs)
        raise OSError('interrupted after immutable receipt')
    with monkeypatch.context() as fault:
        fault.setattr(policy,'atomic_write_json',interrupted)
        with pytest.raises(OSError,match='after immutable'):
            sync.mark_payload_publication_pending(tmp_path,'publication_started',new['pointer'],
                                                  allow_policy_supersession=True)
    assert sync.payload_publication_pending_path(tmp_path).read_bytes()==before
    sync.mark_payload_publication_pending(tmp_path,'publication_started',new['pointer'],
                                          allow_policy_supersession=True)
    assert sync.pending_publication_pointer(tmp_path)==new['pointer']
    assert len(list((state/'population-publication-supersessions-v1').glob('*.json')))==1


def test_policy_supersession_preserves_both_sources_retry_backoff(tmp_path,monkeypatch):
    import pi_payload_retry_policy as policy
    from tests.test_pi_same_day_recovery import NOW
    state,previous,old,new=runtime(tmp_path,monkeypatch)
    monkeypatch.setattr(policy,'data_state_root',lambda _:state)
    paths=[]
    for pointer in [old['pointer'],new['pointer']]:
        record={'pointer':pointer}
        reservation=policy.retry_admission(tmp_path,record,now_utc=NOW,reserve=True)
        assert reservation['status']=='ready'
        policy.finish_retry(tmp_path,reservation,succeeded=False,reason='retained_upload_failure',now_utc=NOW)
        paths.append(policy.retry_state_path(tmp_path,reservation['source_key']))
    before={p:p.read_bytes() for p in paths}
    sync.mark_payload_publication_pending(tmp_path,'publication_started',new['pointer'],
                                          allow_policy_supersession=True)
    assert sync.pending_publication_pointer(tmp_path)==new['pointer']
    assert all(p.read_bytes()==raw for p,raw in before.items())
    assert policy.retry_admission(tmp_path,{'pointer':new['pointer']},now_utc=NOW)['reason']=='publication_retry_cooldown'


@pytest.mark.parametrize('entry',['watchdog','daily_worker'])
def test_interruption_before_publication_intent_is_reconciled_without_new_capture(tmp_path,monkeypatch,entry):
    import pi_cdr_recovery as recovery
    import ar_local_pi_runtime
    from types import SimpleNamespace
    from pi_daily_repair_work import repair
    from tests.test_pi_same_day_recovery import NOW,FixedDatetime
    state,previous,old,new=runtime(tmp_path,monkeypatch)
    monkeypatch.setattr(ar_local_pi_runtime,'data_state_root',lambda _:state)
    monkeypatch.setattr(recovery,'data_state_root',lambda _:state)
    monkeypatch.setattr(recovery,'recovery_block_reason',lambda *a,**kw:'')
    monkeypatch.setattr(recovery,'datetime',FixedDatetime)
    probe=Mock(side_effect=AssertionError('must settle selected publication, not probe'))
    monkeypatch.setattr(recovery,'probe_register',probe)
    launch=Mock()
    if entry=='watchdog':
        result=recovery.run_same_day_recovery(tmp_path,now_utc=NOW,dry_run=False,launch=launch)
        assert result['status']=='pending_publication_must_settle'
    else:
        watchdog=SimpleNamespace(REPO_ROOT=tmp_path,read_payload_publication_pending=sync.read_payload_publication_pending,
            run_payload_retry=Mock(return_value={'status':'published'}),run_recovery_ingest=launch)
        result=repair(watchdog,recovery,DATE,NOW)
        assert result['status']=='publication_attempted'
        watchdog.run_payload_retry.assert_called_once_with(False)
    assert sync.pending_publication_pointer(tmp_path)==new['pointer']
    assert not any(p.name.endswith('.reserved.json') for p in (state/'cdr-recovery-v1').rglob('*'))
    probe.assert_not_called();launch.assert_not_called()
