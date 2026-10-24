"""Fixed plaintext-backup stop-hook contract; separate from ingest hooks.

Only root-owned, bounded authority/terminal records are trusted. A recognizable
name alone never approves launch or releases a retained native/queue claim.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess

PLAIN = re.compile(r"ar-local-plain-backup-([0-9a-f]{32})\.service\Z")
ROOT = Path("/usr/local/lib/ar-local-plain-backup")
HANDOFF = Path("/var/lib/ar-local-plain-backup-handoff")
BROKER = str(ROOT / "broker.py")


def retained_stop(unit):
    return isinstance(unit, str) and PLAIN.fullmatch(unit) is not None


def pairs(rows):
    value = {}
    for key, item in rows:
        if key in value:
            raise ValueError("duplicate structured field")
        value[key] = item
    return value


def root_json(path, maximum=65536):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError("noncanonical root authority")
    for item in (path, *path.parents):
        info = item.lstat()
        if info.st_uid != 0 or stat.S_ISLNK(info.st_mode) or info.st_mode & 0o022:
            raise ValueError("untrusted root authority")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > maximum:
        raise ValueError("invalid bounded root authority")
    data = path.read_bytes()
    after = path.stat()
    if len(data) > maximum or (info.st_ino, info.st_dev, info.st_size, info.st_mtime_ns) != (
            after.st_ino, after.st_dev, after.st_size, after.st_mtime_ns):
        raise ValueError("root authority changed during read")
    value = json.loads(data, object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise ValueError("root authority object required")
    return value


def approval(unit, *, current=False, now=None):
    match = PLAIN.fullmatch(unit or "")
    if not match:
        raise ValueError("not a retained plaintext backup service")
    value = root_json(HANDOFF / match[1] / "approval.json")
    expiry = datetime.fromisoformat(value["expires_at"])
    if (value.get("schema") != "ar-local-plain-backup-authority-v1"
            or value.get("nonce") != match[1] or value.get("unit") != unit
            or value.get("manual_plaintext_drive_write") is not True
            or value.get("data_root") != "/srv/ar-local/data"
            or expiry.utcoffset() != timezone.utc.utcoffset(expiry)
            or any(not re.fullmatch("[0-9a-f]{64}", str(value.get(key, ""))) for key in
                   ("source_closure_sha256", "parent_sha256", "resources_sha256", "broker_sha256", "queue_argv_sha256"))):
        raise ValueError("plaintext backup approval differs")
    if current and expiry <= (now or datetime.now(timezone.utc)):
        raise ValueError("plaintext backup authority expired")
    return value


def _native(unit, prop, run):
    encoded = "".join(char if char.isalnum() else f"_{ord(char):02x}" for char in unit)
    result = run(["/usr/bin/busctl", "--system", "--json=short", "--timeout=10", "get-property",
        "org.freedesktop.systemd1", "/org/freedesktop/systemd1/unit/" + encoded,
        "org.freedesktop.systemd1.Service", prop], text=True, capture_output=True, timeout=10, check=True)
    value = json.loads(result.stdout, object_pairs_hook=pairs)
    if value.get("type") != "a(sasasttttuii)" or not isinstance(value.get("data"), list):
        raise ValueError("native execution evidence unavailable")
    return value["data"]


def verify_plain_service(unit, run=subprocess.run):
    value = approval(unit, current=True)
    start, stop = _native(unit, "ExecStartEx", run), _native(unit, "ExecStopPostEx", run)
    expected = ["/usr/bin/python3", "-I", "-B", BROKER, "recover", value["nonce"]]
    if (len(start) != 1 or len(start[0]) != 10 or start[0][2] != []
            or hashlib.sha256(json.dumps(start[0][1], separators=(",", ":")).encode()).hexdigest() != value["queue_argv_sha256"]
            or len(stop) != 1 or len(stop[0]) != 10 or stop[0][:3] != [expected[0], expected, ["privileged"]]):
        raise ValueError("root-created fixed backup commands differ")
    for prop in ("ExecConditionEx", "ExecStartPreEx", "ExecStartPostEx", "ExecStopEx"):
        if _native(unit, prop, run):
            raise ValueError("unexpected plaintext service hook")
    return value


def completion_proved(job):
    """Caller must additionally prove the whole invocation/cgroup has ended."""
    if not retained_stop(job.get("unit")):
        return False
    try:
        authority = approval(job["unit"])
        value = root_json(HANDOFF / authority["nonce"] / "completion.json")
        return (value.get("schema") == "ar-local-plain-backup-root-completion-v1"
            and value.get("nonce") == authority["nonce"] and value.get("unit") == job["unit"]
            and value.get("job_id") == job["id"] and value.get("invocation") == job["invocation_id"]
            and value.get("boot_id") == job["boot_id"] and value.get("owner_pid") == job["pid"]
            and value.get("owner_ticks") == job["start_ticks"] and value.get("readback") == 60
            and value.get("result") in ("RESTORED", "NOT_ACQUIRED")
            and value.get("untrusted_processes_gone") is True and value.get("credential_quarantined") is True)
    except (OSError, KeyError, TypeError, ValueError):
        return False
