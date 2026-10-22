"""Only exact producer profiles can use their corresponding startup budgets."""
import configparser
import copy
import json
from pathlib import Path
import shlex

import pytest

import pi_deploy_service_snapshot as service
from tests.pi_ingest_service_fixtures import REPO, command_json, ingest_definition_fields

ROOT = Path(__file__).resolve().parents[1]


def snapshot(*, queued=False):
    return {
        **ingest_definition_fields(queued=queued),
        "AR_REPO_PHYSICAL": REPO, "DAILY_USER": "ar-local", "DAILY_USER_UID": "1000",
        "WATCHDOG_KILL_MODE": "control-group", "WATCHDOG_START_TIMEOUT": "1min",
        "WATCHDOG_EXEC_JSON": command_json(["/usr/bin/python3", "-B", REPO + "/pi_ingest_observe.py"]),
        "WATCHDOG_USER_JSON": json.dumps({"type": "s", "data": "ar-local"}),
        "WATCHDOG_ACTIVE_STATE": "inactive", "WATCHDOG_SUB_STATE": "dead",
        "WATCHDOG_MAIN_PID": "0", "WATCHDOG_CONTROL_PID": "0",
    }


@pytest.mark.parametrize("queued", [False, True])
def test_exact_direct_and_commissioned_queued_profiles_pass(queued):
    assert service.pi_ingest_service_fences_ok(snapshot(queued=queued))


@pytest.mark.parametrize("manual", [False, True])
def test_profile_control_argv_and_deadlines_match_checked_in_templates(manual):
    prefix = "MANUAL" if manual else "DAILY"
    stem = "ingest-now" if manual else "daily"
    for queued in (False, True):
        name = "shared-queue-" + stem + ".conf" if queued else "ar-local-" + stem + ".service"
        parser = configparser.ConfigParser(strict=False, interpolation=None)
        parser.read(ROOT / "deploy/pi" / name, encoding="utf-8")
        unit = parser["Service"]
        expected = shlex.split(unit["ExecStart"].replace("{{AR_LOCAL_REPO}}", REPO))
        fields = ingest_definition_fields(queued=queued)
        assert json.loads(fields[prefix + "_EXEC_JSON"])["data"][0][1] == expected
        assert unit["TimeoutStartSec"] == ("46800s" if queued else "6h15min")
        assert unit["TimeoutStopSec"] == ("900s" if queued else "45s")
        if queued:
            assert json.loads(fields[prefix + "_STOP_POST_JSON"])["data"][0][1] == shlex.split(unit["ExecStopPost"])
        else:
            assert unit["ExecStopPost"].startswith("+/usr/bin/systemctl ")
            command = json.loads(fields[prefix + "_STOP_POST_JSON"])["data"][0]
            assert command[1] == shlex.split(unit["ExecStopPost"][1:])
            assert command[2] == ["privileged"]


@pytest.mark.parametrize("prefix", ["DAILY", "MANUAL"])
@pytest.mark.parametrize("queued,field,value", [
    (False, "START_TIMEOUT", "13h"), (True, "START_TIMEOUT", "6h 15min"),
    (True, "START_TIMEOUT", "14h"), (True, "START_TIMEOUT", "infinity"),
    (False, "STOP_TIMEOUT", "15min"), (True, "STOP_TIMEOUT", "45s"),
    (True, "STOP_TIMEOUT", "16min"), (True, "STOP_TIMEOUT", "infinity"),
    (True, "TYPE", "simple"), (True, "RESTART", "always"),
    (True, "KILL_MODE", "process"), (True, "SEND_SIGKILL", "no"),
])
def test_command_role_never_borrows_another_profiles_budget(prefix, queued, field, value):
    current = snapshot(queued=queued)
    current[prefix + "_" + field] = value
    assert not service.pi_ingest_service_fences_ok(current)


@pytest.mark.parametrize("prefix", ["DAILY", "MANUAL"])
@pytest.mark.parametrize("change", ["executable", "queue_path", "action", "project", "resource", "mode",
    "slots", "wait", "runtime", "producer_python", "producer_root", "producer_script", "force", "extra", "state_dir"])
def test_queued_profile_requires_exact_resource_budgets_and_producer(prefix, change):
    current = snapshot(queued=True)
    command = json.loads(current[prefix + "_EXEC_JSON"])
    argv = command["data"][0][1]
    replacements = {
        "executable": (0, "/bin/sh"), "queue_path": (1, "/tmp/pi_shared_queue.py"), "action": (2, "status"),
        "project": (4, "other"), "resource": (6, "host"), "mode": (8, "shared"), "slots": (10, "4"),
        "wait": (12, "43200"), "runtime": (14, "43200"), "producer_python": (16, "/usr/bin/env"),
        "producer_root": (17, "/tmp/other/pi_daily_sync.py"), "producer_script": (17, REPO + "/pi_daily_watchdog.py"),
    }
    if change in replacements:
        index, value = replacements[change]
        argv[index] = value
    elif change == "force":
        argv.remove("--force") if "--force" in argv else argv.append("--force")
    elif change == "extra":
        argv.append("; /usr/bin/other")
    else:
        argv[2:2] = ["--state-dir", "/tmp/unreviewed"]
    current[prefix + "_EXEC_JSON"] = json.dumps(command)
    assert not service.pi_ingest_service_fences_ok(current)


@pytest.mark.parametrize("prefix", ["DAILY", "MANUAL"])
@pytest.mark.parametrize("queued", [False, True])
@pytest.mark.parametrize("change", ["flags", "ignore", "duplicate", "legacy", "short", "wrong_executable", "bool_timestamp", "negative_timestamp"])
def test_definition_commands_require_native_exact_unprivileged_tuples(prefix, queued, change):
    current = snapshot(queued=queued)
    command = json.loads(current[prefix + "_EXEC_JSON"])
    row = command["data"][0]
    if change == "flags": row[2] = ["fully-privileged"]
    elif change == "ignore": row[2] = ["ignore-failure"]
    elif change == "duplicate": command["data"].append(copy.deepcopy(row))
    elif change == "legacy": command["type"] = "a(sasbttttuii)"; row[2] = False
    elif change == "short": row.pop()
    elif change == "wrong_executable": row[0] = "/usr/bin/env"
    elif change == "bool_timestamp": row[3] = True
    else: row[3] = -1
    current[prefix + "_EXEC_JSON"] = json.dumps(command)
    assert not service.pi_ingest_service_fences_ok(current)


@pytest.mark.parametrize("prefix", ["DAILY", "MANUAL"])
@pytest.mark.parametrize("change", ["empty", "missing", "different", "extra", "flags", "duplicate"])
def test_queued_claim_preserving_stop_hook_is_exact(prefix, change):
    current = snapshot(queued=True)
    name = prefix + "_STOP_POST_JSON"
    command = json.loads(current[name])
    row = command["data"][0]
    if change == "missing": current.pop(name)
    else:
        if change == "empty": command["data"] = []
        elif change == "different": row[1][1] = "/tmp/unreviewed_stop.py"
        elif change == "extra": row[1].append("--clear-claims")
        elif change == "flags": row[2] = ["fully-privileged"]
        else: command["data"].append(copy.deepcopy(row))
        current[name] = json.dumps(command)
    assert not service.pi_ingest_service_fences_ok(current)


@pytest.mark.parametrize("prefix", ["DAILY", "MANUAL"])
@pytest.mark.parametrize("change", ["empty", "missing", "different", "extra", "no_flag", "ignore", "unknown_flag", "extra_flag", "duplicate"])
def test_direct_cleanup_has_only_the_explicit_checked_in_privileged_exception(prefix, change):
    current = snapshot()
    name = prefix + "_STOP_POST_JSON"
    command = json.loads(current[name])
    row = command["data"][0]
    if change == "missing": current.pop(name)
    else:
        if change == "empty": command["data"] = []
        elif change == "different": row[1][2] = "other.service"
        elif change == "extra": row[1].append("--no-block")
        elif change == "no_flag": row[2] = []
        elif change == "ignore": row[2] = ["ignore-failure"]
        elif change == "unknown_flag": row[2] = ["fully-privileged"]
        elif change == "extra_flag": row[2].append("ignore-failure")
        else: command["data"].append(copy.deepcopy(row))
        current[name] = json.dumps(command)
    assert not service.pi_ingest_service_fences_ok(current)


@pytest.mark.parametrize("prefix", ["DAILY", "MANUAL"])
@pytest.mark.parametrize("field", ["EXEC_JSON", "USER_JSON", "TYPE", "RESTART", "SEND_SIGKILL", "STOP_TIMEOUT", "START_TIMEOUT", "KILL_MODE"])
def test_missing_real_definition_evidence_is_never_synthesized(prefix, field):
    current = snapshot(queued=True)
    current.pop(prefix + "_" + field)
    assert not service.pi_ingest_service_fences_ok(current)


@pytest.mark.parametrize("queued", [False, True])
@pytest.mark.parametrize("field,value", [
    ("DAILY_USER", "root"), ("DAILY_USER_UID", "0"), ("DAILY_USER_UID", ""),
    ("MANUAL_USER_JSON", '{"type":"s","data":"other"}'),
    ("DAILY_USER_JSON", '{"type":"s","data":"other"}'),
    ("AR_REPO_PHYSICAL", "/tmp/other"), ("AR_REPO_PHYSICAL", "/srv/ar-local/link/../AR-local"),
])
def test_common_nonroot_user_and_physical_producer_binding_cannot_drift(queued, field, value):
    current = snapshot(queued=queued)
    current[field] = value
    assert not service.pi_ingest_service_fences_ok(current)


@pytest.mark.parametrize("queued", [False, True])
@pytest.mark.parametrize("prefix", ["DAILY", "MANUAL"])
@pytest.mark.parametrize("field", ["EXEC_JSON", "STOP_POST_JSON", "USER_JSON"])
@pytest.mark.parametrize("raw", ["", "not JSON", "null", "[]", "x" * 16385])
def test_incomplete_or_oversized_native_property_is_a_failure(queued, prefix, field, raw):
    current = snapshot(queued=queued)
    current[prefix + "_" + field] = raw
    assert not service.pi_ingest_service_fences_ok(current)


@pytest.mark.parametrize("prefix,unit", [("OTHER", "ar-local-daily.service"),
    ("DAILY", "ar-local-daily.service; other"), ("MANUAL", "ar-local-daily.service")])
def test_native_definition_query_never_expands_the_unit_allowlist(prefix, unit):
    with pytest.raises(ValueError, match="unknown ingest"):
        service._ingest_definition_script(prefix, unit)


@pytest.mark.parametrize("queued", [False, True])
def test_not_started_and_recorded_execution_timestamps_are_definition_evidence(queued):
    current = snapshot(queued=queued)
    for prefix in ("DAILY", "MANUAL"):
        value = json.loads(current[prefix + "_EXEC_JSON"])
        value["data"][0][3:] = [1792634904300408, 229711396097, 1792634908039996, 229715135685, 508747, 1, 0]
        current[prefix + "_EXEC_JSON"] = json.dumps(value)
    assert service.pi_ingest_service_fences_ok(current)


def test_snapshot_queries_real_native_definitions_and_no_missing_field_fallback():
    script = service._snapshot_script(REPO, "/site", "/data", "origin")
    for prefix, encoded in (("DAILY", "daily"), ("MANUAL", "ingest_2dnow")):
        assert "/org/freedesktop/systemd1/unit/ar_2dlocal_2d" + encoded + "_2eservice" in script
        for field in ("EXEC_JSON", "STOP_POST_JSON", "USER_JSON", "TYPE", "RESTART", "SEND_SIGKILL", "STOP_TIMEOUT"):
            assert prefix + "_" + field + "=%s" in script
    assert "org.freedesktop.systemd1.Service ExecStopPostEx" in script
    actual = snapshot(queued=True)
    actual.pop("MANUAL_EXEC_JSON")
    actual.update(AR_HEAD="a", AR_ORIGIN="a", SITE_HEAD="b", SITE_ORIGIN="b", DASHBOARD="active")
    returned = service.remote_snapshot(ar=REPO, site="/site", data="/data", remote="origin",
        run=lambda *_args, **_kwargs: (0, "CONTROL", ""), parse=lambda _body: actual)
    assert "MANUAL_EXEC_JSON" not in returned
    assert not service.pi_ingest_service_fences_ok(returned)
