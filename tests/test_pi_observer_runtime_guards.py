"""Late-review regressions using native-control literals and local shell stubs."""
import copy
import json
from pathlib import Path
import subprocess

import pytest

import pi_deploy_verify as deploy
import pi_observer_unit_contract as contract
import pi_observer_unit_verify as guard
from tests.test_deploy_watchdog_observer_role import snapshot
from tests.test_pi_observer_unit_verify import BOOT, REPO, SHELL, USER, WATCHDOG, service

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("unit", [WATCHDOG, BOOT])
@pytest.mark.parametrize("flag", ["privileged", "no-setuid", "ambient-magic", "ignore-failure", "no-env-expand", "unknown"])
def test_modifiers_never_preserve_the_service_user_contract(unit, flag):
    values = service(unit)
    values["ExecStartEx"][0][2] = [flag]
    with pytest.raises(ValueError, match="ExecStart"):
        guard.verify_service(unit, values["ExecStartEx"][0][1], REPO, USER, values)


@pytest.mark.parametrize("user", ["root", "", "0", "another-service", None])
def test_exact_expected_service_user_is_required(user):
    values = service(WATCHDOG)
    values["User"] = user
    with pytest.raises(ValueError, match="service user"):
        guard.verify_service(WATCHDOG, values["ExecStartEx"][0][1], REPO, USER, values)


def test_matching_root_user_is_still_not_an_unprivileged_contract():
    values = service(WATCHDOG)
    values["User"] = "root"
    with pytest.raises(ValueError, match="service user"):
        guard.verify_service(WATCHDOG, values["ExecStartEx"][0][1], REPO, "root", values)


@pytest.mark.parametrize("user,uid", [("root", "0"), (USER, "0"), (USER, "unknown"),
                                    (USER, "4294967295"), ("--help", "1000"), (USER, "١٠٠٠")])
def test_expected_user_must_resolve_to_a_real_nonroot_uid(user, uid):
    calls = []
    with pytest.raises(ValueError, match="non-root"):
        guard.verify(REPO, user, lambda argv: calls.append(argv) or uid)
    assert all(argv[0] == "id" for argv in calls)


@pytest.mark.parametrize("signature,flags", [("a(sasbttttuii)", False), (contract.COMMAND_TYPE, False),
                                          (contract.COMMAND_TYPE, None)])
def test_legacy_or_malformed_modifier_readback_cannot_certify_privileges(signature, flags):
    value = snapshot()
    command = json.loads(value["WATCHDOG_EXEC_JSON"])
    command["type"] = signature
    command["data"][0][2] = flags
    value["WATCHDOG_EXEC_JSON"] = json.dumps(command)
    assert not deploy.pi_ingest_service_fences_ok(value)


@pytest.mark.parametrize("field,value", [("DAILY_USER_UID", "0"), ("DAILY_USER", "root"),
    ("WATCHDOG_USER_JSON", '{"type":"s","data":"root"}'),
    ("WATCHDOG_USER_JSON", '{"type":"as","data":["ar-local"]}'),
    ("WATCHDOG_USER_JSON", ""), ("WATCHDOG_ACTIVE_STATE", "active"),
    ("WATCHDOG_ACTIVE_STATE", "activating"), ("WATCHDOG_SUB_STATE", "exited"),
    ("WATCHDOG_MAIN_PID", "123"), ("WATCHDOG_CONTROL_PID", "456"),
    ("AR_REPO_PHYSICAL", ""), ("AR_REPO_PHYSICAL", "relative/repo"),
    ("AR_REPO_PHYSICAL", "/srv/link/../repo")])
def test_deploy_never_certifies_missing_identity_or_an_old_active_invocation(field, value):
    assert not deploy.pi_ingest_service_fences_ok(snapshot(**{field: value}))


@pytest.mark.parametrize("changes", [{"ActiveState": "active"}, {"ActiveState": "activating"},
    {"ActiveState": "deactivating"}, {"SubState": "start"}, {"MainPID": "123"},
    {"ControlPID": "456"}, {"LoadState": "error"}])
def test_idle_preflight_defers_without_any_mutation(changes):
    row = {"LoadState": "loaded", "ActiveState": "inactive", "SubState": "dead", "MainPID": "0", "ControlPID": "0"}
    row.update(changes)
    calls = []
    with pytest.raises(guard.ObserverBusy):
        guard.verify_idle(lambda argv: calls.append(argv) or "\n".join(key+"="+value for key, value in row.items()))
    assert len(calls) == 1 and calls[0][:2] == ["systemctl", "show"]


@pytest.mark.parametrize("raw", ["", "ActiveState=inactive", "malformed",
    "LoadState=loaded\nActiveState=inactive\nSubState=dead\nMainPID=0\nMainPID=0\nControlPID=0"])
def test_unknown_idle_evidence_fails_closed(raw):
    with pytest.raises((guard.ObserverBusy, ValueError)):
        guard.verify_idle(lambda _argv: raw)


def test_busy_cli_returns_defer_status_without_stopping_an_observer(monkeypatch):
    def busy():
        raise guard.ObserverBusy("operational-control: active")
    monkeypatch.setattr(guard, "verify_idle", busy)
    assert guard.main(["--idle-only"]) == 75


def test_idle_cli_success_receipt_does_not_claim_command_or_user_verification(monkeypatch, capsys):
    monkeypatch.setattr(guard, "verify_idle", lambda: None)
    monkeypatch.setattr(guard, "verify", lambda *_args: pytest.fail("idle-only must not verify commands or user"))
    assert guard.main(["--idle-only"]) == 0
    output = capsys.readouterr().out
    assert output == "Watchdog and boot observer idle metadata verified; no units started.\n"
    assert "commands verified" not in output and "users verified" not in output


def test_remote_physical_path_matches_symlinked_installer_readback(monkeypatch):
    value = snapshot(AR_HEAD="1"*40, AR_ORIGIN="1"*40, SITE_HEAD="2"*40, SITE_ORIGIN="2"*40, DASHBOARD="active")
    commands = []
    monkeypatch.setattr(deploy, "pi_ar_repo", lambda: "/srv/alias to checkout")
    monkeypatch.setattr(deploy, "run_ssh", lambda command, **_kwargs: (
        commands.append(command) or 0, "\n".join(key+"="+data for key, data in value.items()), ""))
    result = deploy.pi_remote_snapshot()
    assert "cd '/srv/alias to checkout' 2>/dev/null && pwd -P" in commands[0]
    assert result["AR_REPO_PHYSICAL"] == REPO
    assert deploy.pi_ingest_service_fences_ok(result)
    changed = copy.deepcopy(result)
    changed["AR_REPO_PHYSICAL"] = "/another/physical/repository"
    assert not deploy.pi_ingest_service_fences_ok(changed)


@pytest.mark.skipif(not SHELL, reason="local POSIX shell fixture unavailable")
@pytest.mark.parametrize("filename", ["apply-pi-runtime-units.sh", "install-pi-systemd.sh"])
@pytest.mark.parametrize("phase", ["before_reload", "after_reload"])
def test_installer_defer_before_or_after_reload_never_enables_old_invocation(filename, phase):
    source = (ROOT/"deploy/pi"/filename).read_text()
    idle = 'sudo /usr/bin/python3 -B "$repo_dir/pi_observer_unit_verify.py" --idle-only'
    first = source.index("--idle-only")
    assert first < source.index("sudo install")
    if filename == "install-pi-systemd.sh":
        assert first < source.index("sudo apt-get")
    tail = source[source.rindex(idle):]
    script = '''set -eu
repo_dir=/reviewed
run_user=ar-local
sudo() {
  printf '%s\n' "$*"
  case "$*" in
    *--idle-only*) [ "$phase" != before_reload ] || return 75;;
    *pi_observer_unit_verify.py*) [ "$phase" != after_reload ] || return 75;;
  esac
}
''' + 'phase='+phase+'\n' + tail
    result = subprocess.run([SHELL, "-c", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 75
    lines = result.stdout.splitlines()
    assert not any("enable" in line or "restart" in line or "stop " in line for line in lines)
    expected = ["/usr/bin/python3 -B /reviewed/pi_observer_unit_verify.py --idle-only"]
    if phase == "after_reload":
        expected += ["systemctl daemon-reload", "/usr/bin/python3 -B /reviewed/pi_observer_unit_verify.py /reviewed --user ar-local"]
    assert lines == expected
