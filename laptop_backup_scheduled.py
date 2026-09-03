"""Run a scheduled laptop pull only when any protected component is stale."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import uuid
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

import laptop_pull_backup as receiver
import laptop_backup_scheduled_lineage as lineage


HOBART_TZ = ZoneInfo("Australia/Hobart")
TIMER_NEXT_RE = re.compile(
    r"^(?P<weekday>[A-Z][a-z]{2}) (?P<date>\d{4}-\d{2}-\d{2}) "
    r"01:00:00 (?P<zone>AEST|AEDT)$"
)


def validate_next_daily_timer(value: object, checked_at: datetime) -> None:
    match = TIMER_NEXT_RE.fullmatch(value) if isinstance(value, str) else None
    local_checked_at = checked_at.astimezone(HOBART_TZ)
    expected_date = local_checked_at.date()
    if local_checked_at.timetz().replace(tzinfo=None) >= time(1, 0):
        expected_date += timedelta(days=1)
    expected = datetime.combine(expected_date, time(1, 0), HOBART_TZ)
    if (
        match is None
        or date.fromisoformat(match["date"]) != expected_date
        or match["weekday"] != expected.strftime("%a")
        or match["zone"] != expected.tzname()
    ):
        raise ValueError("Pi timer is not scheduled for the exact next 01:00 in Australia/Hobart")


def local_path(target: Path, relative: str) -> Path:
    receiver.validate_relative_path(relative, {})
    parts = PurePosixPath(relative).parts
    candidate = target.joinpath(*parts)
    component = target
    for part in parts:
        component /= part
        if component.is_symlink():
            raise ValueError(f"backup metadata path is symlinked: {relative}")
    resolved = candidate.resolve(strict=True)
    if not receiver.is_within(resolved, target) or not resolved.is_file():
        raise ValueError(f"backup metadata path is unsafe: {relative}")
    return resolved


def manifest_file_hash(manifest: Mapping[str, object], relative: str) -> str | None:
    files = manifest.get("files")
    if not isinstance(files, list):
        return None
    matches = [item for item in files if isinstance(item, Mapping) and item.get("path") == relative]
    return str(matches[0].get("sha256")) if len(matches) == 1 else None


def content_revision(manifest: Mapping[str, object]) -> str:
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ValueError("component manifest lacks files")
    volatile_control_paths = {
        f"system/systemd/{unit}.show.txt"
        for unit in (
            "ar-local-daily.service",
            "ar-local-daily.timer",
            "ar-local-dashboard.service",
            "ar-local-status.service",
        )
    }
    volatile_control_paths.update({
        "data/state/runtime_health.json",
        "git/AR-local.bundle",
        "git/australianrates.bundle",
        "system/control-metadata.json",
    })
    identity = [
        {"path": item["path"], "size": item["size"], "sha256": item["sha256"]}
        for item in files
        if isinstance(item, Mapping)
        and not (manifest.get("kind") == "control" and item.get("path") in volatile_control_paths)
    ]
    valid_files = [item for item in files if isinstance(item, Mapping)]
    if len(valid_files) != len(files):
        raise ValueError("component manifest contains an invalid file")
    material: object = identity
    if manifest.get("kind") == "control":
        control = manifest.get("control")
        if not isinstance(control, Mapping) or not isinstance(control.get("repositories"), list):
            raise ValueError("control manifest lacks semantic metadata")
        repositories = []
        for repository in control["repositories"]:
            if not isinstance(repository, Mapping):
                raise ValueError("control repository metadata is invalid")
            repositories.append({key: value for key, value in repository.items() if key != "bundle_sha256"})
        normalized_control = dict(control)
        normalized_control["repositories"] = repositories
        material = {"files": identity, "control": normalized_control}
    return hashlib.sha256(receiver.canonical_json_bytes(material)).hexdigest()


def has_component_restore_evidence(checks: object, kind: str) -> bool:
    if not isinstance(checks, Mapping):
        return False
    if kind == "control":
        bundles = checks.get("git_bundles")
        return (
            isinstance(bundles, list)
            and all(isinstance(bundle, str) for bundle in bundles)
            and sorted(bundles) == ["AR-local.bundle", "australianrates.bundle"]
            and type(checks.get("secret_locations")) is int
            and checks["secret_locations"] >= 0
        )
    return isinstance(checks.get(kind), Mapping)


def verified_receipt(
    target: Path,
    receipt_relative: str,
    catalog_entry: Mapping[str, object],
    kind: str,
    *,
    candidate_sha: str | None,
    protected_sha: str,
    plan_commit: str,
) -> tuple[dict[str, object], dict[str, object], Path]:
    if plan_commit != receiver.PLAN_GIT_COMMIT:
        raise ValueError(f"{kind} plan commit is not current")
    receipt_path = local_path(target, receipt_relative)
    if receiver.sha256_file(receipt_path) != catalog_entry.get("receipt_sha256"):
        raise ValueError(f"{kind} receipt digest mismatch")
    receipt = json.loads(receipt_path.read_bytes())
    expected_candidate = candidate_sha or str(receipt.get("candidate_code_sha") or "")
    plan_identity = receiver.supported_receipt_plan_identity(receipt, allow_legacy=True)
    if (
        receipt.get("result") != "PASS"
        or receipt.get("kind") != kind
        or plan_identity is None
        or receipt.get("candidate_code_sha") != expected_candidate
        or receipt.get("protected_code_sha") != protected_sha
        or receipt.get("deviations") != []
    ):
        raise ValueError(f"{kind} receipt identity is invalid")
    manifest_path = local_path(
        target, receipt_path.with_name("source-manifest.json").relative_to(target).as_posix()
    )
    archive_name = {
        "observation": "observation.tar.zst",
        "diagnostic": "diagnostic.tar.zst",
        "control": "control.tar.zst",
        "macro": "macro.tar.zst",
    }[kind]
    archive = local_path(target, receipt_path.with_name(archive_name).relative_to(target).as_posix())
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if receiver.sha256_file(manifest_path) != receipt.get("source_manifest_sha256"):
        raise ValueError(f"{kind} source manifest digest mismatch")
    assert plan_identity is not None
    receiver.validate_manifest(
        manifest,
        kind,
        expected_candidate,
        protected_sha,
        plan_identity[2],
        plan_version=plan_identity[1],
        plan_sha256=plan_identity[3],
    )
    if (
        receiver.sha256_file(archive) != receipt.get("archive_sha256")
        or archive.stat().st_size != receipt.get("archive_bytes")
    ):
        raise ValueError(f"{kind} archive bytes are invalid")
    if not isinstance(receipt.get("checks"), Mapping):
        raise ValueError(f"{kind} receipt lacks restore evidence")
    return receipt, manifest, receipt_path


def pointer_generation(
    target: Path,
    pointer_name: str,
    kind: str,
    *,
    candidate_sha: str,
    protected_sha: str,
    plan_commit: str,
) -> tuple[dict[str, object], dict[str, object], Mapping[str, object], Path]:
    pointer_path = target / f"catalog/{pointer_name}"
    if pointer_path.is_symlink():
        raise ValueError(f"{kind} pointer is symlinked")
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    entries = receiver.catalog_entries(target / "catalog/generations.jsonl")
    matches = [
        item for item in entries
        if item.get("entry_sha256") == pointer.get("catalog_entry_sha256")
        and item.get("receipt_path") == pointer.get("receipt_path")
        and item.get("receipt_sha256") == pointer.get("receipt_sha256")
        and item.get("kind") == kind
    ]
    if len(matches) != 1:
        raise ValueError(f"{kind} pointer is not bound to the catalog")
    receipt, manifest, receipt_path = verified_receipt(
        target,
        str(pointer["receipt_path"]),
        matches[0],
        kind,
        candidate_sha=candidate_sha,
        protected_sha=protected_sha,
        plan_commit=plan_commit,
    )
    return receipt, manifest, matches[0], receipt_path


def latest_status(
    target: Path,
    remote: Mapping[str, object] | None,
    *,
    candidate_sha: str,
    protected_sha: str,
    plan_commit: str,
) -> dict[str, object]:
    if not remote:
        return {"status": "STALE", "reason": "Pi has no completed observation"}
    date = str(remote.get("observation_date") or "")
    try:
        receipt, manifest, entry, receipt_path = pointer_generation(
            target,
            "latest-verified.json",
            "observation",
            candidate_sha=candidate_sha,
            protected_sha=protected_sha,
            plan_commit=plan_commit,
        )
        if receipt.get("observation_date") != date:
            raise ValueError("latest observation date changed")
        if manifest_file_hash(manifest, f"data/state/{date}.done.json") != remote.get("completion_marker_sha256"):
            raise ValueError("Pi completion generation changed")
        pointer_relative = "data/state/observation-pointers-v2/latest-observation.json"
        if manifest_file_hash(manifest, pointer_relative) != remote.get("pointer_sha256"):
            raise ValueError("Pi observation pointer changed")
        checks = receipt.get("checks")
        if not isinstance(checks, Mapping) or not isinstance(checks.get("observation"), Mapping):
            raise ValueError("latest receipt lacks observation restore evidence")
        return {
            "status": "UP_TO_DATE",
            "observation_date": date,
            "receipt_path": str(receipt_path),
            "archive_sha256": receipt["archive_sha256"],
            "catalog_sequence": entry["sequence"],
        }
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return {"status": "STALE", "observation_date": date, "reason": str(exc)}


def component_status(
    target: Path,
    identities: Mapping[str, object],
    kind: str,
    *,
    candidate_sha: str,
    protected_sha: str,
    plan_commit: str,
) -> dict[str, object]:
    try:
        remote = identities.get(kind)
        if not isinstance(remote, Mapping):
            raise ValueError(f"Pi {kind} identity is missing")
        receipt, manifest, entry, path = pointer_generation(
            target,
            f"latest-{kind}.json",
            kind,
            candidate_sha=candidate_sha,
            protected_sha=protected_sha,
            plan_commit=plan_commit,
        )
        if content_revision(manifest) != remote.get("content_revision"):
            raise ValueError(f"Pi {kind} content changed")
        if not has_component_restore_evidence(receipt.get("checks"), kind):
            raise ValueError(f"{kind} receipt lacks component restore evidence")
        return {"status": "UP_TO_DATE", "receipt_path": str(path), "catalog_sequence": entry["sequence"]}
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return {"status": "STALE", "reason": str(exc)}


def inventory_status(
    target: Path,
    retained: Sequence[Mapping[str, object]],
    identities: Mapping[str, object],
    *,
    protected_sha: str,
    plan_commit: str,
    after_date: str = "2026-05-21",
) -> dict[str, object]:
    if plan_commit != receiver.PLAN_GIT_COMMIT:
        raise ValueError("inventory plan commit is not current")
    entries = receiver.catalog_entries(target / "catalog/generations.jsonl")
    completed = {
        str(item["date"])
        for item in retained
        if item.get("status") == "completed" and str(item["date"]) > after_date
    }
    covered: set[str] = set()
    for entry in entries:
        if entry.get("kind") != "observation" or entry.get("result") != "PASS":
            continue
        try:
            receipt_path = local_path(target, str(entry["receipt_path"]))
            if receiver.sha256_file(receipt_path) != entry.get("receipt_sha256"):
                continue
            receipt = json.loads(receipt_path.read_bytes())
            checks = receipt.get("checks")
            if (
                receipt.get("result") == "PASS"
                and receipt.get("kind") == "observation"
                and receiver.supported_receipt_plan_identity(receipt, allow_legacy=True) is not None
                and receipt.get("protected_code_sha") == protected_sha
                and receipt.get("deviations") == []
                and isinstance(checks, Mapping)
                and isinstance(checks.get("observation"), Mapping)
            ):
                covered.add(str(receipt.get("observation_date")))
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
    missing = sorted(completed - covered)
    diagnostics = identities.get("diagnostics")
    stale_diagnostics: list[str] = []
    if not isinstance(diagnostics, Mapping):
        stale_diagnostics.append("identity inventory missing")
    else:
        for date, remote in diagnostics.items():
            candidates = [
                item for item in entries
                if item.get("kind") == "diagnostic" and item.get("run_date") == date
            ]
            accepted = False
            for entry in reversed(candidates):
                try:
                    if not isinstance(remote, Mapping):
                        raise ValueError("invalid remote identity")
                    _receipt, manifest, _path = verified_receipt(
                        target,
                        str(entry["receipt_path"]),
                        entry,
                        "diagnostic",
                        candidate_sha=None,
                        protected_sha=protected_sha,
                        plan_commit=plan_commit,
                    )
                    if content_revision(manifest) == remote.get("content_revision"):
                        accepted = True
                        break
                except (OSError, ValueError, KeyError, json.JSONDecodeError):
                    continue
            if not accepted:
                stale_diagnostics.append(str(date))
    status = "UP_TO_DATE" if not missing and not stale_diagnostics else "STALE"
    return {
        "status": status,
        "missing_completed_dates": missing,
        "stale_diagnostics": stale_diagnostics,
    }


def select_backup_request(
    observation: Mapping[str, object], inventory: Mapping[str, object]
) -> tuple[str, tuple[str, ...]]:
    missing = inventory.get("missing_completed_dates")
    if not isinstance(missing, list) or any(
        not isinstance(date, str) or not receiver.DATE_RE.fullmatch(date) for date in missing
    ):
        raise ValueError("backup inventory has invalid missing completed dates")
    if missing != sorted(set(missing)):
        raise ValueError("backup inventory missing dates are not unique and ordered")
    latest = observation.get("observation_date")
    if latest is not None and (
        not isinstance(latest, str) or not receiver.DATE_RE.fullmatch(latest)
    ):
        raise ValueError("backup observation has an invalid latest date")
    if missing and latest is None:
        raise ValueError("backup inventory has missing dates without a latest observation")
    if isinstance(latest, str) and any(date > latest for date in missing):
        raise ValueError("backup inventory has a missing date after the latest observation")
    historical = tuple(date for date in missing if date != latest)
    return ("backfill", historical) if historical else ("backup-latest", ())


def validate_source_listing(
    listing: Mapping[str, object],
    *,
    protected_sha: str,
    now: datetime | None = None,
) -> tuple[Mapping[str, object], list[Mapping[str, object]]]:
    if listing.get("ok") is not True:
        raise ValueError("Pi source listing did not report success")
    preflight = listing.get("preflight")
    checked_at_raw = preflight.get("checked_at") if isinstance(preflight, Mapping) else None
    if not isinstance(checked_at_raw, str):
        raise ValueError("Pi source listing lacks a checked_at identity")
    try:
        checked_at = datetime.fromisoformat(checked_at_raw)
    except ValueError as exc:
        raise ValueError("Pi source listing has an invalid checked_at identity") from exc
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("Pi source listing checked_at is not timezone-aware")
    checked_at_hobart = checked_at.astimezone(HOBART_TZ)
    if checked_at.utcoffset() != checked_at_hobart.utcoffset():
        raise ValueError("Pi source listing checked_at is not Australia/Hobart time")
    reference = (now or datetime.now(HOBART_TZ)).astimezone(HOBART_TZ)
    reference_minute = reference.hour * 60 + reference.minute
    if 30 <= reference_minute < 210:
        raise ValueError("laptop backup is forbidden during the Hobart quiet window")
    if checked_at_hobart > reference + timedelta(minutes=5):
        raise ValueError("Pi source listing checked_at is in the future")
    if checked_at_hobart < reference - timedelta(minutes=5):
        raise ValueError("Pi source listing checked_at is stale")
    if checked_at_hobart.date() > reference.date():
        raise ValueError("Pi source listing checked_at is on a future Hobart date")
    source_date = checked_at_hobart.date()

    def source_date_value(value: object, label: str) -> str:
        if not isinstance(value, str) or not receiver.DATE_RE.fullmatch(value):
            raise ValueError(f"Pi {label} date is invalid")
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"Pi {label} date is invalid") from exc
        if parsed > source_date:
            raise ValueError(f"Pi {label} date is in the future")
        return value

    def component_identity(value: object, label: str) -> Mapping[str, object]:
        revision = value.get("content_revision") if isinstance(value, Mapping) else None
        if (
            not isinstance(value, Mapping)
            or not isinstance(revision, str)
            or not receiver.SHA256_RE.fullmatch(revision)
            or type(value.get("source_bytes")) is not int
            or int(value["source_bytes"]) <= 0
        ):
            raise ValueError(f"Pi {label} component identity is invalid")
        return value

    production = preflight.get("production") if isinstance(preflight, Mapping) else None
    if (
        not isinstance(production, Mapping)
        or production.get("clean") is not True
        or production.get("commit") != protected_sha
        or production.get("dirty_paths") != []
    ):
        raise ValueError("Pi production identity is invalid")
    if preflight.get("daily_timer") != "enabled":
        raise ValueError("Pi daily timer identity is invalid")
    if preflight.get("daily_timer_active") != "active":
        raise ValueError("Pi active daily timer identity is invalid")
    validate_next_daily_timer(preflight.get("daily_timer_next"), checked_at_hobart)
    if preflight.get("ingest_lock_absent") is not True:
        raise ValueError("Pi ingest lock identity is invalid")
    runtime_health_fields = [
        field for field in ("dashboard_healthy", "status_healthy") if field in preflight
    ]
    if len(runtime_health_fields) != 1 or preflight[runtime_health_fields[0]] is not True:
        raise ValueError("Pi runtime health identity is invalid")
    service = preflight.get("daily_service")
    terminal_failure = preflight.get("terminal_failure_authorization")
    if service == "inactive":
        if terminal_failure is not None:
            raise ValueError("Pi inactive service has unexpected failure authorization")
    elif service == "failed":
        if not isinstance(terminal_failure, Mapping):
            raise ValueError("Pi failed service lacks terminal-failure authorization")
        failure_date = source_date_value(terminal_failure.get("run_date"), "failure")
        state_root_raw = preflight.get("state_root")
        record_path = terminal_failure.get("record_path")
        state_root = PurePosixPath(state_root_raw) if isinstance(state_root_raw, str) else None
        failure_path = PurePosixPath(record_path) if isinstance(record_path, str) else None
        if (
            terminal_failure.get("result") != "FAIL"
            or state_root is None
            or not state_root.is_absolute()
            or str(state_root) != state_root_raw
            or any(part in {".", ".."} for part in state_root.parts)
            or failure_path is None
            or not failure_path.is_absolute()
            or str(failure_path) != record_path
            or any(part in {".", ".."} for part in failure_path.parts)
            or failure_path.parent
            != state_root / "ingest-executions" / failure_date
            or not failure_path.name.endswith(".FAIL.json")
        ):
            raise ValueError("Pi terminal-failure authorization is invalid")
    else:
        raise ValueError("Pi daily service identity is invalid")

    identities = listing.get("component_identities")
    retained = listing.get("retained_runs")
    if (
        not isinstance(identities, Mapping)
        or not isinstance(identities.get("diagnostics"), Mapping)
        or not isinstance(retained, list)
    ):
        raise ValueError("Pi component inventory is missing or incomplete")
    component_identity(identities.get("control"), "control")
    component_identity(identities.get("macro"), "macro")
    diagnostics = identities["diagnostics"]
    assert isinstance(diagnostics, Mapping)
    for diagnostic_date, diagnostic_identity in diagnostics.items():
        source_date_value(diagnostic_date, "diagnostic")
        component_identity(diagnostic_identity, f"diagnostic {diagnostic_date}")
    completed: list[str] = []
    diagnostic_dates: list[str] = []
    prior = ""
    for item in retained:
        run_date = item.get("date") if isinstance(item, Mapping) else None
        if (
            not isinstance(item, Mapping)
            or item.get("status") not in {"completed", "diagnostic"}
        ):
            raise ValueError("Pi retained-run inventory is invalid")
        try:
            run_date = source_date_value(run_date, "retained-run")
        except ValueError as exc:
            raise ValueError("Pi retained-run inventory is invalid") from exc
        if run_date <= prior:
            raise ValueError("Pi retained-run inventory is invalid")
        prior = run_date
        if item["status"] == "completed":
            completed.append(run_date)
        else:
            diagnostic_dates.append(run_date)
    if not completed:
        raise ValueError("Pi source listing has no completed observation")
    if listing.get("completed_dates") != completed:
        raise ValueError("Pi completed-date identity is inconsistent with retained runs")
    if sorted(diagnostics) != diagnostic_dates:
        raise ValueError("Pi diagnostic identity is inconsistent with retained runs")
    latest = listing.get("latest_observation")
    if not isinstance(latest, Mapping):
        raise ValueError("Pi latest observation is inconsistent with retained runs")
    latest_date = source_date_value(latest.get("observation_date"), "latest observation")
    if latest_date != completed[-1]:
        raise ValueError("Pi latest observation is inconsistent with retained runs")
    completion_digest = latest.get("completion_marker_sha256")
    pointer_digest = latest.get("pointer_sha256")
    if (
        not isinstance(completion_digest, str)
        or not receiver.SHA256_RE.fullmatch(completion_digest)
        or not isinstance(pointer_digest, str)
        or not receiver.SHA256_RE.fullmatch(pointer_digest)
    ):
        raise ValueError("Pi latest observation identity is incomplete")
    return identities, retained


def scheduled_status(target: Path, listing: Mapping[str, object], args: argparse.Namespace) -> dict[str, object]:
    try:
        identities, retained = validate_source_listing(
            listing, protected_sha=args.protected_code_sha
        )
    except ValueError as exc:
        return {"status": "BLOCKED", "reason": str(exc)}
    observation = latest_status(
        target,
        listing.get("latest_observation"),
        candidate_sha=args.candidate_code_sha,
        protected_sha=args.protected_code_sha,
        plan_commit=args.plan_git_commit,
    )
    controls = {
        kind: component_status(
            target,
            identities,
            kind,
            candidate_sha=args.candidate_code_sha,
            protected_sha=args.protected_code_sha,
            plan_commit=args.plan_git_commit,
        )
        for kind in ("control", "macro")
    }
    inventory = inventory_status(
        target,
        retained,
        identities,
        protected_sha=args.protected_code_sha,
        plan_commit=args.plan_git_commit,
    )
    status = "UP_TO_DATE" if all(
        item["status"] == "UP_TO_DATE"
        for item in (observation, controls["control"], controls["macro"], inventory)
    ) else "STALE"
    command, backfill_dates = select_backup_request(observation, inventory)
    return {
        "status": status,
        "backup_command": command,
        "backfill_required": command == "backfill",
        "backfill_dates": list(backfill_dates),
        "observation": observation,
        **controls,
        "inventory": inventory,
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--target", type=Path, required=True)
    receiver.add_transport_arguments(value)
    value.add_argument("--source-helper", type=Path)
    value.add_argument("--recovery-image", type=Path, required=True)
    value.add_argument("--candidate-code-sha", required=True)
    value.add_argument("--protected-code-sha", required=True)
    value.add_argument("--plan-git-commit", required=True)
    value.add_argument("--operator")
    mode = value.add_mutually_exclusive_group()
    mode.add_argument("--check-only", action="store_true")
    mode.add_argument("--status-only", action="store_true")
    value.add_argument("--transition-id")
    value.add_argument("--allowed-predecessor-candidate-sha", action="append", default=[])
    return value


def open_transition_allows_invocation(args: argparse.Namespace) -> tuple[bool, str | None]:
    """Block Task Scheduler during an OPEN A3 transition without writing evidence."""
    try:
        target = receiver.canonical_target(args.target)
        root = target / "evidence/A3-LAPTOP-TASK-TRANSITION"
        pointer = root / "ACTIVE_TRANSITION.json"
        guard = target / "catalog/.receiver.lock"
        active = json.loads(pointer.read_text(encoding="utf-8")) if pointer.exists() else {}
        guarded = False
        transition_id: object = None
        if isinstance(active, Mapping) and active.get("state") == "OPEN":
            guarded = True
            transition_id = active.get("transition_id")
        if guard.exists():
            guard_value = json.loads(guard.read_text(encoding="utf-8"))
            if isinstance(guard_value, Mapping) and guard_value.get("kind") == "A3_TRANSITION_GUARD":
                guarded = True
                guard_id = guard_value.get("transition_id")
                if transition_id not in (None, guard_id):
                    raise ValueError("transition guard identity differs from active pointer")
                transition_id = guard_id
        if not guarded:
            if args.transition_id or getattr(args, "allowed_predecessor_candidate_sha", ()):
                return False, "transition-only lineage authority requires an active A3 transition"
            return True, None
        lease = json.loads((root / ".transition-runtime.lock").read_text(encoding="utf-8"))
        lease_pid = lease.get("pid") if isinstance(lease, Mapping) else None
        lease_owned = type(lease_pid) is int and receiver.process_descends_from(
            os.getpid(), lease_pid
        )
        authorised = (
            isinstance(transition_id, str)
            and args.transition_id == transition_id
            and isinstance(lease, Mapping)
            and lease.get("transition_id") == transition_id
            and lease_owned
        )
        return authorised, None if authorised else "an authenticated A3 transition is active"
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return False, f"transition gate is invalid: {exc}"


def receiver_arguments(
    args: argparse.Namespace,
    command: str,
    include_dates: Sequence[str] = (),
    include_diagnostic_dates: Sequence[str] = (),
) -> list[str]:
    values = [
        command,
        "--target", str(args.target),
        "--host", args.host,
        "--ssh-user", args.ssh_user,
        "--ssh-port", str(args.ssh_port),
        "--ssh-path", args.ssh_path,
        "--ssh-sha256", args.ssh_sha256,
        "--scp-path", args.scp_path,
        "--scp-sha256", args.scp_sha256,
        "--ssh-identity", args.ssh_identity,
        "--ssh-known-hosts", args.ssh_known_hosts,
        "--recovery-image", str(args.recovery_image),
        "--candidate-code-sha", args.candidate_code_sha,
        "--protected-code-sha", args.protected_code_sha,
        "--plan-git-commit", args.plan_git_commit,
    ]
    if args.source_helper:
        values.extend(("--source-helper", str(args.source_helper)))
    if args.operator:
        values.extend(("--operator", args.operator))
    for date in include_dates:
        values.extend(("--include-date", date))
    values.append("--select-diagnostics")
    for date in include_diagnostic_dates:
        values.extend(("--include-diagnostic-date", date))
    return values


def invoke_receiver(
    args: argparse.Namespace,
    command: str,
    include_dates: Sequence[str] = (),
    include_diagnostic_dates: Sequence[str] = (),
) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = receiver.main(
            receiver_arguments(
                args,
                command,
                include_dates,
                include_diagnostic_dates,
            )
        )
    return code, stdout.getvalue(), stderr.getvalue()


scheduled_record_mutex = lineage.scheduled_record_mutex


def prepare_execution_lineage(target: Path, args: argparse.Namespace) -> None:
    """Authenticate or repair the predecessor before any backup-data mutation."""
    receiver.verify_plan_document()
    with scheduled_record_mutex(target):
        lineage.repair_orphaned_suffix(target, {
            "plan_git_commit": args.plan_git_commit,
            "candidate_code_sha": args.candidate_code_sha,
            "protected_code_sha": args.protected_code_sha,
            "operator": args.operator or "scheduled-task",
            "allowed_predecessor_candidates": tuple(
                getattr(args, "allowed_predecessor_candidate_sha", ())
            ),
        })


def record_execution(
    target: Path,
    args: argparse.Namespace,
    result: str,
    action: str,
    detail: object,
) -> Path:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    plan = receiver.verify_plan_document()
    with scheduled_record_mutex(target):
        pointer_path = target / "catalog/latest-scheduled.json"
        previous = lineage.repair_orphaned_suffix(target, {
            "plan_git_commit": args.plan_git_commit,
            "candidate_code_sha": args.candidate_code_sha,
            "protected_code_sha": args.protected_code_sha,
            "operator": args.operator or "scheduled-task",
            "allowed_predecessor_candidates": tuple(
                getattr(args, "allowed_predecessor_candidate_sha", ())
            ),
        })
        previous_execution = (
            {key: previous[key] for key in ("record_path", "record_sha256")}
            if previous else None
        )
        record = {
            "schema_version": 1,
            "plan_document_id": receiver.PLAN_DOCUMENT_ID,
            "plan_version": receiver.PLAN_VERSION,
            "plan_git_commit": args.plan_git_commit,
            "plan_sha256": receiver.PLAN_SHA256,
            "plan_raw_sha256": plan["plan_raw_sha256"],
            "plan_normalized_raw_sha256": plan["plan_normalized_raw_sha256"],
            "candidate_code_sha": args.candidate_code_sha,
            "protected_code_sha": args.protected_code_sha,
            "operator": args.operator or "scheduled-task",
            "timestamps": {"completed_at": now},
            "exact_commands": [" ".join(json.dumps(value) for value in [sys.executable, *sys.argv])],
            "action": action,
            "detail": detail,
            "deviations": [],
            "deviation_authorization": None,
            "result": result,
            "previous_execution": previous_execution,
        }
        root = target / "catalog/scheduled-runs"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{now.replace(':', '').replace('-', '')}-{uuid.uuid4().hex}.json"
        receiver.atomic_create(path, receiver.canonical_json_bytes(record))
        receiver.atomic_replace(
            pointer_path,
            receiver.canonical_json_bytes({
                "record_path": path.relative_to(target).as_posix(),
                "record_sha256": receiver.sha256_file(path),
                "result": result,
            }),
        )
        return path


def safe_record(args: argparse.Namespace, result: str, action: str, detail: object) -> Path | None:
    try:
        target = receiver.canonical_target(args.target)
        if receiver.capacity(target)["free"] <= receiver.FREE_FLOOR_BYTES + 1024**2:
            return None
        return record_execution(target, args, result, action, detail)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.plan_git_commit != receiver.PLAN_GIT_COMMIT:
        print(json.dumps({
            "ok": False,
            "result": "BLOCKED",
            "error": "plan commit does not match the controlled runbook",
        }, indent=2), file=sys.stderr)
        return 1
    if args.status_only and (
        args.transition_id or args.allowed_predecessor_candidate_sha
    ):
        print(json.dumps({
            "ok": False,
            "result": "BLOCKED",
            "error": "status-only mode does not accept transition authority",
        }, indent=2), file=sys.stderr)
        return 1
    allowed, gate_error = open_transition_allows_invocation(args)
    if not allowed:
        print(json.dumps({"ok": False, "result": "BLOCKED", "error": gate_error}, indent=2), file=sys.stderr)
        return 1
    preflight_code, preflight_stdout, preflight_stderr = invoke_receiver(args, "preflight")
    if preflight_code:
        error = preflight_stderr or preflight_stdout
        if not args.status_only:
            safe_record(args, "BLOCKED", "PREFLIGHT_FAILED", {"error": error})
        sys.stderr.write(error)
        return preflight_code
    try:
        listing = json.loads(preflight_stdout)
    except json.JSONDecodeError as exc:
        error = f"Pi backup preflight returned invalid JSON: {exc}"
        if not args.status_only:
            safe_record(args, "BLOCKED", "PREFLIGHT_FAILED", {"error": error})
        print(error, file=sys.stderr)
        return 1
    try:
        target = Path(str(listing["target"])).resolve(strict=True)
        status = scheduled_status(target, listing, args)
    except (KeyError, OSError, ValueError) as exc:
        error = f"Pi backup preflight metadata is invalid: {exc}"
        if not args.status_only:
            safe_record(args, "BLOCKED", "PREFLIGHT_FAILED", {"error": error})
        print(error, file=sys.stderr)
        return 1
    if args.status_only:
        ok = status["status"] != "BLOCKED"
        print(json.dumps({
            "ok": ok,
            "result": "PASS" if ok else "BLOCKED",
            "action": "STATUS_ONLY",
            **status,
        }, indent=2, sort_keys=True), file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    if status["status"] == "BLOCKED":
        path = record_execution(target, args, "BLOCKED", "PREFLIGHT_FAILED", status)
        print(json.dumps({
            "ok": False,
            "result": "BLOCKED",
            "action": "PREFLIGHT_FAILED",
            "execution_record": str(path),
            **status,
        }, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    if status["status"] == "UP_TO_DATE":
        path = record_execution(target, args, "PASS", "NO_BACKUP_DATA_WRITE", status)
        print(json.dumps({
            "ok": True,
            "result": "PASS",
            "action": "NO_BACKUP_DATA_WRITE",
            "execution_record": str(path),
            **status,
        }, indent=2, sort_keys=True))
        return 0
    if args.check_only:
        path = record_execution(target, args, "BLOCKED", "BACKUP_REQUIRED", status)
        print(json.dumps({
            "ok": False,
            "result": "BLOCKED",
            "action": "BACKUP_REQUIRED",
            "execution_record": str(path),
            **status,
        }, indent=2, sort_keys=True))
        return 1
    try:
        prepare_execution_lineage(target, args)
    except (OSError, ValueError) as exc:
        print(f"Scheduled execution lineage is invalid: {exc}", file=sys.stderr)
        return 1
    command = str(status["backup_command"])
    missing_dates = status.get("backfill_dates", [])
    backup_code, backup_stdout, backup_stderr = invoke_receiver(
        args,
        command,
        missing_dates if command == "backfill" else (),
        status.get("inventory", {}).get("stale_diagnostics", []),
    )
    if backup_code:
        error = backup_stderr or backup_stdout
        record_execution(target, args, "FAIL", command.upper(), {"before": status, "error": error})
        sys.stderr.write(error)
        return backup_code
    verify_code, verify_stdout, verify_stderr = invoke_receiver(args, "preflight")
    if verify_code:
        error = verify_stderr or verify_stdout
        record_execution(target, args, "FAIL", "POST_BACKUP_VERIFY", {"before": status, "error": error})
        sys.stderr.write(error)
        return verify_code
    try:
        verified_listing = json.loads(verify_stdout)
    except json.JSONDecodeError as exc:
        error = f"Post-backup preflight returned invalid JSON: {exc}"
        record_execution(target, args, "FAIL", "POST_BACKUP_VERIFY", {
            "before": status,
            "attempted_action": command.upper(),
            "error": error,
        })
        print(error, file=sys.stderr)
        return 1
    try:
        verified = scheduled_status(target, verified_listing, args)
    except (KeyError, OSError, ValueError) as exc:
        error = f"Post-backup preflight metadata is invalid: {exc}"
        record_execution(target, args, "FAIL", "POST_BACKUP_VERIFY", {
            "before": status,
            "attempted_action": command.upper(),
            "error": error,
        })
        print(error, file=sys.stderr)
        return 1
    if verified["status"] == "BLOCKED":
        record_execution(target, args, "FAIL", "POST_BACKUP_VERIFY", {
            "before": status,
            "attempted_action": command.upper(),
            "after": verified,
        })
        print(json.dumps({
            "ok": False,
            "result": "FAIL",
            "action": "POST_BACKUP_VERIFY",
            "attempted_action": command.upper(),
            "detail": verified,
        }, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    result = "PASS" if verified["status"] == "UP_TO_DATE" else "FAIL"
    path = record_execution(target, args, result, command.upper(), {"before": status, "after": verified})
    sys.stdout.write(backup_stdout)
    print(json.dumps({
        "ok": result == "PASS",
        "result": result,
        "action": command.upper(),
        "execution_record": str(path),
        **verified,
    }, indent=2, sort_keys=True))
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
