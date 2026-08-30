"""Launch one Windows child with normal-user rights and propagate its result.

The scheduled backup task can yield an administrator-enabled S4U token even
when its XML says ``LeastPrivilege``.  This launcher derives a restricted token
with the Windows SAFER API before Python loads the backup dispatcher.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile
from ctypes import wintypes
from typing import Sequence

if sys.platform == "win32":
    import msvcrt
else:  # pragma: no cover - the launcher refuses non-Windows execution
    msvcrt = None  # type: ignore[assignment]


SAFER_SCOPEID_USER = 2
SAFER_LEVELID_NORMALUSER = 0x20000
SAFER_LEVEL_OPEN = 1
CREATE_NO_WINDOW = 0x08000000
STARTF_USESTDHANDLES = 0x00000100
WAIT_OBJECT_0 = 0
INFINITE = 0xFFFFFFFF
TOKEN_ELEVATION_TYPE = 18
TOKEN_ELEVATION = 20
TOKEN_ELEVATION_TYPE_FULL = 2
WIN_BUILTIN_ADMINISTRATORS_SID = 26
SECURITY_IMPERSONATION = 2


class StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class WindowsSaferApi:
    def __init__(self) -> None:
        self.advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._declare()

    def _declare(self) -> None:
        self.advapi.SaferCreateLevel.argtypes = [
            wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE), wintypes.LPVOID,
        ]
        self.advapi.SaferCreateLevel.restype = wintypes.BOOL
        self.advapi.SaferComputeTokenFromLevel.argtypes = [
            wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.HANDLE),
            wintypes.DWORD, wintypes.LPVOID,
        ]
        self.advapi.SaferComputeTokenFromLevel.restype = wintypes.BOOL
        self.advapi.SaferCloseLevel.argtypes = [wintypes.HANDLE]
        self.advapi.SaferCloseLevel.restype = wintypes.BOOL
        self.advapi.DuplicateToken.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.POINTER(wintypes.HANDLE),
        ]
        self.advapi.DuplicateToken.restype = wintypes.BOOL
        self.advapi.CreateWellKnownSid.argtypes = [
            ctypes.c_int, wintypes.LPVOID, wintypes.LPVOID,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.advapi.CreateWellKnownSid.restype = wintypes.BOOL
        self.advapi.CheckTokenMembership.argtypes = [
            wintypes.HANDLE, wintypes.LPVOID, ctypes.POINTER(wintypes.BOOL),
        ]
        self.advapi.CheckTokenMembership.restype = wintypes.BOOL
        self.advapi.GetTokenInformation.argtypes = [
            wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.advapi.GetTokenInformation.restype = wintypes.BOOL
        self.advapi.CreateProcessAsUserW.argtypes = [
            wintypes.HANDLE, wintypes.LPCWSTR, wintypes.LPWSTR,
            wintypes.LPVOID, wintypes.LPVOID, wintypes.BOOL, wintypes.DWORD,
            wintypes.LPVOID, wintypes.LPCWSTR, ctypes.POINTER(StartupInfo),
            ctypes.POINTER(ProcessInformation),
        ]
        self.advapi.CreateProcessAsUserW.restype = wintypes.BOOL
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD),
        ]
        self.kernel.GetExitCodeProcess.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL

    @staticmethod
    def _error(label: str) -> OSError:
        return ctypes.WinError(ctypes.get_last_error(), label)

    def restricted_token(self) -> wintypes.HANDLE:
        level = wintypes.HANDLE()
        if not self.advapi.SaferCreateLevel(
            SAFER_SCOPEID_USER, SAFER_LEVELID_NORMALUSER, SAFER_LEVEL_OPEN,
            ctypes.byref(level), None,
        ):
            raise self._error("SaferCreateLevel")
        try:
            token = wintypes.HANDLE()
            if not self.advapi.SaferComputeTokenFromLevel(
                level, None, ctypes.byref(token), 0, None,
            ):
                raise self._error("SaferComputeTokenFromLevel")
        finally:
            self.advapi.SaferCloseLevel(level)
        try:
            if self.token_value(token, TOKEN_ELEVATION) != 0:
                raise RuntimeError("SAFER child token is elevated")
            if self.token_value(token, TOKEN_ELEVATION_TYPE) == TOKEN_ELEVATION_TYPE_FULL:
                raise RuntimeError("SAFER child token has full elevation type")
            if self.admin_enabled(token):
                raise RuntimeError("SAFER child token retains administrator membership")
        except Exception:
            self.close(token)
            raise
        return token

    def admin_enabled(self, token: wintypes.HANDLE) -> bool:
        impersonation = wintypes.HANDLE()
        if not self.advapi.DuplicateToken(token, SECURITY_IMPERSONATION, ctypes.byref(impersonation)):
            raise self._error("DuplicateToken")
        try:
            size = wintypes.DWORD(68)
            sid = ctypes.create_string_buffer(size.value)
            if not self.advapi.CreateWellKnownSid(
                WIN_BUILTIN_ADMINISTRATORS_SID, None, sid, ctypes.byref(size),
            ):
                raise self._error("CreateWellKnownSid")
            member = wintypes.BOOL()
            if not self.advapi.CheckTokenMembership(
                impersonation, ctypes.cast(sid, wintypes.LPVOID), ctypes.byref(member),
            ):
                raise self._error("CheckTokenMembership")
            return bool(member.value)
        finally:
            self.close(impersonation)

    def token_value(self, token: wintypes.HANDLE, info_class: int) -> int:
        value = wintypes.DWORD()
        returned = wintypes.DWORD()
        if not self.advapi.GetTokenInformation(
            token, info_class, ctypes.byref(value), ctypes.sizeof(value),
            ctypes.byref(returned),
        ):
            raise self._error("GetTokenInformation")
        return int(value.value)

    def create_process(
        self,
        token: wintypes.HANDLE,
        command: Sequence[str],
        startup: StartupInfo,
    ) -> ProcessInformation:
        command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
        process = ProcessInformation()
        if not self.advapi.CreateProcessAsUserW(
            token, command[0], command_line, None, None, True,
            CREATE_NO_WINDOW, None, None, ctypes.byref(startup),
            ctypes.byref(process),
        ):
            raise self._error("CreateProcessAsUserW")
        return process

    def wait(self, process: wintypes.HANDLE) -> int:
        if self.kernel.WaitForSingleObject(process, INFINITE) != WAIT_OBJECT_0:
            raise self._error("WaitForSingleObject")
        code = wintypes.DWORD()
        if not self.kernel.GetExitCodeProcess(process, ctypes.byref(code)):
            raise self._error("GetExitCodeProcess")
        return int(code.value)

    def close(self, handle: wintypes.HANDLE) -> None:
        if handle:
            self.kernel.CloseHandle(handle)


def _handle(stream: object) -> int:
    if msvcrt is None:
        raise RuntimeError("Windows handle conversion is unavailable")
    return int(msvcrt.get_osfhandle(stream.fileno()))  # type: ignore[attr-defined]


def run_restricted(command: Sequence[str], api: WindowsSaferApi | None = None) -> int:
    if sys.platform != "win32":
        raise RuntimeError("restricted backup child launching is Windows-only")
    if not command or not os.path.isabs(command[0]) or not os.path.isfile(command[0]):
        raise ValueError("restricted child executable must be an existing absolute file")
    if api is None and bool(ctypes.windll.shell32.IsUserAnAdmin()):
        raise RuntimeError(
            "elevated SAFER backup launching is quarantined; use the protected native launcher"
        )
    api = api or WindowsSaferApi()
    token = api.restricted_token()
    try:
        with open(os.devnull, "rb") as child_input, tempfile.TemporaryFile() as child_output, tempfile.TemporaryFile() as child_error:
            streams = (child_input, child_output, child_error)
            for stream in streams:
                os.set_handle_inheritable(_handle(stream), True)
            startup = StartupInfo()
            startup.cb = ctypes.sizeof(startup)
            startup.dwFlags = STARTF_USESTDHANDLES
            startup.hStdInput = _handle(child_input)
            startup.hStdOutput = _handle(child_output)
            startup.hStdError = _handle(child_error)
            try:
                process = api.create_process(token, command, startup)
            finally:
                for stream in streams:
                    os.set_handle_inheritable(_handle(stream), False)
            try:
                code = api.wait(process.hProcess)
            finally:
                api.close(process.hThread)
                api.close(process.hProcess)
            child_output.seek(0)
            child_error.seek(0)
            sys.stdout.buffer.write(child_output.read())
            sys.stderr.buffer.write(child_error.read())
            return code
    finally:
        api.close(token)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) < 2 or arguments[0] != "--":
        raise SystemExit("usage: laptop_backup_restricted_process.py -- COMMAND [ARG ...]")
    return run_restricted(arguments[1:])


if __name__ == "__main__":
    raise SystemExit(main())
