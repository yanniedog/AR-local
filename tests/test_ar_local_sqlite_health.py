from __future__ import annotations

import sqlite3

import pytest

from ar_local_sqlite_health import (
    check_sqlite_health,
    require_sqlite_health,
    sqlite_health_ok,
)


def test_sqlite_health_accepts_consistent_database() -> None:
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE child(parent_id INTEGER REFERENCES parent(id))"
        )
        connection.execute("INSERT INTO parent VALUES (1)")
        connection.execute("INSERT INTO child VALUES (1)")
        report = check_sqlite_health(connection)

    assert report == {
        "quick_check": "ok",
        "integrity_check": "ok",
        "foreign_key_check": "ok",
    }
    assert sqlite_health_ok(report)


def test_sqlite_health_rejects_orphan_that_page_checks_miss() -> None:
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE child(parent_id INTEGER REFERENCES parent(id))"
        )
        connection.execute("INSERT INTO child VALUES (404)")
        report = check_sqlite_health(connection)

        assert report["quick_check"] == "ok"
        assert report["integrity_check"] == "ok"
        assert report["foreign_key_check"] == "failed"
        assert not sqlite_health_ok(report)
        with pytest.raises(ValueError, match="foreign_key_check"):
            require_sqlite_health(connection, label="test database")
