"""Fail-closed verification for AR-local preservation restore drills."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Mapping

from jsonschema import Draft202012Validator, FormatChecker

from ar_local_backup_policy import canonical_json_bytes, sha256_file
from ar_local_daily_reconciliation import legacy_daily_reconciliation
from ar_local_sqlite_health import check_sqlite_health, sqlite_health_ok
from cdr_observation import load_verified_observation
from cdr_observation_db import SCHEMA_VERSION as OBSERVATION_SCHEMA_VERSION


RESTORE_ACCEPTANCE_SCHEMA = (
    Path(__file__).resolve().parent / "contracts/pi-restore-acceptance-v1.schema.json"
)
def _json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _immutable_connection(path: Path) -> sqlite3.Connection:
    """Open preserved SQLite evidence without creating WAL/SHM sidecars."""

    return sqlite3.connect(
        f"file:{path.as_posix()}?mode=ro&immutable=1",
        uri=True,
    )


def _observation_reconciliation(database: Path) -> dict[str, object]:
    observation, accounting = load_verified_observation(database.parent)
    return {
        "run_date": observation["observation_date"],
        "counts": observation["row_counts"],
        "database_counts": observation["row_counts"],
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "observation_sha256": sha256_file(database.parent / "observation-v1.json"),
        "accounting_sha256": sha256_file(
            database.parent / "product-accounting-v1.json"
        ),
        "database_sha256": sha256_file(database),
        "accounting_id": accounting["accounting_id"],
        "validation_mode": (
            "canonical_observation_and_immutable_sqlite_"
            f"v{OBSERVATION_SCHEMA_VERSION}"
        ),
    }


def _completion_marker_valid(
    marker: Mapping[str, object],
    state_dir: Path,
    observation_date: str,
    marker_relative: Path,
) -> bool:
    from cdr_export_contract import load_contract
    from cdr_ledger_v2 import ledger_root, verify_event_artifacts

    try:
        if marker.get("finalization_schema_version") != 2 or marker.get("ledger_state") != "finalized":
            return False
        if marker.get("run_date") != observation_date:
            return False
        counts = marker.get("banks_counts") or marker.get("banks") or {}
        if not isinstance(counts, Mapping) or int(counts.get("rates") or 0) <= 0:
            return False
        relative = Path(str(marker.get("export_contract_path") or ""))
        if relative.is_absolute() or ".." in relative.parts:
            return False
        contract_path = (state_dir / relative).resolve()
        if not contract_path.is_relative_to(state_dir.resolve()):
            return False
        contract = load_contract(contract_path)
        if contract.get("completion_marker_path") != marker_relative.as_posix():
            return False
        if contract.get("generation_id") != marker.get("generation_id"):
            return False
        if contract.get("observation_date") != observation_date:
            return False
        if contract.get("observation_state") != marker.get("observation_state"):
            return False
        if contract.get("contract_digest") != marker.get("export_contract_digest"):
            return False
        event_path = (
            ledger_root(state_dir)
            / "events"
            / observation_date
            / f"{contract['generation_id']}.json"
        )
        event = _json(event_path)
        verify_event_artifacts(state_dir, event)
        return event.get("event_digest") == marker.get("ledger_event_digest")
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


def _pointer_matches_marker(
    pointer: Mapping[str, object], marker: Mapping[str, object], state_dir: Path
) -> bool:
    from cdr_export_contract import load_contract

    try:
        relative = Path(str(marker["export_contract_path"]))
        contract_path = (state_dir / relative).resolve()
        if relative.is_absolute() or ".." in relative.parts or not contract_path.is_relative_to(state_dir.resolve()):
            return False
        contract = load_contract(contract_path)
        expected = {
            "schema_version": 2,
            "observation_date": marker["run_date"],
            "generation_id": marker["generation_id"],
            "observation_state": marker["observation_state"],
            "ledger_event_digest": marker["ledger_event_digest"],
            "marker_path": str(pointer["marker_path"]),
            "export_path": contract["source_path"],
        }
        return dict(pointer) == expected
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


def _verify_daily_database(path: Path, data_root: Path) -> tuple[dict[str, object], list[str]]:
    findings: list[str] = []
    with closing(_immutable_connection(path)) as connection:
        health = check_sqlite_health(connection)
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        schema_version: object = user_version
        if user_version != OBSERVATION_SCHEMA_VERSION:
            row = (
                connection.execute(
                    "SELECT value FROM schema_meta WHERE key = 'version'"
                ).fetchone()
                if "schema_meta" in tables
                else None
            )
            schema_version = row[0] if row else None
    record: dict[str, object] = {
        "path": path.relative_to(data_root).as_posix(),
        **health,
        "schema_version": schema_version,
    }
    if not sqlite_health_ok(health):
        findings.append(f"sqlite_health_check:{path}")
    try:
        reconciliation = (
            _observation_reconciliation(path)
            if user_version == OBSERVATION_SCHEMA_VERSION
            else legacy_daily_reconciliation(path)
        )
        record["schema_version"] = reconciliation["schema_version"]
        record["export_reconciliation"] = reconciliation
    except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
        findings.append(f"daily_reconciliation_mismatch:{path}:{exc}")
    return record, findings


def verify_restored_state(data_root: Path) -> dict[str, object]:
    from cdr_export_contract import load_contract
    from cdr_ledger_v2 import verify_ledger

    findings: list[str] = []
    sqlite_results: list[dict[str, object]] = []
    daily_databases: list[Path] = []
    for path in sorted(data_root.rglob("*.sqlite")):
        try:
            if path.name == "local-cdr.sqlite":
                daily_databases.append(path.resolve())
                record, database_findings = _verify_daily_database(path, data_root)
                sqlite_results.append(record)
                findings.extend(database_findings)
                continue
            with closing(_immutable_connection(path)) as connection:
                health = check_sqlite_health(connection)
            sqlite_results.append(
                {"path": path.relative_to(data_root).as_posix(), **health}
            )
            if not sqlite_health_ok(health):
                findings.append(f"sqlite_health_check:{path}")
        except sqlite3.Error:
            findings.append(f"sqlite_unreadable:{path}")
    if not daily_databases:
        findings.append("daily_database_missing")

    state = data_root / "state"
    contract_paths = sorted((state / "export-contracts-v2").glob("*/*.json"))
    if not contract_paths:
        findings.append("export_contract_missing")
    for path in contract_paths:
        try:
            load_contract(path)
        except (OSError, ValueError, json.JSONDecodeError):
            findings.append(f"invalid_contract:{path.relative_to(data_root)}")
    if (state / "ledger-v2").exists():
        try:
            ledger = verify_ledger(state)
            if not ledger.get("ok"):
                findings.append("ledger_verification_failed")
        except (OSError, ValueError, json.JSONDecodeError):
            ledger = {"ok": False}
            findings.append("ledger_unreadable")
    else:
        ledger = {"ok": False, "reason": "missing"}
        findings.append("ledger_missing")

    pointer_paths = sorted((state / "observation-pointers-v2").glob("*.json"))
    latest_pointer = state / "observation-pointers-v2/latest-observation.json"
    if not pointer_paths:
        findings.append("observation_pointer_missing")
    if not latest_pointer.is_file() or latest_pointer.is_symlink():
        findings.append("latest_observation_pointer_missing")
    selected: dict[str, object] | None = None
    for pointer in pointer_paths:
        pointer_findings, observation = _verify_pointer(
            pointer, latest_pointer, state, data_root, daily_databases
        )
        findings.extend(pointer_findings)
        if observation is not None:
            selected = observation
    if latest_pointer.is_file() and selected is None:
        findings.append("latest_observation_not_verified")
    return {
        "ok": not findings,
        "findings": findings,
        "sqlite": sqlite_results,
        "ledger": ledger,
        "selected_observation": selected,
    }


def _verify_pointer(
    pointer: Path,
    latest_pointer: Path,
    state: Path,
    data_root: Path,
    daily_databases: list[Path],
) -> tuple[list[str], dict[str, object] | None]:
    findings: list[str] = []
    try:
        value = _json(pointer)
        relative = Path(str(value.get("marker_path") or ""))
        target = (state / relative).resolve()
        if relative.is_absolute() or ".." in relative.parts or not target.is_relative_to(state.resolve()):
            return [f"pointer_escape:{pointer.name}"], None
        if not target.is_file() or target.is_symlink():
            return [f"pointer_target_missing:{pointer.name}"], None
        marker = _json(target)
        observation_date = str(value.get("observation_date") or "")
        if not _completion_marker_valid(marker, state, observation_date, relative):
            return [f"pointer_marker_invalid:{pointer.name}"], None
        if not _pointer_matches_marker(value, marker, state):
            return [f"pointer_fields_mismatch:{pointer.name}"], None
        if pointer != latest_pointer:
            return findings, None
        export_relative = Path(str(value.get("export_path") or ""))
        export_root = (data_root / export_relative).resolve()
        if export_relative.is_absolute() or ".." in export_relative.parts or not export_root.is_relative_to(data_root.resolve()):
            return ["latest_observation_export_escape"], None
        database = (export_root / "local-cdr.sqlite").resolve()
        if not export_root.is_dir():
            return ["latest_observation_export_missing"], None
        if database not in daily_databases:
            return ["latest_observation_database_missing"], None
        return findings, {
            "observation_date": value["observation_date"],
            "generation_id": value["generation_id"],
            "observation_state": value["observation_state"],
            "ledger_event_digest": value["ledger_event_digest"],
            "export_contract_digest": marker["export_contract_digest"],
            "export_contract_path": str(marker["export_contract_path"]),
            "export_contract_sha256": sha256_file(
                state / str(marker["export_contract_path"])
            ),
            "marker_path": relative.as_posix(),
            "marker_sha256": sha256_file(target),
            "export_path": export_relative.as_posix(),
            "database_path": database.relative_to(data_root).as_posix(),
            "database_sha256": sha256_file(database),
            "ledger_event_path": (
                Path("ledger-v2/events")
                / str(value["observation_date"])
                / f"{value['generation_id']}.json"
            ).as_posix(),
            "ledger_event_sha256": sha256_file(
                state
                / "ledger-v2/events"
                / str(value["observation_date"])
                / f"{value['generation_id']}.json"
            ),
        }
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return [f"pointer_invalid:{pointer.name}"], None


def verify_restored_manifest_files(
    manifest: Mapping[str, object], destination: Path
) -> dict[str, object]:
    """Prove copied data and macro bytes exactly match the snapshot manifest."""

    entries = manifest.get("files")
    if not isinstance(entries, list):
        return {"ok": False, "findings": ["restored_manifest_files_invalid"]}
    expected = [
        {"path": entry.get("path"), "size": entry.get("size"), "sha256": entry.get("sha256")}
        for entry in entries
        if isinstance(entry, Mapping)
        and str(entry.get("path") or "").startswith(("data/", "macro/"))
    ]
    actual, structural_findings = _restored_entries(destination)
    expected_by_path = {str(entry["path"]): entry for entry in expected}
    actual_by_path = {str(entry["path"]): entry for entry in actual}
    findings = [
        *structural_findings,
        *(f"restored_file_missing:{path}" for path in sorted(expected_by_path.keys() - actual_by_path.keys())),
        *(f"restored_file_extra:{path}" for path in sorted(actual_by_path.keys() - expected_by_path.keys())),
        *(
            f"restored_file_changed:{path}"
            for path in sorted(expected_by_path.keys() & actual_by_path.keys())
            if actual_by_path[path] != expected_by_path[path]
        ),
    ]
    expected_payload = canonical_json_bytes(sorted(expected, key=lambda item: str(item["path"])))
    actual_payload = canonical_json_bytes(sorted(actual, key=lambda item: str(item["path"])))
    return {
        "ok": not findings,
        "findings": findings,
        "file_count": len(actual),
        "total_bytes": sum(int(item["size"]) for item in actual),
        "source_file_set_sha256": hashlib.sha256(expected_payload).hexdigest(),
        "restored_file_set_sha256": hashlib.sha256(actual_payload).hexdigest(),
    }


def _restored_entries(
    root: Path,
) -> tuple[list[dict[str, object]], list[str]]:
    entries: list[dict[str, object]] = []
    findings: list[str] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            findings.append(f"restored_symlink:{relative}")
        elif path.is_file():
            entries.append(
                {
                    "path": relative,
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        elif not path.is_dir():
            findings.append(f"restored_special:{relative}")
    return entries, findings


def validate_restore_acceptance(
    receipt: Mapping[str, object],
    manifest: Mapping[str, object],
    protected_code_sha: str,
) -> dict[str, object]:
    findings: list[str] = []
    try:
        schema = _json(RESTORE_ACCEPTANCE_SCHEMA)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        for error in sorted(validator.iter_errors(receipt), key=lambda item: list(item.path)):
            location = ".".join(str(part) for part in error.path) or "$"
            findings.append(f"restore_schema_invalid:{location}:{error.message}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        findings.append(f"restore_schema_unavailable:{type(exc).__name__}")
    checks = receipt.get("checks")
    if isinstance(checks, Mapping):
        restored = checks.get("restored_files")
        manifest_entries = manifest.get("files")
        expected_entries = [
            {
                "path": entry.get("path"),
                "size": entry.get("size"),
                "sha256": entry.get("sha256"),
            }
            for entry in manifest_entries
            if isinstance(manifest_entries, list)
            and isinstance(entry, Mapping)
            and str(entry.get("path") or "").startswith(("data/", "macro/"))
        ] if isinstance(manifest_entries, list) else []
        expected_digest = hashlib.sha256(
            canonical_json_bytes(
                sorted(expected_entries, key=lambda item: str(item["path"]))
            )
        ).hexdigest()
        if not isinstance(restored, Mapping) or (
            restored.get("source_file_set_sha256") != expected_digest
            or restored.get("restored_file_set_sha256") != expected_digest
        ):
            findings.append("restore_file_set_digest_mismatch")
        elif (
            restored.get("file_count") != len(expected_entries)
            or restored.get("total_bytes")
            != sum(int(entry["size"]) for entry in expected_entries)
        ):
            findings.append("restore_file_set_size_mismatch")
        selected = checks.get("selected_observation")
        if isinstance(selected, Mapping):
            expected_by_path = {
                str(entry["path"]): entry for entry in expected_entries
            }
            selected_hashes = {
                f"data/{selected.get('database_path')}": selected.get(
                    "database_sha256"
                ),
                f"data/state/{selected.get('marker_path')}": selected.get(
                    "marker_sha256"
                ),
                f"data/state/{selected.get('export_contract_path')}": selected.get(
                    "export_contract_sha256"
                ),
                f"data/state/{selected.get('ledger_event_path')}": selected.get(
                    "ledger_event_sha256"
                ),
            }
            for path, digest in selected_hashes.items():
                if expected_by_path.get(path, {}).get("sha256") != digest:
                    findings.append(f"restore_observation_hash_mismatch:{path}")
    if (
        receipt.get("candidate_code_sha") != protected_code_sha
        or manifest.get("candidate_code_sha") != protected_code_sha
    ):
        findings.append("restore_candidate_sha_mismatch")
    return {"ok": not findings, "findings": findings}
