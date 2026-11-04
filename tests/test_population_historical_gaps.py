"""Retained20/21/22 counts; altered completeness/hold inputs are controls only."""
import copy
import hashlib
import json

import pytest

import cdr_population_history as history
from cdr_population_coverage import apply_population_coverage
from cdr_population_identity import retain_population_uncertainty
from cdr_population_recovery import population_recovery_requests
from cdr_population_sanity import compare_population_counts
from tests.test_cdr_population_bootstrap import observed


def reconstructed(monkeypatch):
    snapshots={day:observed(day) for day in ('2026-10-20','2026-10-21')}
    monkeypatch.setattr(history,'historical_pointer',
        lambda state,day,budget:{'observation_date':day} if day in snapshots else None)
    return history.historical_findings(observed('2026-10-22')[2],snapshots['2026-10-21'],'.',
        '2026-10-22',lambda pointer:snapshots[pointer['observation_date']],lambda **kw:None)


def bound_report(tmp_path,findings):
    observation=observed('2026-10-22')[0]
    value={'run_date':'2026-10-22','compared_against':'2026-10-21',
        'provider_population':{'status':'WARN','findings':copy.deepcopy(findings),
                              'baseline':observed('2026-10-21')[1]}}
    def write():
        raw=json.dumps(value).encode();(tmp_path/'provider-population-report.json').write_bytes(raw)
        observation['contract']['artifacts']=[{'path':'provider-population-report.json',
            'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}]
    observation['export_root']=tmp_path
    write()
    return observation,value,write


def test_verified_zero_gap_is_retained_until_actual_current_index_proves_recovery(monkeypatch):
    findings,scope=reconstructed(monkeypatch)
    bank=next(row for row in findings if row['provider']=='BankSA')
    assert bank['products_curr']==20 and bank['rates_curr']==290
    assert bank['last_nonempty']=={'observation_date':'2026-10-20','products':20,'rates':290}
    absence=bank['historical_absence']
    assert absence['products']==absence['rates']==0
    assert absence['provider_identity']['source_observation']==observed('2026-10-21')[1]
    assert scope['status']=='INCOMPLETE'  # Only retained20/21 are provided.
    actual=observed('2026-10-22')[0]['status']
    control=copy.deepcopy(actual)
    # The real22Oct index is complete. This metadata control changes no count/row.
    control['index_diagnostics']['BankSA']['pagination_complete']=False
    held=retain_population_uncertainty({'status':'WARN','findings':copy.deepcopy(findings)},control)
    assert 'BankSA' in {row['provider'] for row in held['findings']}
    cleared=retain_population_uncertainty({'status':'WARN','findings':copy.deepcopy(findings)},actual)
    assert 'BankSA' not in {row['provider'] for row in cleared['findings']}


def test_reconstructed_nonempty_hold_never_grants_a_new_probe(tmp_path,monkeypatch):
    findings,_=reconstructed(monkeypatch)
    bank=next(row for row in findings if row['provider']=='BankSA')
    assert not bank.get('carried_unresolved')  # No claimed historical persisted hold.
    observation,_,_=bound_report(tmp_path,[bank])
    providers={row['provider_dir']:row for row in observation['status']['provider_states']}
    assert population_recovery_requests(observation,providers)==[]


@pytest.mark.parametrize('fault',['uid','endpoint','nonzero','date','missing_source','bad_identity','bad_source'])
def test_invalid_zero_gap_proof_cannot_supply_recovery_authority(tmp_path,monkeypatch,fault):
    findings,_=reconstructed(monkeypatch)
    bank=next(row for row in findings if row['provider']=='BankSA')
    observation,value,write=bound_report(tmp_path,[bank])
    absence=value['provider_population']['findings'][0]['historical_absence']
    if fault=='uid':absence['provider_identity']['provider_uid']='mismatched-control'
    elif fault=='endpoint':absence['provider_identity']['endpoint_url']='https://invalid.example/control'
    elif fault=='nonzero':absence['products']=1  # Invalid proof control; not a business observation.
    elif fault=='date':absence['provider_identity']['source_observation']=observed('2026-10-20')[1]
    elif fault=='missing_source':value['provider_population']['findings'][0]['provider_identity'].pop('source_observation')
    elif fault=='bad_identity':absence['provider_identity']=[]
    else:absence['provider_identity']['source_observation']=[]
    write()
    providers={row['provider_dir']:row for row in observation['status']['provider_states']}
    with pytest.raises(ValueError,match='historical population baseline'):
        population_recovery_requests(observation,providers)


def test_gap_proof_survives_canonical_projection_and_adjacent_count_comparison(tmp_path,monkeypatch):
    findings,_=reconstructed(monkeypatch)
    bank=next(row for row in findings if row['provider']=='BankSA')
    _,value,_=bound_report(tmp_path,[bank])
    providers=copy.deepcopy(observed('2026-10-22')[0]['status']['provider_states'])
    flags=apply_population_coverage(tmp_path,'2026-10-22',providers)
    assert flags[0]['historical_absence']==bank['historical_absence']
    assert flags[0]['historical_baseline']==bank['historical_baseline']
    assert flags[0]['last_nonempty']==bank['last_nonempty']
    # Pure carried-hold control over actual adjacent21/22 count maps.
    report=compare_population_counts(observed('2026-10-22')[2],observed('2026-10-21')[2],flags)
    carried=next(row for row in report['findings'] if row['provider']=='BankSA')
    assert carried['products_prev']==0 and carried['last_nonempty']['products']==20
    assert carried['historical_absence']==bank['historical_absence']
    assert carried['historical_baseline']==bank['historical_baseline']
    value['provider_population']['findings']=[carried]
    raw=json.dumps(value).encode();(tmp_path/'provider-population-report.json').write_bytes(raw)


def test_old_complete_stamp_does_not_bypass_corrected_gap_semantics(tmp_path):
    observation=observed('2026-10-21')[0];observation['export_root']=tmp_path
    value={'run_date':'2026-10-21','provider_population':{'status':'PASS',
        'bootstrap_history':{'status':'COMPLETE','lookback_days':7}}}
    raw=json.dumps(value).encode();(tmp_path/'provider-population-report.json').write_bytes(raw)
    observation['contract']['artifacts'].append({'path':'provider-population-report.json',
        'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
    assert history.bootstrap_verified(observation) is False


@pytest.mark.parametrize('complete_between',[False,True])
def test_repeated_gap_lineage_keeps_original_loss_until_complete_index(complete_between):
    # Pure lineage-protocol control, not additional dated business observations.
    # Count values/UID/endpoint come unchanged from retained Westpac20/21/22.
    # The ordinal labels exercise ordering only, never finalization/authority.
    def control(ordinal,capture_day,complete):
        observation,baseline,counts=observed(capture_day)
        baseline['observation_date']=f'control-{ordinal}'
        observation['status']['index_diagnostics']={'Westpac':{
            'pagination_complete':complete,'unique_products':counts[0].get('Westpac',0)}}
        return observation,baseline,tuple({'Westpac':group['Westpac']} if 'Westpac' in group else {} for group in counts)
    first=control(1,'2026-10-20',True)
    first_zero=control(2,'2026-10-22',True)
    partial=control(3,'2026-10-21',complete_between)
    second_zero=control(4,'2026-10-22',True)
    current=observed('2026-10-21')[2]
    findings,seen,closed=[],set(),set()
    history._retain_gap_findings(findings,seen,closed,*partial,[second_zero],second_zero[0],current,lambda:None)
    history._retain_gap_findings(findings,seen,closed,*first,
        [second_zero,partial,first_zero],second_zero[0],current,lambda:None)
    assert len(findings)==1
    row=findings[0]
    assert row['last_nonempty']['observation_date']==('control-3' if complete_between else 'control-1')
    assert row['last_nonempty']['products']==(15 if complete_between else 24)
    assert row['last_nonempty']['rates']==(78 if complete_between else 270)
    assert row['historical_absence']['provider_identity']['source_observation']['observation_date']==(
        'control-4' if complete_between else 'control-2')
    # Returning to zero preserves original proof while adjacent counts stay15/78.
    carried=compare_population_counts(observed('2026-10-22')[2],observed('2026-10-21')[2],findings)
    westpac=next(item for item in carried['findings'] if item['provider']=='Westpac')
    assert westpac['products_prev']==15 and westpac['rates_prev']==78
    assert westpac['historical_absence']==row['historical_absence']
    assert westpac['last_nonempty']==row['last_nonempty']
