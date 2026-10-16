"""03:00 is conditional on current-day whole-run and validation clearance."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shlex
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import pi_daily_repair_admission as admission
import pi_cdr_recovery as recovery
import pi_payload_retry_policy as publication

NOW = datetime.fromisoformat("2026-10-16T03:00:00+11:00")
MONO = 10000.0


def terminal_units():
    values = {name: {"LoadState": "loaded", "ActiveState": "inactive", "MainPID": "0", "ControlPID": "0",
        "ControlGroup": "", "Result": "success", "ExecMainStatus": "0",
        "ExecMainStartTimestampMonotonic": "2000000000", "ExecMainExitTimestampMonotonic": "5000000000",
        "InactiveEnterTimestampMonotonic": "8000000000", "automatic_validation_contract_verified": True}
        for name in admission.INGEST_UNITS}
    return values


def test_current_day_terminal_ingest_followed_by_validation():
    assert admission.validate_terminal(terminal_units(), NOW, MONO) == ""


@pytest.mark.parametrize("unit,key,value", [
    (name, key, value) for name in admission.INGEST_UNITS
    for key, value in [("LoadState", "not-found"), ("ActiveState", "activating"), ("MainPID", "12"), ("ControlPID", "13")]
] + [(admission.INGEST_UNITS[0], "ExecMainStartTimestampMonotonic", "-1"),
     (admission.INGEST_UNITS[0], "ExecMainExitTimestampMonotonic", "11000000000"),
     (admission.INGEST_UNITS[0], "InactiveEnterTimestampMonotonic", "4000000000"),
     (admission.INGEST_UNITS[0], "InactiveEnterTimestampMonotonic", ""),
     (admission.INGEST_UNITS[0], "Result", "timeout"), (admission.INGEST_UNITS[0], "ExecMainStatus", "1"),
     (admission.INGEST_UNITS[0], "automatic_validation_contract_verified", False)])
def test_active_ambiguous_stale_or_failed_validation_refuses(unit, key, value):
    values = terminal_units()
    values[unit][key] = value
    assert admission.validate_terminal(values, NOW, MONO)


def test_previous_date_terminal_evidence_cannot_admit_today():
    assert admission.validate_terminal(terminal_units(), NOW + timedelta(days=1), MONO + 86400)


@pytest.mark.parametrize("date", ["2026-10-16", "2027-04-04", "2027-10-03"])
@pytest.mark.parametrize("clock,allowed", [("02:59", False), ("03:00", True), ("03:29", True), ("04:59", True), ("05:00", False)])
def test_hobart_window_has_two_hour_width_across_dst(date, clock, allowed):
    if date == "2027-10-03" and clock == "02:59":
        # This local minute does not exist: Hobart jumps from 01:59 to 03:00.
        value = datetime.fromisoformat("2027-10-02T15:59:00+00:00")
        assert not admission.daily_window(value)
        assert admission.daily_window(value + timedelta(minutes=1))
        return
    value = datetime.fromisoformat(date + "T" + clock).replace(tzinfo=admission.HOBART)
    assert admission.daily_window(value.astimezone(timezone.utc)) is allowed


def claim_fixture(tmp_path):
    claims = tmp_path / "claims"
    claims.mkdir()
    receipt = claims / "2026-10-16.json"
    invocation = "a" * 32
    value = {"date": "2026-10-16", "started_at": NOW.isoformat(), "invocation": invocation,
        "max_total_seconds": 1200, "status": "claimed_no_retry"}
    receipt.write_text(json.dumps(value))
    cgroup = tmp_path / "cgroup"
    cgroup.write_text("0::/system.slice/" + admission.UNIT + "\n")
    environ = {"INVOCATION_ID": invocation, "AR_LOCAL_DAILY_REPAIR_RECEIPT": str(receipt)}
    return claims, receipt, value, cgroup, environ


def test_exact_claimed_service_is_required_and_expiry_is_not_renewed(tmp_path):
    claims, receipt, value, cgroup, environ = claim_fixture(tmp_path)
    def check(now=NOW):
        return admission.claimed_service(now, environ=environ, cgroup_path=cgroup, claims=claims)
    assert check()
    assert not check(NOW - timedelta(seconds=1))
    assert not check(NOW + timedelta(seconds=1200))
    cgroup.write_text("0::/system.slice/manual-job.service\n")
    assert not check()


@pytest.mark.parametrize("key,value", [("date", "2026-10-15"), ("invocation", "b" * 32),
    ("started_at", "2026-10-16T03:00:00"), ("max_total_seconds", 99999), ("status", "finished")])
def test_wrong_or_ambiguous_claim_refuses(tmp_path, key, value):
    claims, receipt, claim, cgroup, environ = claim_fixture(tmp_path)
    claim[key] = value
    receipt.write_text(json.dumps(claim))
    assert not admission.claimed_service(NOW, environ=environ, cgroup_path=cgroup, claims=claims)


@pytest.mark.parametrize("claimed,clear,allowed", [(False, "", False), (True, "natural_cgroup_has_processes", False), (True, "", True)])
def test_both_legacy_policies_only_open_early_for_verified_daily_context(monkeypatch, claimed, clear, allowed):
    monkeypatch.setattr(admission, "claimed_service", lambda now: claimed)
    monkeypatch.setattr(admission, "natural_clearance", lambda *a, **k: clear)
    assert recovery.recovery_window(NOW) is allowed
    assert (publication.payload_retry_window_reason(NOW) == "") is allowed
    for clock in ["00:30", "02:59", "22:00"]:
        assert not recovery.recovery_window(datetime.fromisoformat("2026-10-16T" + clock + ":00+11:00"))
    assert recovery.recovery_window(NOW + timedelta(minutes=30))


def test_unclaimed_daily_pass_cannot_trigger_network_or_capture_at_three(monkeypatch, tmp_path):
    monkeypatch.setattr(admission, "claimed_service", lambda now: False)
    launch = Mock()
    result = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, daily_pass=True, launch=launch)
    assert result["status"] == "outside_recovery_window"
    launch.assert_not_called()


def test_lease_presence_and_unavailable_unit_metadata_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(admission, "data_state_root", lambda _: tmp_path)
    lock = tmp_path / "daily-ingest.lock"
    lock.write_text("ambiguous retained owner")
    assert admission.natural_clearance(tmp_path, NOW) == "natural_ingest_lease_present"
    lock.unlink()
    monkeypatch.setattr(admission.subprocess, "run", Mock(side_effect=OSError("unavailable")))
    assert admission.natural_clearance(tmp_path, NOW) == "natural_terminal_state_unavailable"


@pytest.mark.parametrize("change,allowed", [("none", True), ("ignore_errors", False),
    ("different_command", False), ("different_source", False), ("duplicate", False), ("malformed", False),
    ("short_circuit", False), ("no_op", False), ("commented", False), ("unexecuted", False),
    ("previous_run", False), ("reversed_exit", False), ("late_exit", False), ("signal", False),
    ("failed_exit", False), ("string_timestamp", False), ("boolean_timestamp", False),
    ("short_row", False), ("non_list_row", False), ("non_list_argv", False), ("non_string_argv", False)])
def test_non_optional_exact_post_start_validation_is_bound(tmp_path, monkeypatch, change, allowed):
    import hashlib
    verifier = tmp_path / "verify_local.py"
    verifier.write_text("authentic test verifier source")
    monkeypatch.setattr(admission, "VALIDATOR", verifier)
    monkeypatch.setattr(admission, "VALIDATOR_SHA256", hashlib.sha256(verifier.read_bytes()).hexdigest())
    # Bind the positive control to the deployed unit template, independently
    # of the admission implementation's expected command.
    unit = Path(__file__).resolve().parents[1] / "deploy/pi/ar-local-daily.service"
    line = next(line for line in unit.read_text().splitlines() if line.startswith("ExecStartPost=/bin/sh"))
    command = shlex.split(line.split("=", 1)[1])[2].replace("{{AR_LOCAL_REPO}}", str(tmp_path)).replace("%%", "%")
    row = ["/bin/sh", ["/bin/sh", "-c", command], False, 1, 6000000000, 2, 7000000000, 123, 1, 0]
    value = {"type": "a(sasbttttuii)", "data": [row]}
    if change == "ignore_errors": row[2] = True
    if change == "different_command": row[1][2] += " || true"
    if change == "different_source": verifier.write_text("changed verifier source")
    if change == "duplicate": value["data"].append(deepcopy(row))
    if change == "malformed": value = {"type": "string", "data": []}
    if change == "short_circuit": row[1][2] = "false && " + command
    if change == "no_op": row[1][2] = ": " + command
    if change == "commented": row[1][2] = "true # " + command
    if change == "unexecuted": row[4] = row[6] = row[8] = 0
    if change == "previous_run": row[4], row[6] = 3000000000, 4000000000
    if change == "reversed_exit": row[6] = row[4] - 1
    if change == "late_exit": row[6] = 9000000000
    if change == "signal": row[8] = 2
    if change == "failed_exit": row[9] = 1
    if change == "string_timestamp": row[4] = str(row[4])
    if change == "boolean_timestamp": row[4] = True
    if change == "short_row": value["data"].append([])
    if change == "non_list_row": value["data"].append(None)
    if change == "non_list_argv": row[1] = {"command": command}
    if change == "non_string_argv": row[1][2] = None
    monkeypatch.setattr(admission.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=json.dumps(value)))
    assert admission.validation_installed(terminal_units()[admission.INGEST_UNITS[0]]) is allowed


@pytest.mark.parametrize("state,reason", [("missing", ""), ("empty", ""),
    ("live_descendant", "natural_cgroup_has_processes"),
    ("membership_missing", "natural_cgroup_membership_unverified"),
    ("wrong_group", "natural_cgroup_identity_unverified")])
def test_inactive_main_does_not_hide_surviving_or_ambiguous_cgroup(tmp_path, monkeypatch, state, reason):
    units = terminal_units()
    group = tmp_path / "cgroups/system.slice" / admission.INGEST_UNITS[0]
    if state not in {"missing", "wrong_group"}:
        group.mkdir(parents=True)
    if state in {"empty", "live_descendant"}:
        (group / "cgroup.procs").write_text("")
    if state == "live_descendant":
        child = group / "orphan"
        child.mkdir()
        (child / "cgroup.procs").write_text("123\n")
    if state == "wrong_group":
        units[admission.INGEST_UNITS[0]]["ControlGroup"] = "/unverified/other.service"
    def run(command, **kwargs):
        return SimpleNamespace(stdout="\n".join(key + "=" + str(value) for key, value in units[command[2]].items()))
    monkeypatch.setattr(admission.subprocess, "run", run)
    monkeypatch.setattr(admission, "validation_installed", lambda daily: True)
    monkeypatch.setattr(admission, "data_state_root", lambda _: tmp_path / "state")
    monkeypatch.setattr(admission.time, "monotonic", lambda: MONO)
    assert admission.natural_clearance(tmp_path, NOW, cgroup_root=tmp_path / "cgroups") == reason


def test_cgroup_membership_limit_bounds_discovery_before_reading_entries(tmp_path, monkeypatch):
    group = tmp_path / "system.slice" / admission.INGEST_UNITS[0]
    group.mkdir(parents=True)
    units = terminal_units()
    def run(command, **kwargs):
        return SimpleNamespace(stdout="\n".join(key + "=" + str(value) for key, value in units[command[2]].items()))
    def entries(path, pattern):
        assert path == group and pattern == "cgroup.procs"
        for _ in range(257):
            yield group / "cgroup.procs"
        raise AssertionError("cgroup traversal exceeded its fail-closed entry limit")
    monkeypatch.setattr(admission.subprocess, "run", run)
    monkeypatch.setattr(admission, "data_state_root", lambda _: tmp_path / "state")
    monkeypatch.setattr(Path, "rglob", entries)
    assert admission.natural_clearance(tmp_path, NOW, cgroup_root=tmp_path) == "natural_cgroup_membership_unverified"
