"""Derive a fixed, readonly upload view; never export duplicate OS tar layers."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat

from pi_system_capture import sha
from pi_system_drive_transport import METADATA

ROOT = Path("/usr/local/lib/ar-local-system-recovery")
WORK = Path("/var/lib/ar-local-system-recovery")
EXPORT = Path("/var/lib/ar-local-system-recovery-export")
UPLOAD = Path("/var/lib/ar-local-system-recovery-upload")
TOOLS = {"pi_system_image_restore.py", "pi_system_sparse.py", "pi_system_raw_restore.py", "pi_system_image.py",
         "pi_system_capture.py", "pi_system_filesystems.py", "pi_system_image_rejoin.py", "pi_system_image_rejoin_launch.py", "pi_system_namespace.py",
         "pi_plain_backup_restore.py", "pi_drive_backup_manifest.py", "pi_laptop_backup_source.py"}


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def plan_for(workspace_id):
    if not re.fullmatch(r"[a-f0-9]{32}", workspace_id):
        raise ValueError("fixed image workspace identity required")
    work = WORK / workspace_id
    recovery = json.loads((work / "recovery-set.json").read_text())
    checksum = sha(work / "recovery-set.json")
    image = json.loads((work / "image-result.json").read_text())
    capture = json.loads((work / "capture.json").read_text())
    if (recovery["result"] != "IMAGE_AND_FILESYSTEM_VERIFIED" or image["result"] != "FILESYSTEM_RESTORE_VERIFIED"
            or image.get("filesystem_check", {}).get("result") != "PASS" or image.get("cleanup_errors")
            or recovery["image_result_sha256"] != sha(work / "image-result.json")
            or image["capture_sha256"] != sha(work / "capture.json")
            or capture["external_restore_map_sha256"] != sha(work / "external-restore-map.jsonl")
            or recovery["catalog_sha256"] != capture["settings"]["external_recovery"]["catalog_sha256"]):
        raise ValueError("fully verified fixed image/capture identity required for export")
    for tree in ("root", "boot"):
        if capture["trees"][tree]["manifest"]["sha256"] != sha(work / (tree + ".manifest.jsonl")):
            raise ValueError("full filesystem metadata manifest changed")
    if capture["source_observations"]["sha256"] != sha(work / "source-observations.jsonl"):
        raise ValueError("source observation windows changed")
    prefix, objects = "system-images/sets/" + checksum + "/", []
    def add(name, path, target, expected=None):
        info = path.lstat()
        if path.resolve() != path or not stat.S_ISREG(info.st_mode) or info.st_uid != 0:
            raise ValueError("root-owned canonical derived image object required")
        digest = sha(path)
        if expected is not None and digest != expected:
            raise ValueError("verified image object changed before export")
        objects.append({"source": name, "path": prefix + target.format(sha=digest), "sha256": digest, "bytes": info.st_size})
    offset = 0
    for number, part in enumerate(recovery["compressed_parts"], 1):
        name = f"recovery.img.part{number:06d}.zst"
        if part["path"] != name or part["offset"] != offset or not 0 < part["length"] <= 1024 ** 3:
            raise ValueError("ordered complete image frame catalog required")
        add(name, work / name, "frames/" + name, part["sha256"])
        offset += part["length"]
    if offset != recovery["image_bytes"]:
        raise ValueError("image frame coverage is incomplete")
    for name in sorted(METADATA):
        add(name, work / name, "metadata/{sha}" + Path(name).suffix)
    add("recovery-set.json", work / "recovery-set.json", "recovery-set.json", checksum)
    for name in sorted(TOOLS):
        add("tools/" + name, ROOT / name, "tools/{sha}.py")
    return {"schema": "ar-local-system-image-upload-plan-v1", "recovery_set_sha256": checksum,
            "raw_catalog_sha256": recovery["catalog_sha256"], "raw_restore_required": recovery["raw_restore_required"], "objects": objects}


def prepare_export(packet):
    plan = plan_for(packet["workspace_id"])
    if hashlib.sha256(encoded(plan)).hexdigest() != packet["upload_plan_sha256"]:
        raise ValueError("independently sealed image upload plan differs")
    export, scratch = EXPORT / packet["nonce"], UPLOAD / packet["nonce"]
    export.mkdir(mode=0o750)
    os.chmod(export, 0o750)
    os.chown(export, 0, packet["gid"])
    (export / "tools").mkdir(mode=0o750)
    os.chmod(export / "tools", 0o750)
    os.chown(export / "tools", 0, packet["gid"])
    scratch.mkdir(mode=0o700)
    os.chmod(scratch, 0o700)
    os.chown(scratch, packet["uid"], packet["gid"])
    for row in plan["objects"]:
        name = row["source"]
        source = ROOT / Path(name).name if name.startswith("tools/") else WORK / packet["workspace_id"] / name
        target = export / name
        if name.startswith("recovery.img.part"):
            os.link(source, target, follow_symlinks=False)  # Only derived immutable compressed bytes; no duplicate payload allocation.
        else:
            with source.open("rb") as original, target.open("xb") as destination:
                shutil.copyfileobj(original, destination, 1024 * 1024)
                destination.flush()
                os.fsync(destination.fileno())
        os.chown(target, 0, packet["gid"])
        os.chmod(target, 0o440)
        if sha(target) != row["sha256"]:
            raise ValueError("readonly image export copy differs")
    path = export / "upload-plan.json"
    with path.open("xb") as stream:
        stream.write(encoded(plan))
        stream.flush()
        os.fsync(stream.fileno())
    os.chown(path, 0, packet["gid"])
    os.chmod(path, 0o440)
    return export, scratch
