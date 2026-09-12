"""Dashboard SQL and published rows agree on retained real product categories."""
import gzip
import json
import sqlite3
from pathlib import Path

import pytest

from app_payload_common import section_filter
from cdr_dashboard_server import bank_section_rate_filter, read_bank_history_db, register_bank_category_filter


def test_dashboard_filters_real_misclassified_products_like_the_publisher():
    evidence = Path(__file__).parents[1] / 'docs/evidence/backup-observation-20260911/publication/v1-core.json.gz'
    core = json.loads(gzip.decompress(evidence.read_bytes()))
    db = sqlite3.connect(':memory:')
    try:
        register_bank_category_filter(db)
        db.execute("CREATE TABLE bank_products (run_date TEXT, dataset TEXT, product_key TEXT NOT NULL, category TEXT, details_json TEXT DEFAULT '{}')")
        db.execute('CREATE TABLE bank_rates (run_date TEXT, dataset TEXT, product_key TEXT, rate TEXT, rate_family TEXT, rate_type TEXT)')
        excluded = 0
        for section, data in core['sections'].items():
            rows = [{**r, 'dataset': section, 'rate_family': 'lending' if section == 'Mortgage' else 'deposit'} for r in data['rates']]
            products = {(r['product_key'], r.get('category')) for r in rows}
            db.executemany('INSERT INTO bank_products (run_date,dataset,product_key,category) VALUES (?,?,?,?)', [(core['run_date'], section, *p) for p in products])
            db.executemany('INSERT INTO bank_rates VALUES (?,?,?,?,?,?)', [(core['run_date'], section, r['product_key'], r['rate'], r['rate_family'], r.get('rate_type')) for r in rows])
            tail, params = bank_section_rate_filter(core['run_date'], section)
            actual = db.execute("SELECT product_key, rate FROM bank_rates WHERE run_date=? AND dataset=? AND rate IS NOT NULL AND rate != ''" + tail, [core['run_date'], section, *params]).fetchall()
            expected = [(r['product_key'], r['rate']) for r in rows if section_filter(section, r)]
            assert sorted(actual) == sorted(expected)
            excluded += len(rows) - len(actual)
        assert excluded == 27
    finally:
        db.close()


@pytest.mark.parametrize('section', ['Mortgage', ''])
def test_history_reader_keeps_each_dates_category_scope(tmp_path, section):
    evidence = Path(__file__).parents[1] / 'docs/evidence/backup-observation-20260911/publication/v1-core.json.gz'
    core = json.loads(gzip.decompress(evidence.read_bytes()))
    real = next(row for row in core['sections']['Mortgage']['rates']
                if row.get('category') == 'RESIDENTIAL_MORTGAGES' and row.get('rate_type') != 'DISCOUNT')
    day = core['run_date']
    db_path = tmp_path / 'history.sqlite'
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE bank_products (run_date TEXT, dataset TEXT, product_key TEXT, category TEXT, details_json TEXT DEFAULT '{}')")
        db.execute('CREATE TABLE bank_rates (run_date TEXT, dataset TEXT, product_key TEXT, rate TEXT, rate_family TEXT, rate_type TEXT)')
        db.execute('INSERT INTO bank_products (run_date,dataset,product_key,category) VALUES (?,?,?,?)', (day, 'Mortgage', real['product_key'], real['category']))
        db.execute('INSERT INTO bank_rates VALUES (?,?,?,?,?,?)', (day, 'Mortgage', real['product_key'], real['rate'], 'lending', real.get('rate_type')))
        # Structural fault injection: a later category change must not hide an
        # earlier valid row with the same product key. This is not capture data.
        db.execute('INSERT INTO bank_products (run_date,dataset,product_key,category) VALUES (?,?,?,?)', ('2026-09-12', 'Mortgage', real['product_key'], 'BUSINESS_LOANS'))
        db.execute('INSERT INTO bank_rates VALUES (?,?,?,?,?,?)', ('2026-09-12', 'Mortgage', real['product_key'], real['rate'], 'lending', real.get('rate_type')))
    rows = read_bank_history_db(db_path, '2026-09-12', section)
    assert [(row['run_date'], row['product_key'], row['rate']) for row in rows] == [(day, real['product_key'], real['rate'])]
    assert read_bank_history_db(db_path, day, section) == rows


def test_unscoped_history_matches_all_scoped_sections_on_retained_real_rows(tmp_path):
    evidence = Path(__file__).parents[1] / 'docs/evidence/backup-observation-20260911/publication/v1-core.json.gz'
    core = json.loads(gzip.decompress(evidence.read_bytes()))
    db_path = tmp_path / 'history.sqlite'
    expected = {}
    source_count = 0
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE bank_products (run_date TEXT, dataset TEXT, product_key TEXT, category TEXT, details_json TEXT DEFAULT '{}')")
        db.execute('CREATE TABLE bank_rates (run_date TEXT, dataset TEXT, product_key TEXT, rate TEXT, rate_family TEXT, rate_type TEXT)')
        for section, data in core['sections'].items():
            family = 'lending' if section == 'Mortgage' else 'deposit'
            rows = [{**row, 'dataset': section, 'rate_family': family} for row in data['rates']]
            source_count += len(rows)
            products = {(row['product_key'], row.get('category')) for row in rows}
            db.executemany('INSERT INTO bank_products (run_date,dataset,product_key,category) VALUES (?,?,?,?)',
                           [(core['run_date'], section, *product) for product in products])
            db.executemany('INSERT INTO bank_rates VALUES (?,?,?,?,?,?)',
                           [(core['run_date'], section, row['product_key'], row['rate'], family, row.get('rate_type')) for row in rows])
            expected[section] = sorted((row['product_key'], row['rate']) for row in rows if section_filter(section, row))
    unscoped = read_bank_history_db(db_path, core['run_date'], '')
    assert source_count - len(unscoped) == 27
    for section in core['sections']:
        scoped = read_bank_history_db(db_path, core['run_date'], section)
        assert sorted((row['product_key'], row['rate']) for row in scoped) == expected[section]
        selected = [row for row in unscoped if row['dataset'] == section]
        assert sorted((row['product_key'], row['rate']) for row in selected) == expected[section]
        assert all(row['rate_family'] == ('lending' if section == 'Mortgage' else 'deposit') for row in selected)
        assert all('dataset' not in row and 'rate_family' not in row for row in scoped)


def test_dashboard_td_exception_requires_retained_raw_product_evidence(tmp_path):
    fixture = Path(__file__).parent / 'fixtures/cdr_term_classification_real_2026-09-12.json'
    observed = json.loads(fixture.read_text(encoding='utf-8'))
    db_path = tmp_path / 'term-history.sqlite'
    db = sqlite3.connect(db_path)
    try:
        register_bank_category_filter(db)
        db.execute('CREATE TABLE bank_products (run_date TEXT, dataset TEXT, product_key TEXT, category TEXT, details_json TEXT)')
        db.execute('CREATE TABLE bank_rates (run_date TEXT, dataset TEXT, product_key TEXT, rate TEXT, rate_family TEXT, rate_type TEXT)')
        expected = []
        for item in observed['products']:
            product = item['product']
            # Exercise the derived TD classification while retaining original
            # rate/category values; ambiguous savings controls must stay excluded.
            db.execute('INSERT INTO bank_products VALUES (?,?,?,?,?)', ('2026-09-12', 'TD', product['product_key'], product['category'], product['details_json']))
            for row in item['rates']:
                db.execute('INSERT INTO bank_rates VALUES (?,?,?,?,?,?)', ('2026-09-12', 'TD', row['product_key'], row['rate'], row['rate_family'], row['rate_type']))
                if item['expected_dataset'] == 'TD':
                    expected.append((row['product_key'], row['rate']))
        tail, params = bank_section_rate_filter('2026-09-12', 'TD')
        actual = db.execute("SELECT product_key,rate FROM bank_rates WHERE run_date=? AND dataset=?" + tail, ['2026-09-12', 'TD', *params]).fetchall()
        assert sorted(actual) == sorted(expected)
        assert len(actual) == 25
        db.commit()
        for section in ('TD', ''):
            rows = read_bank_history_db(db_path, '2026-09-12', section)
            assert sorted((row['product_key'], row['rate']) for row in rows) == sorted(expected)
    finally:
        db.close()


def test_sql_extraction_preserves_server_connection_hooks(monkeypatch, tmp_path):
    from contextlib import contextmanager
    import cdr_dashboard_server as server

    opened = []
    registered = []
    closed = []
    connection = sqlite3.connect(':memory:')

    @contextmanager
    def connector(path):
        opened.append(path)
        try:
            yield connection
        finally:
            closed.append(True)
            connection.close()

    monkeypatch.setattr(server, '_connect_readonly', connector)
    monkeypatch.setattr(server, 'register_bank_category_filter', registered.append)
    with pytest.raises(RuntimeError, match='caller failure'):
        with server.connect_readonly(tmp_path / 'unused.sqlite') as actual:
            assert actual is connection
            raise RuntimeError('caller failure')
    assert opened == [tmp_path / 'unused.sqlite']
    assert registered == [connection]
    assert closed == [True]
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        connection.execute('SELECT 1')
