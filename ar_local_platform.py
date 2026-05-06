"""Detect host platform for AR-local launchers (Windows, Raspberry Pi, other Linux)."""

from __future__ import annotations

import platform
from enum import Enum
from pathlib import Path


class HostKind(Enum):
    WINDOWS = "windows"
    RASPBERRY_PI = "raspberry_pi"
    LINUX_OTHER = "linux_other"
    OTHER = "other"


def _read_device_tree_model() -> str:
    p = Path("/proc/device-tree/model")
    if not p.is_file():
        return ""
    try:
        raw = p.read_bytes()
    except OSError:
        return ""
    return raw.decode("utf-8", errors="replace").strip().strip("\x00")


def host_kind() -> HostKind:
    sys_name = platform.system()
    if sys_name == "Windows":
        return HostKind.WINDOWS
    if sys_name == "Linux":
        model = _read_device_tree_model().lower()
        if "raspberry pi" in model:
            return HostKind.RASPBERRY_PI
        machine = platform.machine().lower()
        if machine in ("armv7l", "armv6l", "aarch64") and model:
            if "raspberry" in model:
                return HostKind.RASPBERRY_PI
        return HostKind.LINUX_OTHER
    return HostKind.OTHER


def platform_label() -> str:
    kind = host_kind()
    if kind == HostKind.WINDOWS:
        return "Windows PC"
    if kind == HostKind.RASPBERRY_PI:
        model = _read_device_tree_model().strip()
        return f"Raspberry Pi ({model})" if model else "Raspberry Pi"
    if kind == HostKind.LINUX_OTHER:
        return "Linux (other)"
    return platform.system()
