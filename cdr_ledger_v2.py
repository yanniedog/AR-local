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
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_GENERATION = re.compile(r"^obs-\d{4}-\d{2}-\d{2}-[0-9a-f]{16}$")


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
    observation_date = str(event.get("observation_date") or "")
    generation_id = str(event.get("generation_id") or "")
    if not _DATE.fullmatch(observation_date):
        raise ValueError("invalid ledger event observation_date")
    if not _GENERATION.fullmatch(generation_id):
        raise ValueError("invalid ledger event generation_id")
    contract_path = Path(str(event.get("contract_path") or ""))
    if (
        not str(event.get("contract_path") or "")
        or contract_path.is_absolute()
        or ".." in contract_path.parts
    ):
        raise ValueError("invalid ledger event contract_path")
    for field in ("contract_digest", "event_digest"):
        if not _DIGEST.fullmatch(str(event.get(field) or "")):
            raise ValueError(f"invalid ledger event {field}")
    previous = event.get("previous_event_digest")
    if previous is not None and not _DIGEST.fullmatch(str(previous)):
        raise ValueError("invalid previous_event_digest")
    if event_digest(event) != event.get("event_digest"):
        raise ValueError("ledger event digest mismatch")
    is_revision = event.get("event_type") == "revision_finalized"
    parent_generation_id = event.get("parent_generation_id")
    parent_event_digest = event.get("parent_event_digest")
    if is_revision != bool(parent_generation_id) or is_revision != bool(
        parent_event_digest
    ):
        raise ValueError(
            "revision events require parent_generation_id and parent_event_digest"
        )
    if parent_generation_id is not None and not _GENERATION.fullmatch(
        str(parent_generation_id)
    ):
        raise ValueError("invalid parent_generation_id")
    if parent_event_digest is not None and not _DIGEST.fullmatch(
        str(parent_event_digest)
    ):
        raise ValueError("invalid parent_event_digest")


def _generation_event_path(root: Path, observation_date: str, generation_id: str) -> Path:
    return root / "events" / observation_date / f"{generation_id}.json"


def _load_generation_event(
    root: Path, observation_date: str, generation_id: str
) -> dict[str, Any]:
    if not _GENERATION.fullmatch(generation_id):
        raise ValueError("invalid parent_generation_id")
    path = _generation_event_path(root, observation_date, generation_id)
    if not path.is_file():
        raise ValueError("revision parent generation does not exist on this date")
    payload = json.loads(path.read_text(encoding="utf-8"))
    _validate_event(payload)
    if payload.get("generation_id") != generation_id:
        raise ValueError("revision parent event path does not match its generation")
    if payload.get("observation_date") != observation_date:
        raise ValueError("revision parent belongs to a different observation date")
    return payload


def _validate_parent_binding(state_dir: Path, event: Mapping[str, Any]) -> None:
    if event.get("event_type") != "revision_finalized":
        return
    generation_id = str(event["generation_id"])
    parent_generation_id = str(event["parent_generation_id"])
    if parent_generation_id == generation_id:
        raise ValueError("revision event cannot parent itself")
    parent = _load_generation_event(
        ledger_root(state_dir), str(event["observation_date"]), parent_generation_id
    )
    if parent.get("event_digest") != event.get("parent_event_digest"):
        raise ValueError("revision parent event digest mismatch")


def append_contract_event(
    state_dir: Path,
    contract_path: Path,
    *,
    parent_generation_id: Optional[str] = None,
) -> dict[str, Any]:
    root = ledger_root(state_dir)
    with FileLock(root / ".append.lock"):
        return append_contract_event_locked(
            state_dir,
            contract_path,
            parent_generation_id=parent_generation_id,
        )


def append_contract_event_locked(
    state_dir: Path,
    contract_path: Path,
    *,
    parent_generation_id: Optional[str] = None,
) -> dict[str, Any]:
    """Append while the caller holds ``ledger-v2/.append.lock``."""

    root = ledger_root(state_dir)
    contract = load_contract(contract_path)
    head = _read_head(root)
    generation_id = str(contract["generation_id"])
    observation_date = str(contract["observation_date"])
    parent_event_digest: Optional[str] = None
    if parent_generation_id is not None:
        parent = _load_generation_event(root, observation_date, parent_generation_id)
        if parent_generation_id == generation_id:
            raise ValueError("revision event cannot parent itself")
        verify_event_artifacts(state_dir, parent)
        parent_event_digest = str(parent["event_digest"])
    event_path = root / "events" / str(contract["observation_date"]) / f"{generation_id}.json"
    if event_path.is_file():
        existing = json.loads(event_path.read_text(encoding="utf-8"))
        _validate_event(existing)
        if existing["contract_digest"] != contract_digest(contract):
            raise ValueError("existing ledger event points at different contract bytes")
        if existing.get("parent_generation_id") != parent_generation_id:
            raise ValueError("existing ledger event has a different revision parent")
        if existing.get("parent_event_digest") != parent_event_digest:
            raise ValueError("existing ledger event has a different revision parent digest")
        _validate_parent_binding(state_dir, existing)
        # Repair only the safe crash window where the event landed but its head
        # pointer did not. Never move a newer head backwards.
        if head and head.get("event_digest") not in {
            existing["event_digest"],
            existing["previous_event_digest"],
        }:
            return existing
        event = existing
    else:
        current_head = (head or {}).get("event_digest")
        if contract.get("prior_ledger_head") != current_head:
            raise ValueError("export contract prior head no longer matches ledger head")
        event = {
            "schema_version": SCHEMA_VERSION,
            "event_type": "revision_finalized" if parent_generation_id else "observation_finalized",
            "ledger_state": "finalized",
            "observation_state": contract["observation_state"],
            "observation_date": contract["observation_date"],
            "generation_id": generation_id,
            "parent_generation_id": parent_generation_id,
            "parent_event_digest": parent_event_digest,
            "contract_path": contract_path.resolve().relative_to(
                state_dir.expanduser().resolve()
            ).as_posix(),
            "contract_digest": contract["contract_digest"],
            "previous_event_digest": current_head,
            "finalized_at": utc_now(),
        }
        event["event_digest"] = event_digest(event)
        _validate_event(event)
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


def find_contract_event_locked(
    state_dir: Path,
    observation_date: str,
    source_generation_digest: str,
    parent_generation_id: Optional[str],
) -> Optional[tuple[Path, dict[str, Any], dict[str, Any]]]:
    """Find one already-finalized semantic generation under the append lock."""

    root = ledger_root(state_dir)
    matches: list[tuple[Path, dict[str, Any], dict[str, Any]]] = []
    for event_path in sorted((root / "events" / observation_date).glob("*.json")):
        event = json.loads(event_path.read_text(encoding="utf-8"))
        verify_event_artifacts(state_dir, event)
        contract_path = state_dir.expanduser().resolve() / str(event["contract_path"])
        contract = load_contract(contract_path)
        if (
            contract.get("source_generation_digest") == source_generation_digest
            and event.get("parent_generation_id") == parent_generation_id
        ):
            matches.append((contract_path, contract, event))
    if len(matches) > 1:
        raise ValueError("multiple finalized events share one source generation and parent")
    return matches[0] if matches else None


def verify_event(state_dir: Path, event: Mapping[str, Any]) -> dict[str, Any]:
    _validate_event(event)
    root = ledger_root(state_dir)
    event_path = root / "events" / str(event["observation_date"]) / f"{event['generation_id']}.json"
    stored = json.loads(event_path.read_text(encoding="utf-8"))
    _validate_event(stored)
    if stored != event:
        raise ValueError("ledger event does not match stored event")
    state_dir = state_dir.expanduser().resolve()
    contract_path = (state_dir / str(event["contract_path"])).resolve()
    try:
        contract_path.relative_to(state_dir)
    except ValueError as error:
        raise ValueError("ledger event contract_path escapes state root") from error
    contract = load_contract(contract_path)
    if contract["contract_digest"] != event["contract_digest"]:
        raise ValueError("ledger event contract binding mismatch")
    if contract.get("prior_ledger_head") != event.get("previous_event_digest"):
        raise ValueError("ledger event prior-head binding mismatch")
    for field in ("generation_id", "observation_date", "observation_state"):
        if contract.get(field) != event.get(field):
            raise ValueError(f"ledger event {field} does not match contract")
    _validate_parent_binding(state_dir, stored)
    return stored


def verify_event_artifacts(
    state_dir: Path, event: Mapping[str, Any]
) -> dict[str, Any]:
    """Re-hash every artifact bound to one verified ledger event."""

    verify_event(state_dir, event)
    _verify_artifacts(state_dir.expanduser().resolve(), event)
    return dict(event)


def verify_ledger(state_dir: Path) -> dict[str, Any]:
    state_dir = state_dir.expanduser().resolve()
    root = ledger_root(state_dir)
    findings: list[dict[str, Any]] = []
    events: dict[str, dict[str, Any]] = {}
    events_by_generation: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted((root / "events").glob("*/*.json")):
        try:
            event = json.loads(path.read_text(encoding="utf-8"))
            verify_event(state_dir, event)
            events[str(event["event_digest"])] = event
            events_by_generation[
                (str(event["observation_date"]), str(event["generation_id"]))
            ] = event
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            findings.append(
                {"path": path.relative_to(root).as_posix(), "issue": "INVALID_EVENT", "detail": str(error)}
            )
    try:
        head = _read_head(root)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        head = None
        findings.append(
            {"path": "head.json", "issue": "INVALID_HEAD", "detail": str(error)}
        )
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
        ancestry_seen: set[tuple[str, str]] = set()
        ancestry_event: Optional[dict[str, Any]] = event
        while ancestry_event is not None and ancestry_event.get(
            "parent_generation_id"
        ):
            ancestry_key = (
                str(ancestry_event["observation_date"]),
                str(ancestry_event["parent_generation_id"]),
            )
            if ancestry_key in ancestry_seen:
                findings.append(
                    {
                        "event_digest": digest,
                        "generation_id": event.get("generation_id"),
                        "issue": "PARENT_CHAIN_LOOP",
                    }
                )
                break
            ancestry_seen.add(ancestry_key)
            ancestry_event = events_by_generation.get(ancestry_key)
            if ancestry_event is None:
                break
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
    contract_path = (state_dir / str(event["contract_path"])).resolve()
    try:
        contract_path.relative_to(state_dir)
    except ValueError as error:
        raise ValueError("ledger event contract_path escapes state root") from error
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
