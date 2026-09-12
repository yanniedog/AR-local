"""Startup warms current sections without materializing retained history."""
import gzip
import json
import sqlite3
from pathlib import Path

import cdr_dashboard_server as server


def test_preload_defers_history_until_requested_and_keeps_its_real_rows(tmp_path, monkeypatch):
    evidence = Path(__file__).parents[1] / 'docs/evidence/backup-observation-20260911/publication/v1-core.json.gz'
    core = json.loads(gzip.decompress(evidence.read_bytes()))
    day = core['run_date']
    exports = tmp_path / 'runs' / day / '_exports'
    cache = exports / 'dashboard-cache'
    cache.mkdir(parents=True)
    (cache / 'latest.json').write_text(json.dumps({'run_date': day}), encoding='utf-8')
    db_path = exports / 'local-cdr.sqlite'
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE bank_products (run_date TEXT, dataset TEXT, product_key TEXT, category TEXT, details_json TEXT DEFAULT '{}')")
        db.execute('CREATE TABLE bank_rates (run_date TEXT, dataset TEXT, product_key TEXT, provider TEXT, product_id TEXT, product_name TEXT, rate TEXT, rate_family TEXT, rate_type TEXT)')
        for section in ('Mortgage', 'Savings', 'TD'):
            row = next(row for row in core['sections'][section]['rates']
                       if row.get('rate_type') != 'DISCOUNT'
                       and row.get('category') in {'RESIDENTIAL_MORTGAGES', 'TRANS_AND_SAVINGS_ACCOUNTS', 'TERM_DEPOSITS'})
            db.execute('INSERT INTO bank_products (run_date,dataset,product_key,category) VALUES (?,?,?,?)',
                       (day, section, row['product_key'], row['category']))
            db.execute('INSERT INTO bank_rates VALUES (?,?,?,?,?,?,?,?,?)',
                       (day, section, row['product_key'], row['provider'], row['product_id'], row['product_name'],
                        row['rate'], 'lending' if section == 'Mortgage' else 'deposit', row.get('rate_type')))
    expected = server.read_bank_history_db(db_path, day, 'Mortgage')
    assert len(expected) == 1
    original = server.read_bank_history_db
    reads = []

    def read_history(*args):
        reads.append(args)
        return original(*args)

    monkeypatch.setattr(server, 'read_bank_history_db', read_history)
    handler_class = server.make_handler(server.ExportResolver(str(exports), tmp_path / 'runs'), tmp_path / 'site', True)
    assert reads == [], 'preload must not scan any full history'
    handler = object.__new__(handler_class)
    for section in ('Mortgage', 'Savings', 'TD'):
        body, _, _ = handler.route('/api/banks/section', {'date': [day], 'section': [section]})
        assert len(json.loads(body)['rates']) == 1
    query = {'date': [day], 'section': ['Mortgage']}
    body, _, _ = handler.route('/api/banks/history/section', query)
    assert json.loads(body)['rates'] == expected
    assert len(reads) == 1
    assert handler.route('/api/banks/history/section', query)[0] == body
    assert len(reads) == 1, 'requested history remains cached'
