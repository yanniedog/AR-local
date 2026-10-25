"""Canonical laptop backup target path checks (local volume only)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

# Cloud / virtual roots are not authorized D-004 receivers (Drive write hold).
_CLOUD_VOLUME_LABEL_MARKERS = (
    "google drive",
    "google drive stream",
    "onedrive",
    "dropbox",
    "icloud",
)
_CLOUD_FILESYSTEM_MARKERS = (
    "fuse",
    "9p",
    "cifs",
    "smb",
    "nfs",
    "davfs",
    "sshfs",
)
# Path-segment markers for cloud-synced trees that live on ordinary NTFS volumes.
_CLOUD_PATH_MARKERS = (
    "google drive",
    "google drive stream",
    "\\googledrivefs\\",
    "/googledrivefs/",
    "onedrive",
    "dropbox",
    "icloud drive",
    "iclouddrive",
)
# Win32 GetDriveTypeW: DRIVE_REMOTE = network share / mapped SMB.
_DRIVE_REMOTE = 4


def _is_unc_path(path: Path) -> bool:
    text = str(path)
    if text.startswith("\\\\") or text.startswith("//"):
        return True
    upper = text.upper()
    return upper.startswith("\\\\?\\UNC\\") or upper.startswith("//?/UNC/")


def _windows_drive_type(path: Path) -> int | None:
    try:
        import ctypes

        root = str(path.anchor or path)
        drive = root if root.endswith("\\") else root + "\\"
        return int(ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(drive)))
    except (AttributeError, OSError, ValueError, TypeError):
        return None


def existing_ancestor(path: Path) -> Path:
    """Nearest existing ancestor (or the path itself) for volume probes before mkdir."""
    current = path.expanduser()
    while True:
        try:
            if current.exists():
                return current
        except OSError:
            pass
        parent = current.parent
        if parent == current:
            return current
        current = parent


def volume_probe(path: Path) -> dict[str, str]:
    """Best-effort local volume identity for refuse-cloud checks (Windows + POSIX)."""
    label = ""
    filesystem = ""
    root = str(path.anchor or path)
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            GetVolumeInformationW = ctypes.windll.kernel32.GetVolumeInformationW
            volume_name = ctypes.create_unicode_buffer(261)
            fs_name = ctypes.create_unicode_buffer(261)
            serial = wintypes.DWORD()
            max_comp = wintypes.DWORD()
            flags = wintypes.DWORD()
            drive = root if root.endswith("\\") else root + "\\"
            ok = GetVolumeInformationW(
                ctypes.c_wchar_p(drive),
                volume_name,
                len(volume_name),
                ctypes.byref(serial),
                ctypes.byref(max_comp),
                ctypes.byref(flags),
                fs_name,
                len(fs_name),
            )
            if ok:
                label = volume_name.value or ""
                filesystem = fs_name.value or ""
        except (AttributeError, OSError, ValueError):
            pass
    else:
        try:
            target = path.resolve()
            with open("/proc/mounts", encoding="utf-8") as handle:
                matches: list[tuple[int, str]] = []
                for line in handle:
                    parts = line.split()
                    if len(parts) < 3:
                        continue
                    mountpoint, fstype = parts[1], parts[2]
                    try:
                        mount_path = Path(mountpoint).resolve()
                    except OSError:
                        continue
                    try:
                        target.relative_to(mount_path)
                    except ValueError:
                        continue
                    matches.append((len(mount_path.parts), fstype))
                if matches:
                    filesystem = sorted(matches, reverse=True)[0][1]
        except OSError:
            pass
    return {"root": root, "label": label, "filesystem": filesystem}


def refuse_cloud_backup_root(path: Path, probe: Mapping[str, str] | None = None) -> None:
    """Reject cloud/virtual/network roots; local NTFS/exFAT/ext4 targets remain allowed."""
    if _is_unc_path(path):
        raise ValueError(f"backup target must not be a UNC/network path ({path})")
    folded = str(path).casefold().replace("/", "\\")
    for marker in _CLOUD_PATH_MARKERS:
        if marker.replace("/", "\\") in folded:
            raise ValueError(f"backup target path is a cloud-synced directory ({path})")
    identity = dict(probe) if probe is not None else volume_probe(path)
    drive_type_raw = str(identity.get("drive_type", "")).strip()
    if drive_type_raw.isdigit() and int(drive_type_raw) == _DRIVE_REMOTE:
        raise ValueError(f"backup target is a remote/network drive ({path})")
    elif probe is None and os.name == "nt":
        drive_type = _windows_drive_type(path)
        if drive_type == _DRIVE_REMOTE:
            raise ValueError(f"backup target is a remote/network drive ({path})")
    label = str(identity.get("label", "")).casefold()
    filesystem = str(identity.get("filesystem", "")).casefold()
    for marker in _CLOUD_VOLUME_LABEL_MARKERS:
        if marker in label:
            raise ValueError(
                f"backup target volume label is a cloud/virtual root ({identity.get('label')})"
            )
    for marker in _CLOUD_FILESYSTEM_MARKERS:
        if marker in filesystem:
            raise ValueError(
                f"backup target filesystem is remote/virtual ({identity.get('filesystem')})"
            )


def canonical_target(value: Path) -> Path:
    configured = value.expanduser()
    if not configured.is_absolute() or configured.is_symlink():
        raise ValueError("backup target must be an absolute non-symlink path")
    # Probe existing ancestor and refuse before mkdir so cloud/UNC roots never get dirs created.
    ancestor = existing_ancestor(configured)
    refuse_cloud_backup_root(configured, probe=volume_probe(ancestor))
    configured.mkdir(parents=True, exist_ok=True)
    resolved = configured.resolve(strict=True)
    if configured != resolved or not resolved.is_dir() or resolved.anchor == str(resolved):
        raise ValueError("backup target must be a canonical directory below a volume root")
    refuse_cloud_backup_root(resolved)
    return resolved
