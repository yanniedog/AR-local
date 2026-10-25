"""Pi-owned GitHub alerts for Drive access and failed, partial or missed ingest."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import time

from ar_local_ingest_schedule import DAILY_INGEST_TZ, latest_daily_due_utc, expected_run_date_for_due
from pi_github_alerts import configured_store, deliver

UNITS = ("ar-local-daily.service", "ar-local-ingest-now.service",
         "ar-local-daily-watchdog.service", "ar-local-drive-backup.service")
DAILY_TIMER = "ar-local-daily.timer"


class EvidenceLimit(ValueError):
    pass


def parse_systemd_timestamp(value):
    """Parse a systemd show timestamp rendered under TZ=UTC / LC_ALL=C."""
    if not isinstance(value, str) or not value or value in {"n/a", "0"}:
        return None
    for format in ("%a %Y-%m-%d %H:%M:%S UTC", "%a %Y-%m-%d %H:%M:%S.%f UTC"):
        try:
            return datetime.strptime(value, format).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_iso_utc(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        return None
    return stamp.astimezone(timezone.utc)


def unit_state(name):
    if name not in UNITS:
        raise ValueError("unexpected monitored unit")
    response = subprocess.run(
        ["systemctl", "show", name, "-p", "LoadState", "-p", "ActiveState",
         "-p", "Result", "-p", "ExecMainPID", "-p", "ExecMainStatus", "-p", "ExecMainStartTimestamp",
         "-p", "ExecMainExitTimestamp"],
        env={**os.environ, "TZ": "UTC", "LC_ALL": "C"},
        capture_output=True, text=True, timeout=5, check=True)
    if len(response.stdout) > 16384:
        raise ValueError("oversized unit response")
    row = dict(line.split("=", 1) for line in response.stdout.splitlines() if "=" in line)
    if row.get("LoadState") != "loaded":
        raise ValueError("monitored unit unavailable")
    for field, key in (("ExecMainStartTimestamp", "started_at"), ("ExecMainExitTimestamp", "finished_at")):
        row[key] = parse_systemd_timestamp(row.get(field, ""))
    # An unavailable start identity cannot prove recovery or quiet deferral,
    # but must not discard an actual OnFailure trigger before it is persisted.
    return row


def timer_last_trigger(name=DAILY_TIMER):
    """LastTriggerUSec for the daily timer; survives reboot when the timer unit does."""
    if name != DAILY_TIMER:
        raise ValueError("unexpected timer unit")
    response = subprocess.run(
        ["systemctl", "show", name, "-p", "LoadState", "-p", "LastTriggerUSec"],
        env={**os.environ, "TZ": "UTC", "LC_ALL": "C"},
        capture_output=True, text=True, timeout=5, check=True)
    if len(response.stdout) > 16384:
        raise ValueError("oversized timer response")
    row = dict(line.split("=", 1) for line in response.stdout.splitlines() if "=" in line)
    if row.get("LoadState") != "loaded":
        raise ValueError("daily timer unavailable")
    return parse_systemd_timestamp(row.get("LastTriggerUSec", ""))


def _aware_at_or_after(stamp, due):
    return isinstance(stamp, datetime) and stamp.tzinfo is not None and stamp >= due


def durable_run_started(state_root, date, due):
    """True when on-disk evidence shows a Hobart-date run at/after due.

    Used when ExecMainStartTimestamp was cleared by reboot. Fail closed when
    pointers, ledger timestamps, or dated run artifacts are absent or stale.
    """
    try:
        pointer = read_json(state_root, "observation-pointers-v2/latest-observation.json")
        if (pointer.get("observation_date") == date
                and pointer.get("observation_state") in {"complete", "partial"}):
            generation = pointer.get("generation_id")
            if isinstance(generation, str) and generation:
                event = read_json(state_root, f"ledger-v2/events/{date}/{generation}.json")
                if _aware_at_or_after(parse_iso_utc(event.get("finalized_at")), due):
                    return True
            marker_path = pointer.get("marker_path")
            if isinstance(marker_path, str) and marker_path:
                marker = read_json(state_root, marker_path)
                for key in ("finalized_at", "completed_at", "observed_at"):
                    if _aware_at_or_after(parse_iso_utc(marker.get(key)), due):
                        return True
    except (FileNotFoundError, OSError, ValueError, KeyError, TypeError, EvidenceLimit):
        pass
    try:
        data_root = state_root.resolve()
        if not data_root.is_dir():
            return False
        parent = data_root.parent
        for parts in (("runs", date, "_exports", "ingest-status.json"),
                      ("runs", date, "banks", "ingest-status.json")):
            path = parent.joinpath(*parts)
            if path.is_symlink() or not path.is_file():
                continue
            resolved = path.resolve()
            if parent not in resolved.parents:
                continue
            if path.stat().st_mtime >= due.timestamp():
                return True
            with path.open("rb") as stream:
                raw = stream.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                continue
            status = json.loads(raw)
            if not isinstance(status, dict):
                continue
            for key in ("started_at", "completed_at", "finished_at", "observed_at"):
                if _aware_at_or_after(parse_iso_utc(status.get(key)), due):
                    return True
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return False


def scheduled_ingest_started(*, due, service_started, timer_triggered, state_root, date):
    """Prove the day's scheduled ingest started; empty ExecMainStart is not a miss alone."""
    if _aware_at_or_after(service_started, due):
        return True
    if _aware_at_or_after(timer_triggered, due):
        return True
    return durable_run_started(state_root, date, due)


def watchdog_recovery(store, row, due, now):
    """Resolve only a dated watchdog failure followed by a proven successful run.

    Watchdog execution and capture completeness are independent. This does not
    resolve the ingest incident, infer past-day recovery, or run a service.
    """
    started, finished = row.get("started_at"), row.get("finished_at")
    try:
        if (row.get("ActiveState") != "inactive" or row.get("Result") != "success"
                or str(row.get("ExecMainStatus")) != "0" or int(row.get("ExecMainPID", 0)) <= 0
                or not isinstance(started, datetime) or started.tzinfo is None
                or not isinstance(finished, datetime) or finished.tzinfo is None
                or not due <= started <= finished <= now):
            return
    except (ValueError, TypeError):
        return
    date = expected_run_date_for_due(due)
    store.observe("ingest-watchdog:" + date, "Pi ingest watchdog failed: " + date,
                  "INGEST_WATCHDOG_FAILED", healthy=True, recovery_started_at=started)


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


def ingest_checks(store, state_root, now, units=None, timer_triggered=None):
    due = latest_daily_due_utc(now); date = expected_run_date_for_due(due)
    if now < due + timedelta(minutes=30):
        return {"status": "GRACE", "date": date}
    units = units if units is not None else {name: unit_state(name) for name in UNITS[:3]}
    daily = units[UNITS[0]]
    if timer_triggered is None:
        try:
            timer_triggered = timer_last_trigger()
        except (OSError, ValueError, subprocess.SubprocessError):
            # Timer probe failure is not proof of a miss; other durable signals remain.
            timer_triggered = None
    started = scheduled_ingest_started(
        due=due, service_started=daily.get("started_at"),
        timer_triggered=timer_triggered, state_root=state_root, date=date)
    store.observe("ingest-schedule:" + date, "Pi scheduled ingest missed: " + date,
                  "SCHEDULED_INGEST_NOT_STARTED", healthy=started)
    watchdog_recovery(store, units[UNITS[2]], due, now)
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
        spool = Path(os.environ.get("AR_LOCAL_DRIVE_BACKUP_SPOOL", "/var/lib/ar-local-drive-backup"))
        if quiet_window_deferral(spool, row):
            return {"status": "QUIET_WINDOW_DEFERRED"}
        key, title, category = "drive-backup", "Pi Google Drive backup failed", "BACKUP_SERVICE_FAILED"
    elif unit == "ar-local-daily-watchdog.service":
        key, title, category = "ingest-watchdog:" + date, "Pi ingest watchdog failed: " + date, "INGEST_WATCHDOG_FAILED"
    else:
        key, title, category = "ingest:" + date, "Pi ingest needs attention: " + date, "INGEST_SERVICE_FAILED"
    store.observe(key, title, category, healthy=False,
                  **({"record_failure": True} if unit == UNITS[2] else {}))
    return {"status": "FAILURE_EVENT_RECORDED", "category": category}


def quiet_window_deferral(spool, row):
    """Recognize only a clean pre-worker quiet-window refusal of this invocation.

    Exit2 also covers credential, disk, lock and other genuine failures. Missing
    or ambiguous proof leaves those failures alertable; no incident is recovered.
    """
    try:
        started = row.get("started_at")
        if (row.get("ActiveState") not in {"failed", "inactive"} or row.get("Result") != "exit-code"
                or str(row.get("ExecMainStatus")) != "2" or not isinstance(started, datetime)
                or started.tzinfo is None or int(row.get("ExecMainPID", 0)) <= 0):
            return False
        local = started.astimezone(DAILY_INGEST_TZ)
        if not 30 <= local.hour * 60 + local.minute < 210:
            return False
        root = spool / "resource-runs"
        if root.resolve() != root or root.is_symlink():
            return False
        matches, eligible, deadline = [], 0, time.monotonic() + 3
        with os.scandir(root) as entries:
            for count, entry in enumerate(entries, 1):
                if count > 2048 or time.monotonic() > deadline:
                    return False
                if not re.fullmatch(r"[0-9a-f]{32}", entry.name) or entry.is_symlink():
                    continue
                if not entry.is_dir(follow_symlinks=False) or entry.stat().st_mtime < started.timestamp():
                    continue
                eligible += 1
                if eligible > 64:
                    return False
                request_path = Path(entry.path) / "request.json"
                request = read_json(root, entry.name + "/request.json", maximum=65536)
                if (request.get("command") == "run" and type(request.get("supervisor_pid")) is int
                        and request["supervisor_pid"] == int(row["ExecMainPID"])
                        and request_path.stat().st_mtime >= started.timestamp()):
                    matches.append(entry.name)
        if len(matches) != 1:
            return False
        resource = read_json(root, matches[0] + "/resources.json")
        return (resource.get("schema") == "ar-local-drive-resources-v1"
                and resource.get("result") == "BLOCKED" and resource.get("group_clean") is True
                and resource.get("reason") == "Blocked: daily ingest quiet window: 00:30-03:30 Australia/Hobart"
                and type(resource.get("samples")) is int and resource["samples"] == 0
                and "workload_exit_code" in resource and resource["workload_exit_code"] is None
                and "cleanup_error" not in resource)
    except (OSError, ValueError, TypeError, KeyError):
        return False


def backup_check(store, spool, row=None):
    row = row if row is not None else unit_state("ar-local-drive-backup.service")
    title = "Pi Google Drive backup failed"
    if row.get("ActiveState") == "failed" or row.get("Result") not in {"", "success", None}:
        if quiet_window_deferral(spool, row):
            return {"status": "QUIET_WINDOW_DEFERRED"}
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
    store = None if args.checks_only else configured_store()
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
