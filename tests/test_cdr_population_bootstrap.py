"""Replay retained 20/21 October metadata without inventing later observations."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

import cdr_population_history as history
from cdr_population_sanity import compare_population_counts
from cdr_population_identity import retain_population_uncertainty
from cdr_partial_index import partial_index_evidence
from cdr_population_recovery import population_recovery_requests

FIXTURES = Path(__file__).parent/'fixtures'
RETAINED = json.loads((FIXTURES/'ingest-capture-20261021/population-counts.json').read_bytes())


def observed(day):
    row = copy.deepcopy(next(r for r in RETAINED['observations'] if r['observation_date']==day))
    baseline = {'observation_date':day, 'generation_id':row['pointer']['generation_id'],
        'contract_digest':row['contract_digest'], 'database_sha256':row['database']['sha256'],
        'ledger_event_digest':row['ledger_event_digest']}
    counts = tuple({p:r[key] for p,r in row['counts'].items()} for key in ('products','rates'))
    observation = {'status':{'provider_states':row['provider_states']},
        'contract':{'observation_date':day,'artifacts':[row['database']]}}
    return observation, baseline, counts


def replay(monkeypatch, *, latest=None, budget=lambda:None, failure=None):
    snapshots = {day:observed(day) for day in ('2026-10-20','2026-10-21')}
    monkeypatch.setattr(history,'historical_pointer',
        lambda state,day,budget:{'observation_date':day} if day in snapshots else None)
    def load(pointer):
        if failure:
            raise failure
        return snapshots[pointer['observation_date']]
    return history.historical_findings(snapshots['2026-10-21'][2],
        latest or snapshots['2026-10-21'],Path('.'),'2026-10-22',load,budget)


def test_actual_counts_expose_loss_without_reclassifying_partial_populations():
    result = compare_population_counts(observed('2026-10-21')[2],observed('2026-10-20')[2])
    assert [(r['provider'],r['products_prev'],r['rates_prev']) for r in result['findings']]==[
        ('BankSA',20,290)]
    assert result['findings'][0]['population_known'] is False
    assert result['findings'][0]['disposition']=='UNVERIFIED_SOURCE_ABSENCE'


def test_legacy_zero_baseline_does_not_erase_verified_last_nonempty(monkeypatch):
    current = observed('2026-10-21')[2]
    assert compare_population_counts(current,current)['status']=='PASS'  # Original blindspot.
    findings,scope = replay(monkeypatch)
    assert len(findings)==1 and findings[0]['provider']=='BankSA'
    row = findings[0]
    assert row['last_nonempty']=={'observation_date':'2026-10-20','products':20,'rates':290}
    assert row['historical_baseline']==row['provider_identity']['source_observation']
    assert row['historical_baseline']['database_sha256']=='7202927a9edc051a410a84b7a21670fc3ce2d0613f8ca347dc257ab11bf660de'
    assert scope['status']=='INCOMPLETE' and scope['missing_dates']
    assert scope['scanned_dates']==['2026-10-21','2026-10-20']
    assert scope['lookback_days']==7 and scope['shared_deadline_seconds']==8
    carried = compare_population_counts(current,current,findings)
    assert carried['status']=='WARN' and carried['findings'][0]['products_prev']==0
    assert carried['findings'][0]['last_nonempty']==row['last_nonempty']
    assert carried['findings'][0]['provider_identity']==row['provider_identity']
    assert current==observed('2026-10-21')[2]


@pytest.mark.parametrize('fault',['uid','endpoint','duplicate_uid'])
def test_unverified_holder_changes_add_no_historical_probe_authority(monkeypatch,fault):
    latest = observed('2026-10-21')
    rows = latest[0]['status']['provider_states']
    bank = next(r for r in rows if r['provider_dir']=='BankSA')
    other = next(r for r in rows if r['provider_dir']=='Westpac')
    if fault=='uid': bank['provider_uid']=other['provider_uid']
    elif fault=='endpoint': bank['endpoint_url']=other['endpoint_url']
    else: rows.append(copy.deepcopy(bank))
    findings,scope = replay(monkeypatch,latest=latest)
    assert findings==[] and scope['status']=='INCOMPLETE'


@pytest.mark.parametrize('failure',[ValueError('unverified ledger'),OSError('unreadable database')])
def test_unverified_history_grants_no_finding(monkeypatch,failure):
    findings,scope = replay(monkeypatch,failure=failure)
    assert findings==[] and scope['status']=='INCOMPLETE'


def test_historical_authority_requires_an_original_registered_endpoint():
    old,baseline,prior = observed('2026-10-20')
    latest = observed('2026-10-21')[0]
    finding = compare_population_counts(observed('2026-10-21')[2],prior)['findings'][0]
    for status in (old['status'],latest['status']):
        next(row for row in status['provider_states'] if row['provider_dir']=='BankSA').pop('endpoint_url')
    with pytest.raises(ValueError,match='endpoint changed'):
        history._historical_finding(finding,old,baseline,latest)


@pytest.mark.parametrize('limit',[0,2])
def test_expired_budget_retains_only_already_verified_findings(monkeypatch,limit):
    calls = []
    def budget():
        calls.append(None)
        if len(calls)>limit:
            raise ValueError('expired')
    findings,scope = replay(monkeypatch,budget=budget)
    assert scope['status']=='INCOMPLETE'
    assert [r['provider'] for r in findings]==(['BankSA'] if limit else [])


@pytest.mark.parametrize('state,expected',[('UNKNOWN',False),('PASS',True),('WARN',True)])
def test_only_complete_bound_bootstrap_stamp_ends_rescan(tmp_path,state,expected):
    observation = observed('2026-10-21')[0]
    report = {'run_date':'2026-10-21','provider_population':{'status':state,
        'bootstrap_history':{'status':'COMPLETE','lookback_days':7}}}
    raw = json.dumps(report).encode()
    (tmp_path/'provider-population-report.json').write_bytes(raw)
    observation['export_root']=tmp_path
    assert history.bootstrap_verified(observation) is False  # Legacy contract has no report.
    observation['contract']['artifacts'].append({'path':'provider-population-report.json',
        'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
    assert history.bootstrap_verified(observation) is expected
    (tmp_path/'provider-population-report.json').write_bytes(raw+b' ')
    with pytest.raises(ValueError): history.bootstrap_verified(observation)


def test_rows_alone_do_not_clear_hold_and_legacy_generation_gets_no_probe(monkeypatch):
    findings,_ = replay(monkeypatch)
    population = {'status':'WARN','findings':findings}
    latest = observed('2026-10-21')[0]
    before = copy.deepcopy(findings)
    assert retain_population_uncertainty(population,latest['status'])['findings']==before
    assert population_recovery_requests(latest,{})==[]


def test_historical_sidecar_checks_current_registered_endpoint(tmp_path,monkeypatch):
    findings,_ = replay(monkeypatch)
    observation = observed('2026-10-21')[0]
    baseline = observed('2026-10-20')[1]
    report = {'run_date':'2026-10-21','compared_against':'2026-10-20',
        'provider_population':{'status':'WARN','findings':findings,'baseline':baseline}}
    raw = json.dumps(report).encode()
    (tmp_path/'provider-population-report.json').write_bytes(raw)
    observation['export_root']=tmp_path
    observation['contract']['artifacts'].append({'path':'provider-population-report.json',
        'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
    observation['status']['index_diagnostics']={'BankSA':{'pagination_complete':True,'unique_products':0}}
    bank = next(r for r in observation['status']['provider_states'] if r['provider_dir']=='BankSA')
    providers = {'BankSA':dict(bank)}
    assert len(population_recovery_requests(observation,providers))==1
    providers['BankSA']['endpoint_url']=next(r['endpoint_url']
        for r in observation['status']['provider_states'] if r['provider_dir']=='Westpac')
    assert population_recovery_requests(observation,providers)==[]
    report['provider_population']['findings'][0]['historical_baseline']['contract_digest']='0'*64
    raw = json.dumps(report).encode()
    (tmp_path/'provider-population-report.json').write_bytes(raw)
    observation['contract']['artifacts'][-1].update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError,match='historical population baseline'):
        population_recovery_requests(observation,providers)


def test_scan_interval_is_calendar_bound_when_selected_pointer_is_stale(monkeypatch):
    latest = observed('2026-10-20')
    findings,scope = replay(monkeypatch,latest=latest)
    assert scope['interval_end']=='2026-10-21'
    assert scope['scanned_dates']==['2026-10-21','2026-10-20']
    assert [r['provider'] for r in findings]==['BankSA']


@pytest.mark.parametrize('fault',['other_day','duplicate','other_namespace'])
def test_snapshot_paths_are_canonical_and_unique(tmp_path,fault):
    from app_payload_historical_source import historical_contract
    state = tmp_path/'state'
    path = state/'export-contracts-v2/2026-10-20'/observed('2026-10-20')[1]['generation_id']
    path = path.with_suffix('.json')
    paths = [path]
    if fault=='other_day': path = path.parent.parent/'2026-10-21'/path.name;paths=[path]
    elif fault=='duplicate': paths.append(path)
    else: paths=[state/'observation-selections-v1/2026-10-20'/path.name]
    with pytest.raises(ValueError,match='snapshot paths'):
        historical_contract(state,'2026-10-20',paths=paths,decision_paths=[],budget=lambda **kw:None)


def test_metadata_enumeration_stops_before_exceeding_generation_cap(tmp_path):
    for i in range(history.MAX_GENERATIONS_PER_DAY+1):
        (tmp_path/f'{i}.json').write_bytes(b'{}')  # Non-business metadata-boundary control.
    with pytest.raises(ValueError,match='metadata budget'):
        history._bounded_metadata(tmp_path,history.MAX_GENERATIONS_PER_DAY,65536,lambda:None)


def test_one_snapshot_contract_must_match_its_canonical_date(tmp_path,monkeypatch):
    import app_payload_historical_source as source
    state = tmp_path/'state'
    path = state/'export-contracts-v2/2026-10-20/contract.json'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'{}')  # Pure metadata path/date boundary control.
    monkeypatch.setattr(source,'load_contract',lambda *a,**kw:observed('2026-10-21')[0]['contract'])
    with pytest.raises(ValueError,match='another date'):
        source.historical_contract(state,'2026-10-20',paths=[path],decision_paths=[],budget=lambda **kw:None)


def test_expired_shared_budget_cannot_return_inherited_complete(monkeypatch):
    from cdr_population_baseline import _with_history
    latest = observed('2026-10-20')
    result = compare_population_counts(observed('2026-10-21')[2],latest[2])
    result['baseline']=latest[1]
    monkeypatch.setattr(history,'bootstrap_verified',lambda observation:True)
    def expired(**kw):raise ValueError('expired during report read')
    with pytest.raises(ValueError,match='expired'):
        _with_history(result,latest,observed('2026-10-21')[2],Path('.'),'2026-10-21',expired,0)
    assert 'bootstrap_history' not in result


def test_stale_pointer_cannot_inherit_a_complete_bootstrap_stamp(monkeypatch):
    from cdr_population_baseline import _with_history
    latest = observed('2026-10-20')
    current = observed('2026-10-21')[2]
    result = compare_population_counts(current,latest[2]);result['baseline']=latest[1]
    def forbidden(observation):pytest.fail('stale baseline inherited COMPLETE')
    monkeypatch.setattr(history,'bootstrap_verified',forbidden)
    monkeypatch.setattr(history,'historical_findings',lambda *a:([],
        {'status':'INCOMPLETE','missing_dates':['2026-10-21']}))
    report = _with_history(result,latest,current,Path('.'),'2026-10-22',lambda:None,None)
    assert report['status']=='WARN' and report['bootstrap_history']['status']=='INCOMPLETE'


def test_current_geelong_response_matches_retained_salvage_contract():
    raw = (FIXTURES/'ingest-capture-20261015/geelong-index.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='83e81987d7e9c142c0977cd6c308bb18430e2acfc05aedb6c63277057c845100'
    assert partial_index_evidence(json.loads(raw))=={'raw_records':18,'identified_records':17,
        'unidentified_records':1,'omitted_row_positions':[17],'unique_products':17}
