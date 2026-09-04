"""Bounded verification for canonical and retained historical daily exports."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Mapping

from ar_local_daily_reconciliation import legacy_daily_reconciliation
from cdr_attempt_evidence_promotion import (
    AttemptEvidencePromotionError,
    verify_promoted_attempt_evidence,
)
from cdr_journal_evidence import validate_journal_evidence
from cdr_observation import load_verified_observation
from cdr_observation_db import SCHEMA_VERSION as OBSERVATION_SCHEMA_VERSION


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_promoted_product_evidence(
    export_root: Path, accounting: Mapping[str, object]
) -> None:
    status_path = export_root / "ingest-status.json"
    if status_path.is_symlink() or not status_path.is_file():
        raise ValueError("canonical observation lacks promoted ingest evidence")
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("promoted ingest status is unreadable") from error
    pointer = status.get("raw_attempt_journal") if isinstance(status, Mapping) else None
    if not isinstance(pointer, Mapping):
        raise ValueError("promoted ingest evidence pointer is absent")
    try:
        journal = verify_promoted_attempt_evidence(
            export_root,
            pointer,
            expected_head_digest=str(accounting["raw_attempt_journal_digest"]),
            expected_session_id=str(accounting["accounting_id"]),
        )
    except AttemptEvidencePromotionError as error:
        raise ValueError(str(error)) from error
    validate_journal_evidence(accounting, status.get("provider_states"), journal)


def daily_reconciliation_bounded(database: Path) -> dict[str, object]:
    with closing(sqlite3.connect(
        f"file:{database.as_posix()}?mode=ro&immutable=1", uri=True
    )) as connection:
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if user_version == OBSERVATION_SCHEMA_VERSION:
        observation, accounting = load_verified_observation(database.parent)
        _validate_promoted_product_evidence(database.parent, accounting)
        return {
            "run_date": observation["observation_date"],
            "counts": observation["row_counts"],
            "database_counts": observation["row_counts"],
            "schema_version": str(user_version),
            "accounting_id": accounting["accounting_id"],
            "observation_sha256": _sha256_file(database.parent / "observation-v1.json"),
            "accounting_sha256": _sha256_file(database.parent / "product-accounting-v1.json"),
            "database_sha256": _sha256_file(database),
            "validation_mode": (
                "canonical_observation_and_immutable_sqlite_"
                f"v{OBSERVATION_SCHEMA_VERSION}"
            ),
        }

    return legacy_daily_reconciliation(database)
