"""Installer verification tests: no systemd mutation or network operations."""
import copy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

import pi_observer_unit_verify as guard

ROOT = Path(__file__).resolve().parents[1]
REPO = "/srv/ar-local/AR-local"
WATCHDOG = "ar-local-daily-watchdog.service"
BOOT = "ar-local-boot-recovery.service"


def service(unit):
    argv = (["/usr/bin/python3", "-B", REPO + "/pi_ingest_observe.py"] if unit == WATCHDOG else
            ["/usr/bin/sh", REPO + "/deploy/pi/ar-local-boot-recovery.sh"])
    return {"ExecStart": [[argv[0], argv, False, 0, 0, 0, 0, 0, 0, 0]],
            **{name: [] for name in guard.COMMAND_PROPERTIES[1:]},
            "Environment": ["AR_LOCAL_CODE_ROOT=" + REPO, "AR_LOCAL_REPO=" + REPO],
            "UnsetEnvironment": ["AR_LOCAL_REPO"]}


def readback(values):
    return "\n".join(json.dumps({"type": guard.COMMAND_TYPE if name.startswith("Exec") else "as",
                                 "data": values[name]}) for name in guard.PROPERTIES)


def test_readback_uses_typed_properties_without_starting_units():
    calls = []

    def run(command):
        calls.append(command)
        if command[0] == "systemctl":
            assert command[1] == "show"
            return "loaded\n"
        assert command[:5] == ["busctl", "--system", "--json=short", "--timeout=10", "get-property"]
        unit = WATCHDOG if "watchdog" in command[6] else BOOT
        return readback(service(unit))

    guard.verify(REPO, run)
    assert len(calls) == 4
    assert calls[1][6] == "/org/freedesktop/systemd1/unit/ar_2dlocal_2ddaily_2dwatchdog_2eservice"


@pytest.mark.parametrize("change", ["queue", "extra_command", "extra_argument", "ignore_failure", "hook", "code_root"])
def test_later_dropin_cannot_authorize_a_different_effective_command(change):
    values = service(WATCHDOG)
    expected = copy.deepcopy(values["ExecStart"][0][1])
    if change == "queue":
        values["ExecStart"][0][1] = ["/usr/bin/python3", REPO + "/pi_shared_queue.py", "run"]
    elif change == "extra_command":
        values["ExecStart"].append(copy.deepcopy(values["ExecStart"][0]))
    elif change == "extra_argument":
        values["ExecStart"][0][1].append("--repair")
    elif change == "ignore_failure":
        values["ExecStart"][0][2] = True
    elif change == "hook":
        values["ExecCondition"] = copy.deepcopy(values["ExecStart"])
    else:
        values["Environment"] = ["AR_LOCAL_CODE_ROOT=/different/repository"]
    with pytest.raises(ValueError):
        guard.verify_service(WATCHDOG, expected, REPO, values)


def test_boot_path_environment_must_be_unset_even_if_command_matches():
    values = service(BOOT)
    values["UnsetEnvironment"] = []
    with pytest.raises(ValueError, match="AR_LOCAL_REPO"):
        guard.verify_service(BOOT, values["ExecStart"][0][1], REPO, values)
    dropin = (ROOT / "deploy/pi/ar-local-boot-observe.conf").read_text()
    assert "UnsetEnvironment=AR_LOCAL_REPO\n" in dropin
    assert "Environment=AR_LOCAL_CODE_ROOT={{AR_LOCAL_REPO}}\n" in dropin


@pytest.mark.parametrize("output", ["", "{}", "not JSON", '{"type":"as","data":[]}',
                                     readback(service(WATCHDOG)).replace('"a(sasbttttuii)"', '"s"', 1)])
def test_incomplete_or_unknown_bus_readback_fails_closed(output):
    with pytest.raises(ValueError):
        guard.read_service(WATCHDOG, lambda command: "loaded" if command[0] == "systemctl" else output)


@pytest.mark.parametrize("filename", ["apply-pi-runtime-units.sh", "install-pi-systemd.sh"])
def test_installer_aborts_before_activation_when_verification_fails(filename):
    shell = shutil.which("sh")
    if not shell:
        pytest.skip("POSIX shell contract is exercised by Linux CI")
    text = (ROOT / "deploy/pi" / filename).read_text()
    # Execute the real post-reload installer tail, replacing sudo with a recorder.
    # No installed service, host path or package manager is ever touched.
    tail = text[text.index("sudo systemctl daemon-reload"):]
    script = """set -eu
repo_dir=/repo
sudo() {
  printf '%s\\n' "$*"
  case "$*" in *pi_observer_unit_verify.py*) return 73;; esac
}
""" + tail
    result = subprocess.run([shell, "-c", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 73
    assert result.stdout.splitlines() == ["systemctl daemon-reload",
                                          "/usr/bin/python3 -B /repo/pi_observer_unit_verify.py /repo"]


def test_legacy_installer_disables_duplicate_without_starting_observer():
    shell = shutil.which("sh")
    if not shell:
        pytest.skip("POSIX shell contract is exercised by Linux CI")
    text = (ROOT / "deploy/pi/install-user-daily-watchdog.sh").read_text()
    tail = text[text.index("systemctl --user daemon-reload"):]
    script = "set -eu\nsystemctl() { printf '%s\\n' \"$*\"; }\n" + tail
    result = subprocess.run([shell, "-c", script], capture_output=True, text=True, timeout=10, check=True)
    assert result.stdout.splitlines() == ["--user daemon-reload",
        "--user disable --now ar-local-daily-watchdog.timer",
        "--user list-timers --all ar-local-daily-watchdog.timer --no-pager"]
