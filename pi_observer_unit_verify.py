"""Refuse installer activation unless systemd loaded the intended observer commands."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

SERVICE = "org.freedesktop.systemd1"
INTERFACE = SERVICE + ".Service"
COMMAND_TYPE = "a(sasbttttuii)"
COMMAND_PROPERTIES = ("ExecStart", "ExecCondition", "ExecStartPre", "ExecStartPost", "ExecStop", "ExecStopPost")
PROPERTIES = (*COMMAND_PROPERTIES, "Environment", "UnsetEnvironment")


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
    rows = [json.loads(line) for line in output.splitlines() if line.strip()]
    if len(rows) != len(PROPERTIES):
        raise ValueError(f"{unit}: incomplete property readback")
    values = {}
    for name, row in zip(PROPERTIES, rows):
        expected_type = COMMAND_TYPE if name.startswith("Exec") else "as"
        if not isinstance(row, dict) or row.get("type") != expected_type or not isinstance(row.get("data"), list):
            raise ValueError(f"{unit}: invalid {name} readback")
        values[name] = row["data"]
    return values


def verify_service(unit, expected, repo, values):
    commands = values["ExecStart"]
    if (len(commands) != 1 or not isinstance(commands[0], list) or len(commands[0]) != 10
            or commands[0][0] != expected[0] or commands[0][1] != expected or commands[0][2] is not False):
        raise ValueError(f"{unit}: effective ExecStart differs from the intended observer")
    if any(values[name] for name in COMMAND_PROPERTIES[1:]):
        raise ValueError(f"{unit}: inherited execution hooks require explicit review")
    environment = values["Environment"]
    if (not all(isinstance(item, str) for item in environment)
            or [item for item in environment if item.startswith("AR_LOCAL_CODE_ROOT=")]
            != ["AR_LOCAL_CODE_ROOT=" + repo]):
        raise ValueError(f"{unit}: observation code root differs from the installed repository")
    if unit == "ar-local-boot-recovery.service" and "AR_LOCAL_REPO" not in values["UnsetEnvironment"]:
        raise ValueError(f"{unit}: inherited path-valued AR_LOCAL_REPO is not unset")


def verify(repo, run=_run):
    commands = {
        "ar-local-daily-watchdog.service": ["/usr/bin/python3", "-B", repo + "/pi_ingest_observe.py"],
        "ar-local-boot-recovery.service": ["/usr/bin/sh", repo + "/deploy/pi/ar-local-boot-recovery.sh"],
    }
    for unit, expected in commands.items():
        verify_service(unit, expected, repo, read_service(unit, run))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path)
    args = parser.parse_args(argv)
    try:
        verify(str(args.repo.resolve(strict=True)))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(f"Observer unit verification failed; no activation authorized: {exc}", file=sys.stderr)
        return 1
    print("Effective watchdog and boot observation commands verified; no units started.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
