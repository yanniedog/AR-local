"""One bounded, read-only ingest/publication observation; never sends alerts."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import inspect
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ar_local_ingest_schedule import (
    DAILY_INGEST_TZ, DAILY_INGEST_TZ_KEY, expected_run_date_for_due,
    latest_daily_due_utc, next_daily_due_utc,
)

WORKER_TIMEOUT = 35
OUTPUT_LIMIT = 65536
UNITS = ("ar-local-daily.service", "ar-local-ingest-now.service", "ar-local-daily-watchdog.service")
INGEST_STATES = {"GRACE", "RUNNING", "STUCK", "COMPLETE", "PARTIAL", "MISSING", "INVALID",
                 "UNVERIFIED_METADATA_LIMIT", "CHECK_FAILED"}


def _remote_recovery(watch, root):
    """Return only small operational fields, never provider data or errors."""
    import re
    try:
        row = watch.read_json(root, "cdr-recovery-status.json", maximum=65536)
    except FileNotFoundError:
        return {"available": False}
    except (OSError, ValueError, TypeError):
        return {"available": False, "unverified": True}
    output = {"available": True}
    for key in ("run_date", "checked_at", "selected_generation_id"):
        value = row.get(key)
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:+-]{1,100}", value):
            output[key] = value
    count = row.get("failure_records")
    if type(count) is int and count >= 0:
        output["failure_records"] = count
    return output


def _remote_pending(watch, root):
    """Inspect all queued dates within a fixed metadata budget, never source files."""
    from datetime import date
    try:
        row = watch.read_json(root, "app-payload-publication-pending.json", maximum=1048576)
    except FileNotFoundError:
        return {"exists": False, "dates": []}
    except (OSError, ValueError, TypeError):
        return {"exists": True, "unverified": True}
    try:
        queued = row.get("queued_pointers", [])
        if "selection_retry" in row or not isinstance(queued, list) or len(queued) > 128:
            raise ValueError("ambiguous pending metadata")
        pointers = [row.get("pointer"), *queued]
        dates = []
        for pointer in pointers:
            day = pointer.get("observation_date") if isinstance(pointer, dict) else None
            if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
                raise ValueError("invalid pending date")
            dates.append(day)
        if row.get("run_date", dates[0]) != dates[0]:
            raise ValueError("contradictory pending date")
        return {"exists": True, "dates": sorted(set(dates)), "pointer_count": len(pointers)}
    except (ValueError, TypeError):
        return {"exists": True, "unverified": True}


def remote_snapshot():
    """Executed by python -B over stdin; imports no write-capable entrypoint."""
    from datetime import datetime, timezone
    from pathlib import Path
    import re
    import signal
    import sys
    signal.alarm(25)
    sys.path.insert(0, "/srv/ar-local/AR-local")
    import pi_issue_watchdog as watch
    now = datetime.now(timezone.utc)
    root = Path("/srv/ar-local/data/state")
    units, facets = {}, []

    class Observer:
        def observe(self, key, title, category, *, healthy):
            if re.fullmatch(r"[a-z0-9:-]{1,100}", key) and re.fullmatch(r"[A-Z_]{1,80}", category):
                facets.append({"key": key, "category": category, "healthy": healthy is True})

    for name in ("ar-local-daily.service", "ar-local-ingest-now.service", "ar-local-daily-watchdog.service"):
        try:
            units[name] = watch.unit_state(name)
        except Exception:
            units[name] = {"unverified": True}
    if any(row.get("unverified") for row in units.values()):
        ingest = {"status": "CHECK_FAILED"}
    else:
        try:
            ingest = watch.ingest_checks(Observer(), root, now, units=units)
        except Exception:
            ingest = {"status": "CHECK_FAILED"}
    safe_units = []
    for name, row in units.items():
        safe = {"unit": name, "unverified": row.get("unverified", False)}
        for key in ("ActiveState", "Result", "ExecMainStatus"):
            value = str(row.get(key, ""))
            safe[key] = value if re.fullmatch(r"[A-Za-z0-9_-]{0,60}", value) else "unverified"
        started = row.get("started_at")
        safe["started_at"] = started.isoformat() if isinstance(started, datetime) else None
        safe_units.append(safe)
    return {"schema_version": 1, "read_only": True, "checked_at": now.isoformat(),
            "ingest": {key: ingest.get(key) for key in ("status", "date")},
            "units": safe_units, "health_facets": facets,
            "recovery": _remote_recovery(watch, root), "publication_pending": _remote_pending(watch, root)}


def _worker(command, *, input_text=None):
    try:
        result = subprocess.run(command, input=input_text, capture_output=True, text=True,
                                timeout=WORKER_TIMEOUT, shell=False,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode or len(result.stdout.encode("utf-8")) > OUTPUT_LIMIT:
            return {"available": False, "error": "worker_failed"}
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise ValueError("invalid snapshot")
        return {"available": True, "value": value}
    except subprocess.TimeoutExpired:
        return {"available": False, "error": "worker_timeout"}
    except (OSError, ValueError):
        return {"available": False, "error": "worker_unavailable_or_invalid"}


def collect_pi():
    # Only trusted local source goes to the interpreter. Remote JSON is parsed as data.
    source = (inspect.getsource(_remote_recovery) + "\n" + inspect.getsource(_remote_pending)
              + "\n" + inspect.getsource(remote_snapshot)
              + "\nimport json\nprint(json.dumps(remote_snapshot()))\n")
    return _worker(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                    "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=1",
                    "-o", "RequestTTY=no", "ar-local-pi5", "python3 -B -"], input_text=source)


def collect_public(expected):
    return _worker([sys.executable, "-B", str(Path(__file__).resolve()), "--public-worker", expected])


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value)
        return stamp.astimezone(timezone.utc) if stamp.tzinfo is not None else None
    except ValueError:
        return None


def _schedule(now):
    today = now.astimezone(DAILY_INGEST_TZ).date().isoformat()
    due = latest_daily_due_utc(now)
    if expected_run_date_for_due(due) != today:
        due = next_daily_due_utc(now)
    return today, due


def _pi_facets(value, now, expected, start_due):
    failures, unknown = [], []
    checked = _timestamp(value.get("checked_at"))
    units = value.get("units")
    if (value.get("schema_version") != 1 or value.get("read_only") is not True
            or checked is None or abs((now - checked).total_seconds()) > 120
            or not isinstance(units, list) or len(units) != 3
            or {row.get("unit") for row in units if isinstance(row, dict)} != set(UNITS)):
        return [], ["pi_snapshot_unverified"]
    for row in units:
        started = _timestamp(row.get("started_at"))
        failed = (row.get("ActiveState") == "failed" or row.get("Result") not in ("", "success")
                  or row.get("ExecMainStatus") not in ("0", 0, ""))
        if row.get("unverified") or (failed and started is None):
            unknown.append("unit_state_unverified:" + row["unit"])
        elif failed and started.astimezone(DAILY_INGEST_TZ).date().isoformat() == expected:
            failures.append("same_day_unit_failed:" + row["unit"])
    ingest = value.get("ingest", {})
    status = ingest.get("status") if isinstance(ingest, dict) else None
    if now >= start_due:
        if status not in INGEST_STATES or ingest.get("date") != expected or status in {"CHECK_FAILED", "GRACE"}:
            unknown.append("ingest_check_unverified")
        elif status not in {"COMPLETE", "RUNNING"}:
            failures.append("ingest_" + status.lower())
        facets = value.get("health_facets")
        if not isinstance(facets, list):
            unknown.append("ingest_facets_unverified")
        else:
            for row in facets:
                if (isinstance(row, dict) and row.get("key") == "ingest-schedule:" + expected
                        and row.get("healthy") is False):
                    failures.append("scheduled_ingest_not_started")
        daily = next(row for row in units if row["unit"] == UNITS[0])
        if (_timestamp(daily.get("started_at")) or datetime.min.replace(tzinfo=timezone.utc)) < start_due - timedelta(minutes=30):
            failures.append("scheduled_ingest_not_started")
    return failures, unknown


def summarize(now, pi, public):
    if now.tzinfo is None:
        raise ValueError("timezone-aware observation time required")
    expected, due = _schedule(now)
    start_due, publication_due = due + timedelta(minutes=30), due + timedelta(minutes=90)
    failures, unknown = [], []
    pi_value = pi.get("value", {}) if pi.get("available") else {}
    if not pi.get("available"):
        unknown.append("pi_monitoring_unverified")
    else:
        failures, unknown = _pi_facets(pi_value, now, expected, start_due)
    ingest = pi_value.get("ingest", {})
    terminal_complete = (not unknown and isinstance(ingest, dict)
                         and ingest.get("status") == "COMPLETE" and ingest.get("date") == expected)
    pending = pi_value.get("publication_pending")
    pending_dates = pending.get("dates") if isinstance(pending, dict) else None
    try:
        valid_dates = (isinstance(pending_dates, list) and len(pending_dates) <= 129
                       and all(isinstance(day, str) and date.fromisoformat(day).isoformat() == day
                               and day <= expected for day in pending_dates))
    except ValueError:
        valid_dates = False
    current_pending = False
    if pi.get("available"):
        if (not isinstance(pending, dict) or pending.get("unverified")
                or type(pending.get("exists")) is not bool or not valid_dates
                or pending["exists"] != bool(pending_dates)):
            unknown.append("publication_pending_unverified")
        else:
            current_pending = expected in pending_dates
            if current_pending and now >= publication_due:
                failures.append("publication_pending")
    published = public.get("value", {}) if public.get("available") else {}
    current = (published.get("publication_current") is True
               and published.get("manifest_run_date") == expected
               and published.get("dates_index_latest_date") == expected
               and published.get("verification_scope") == "public_ciphertext_receipt")
    if now >= publication_due and not current:
        if public.get("available"):
            failures.append("publication_unavailable_or_inconsistent")
        else:
            unknown.append("public_monitoring_unverified")
    recovered_attempts = [facet for facet in failures if terminal_complete and current and not current_pending and not unknown
                          and (facet.startswith("same_day_unit_failed:") or facet == "scheduled_ingest_not_started")]
    ongoing = [facet for facet in failures if facet not in recovered_attempts]
    recovered = bool(recovered_attempts) and not ongoing
    status = ("RECOVERED_AFTER_FAILURE" if recovered else "FAILURE" if failures else "MONITORING_UNVERIFIED" if unknown else
              "GRACE" if now < publication_due else
              "RUNNING" if pi_value.get("ingest", {}).get("status") == "RUNNING" else "HEALTHY")
    return {"schema_version": 1, "read_only": True, "checked_at": now.isoformat(),
            "run_date": expected, "incident_key": "AR-INGEST-" + expected,
            "status": status, "notification_required": bool(failures or unknown),
            "failing_facets": sorted(set(failures)), "unknown": sorted(set(unknown)),
            "terminal_capture_complete": terminal_complete, "ongoing_failure": bool(ongoing),
            "recovered_after_failure": recovered, "recovered_facets": sorted(set(recovered_attempts)),
            "recovery_scope": "bounded capture metadata and publication date; exact generation reconciliation unverified",
            "publication_date_current": current, "exact_selected_generation_publication_verified": False,
            "schedule": {"timezone": DAILY_INGEST_TZ_KEY, "due_utc": due.isoformat(),
                         "start_ready_at": start_due.isoformat(), "publication_ready_at": publication_due.isoformat()},
            "pi": pi, "public": {"available": public.get("available", False), "current": current,
                                  "verification_scope": "public_ciphertext_receipt"},
            "scope": {"ingest": "Pi unit state and bounded finalized contract metadata",
                      "publication": "keyless ciphertext receipt and queued dates; does not prove full ingest or selected generation publication",
                      "excluded": ["database scans", "credentials", "Drive", "delivery", "router diagnosis"]}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-worker", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.public_worker:
        if date.fromisoformat(args.public_worker).isoformat() != args.public_worker:
            parser.error("invalid expected date")
        from publication_status import check
        print(json.dumps(check(args.public_worker)))
        return 0
    now = datetime.now(timezone.utc)
    expected, _ = _schedule(now)
    with ThreadPoolExecutor(max_workers=2) as executor:
        pi = executor.submit(collect_pi)
        public = executor.submit(collect_public, expected)
        result = summarize(now, pi.result(), public.result())
    print(json.dumps(result, sort_keys=True))
    return 1 if result["notification_required"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
