"""Bounded, immutable point lookup of an already completed capture.

No schema migration or whole-archive read is required. VM steps and a small
SQLite page cache bound query work; they are not measured physical I/O bytes.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

QUERY = ('SELECT receipt_sha256 FROM ingest_captures '
         'INDEXED BY sqlite_autoindex_ingest_captures_1 WHERE ingest_id=? LIMIT 2')
SCHEMA = [('ingest_id', 'TEXT', 0, 1), ('receipt_sha256', 'TEXT', 1, 0),
          ('completed_at', 'TEXT', 1, 0), ('products', 'INTEGER', 1, 0)]
VALUE_LIMIT = 65536
UNSUPPORTED = 'capture_cleanup_sqlite_value_limits_unavailable'


def sqlite_value_limits_available() -> bool:
    """Fail closed before connect where native SQLite limits cannot be set."""
    return (all(callable(getattr(sqlite3.Connection, name, None)) for name in ('setlimit', 'getlimit'))
            and all(type(getattr(sqlite3, name, None)) is int for name in (
                'SQLITE_LIMIT_LENGTH', 'SQLITE_LIMIT_SQL_LENGTH', 'SQLITE_LIMIT_COLUMN', 'SQLITE_LIMIT_VDBE_OP')))


def _apply_limits(connection) -> None:
    # LIMIT rows, projection expressions, a page cache and VM-step counts do
    # not cap the allocation of a malformed stored TEXT/BLOB. Set the native
    # value/row length limit before even a schema or PRAGMA query is prepared.
    limits = ((sqlite3.SQLITE_LIMIT_LENGTH, VALUE_LIMIT), (sqlite3.SQLITE_LIMIT_SQL_LENGTH, 16384),
              (sqlite3.SQLITE_LIMIT_COLUMN, 128), (sqlite3.SQLITE_LIMIT_VDBE_OP, 10000))
    for category, maximum in limits:
        connection.setlimit(category, maximum)
        actual = connection.getlimit(category)
        if type(actual) is not int or not 0 < actual <= maximum:
            raise ValueError('capture_cleanup_sqlite_value_limits_not_enforced')


def completed_receipt_hash(database: Path, generation: str, budget) -> str | None:
    """Only the known primary-key plan may read a maximum of two small rows."""
    if not sqlite_value_limits_available():
        raise ValueError(UNSUPPORTED)
    if not isinstance(generation, str) or not 0 < len(generation) <= 1024:
        raise ValueError('capture_generation_lookup_invalid')
    budget.check(entries=1, reserve_bytes=VALUE_LIMIT)
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro&immutable=1', uri=True, timeout=1)) as connection:
        _apply_limits(connection)
        connection.set_progress_handler(budget.query_step, 1)
        # These settings affect only this private read connection, never the DB.
        connection.execute('PRAGMA mmap_size=0')
        connection.execute('PRAGMA cache_size=-2048')
        connection.execute('PRAGMA query_only=ON')
        if (connection.execute('PRAGMA application_id').fetchone()[0] != 0x4152544D
                or connection.execute('PRAGMA user_version').fetchone()[0] != 1):
            raise ValueError('capture_archive_is_not_a_completed_terms_store')
        schema = connection.execute('PRAGMA table_info(ingest_captures)').fetchmany(5)
        if [(row[1], row[2], row[3], row[5]) for row in schema] != SCHEMA:
            raise ValueError('capture_archive_completion_schema_invalid')
        plan = connection.execute('EXPLAIN QUERY PLAN ' + QUERY, (generation,)).fetchmany(2)
        if len(plan) != 1 or plan[0][3] != 'SEARCH ingest_captures USING INDEX sqlite_autoindex_ingest_captures_1 (ingest_id=?)':
            raise ValueError('capture_archive_completion_lookup_is_not_indexed')
        rows = connection.execute(QUERY, (generation,)).fetchmany(2)
        if len(rows) > 1 or (rows and (type(rows[0][0]) is not str or len(rows[0][0]) != 64)):
            raise ValueError('capture_archive_completion_row_invalid')
    budget.check()
    return rows[0][0] if rows else None
