"""Retained Westpac disappearance must not be invisible to an intersection-only rate check."""
import hashlib
import json
from pathlib import Path
import sqlite3
from contextlib import closing

from cdr_population_sanity import disappeared_providers, population_report
from cdr_ingest_sanity import compare_ladders, write_sanity_report

FIXTURES = Path(__file__).parent/'fixtures/ingest-capture-20261015'


def test_retained_zero_index_is_a_real_response_but_not_a_withdrawal_proof():
    raw = (FIXTURES/'westpac-empty.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '25f1f2cdbb29cc2236883f6b1e132b6cf554687533f7614f1514166329d7e1fa'
    body = json.loads(raw)
    assert body['data']['products'] == []
    assert body['meta'] == {'totalRecords': 0, 'totalPages': 0}
    findings = disappeared_providers({}, {'Westpac': 32}, {}, {'Westpac': 379})
    assert findings == [{'severity': 'HIGH', 'code': 'provider_population_disappeared',
        'provider': 'Westpac', 'products_prev': 32, 'products_curr': 0,
        'rates_prev': 379, 'rates_curr': 0, 'population_known': False,
        'disposition': 'UNVERIFIED_SOURCE_ABSENCE'}]


def test_partial_or_unchanged_populations_do_not_become_total_disappearance():
    assert disappeared_providers({'Westpac': 31}, {'Westpac': 32}) == []
    assert disappeared_providers({}, {'Already empty': 0}) == []
    assert disappeared_providers({'New provider': 1}, {}) == []
    # Conflicting product/rate evidence is not silently described as zero/zero.
    assert disappeared_providers({}, {'Westpac': 32}, {'Westpac': 1}, {'Westpac': 379}) == []


def database(path, *, include_provider, run_date=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute('create table bank_products(provider text, product_id text, run_date text)')
        connection.execute('create table bank_rates(provider text,product_id text,application_type text,'
            'ribbon_rate_structure text,product_name text,dataset text,rate real,run_date text)')
        # This fixture tests missing membership, not financial rate values.
        if include_provider:
            day=run_date or path.parent.parent.name
            connection.executemany('insert into bank_products values(?,?,?)',
                [('Westpac',f'p{i}',day) for i in range(32)])


def test_unfinalized_baseline_cannot_authorize_population_recovery(tmp_path):
    previous = tmp_path/'2026-10-14/_exports/local-cdr.sqlite'
    current = tmp_path/'2026-10-15/_exports/local-cdr.sqlite'
    database(previous, include_provider=True); database(current, include_provider=False)
    before = {p:hashlib.sha256(p.read_bytes()).hexdigest() for p in (previous,current)}
    assert compare_ladders(current, previous) == []  # No common current ladder to compare.
    report_path = write_sanity_report(current.parent, '2026-10-15', tmp_path)
    report = json.loads(report_path.read_text())
    assert report['counts']['HIGH'] == 0
    assert report['provider_population']['status'] == 'UNKNOWN'
    assert report['provider_population']['reason'] == 'baseline_not_finalized_or_verified'
    assert before == {p:hashlib.sha256(p.read_bytes()).hexdigest() for p in (previous,current)}


def finalized_previous(tmp_path, *, include_provider=True):
    from cdr_finalization import finalize_observation
    from tests.test_irreplaceable_finalization import make_export
    root=tmp_path/'runs/2026-10-14/_exports'
    make_export(root,observation_date='2026-10-14')
    database(root/'local-cdr.sqlite',include_provider=include_provider)
    status=json.loads((root/'ingest-status.json').read_bytes())
    status['provider_states'][0]['provider_dir']='Westpac'
    (root/'ingest-status.json').write_text(json.dumps(status))
    state=tmp_path/'state'
    finalize_observation(root,state,state/'2026-10-14.done.json',observation_date='2026-10-14',
        result={'run_date':'2026-10-14','banks_counts':{'rates':7}})
    return root,state


def test_finalized_hash_bound_baseline_can_establish_disappearance(tmp_path):
    previous,state=finalized_previous(tmp_path)
    current=tmp_path/'runs/2026-10-15/_exports/local-cdr.sqlite'
    database(current,include_provider=False)
    (current.parent/'ingest-status.json').write_text(json.dumps({'index_diagnostics':{
        'Westpac':{'pagination_complete':True,'unique_products':0}}}))
    path=write_sanity_report(current.parent,'2026-10-15',tmp_path/'runs',state_dir=state)
    report=json.loads(path.read_bytes());population=report['provider_population']
    assert population['status']=='WARN'
    assert population['baseline']['observation_date']=='2026-10-14'
    assert population['baseline']['database_sha256']==hashlib.sha256((previous/'local-cdr.sqlite').read_bytes()).hexdigest()
    assert population['findings'][0]['products_prev']==32


def test_changed_database_or_marker_cannot_be_a_recovery_baseline(tmp_path):
    from cdr_population_baseline import finalized_population_report
    previous,state=finalized_previous(tmp_path)
    current=tmp_path/'current.sqlite';database(current,include_provider=False)
    db=previous/'local-cdr.sqlite'
    with sqlite3.connect(db) as connection:connection.execute("insert into bank_products(provider) values('changed')")
    assert finalized_population_report(current,state,run_date='2026-10-15')['status']=='UNKNOWN'
    (state/'2026-10-14.done.json').write_text('{}')
    assert finalized_population_report(current,state,run_date='2026-10-15')['status']=='UNKNOWN'


def next_export(tmp_path, day, *, include_provider):
    from tests.test_irreplaceable_finalization import make_export
    root=tmp_path/'runs'/day/'_exports';make_export(root,observation_date=day)
    database(root/'local-cdr.sqlite',include_provider=include_provider)
    status=json.loads((root/'ingest-status.json').read_bytes())
    status['provider_states'][0]['provider_dir']='Westpac'
    status['index_diagnostics']={'Westpac':{'pagination_complete':True,'unique_products':32 if include_provider else 0}}
    (root/'ingest-status.json').write_text(json.dumps(status))
    return root


def finalize_next(root,state,day):
    from cdr_finalization import finalize_observation
    write_sanity_report(root,day,root.parent.parent,state_dir=state)
    return finalize_observation(root,state,state/f'{day}.done.json',observation_date=day,
        result={'run_date':day,'banks_counts':{'rates':7}})


def test_repeated_zero_preserves_the_sealed_warning_and_recovery_identity(tmp_path):
    from app_payload_observation_gate import publication_allowed
    from cdr_observation_selection import selected_observation
    from cdr_population_recovery import population_recovery_requests
    previous,state=finalized_previous(tmp_path)
    first=next_export(tmp_path,'2026-10-15',include_provider=False)
    finalize_next(first,state,'2026-10-15')
    second=next_export(tmp_path,'2026-10-16',include_provider=False)
    finalize_next(second,state,'2026-10-16')
    observation=selected_observation(state,'2026-10-16')
    report=json.loads((second/'provider-population-report.json').read_bytes())
    finding=report['provider_population']['findings'][0]
    assert finding['products_prev']==0 and finding['carried_unresolved'] is True
    assert finding['last_nonempty']=={'observation_date':'2026-10-14','products':32,'rates':0}
    assert publication_allowed(observation['contract'])==(False,'unverified_provider_population')
    requests=population_recovery_requests(observation,{'Westpac':{'provider_uid':'provider-a',
        'endpoint_url':'https://bank.example/cds-au/v1/banking/products'}})
    assert len(requests)==1 and requests[0]['provider_dir']=='Westpac'


def test_current_nonempty_data_can_clear_a_previous_population_warning(tmp_path):
    from app_payload_observation_gate import publication_allowed
    from cdr_observation_selection import selected_observation
    previous,state=finalized_previous(tmp_path)
    first=next_export(tmp_path,'2026-10-15',include_provider=False)
    finalize_next(first,state,'2026-10-15')
    second=next_export(tmp_path,'2026-10-16',include_provider=True)
    finalize_next(second,state,'2026-10-16')
    observation=selected_observation(state,'2026-10-16')
    assert 'provider_population_unverified' not in observation['contract']['coverage']
    assert publication_allowed(observation['contract'])==(True,'complete')


def test_unknown_comparison_cannot_clear_a_known_previous_warning(tmp_path):
    from app_payload_observation_gate import publication_allowed
    from cdr_export_contract import load_contract
    from cdr_finalization import finalize_observation
    from cdr_population_baseline import finalized_population_report
    previous,state=finalized_previous(tmp_path)
    first=next_export(tmp_path,'2026-10-15',include_provider=False)
    finalize_next(first,state,'2026-10-15')
    second=next_export(tmp_path,'2026-10-16',include_provider=False)
    (first/'local-cdr.sqlite-journal').write_bytes(b'retained journal')
    report=finalized_population_report(second/'local-cdr.sqlite',state,run_date='2026-10-16')
    assert report['status']=='UNKNOWN' and report['unresolved_prior']
    (second/'provider-population-report.json').write_text(json.dumps({'run_date':'2026-10-16',
        'compared_against':'2026-10-15','provider_population':report}))
    completion=finalize_observation(second,state,state/'2026-10-16.done.json',observation_date='2026-10-16',
        result={'run_date':'2026-10-16','banks_counts':{'rates':7}})
    contract=load_contract(state/completion['export_contract_path'])
    assert publication_allowed(contract)==(False,'unverified_provider_population')


def test_missing_or_invalid_database_is_unknown_and_never_created(tmp_path):
    absent = tmp_path/'absent.sqlite'
    assert population_report(absent, absent)['status'] == 'UNKNOWN'
    assert not absent.exists()
    broken = tmp_path/'broken.sqlite'; broken.write_bytes(b'not SQLite')
    assert population_report(broken, broken)['status'] == 'UNKNOWN'


def test_retained_journal_is_not_opened_or_silently_ignored(tmp_path):
    db = tmp_path/'retained.sqlite'; database(db, include_provider=True)
    journal = tmp_path/'retained.sqlite-journal'; journal.write_bytes(b'retained journal')
    before = journal.read_bytes()
    report = population_report(db, db)
    assert report['status'] == 'UNKNOWN'
    assert journal.read_bytes() == before


def test_empty_wal_adds_no_content_and_immutable_read_does_not_create_shm(tmp_path):
    db = tmp_path/'retained.sqlite'; database(db, include_provider=True)
    wal = tmp_path/'retained.sqlite-wal'; wal.write_bytes(b'')
    assert population_report(db, db)['status'] == 'PASS'
    assert wal.read_bytes() == b''
    assert not (tmp_path/'retained.sqlite-shm').exists()


def test_selected_repaired_revision_is_the_prior_baseline(tmp_path):
    from cdr_finalization import finalize_observation
    from cdr_population_baseline import finalized_population_report
    from cdr_observation_selection import selected_observation
    from tests.test_irreplaceable_finalization import make_export
    day='2026-10-14';state=tmp_path/'state'
    primary=next_export(tmp_path,day,include_provider=False)
    finalize_observation(primary,state,state/f'{day}.done.json',observation_date=day,
        result={'run_date':day,'banks_counts':{'rates':7}})
    revision=tmp_path/'runs'/day/'_revisions/fixed/_exports'
    make_export(revision,observation_date=day)
    database(revision/'local-cdr.sqlite',include_provider=True,run_date=day)
    completed=finalize_observation(revision,state,state/f'{day}.revision.fixed.json',
        observation_date=day,result={'run_date':day,'banks_counts':{'rates':7}})
    selected=selected_observation(state,day)
    assert selected['contract']['generation_id']==completed['generation_id']
    current=tmp_path/'runs/2026-10-15/_exports/local-cdr.sqlite';database(current,include_provider=False)
    report=finalized_population_report(current,state,run_date='2026-10-15')
    assert report['status']=='WARN' and report['findings'][0]['products_prev']==32
    assert report['baseline']['generation_id']==completed['generation_id']
    assert report['baseline']['database_sha256']==hashlib.sha256((revision/'local-cdr.sqlite').read_bytes()).hexdigest()


def test_observation_database_is_preferred_over_persistent_custom_rows(tmp_path):
    previous,state=finalized_previous(tmp_path)
    root=next_export(tmp_path,'2026-10-15',include_provider=False)
    actual=tmp_path/'configured.sqlite';database(actual,include_provider=True,run_date='2026-10-14')
    status=json.loads((root/'ingest-status.json').read_bytes())
    status['index_diagnostics']['Westpac']['unique_products']=0
    (root/'ingest-status.json').write_text(json.dumps(status))
    write_sanity_report(root,'2026-10-15',tmp_path/'runs',state_dir=state,db_path=actual)
    report=json.loads((root/'provider-population-report.json').read_bytes())
    assert report['provider_population']['status']=='WARN'
    assert report['provider_population']['findings'][0]['products_curr']==0


def test_custom_output_keeps_a_finalized_database_for_next_day_baseline(tmp_path):
    from cdr_finalization import finalize_observation
    from cdr_outputs import build_outputs
    from cdr_population_baseline import finalized_population_report
    from tests.test_cdr_product_facts import captured
    from tests.test_irreplaceable_finalization import make_export
    day='2026-10-14';run=tmp_path/'runs'/day;root=run/'_exports'
    make_export(root,observation_date=day)
    product=captured()[0]
    path=run/'banks'/product['dataset']/product['provider']/'captured/id/product-detail.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'data':product['record']}))
    custom=tmp_path/'configured.sqlite'
    result=build_outputs(run,db_path=custom)
    assert custom.is_file() and (root/'local-cdr.sqlite').is_file()
    with sqlite3.connect(custom) as db:
        rows=db.execute('select provider,count(*) from bank_products group by provider').fetchall()
    with sqlite3.connect(root/'local-cdr.sqlite') as db:
        assert db.execute('select provider,count(*) from bank_products group by provider').fetchall()==rows
    assert rows and rows[0][1]>0
    state=tmp_path/'state'
    finalize_observation(root,state,state/f'{day}.done.json',observation_date=day,result=result)
    # Subsequent changes to the custom output do not alter finalized evidence.
    with sqlite3.connect(custom) as db:db.execute('delete from bank_products')
    current=tmp_path/'runs/2026-10-15/_exports/local-cdr.sqlite'
    database(current,include_provider=False)
    report=finalized_population_report(current,state,run_date='2026-10-15')
    assert report['status']=='WARN' and report['findings'][0]['provider']==rows[0][0]
    assert report['findings'][0]['products_prev']==rows[0][1]


def test_population_sidecar_survives_ladder_advisory_failure(tmp_path,monkeypatch):
    import cdr_ingest_sanity as sanity
    previous,state=finalized_previous(tmp_path)
    root=next_export(tmp_path,'2026-10-15',include_provider=False)
    def broken(*a):raise ValueError('unrelated ladder advisory failed')
    monkeypatch.setattr(sanity,'compare_ladders',broken)
    import pytest
    with pytest.raises(ValueError,match='unrelated ladder'):
        sanity.write_sanity_report(root,'2026-10-15',tmp_path/'runs',state_dir=state)
    report=json.loads((root/'provider-population-report.json').read_bytes())
    assert report['provider_population']['status']=='WARN'


def test_same_day_restoration_can_clear_carried_warning_with_fresh_nonempty_index(tmp_path):
    previous,state=finalized_previous(tmp_path)
    first=next_export(tmp_path,'2026-10-15',include_provider=False)
    finalize_next(first,state,'2026-10-15')
    root=tmp_path/'runs/2026-10-15/_revisions/fixed/_exports'
    root.mkdir(parents=True)
    database(root/'local-cdr.sqlite',include_provider=True,run_date='2026-10-15')
    (root/'ingest-status.json').write_text(json.dumps({'provider_states':[{
        'provider_uid':'provider-a','provider_dir':'Westpac'}],'index_diagnostics':{
        'Westpac':{'pagination_complete':True,'unique_products':32}}}))
    write_sanity_report(root,'2026-10-15',tmp_path/'runs',state_dir=state)
    report=json.loads((root/'provider-population-report.json').read_bytes())['provider_population']
    assert report['status']=='UNKNOWN' and not report.get('unresolved_prior')
