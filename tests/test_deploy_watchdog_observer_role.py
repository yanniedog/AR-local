"""The deploy verifier keeps capture fences and accepts only the bounded observer."""
import configparser
import copy
import json
from pathlib import Path

import pytest

import pi_deploy_verify as verify
from tests.pi_ingest_service_fixtures import ingest_definition_fields


EXEC = {"type": "a(sasasttttuii)", "data": [["/usr/bin/python3",
        ["/usr/bin/python3", "-B", "/srv/ar-local/AR-local/pi_ingest_observe.py"],
        [], 0, 0, 0, 0, 0, 0, 0]]}


def snapshot(**changes):
    value = {
        **ingest_definition_fields(),
        "DAILY_KILL_MODE": "control-group", "DAILY_START_TIMEOUT": "6h 15min",
        "MANUAL_KILL_MODE": "control-group", "MANUAL_START_TIMEOUT": "6h 15min",
        "WATCHDOG_KILL_MODE": "control-group", "WATCHDOG_START_TIMEOUT": "1min",
        "WATCHDOG_EXEC_JSON": json.dumps(EXEC),
        "AR_REPO_PHYSICAL": "/srv/ar-local/AR-local", "DAILY_USER": "ar-local", "DAILY_USER_UID": "1000",
        "WATCHDOG_USER_JSON": json.dumps({"type": "s", "data": "ar-local"}),
        "WATCHDOG_ACTIVE_STATE": "inactive", "WATCHDOG_SUB_STATE": "dead",
        "WATCHDOG_MAIN_PID": "0", "WATCHDOG_CONTROL_PID": "0",
    }
    value.update(changes)
    return value


def test_fixed_observer_passes_without_weakening_capture_fences():
    assert verify.pi_ingest_service_fences_ok(snapshot())


@pytest.mark.parametrize("field,value", [
    ("DAILY_START_TIMEOUT", "13h"), ("MANUAL_START_TIMEOUT", "13h"),
    ("DAILY_START_TIMEOUT", "infinity"), ("WATCHDOG_START_TIMEOUT", "6h 15min"),
    ("WATCHDOG_START_TIMEOUT", "infinity"), ("WATCHDOG_START_TIMEOUT", ""),
    ("DAILY_KILL_MODE", "process"), ("MANUAL_KILL_MODE", "process"),
    ("WATCHDOG_KILL_MODE", "process"),
])
def test_each_wrong_or_missing_fence_remains_a_failure(field, value):
    assert not verify.pi_ingest_service_fences_ok(snapshot(**{field: value}))


@pytest.mark.parametrize("change", ["legacy", "capture", "other_repo", "missing_B",
    "extra_argument", "semicolon_argument", "wrong_executable", "duplicate_command",
    "ignore_failure", "short_tuple", "wrong_type", "non_array_data", "sealed_wrapper"])
def test_short_timeout_does_not_certify_an_unknown_or_mutating_command(change):
    value = copy.deepcopy(EXEC)
    command = value["data"][0]
    if change in ("legacy", "capture", "other_repo"):
        command[1][2] = {"legacy": "/srv/ar-local/AR-local/pi_daily_watchdog.py",
                         "capture": "/srv/ar-local/AR-local/pi_daily_sync.py",
                         "other_repo": "/tmp/other/pi_ingest_observe.py"}[change]
    elif change == "missing_B":
        command[1].remove("-B")
    elif change in ("extra_argument", "semicolon_argument"):
        command[1].append("--repair" if change == "extra_argument" else "; ignore_errors=no ;")
    elif change == "wrong_executable":
        command[0] = "/bin/sh"
    elif change == "duplicate_command":
        value["data"].append(copy.deepcopy(command))
    elif change == "ignore_failure":
        command[2] = ["ignore-failure"]
    elif change == "short_tuple":
        command.pop()
    elif change == "wrong_type":
        value["type"] = "s"
    elif change == "sealed_wrapper":
        sealed = "/usr/local/lib/ar-local-ingest-observer/58f604fb19a7386a3960332d2cc94e6d51d0762e"
        command[0] = "/usr/bin/env"
        command[1] = ["/usr/bin/env", "AR_LOCAL_CODE_ROOT=" + sealed,
                      "AR_LOCAL_DATA_ROOT=/srv/ar-local/data", "/usr/bin/python3", "-B",
                      sealed + "/pi_ingest_observe.py"]
    else:
        value["data"] = {}
    assert not verify.pi_ingest_service_fences_ok(snapshot(WATCHDOG_EXEC_JSON=json.dumps(value)))


@pytest.mark.parametrize("raw", ["", "not JSON", "null", "[]", "x" * 16385])
def test_incomplete_or_oversized_typed_readback_fails_closed(raw):
    assert not verify.pi_ingest_service_fences_ok(snapshot(WATCHDOG_EXEC_JSON=raw))


def test_snapshot_transports_role_readback_and_dry_run_has_same_policy(monkeypatch):
    captured = []
    def no_ssh(script, **_kwargs):
        captured.append(script)
        return 0, "", ""
    monkeypatch.setattr(verify, "run_ssh", no_ssh)
    dry = verify.pi_remote_snapshot(dry_run=True)
    assert verify.pi_ingest_service_fences_ok(dry)
    assert "busctl --system --json=short --timeout=3 get-property" in captured[0]
    assert "org.freedesktop.systemd1.Service ExecStartEx" in captured[0]
    assert "org.freedesktop.systemd1.Service User" in captured[0]
    assert "ar_physical=$(CDPATH= cd /srv/ar-local/AR-local 2>/dev/null && pwd -P)" in captured[0]
    assert "WATCHDOG_EXEC_JSON=%s" in captured[0]


def test_shipped_watchdog_and_observer_override_share_the_sixty_second_bound():
    root = Path(__file__).resolve().parents[1]
    for name in ("ar-local-daily-watchdog.service", "ar-local-daily-watchdog-observe.conf"):
        unit = configparser.ConfigParser(strict=False, interpolation=None)
        unit.read(root / "deploy/pi" / name, encoding="utf-8")
        assert unit["Service"]["TimeoutStartSec"] == "60s"
        assert unit["Service"]["ExecStart"].endswith("/pi_ingest_observe.py")
