from __future__ import annotations

import json
import ctypes
import os
import subprocess
import sys
from pathlib import Path

import pytest

import laptop_backup_restricted_process as restricted


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "laptop_backup_restricted_process.py"


def windows_only() -> None:
    if os.name != "nt":
        pytest.skip("restricted process integration is Windows-only")


def elevated_windows() -> bool:
    return os.name == "nt" and bool(ctypes.windll.shell32.IsUserAnAdmin())


def test_cli_requires_explicit_command_boundary() -> None:
    with pytest.raises(SystemExit, match="usage"):
        restricted.main([sys.executable])


@pytest.mark.skipif(not elevated_windows(), reason="requires elevated Windows CI token")
def test_real_elevated_parent_is_quarantined() -> None:
    with pytest.raises(RuntimeError, match="protected native launcher"):
        restricted.run_restricted([sys.executable, "-c", "raise SystemExit(0)"])


@pytest.mark.skipif(elevated_windows(), reason="PR581 elevated-parent route is quarantined")
def test_real_restricted_child_propagates_streams_and_exit() -> None:
    windows_only()
    command = [
        sys.executable,
        str(LAUNCHER),
        "--",
        sys.executable,
        "-c",
        "import sys;print('child-out');print('child-error',file=sys.stderr);raise SystemExit(7)",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 7
    assert result.stdout == "child-out\n"
    assert result.stderr == "child-error\n"


@pytest.mark.skipif(elevated_windows(), reason="PR581 elevated-parent route is quarantined")
def test_real_restricted_child_is_limited(tmp_path: Path) -> None:
    windows_only()
    child = tmp_path / "child.py"
    output = tmp_path / "token.json"
    child.write_text(
        """import ctypes,json,subprocess,sys
from ctypes import wintypes
a=ctypes.WinDLL('advapi32',use_last_error=True);k=ctypes.WinDLL('kernel32',use_last_error=True)
a.OpenProcessToken.argtypes=[wintypes.HANDLE,wintypes.DWORD,ctypes.POINTER(wintypes.HANDLE)];a.OpenProcessToken.restype=wintypes.BOOL
a.GetTokenInformation.argtypes=[wintypes.HANDLE,ctypes.c_int,wintypes.LPVOID,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)];a.GetTokenInformation.restype=wintypes.BOOL
k.GetCurrentProcess.restype=wintypes.HANDLE
t=wintypes.HANDLE();assert a.OpenProcessToken(k.GetCurrentProcess(),8,ctypes.byref(t))
def value(c):
 v=wintypes.DWORD();n=wintypes.DWORD();assert a.GetTokenInformation(t,c,ctypes.byref(v),ctypes.sizeof(v),ctypes.byref(n));return v.value
data={'admin':bool(ctypes.windll.shell32.IsUserAnAdmin()),'elevation_type':value(18),'elevation':value(20),'privileges':subprocess.check_output(['whoami','/priv','/fo','csv','/nh'],text=True)}
open(sys.argv[1],'x',encoding='utf-8',newline='\\n').write(json.dumps(data,sort_keys=True)+'\\n')
""",
        encoding="utf-8",
        newline="",
    )
    result = subprocess.run(
        [sys.executable, str(LAUNCHER), "--", sys.executable, str(child), str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["admin"] is False
    assert data["elevation"] == 0
    assert data["elevation_type"] != restricted.TOKEN_ELEVATION_TYPE_FULL
    assert "SeChangeNotifyPrivilege" in data["privileges"]
    assert "SeDebugPrivilege" not in data["privileges"]


class FakeApi:
    def __init__(self, *, fail_create: bool = False) -> None:
        self.fail_create = fail_create
        self.closed: list[int] = []
        self.command: list[str] | None = None

    def restricted_token(self) -> int:
        return 101

    def create_process(self, token: int, command: list[str], startup: object) -> restricted.ProcessInformation:
        assert token == 101
        self.command = list(command)
        if self.fail_create:
            raise OSError("synthetic create failure")
        process = restricted.ProcessInformation()
        process.hProcess = 202
        process.hThread = 303
        return process

    def wait(self, process: int) -> int:
        assert process == 202
        return 19

    def close(self, handle: int) -> None:
        self.closed.append(int(handle))


def test_fake_api_preserves_arguments_exit_and_closes_handles() -> None:
    windows_only()
    api = FakeApi()
    command = [sys.executable, "argument with spaces", 'quoted"argument']
    assert restricted.run_restricted(command, api=api) == 19
    assert api.command == command
    assert api.closed == [303, 202, 101]


def test_fake_api_closes_token_when_process_creation_fails() -> None:
    windows_only()
    api = FakeApi(fail_create=True)
    with pytest.raises(OSError, match="synthetic create failure"):
        restricted.run_restricted([sys.executable], api=api)
    assert api.closed == [101]
