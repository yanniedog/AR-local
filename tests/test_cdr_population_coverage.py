"""Population uncertainty is canonical and cannot take the complete-publication shortcut."""
import copy
import json

import pytest

from app_payload_observation_gate import publication_allowed
from cdr_export_contract import load_contract
from cdr_finalization import finalize_observation
from tests.test_irreplaceable_finalization import make_export

DAY='2026-10-15'


def warning(export, *, provider='provider-a'):
    value={'run_date':DAY,'compared_against':'2026-10-14','provider_population':{
        'status':'WARN','findings':[{'provider':provider,'code':'provider_population_disappeared',
            'population_known':False,'disposition':'UNVERIFIED_SOURCE_ABSENCE',
            'products_prev':32,'products_curr':0,'rates_prev':379,'rates_curr':0}]}}
    (export/'sanity-report.json').write_text(json.dumps(value))


@pytest.mark.parametrize('http_failures',[0,1])
def test_loss_is_partial_and_publication_held_without_fabricating_http_failures(tmp_path,http_failures):
    export=tmp_path/'runs'/DAY/'_exports';make_export(export,failures=http_failures,observation_date=DAY)
    original=(export/'ingest-status.json').read_bytes();warning(export)
    state=tmp_path/'state'
    completion=finalize_observation(export,state,state/f'{DAY}.done.json',observation_date=DAY,
        result={'run_date':DAY,'banks_counts':{'rates':7}})
    contract=load_contract(state/completion['export_contract_path'])
    assert completion['observation_state']==contract['observation_state']=='partial'
    assert contract['coverage']['failure_records']==http_failures
    assert contract['coverage']['providers_failed']==1
    assert contract['provider_states'][0]['failure_records']==http_failures
    assert contract['provider_states'][0]['population_known'] is False
    assert publication_allowed(contract)==(False,'unverified_provider_population')
    # Even a contradictory complete label cannot bypass this explicit admission hold.
    forged=copy.deepcopy(contract);forged['observation_state']='complete'
    assert publication_allowed(forged)==(False,'unverified_provider_population')
    assert (export/'ingest-status.json').read_bytes()==original


def test_unknown_comparison_does_not_invent_a_population_loss(tmp_path):
    export=tmp_path/'runs'/DAY/'_exports';make_export(export,observation_date=DAY)
    (export/'sanity-report.json').write_text(json.dumps({'provider_population':{
        'status':'UNKNOWN','reason':'comparison_database_unreadable','findings':[]}}))
    state=tmp_path/'state'
    completion=finalize_observation(export,state,state/f'{DAY}.done.json',observation_date=DAY,
        result={'run_date':DAY,'banks_counts':{'rates':7}})
    contract=load_contract(state/completion['export_contract_path'])
    assert contract['observation_state']=='complete'
    assert 'provider_population_unverified' not in contract['coverage']
    assert publication_allowed(contract)==(True,'complete')


def test_unreconciled_provider_identity_stops_finalization(tmp_path):
    export=tmp_path/'runs'/DAY/'_exports';make_export(export,observation_date=DAY)
    warning(export,provider='unregistered')
    state=tmp_path/'state'
    with pytest.raises(ValueError,match='reconcile'):
        finalize_observation(export,state,state/f'{DAY}.done.json',observation_date=DAY,
            result={'run_date':DAY,'banks_counts':{'rates':7}})
    assert not (state/f'{DAY}.done.json').exists()
