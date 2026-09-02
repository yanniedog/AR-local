"""Bounded verification for canonical and retained historical daily exports."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from cdr_observation import load_verified_observation
from cdr_observation_db import SCHEMA_VERSION as OBSERVATION_SCHEMA_VERSION


HISTORICAL_DAILY_SCHEMA_SQL_SHA256 = {
    "6": {
        "bank_items": "73fe34d78096f0bf097b11f99bca0a5d0ea97a28ddc78f8b303ed3ac6ec287e5",
        "bank_products": "aac255948d8428386f8ff82e8ae21048bdad976c33fa3d1c5e13955c34cbac4d",
        "bank_rates": "de1518ed0e183e244b9821c92e6bfd53138eb77b11f48030ccc886671b695f97",
        "runs": "db53d10ea555a157e80ba6cf3fb788568fedb33d192279d6ba9fe2ed67a7e84e",
        "schema_meta": "df329d1ca13122b7aafc5ebfade279b177a46ca05b5e266b6c571b29b29da92c",
    },
    "7": {
        "bank_items": "73fe34d78096f0bf097b11f99bca0a5d0ea97a28ddc78f8b303ed3ac6ec287e5",
        "bank_products": "aac255948d8428386f8ff82e8ae21048bdad976c33fa3d1c5e13955c34cbac4d",
        "bank_rates": "0628240b062e356f2608a9d18d684289c7bb458ab3acdb9f5dd3c1bfe2429191",
        "runs": "db53d10ea555a157e80ba6cf3fb788568fedb33d192279d6ba9fe2ed67a7e84e",
        "schema_meta": "df329d1ca13122b7aafc5ebfade279b177a46ca05b5e266b6c571b29b29da92c",
    },
    "8": {
        "bank_items": "73fe34d78096f0bf097b11f99bca0a5d0ea97a28ddc78f8b303ed3ac6ec287e5",
        "bank_product_changes": "ec8fd2a618bd34c04e84e8e28401ed9f3c848e00bb27e3e5b20f03f225062049",
        "bank_product_facts": "2b4ab300506dc67339d0982de038042c8cde0cd3cc8dc9b8d51ec0b1a4c2f788",
        "bank_products": "aac255948d8428386f8ff82e8ae21048bdad976c33fa3d1c5e13955c34cbac4d",
        "bank_rates": "0628240b062e356f2608a9d18d684289c7bb458ab3acdb9f5dd3c1bfe2429191",
        "runs": "db53d10ea555a157e80ba6cf3fb788568fedb33d192279d6ba9fe2ed67a7e84e",
        "schema_meta": "df329d1ca13122b7aafc5ebfade279b177a46ca05b5e266b6c571b29b29da92c",
    },
}
HISTORICAL_EXPORT_POPULATIONS = {
    "6": {"products", "rates", "fees", "features", "eligibility", "constraints", "failures"},
    "7": {"products", "rates", "fees", "features", "eligibility", "constraints", "failures"},
    "8": {
        "products", "rates", "fees", "features", "eligibility", "constraints",
        "product_facts", "product_changes", "failures", "holder_attempts",
    },
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b""):
            digest.update(block)
    return digest.hexdigest()


def daily_reconciliation_bounded(database: Path) -> dict[str, object]:
    with closing(sqlite3.connect(
        f"file:{database.as_posix()}?mode=ro&immutable=1", uri=True
    )) as connection:
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if user_version == OBSERVATION_SCHEMA_VERSION:
        observation, accounting = load_verified_observation(database.parent)
        return {
            "run_date": observation["observation_date"],
            "counts": observation["row_counts"],
            "database_counts": observation["row_counts"],
            "schema_version": str(user_version),
            "accounting_id": accounting["accounting_id"],
            "observation_sha256": _sha256_file(database.parent / "observation-v1.json"),
            "accounting_sha256": _sha256_file(database.parent / "product-accounting-v1.json"),
            "database_sha256": _sha256_file(database),
            "validation_mode": "canonical_observation_and_immutable_sqlite_v9",
        }

    banks_files = sorted(database.parent.glob("banks-*.json"))
    if len(banks_files) != 1:
        raise ValueError("daily export must contain exactly one banks JSON")
    date = banks_files[0].stem.removeprefix("banks-")
    banks = json.loads(banks_files[0].read_text(encoding="utf-8"))
    if not isinstance(banks, dict):
        raise ValueError("daily banks export is not a JSON object")
    exported = {key: len(value) for key, value in banks.items() if isinstance(value, list)}
    with closing(sqlite3.connect(
        f"file:{database.as_posix()}?mode=ro&immutable=1", uri=True
    )) as connection:
        schema_sql = {
            str(name): hashlib.sha256(str(sql).encode("utf-8")).hexdigest()
            for name, sql in connection.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type = 'table' AND name != 'sqlite_sequence'"
            )
        }
        tables = set(schema_sql)
        if "schema_meta" not in tables:
            raise ValueError("daily database schema metadata is missing")
        schema_row = connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'version'"
        ).fetchone()
        schema_version = str(schema_row[0]) if schema_row else ""
        if schema_sql != HISTORICAL_DAILY_SCHEMA_SQL_SHA256.get(schema_version):
            raise ValueError("daily database definition does not match its schema version")
        if set(exported) != HISTORICAL_EXPORT_POPULATIONS[schema_version]:
            raise ValueError("daily export populations do not match its schema version")
        run = connection.execute("SELECT run_date, banks_counts_json FROM runs").fetchall()
        actual = {
            "products": connection.execute("SELECT COUNT(*) FROM bank_products").fetchone()[0],
            "rates": connection.execute("SELECT COUNT(*) FROM bank_rates").fetchone()[0],
        }
        if "bank_product_facts" in tables:
            actual["product_facts"] = connection.execute(
                "SELECT COUNT(*) FROM bank_product_facts"
            ).fetchone()[0]
        if "bank_product_changes" in tables:
            actual["product_changes"] = connection.execute(
                "SELECT COUNT(*) FROM bank_product_changes"
            ).fetchone()[0]
        for group in ("fees", "features", "eligibility", "constraints"):
            actual[group] = connection.execute(
                "SELECT COUNT(*) FROM bank_items WHERE item_group = ?", (group,)
            ).fetchone()[0]
    if len(run) != 1 or run[0][0] != date:
        raise ValueError("daily database run metadata is invalid")
    expected = json.loads(run[0][1])
    if not isinstance(expected, dict) or exported != expected or any(
        expected.get(key) != value for key, value in actual.items()
    ):
        raise ValueError("daily export population counts do not reconcile")
    legacy_manifest = database.parent / "dashboard-cache/latest.json"
    manifest = json.loads(legacy_manifest.read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("run_date") != date
        or manifest.get("banks_counts") != expected
    ):
        raise ValueError("historical manifest does not match daily database")
    return {
        "run_date": date,
        "counts": exported,
        "database_counts": actual,
        "schema_version": schema_version,
        "schema_tables": sorted(tables),
        "unpersisted_populations": sorted(set(exported) - set(actual)),
        "banks_json": banks_files[0].name,
        "banks_json_bytes": banks_files[0].stat().st_size,
        "banks_json_sha256": _sha256_file(banks_files[0]),
        "legacy_manifest_sha256": _sha256_file(legacy_manifest),
        "validation_mode": "legacy_bounded_database_manifest_and_byte_hash",
    }
