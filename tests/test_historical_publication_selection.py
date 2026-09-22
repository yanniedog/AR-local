import json

import pytest

from cdr_finalization import finalize_observation
from tests.test_irreplaceable_finalization import make_export, DATE
from tests.test_reconciled_publication_source import finalized
from tests.test_app_payload_observation_gate import _load_backfill


def complete(tmp_path, revision='complete'):
    exports=tmp_path/'runs'/DATE/'_revisions'/revision/'_exports'
    make_export(exports, failures=0)
    state=tmp_path/'state'
    marker=finalize_observation(exports,state,state/f'{DATE}-{revision}.done.json',
        observation_date=DATE,result={'run_date':DATE,'banks_counts':{'rates':7}})
    return exports,state,marker


def advance_pointer(state):
    path=state/'observation-pointers-v2/latest-observation.json'
    pointer=json.loads(path.read_bytes());pointer['observation_date']='2026-08-15'
    path.write_text(json.dumps(pointer),encoding='utf8')


@pytest.mark.parametrize('force',[False,True])
def test_historical_rejected_repair_never_replaces_selected_source(tmp_path,force,monkeypatch):
    import app_payload_observation_gate as gate
    from cdr_export_contract import load_contract
    selected,state,_=finalized(tmp_path,bounded=True)
    _,_,marker=finalized(tmp_path,revision='diminished')
    rejected=load_contract(state/marker['export_contract_path'])
    monkeypatch.setattr(gate,'contract_for_run_date',lambda *a:rejected)
    advance_pointer(state)
    allowed,_,_,exports=_load_backfill().publication_candidate(state,DATE,force=force)
    assert allowed and exports==selected


@pytest.mark.parametrize('force',[False,True])
@pytest.mark.parametrize('fault',['artifact','missing_marker'])
def test_complete_revision_requires_exact_finalized_artifacts(tmp_path,force,fault):
    exports,state,_=complete(tmp_path)
    if fault=='artifact':(exports/'banks.json').write_text('{"changed":true}',encoding='utf8')
    else:(state/f'{DATE}-complete.done.json').unlink()
    assert not _load_backfill().observation_gate(state,DATE,force=force)[0]


def test_valid_complete_revision_has_no_failure_histogram_requirement(tmp_path):
    _,state,_=complete(tmp_path)
    assert _load_backfill().observation_gate(state,DATE,force=False)[:2]==(True,'complete')


def test_default_non_pi_developer_copy_needs_no_systemd(tmp_path,monkeypatch):
    import app_payload_backfill_window as guard
    monkeypatch.delenv('AR_LOCAL_DATA_ROOT',raising=False)
    monkeypatch.delenv('AR_LOCAL_PORTABLE_ROOT',raising=False)
    monkeypatch.setattr(guard,'data_runs_root',lambda _:tmp_path/'runs')
    monkeypatch.setattr(guard,'_unit_properties',lambda:pytest.fail('Developer copy consulted systemd'))
    guard.require_backfill_window(tmp_path/'runs',tmp_path)


def test_historical_selection_replays_acceptances_and_rejections(tmp_path):
    finalized(tmp_path)
    finalized(tmp_path,bounded=True,revision='better')
    rejected,state,_=finalized(tmp_path,revision='worse')
    selected,_,_=finalized(tmp_path,status='404',bounded=True,revision='equally-good')
    advance_pointer(state)
    (rejected/'banks.json').write_text('unselected artifact is not a publication source',encoding='utf8')
    allowed,_,_,exports=_load_backfill().publication_candidate(state,DATE,force=False)
    assert allowed and exports==selected


@pytest.mark.parametrize('fault',['missing','changed_bytes','event_binding','duplicate','wrong_type'])
def test_historical_selection_evidence_corruption_cannot_be_forced(tmp_path,fault):
    import hashlib
    from cdr_atomic import canonical_json_bytes
    finalized(tmp_path)
    _,state,_=finalized(tmp_path,bounded=True,revision='better')
    advance_pointer(state)
    path=next((state/'observation-selections-v1'/DATE).glob('*.json'))
    value=json.loads(path.read_bytes())
    if fault=='missing':path.unlink()
    elif fault=='changed_bytes':
        value['selected']=False;path.write_text(json.dumps(value),encoding='utf8')
    else:
        if fault=='event_binding':
            value['candidate_event_digest']='0'*64;path.unlink()
        elif fault=='wrong_type':
            value=[];path.unlink()
        else:value['reason']='duplicate candidate decision'
        raw=canonical_json_bytes(value)
        (path.parent/(hashlib.sha256(raw).hexdigest()+'.json')).write_bytes(raw)
    assert not _load_backfill().publication_candidate(state,DATE,force=True)[0]


def test_explicit_runtime_root_equal_to_repo_still_requires_supervision(tmp_path,monkeypatch):
    import app_payload_backfill_window as guard
    monkeypatch.setenv('AR_LOCAL_DATA_ROOT',str(tmp_path))
    monkeypatch.setattr(guard,'data_runs_root',lambda _:tmp_path/'runs')
    monkeypatch.setattr(guard,'_unit_properties',lambda:(_ for _ in ()).throw(RuntimeError('supervisor required')))
    with pytest.raises(RuntimeError,match='supervisor required'):
        guard.require_backfill_window(tmp_path/'runs',tmp_path)
