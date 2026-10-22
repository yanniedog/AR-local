"""Population loss survives date, register and index boundaries without new authority."""
import json
import sqlite3

import pytest

from app_payload_observation_gate import publication_allowed
from cdr_finalization import finalize_observation
from cdr_ingest_sanity import write_sanity_report
from cdr_observation_selection import selected_observation
from cdr_population_recovery import population_recovery_requests
from tests.test_cdr_population_sanity import database,finalized_previous,next_export

DAY='2026-10-15'


def population(root):
    return json.loads((root/'provider-population-report.json').read_bytes())['provider_population']


def seal(root,state,day):
    return finalize_observation(root,state,state/f'{day}.done.json',observation_date=day,
        result={'run_date':day,'banks_counts':{'rates':7}})


def current_register(root,mode):
    status=json.loads((root/'ingest-status.json').read_bytes())
    if mode=='absent':
        status['provider_states']=[{'provider_uid':'other-provider','provider_dir':'Other',
            'state':'complete','failure_records':0}]
        status['index_diagnostics']={'Other':{'pagination_complete':True,'unique_products':3}}
    elif mode=='failed':
        status['index_diagnostics']['Westpac']['pagination_complete']=False
        status.update(total=1,by_provider={'Westpac':1},incomplete=True,
            unresolved_requests_complete=True,unresolved_requests=[{'provider_dir':'Westpac',
                'phase':'products_index','url':'https://bank.example/cds-au/v1/banking/products','status':500}])
        status['provider_states'][0].update(state='failed',failure_records=1)
    elif mode=='nonempty':
        status['index_diagnostics']['Westpac']['unique_products']=32
    (root/'ingest-status.json').write_text(json.dumps(status))
    return status


@pytest.mark.parametrize('use_persistent',[False,True])
@pytest.mark.parametrize('mode',['empty','failed','absent','nonempty'])
@pytest.mark.parametrize('prior_nonempty',[False,True])
def test_current_population_not_old_rows_and_unknown_register_does_not_clear_loss(tmp_path,use_persistent,mode,prior_nonempty):
    previous,state=finalized_previous(tmp_path,include_provider=prior_nonempty)
    current=next_export(tmp_path,DAY,include_provider=False)
    status=current_register(current,mode);original=(current/'ingest-status.json').read_bytes()
    custom=tmp_path/'persistent.sqlite'
    database(custom,include_provider=True,run_date='2026-10-14')
    write_sanity_report(current,DAY,tmp_path/'runs',state_dir=state,
        db_path=custom if use_persistent else None)
    report=population(current)
    held=prior_nonempty and mode!='nonempty'
    expected = 'WARN' if held else ('PASS' if prior_nonempty else 'UNKNOWN')
    assert report['status']==expected
    if not prior_nonempty:
        assert report['reason']=='population_bootstrap_incomplete'
        assert report['bootstrap_history']['missing_dates']
    completion=seal(current,state,DAY)
    observation=selected_observation(state,DAY);coverage=observation['contract']['coverage']
    assert coverage['failure_records']==status['total']
    assert coverage['providers_attempted']==coverage['providers_registered']==1
    assert (current/'ingest-status.json').read_bytes()==original
    if not held:
        assert 'provider_population_unverified' not in coverage
        return
    assert completion['observation_state']=='partial'
    assert publication_allowed(observation['contract'])==(False,'unverified_provider_population')
    warning=coverage['provider_population_unverified'][0]
    assert warning['provider']=='Westpac' and warning['provider_uid']=='provider-a'
    if mode=='absent':
        assert coverage['providers_failed']==0  # Do not fabricate a register attempt.
        assert warning['current_register_membership']=='absent'
    # No prior endpoint is eligible when the current register omitted this holder.
    providers={} if mode=='absent' else {'Westpac':{'provider_uid':'provider-a',
        'endpoint_url':'https://bank.example/cds-au/v1/banking/products'}}
    requests=population_recovery_requests(observation,providers)
    assert len(requests)==int(mode=='empty')
    following=next_export(tmp_path,'2026-10-16',include_provider=False)
    current_register(following,mode)
    write_sanity_report(following,'2026-10-16',tmp_path/'runs',state_dir=state)
    seal(following,state,'2026-10-16')
    second=selected_observation(state,'2026-10-16')
    assert publication_allowed(second['contract'])==(False,'unverified_provider_population')
    assert second['contract']['coverage']['provider_population_unverified'][0]['last_nonempty']['observation_date']=='2026-10-14'


def test_both_comparison_databases_exclude_other_observation_dates(tmp_path):
    from cdr_population_sanity import population_report
    prior=tmp_path/'prior.sqlite';current=tmp_path/'current.sqlite'
    database(prior,include_provider=True,run_date='2026-10-14')
    database(current,include_provider=True,run_date='2026-10-14')
    with sqlite3.connect(prior) as db:
        db.execute("insert into bank_products values('Older-only','p1','2026-10-13')")
    with sqlite3.connect(current) as db:
        db.execute("insert into bank_products values('Westpac','future','2026-10-16')")
    report=population_report(current,prior,current_date='2026-10-15',prior_date='2026-10-14')
    assert report['status']=='WARN'
    assert [(r['provider'],r['products_prev'],r['products_curr']) for r in report['findings']]==[('Westpac',32,0)]


def test_legacy_custom_only_comparison_is_still_date_scoped_and_read_only(tmp_path):
    previous,state=finalized_previous(tmp_path)
    current=next_export(tmp_path,DAY,include_provider=False)
    (current/'local-cdr.sqlite').unlink()  # Unfinalized fixture, before any contract.
    custom=tmp_path/'persistent.sqlite';database(custom,include_provider=True,run_date='2026-10-14')
    before=custom.read_bytes()
    write_sanity_report(current,DAY,tmp_path/'runs',state_dir=state,db_path=custom)
    assert population(current)['status']=='WARN'
    assert custom.read_bytes()==before and not (current/'local-cdr.sqlite').exists()


@pytest.mark.parametrize('uid,expected',[('provider-a','PASS'),('replacement-identity','WARN')])
def test_nonempty_index_resolves_only_the_same_prior_holder_identity(tmp_path,uid,expected):
    previous,state=finalized_previous(tmp_path)
    current=next_export(tmp_path,DAY,include_provider=False)
    status=json.loads((current/'ingest-status.json').read_bytes())
    status['provider_states'][0].update(provider_uid=uid,provider_dir='Renamed')
    status['index_diagnostics']={'Renamed':{'pagination_complete':True,'unique_products':32}}
    (current/'ingest-status.json').write_text(json.dumps(status))
    write_sanity_report(current,DAY,tmp_path/'runs',state_dir=state)
    assert population(current)['status']==expected
    seal(current,state,DAY)
    observation=selected_observation(state,DAY)
    assert bool(observation['contract']['coverage'].get('provider_population_unverified'))==(expected=='WARN')


def test_more_missing_prior_holders_than_current_register_members_are_retained(tmp_path):
    from tests.test_irreplaceable_finalization import make_export
    prior=tmp_path/'runs/2026-10-14/_exports';make_export(prior,observation_date='2026-10-14')
    database(prior/'local-cdr.sqlite',include_provider=True,run_date='2026-10-14')
    with sqlite3.connect(prior/'local-cdr.sqlite') as db:
        db.execute("insert into bank_products values('Second missing holder','p1','2026-10-14')")
    state=tmp_path/'state';seal(prior,state,'2026-10-14')
    current=next_export(tmp_path,DAY,include_provider=False);current_register(current,'absent')
    write_sanity_report(current,DAY,tmp_path/'runs',state_dir=state);seal(current,state,DAY)
    observation=selected_observation(state,DAY)
    warnings=observation['contract']['coverage']['provider_population_unverified']
    assert {r['provider'] for r in warnings}=={'Westpac','Second missing holder'}
    assert observation['contract']['coverage']['providers_attempted']==1
    assert population_recovery_requests(observation,{})==[]


@pytest.mark.parametrize('uid,index_complete,held',[
    ('provider-a',True,False),('provider-a',False,True),('replacement-identity',True,True)])
def test_returning_rows_alone_do_not_erase_a_carried_identity_hold(tmp_path,uid,index_complete,held):
    previous,state=finalized_previous(tmp_path)
    first=next_export(tmp_path,DAY,include_provider=False)
    write_sanity_report(first,DAY,tmp_path/'runs',state_dir=state);seal(first,state,DAY)
    current=next_export(tmp_path,'2026-10-16',include_provider=True)
    status=json.loads((current/'ingest-status.json').read_bytes())
    status['provider_states'][0]['provider_uid']=uid
    status['index_diagnostics']['Westpac']['pagination_complete']=index_complete
    (current/'ingest-status.json').write_text(json.dumps(status))
    write_sanity_report(current,'2026-10-16',tmp_path/'runs',state_dir=state);seal(current,state,'2026-10-16')
    observation=selected_observation(state,'2026-10-16')
    assert bool(observation['contract']['coverage'].get('provider_population_unverified'))==held
    if held:
        assert publication_allowed(observation['contract'])==(False,'unverified_provider_population')
