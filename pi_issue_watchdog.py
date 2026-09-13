"""Pi-owned GitHub alerts for Drive access and failed, partial or missed ingest."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess

from ar_local_ingest_schedule import DAILY_INGEST_TZ, latest_daily_due_utc, expected_run_date_for_due
from pi_github_alerts import configured_store, deliver

UNITS = ("ar-local-daily.service", "ar-local-ingest-now.service",
         "ar-local-daily-watchdog.service", "ar-local-drive-backup.service")


class EvidenceLimit(ValueError):
    pass


def unit_state(name):
    if name not in UNITS:
        raise ValueError("unexpected monitored unit")
    response = subprocess.run(
        ["systemctl", "show", name, "-p", "LoadState", "-p", "ActiveState",
         "-p", "Result", "-p", "ExecMainPID", "-p", "ExecMainStatus", "-p", "ExecMainStartTimestamp"],
        env={**os.environ, "TZ": "UTC", "LC_ALL": "C"},
        capture_output=True, text=True, timeout=5, check=True)
    if len(response.stdout) > 16384:
        raise ValueError("oversized unit response")
    row = dict(line.split("=", 1) for line in response.stdout.splitlines() if "=" in line)
    if row.get("LoadState") != "loaded":
        raise ValueError("monitored unit unavailable")
    value = row.get("ExecMainStartTimestamp", "")
    row["started_at"] = (datetime.strptime(value, "%a %Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
                         if value else None)
    return row


def read_json(root, relative, *, maximum=1024 * 1024):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("invalid evidence path")
    path = root / relative
    if path.resolve() != path or root not in path.parents or path.is_symlink():
        raise ValueError("unsafe evidence path")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise EvidenceLimit("evidence exceeds metadata budget")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("invalid evidence object")
    return value


def completion(state_root, date):
    """Verify current finalization metadata without rehashing database contents.

    Full source/ledger integrity remains owned by the daily quality audit.
    This read-only check never repairs or advances an observation pointer.
    """
    from cdr_export_contract import contract_digest, source_generation_digest, validate_contract
    from cdr_ledger_v2 import event_digest
    try:
        pointer = read_json(state_root, "observation-pointers-v2/latest-observation.json")
        if pointer.get("observation_date") != date:
            return "MISSING"
        marker = read_json(state_root, pointer.get("marker_path"))
        contract_path = marker.get("export_contract_path")
        # Current real contracts exceed 2 MiB because they inventory preserved
        # artifacts. Only this bounded metadata record gets the larger limit.
        contract = read_json(state_root, contract_path, maximum=8 * 1024 * 1024)
        validate_contract(contract)
        generation = contract["generation_id"]
        event = read_json(state_root, f"ledger-v2/events/{date}/{generation}.json")
        if not (marker.get("finalization_schema_version") == 2 and marker.get("ledger_state") == "finalized"
                and marker.get("run_date") == date == contract["observation_date"]
                and contract["contract_digest"] == contract_digest(contract) == marker.get("export_contract_digest")
                and contract["source_generation_digest"] == source_generation_digest(contract)
                and event.get("event_digest") == event_digest(event) == marker.get("ledger_event_digest")
                == pointer.get("ledger_event_digest")
                and event.get("contract_path") == contract_path
                and event.get("contract_digest") == contract["contract_digest"]
                and event.get("ledger_state") == "finalized"
                and event.get("generation_id") == marker.get("generation_id") == pointer.get("generation_id") == generation
                and contract.get("completion_marker_path") == pointer.get("marker_path")
                and contract.get("source_path") == pointer.get("export_path")
                and contract.get("coverage", {}).get("eligible_rate_rows", 0) > 0):
            return "INVALID"
        observation = contract.get("observation_state")
        if any(row.get("observation_state") != observation for row in (pointer, marker, event)):
            return "INVALID"
        return "COMPLETE" if observation == "complete" else "PARTIAL"
    except FileNotFoundError:
        return "MISSING"
    except EvidenceLimit:
        return "UNVERIFIED_METADATA_LIMIT"
    except (OSError, ValueError, KeyError, TypeError):
        return "INVALID"


def ingest_checks(store, state_root, now, units=None):
    due = latest_daily_due_utc(now); date = expected_run_date_for_due(due)
    if now < due + timedelta(minutes=30):
        return {"status": "GRACE", "date": date}
    units = units if units is not None else {name: unit_state(name) for name in UNITS[:3]}
    daily = units[UNITS[0]]
    started = daily.get("started_at")
    scheduled_missed = started is None or started < due
    store.observe("ingest-schedule:" + date, "Pi scheduled ingest missed: " + date,
                  "SCHEDULED_INGEST_NOT_STARTED", healthy=not scheduled_missed)
    active = [r for r in units.values() if r.get("ActiveState") in {"active", "activating"}]
    if active:
        stale = any(r.get("started_at") and now - r["started_at"] > timedelta(hours=6) for r in active)
        if stale:
            store.observe("ingest:" + date, "Pi ingest needs attention: " + date, "INGEST_RUNTIME_EXCEEDED", healthy=False)
        return {"status": "STUCK" if stale else "RUNNING", "date": date}
    status = completion(state_root, date)
    store.observe("ingest:" + date, "Pi ingest needs attention: " + date,
                  "INGEST_" + status, healthy=status == "COMPLETE")
    return {"status": status, "date": date}


def failure_event(store, unit, now):
    row = unit_state(unit)
    # A delayed OnFailure invocation must still record its failed trigger even
    # when systemd has already recovered; never claim an observed failure in a test.
    date = expected_run_date_for_due(latest_daily_due_utc(row.get("started_at") or now))
    if unit == "ar-local-drive-backup.service":
        key, title, category = "drive-backup", "Pi Google Drive backup failed", "BACKUP_SERVICE_FAILED"
    elif unit == "ar-local-daily-watchdog.service":
        key, title, category = "ingest-watchdog:" + date, "Pi ingest watchdog failed: " + date, "INGEST_WATCHDOG_FAILED"
    else:
        key, title, category = "ingest:" + date, "Pi ingest needs attention: " + date, "INGEST_SERVICE_FAILED"
    store.observe(key, title, category, healthy=False)
    return {"status": "FAILURE_EVENT_RECORDED", "category": category}


def backup_check(store, spool, row=None):
    row = row if row is not None else unit_state("ar-local-drive-backup.service")
    title = "Pi Google Drive backup failed"
    if row.get("ActiveState") == "failed" or row.get("Result") not in {"", "success", None}:
        store.observe("drive-backup", title, "BACKUP_SERVICE_FAILED", healthy=False)
        return {"status": "FAILED"}
    if row.get("ActiveState") in {"active", "activating"}:
        return {"status": "RUNNING"}
    try:
        from pi_drive_backup_controller import validate_binding
        accepted = read_json(spool, "latest-verified.json")
        validate_binding(spool, accepted)
        operation = accepted["resource_evidence"]["path"]
        request = read_json(spool, operation + "/request.json")
        finished = datetime.fromisoformat(accepted["finished_at"])
        if not (accepted.get("result") == "PASS" and accepted.get("repository_check") == "PASS"
                and accepted.get("restore_verified_at") and accepted.get("snapshot_id")
                and request.get("command") == "run"
                and request.get("supervisor_pid") == int(row.get("ExecMainPID", 0))
                and str(row.get("ExecMainStatus")) == "0" and finished.tzinfo is not None
                and row.get("started_at") is not None and finished >= row["started_at"]):
            return {"status": "NO_CURRENT_VERIFIED_RECOVERY"}
    except (OSError, ValueError, RuntimeError, ImportError, KeyError, TypeError):
        return {"status": "NO_CURRENT_VERIFIED_RECOVERY"}
    store.observe("drive-backup", title, "BACKUP_SERVICE_FAILED", healthy=True)
    return {"status": "VERIFIED_RECOVERY"}


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--failed-unit", choices=UNITS)
    cli.add_argument("--delivery-test", action="store_true")
    cli.add_argument("--checks-only", action="store_true", help="Read health only; no issues or incident changes")
    args = cli.parse_args(argv)
    if args.checks_only and (args.failed_unit or args.delivery_test):
        cli.error("--checks-only cannot be combined with an issue-writing operation")
    now = datetime.now(timezone.utc)
    store = configured_store()
    if args.delivery_test:
        if args.checks_only or args.failed_unit:
            cli.error("delivery test is a separate operation")
        key = "delivery-test:" + now.strftime("%Y%m%d%H%M%S")
        title = "Pi alert delivery verification (test)"
        store.observe(key, title, "DELIVERY_TEST", healthy=False)
        first = deliver(store)
        store.observe(key, title, "DELIVERY_TEST", healthy=True)
        final = deliver(store)
        print(json.dumps({"test": first, "recovery": final}))
        return 0 if first["result"] == final["result"] == "DELIVERED" else 1
    if args.failed_unit:
        event = failure_event(store, args.failed_unit, now)
        delivery = deliver(store)
        print(json.dumps({"event": event, "delivery": delivery}))
        return 0 if delivery["result"] == "DELIVERED" else 1
    if args.checks_only:
        class ReadOnlyStore:
            def observe(self, *args, **kwargs): pass
        target = ReadOnlyStore()
    else:
        target = store
    try:
        ingest = ingest_checks(target, Path(os.environ.get("AR_LOCAL_DATA_ROOT", "/srv/ar-local/data")) / "state", now)
    except (OSError, ValueError, RuntimeError, ImportError, subprocess.SubprocessError):
        ingest = {"status": "CHECK_FAILED"}
        target.observe("ingest-monitor", "Pi ingest monitoring needs attention", "INGEST_MONITOR_FAILED", healthy=False)
    else:
        target.observe("ingest-monitor", "Pi ingest monitoring needs attention", "INGEST_MONITOR_FAILED", healthy=True)
    try:
        backup = backup_check(target, Path(os.environ.get("AR_LOCAL_DRIVE_BACKUP_SPOOL", "/var/lib/ar-local-drive-backup")))
    except (OSError, ValueError, RuntimeError, ImportError, subprocess.SubprocessError):
        backup = {"status": "CHECK_FAILED"}
        target.observe("backup-monitor", "Pi backup monitoring needs attention", "BACKUP_MONITOR_FAILED", healthy=False)
    else:
        target.observe("backup-monitor", "Pi backup monitoring needs attention", "BACKUP_MONITOR_FAILED", healthy=True)
    # Keep the natural ingest's resource window free of Drive probes. Queued
    # incident delivery and failure hooks still work during this window.
    local = now.astimezone(DAILY_INGEST_TZ)
    minutes = local.hour * 60 + local.minute
    if 30 <= minutes < 210 or ingest.get("status") in {"RUNNING", "STUCK"}:
        drive = {"status": "SKIPPED_INGEST_WINDOW"}
    else:
        try:
            from pi_drive_access_probe import probe
            drive = probe(os.environ.get("RESTIC_REPOSITORY", ""), Path(os.environ.get("RCLONE_CONFIG", "")))
        except Exception:
            drive = {"status": "FAIL", "category": "DRIVE_PROBE_FAILED", "phase": "LOCAL"}
        target.observe("drive-access", "Pi Google Drive authentication or access problem",
                       drive.get("category", "DRIVE_ACCESS_FAILED"), healthy=drive.get("status") == "PASS")
    delivery = {"result": "NOT_REQUESTED"} if args.checks_only else deliver(store)
    print(json.dumps({"ingest": ingest, "backup": backup, "drive": drive, "delivery": delivery}, sort_keys=True))
    return 0 if delivery["result"] in {"DELIVERED", "NOT_REQUESTED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
