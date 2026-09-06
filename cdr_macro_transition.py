"""Preserve retired CPI definitions before replacing their public series IDs."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

CPI_SERIES_IDS = frozenset({"monthly_cpi_indicator", "monthly_trimmed_mean_cpi"})
ARCHIVE_DEFINITION = "before_complete_monthly_cpi"


def archive_schema_sql() -> list[str]:
    # One immutable snapshot per public ID and retired definition. Readers of
    # current series never scan this table; normal SQLite backups retain it.
    return [
        """CREATE TABLE IF NOT EXISTS series_definition_archive (
            series_id TEXT NOT NULL,
            definition_id TEXT NOT NULL,
            archived_at TEXT NOT NULL,
            observation_count INTEGER NOT NULL CHECK(observation_count >= 0),
            snapshot_json TEXT NOT NULL,
            snapshot_sha256 TEXT NOT NULL CHECK(length(snapshot_sha256) = 64),
            PRIMARY KEY (series_id, definition_id)
        )""",
        """CREATE TRIGGER IF NOT EXISTS series_definition_archive_no_update
           BEFORE UPDATE ON series_definition_archive
           BEGIN SELECT RAISE(ABORT, 'series definition archives are immutable'); END""",
        """CREATE TRIGGER IF NOT EXISTS series_definition_archive_no_delete
           BEFORE DELETE ON series_definition_archive
           BEGIN SELECT RAISE(ABORT, 'series definition archives are immutable'); END""",
    ]


def _rows_as_dicts(cursor: sqlite3.Cursor) -> list[dict]:
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def archive_cpi_predecessor(con: sqlite3.Connection, series_id: str, source_url: str) -> None:
    """Archive, verify, then clear predecessor membership in the caller's transaction.

    The caller must install the new rows and successful ingest metadata before
    committing. Rollback restores the predecessor and removes an uncommitted
    archive if any later write fails. No observation is relabelled in place.
    """
    if series_id not in CPI_SERIES_IDS or "/rest/data/CPI/" not in source_url:
        return
    metadata = _rows_as_dicts(con.execute("SELECT * FROM ingest_runs WHERE series_id = ?", (series_id,)))
    if metadata and "/rest/data/CPI/" in str(metadata[0].get("source_url") or ""):
        return
    observations = _rows_as_dicts(con.execute(
        "SELECT * FROM series_observations WHERE series_id = ? ORDER BY observation_date", (series_id,)
    ))
    if not observations and not metadata:
        return
    snapshot = json.dumps({"series_id": series_id, "ingest_runs": metadata, "observations": observations},
                          sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    digest = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
    expected = (len(observations), snapshot, digest)
    existing = con.execute(
        """SELECT observation_count, snapshot_json, snapshot_sha256
           FROM series_definition_archive WHERE series_id = ? AND definition_id = ?""",
        (series_id, ARCHIVE_DEFINITION),
    ).fetchone()
    if existing is None:
        con.execute(
            "INSERT INTO series_definition_archive VALUES (?, ?, ?, ?, ?, ?)",
            (series_id, ARCHIVE_DEFINITION, datetime.now(timezone.utc).isoformat(), *expected),
        )
    preserved = con.execute(
        """SELECT observation_count, snapshot_json, snapshot_sha256
           FROM series_definition_archive WHERE series_id = ? AND definition_id = ?""",
        (series_id, ARCHIVE_DEFINITION),
    ).fetchone()
    if preserved != expected or hashlib.sha256(preserved[1].encode("utf-8")).hexdigest() != preserved[2]:
        raise ValueError("retired CPI archive does not exactly match its source rows and metadata")
    con.execute("DELETE FROM series_observations WHERE series_id = ?", (series_id,))
