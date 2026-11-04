"""Capture and replay the kernel's supported FAT mount metadata semantics."""
import os
import re
import stat
from pathlib import Path


def fat_mount(path, mountinfo):
    found = []
    for line in mountinfo.splitlines():
        left, right = line.split(" - ", 1)
        fields, filesystem = left.split(), right.split()
        if fields[4] == str(path):
            if filesystem[0] != "vfat":
                raise ValueError("boot source must be the inventoried FAT filesystem")
            found.append(filesystem[2].split(","))
    if len(found) != 1:
        raise ValueError("exact boot source mount must be independently visible")
    values = {key: value for option in found[0] if "=" in option for key, value in [option.split("=", 1)]}
    result = {"fstype": "vfat", "uid": values.get("uid", "0"), "gid": values.get("gid", "0"),
              "fmask": values["fmask"], "dmask": values["dmask"]}
    for key in ("shortname", "codepage", "iocharset", "utf8", "time_offset", "tz"):
        if key in values:
            result[key] = values[key]
    if "utf8" in found[0]:
        result["utf8"] = "1"
    if "showexec" in found[0]:
        raise ValueError("showexec boot mount requires separately reviewed filename-specific metadata support")
    fat_options(result)
    return result


def fat_options(settings):
    if settings.get("fstype") != "vfat" or set(settings) - {"fstype", "uid", "gid", "fmask", "dmask", "shortname", "codepage", "iocharset", "utf8", "time_offset", "tz"}:
        raise ValueError("unsupported boot mount options")
    if any(not re.fullmatch(r"[0-9]+", str(settings[name])) for name in ("uid", "gid")):
        raise ValueError("invalid FAT ownership")
    if any(not re.fullmatch(r"[0-7]{4}", settings[name]) for name in ("fmask", "dmask")):
        raise ValueError("explicit source FAT masks required")
    if any(not re.fullmatch(r"[A-Za-z0-9_.+-]+", str(value)) for key, value in settings.items() if key != "fstype"):
        raise ValueError("invalid FAT option value")
    return [key + "=" + str(value) for key, value in settings.items() if key != "fstype"]


def source_fat(path):
    settings = fat_mount(path, Path("/proc/self/mountinfo").read_text())
    info = os.stat(path)
    if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (int(settings["uid"]), int(settings["gid"]), 0o777 & ~int(settings["dmask"], 8)):
        raise ValueError("source FAT stat metadata differs from its kernel mount options")
    return settings
