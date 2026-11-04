"""Fail-closed 03:00 repair admission after the entire natural run terminates."""
from datetime import datetime, time as daytime, timedelta, timezone
import json
import hashlib
from itertools import islice
import os
from pathlib import Path
import re
import subprocess
import time
from zoneinfo import ZoneInfo

from ar_local_pi_runtime import data_state_root

HOBART = ZoneInfo("Australia/Hobart")
UNIT = "ar-local-queue-task-daily-repair.service"
CLAIMS = Path("/var/lib/ar-local-daily-repair")
INGEST_UNITS = ("ar-local-daily.service", "ar-local-ingest-now.service")
# Runtime units invoke the verifier shipped with this exact checkout. Keep its
# reviewed bytes pinned; a verifier change requires updating this contract too.
VALIDATOR = Path(__file__).resolve().with_name("verify_local.py")
VALIDATOR_SHA256 = "625b5f774985e6763523b8157693aac365dbe07672c90309b5b16eeb31eefaf2"
PROPERTIES = "LoadState,ActiveState,MainPID,ControlPID,ControlGroup,Result,ExecMainStatus,ExecMainStartTimestampMonotonic,ExecMainExitTimestampMonotonic,InactiveEnterTimestampMonotonic"
UNIT_PATHS = {
    INGEST_UNITS[0]: "/org/freedesktop/systemd1/unit/ar_2dlocal_2ddaily_2eservice",
    INGEST_UNITS[1]: "/org/freedesktop/systemd1/unit/ar_2dlocal_2dingest_2dnow_2eservice",
}


def _terminal_times(row):
    values = []
    for key in ("ExecMainStartTimestampMonotonic", "ExecMainExitTimestampMonotonic",
                "InactiveEnterTimestampMonotonic"):
        value = row[key]
        if not (type(value) is int or isinstance(value, str) and re.fullmatch(r"[0-9]+", value)):
            raise ValueError("unverified unit timestamp")
        values.append(int(value) / 1_000_000)
    return tuple(values)


def _manual_requires_validation(daily_times, manual_times):
    # A queued manual capture can start before the daily run yet finish later.
    # Its late post-start validation must not be hidden by older daily proof.
    return manual_times[1] > daily_times[1] or manual_times[2] > daily_times[2]


def daily_window(now):
    return daytime(3) <= now.astimezone(HOBART).time() < daytime(5)


def validate_terminal(units, now, monotonic):
    """An inactive main process alone does not establish terminal clearance."""
    for name in INGEST_UNITS:
        row = units.get(name, {})
        if (row.get("LoadState") != "loaded" or row.get("ActiveState") not in {"inactive", "failed"}
                or row.get("MainPID") != "0" or row.get("ControlPID") != "0"):
            return "natural_run_or_validation_not_terminal"
    try:
        daily = units[INGEST_UNITS[0]]
        daily_times = _terminal_times(daily)
        started, ended, verified = daily_times
        source_day = (now - timedelta(seconds=monotonic - started)).astimezone(HOBART).date()
        if not 0 < started <= ended <= verified <= monotonic or source_day != now.astimezone(HOBART).date():
            return "current_day_terminal_validation_unverified"
    except (KeyError, TypeError, ValueError, OverflowError):
        return "current_day_terminal_validation_unverified"
    if (daily.get("Result") != "success" or daily.get("ExecMainStatus") != "0"
            or daily.get("automatic_validation_contract_verified") is not True):
        return "automatic_validation_failed"
    try:
        manual = units[INGEST_UNITS[1]]
        manual_times = _terminal_times(manual)
        if manual_times != (0, 0, 0):
            if not 0 < manual_times[0] <= manual_times[1] <= manual_times[2] <= monotonic:
                return "manual_terminal_validation_unverified"
            if (_manual_requires_validation(daily_times, manual_times)
                    and (manual.get("Result") != "success" or manual.get("ExecMainStatus") != "0"
                         or manual.get("automatic_validation_contract_verified") is not True)):
                return "manual_automatic_validation_failed"
    except (KeyError, TypeError, ValueError, OverflowError):
        return "manual_terminal_validation_unverified"
    return ""


def natural_clearance(repo_root, now, *, include_ingest_lock=True, cgroup_root=Path("/sys/fs/cgroup")):
    """Read only public unit metadata, cgroup membership and lease presence."""
    try:
        if include_ingest_lock and os.path.lexists(data_state_root(repo_root) / "daily-ingest.lock"):
            return "natural_ingest_lease_present"
        units = {}
        for name in INGEST_UNITS:
            result = subprocess.run(["systemctl", "show", name, "--property=" + PROPERTIES],
                check=True, capture_output=True, text=True, timeout=5)
            row = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
            units[name] = row
            group = row.get("ControlGroup") or "/system.slice/" + name
            if group != "/system.slice/" + name:
                return "natural_cgroup_identity_unverified"
            path = cgroup_root / group.lstrip("/")
            if path.exists():
                entries = list(islice(path.rglob("cgroup.procs"), 257))
                if not entries or len(entries) > 256:
                    return "natural_cgroup_membership_unverified"
                if any(entry.read_text().strip() for entry in entries):
                    return "natural_cgroup_has_processes"
        daily = units[INGEST_UNITS[0]]
        daily["automatic_validation_contract_verified"] = validation_installed(daily)
        manual = units[INGEST_UNITS[1]]
        if _manual_requires_validation(_terminal_times(daily), _terminal_times(manual)):
            manual["automatic_validation_contract_verified"] = validation_installed(manual, unit=INGEST_UNITS[1])
        return validate_terminal(units, now, time.monotonic())
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError, subprocess.SubprocessError):
        return "natural_terminal_state_unavailable"


def validation_installed(daily, *, unit=INGEST_UNITS[0]):
    """Bind this run's successful post-start execution to the exact verifier."""
    if unit not in UNIT_PATHS:
        return False
    result = subprocess.run(["busctl", "--system", "--json=short", "--timeout=5", "get-property",
        "org.freedesktop.systemd1", UNIT_PATHS[unit],
        "org.freedesktop.systemd1.Service", "ExecStartPost"],
        check=True, capture_output=True, text=True, timeout=6)
    value = json.loads(result.stdout)
    if not isinstance(value, dict) or value.get("type") != "a(sasbttttuii)" or not isinstance(value.get("data"), list):
        return False
    command = ('for i in $(seq 1 40); do curl -fsS -o /dev/null --max-time 5 '
        'http://127.0.0.1:8808/api/latest && break; sleep 3; done; /usr/bin/python3 '
        + str(VALIDATOR) + ' --base-url=http://127.0.0.1:8808/ --require-banks-rates '
        '--expect-run-date "$(date +%F)" --history-mode=compact --history-timeout-seconds=90')
    if any(not isinstance(row, list) or len(row) != 10 for row in value["data"]):
        return False
    matches = [row for row in value["data"] if row[0] == "/bin/sh"
        and row[1] == ["/bin/sh", "-c", command] and row[2] is False]
    if len(matches) != 1 or VALIDATOR.is_symlink():
        return False
    row = matches[0]
    try:
        # systemd's ExecStartPost record exposes each command's monotonic
        # start/exit (fields 4/6), waitid code (8) and exit status (9).
        ended = int(daily["ExecMainExitTimestampMonotonic"])
        inactive = int(daily["InactiveEnterTimestampMonotonic"])
        completed = (all(type(row[index]) is int for index in (4, 6, 8, 9))
            and 0 < ended <= row[4] <= row[6] <= inactive
            and row[8] == 1 and row[9] == 0)
        return completed and hashlib.sha256(VALIDATOR.read_bytes()).hexdigest() == VALIDATOR_SHA256
    except (OSError, KeyError, TypeError, ValueError):
        return False


def claimed_service(now, *, environ=None, cgroup_path=Path("/proc/self/cgroup"), claims=CLAIMS):
    """Only the fixed once/day unit's current invocation can use early recovery."""
    values = os.environ if environ is None else environ
    try:
        invocation = values.get("INVOCATION_ID", "")
        if not re.fullmatch(r"[0-9a-f]{32}", invocation):
            return False
        group = "0::/system.slice/" + UNIT
        if group not in cgroup_path.read_text().splitlines():
            return False
        receipt = Path(values.get("AR_LOCAL_DAILY_REPAIR_RECEIPT", ""))
        day = now.astimezone(HOBART).date().isoformat()
        if receipt != claims / (day + ".json") or receipt.is_symlink() or receipt.stat().st_size > 4096:
            return False
        claim = json.loads(receipt.read_bytes())
        started = datetime.fromisoformat(claim["started_at"])
        return (claim.get("date") == day and claim.get("invocation") == invocation
                and claim.get("status") == "claimed_no_retry" and claim.get("max_total_seconds") == 1200
                and started.tzinfo is not None and 0 <= (now - started).total_seconds() < 1200)
    except (OSError, KeyError, TypeError, ValueError):
        return False


def early_daily_allowed(now):
    """Preserve every legacy 03:30 gate outside the supervised daily service."""
    local = now.astimezone(HOBART)
    if not daytime(3) <= local.time() < daytime(3, 30) or not claimed_service(now):
        return False
    repo = Path(os.environ.get("AR_LOCAL_CODE_ROOT", Path(__file__).resolve().parent))
    # The capture child checks this while holding its own native ingest lease;
    # lease admission and generation fencing remain with the existing wrapper.
    return not natural_clearance(repo, now, include_ingest_lock=False)
