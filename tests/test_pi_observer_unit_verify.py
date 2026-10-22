"""Installer verification tests: no systemd mutation or network operations."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

import pi_observer_unit_verify as guard

ROOT = Path(__file__).resolve().parents[1]
SHELL = shutil.which("sh") or (r"C:\Program Files\Git\bin\sh.exe" if Path(r"C:\Program Files\Git\bin\sh.exe").is_file() else None)
REPO = "/srv/ar-local/AR-local"
USER = "ar-local"
WATCHDOG = "ar-local-daily-watchdog.service"
BOOT = "ar-local-boot-recovery.service"


def service(unit):
    argv = (["/usr/bin/python3", "-B", REPO + "/pi_ingest_observe.py"] if unit == WATCHDOG else
            ["/usr/bin/sh", REPO + "/deploy/pi/ar-local-boot-recovery.sh"])
    return {"ExecStartEx": [[argv[0], argv, [], 0, 0, 0, 0, 0, 0, 0]],
            **{name: [] for name in guard.COMMAND_PROPERTIES[1:]},
            "Environment": ["AR_LOCAL_CODE_ROOT=" + REPO, "AR_LOCAL_REPO=" + REPO],
            "UnsetEnvironment": ["AR_LOCAL_REPO"], "User": USER}


def readback(values):
    return "\n".join(json.dumps({"type": guard.COMMAND_TYPE if name.startswith("Exec") else ("s" if name == "User" else "as"),
                                 "data": values[name]}) for name in guard.PROPERTIES)


def test_readback_uses_typed_properties_without_starting_units():
    calls = []

    def run(command):
        calls.append(command)
        if command[0] == "id":
            return "1000\n"
        if command[0] == "systemctl":
            assert command[1] == "show"
            if "--value" not in command:
                return "LoadState=loaded\nActiveState=inactive\nSubState=dead\nMainPID=0\nControlPID=0\n"
            return "loaded\n"
        assert command[:5] == ["busctl", "--system", "--json=short", "--timeout=10", "get-property"]
        unit = WATCHDOG if "watchdog" in command[6] else BOOT
        return readback(service(unit))

    guard.verify(REPO, USER, run)
    assert len(calls) == 7
    assert calls[4][6] == "/org/freedesktop/systemd1/unit/ar_2dlocal_2ddaily_2dwatchdog_2eservice"
    assert "ExecStartEx" in calls[4] and "User" in calls[4]


@pytest.mark.parametrize("change", ["queue", "extra_command", "extra_argument", "ignore_failure", "hook", "code_root"])
def test_later_dropin_cannot_authorize_a_different_effective_command(change):
    values = service(WATCHDOG)
    expected = copy.deepcopy(values["ExecStartEx"][0][1])
    if change == "queue":
        values["ExecStartEx"][0][1] = ["/usr/bin/python3", REPO + "/pi_shared_queue.py", "run"]
    elif change == "extra_command":
        values["ExecStartEx"].append(copy.deepcopy(values["ExecStartEx"][0]))
    elif change == "extra_argument":
        values["ExecStartEx"][0][1].append("--repair")
    elif change == "ignore_failure":
        values["ExecStartEx"][0][2] = ["ignore-failure"]
    elif change == "hook":
        values["ExecConditionEx"] = copy.deepcopy(values["ExecStartEx"])
    else:
        values["Environment"] = ["AR_LOCAL_CODE_ROOT=/different/repository"]
    with pytest.raises(ValueError):
        guard.verify_service(WATCHDOG, expected, REPO, USER, values)


def test_boot_path_environment_must_be_unset_even_if_command_matches():
    values = service(BOOT)
    values["UnsetEnvironment"] = []
    with pytest.raises(ValueError, match="AR_LOCAL_REPO"):
        guard.verify_service(BOOT, values["ExecStartEx"][0][1], REPO, USER, values)
    dropin = (ROOT / "deploy/pi/ar-local-boot-observe.conf").read_text()
    assert "UnsetEnvironment=AR_LOCAL_REPO\n" in dropin
    assert "Environment=AR_LOCAL_CODE_ROOT={{AR_LOCAL_REPO}}\n" in dropin


@pytest.mark.parametrize("output", ["", "{}", "not JSON", '{"type":"as","data":[]}',
                                     readback(service(WATCHDOG)).replace('"a(sasasttttuii)"', '"s"', 1)])
def test_incomplete_or_unknown_bus_readback_fails_closed(output):
    with pytest.raises(ValueError):
        guard.read_service(WATCHDOG, lambda command: "loaded" if command[0] == "systemctl" else output)


@pytest.mark.parametrize("filename", ["apply-pi-runtime-units.sh", "install-pi-systemd.sh"])
def test_installer_aborts_before_activation_when_verification_fails(filename):
    shell = SHELL
    if not shell:
        pytest.skip("POSIX shell contract is exercised by Linux CI")
    text = (ROOT / "deploy/pi" / filename).read_text()
    # Execute the real post-reload installer tail, replacing sudo with a recorder.
    # No installed service, host path or package manager is ever touched.
    tail = text[text.index("sudo systemctl daemon-reload"):]
    script = """set -eu
repo_dir=/repo
run_user=ar-local
sudo() {
  printf '%s\\n' "$*"
  case "$*" in *pi_observer_unit_verify.py*) return 73;; esac
}
""" + tail
    result = subprocess.run([shell, "-c", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 73
    assert result.stdout.splitlines() == ["systemctl daemon-reload",
                                          "/usr/bin/python3 -B /repo/pi_observer_unit_verify.py /repo --user ar-local"]


def test_legacy_installer_disables_duplicate_without_starting_observer():
    shell = SHELL
    if not shell:
        pytest.skip("POSIX shell contract is exercised by Linux CI")
    text = (ROOT / "deploy/pi/install-user-daily-watchdog.sh").read_text()
    tail = text[text.index("systemctl --user daemon-reload"):]
    script = "set -eu\nsystemctl() { printf '%s\\n' \"$*\"; }\n" + tail
    result = subprocess.run([shell, "-c", script], capture_output=True, text=True, timeout=10, check=True)
    assert result.stdout.splitlines() == ["--user daemon-reload",
        "--user disable --now ar-local-daily-watchdog.timer",
        "--user list-timers --all ar-local-daily-watchdog.timer --no-pager"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX installer path semantics")
@pytest.mark.parametrize("filename", ["apply-pi-runtime-units.sh", "install-pi-systemd.sh"])
def test_installer_renders_the_same_physical_repo_path_as_verifier(tmp_path, filename):
    actual = tmp_path / "actual repository"
    actual.mkdir()
    alias = tmp_path / "repository alias"
    alias.symlink_to(actual, target_is_directory=True)
    source = (ROOT / "deploy/pi" / filename).read_text()
    assignment = next(line for line in source.splitlines() if line.startswith('repo_dir="$('))
    script = 'repo_dir="$1"\n' + assignment + '\nprintf "%s\\n" "$repo_dir"\n'
    result = subprocess.run(["sh", "-c", script, "installer-path-test", str(alias)],
                            capture_output=True, text=True, timeout=10, check=True)
    assert result.stdout.strip() == str(alias.resolve(strict=True))
