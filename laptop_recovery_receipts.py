"""Read-only binding of current-plan laptop receipts; never a physical boot gate.

The caller supplies reviewed, hash-pinned expectations. This reader checks
metadata only: archive restoration, natural-trigger provenance, media identity
and unattended return remain separate evidence requirements.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from zoneinfo import ZoneInfo

import laptop_pull_backup as receiver
from laptop_backup_scheduled import has_component_restore_evidence

SCHEMA = "ARL-RECOVERY-RECEIPT-BINDING-V1"
KINDS = {"observation", "control", "macro"}
MAX_METADATA_BYTES = 16 * 1024**2
MAX_AGE_SECONDS = 36 * 3600


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _pairs(pairs: list) -> dict:
    value = {}
    for key, item in pairs:
        _require(key not in value, "duplicate JSON key")
        value[key] = item
    return value


def _object(raw: bytes) -> dict:
    value = json.loads(raw, object_pairs_hook=_pairs)
    _require(isinstance(value, dict), "expected JSON object")
    return value


def _real(path: Path) -> Path:
    _require(path.is_absolute() and path.resolve(strict=True) == path,
             "path must be absolute and canonical")
    for part in (path, *path.parents):
        info = part.lstat()
        _require(not part.is_symlink()
                 and not (getattr(info, "st_file_attributes", 0) & 0x400),
                 "path contains a link or reparse point")
    return path


def read_bytes(path: Path) -> bytes:
    _real(path)
    _require(path.is_file(), "metadata is not a regular file")
    with path.open("rb") as stream:
        raw = stream.read(MAX_METADATA_BYTES + 1)
    _require(len(raw) <= MAX_METADATA_BYTES, "metadata exceeds size bound")
    return raw


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _hash(value: object, width: int = 64) -> None:
    _require(isinstance(value, str) and re.fullmatch(rf"[0-9a-f]{{{width}}}", value)
             is not None, "invalid pinned digest")


def _relative(value: object) -> str:
    _require(isinstance(value, str), "relative path must be text")
    receiver.validate_relative_path(value, {})
    _require(PurePosixPath(value).as_posix() == value, "relative path is not canonical")
    return value


def _reference(root: Path, reference: object) -> tuple[str, dict]:
    _require(isinstance(reference, dict) and set(reference) == {"path", "sha256"},
             "evidence reference is incomplete")
    relative = _relative(reference["path"])
    _hash(reference["sha256"])
    raw = read_bytes(root / relative)
    _require(_digest(raw) == reference["sha256"], "evidence digest mismatch")
    return relative, _object(raw)


def _timestamp(value: object) -> datetime:
    _require(isinstance(value, str), "timestamp must be text")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _require(parsed.tzinfo is not None, "timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _identity(value: dict, expected: dict) -> None:
    _require(receiver.supported_receipt_plan_identity(value) is not None,
             "receipt is not bound to the current controlled plan")
    fixed = {"schema_version": 1, "result": "PASS", "deviations": [],
             "deviation_authorization": None, "operator": expected["operator"],
             "protected_code_sha": expected["production_sha"],
             "candidate_code_sha": expected["receiver_sha"]}
    _require(type(value.get("schema_version")) is int
             and all(value.get(key) == item for key, item in fixed.items()),
             "receipt runtime, operator or outcome mismatch")
    commands = value.get("exact_commands")
    _require(isinstance(commands, list) and bool(commands)
             and all(isinstance(command, str) and command.strip() for command in commands),
             "receipt command evidence is missing")


def _expectations(expected: dict, now: datetime) -> None:
    fields = {"schema", "production_sha", "receiver_sha", "operator",
              "observation_date", "recorded_backup_root", "scheduled",
              "catalog_sha256", "components"}
    _require(set(expected) == fields and expected["schema"] == SCHEMA,
             "expectation fields are not exact")
    for field in ("production_sha", "receiver_sha"):
        _hash(expected[field], 40)
    _hash(expected["catalog_sha256"])
    _require(isinstance(expected["operator"], str) and bool(expected["operator"].strip()),
             "operator is missing")
    _require(isinstance(expected["components"], dict)
             and set(expected["components"]) == KINDS, "three component pins required")
    _require(isinstance(expected["observation_date"], str)
             and date.fromisoformat(expected["observation_date"])
             == now.astimezone(ZoneInfo("Australia/Hobart")).date(),
             "observation date is not today in Hobart")
    recorded = expected["recorded_backup_root"]
    _require(isinstance(recorded, str), "recorded backup root is missing")
    root = PureWindowsPath(recorded) if PureWindowsPath(recorded).drive else PurePosixPath(recorded)
    _require(root.is_absolute() and ".." not in root.parts, "recorded backup root is invalid")


def _catalog(root: Path, expected: dict) -> tuple[bytes, list[dict]]:
    raw = read_bytes(root / "catalog/generations.jsonl")
    _require(_digest(raw) == expected["catalog_sha256"], "catalog snapshot digest mismatch")
    entries, prior = [], None
    for number, line in enumerate(raw.splitlines(), 1):
        entry = _object(line)
        material = dict(entry)
        digest = material.pop("entry_sha256", None)
        _require(type(entry.get("sequence")) is int and entry["sequence"] == number
                 and entry.get("previous_entry_sha256") == prior
                 and digest == _digest(receiver.canonical_json_bytes(material)),
                 "catalog chain is invalid")
        entries.append(entry)
        prior = digest
    return raw, entries


def _scheduled(root: Path, expected: dict, now: datetime) -> tuple[dict, datetime, bytes]:
    relative, record = _reference(root, expected["scheduled"])
    parts = PurePosixPath(relative).parts
    _require(len(parts) == 3 and parts[:2] == ("catalog", "scheduled-runs"),
             "scheduled receipt is outside its namespace")
    _identity(record, expected)
    _require(record.get("plan_normalized_raw_sha256") == receiver.PLAN_NORMALIZED_RAW_SHA256,
             "scheduled normalized plan evidence is missing")
    _require(record.get("action") in {"BACKUP-LATEST", "BACKFILL", "NO_BACKUP_DATA_WRITE"},
             "scheduled action is not successful backup verification")
    timestamps = record.get("timestamps")
    _require(isinstance(timestamps, dict), "scheduled timestamps are missing")
    completed = _timestamp(timestamps.get("completed_at"))
    _require(0 <= (now - completed).total_seconds() <= MAX_AGE_SECONDS,
             "scheduled receipt is stale or in the future")
    pointer_raw = read_bytes(root / "catalog/latest-scheduled.json")
    _require(_object(pointer_raw) == {"record_path": relative,
             "record_sha256": expected["scheduled"]["sha256"], "result": "PASS"},
             "pinned receipt is not the latest successful execution")
    detail = record.get("detail")
    _require(isinstance(detail, dict), "scheduled inventory is missing")
    inventory = detail.get("after", detail)
    _require(isinstance(inventory, dict) and inventory.get("status") == "UP_TO_DATE",
             "scheduled inventory is not current")
    coverage = inventory.get("inventory")
    _require(inventory.get("backfill_required") is False and inventory.get("backfill_dates") == []
             and isinstance(coverage, dict) and coverage.get("status") == "UP_TO_DATE"
             and coverage.get("missing_completed_dates") == []
             and coverage.get("stale_diagnostics") == [], "scheduled inventory has protection gaps")
    return inventory, completed, pointer_raw


def _scheduled_snapshot(root: Path, expected: dict) -> dict[str, str]:
    """Reject unpointed immutable successors; never repair a mutable pointer."""
    directory = _real(root / "catalog/scheduled-runs")
    paths = sorted(directory.glob("*.json"))
    _require(len(paths) <= 4096, "scheduled record count exceeds bound")
    predecessor = {"record_path": expected["scheduled"]["path"],
                   "record_sha256": expected["scheduled"]["sha256"]}
    snapshot = {}
    for path in paths:
        _require(path.stat().st_size <= 1024**2, "scheduled record exceeds size bound")
        raw = read_bytes(path)
        _require(len(raw) <= 1024**2, "scheduled record exceeds size bound")
        record = _object(raw)
        _require(record.get("previous_execution") != predecessor,
                 "latest pointer has an unpointed scheduled successor")
        snapshot[path.name] = _digest(raw)
    return snapshot


def _component(root: Path, expected: dict, entries: list, inventory: dict,
               completed: datetime, kind: str) -> dict:
    reference = expected["components"][kind]
    relative, receipt = _reference(root, reference)
    _identity(receipt, expected)
    _require(receipt.get("kind") == kind and PurePosixPath(relative).parts[0]
             == ("observations" if kind == "observation" else kind),
             "component kind or namespace mismatch")
    matches = [entry for entry in entries if entry.get("receipt_path") == relative]
    _require(len(matches) == 1, "component is absent or ambiguous in catalog")
    entry = matches[0]
    _require(entry.get("receipt_sha256") == reference["sha256"]
             and all(entry.get(key) == receipt.get(key) for key in
                     ("kind", "result", "archive_sha256", "source_manifest_sha256", "observation_date")),
             "component does not match catalog")
    for field in ("archive_sha256", "source_manifest_sha256"):
        _hash(receipt.get(field))
    state = inventory.get(kind)
    recorded = expected["recorded_backup_root"]
    path_type = PureWindowsPath if PureWindowsPath(recorded).drive else PurePosixPath
    _require(isinstance(state, dict) and state.get("status") == "UP_TO_DATE"
             and type(state.get("catalog_sequence")) is int
             and state["catalog_sequence"] == entry["sequence"]
             and state.get("receipt_path") == str(path_type(recorded) / relative),
             "component does not match scheduled inventory")
    _require(_timestamp(receipt.get("completed_at")) <= completed,
             "component was completed after the scheduled receipt")
    _require(has_component_restore_evidence(receipt.get("checks"), kind),
             "component receipt lacks restore evidence")
    if kind == "observation":
        _require(receipt.get("observation_date") == expected["observation_date"]
                 and state.get("observation_date") == expected["observation_date"]
                 and state.get("archive_sha256") == receipt["archive_sha256"],
                 "observation does not match the requested current day")
    return {"kind": kind, "catalog_sequence": entry["sequence"], **reference}


def verify_binding(root: Path, expected: dict, now: datetime) -> dict:
    """Validate pinned receipt metadata without invoking a writer or live probe."""
    _require(now.tzinfo is not None, "verification time must include a timezone")
    _real(root)
    _expectations(expected, now)
    receiver.verify_plan_document()
    catalog_raw, entries = _catalog(root, expected)
    inventory, completed, pointer_raw = _scheduled(root, expected, now)
    scheduled_snapshot = _scheduled_snapshot(root, expected)
    components = [_component(root, expected, entries, inventory, completed, kind)
                  for kind in sorted(KINDS)]
    # A concurrent edit need not advance either catalog or mutable pointer.
    # Recheck every hash-bound record after interpreting all component metadata.
    for reference in (expected["scheduled"], *expected["components"].values()):
        _reference(root, reference)
    _require(_scheduled_snapshot(root, expected) == scheduled_snapshot,
             "scheduled record inventory changed during verification")
    _require(read_bytes(root / "catalog/generations.jsonl") == catalog_raw
             and read_bytes(root / "catalog/latest-scheduled.json") == pointer_raw,
             "backup metadata changed during verification")
    return {"schema": SCHEMA, "checked_at": now.isoformat(), "receipt_binding": "PASS",
            "components": components, "physical_recovery": "BLOCKED",
            "natural_trigger": "UNVERIFIED", "archive_restore": "NOT_RUN",
            "scope": "Pinned receipt metadata only; no A3 or A4 acceptance"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--expectations", type=Path, required=True)
    parser.add_argument("--expectations-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        _hash(args.expectations_sha256)
        raw = read_bytes(args.expectations)
        _require(_digest(raw) == args.expectations_sha256, "expectations digest mismatch")
        result = verify_binding(args.target, _object(raw), datetime.now(timezone.utc))
    except (ValueError, OSError, TypeError, KeyError) as error:
        print(json.dumps({"receipt_binding": "FAIL", "physical_recovery": "BLOCKED",
                          "error": str(error)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
