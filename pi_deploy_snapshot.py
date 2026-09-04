"""Validate the service and timer fields in a read-only Pi snapshot."""

from __future__ import annotations

import re
import shlex
import sys
from collections.abc import Mapping


def service_paths_ok(
    snapshot: Mapping[str, str],
    *,
    repo_path: str,
    forbidden_bootstrap_path: re.Pattern[str],
) -> bool:
    ok = True
    path_fields = {
        "status WorkingDirectory": snapshot.get("STATUS_WD", ""),
        "status ExecStart": snapshot.get("STATUS_EXEC", ""),
        "daily WorkingDirectory": snapshot.get("DAILY_WD", ""),
        "daily ExecStart": snapshot.get("DAILY_EXEC", ""),
    }
    environment_fields = {
        "status Environment": snapshot.get("STATUS_ENV", ""),
        "daily Environment": snapshot.get("DAILY_ENV", ""),
    }
    for label, value in {**path_fields, **environment_fields}.items():
        print(f"pi_deploy_verify: {label}: {value}")
    for label, value in path_fields.items():
        if forbidden_bootstrap_path.search(value):
            print(
                f"pi_deploy_verify: forbidden bootstrap path in {label}: {value}",
                file=sys.stderr,
            )
            ok = False
    for label, value in environment_fields.items():
        try:
            assignments = shlex.split(value)
        except ValueError:
            assignments = [value]
        for assignment in assignments:
            name, separator, path = assignment.partition("=")
            name = name.strip()
            path = path.strip()
            if not separator or not forbidden_bootstrap_path.search(path):
                continue
            if (name, path) in {
                ("HOME", "/home/pi"),
                ("XDG_CONFIG_HOME", "/home/pi/.config"),
            }:
                continue
            print(
                f"pi_deploy_verify: forbidden bootstrap path in {label}: {assignment}",
                file=sys.stderr,
            )
            ok = False

    status_exec = snapshot.get("STATUS_EXEC", "")
    repo_local_runs = f"{repo_path.rstrip('/')}/runs"
    bad_runs_tokens = (
        "--runs runs",
        "--runs=.",
        "--runs ./runs",
        f"--runs {repo_local_runs}",
        f"--runs={repo_local_runs}",
    )
    if any(token in status_exec for token in bad_runs_tokens):
        print(
            f"pi_deploy_verify: status --runs points inside the service checkout: {status_exec}",
            file=sys.stderr,
        )
        ok = False
    environments = snapshot.get("STATUS_ENV", "") + ";" + snapshot.get("DAILY_ENV", "")
    if "AR_LOCAL_DATA_ROOT=" not in environments:
        print(
            "pi_deploy_verify: AR_LOCAL_DATA_ROOT missing from Pi service environments",
            file=sys.stderr,
        )
        ok = False

    for label, key in (("repo", "DF_AR"), ("site", "DF_SITE"), ("data", "DF_DATA")):
        print(f"pi_deploy_verify: df {label}: {snapshot.get(key, '')}")
    return ok


def _expected_fields_ok(
    snapshot: Mapping[str, str], expected: Mapping[str, str], error: str
) -> bool:
    ok = True
    for field, value in expected.items():
        actual = snapshot.get(field, "")
        print(f"pi_deploy_verify: {field}: {actual}")
        if actual != value:
            ok = False
    if not ok:
        print(error, file=sys.stderr)
    return ok


def ingest_timers_ok(snapshot: Mapping[str, str]) -> bool:
    return _expected_fields_ok(
        snapshot,
        {
            "DAILY_TIMER_ENABLED": "enabled",
            "DAILY_TIMER_ACTIVE": "active",
            "WATCHDOG_TIMER_ENABLED": "enabled",
            "WATCHDOG_TIMER_ACTIVE": "active",
            "CAPACITY_TIMER_ENABLED": "enabled",
            "CAPACITY_TIMER_ACTIVE": "active",
        },
        "pi_deploy_verify: daily ingest timers are not armed",
    )


def ingest_service_fences_ok(snapshot: Mapping[str, str]) -> bool:
    return _expected_fields_ok(
        snapshot,
        {
            "DAILY_KILL_MODE": "control-group",
            "DAILY_START_TIMEOUT": "6h 15min",
            "WATCHDOG_KILL_MODE": "control-group",
            "WATCHDOG_START_TIMEOUT": "6h 15min",
            "MANUAL_KILL_MODE": "control-group",
            "MANUAL_START_TIMEOUT": "6h 15min",
        },
        "pi_deploy_verify: ingest process fencing is not active",
    )
