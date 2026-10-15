"""Advisory ladders and finalized population comparisons retain separate origins."""
import json
import sqlite3

import pytest

from cdr_ingest_sanity import write_sanity_report
from tests.test_cdr_population_sanity import database,finalized_previous,next_export


@pytest.mark.parametrize('verified_population',[False,True])
def test_ladder_findings_name_the_database_actually_compared(tmp_path,verified_population):
    if verified_population:previous,state=finalized_previous(tmp_path)
    else:
        state=tmp_path/'state'
        previous=tmp_path/'runs/2026-10-14/_exports'
        database(previous/'local-cdr.sqlite',include_provider=True)
    newer=tmp_path/'runs/2026-10-15/_exports/local-cdr.sqlite'
    database(newer,include_provider=True)
    current=next_export(tmp_path,'2026-10-16',include_provider=False)
    for path,day,rate in [(newer,'2026-10-15',0.05),(current/'local-cdr.sqlite','2026-10-16',0.08)]:
        db=sqlite3.connect(path)
        db.execute('insert into bank_rates values(?,?,?,?,?,?,?,?)',('Other','p1','','','Product','Savings',rate,day))
        db.commit();db.close()
    out=write_sanity_report(current,'2026-10-16',tmp_path/'runs',state_dir=state)
    report=json.loads(out.read_bytes())
    assert report['compared_against']=='2026-10-15'
    assert report['provider_population_compared_against']==('2026-10-14' if verified_population else None)
    ladders=[f for f in report['findings'] if f.get('code')!='provider_population_disappeared']
    assert len(ladders)==1 and ladders[0]['worst_delta_bp']==300.0
    populations=[f for f in report['findings'] if f.get('code')=='provider_population_disappeared']
    if verified_population:assert populations[0]['compared_against']=='2026-10-14'
    else:assert populations==[]
