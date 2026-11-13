"""Lossless export regression and bounded Python allocation during SQLite writes."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tracemalloc

import pytest

import cdr_outputs as outputs


@pytest.fixture
def banks(tmp_path):
    captured = json.loads((Path(__file__).parent / "fixtures" /
                           "product_facts_real_2026-05-19.json").read_text(encoding="utf-8"))
    run = tmp_path / "2026-05-19"
    for entry in captured["products"]:
        record = entry["record"]
        path = run / "banks" / entry["dataset"] / entry["provider"] / record["productId"] / "product-detail.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"data": record}, ensure_ascii=False), encoding="utf-8")
    return outputs.parse_banks_run(run)


def database_rows(path):
    with closing(sqlite3.connect(path)) as con:
        assert con.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
        return {table: con.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
                for table in (*outputs.TABLE_COLUMNS, "schema_meta")}


def test_rebuild_matches_prior_materialized_database_for_real_capture(tmp_path, banks, monkeypatch):
    # Reference only the old materialization boundary; SQL/schema/normalization
    # stay identical, so every column, row order and NULL/default is compared.
    insert = outputs.insert_rows
    date_rows, grouped = outputs.with_run_date, outputs.add_group

    def materialized_insert(con, table, rows):
        rows = list(rows)
        columns = outputs.TABLE_COLUMNS[table]
        values = ([tuple(row.get(column) for column in columns) for row in rows]
                  if table in {"bank_product_facts", "bank_product_changes"}
                  else [outputs.row_for_columns(row, columns) for row in rows])
        names = ",".join(outputs.quote_column(column) for column in columns)
        sql = f'INSERT INTO "{table}" ({names}) VALUES ({",".join("?" for _ in columns)})'
        con.executemany(sql, values)

    monkeypatch.setattr(outputs, "utc_now", lambda: "2026-05-19T00:00:00Z")
    monkeypatch.setattr(outputs, "insert_rows", materialized_insert)
    monkeypatch.setattr(outputs, "with_run_date", lambda rows, day: list(date_rows(rows, day)))
    monkeypatch.setattr(outputs, "add_group", lambda rows, group: list(grouped(rows, group)))
    reference = tmp_path / "reference.sqlite"
    outputs.rebuild_run_db(reference, "2026-05-19", banks)
    monkeypatch.setattr(outputs, "insert_rows", insert)
    monkeypatch.setattr(outputs, "with_run_date", date_rows)
    monkeypatch.setattr(outputs, "add_group", grouped)
    actual = tmp_path / "actual.sqlite"
    outputs.rebuild_run_db(actual, "2026-05-19", banks)
    assert database_rows(actual) == database_rows(reference)


@pytest.mark.parametrize("table", ["bank_product_facts", "bank_items"])
def test_insert_has_bounded_incremental_allocation(tmp_path, banks, table):
    # Repeat captured business fields solely for allocation stress. Fact IDs are
    # distinct control identifiers so the real UNIQUE constraint stays enabled.
    original = banks["product_facts" if table == "bank_product_facts" else "fees"][0]
    saved = deepcopy(original)
    count = 25_000

    def rows():
        for index in range(count):
            yield ({**original, "fact_id": f'{original["fact_id"]}:{index}'}
                   if table == "bank_product_facts" else original)

    with closing(sqlite3.connect(tmp_path / f"{table}.sqlite")) as con:
        outputs.ensure_db(con)
        tracemalloc.start()
        try:
            decorated = rows()
            if table == "bank_items":
                decorated = outputs.add_group(decorated, "fees")
            decorated = outputs.with_run_date(decorated, "2026-05-19")
            with con:
                outputs.insert_rows(con, table, decorated)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert peak < 2_000_000
        assert con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone() == (count,)
        assert con.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    assert original == saved


@pytest.mark.parametrize("failure", ["generator", "constraint"])
def test_late_failure_rolls_back_replacement_and_prior_table_inserts(tmp_path, banks, monkeypatch, failure):
    path = tmp_path / "stable.sqlite"
    outputs.rebuild_run_db(path, "2026-05-19", banks)
    before = database_rows(path)
    insert = outputs.insert_rows
    observed = []

    def failing_insert(con, table, rows):
        if table != "bank_product_facts":
            return insert(con, table, rows)

        def fail_after_first():
            first = next(iter(rows))
            yield first
            observed.append(con.execute("SELECT COUNT(*) FROM bank_product_facts").fetchone()[0])
            if failure == "generator":
                raise RuntimeError("late input failure")
            yield first  # Real UNIQUE constraint fails after a successful insert.

        insert(con, table, fail_after_first())

    monkeypatch.setattr(outputs, "insert_rows", failing_insert)
    expected = RuntimeError if failure == "generator" else sqlite3.IntegrityError
    with pytest.raises(expected):
        outputs.rebuild_run_db(path, "2026-05-19", banks)
    assert observed == [1]
    assert database_rows(path) == before


def test_empty_single_pass_iterables_and_existing_date_precedence(tmp_path, banks):
    row = {**banks["product_facts"][0], "run_date": "2026-05-18"}
    with closing(sqlite3.connect(tmp_path / "empty.sqlite")) as con:
        outputs.ensure_db(con)
        with con:
            outputs.insert_rows(con, "bank_product_facts", iter(()))
            outputs.insert_rows(con, "bank_product_facts", outputs.with_run_date(iter([row]), "2026-05-19"))
        assert con.execute("SELECT run_date FROM bank_product_facts").fetchall() == [("2026-05-18",)]
