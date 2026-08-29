"""Fail-closed contracts for the Windows laptop-backup task transition."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

import laptop_backup_scheduled as scheduled
import laptop_pull_backup as receiver


HOBART = ZoneInfo("Australia/Hobart")
SHA40 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
ATOMIC_TEMP = re.compile(r"^\..+\.[0-9a-f]{32}\.tmp$")
FREE_FLOOR = 50 * 1024**3
COMPONENT_POINTERS = (
    "latest-verified.json",
    "latest-control.json",
    "latest-macro.json",
)
ALL_POINTERS = (*COMPONENT_POINTERS, "latest-scheduled.json")
EXPECTED_KINDS = ("observation", "control", "macro")
AUTH_BEGIN = "<!-- ARL_A3_TRANSITION_AUTHORIZATION_BEGIN -->"
AUTH_END = "<!-- ARL_A3_TRANSITION_AUTHORIZATION_END -->"


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def parse_transition_authorization(payload: bytes) -> Mapping[str, object]:
    text = payload.decode("utf-8")
    if text.count(AUTH_BEGIN) != 1 or text.count(AUTH_END) != 1:
        raise ValueError("handoff lacks one canonical transition authorization")
    raw = text.split(AUTH_BEGIN, 1)[1].split(AUTH_END, 1)[0].strip()
    value = json.loads(raw)
    if not isinstance(value, Mapping):
        raise ValueError("transition authorization is not an object")
    return value


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = path.stat(follow_symlinks=False).st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & 0x400)


def lexical_absolute(path: Path) -> Path:
    """Return an absolute path without dereferencing links or junctions."""
    return Path(os.path.abspath(os.fspath(path)))


def reject_linked_components(path: Path, label: str) -> Path:
    """Reject any existing reparse-point component before canonicalization."""
    lexical = lexical_absolute(path)
    anchor = Path(lexical.anchor)
    current = anchor
    for part in lexical.parts[1:]:
        current /= part
        if current.exists() and is_link_or_reparse(current):
            raise ValueError(f"{label} traverses a link or reparse point")
    return lexical


def partial_paths(target: Path) -> list[str]:
    found: list[str] = []
    for root, directories, files in os.walk(target, followlinks=False):
        root_path = Path(root)
        for name in tuple(directories):
            path = root_path / name
            if is_link_or_reparse(path):
                raise ValueError(f"backup target contains a linked directory: {path}")
        for name in files:
            path = root_path / name
            if is_link_or_reparse(path):
                raise ValueError(f"backup target contains a linked file: {path}")
            if name.endswith(".partial"):
                found.append(str(path))
    return found


def temporary_paths(target: Path) -> tuple[list[str], list[str]]:
    """Return exact receiver atomic-write residue and unknown ``*.tmp`` files."""
    known: list[str] = []
    unknown: list[str] = []
    for root, directories, files in os.walk(target, followlinks=False):
        root_path = Path(root)
        for name in tuple(directories):
            path = root_path / name
            if is_link_or_reparse(path):
                raise ValueError(f"backup target contains a linked directory: {path}")
        for name in files:
            if not name.endswith(".tmp"):
                continue
            path = root_path / name
            if is_link_or_reparse(path):
                raise ValueError(f"backup target contains a linked file: {path}")
            (known if ATOMIC_TEMP.fullmatch(name) else unknown).append(str(path))
    return sorted(known), sorted(unknown)


def validate_hygiene(
    target: Path,
    helpers: Sequence[Mapping[str, object]],
    *,
    allowed_receiver_guard_sha256: str | None = None,
) -> dict[str, object]:
    lock = target / "catalog/.receiver.lock"
    if lock.exists() and (
        allowed_receiver_guard_sha256 is None
        or sha256_file(lock) != allowed_receiver_guard_sha256
    ):
        raise ValueError("receiver lock remains")
    partials = partial_paths(target)
    if partials:
        raise ValueError("partial backup artifacts remain")
    temporaries, unknown_temporaries = temporary_paths(target)
    if temporaries or unknown_temporaries:
        raise ValueError("temporary backup artifacts remain")
    if helpers:
        raise ValueError("backup helpers remain")
    free = shutil.disk_usage(target).free
    if free < FREE_FLOOR:
        raise ValueError("post-transition free space is below 50 GiB")
    return {
        "free_bytes": free,
        "partials": partials,
        "temporaries": temporaries,
        "receiver_guard_sha256": sha256_file(lock) if lock.exists() else None,
        "helpers": list(helpers),
    }


def require_sha(value: str, length: int, label: str) -> str:
    matcher = SHA40 if length == 40 else SHA256
    if not matcher.fullmatch(value):
        raise ValueError(f"{label} must be a full lowercase SHA-{length * 4}")
    return value


def safe_file(root: Path, relative: str) -> Path:
    if not root.is_absolute() or root.is_symlink():
        raise ValueError("trusted root is unsafe")
    return scheduled.local_path(root.resolve(strict=True), relative)


def require_descendant(path: Path, root: Path, label: str, *, exists: bool = True) -> Path:
    if not path.is_absolute() or is_link_or_reparse(path):
        raise ValueError(f"{label} is not an absolute regular path")
    resolved_root = root.resolve(strict=True)
    resolved = path.resolve(strict=exists)
    if not receiver.is_within(resolved, resolved_root):
        raise ValueError(f"{label} escapes its trusted root")
    component = resolved_root
    for part in resolved.relative_to(resolved_root).parts:
        component /= part
        if component.exists() and is_link_or_reparse(component):
            raise ValueError(f"{label} traverses a link")
    return resolved


def expected_timer_date(observation_date: str) -> str:
    return (date.fromisoformat(observation_date) + timedelta(days=1)).isoformat()


def validate_source_listing(
    listing: Mapping[str, object],
    *,
    protected_sha: str,
    expected_observation_date: str,
    now: datetime,
) -> None:
    if now.astimezone(HOBART).date() != date.fromisoformat(expected_observation_date):
        raise ValueError("authorised observation date is not today's Hobart date")
    scheduled.validate_source_listing(listing, protected_sha=protected_sha, now=now)
    latest = listing.get("latest_observation")
    if not isinstance(latest, Mapping) or latest.get("observation_date") != expected_observation_date:
        raise ValueError("Pi latest observation date is not the authorised date")
    preflight = listing.get("preflight")
    timer_next = preflight.get("daily_timer_next") if isinstance(preflight, Mapping) else None
    next_date = expected_timer_date(expected_observation_date)
    if (
        not isinstance(timer_next, str)
        or next_date not in timer_next
        or "01:00:00" not in timer_next
    ):
        raise ValueError("Pi timer is not scheduled for the exact next 01:00")


def validate_recovery_source_listing(
    listing: Mapping[str, object], *, protected_sha: str, now: datetime
) -> None:
    scheduled.validate_source_listing(listing, protected_sha=protected_sha, now=now)
    latest = listing.get("latest_observation")
    preflight = listing.get("preflight")
    latest_date = latest.get("observation_date") if isinstance(latest, Mapping) else None
    timer_next = preflight.get("daily_timer_next") if isinstance(preflight, Mapping) else None
    if not isinstance(latest_date, str):
        raise ValueError("Pi recovery source lacks a latest observation date")
    next_date = expected_timer_date(latest_date)
    if not isinstance(timer_next, str) or next_date not in timer_next or "01:00:00" not in timer_next:
        raise ValueError("Pi recovery timer is not scheduled for the exact next 01:00")


@dataclass(frozen=True)
class TaskExpectation:
    executable: str
    arguments: str
    working_directory: str
    principal: str
    receiver_sha: str
    enabled: bool


def validate_task_snapshot(
    snapshot: Mapping[str, object], expectation: TaskExpectation, *, last_result_zero: bool
) -> None:
    actions = snapshot.get("actions")
    triggers = snapshot.get("triggers")
    settings = snapshot.get("settings")
    principal = snapshot.get("principal")
    if snapshot.get("state") != ("Ready" if expectation.enabled else "Disabled"):
        raise ValueError("scheduled task state is not exact")
    if snapshot.get("enabled") is not expectation.enabled:
        raise ValueError("scheduled task enabled state is not exact")
    if last_result_zero and snapshot.get("last_task_result") != 0:
        raise ValueError("scheduled task last result is nonzero")
    if not isinstance(actions, list) or actions != [{
        "execute": expectation.executable,
        "arguments": expectation.arguments,
        "working_directory": expectation.working_directory,
    }]:
        raise ValueError("scheduled task action is not exact")
    if not isinstance(principal, Mapping) or principal != {
        "user_id": expectation.principal,
        "logon_type": "S4U",
        "run_level": "Limited",
    }:
        raise ValueError("scheduled task principal is not exact")
    if not isinstance(settings, Mapping) or settings != {
        "enabled": expectation.enabled,
        "multiple_instances": "IgnoreNew",
        "restart_count": 3,
        "restart_interval": "PT30M",
        "execution_time_limit": "PT6H",
        "start_when_available": True,
    }:
        raise ValueError("scheduled task settings are not exact")
    if not isinstance(triggers, list) or len(triggers) != 2 or not all(
        isinstance(item, Mapping) for item in triggers
    ) or sorted(
        (str(item.get("kind")), str(item.get("at")), str(item.get("delay")))
        for item in triggers
    ) != [
        ("boot", "", "PT5M"),
        ("daily", "05:00:00", ""),
    ]:
        raise ValueError("scheduled task triggers are not exact")
    if snapshot.get("receiver_sha") != expectation.receiver_sha:
        raise ValueError("scheduled task receiver SHA is not exact")
    xml_b64 = snapshot.get("xml_base64")
    if not isinstance(xml_b64, str):
        raise ValueError("scheduled task XML is missing")
    try:
        base64.b64decode(xml_b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("scheduled task XML is malformed") from exc


def decode_task_xml(snapshot: Mapping[str, object]) -> bytes:
    value = snapshot.get("xml_base64")
    if not isinstance(value, str):
        raise ValueError("scheduled task XML is missing")
    return base64.b64decode(value, validate=True)


def task_xml_text(payload: bytes) -> str:
    """Decode exported Task Scheduler XML without weakening byte-level evidence."""
    if payload.startswith(b"\xff\xfe") or payload.startswith(b"\xfe\xff"):
        return payload.decode("utf-16")
    if payload.startswith(b"\xef\xbb\xbf"):
        return payload.decode("utf-8-sig")
    return payload.decode("utf-8")


def canonical_task_xml_sha256(payload: bytes) -> str:
    return sha256_bytes(task_xml_text(payload).encode("utf-8"))


def validate_accepted_task_snapshot(
    snapshot: Mapping[str, object],
    expectation: TaskExpectation,
    *,
    accepted_xml: bytes,
    accepted_sha256: str,
) -> None:
    validate_task_snapshot(snapshot, expectation, last_result_zero=True)
    live_xml = decode_task_xml(snapshot)
    if sha256_bytes(live_xml) != accepted_sha256:
        raise ValueError("live scheduled task XML bytes differ from the accepted artifact")
    if canonical_task_xml_sha256(live_xml) != canonical_task_xml_sha256(accepted_xml):
        raise ValueError("live scheduled task XML differs from the accepted artifact")


def parse_json_documents(text: str) -> list[Mapping[str, object]]:
    decoder = json.JSONDecoder()
    index = 0
    values: list[Mapping[str, object]] = []
    while True:
        while index < len(text) and text[index].isspace():
            index += 1
        if index == len(text):
            break
        try:
            value, index = decoder.raw_decode(text, index)
        except json.JSONDecodeError as exc:
            raise ValueError("command output contains non-JSON or truncated data") from exc
        if not isinstance(value, Mapping):
            raise ValueError("command output JSON document is not an object")
        values.append(value)
    if not values:
        raise ValueError("command output contains no JSON document")
    return values


def execution_document(text: str) -> Mapping[str, object]:
    matches = [
        value for value in parse_json_documents(text)
        if "execution_record" in value and "action" in value and "result" in value
    ]
    if len(matches) != 1:
        raise ValueError("command output does not contain exactly one execution result")
    return matches[0]


def bind_execution_output(
    text: str,
    *,
    target: Path,
    expected_action: str,
    record_path: Path,
) -> Mapping[str, object]:
    value = execution_document(text)
    if value.get("action") != expected_action or value.get("result") != "PASS" or value.get("ok") is not True:
        raise ValueError("command execution result is not the required PASS action")
    raw = value.get("execution_record")
    if not isinstance(raw, str):
        raise ValueError("command execution record path is missing")
    output_path = require_descendant(Path(raw), target, "command execution record")
    if output_path != record_path.resolve(strict=True):
        raise ValueError("command output is not bound to latest-scheduled")
    return value


def scheduled_record_path(target: Path) -> Path:
    pointer_path = safe_file(target, "catalog/latest-scheduled.json")
    return scheduled_record_path_from_pointer_bytes(target, pointer_path.read_bytes())


def scheduled_record_path_from_pointer_bytes(target: Path, payload: bytes) -> Path:
    pointer = json.loads(payload.decode("utf-8"))
    relative = pointer.get("record_path") if isinstance(pointer, Mapping) else None
    digest = pointer.get("record_sha256") if isinstance(pointer, Mapping) else None
    if not isinstance(relative, str) or not relative.startswith("catalog/scheduled-runs/"):
        raise ValueError("scheduled execution pointer path is invalid")
    record = safe_file(target, relative)
    if not isinstance(digest, str) or sha256_file(record) != digest:
        raise ValueError("scheduled execution pointer hash is invalid")
    return record


def scheduled_pointer_identity(target: Path, payload: bytes) -> dict[str, object]:
    pointer = json.loads(payload.decode("utf-8"))
    record = scheduled_record_path_from_pointer_bytes(target, payload)
    value = json.loads(record.read_text(encoding="utf-8"))
    pointer_result = pointer.get("result") if isinstance(pointer, Mapping) else None
    if (
        not isinstance(value, Mapping)
        or pointer_result not in {"PASS", "FAIL", "BLOCKED"}
        or value.get("result") != pointer_result
    ):
        raise ValueError("scheduled execution pointer result is invalid")
    return {
        "record_path": record.relative_to(target.resolve(strict=True)).as_posix(),
        "record_sha256": sha256_file(record),
        "result": pointer_result,
    }


def scheduled_inventory(target: Path) -> dict[str, str]:
    root = require_descendant(
        target / "catalog/scheduled-runs", target, "scheduled record directory"
    )
    result: dict[str, str] = {}
    for path in sorted(root.glob("*.json")):
        regular = require_descendant(path, target, "scheduled execution record")
        result[regular.relative_to(target.resolve(strict=True)).as_posix()] = sha256_file(regular)
    return result


def validate_scheduled_inventory(
    target: Path,
    baseline: Mapping[str, str],
    *,
    expected_new: Sequence[Path] | None,
) -> dict[str, str]:
    current = scheduled_inventory(target)
    for relative, digest in baseline.items():
        if current.get(relative) != digest:
            raise ValueError("scheduled execution baseline was deleted or modified")
    appended = {key: value for key, value in current.items() if key not in baseline}
    if expected_new is not None:
        expected = {
            require_descendant(path, target, "expected scheduled record")
            .relative_to(target.resolve(strict=True))
            .as_posix()
            for path in expected_new
        }
        if set(appended) != expected or len(expected) != len(expected_new):
            raise ValueError("scheduled execution append set is not exact")
    return appended


def validate_preserved_scheduled_records(
    target: Path,
    records: Mapping[str, str],
    *,
    candidate_shas: Sequence[str],
    protected_sha: str,
    plan_commit: str,
    plan_sha256: str,
    operator: str,
) -> None:
    allowed_candidates = set(candidate_shas)
    for relative, digest in records.items():
        path = safe_file(target, relative)
        if sha256_file(path) != digest:
            raise ValueError("preserved scheduled record hash changed")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, Mapping):
            raise ValueError("preserved scheduled record is not an object")
        validate_scheduled_record_structure(value)
        expected = {
            "plan_document_id": receiver.PLAN_DOCUMENT_ID,
            "plan_version": receiver.PLAN_VERSION,
            "plan_git_commit": plan_commit,
            "plan_sha256": plan_sha256,
            "protected_code_sha": protected_sha,
            "operator": operator,
            "deviations": [],
            "deviation_authorization": None,
        }
        if any(value.get(key) != expected_value for key, expected_value in expected.items()):
            raise ValueError("preserved scheduled record identity is invalid")
        if value.get("candidate_code_sha") not in allowed_candidates:
            raise ValueError("preserved scheduled record candidate is invalid")
        if value.get("result") not in {"PASS", "FAIL", "BLOCKED"}:
            raise ValueError("preserved scheduled record result is invalid")


def validate_scheduled_record_structure(value: Mapping[str, object]) -> None:
    """Validate the immutable execution-record envelope, including legacy records."""
    if value.get("schema_version") != 1:
        raise ValueError("preserved scheduled record schema is invalid")
    if value.get("plan_raw_sha256") not in receiver.PLAN_VALID_RAW_SHA256S:
        raise ValueError("preserved scheduled record plan_raw_sha256 is invalid")
    if value.get("plan_normalized_raw_sha256") != receiver.PLAN_NORMALIZED_RAW_SHA256:
        raise ValueError("preserved scheduled record plan_normalized_raw_sha256 is invalid")
    timestamps = value.get("timestamps")
    completed_at = timestamps.get("completed_at") if isinstance(timestamps, Mapping) else None
    if not isinstance(completed_at, str):
        raise ValueError("preserved scheduled record timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("preserved scheduled record timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("preserved scheduled record timestamp is not timezone-aware")
    commands = value.get("exact_commands")
    if not isinstance(commands, list) or not commands or any(
        not isinstance(command, str) or not command.strip() for command in commands
    ):
        raise ValueError("preserved scheduled record commands are invalid")
    valid_outcomes = {
        "PREFLIGHT_FAILED": {"BLOCKED"},
        "NO_BACKUP_DATA_WRITE": {"PASS"},
        "BACKUP_REQUIRED": {"BLOCKED"},
        "BACKUP-LATEST": {"PASS", "FAIL"},
        "BACKFILL": {"PASS", "FAIL"},
        "POST_BACKUP_VERIFY": {"FAIL"},
    }
    action = value.get("action")
    if not isinstance(action, str) or action not in valid_outcomes:
        raise ValueError("preserved scheduled record action is invalid")
    if value.get("result") not in valid_outcomes[action]:
        raise ValueError("preserved scheduled record action/result is invalid")
    if not isinstance(value.get("detail"), Mapping):
        raise ValueError("preserved scheduled record detail is invalid")
    previous = value.get("previous_execution")
    if previous is not None and (
        not isinstance(previous, Mapping)
        or set(previous) != {"record_path", "record_sha256"}
        or not isinstance(previous.get("record_path"), str)
        or not str(previous["record_path"]).startswith("catalog/scheduled-runs/")
        or not isinstance(previous.get("record_sha256"), str)
        or not SHA256.fullmatch(str(previous["record_sha256"]))
    ):
        raise ValueError("preserved scheduled record lineage is invalid")


def reconcile_scheduled_pointer(
    target: Path,
    baseline_pointer: bytes,
    live_pointer: bytes,
    records: Mapping[str, str],
    *,
    old_candidate_sha: str,
    apply: bool = True,
) -> dict[str, object]:
    if apply:
        with scheduled.scheduled_record_mutex(target):
            current = (target / "catalog/latest-scheduled.json").read_bytes()
            if current != live_pointer:
                raise ValueError("scheduled execution pointer changed before reconciliation")
            result = reconcile_scheduled_pointer(
                target, baseline_pointer, current, records,
                old_candidate_sha=old_candidate_sha, apply=False,
            )
            receiver.atomic_replace(
                target / "catalog/latest-scheduled.json",
                canonical_json({
                    "record_path": result["latest_record"],
                    "record_sha256": result["latest_record_sha256"],
                    "result": result["result"],
                }),
            )
            return result
    baseline_identity = scheduled_pointer_identity(target, baseline_pointer)
    live_identity = scheduled_pointer_identity(target, live_pointer)
    current_relative = str(baseline_identity["record_path"])
    current_sha256 = str(baseline_identity["record_sha256"])
    remaining = dict(records)
    ordered: list[str] = []
    legacy_unordered: list[str] = []
    final_result = baseline_identity["result"]

    def advance_linked_suffix() -> None:
        nonlocal current_relative, current_sha256, final_result
        while True:
            matches: list[tuple[str, Mapping[str, object]]] = []
            for relative, digest in remaining.items():
                path = safe_file(target, relative)
                if sha256_file(path) != digest:
                    raise ValueError("scheduled reconciliation record hash changed")
                value = json.loads(path.read_text(encoding="utf-8"))
                previous = value.get("previous_execution") if isinstance(value, Mapping) else None
                if isinstance(previous, Mapping) and previous == {
                    "record_path": current_relative,
                    "record_sha256": current_sha256,
                }:
                    matches.append((relative, value))
            if len(matches) > 1:
                raise ValueError("scheduled execution append chain is ambiguous or incomplete")
            if not matches:
                return
            current_relative, value = matches[0]
            current_sha256 = remaining.pop(current_relative)
            final_result = value.get("result")
            ordered.append(current_relative)

    advance_linked_suffix()
    legacy = []
    for relative in tuple(remaining):
        value = json.loads(safe_file(target, relative).read_text(encoding="utf-8"))
        if isinstance(value, Mapping) and value.get("previous_execution") is None:
            legacy.append((relative, value))
    if legacy:
        if any(value.get("candidate_code_sha") != old_candidate_sha for _, value in legacy):
            raise ValueError("unlinked scheduled record is not from the legacy candidate")
        live_relative = str(live_identity["record_path"])
        legacy_relatives = {relative for relative, _ in legacy}
        anchors: list[str] = []
        for anchor, _ in legacy:
            cursor, cursor_sha = anchor, remaining[anchor]
            reached, visited = cursor == live_relative, {cursor}
            while not reached:
                matches: list[tuple[str, str]] = []
                for relative, digest in remaining.items():
                    if relative in legacy_relatives or relative in visited:
                        continue
                    value = json.loads(safe_file(target, relative).read_text(encoding="utf-8"))
                    if isinstance(value, Mapping) and value.get("previous_execution") == {
                        "record_path": cursor,
                        "record_sha256": cursor_sha,
                    }:
                        matches.append((relative, digest))
                if len(matches) > 1:
                    raise ValueError("scheduled execution append chain is ambiguous or incomplete")
                if not matches:
                    break
                cursor, cursor_sha = matches[0]
                visited.add(cursor)
                reached = cursor == live_relative
            if reached:
                anchors.append(anchor)
        if len(anchors) != 1:
            raise ValueError("legacy scheduled records are not bound to the live pointer")
        anchor = anchors[0]
        legacy_unordered = sorted(relative for relative, _ in legacy if relative != anchor)
        for relative, _ in legacy:
            remaining.pop(relative)
        anchor_value = next(value for relative, value in legacy if relative == anchor)
        current_relative = anchor
        current_sha256 = records[anchor]
        final_result = anchor_value.get("result")
        ordered.append(anchor)
        advance_linked_suffix()

    if remaining:
        raise ValueError("scheduled execution append chain is ambiguous or incomplete")
    allowed_live = {
        str(baseline_identity["record_path"]),
        *records.keys(),
    }
    if str(live_identity["record_path"]) not in allowed_live:
        raise ValueError("live scheduled pointer is outside the authenticated append chain")
    if not isinstance(final_result, str):
        raise ValueError("scheduled reconciliation result is invalid")
    return {
        "baseline_record": baseline_identity["record_path"],
        "live_entry_record": live_identity["record_path"],
        "ordered_appended_records": ordered,
        "legacy_unordered_preserved": legacy_unordered,
        "latest_record": current_relative,
        "latest_record_sha256": current_sha256,
        "result": final_result,
    }


def validate_component_status(detail: Mapping[str, object], expected_date: str) -> None:
    observation = detail.get("observation")
    inventory = detail.get("inventory")
    if not isinstance(observation, Mapping) or observation.get("status") != "UP_TO_DATE":
        raise ValueError("scheduled observation status is invalid")
    if observation.get("observation_date") != expected_date:
        raise ValueError("scheduled observation date is invalid")
    for kind in ("control", "macro"):
        value = detail.get(kind)
        if not isinstance(value, Mapping) or value.get("status") != "UP_TO_DATE":
            raise ValueError(f"scheduled {kind} status is invalid")
    if not isinstance(inventory, Mapping) or inventory != {
        "status": "UP_TO_DATE",
        "missing_completed_dates": [],
        "stale_diagnostics": [],
    }:
        raise ValueError("scheduled inventory status is invalid")
    if detail.get("backfill_required") is not False or detail.get("status") != "UP_TO_DATE":
        raise ValueError("scheduled aggregate state is invalid")


def validate_execution_record(
    record: Mapping[str, object],
    *,
    action: str,
    candidate_sha: str,
    protected_sha: str,
    plan_commit: str,
    plan_sha256: str,
    operator: str,
    expected_date: str,
) -> None:
    expected = {
        "plan_document_id": receiver.PLAN_DOCUMENT_ID,
        "plan_version": receiver.PLAN_VERSION,
        "plan_git_commit": plan_commit,
        "plan_sha256": plan_sha256,
        "candidate_code_sha": candidate_sha,
        "protected_code_sha": protected_sha,
        "operator": operator,
        "action": action,
        "result": "PASS",
        "deviations": [],
        "deviation_authorization": None,
    }
    for key, value in expected.items():
        if record.get(key) != value:
            raise ValueError(f"scheduled execution {key} is invalid")
    detail = record.get("detail")
    if action == "BACKUP-LATEST":
        if not isinstance(detail, Mapping) or not isinstance(detail.get("before"), Mapping):
            raise ValueError("foreground execution lacks before/after state")
        before = detail["before"]
        after = detail.get("after")
        if before.get("status") != "STALE" or before.get("backup_command") != "backup-latest":
            raise ValueError("foreground before state is invalid")
        if before.get("backfill_required") is not False:
            raise ValueError("foreground unexpectedly requires backfill")
        if not isinstance(after, Mapping):
            raise ValueError("foreground after state is invalid")
        validate_component_status(after, expected_date)
    elif action == "NO_BACKUP_DATA_WRITE":
        if not isinstance(detail, Mapping):
            raise ValueError("no-write execution detail is invalid")
        validate_component_status(detail, expected_date)
    else:
        raise ValueError("transition execution action is invalid")


def validate_receipts(
    target: Path,
    *,
    candidate_sha: str,
    protected_sha: str,
    plan_commit: str,
    expected_date: str,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for kind, pointer in (
        ("observation", "latest-verified.json"),
        ("control", "latest-control.json"),
        ("macro", "latest-macro.json"),
    ):
        receipt, _manifest, _entry, path = scheduled.pointer_generation(
            target,
            pointer,
            kind,
            candidate_sha=candidate_sha,
            protected_sha=protected_sha,
            plan_commit=plan_commit,
        )
        if kind == "observation" and receipt.get("observation_date") != expected_date:
            raise ValueError("observation receipt date is invalid")
        if not scheduled.has_component_restore_evidence(receipt.get("checks"), kind):
            raise ValueError(f"{kind} receipt restore evidence is invalid")
        result[kind] = str(path)
    return result


def receipt_evidence(paths: Mapping[str, str]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for kind in EXPECTED_KINDS:
        raw = paths.get(kind)
        if not isinstance(raw, str):
            raise ValueError(f"{kind} receipt path is missing")
        path = Path(raw)
        result[kind] = {"path": str(path), "sha256": sha256_file(path)}
    return result


def validate_catalog_delta(
    baseline_bytes: bytes,
    current_path: Path,
    *,
    receipt_paths: Mapping[str, str],
) -> Sequence[Mapping[str, object]]:
    current_bytes = current_path.read_bytes()
    if not current_bytes.startswith(baseline_bytes):
        raise ValueError("backup catalog does not preserve the exact prefix")
    entries = receiver.catalog_entries(current_path)
    baseline_count = len(baseline_bytes.splitlines())
    appended = entries[baseline_count:]
    if [item.get("kind") for item in appended] != list(EXPECTED_KINDS):
        raise ValueError("backup catalog appended unexpected generation kinds")
    expected_paths = [receipt_paths[kind] for kind in EXPECTED_KINDS]
    actual_paths = [str((current_path.parent.parent / str(item.get("receipt_path"))).resolve()) for item in appended]
    if actual_paths != expected_paths or any(item.get("result") != "PASS" for item in appended):
        raise ValueError("backup catalog appended unexpected receipts")
    return appended


def validate_preserved_catalog_entries(
    target: Path,
    entries: Sequence[Mapping[str, object]],
    *,
    candidate_sha: str,
    protected_sha: str,
    plan_commit: str,
) -> None:
    for entry in entries:
        kind = entry.get("kind")
        receipt_path = entry.get("receipt_path")
        if kind not in {"observation", "diagnostic", "control", "macro"} or not isinstance(receipt_path, str):
            raise ValueError("preserved catalog entry identity is invalid")
        receipt, _manifest, _path = scheduled.verified_receipt(
            target,
            receipt_path,
            entry,
            str(kind),
            candidate_sha=candidate_sha,
            protected_sha=protected_sha,
            plan_commit=plan_commit,
        )
        if not scheduled.has_component_restore_evidence(receipt.get("checks"), str(kind)):
            raise ValueError("preserved catalog receipt restore evidence is invalid")


def validate_deadline(now: datetime, deadline: datetime, required_remaining: timedelta) -> None:
    if now.tzinfo is None or deadline.tzinfo is None:
        raise ValueError("transition deadline must be timezone-aware")
    local_now = now.astimezone(HOBART)
    local_deadline = deadline.astimezone(HOBART)
    if local_now.date() != local_deadline.date():
        raise ValueError("transition deadline is not today's Hobart date")
    if local_now.time() < time(3, 30):
        raise ValueError("transition is prohibited during the D-006 quiet window")
    if local_now.time() >= time(22, 0) or local_deadline.time() != time(22, 0):
        raise ValueError("transition is outside the controlled daylight deadline")
    if deadline - now < required_remaining:
        raise ValueError("insufficient time remains before the hard transition deadline")


def validate_recovery_window(
    now: datetime, required_remaining: timedelta = timedelta(minutes=30)
) -> None:
    if now.tzinfo is None:
        raise ValueError("recovery time must be timezone-aware")
    local = now.astimezone(HOBART)
    if local.time() < time(3, 30) or local.time() >= time(22, 0):
        raise ValueError("recovery is outside the controlled post-ingest daylight window")
    boundary = datetime.combine(local.date(), time(22, 0), tzinfo=HOBART)
    if boundary - local < required_remaining:
        raise ValueError("insufficient time remains for controlled recovery")


def terminal_payload(
    *,
    transition_id: str,
    result: str,
    config: Mapping[str, object],
    evidence: Mapping[str, object],
    error: str | None,
    started_at: str,
    completed_at: str,
) -> bytes:
    if result not in {"PASS", "FAIL", "BLOCKED", "ROLLED_BACK"}:
        raise ValueError("terminal result is invalid")
    return canonical_json({
        "schema_version": 1,
        "plan_document_id": receiver.PLAN_DOCUMENT_ID,
        "plan_version": receiver.PLAN_VERSION,
        "plan_git_commit": config.get("plan_git_commit"),
        "plan_sha256": config.get("plan_sha256"),
        "candidate_code_sha": config.get("candidate_code_sha"),
        "protected_code_sha": config.get("protected_code_sha"),
        "operator": config.get("operator"),
        "transition_id": transition_id,
        "timestamps": {"started_at": started_at, "completed_at": completed_at},
        "exact_commands": list(evidence.get("exact_commands", []))
        if isinstance(evidence.get("exact_commands"), list)
        else [],
        "result": result,
        "config": dict(config),
        "evidence": dict(evidence),
        "error": error,
        "deviations": [],
        "deviation_authorization": None,
    })


def pid_alive(pid: int) -> bool:
    return receiver.process_alive(pid)
