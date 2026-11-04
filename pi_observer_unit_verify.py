"""Refuse installer activation unless systemd loaded the intended observer commands."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from pi_observer_unit_contract import COMMAND_TYPE, command_matches, native_property, unprivileged_user

SERVICE = "org.freedesktop.systemd1"
INTERFACE = SERVICE + ".Service"
COMMAND_PROPERTIES = ("ExecStartEx", "ExecConditionEx", "ExecStartPreEx", "ExecStartPostEx", "ExecStopEx", "ExecStopPostEx")
PROPERTIES = (*COMMAND_PROPERTIES, "Environment", "UnsetEnvironment", "User")
UNITS = ("ar-local-daily-watchdog.service", "ar-local-boot-recovery.service")


class ObserverBusy(ValueError):
    pass


def _run(command):
    result = subprocess.run(command, check=True, capture_output=True, text=True,
                            timeout=15, shell=False)
    return result.stdout


def read_service(unit, run=_run):
    # show loads an inactive unit's definition without starting it. Query the
    # typed D-Bus properties, not systemctl's lossy human-readable argv string.
    if run(["systemctl", "show", unit, "--property=LoadState", "--value"]).strip() != "loaded":
        raise ValueError(f"{unit}: unit is not loaded")
    encoded = "".join(char if char.isalnum() else f"_{ord(char):02x}" for char in unit)
    output = run(["busctl", "--system", "--json=short", "--timeout=10", "get-property",
                  SERVICE, "/org/freedesktop/systemd1/unit/" + encoded, INTERFACE, *PROPERTIES])
    rows = [line for line in output.splitlines() if line.strip()]
    if len(rows) != len(PROPERTIES):
        raise ValueError(f"{unit}: incomplete property readback")
    values = {}
    for name, row in zip(PROPERTIES, rows):
        expected_type = COMMAND_TYPE if name.startswith("Exec") else ("s" if name == "User" else "as")
        value = native_property(row, expected_type)
        if not isinstance(value, str if name == "User" else list):
            raise ValueError(f"{unit}: invalid {name} readback")
        values[name] = value
    return values


def verify_service(unit, expected, repo, user, values):
    if not command_matches(values["ExecStartEx"], expected):
        raise ValueError(f"{unit}: effective ExecStart differs from the intended observer")
    if not unprivileged_user(user, "1") or values["User"] != user:
        raise ValueError(f"{unit}: effective service user differs from the intended non-root user")
    if any(values[name] for name in COMMAND_PROPERTIES[1:]):
        raise ValueError(f"{unit}: inherited execution hooks require explicit review")
    environment = values["Environment"]
    if (not all(isinstance(item, str) for item in environment)
            or [item for item in environment if item.startswith("AR_LOCAL_CODE_ROOT=")]
            != ["AR_LOCAL_CODE_ROOT=" + repo]):
        raise ValueError(f"{unit}: observation code root differs from the installed repository")
    if unit == "ar-local-boot-recovery.service" and "AR_LOCAL_REPO" not in values["UnsetEnvironment"]:
        raise ValueError(f"{unit}: inherited path-valued AR_LOCAL_REPO is not unset")


def verify_idle(run=_run):
    for unit in UNITS:
        output = run(["systemctl", "show", unit,
                      "--property=LoadState,ActiveState,SubState,MainPID,ControlPID"])
        rows = [line.split("=", 1) for line in output.splitlines() if line]
        values = dict(rows)
        if (len(rows) != 5 or len(values) != 5 or values.get("LoadState") not in {"loaded", "not-found"}
                or values.get("ActiveState") not in {"inactive", "failed"}
                or values.get("SubState") not in {"dead", "failed"}
                or values.get("MainPID") != "0" or values.get("ControlPID") != "0"):
            raise ObserverBusy(f"{unit}: observer invocation is active or idle evidence is incomplete; defer rollout")


def verify(repo, user, run=_run):
    if (not unprivileged_user(user, "1")
            or not unprivileged_user(user, run(["id", "-u", "--", user]).strip())):
        raise ValueError("expected observer user must resolve to a non-root account")
    verify_idle(run)
    commands = {
        "ar-local-daily-watchdog.service": ["/usr/bin/python3", "-B", repo + "/pi_ingest_observe.py"],
        "ar-local-boot-recovery.service": ["/usr/bin/sh", repo + "/deploy/pi/ar-local-boot-recovery.sh"],
    }
    for unit, expected in commands.items():
        verify_service(unit, expected, repo, user, read_service(unit, run))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path, nargs="?")
    parser.add_argument("--user", help="expected existing non-root service account")
    parser.add_argument("--idle-only", action="store_true", help="defer before any unit rollout if an old observer is active")
    args = parser.parse_args(argv)
    try:
        if args.idle_only:
            verify_idle()
        else:
            if args.repo is None or args.user is None:
                parser.error("repo and --user are required for full verification")
            verify(str(args.repo.resolve(strict=True)), args.user)
    except ObserverBusy as exc:
        print(f"Observer rollout deferred; no activation authorized: {exc}", file=sys.stderr)
        return 75
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(f"Observer unit verification failed; no activation authorized: {exc}", file=sys.stderr)
        return 1
    if args.idle_only:
        print("Watchdog and boot observer idle metadata verified; no units started.")
    else:
        print("Effective watchdog and boot observation commands verified; no units started.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
