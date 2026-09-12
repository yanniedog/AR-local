"""Dashboard SQL and published rows agree on retained real product categories."""
import gzip
import json
import sqlite3
from pathlib import Path

from app_payload_common import section_filter
from cdr_dashboard_server import bank_section_rate_filter, read_bank_history_db


def test_dashboard_filters_real_misclassified_products_like_the_publisher():
    evidence = Path(__file__).parents[1] / 'docs/evidence/backup-observation-20260911/publication/v1-core.json.gz'
    core = json.loads(gzip.decompress(evidence.read_bytes()))
    db = sqlite3.connect(':memory:')
    try:
        db.execute('CREATE TABLE bank_products (run_date TEXT, dataset TEXT, product_key TEXT NOT NULL, category TEXT)')
        db.execute('CREATE TABLE bank_rates (run_date TEXT, dataset TEXT, product_key TEXT, rate TEXT, rate_family TEXT, rate_type TEXT)')
        excluded = 0
        for section, data in core['sections'].items():
            rows = [{**r, 'dataset': section, 'rate_family': 'lending' if section == 'Mortgage' else 'deposit'} for r in data['rates']]
            products = {(r['product_key'], r.get('category')) for r in rows}
            db.executemany('INSERT INTO bank_products VALUES (?,?,?,?)', [(core['run_date'], section, *p) for p in products])
            db.executemany('INSERT INTO bank_rates VALUES (?,?,?,?,?,?)', [(core['run_date'], section, r['product_key'], r['rate'], r['rate_family'], r.get('rate_type')) for r in rows])
            tail, params = bank_section_rate_filter(core['run_date'], section)
            actual = db.execute("SELECT product_key, rate FROM bank_rates WHERE run_date=? AND dataset=? AND rate IS NOT NULL AND rate != ''" + tail, [core['run_date'], section, *params]).fetchall()
            expected = [(r['product_key'], r['rate']) for r in rows if section_filter(section, r)]
            assert sorted(actual) == sorted(expected)
            excluded += len(rows) - len(actual)
        assert excluded == 27
    finally:
        db.close()


def test_history_reader_keeps_each_dates_category_scope(tmp_path):
    evidence = Path(__file__).parents[1] / 'docs/evidence/backup-observation-20260911/publication/v1-core.json.gz'
    core = json.loads(gzip.decompress(evidence.read_bytes()))
    real = next(row for row in core['sections']['Mortgage']['rates']
                if row.get('category') == 'RESIDENTIAL_MORTGAGES' and row.get('rate_type') != 'DISCOUNT')
    day = core['run_date']
    db_path = tmp_path / 'history.sqlite'
    with sqlite3.connect(db_path) as db:
        db.execute('CREATE TABLE bank_products (run_date TEXT, dataset TEXT, product_key TEXT, category TEXT)')
        db.execute('CREATE TABLE bank_rates (run_date TEXT, dataset TEXT, product_key TEXT, rate TEXT, rate_family TEXT, rate_type TEXT)')
        db.execute('INSERT INTO bank_products VALUES (?,?,?,?)', (day, 'Mortgage', real['product_key'], real['category']))
        db.execute('INSERT INTO bank_rates VALUES (?,?,?,?,?,?)', (day, 'Mortgage', real['product_key'], real['rate'], 'lending', real.get('rate_type')))
        # Structural fault injection: a later category change must not hide an
        # earlier valid row with the same product key. This is not capture data.
        db.execute('INSERT INTO bank_products VALUES (?,?,?,?)', ('2026-09-12', 'Mortgage', real['product_key'], 'BUSINESS_LOANS'))
        db.execute('INSERT INTO bank_rates VALUES (?,?,?,?,?,?)', ('2026-09-12', 'Mortgage', real['product_key'], real['rate'], 'lending', real.get('rate_type')))
    rows = read_bank_history_db(db_path, '2026-09-12', 'Mortgage')
    assert [(row['run_date'], row['product_key'], row['rate']) for row in rows] == [(day, real['product_key'], real['rate'])]
    assert read_bank_history_db(db_path, day, 'Mortgage') == rows
