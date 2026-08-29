"""Cross-platform process liveness and ancestry checks without signals on Windows."""

from __future__ import annotations

import os
from pathlib import Path


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32))
        kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            exit_code = ctypes.c_uint32()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and (
                exit_code.value == 259
            )
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def process_descends_from(pid: int, ancestor_pid: int, *, max_depth: int = 12) -> bool:
    if pid <= 0 or ancestor_pid <= 0:
        return False
    if pid == ancestor_pid:
        return process_alive(pid)
    parents: dict[int, int] = {}
    if os.name == "nt":
        parents = _windows_parent_map()
    else:
        current = pid
        for _ in range(max_depth):
            try:
                fields = Path(f"/proc/{current}/stat").read_text(encoding="utf-8").split()
                parents[current] = int(fields[3])
                current = parents[current]
            except (OSError, ValueError, IndexError):
                break
    current = pid
    for _ in range(max_depth):
        current = parents.get(current, 0)
        if current == ancestor_pid:
            return process_alive(ancestor_pid)
        if current <= 0:
            return False
    return False


def _windows_parent_map() -> dict[int, int]:
    import ctypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_uint32), ("cntUsage", ctypes.c_uint32),
            ("th32ProcessID", ctypes.c_uint32), ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", ctypes.c_uint32), ("cntThreads", ctypes.c_uint32),
            ("th32ParentProcessID", ctypes.c_uint32), ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_uint32), ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = (ctypes.c_uint32, ctypes.c_uint32)
    kernel.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel.Process32FirstW.argtypes = (ctypes.c_void_p, ctypes.POINTER(ProcessEntry))
    kernel.Process32NextW.argtypes = (ctypes.c_void_p, ctypes.POINTER(ProcessEntry))
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    snapshot = kernel.CreateToolhelp32Snapshot(0x2, 0)
    if snapshot in (None, ctypes.c_void_p(-1).value):
        return {}
    parents: dict[int, int] = {}
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(ProcessEntry)
        more = bool(kernel.Process32FirstW(snapshot, ctypes.byref(entry)))
        while more:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            more = bool(kernel.Process32NextW(snapshot, ctypes.byref(entry)))
    finally:
        kernel.CloseHandle(snapshot)
    return parents
