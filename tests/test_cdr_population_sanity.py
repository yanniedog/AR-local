"""Retained Westpac disappearance must not be invisible to an intersection-only rate check."""
import hashlib
import json
from pathlib import Path
import sqlite3

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


def database(path, *, include_provider):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute('create table bank_products(provider text)')
        connection.execute('create table bank_rates(provider text,product_id text,application_type text,'
            'ribbon_rate_structure text,product_name text,dataset text,rate real)')
        # This fixture tests missing membership, not financial rate values.
        if include_provider:
            connection.executemany('insert into bank_products values(?)', [('Westpac',)]*32)


def test_report_reads_immutable_sources_and_surfaces_whole_provider_absence(tmp_path):
    previous = tmp_path/'2026-10-14/_exports/local-cdr.sqlite'
    current = tmp_path/'2026-10-15/_exports/local-cdr.sqlite'
    database(previous, include_provider=True); database(current, include_provider=False)
    before = {p:hashlib.sha256(p.read_bytes()).hexdigest() for p in (previous,current)}
    assert compare_ladders(current, previous) == []  # No common current ladder to compare.
    report_path = write_sanity_report(current.parent, '2026-10-15', tmp_path)
    report = json.loads(report_path.read_text())
    assert report['counts']['HIGH'] == 1
    assert report['provider_population']['status'] == 'WARN'
    assert report['findings'][0]['population_known'] is False
    assert report['findings'][0]['products_prev'] == 32
    assert before == {p:hashlib.sha256(p.read_bytes()).hexdigest() for p in (previous,current)}


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
