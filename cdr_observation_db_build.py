"""Atomic create-once writer for validated observation databases."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, Sequence

from cdr_observation_db_schema import APPLICATION_ID, SCHEMA_SQL, SCHEMA_VERSION

if TYPE_CHECKING:
    from cdr_observation_db import DatabaseBuildResult

FailureHook = Callable[[str], None]


def _insert_many(
    connection: sqlite3.Connection,
    table: str,
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> None:
    if rows:
        marks = ",".join("?" for _ in columns)
        connection.executemany(
            f"INSERT INTO {table} ({','.join(columns)}) VALUES ({marks})", rows
        )


def _storage_rows(
    accounting_id: str,
    rows: Sequence[Mapping[str, Any]],
    columns: Sequence[str],
    *,
    boolean_fields: frozenset[str] = frozenset(),
) -> list[tuple[Any, ...]]:
    from cdr_observation_db import _json_text

    def stored(row: Mapping[str, Any], column: str) -> Any:
        key = column.removesuffix("_json")
        if column.endswith("_json"):
            return _json_text(row[key])
        if key in boolean_fields:
            return None if row[key] is None else int(row[key])
        return row[key]

    return [
        (accounting_id, *(stored(row, column) for column in columns[1:]))
        for row in rows
    ]


def _write_accounting(
    connection: sqlite3.Connection,
    accounting: Mapping[str, Any],
    generated_at: str,
    projections: Mapping[str, Sequence[Any]],
) -> None:
    from cdr_observation_db import _json_bytes, _json_text, _projection_counts

    accounting_id = accounting["accounting_id"]
    connection.execute(
        "INSERT INTO runs VALUES(?,?,?,?,?,?)",
        (
            accounting["observation_date"],
            accounting_id,
            accounting["raw_attempt_journal_digest"],
            generated_at,
            _json_bytes(accounting),
            _json_text(_projection_counts(projections)),
        ),
    )
    specifications = (
        (
            "bank_provider_observations",
            "providers",
            (
                "accounting_id", "provider_uid", "brand_name", "datasets_json",
                "affected_sections_json", "state", "attempted", "population_known",
                "discovered_count", "published_full_count",
                "published_core_only_count", "omitted_valid_count",
                "quarantined_invalid_count", "issue_count", "issue_ids_json",
            ),
            frozenset({"attempted", "population_known"}),
        ),
        (
            "bank_product_dispositions",
            "products",
            (
                "accounting_id", "product_uid", "provider_uid", "cdr_product_id",
                "dataset", "display_name", "legacy_product_key", "disposition",
                "reason_codes_json", "evidence_ids_json", "core_valid",
                "details_complete",
            ),
            frozenset({"core_valid", "details_complete"}),
        ),
        (
            "bank_observation_issues",
            "issues",
            (
                "accounting_id", "issue_id", "scope", "provider_uid", "product_uid",
                "affected_sections_json", "phase", "code", "http_status",
                "occurrence_count", "first_seen_at", "last_seen_at",
                "evidence_digest", "disposition", "public_safe",
            ),
            frozenset({"public_safe"}),
        ),
    )
    for table, group, columns, boolean_fields in specifications:
        _insert_many(
            connection,
            table,
            columns,
            _storage_rows(
                accounting_id,
                accounting[group],
                columns,
                boolean_fields=boolean_fields,
            ),
        )


def _write_projections(
    connection: sqlite3.Connection,
    accounting_id: str,
    projections: Mapping[str, Sequence[Mapping[str, Any]]],
) -> None:
    specifications = {
        "products": (
            "product_uid", "provider_uid", "dataset", "cdr_product_id",
            "legacy_product_key", "document_json",
        ),
        "rates": (
            "rate_uid", "product_uid", "rate_index", "rate", "comparison_rate",
            "document_json",
        ),
        "items": ("product_uid", "item_group", "item_index", "document_json"),
        "product_facts": (
            "product_uid", "fact_id", "kind", "canonical_key", "value_type",
            "value_boolean", "value_number", "value_text", "min_value",
            "max_value", "document_json",
        ),
        "product_changes": (
            "event_id", "provider_uid", "product_uid", "event_type",
            "canonical_key", "document_json",
        ),
    }
    for group, fields in specifications.items():
        columns = ("accounting_id", *fields)
        booleans = frozenset({"value_boolean"}) if group == "product_facts" else frozenset()
        _insert_many(
            connection,
            f"bank_{group}",
            columns,
            _storage_rows(
                accounting_id,
                projections[group],
                columns,
                boolean_fields=booleans,
            ),
        )


def _configure_writer(connection: sqlite3.Connection) -> None:
    from cdr_observation_db import _fail

    connection.execute("PRAGMA foreign_keys=ON")
    if connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0].lower() != "delete":
        _fail("SQLite refused DELETE journal mode")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA trusted_schema=OFF")
    connection.execute("PRAGMA writable_schema=OFF")
    connection.execute("PRAGMA secure_delete=ON")
    connection.execute("PRAGMA temp_store=MEMORY")


def _fsync_file(path: Path) -> None:
    with path.open("rb+") as stream:
        os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _cleanup_candidate(path: Path) -> None:
    from cdr_observation_db import _sidecar_paths

    path.unlink(missing_ok=True)
    for sidecar in _sidecar_paths(path):
        sidecar.unlink(missing_ok=True)


def build_observation_database(
    target: Path | str,
    *,
    accounting: Mapping[str, Any],
    projections: Mapping[str, Any],
    generated_at: str,
    normalization_version: str,
    failure_hook: FailureHook | None = None,
) -> DatabaseBuildResult:
    """Build privately, verify, then atomically install without overwriting history."""

    from cdr_observation_db import (
        DatabaseBuildResult,
        _fail,
        _json_bytes,
        _projection_counts,
        _schema_fingerprint,
        _sha256,
        _text,
        _timestamp_on_observation_date,
        validate_observation_inputs,
        verify_observation_database,
    )

    supplied = Path(target).expanduser()
    if supplied.is_symlink():
        _fail("database path must not be a symlink")
    destination = supplied.resolve()
    normalized_accounting, normalized_projections = validate_observation_inputs(
        accounting, projections
    )
    sidecar_bytes = _json_bytes(normalized_accounting)
    generated_at = _timestamp_on_observation_date(
        generated_at, normalized_accounting["observation_date"], "generated_at"
    )
    normalization_version = _text(normalization_version, "normalization_version")
    hook = failure_hook or (lambda _stage: None)
    verification_kwargs = {
        "expected_sidecar_bytes": sidecar_bytes,
        "expected_projections": normalized_projections,
        "expected_normalization_version": normalization_version,
        "expected_generated_at": generated_at,
    }
    if destination.exists():
        return DatabaseBuildResult(
            verify_observation_database(destination, **verification_kwargs), False
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, candidate_name = tempfile.mkstemp(
        prefix=f".{destination.name}.tmp-", dir=destination.parent
    )
    os.close(descriptor)
    candidate, installed = Path(candidate_name), False
    try:
        os.chmod(candidate, 0o600)
        connection = sqlite3.connect(candidate)
        try:
            _configure_writer(connection)
            connection.executescript(SCHEMA_SQL)
            connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            hook("after_schema")
            connection.execute("BEGIN IMMEDIATE")
            _write_accounting(
                connection, normalized_accounting, generated_at, normalized_projections
            )
            hook("after_accounting")
            _write_projections(
                connection,
                normalized_accounting["accounting_id"],
                normalized_projections,
            )
            hook("after_projections")
            schema_sha = _schema_fingerprint(connection)
            projection_sha = _sha256(
                _json_bytes({"schema_version": 1, **normalized_projections})
            )
            connection.executemany(
                "INSERT INTO schema_meta VALUES(?,?)",
                (
                    ("schema_sha256", schema_sha),
                    ("accounting_sha256", _sha256(sidecar_bytes)),
                    ("projections_sha256", projection_sha),
                    ("normalization_version", normalization_version),
                ),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        hook("after_commit")
        _fsync_file(candidate)
        verified = verify_observation_database(candidate, **verification_kwargs)
        hook("after_verify")
        hook("before_install")
        try:
            os.link(candidate, destination)
            installed = True
        except FileExistsError:
            return DatabaseBuildResult(
                verify_observation_database(destination, **verification_kwargs), False
            )
        hook("after_install")
        _cleanup_candidate(candidate)
        _fsync_directory(destination.parent)
        try:
            verification = verify_observation_database(
                destination, **verification_kwargs
            )
            if verification.database_sha256 != verified.database_sha256:
                _fail("installed database differs from verified candidate")
        except BaseException:
            _cleanup_candidate(destination)
            raise
        return DatabaseBuildResult(verification, True)
    finally:
        _cleanup_candidate(candidate)
        if installed:
            _fsync_directory(destination.parent)
