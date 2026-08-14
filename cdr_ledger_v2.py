"""Append-only ledger events bound to immutable export-contract v2 records."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from cdr_atomic import atomic_write_json, canonical_json_bytes
from cdr_export_contract import contract_digest, hash_file, load_contract
from cdr_file_lock import FileLock

SCHEMA_VERSION = 2
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ledger_root(state_dir: Path) -> Path:
    return state_dir.expanduser().resolve() / "ledger-v2"


def event_digest(event: Mapping[str, Any]) -> str:
    material = dict(event)
    material.pop("event_digest", None)
    return hashlib.sha256(canonical_json_bytes(material)).hexdigest()


def _read_head(root: Path) -> Optional[dict[str, Any]]:
    path = root / "head.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not _DIGEST.fullmatch(str(payload.get("event_digest") or "")):
        raise ValueError("ledger-v2 head has an invalid digest")
    return payload


def _validate_event(event: Mapping[str, Any]) -> None:
    if event.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("ledger event schema_version must be 2")
    if event.get("event_type") not in {"observation_finalized", "revision_finalized"}:
        raise ValueError("invalid ledger event_type")
    if event.get("ledger_state") != "finalized":
        raise ValueError("ledger event must be finalized")
    for field in ("contract_digest", "event_digest"):
        if not _DIGEST.fullmatch(str(event.get(field) or "")):
            raise ValueError(f"invalid ledger event {field}")
    previous = event.get("previous_event_digest")
    if previous is not None and not _DIGEST.fullmatch(str(previous)):
        raise ValueError("invalid previous_event_digest")
    if event_digest(event) != event.get("event_digest"):
        raise ValueError("ledger event digest mismatch")
    is_revision = event.get("event_type") == "revision_finalized"
    if is_revision != bool(event.get("parent_generation_id")):
        raise ValueError("revision events require exactly one parent_generation_id")


def append_contract_event(
    state_dir: Path,
    contract_path: Path,
    *,
    parent_generation_id: Optional[str] = None,
) -> dict[str, Any]:
    root = ledger_root(state_dir)
    with FileLock(root / ".append.lock"):
        contract = load_contract(contract_path)
        head = _read_head(root)
        generation_id = str(contract["generation_id"])
        event = {
            "schema_version": SCHEMA_VERSION,
            "event_type": "revision_finalized" if parent_generation_id else "observation_finalized",
            "ledger_state": "finalized",
            "observation_state": contract["observation_state"],
            "observation_date": contract["observation_date"],
            "generation_id": generation_id,
            "parent_generation_id": parent_generation_id,
            "contract_path": contract_path.resolve().relative_to(
                state_dir.expanduser().resolve()
            ).as_posix(),
            "contract_digest": contract["contract_digest"],
            "previous_event_digest": (head or {}).get("event_digest"),
            "finalized_at": utc_now(),
        }
        event["event_digest"] = event_digest(event)
        _validate_event(event)
        event_path = root / "events" / str(contract["observation_date"]) / f"{generation_id}.json"
        if event_path.is_file():
            existing = json.loads(event_path.read_text(encoding="utf-8"))
            _validate_event(existing)
            if existing["contract_digest"] != contract_digest(contract):
                raise ValueError("existing ledger event points at different contract bytes")
            if existing.get("parent_generation_id") != parent_generation_id:
                raise ValueError("existing ledger event has a different revision parent")
            event = existing
            # Repair only the safe crash window where the event landed but its
            # head pointer did not. Never move a newer head backwards.
            if head and head.get("event_digest") not in {
                existing["event_digest"],
                existing["previous_event_digest"],
            }:
                return existing
        else:
            atomic_write_json(event_path, event, create_once=True)
        pointer = {
            "schema_version": SCHEMA_VERSION,
            "generation_id": generation_id,
            "observation_date": contract["observation_date"],
            "observation_state": contract["observation_state"],
            "event_path": event_path.relative_to(root).as_posix(),
            "event_digest": event["event_digest"],
            "updated_at": utc_now(),
        }
        atomic_write_json(root / "head.json", pointer)
        return event


def verify_event(state_dir: Path, event: Mapping[str, Any]) -> dict[str, Any]:
    _validate_event(event)
    root = ledger_root(state_dir)
    event_path = root / "events" / str(event["observation_date"]) / f"{event['generation_id']}.json"
    stored = json.loads(event_path.read_text(encoding="utf-8"))
    _validate_event(stored)
    if stored != event:
        raise ValueError("ledger event does not match stored event")
    contract_path = state_dir.expanduser().resolve() / str(event["contract_path"])
    contract = load_contract(contract_path)
    if contract["contract_digest"] != event["contract_digest"]:
        raise ValueError("ledger event contract binding mismatch")
    if contract.get("prior_ledger_head") != event.get("previous_event_digest"):
        raise ValueError("ledger event prior-head binding mismatch")
    return stored


def verify_ledger(state_dir: Path) -> dict[str, Any]:
    state_dir = state_dir.expanduser().resolve()
    root = ledger_root(state_dir)
    findings: list[dict[str, Any]] = []
    events: dict[str, dict[str, Any]] = {}
    for path in sorted((root / "events").glob("*/*.json")):
        try:
            event = json.loads(path.read_text(encoding="utf-8"))
            verify_event(state_dir, event)
            events[str(event["event_digest"])] = event
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            findings.append(
                {"path": path.relative_to(root).as_posix(), "issue": "INVALID_EVENT", "detail": str(error)}
            )
    head = _read_head(root)
    reached: set[str] = set()
    cursor = str((head or {}).get("event_digest") or "") or None
    while cursor is not None:
        if cursor in reached:
            findings.append({"event_digest": cursor, "issue": "CHAIN_LOOP"})
            break
        reached.add(cursor)
        event = events.get(cursor)
        if event is None:
            findings.append({"event_digest": cursor, "issue": "MISSING_CHAIN_EVENT"})
            break
        cursor = event.get("previous_event_digest")
    for digest, event in events.items():
        if digest not in reached:
            findings.append(
                {
                    "event_digest": digest,
                    "generation_id": event.get("generation_id"),
                    "issue": "ORPHAN_EVENT",
                }
            )
        try:
            _verify_artifacts(state_dir, event)
        except (OSError, ValueError, KeyError) as error:
            findings.append(
                {
                    "event_digest": digest,
                    "generation_id": event.get("generation_id"),
                    "issue": "ARTIFACT_MISMATCH",
                    "detail": str(error),
                }
            )
    return {
        "ok": not findings,
        "checked_events": len(events),
        "chain_events": len(reached),
        "findings": findings,
        "head": head,
    }


def _verify_artifacts(state_dir: Path, event: Mapping[str, Any]) -> None:
    contract_path = state_dir / str(event["contract_path"])
    contract = load_contract(contract_path)
    data_root = state_dir.parent.resolve()
    source_root = (data_root / str(contract["source_path"])).resolve()
    try:
        source_root.relative_to(data_root)
    except ValueError as error:
        raise ValueError("contract source_path escapes data root") from error
    for artifact in contract["artifacts"]:
        path = source_root / str(artifact["path"])
        if not path.is_file():
            raise ValueError(f"missing artifact: {artifact['path']}")
        if path.stat().st_size != int(artifact["bytes"]):
            raise ValueError(f"artifact size changed: {artifact['path']}")
        if hash_file(path) != artifact["sha256"]:
            raise ValueError(f"artifact hash changed: {artifact['path']}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Verify append-only ledger-v2 and source artifacts.")
    parser.add_argument("verify", choices=("verify",))
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args(argv)
    report = verify_ledger(args.state)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
