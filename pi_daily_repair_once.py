"""Claim one Hobart day, then enter the existing queue under a kernel deadline."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

UNIT = "ar-local-queue-task-daily-repair.service"
STATE = Path("/var/lib/ar-local-daily-repair")
QUEUE = "/usr/local/lib/shared-pi-queue/pi_shared_queue.py"


def validate_supervisor(details, group, pid):
    expected = {"Id": UNIT, "Type": "notify", "NotifyAccess": "main", "MainPID": str(pid),
                "ControlGroup": group, "KillMode": "control-group",
                "SendSIGKILL": "yes", "Restart": "no",
                "RuntimeMaxUSec": "18min 20s", "TimeoutStartUSec": "1min 1s",
                "TimeoutStopUSec": "10s"}
    if not group.endswith("/" + UNIT) or any(details.get(k) != v for k, v in expected.items()):
        raise RuntimeError("repair requires the verified 20-minute systemd supervisor")


def claim_day(state, now, invocation):
    local = now.astimezone(ZoneInfo("Australia/Hobart"))
    if not 20 <= local.hour < 22:
        return None, "outside_daily_repair_window"
    day = local.date().isoformat()
    receipt = state / (day + ".json")
    value = {"date": day, "started_at": now.isoformat(), "invocation": invocation,
             "max_total_seconds": 1200, "status": "claimed_no_retry"}
    try:
        with receipt.open("x", encoding="utf-8") as stream:
            json.dump(value, stream); stream.flush(); os.fsync(stream.fileno())
    except FileExistsError:
        return None, "already_attempted_today"
    return receipt, "claimed"


def main():
    if sys.argv[1:] == ["--finish"]:
        return finish()
    lines = Path("/proc/self/cgroup").read_text().splitlines()
    group = next(line.split(":", 2)[2] for line in lines if line.startswith("0::"))
    names = "Id,Type,NotifyAccess,MainPID,ControlGroup,KillMode,SendSIGKILL,Restart,RuntimeMaxUSec,TimeoutStartUSec,TimeoutStopUSec"
    result = subprocess.run(["systemctl", "show", UNIT, "--property=" + names],
                            check=True, capture_output=True, text=True, timeout=5)
    details = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    validate_supervisor(details, group, os.getpid())
    receipt, status = claim_day(STATE, datetime.now(timezone.utc), os.environ["INVOCATION_ID"])
    print(json.dumps({"status": status}), flush=True)
    if receipt is None:
        return 0
    os.environ["AR_LOCAL_DAILY_REPAIR_RECEIPT"] = str(receipt)
    os.environ.pop("AR_LOCAL_DRIVE_BACKUP_SPOOL", None)
    # exec preserves the exact systemd MainPID required by the shared queue.
    worker = str(Path(__file__).with_name("pi_daily_repair_work.py"))
    args = ["/usr/bin/python3", "-B", QUEUE, "run", "--project", "ar-local",
            "--resource", "ar-local", "--mode", "exclusive", "--cpu-slots", "3",
            "--wait-timeout", "1", "--max-runtime", "1100", "--",
            "/usr/bin/python3", "-B", worker]
    os.execv(args[0], args)


def finish():
    day = datetime.now(timezone.utc).astimezone(ZoneInfo("Australia/Hobart")).date().isoformat()
    receipt = STATE / (day + ".json")
    if not receipt.exists():
        return 0
    claim = json.loads(receipt.read_text())
    if claim.get("invocation") != os.environ.get("INVOCATION_ID"):
        return 0  # A rejected duplicate must not overwrite the first result.
    outcome = {key: os.environ.get(key, "unknown") for key in ("SERVICE_RESULT", "EXIT_CODE", "EXIT_STATUS")}
    with receipt.with_suffix(".finished.json").open("x", encoding="utf-8") as stream:
        json.dump(outcome, stream); stream.flush(); os.fsync(stream.fileno())
    repo = Path(os.environ.get("AR_LOCAL_CODE_ROOT", Path(__file__).resolve().parent))
    subprocess.run(["/usr/bin/python3", "-B", str(repo / "pi_cdr_recovery.py"),
                    "--restore-dashboard"], check=False, timeout=8)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
