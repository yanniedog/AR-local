"""Replay semantics and bounded ownership; synthetic values are technical controls."""
from dataclasses import replace
import io
import json
from pathlib import Path
import sqlite3
import pytest

from cdr_json_replay import write_json_object
from cdr_product_changes import _product_key, _fact_key
from cdr_replay_rows import ReplayStore, ReplayLimits, ReplayLimitError, sort_blob


def store(parent, **changes):
    return ReplayStore(parent, key_of=_product_key, validate_fact=_fact_key, limits=replace(ReplayLimits(), **changes))


def fact(**extra):
    return dict(provider='Technical', product_id='control', dataset='Savings', fact_id='id', kind='attribute', **extra)


def test_replay_is_ordered_reusable_and_not_a_list(tmp_path):
    values = [fact(value=None), fact(value=True), fact(value=2**70), fact(value='\0\n😀'), fact(value=[])]
    with store(tmp_path) as spool:
        root = spool.root; spool.facts.extend(values)
        with pytest.raises(RuntimeError, match='not sealed'): list(spool.facts)
        spool.facts.seal()
        assert not isinstance(spool.facts, list) and len(spool.facts) == len(values)
        first, second = iter(spool.facts), iter(spool.facts)
        assert next(first) == next(second) == values[0]
        assert list(first) == list(second) == values[1:]
        assert list(spool.facts) == values
        with pytest.raises(RuntimeError, match='sealed'): spool.facts.append(values[0])
    assert not root.exists()
    with pytest.raises(RuntimeError, match='closed'): list(spool.facts)


def test_json_writer_matches_literal_stdlib_bytes_and_errors(tmp_path):
    values = [fact(text='é😀\0\n\t"\\', nested={'new': [None, {}, [], True, -0.0, 2**80]}), fact(text='last')]
    with store(tmp_path) as spool:
        spool.facts.extend(values); spool.facts.seal(); spool.changes.seal()
        ordinary = dict(meta={'values': ['é', None]}, facts=values, empty=[], last='tail')
        replay = {**ordinary, 'facts': spool.facts, 'empty': spool.changes}
        output = io.StringIO(); write_json_object(output, replay)
        assert output.getvalue() == json.dumps(ordinary, indent=2, ensure_ascii=False)
        for text in ['\ud800', '\udfff']:
            # Both paths preserve the codepoint; UTF-8 output rejects it equally.
            a = io.StringIO(); write_json_object(a, dict(facts=spool.facts, text=text))
            expected = json.dumps(dict(facts=values, text=text), indent=2, ensure_ascii=False)
            assert a.getvalue() == expected
            with pytest.raises(UnicodeEncodeError): a.getvalue().encode('utf-8')
            with pytest.raises(UnicodeEncodeError): expected.encode('utf-8')


def test_python_unicode_sort_is_exact_for_sql_blob_and_stable_ties(tmp_path):
    strings = ['Z', 'a', 'ß', 'SS', '\0', '\x01', '', '\ud800', '\udfff', '😀', '\uffff', 'İ', 'ı']
    with store(tmp_path) as spool:
        for index, value in enumerate(strings + ['a']):
            spool.append_change(dict(value=value, index=index), (value.casefold(), '', '', 0, '', 'same'))
        spool.changes.seal()
        expected = sorted(enumerate(strings+['a']), key=lambda item: item[1].casefold())
        assert [(r['index'], r['value']) for r in spool.changes] == expected
        assert sorted(strings, key=sort_blob) == sorted(strings)


def test_exact_product_identity_and_duplicate_rows_are_preserved(tmp_path):
    with store(tmp_path) as spool:
        rows = [fact(), fact(), {**fact(), 'provider': 'technical'}, {**fact(), 'provider': ' Technical '}]
        spool.facts.extend(rows); spool.facts.seal()
        assert spool.product_count() == 2 and list(spool.facts) == rows
        assert spool.take_product(('Technical', 'control', 'Savings')) == [rows[0], rows[1], rows[3]]
        with pytest.raises(ValueError, match='prior product group repeated'): spool.take_product(('Technical', 'control', 'Savings'))
        assert list(spool.product_keys(unmatched=True)) == [('technical', 'control', 'Savings')]


def test_all_readers_share_cumulative_budget_without_deadline_renewal(tmp_path):
    with store(tmp_path, read_bytes=1000) as spool:
        spool.facts.append(fact(text='x'*100)); spool.facts.seal()
        deadline = spool.deadline; completed = 0
        with pytest.raises(ReplayLimitError):
            for _ in range(20): list(spool.facts); completed += 1
        assert 0 < completed < 20 and spool.deadline == deadline
        with pytest.raises(ReplayLimitError): list(spool.facts)
        spool.deadline = 0
        with pytest.raises(ReplayLimitError): spool.facts.seal()


@pytest.mark.parametrize('limit,values', [('rows', 1), ('row_bytes', 80)])
def test_bound_failure_retains_only_owned_failed_scratch(tmp_path, limit, values):
    unrelated = tmp_path / 'keep'; unrelated.write_bytes(b'original')
    with pytest.raises(ReplayLimitError):
        with store(tmp_path, **{limit: values}) as spool:
            root = spool.root; spool.facts.extend([fact(text='x'*100), fact()])
    assert root.is_dir() and (root / 'failure.json').is_file() and unrelated.read_bytes() == b'original'
    assert json.loads((root / 'failure.json').read_bytes())['finalized'] is False


def test_disk_hard_limit_is_finite_and_unknown_files_are_never_deleted(tmp_path):
    with pytest.raises((ReplayLimitError, sqlite3.OperationalError)):
        with store(tmp_path, database_bytes=128*1024, disk_bytes=512*1024) as spool:
            root = spool.root
            for i in range(100): spool.facts.append(fact(text='x'*10000, number=i))
    assert root.is_dir() and sum(p.stat().st_size for p in root.iterdir()) <= 512*1024
    other = store(tmp_path); foreign = other.root / 'unrelated'; foreign.write_bytes(b'keep')
    with pytest.raises(ReplayLimitError, match='unknown file'): other.close()
    assert foreign.read_bytes() == b'keep'


def test_queries_use_declared_indexes_without_temp_sort(tmp_path):
    with store(tmp_path) as spool:
        for sql in ['SELECT payload FROM facts WHERE product=1 ORDER BY seq',
                    'SELECT payload FROM changes ORDER BY k1,k2,k3,k4,k5,k6,seq',
                    'SELECT identity FROM products WHERE matched=0 ORDER BY k1,k2,k3,first_seq']:
            plan = list(spool.connection.execute('EXPLAIN QUERY PLAN '+sql))
            assert not any('TEMP B-TREE' in row[3] for row in plan)


def test_xlsx_replays_late_columns_and_every_partition_exactly(tmp_path, monkeypatch):
    import zipfile
    import cdr_xlsx
    from cdr_clean_export import summary_counts
    monkeypatch.setattr(cdr_xlsx, 'MAX_WORKSHEET_ROWS', 4)
    values = [fact(index=i, **({'late': 'last-column'} if i == 8 else {})) for i in range(9)]
    with store(tmp_path) as spool:
        spool.facts.extend(values); spool.facts.seal()
        assert summary_counts(dict(product_facts=spool.facts, metadata={}, old_list=[])) == dict(product_facts=9, old_list=0)
        cdr_xlsx.write_workbook(tmp_path / 'replayed.xlsx', {'facts': spool.facts})
        cdr_xlsx.write_workbook(tmp_path / 'literal.xlsx', {'facts': values})
    with zipfile.ZipFile(tmp_path / 'replayed.xlsx') as a, zipfile.ZipFile(tmp_path / 'literal.xlsx') as b:
        assert a.namelist() == b.namelist()
        assert all(a.read(name) == b.read(name) for name in a.namelist())
        assert len([name for name in a.namelist() if name.startswith('xl/worksheets/')]) == 3


@pytest.mark.parametrize('updates', [dict(version=True), dict(seconds=True), dict(seconds=float('inf')), dict(read_bytes=0)])
def test_malformed_versioned_limits_reject_before_creating_scratch(tmp_path, updates):
    with pytest.raises(ValueError): store(tmp_path, **updates)
    assert list(tmp_path.iterdir()) == []


def test_last_identity_cache_preserves_alternation_unicode_and_raw_empty_aliases(tmp_path):
    values = []
    for provider, pid, alias in [('ß', 'x', None), ('SS', 'x', None), ('ß', '', 'x'), (' ß ', 'x', None)]:
        row = {**fact(), 'provider': provider, 'product_id': pid}
        if alias is not None: row['productId'] = alias
        values.extend([row.copy() for _ in range(12)])
    with store(tmp_path) as spool:
        statements = []; spool.connection.set_trace_callback(statements.append)
        spool.facts.extend(values); spool.facts.seal()
        assert list(spool.facts) == values and spool.product_count() == 2
        assert set(spool.facts.product_presence()) == {('ss', 'x', 'Savings'), ('ss', '', 'Savings'), (' ss ', 'x', 'Savings')}
        assert spool.product(('ß', 'x', 'Savings')) == values[:12] + values[24:]
        assert sum(sql.startswith('INSERT INTO facts(') for sql in statements) == len(values)
        assert sum(sql.startswith('SELECT id FROM products WHERE identity=') for sql in statements) < len(values) // 2


@pytest.mark.parametrize('table', ['facts', 'changes'])
def test_failed_sqlite_rollback_invalidates_cache_and_cannot_reuse_store(tmp_path, table):
    with store(tmp_path) as spool:
        root = spool.root; spool.facts.append(fact())
        assert spool._last_product is not None
        spool.connection.execute(f"CREATE TEMP TRIGGER fail_insert BEFORE INSERT ON {table} BEGIN SELECT RAISE(ROLLBACK, 'technical rollback'); END")
        with pytest.raises(sqlite3.IntegrityError, match='technical rollback'):
            if table == 'facts': spool.facts.append(fact())
            else: spool.append_change({'event': 'technical'}, ('p', 'id', 's', 0, '', ''))
        assert spool.write_failed
        assert spool._last_product is spool._last_presence is None
        for operation in (lambda: spool.facts.append(fact()), spool.facts.seal, spool.product_count,
                          lambda: spool.product(('Technical', 'control', 'Savings'))):
            with pytest.raises(ReplayLimitError, match='SQLite write failed'): operation()
    assert root.is_dir() and json.loads((root / 'failure.json').read_bytes())['finalized'] is False
