"""An empty-index warning can use only the existing single-day repair envelope."""
import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from cdr_population_recovery import population_probe_has_progress, population_recovery_requests
import pi_cdr_recovery as recovery
from tests.test_pi_same_day_recovery import DATE, NOW, PROVIDER, stage

FIXTURES = Path(__file__).parent/'fixtures/ingest-capture-20261015'


def bound_population(tmp_path, observation):
    finding = {'code':'provider_population_disappeared','provider':PROVIDER['provider_dir'],
        'disposition':'UNVERIFIED_SOURCE_ABSENCE','population_known':False,
        'products_prev':32,'products_curr':0,'rates_prev':379,'rates_curr':0}
    value={'run_date':DATE,'compared_against':'2026-09-06',
        'provider_population':{'status':'WARN','findings':[finding]}}
    raw=json.dumps(value).encode();path=tmp_path/'sanity-report.json';path.write_bytes(raw)
    observation['export_root']=tmp_path
    observation['contract']['artifacts']=[{'path':'sanity-report.json','bytes':len(raw),
        'sha256':hashlib.sha256(raw).hexdigest()}]
    observation['status']['index_diagnostics']={PROVIDER['provider_dir']:{'pagination_complete':True,'unique_products':0}}
    return value,path


def test_verified_anomaly_creates_one_current_index_request_not_a_failure(tmp_path,monkeypatch):
    _,observation=stage(monkeypatch,tmp_path);bound_population(tmp_path,observation)
    before=copy.deepcopy(observation['status'])
    requests=population_recovery_requests(observation,{PROVIDER['provider_dir']:PROVIDER})
    assert requests==[{'provider_dir':PROVIDER['provider_dir'],'provider_uid':PROVIDER['provider_uid'],
        'phase':'products_index','product_id':'','url':PROVIDER['endpoint_url'],
        'status':200,'failure_category':'provider_population_unverified'}]
    assert observation['status']==before


def test_tampered_comparison_cannot_authorize_a_probe(tmp_path,monkeypatch):
    _,observation=stage(monkeypatch,tmp_path);_,path=bound_population(tmp_path,observation)
    path.write_bytes(b'{}')
    with pytest.raises(ValueError):
        population_recovery_requests(observation,{PROVIDER['provider_dir']:PROVIDER})


def test_no_fresh_data_is_inferred_from_a_second_empty_source_response():
    empty=json.loads((FIXTURES/'westpac-empty.json').read_bytes())
    prior=json.loads((FIXTURES/'westpac-prior-page1.json').read_bytes())
    assert not population_probe_has_progress({'ok':True,'data':empty})
    # The retained nonempty page is an offline progress control, not today's replacement.
    assert population_probe_has_progress({'ok':True,'data':prior})
    assert not population_probe_has_progress({'ok':False,'data':prior})


def test_complete_label_does_not_skip_contract_bound_empty_population(tmp_path,monkeypatch):
    state,observation=stage(monkeypatch,tmp_path);bound_population(tmp_path,observation)
    observation['contract']['observation_state']='complete'
    observation['status']['unresolved_requests']=[]
    seen=[]
    def probe_due(root,obs,providers,requests,*a,**kw):
        seen.extend(requests);return [],[]
    monkeypatch.setattr(recovery,'_probe_due',probe_due)
    launch=Mock()
    result=recovery.run_same_day_recovery(tmp_path,now_utc=NOW,dry_run=False,launch=launch,daily_pass=True)
    assert result['status']=='upstream_gaps_remain'
    assert result['population_anomaly_providers']==[PROVIDER['provider_dir']]
    assert len(seen)==1 and seen[0]['failure_category']=='provider_population_unverified'
    assert result['failure_records']==1  # Original source aggregate is not edited.
    launch.assert_not_called()
    assert not any(row['kind']=='capture' for row in recovery._history(state/'cdr-recovery-v1'/DATE,DATE))


@pytest.mark.parametrize('fault',['unknown','contradiction','unknown_provider','not_zero','bad_index','duplicate',
    'stale_date','same_prior_date','future_prior_date','invalid_date','missing_date','noncanonical_date'])
def test_semantically_invalid_bound_report_cannot_add_recovery_work(tmp_path,monkeypatch,fault):
    _,observation=stage(monkeypatch,tmp_path);value,path=bound_population(tmp_path,observation)
    population=value['provider_population'];finding=population['findings'][0]
    if fault=='unknown':population['status']='UNKNOWN'
    elif fault=='contradiction':population['status']='PASS'
    elif fault=='unknown_provider':finding['provider']='unregistered'
    elif fault=='not_zero':finding['products_curr']=True
    elif fault=='bad_index':observation['status']['index_diagnostics'][PROVIDER['provider_dir']]['unique_products']=1
    elif fault=='stale_date':value['run_date']='2026-09-06'
    elif fault=='same_prior_date':value['compared_against']=DATE
    elif fault=='future_prior_date':value['compared_against']='2026-09-08'
    elif fault=='invalid_date':value['run_date']='2026-99-07'
    elif fault=='missing_date':value.pop('compared_against')
    elif fault=='noncanonical_date':value['compared_against']='20260906'
    else:population['findings'].append(copy.deepcopy(finding))
    raw=json.dumps(value).encode();path.write_bytes(raw)
    observation['contract']['artifacts'][0].update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError):
        population_recovery_requests(observation,{PROVIDER['provider_dir']:PROVIDER})


@pytest.mark.parametrize('empty',[True,False])
def test_probe_does_not_turn_another_empty_response_into_capture_progress(tmp_path,monkeypatch,empty):
    state,observation=stage(monkeypatch,tmp_path);bound_population(tmp_path,observation)
    request=population_recovery_requests(observation,{PROVIDER['provider_dir']:PROVIDER})[0]
    request['request_key']=recovery._request_key(request)
    body=json.loads((FIXTURES/'westpac-empty.json').read_bytes())
    outcome={'ok':True,'data':body,'attempts':[{'status':200}],'body_sha256':'a'*64}
    if not empty:outcome.update(ok=False,failure_category='upstream_dependency_failure')
    monkeypatch.setattr(recovery,'probe_request',lambda *a,**k:copy.deepcopy(outcome))
    positive,reports=recovery._probe_due(state/'cdr-recovery-v1'/DATE,observation,
        {PROVIDER['provider_dir']:PROVIDER},[request],[],NOW)
    assert positive==[] and reports[0]['ok'] is False
    assert reports[0]['failure_category']==('provider_population_still_unverified' if empty else 'upstream_dependency_failure')
    assert 'data' not in reports[0]
