from __future__ import annotations

import ctypes
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "native" / "laptop_backup_trusted_launcher.cpp"
TRUSTED_CHILD = ROOT / "run_laptop_backup_trusted_child.ps1"
DISPATCHER = ROOT / "laptop_backup_dispatcher.py"


def windows_only() -> None:
    if sys.platform != "win32":
        pytest.skip("native trusted launcher is Windows-only")


def build(output: Path, *, testing: bool = False) -> None:
    windows_only()
    command = [
        "cl.exe",
        "/nologo",
        "/std:c++17",
        "/O2",
        "/MT",
        "/W4",
        "/WX",
        "/EHsc",
        "/GS",
        "/guard:cf",
        "/Brepro",
        "/DUNICODE",
        "/D_UNICODE",
    ]
    if testing:
        command.append("/DAR_LAUNCHER_TESTING")
    command += [
        str(SOURCE),
        f"/Fe:{output}",
        "/link",
        "advapi32.lib",
        "user32.lib",
        "/DYNAMICBASE",
        "/NXCOMPAT",
        "/guard:cf",
    ]
    subprocess.run(command, cwd=output.parent, check=True)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_sid() -> str:
    return subprocess.check_output(["whoami", "/user", "/fo", "csv", "/nh"], text=True).strip().split(",")[1].strip('"')


def protect_install(root: Path, sid: str) -> None:
    subprocess.run(["icacls", str(root), "/setowner", "*S-1-5-32-544", "/T", "/C"], check=True, capture_output=True)
    subprocess.run(["icacls", str(root), "/inheritance:r", "/grant:r", "*S-1-5-18:(OI)(CI)(F)", "*S-1-5-32-544:(OI)(CI)(F)", f"*{sid}:(OI)(CI)(RX)"], check=True, capture_output=True)
    for path in root.iterdir():
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", "*S-1-5-18:(F)", "*S-1-5-32-544:(F)", f"*{sid}:(RX)"], check=True, capture_output=True)


def test_source_has_no_general_command_channel() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    assert "system(" not in text
    assert "ShellExecute" not in text
    assert "CreateProcessWithTokenW" in text
    assert "CreateRestrictedToken" in text
    assert "LUA_TOKEN" not in text
    assert "DOMAIN_ALIAS_RID_ADMINS" in text
    assert "TokenHasRestrictions" in text
    assert "CreateWindowStationW" in text
    assert "CreateDesktopW" in text
    assert "S:(ML;;NW;;;ME)" in text
    assert "startup.lpDesktop = private_desktop.startup_name()" in text
    assert "require_write_denied(token, root, true)" in text
    assert "--restricted-child" in text


def test_trusted_child_requires_protected_code_and_controlled_tools() -> None:
    child = TRUSTED_CHILD.read_text(encoding="utf-8")
    dispatcher = DISPATCHER.read_text(encoding="utf-8")
    assert "$config.schema_version -ne 2" in child
    assert "Assert-ArTrustedWithinRoot $python" in child
    assert "Assert-ArTrustedWithinRoot $dispatcher" in child
    assert "Assert-ArTrustedWithinRoot $atomic" in child
    assert "Assert-ArTrustedWriteDenied $tool.Path" in child
    assert "$env:PATH =" in child
    assert "$env:AR_TRUSTED_ROOT = $trustedRoot" in child
    assert 'os.environ.get("AR_TRUSTED_ROOT")' in dispatcher


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only reproducible build")
def test_production_build_is_reproducible(tmp_path: Path) -> None:
    first = tmp_path / "first.exe"
    second = tmp_path / "second.exe"
    build(first)
    build(second)
    assert sha256(first) == sha256(second)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only token integration")
def test_elevated_origin_produces_restricted_child() -> None:
    if not ctypes.windll.shell32.IsUserAnAdmin():
        pytest.skip("integration requires the elevated Windows CI token")
    install = Path(os.environ["ProgramFiles"]) / f"AR-local-launcher-test-{uuid.uuid4().hex}"
    install.mkdir()
    try:
        launcher = install / "launcher-test.exe"
        build(launcher, testing=True)
        (install / "operator.sid").write_text(current_sid(), encoding="ascii", newline="")
        (install / "protected.sentinel").write_bytes(b"AR-local trusted launcher sentinel\n")
        (install / "run_laptop_backup_trusted_child.ps1").write_text("exit 0\n", encoding="ascii", newline="")
        (install / "trusted-child.json").write_text("{}\n", encoding="ascii", newline="")
        (install / "probe.enabled").write_bytes(b"PROBE")
        protect_install(install, current_sid())
        result = subprocess.run([str(launcher), "--probe"], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
    finally:
        shutil.rmtree(install, ignore_errors=False)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only command rejection")
def test_production_binary_rejects_operator_command(tmp_path: Path) -> None:
    launcher = tmp_path / "launcher.exe"
    build(launcher)
    result = subprocess.run([str(launcher), "cmd.exe", "/c", "exit", "0"], capture_output=True, text=True, check=False)
    assert result.returncode == 64
    assert "accepts no operator-supplied command" in result.stderr
