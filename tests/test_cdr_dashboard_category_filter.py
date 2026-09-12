"""Dashboard SQL and published rows agree on retained real product categories."""
import gzip
import json
import sqlite3
from pathlib import Path

from app_payload_common import section_filter
from cdr_dashboard_server import bank_section_rate_filter


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
