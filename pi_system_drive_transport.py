"""Create-only image-object transport, separate from the raw-pack whitelist.

The caller must be the sealed, unprivileged image upload worker. No physical
device, arbitrary remote pathname, replacement, deletion or moving pointer API.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

from pi_plain_backup_transport import Rclone as RawRclone
from pi_plain_backup_attestation import protected_file

OBJECT = re.compile(r"system-images/(?:sets/[a-f0-9]{64}/(?:frames/recovery\.img\.part[0-9]{6}\.zst|metadata/[a-f0-9]{64}\.jsonl?|tools/[a-f0-9]{64}\.py|recovery-set\.json)|catalogs/[a-f0-9]{64}\.json)")
METADATA = {"capture.json", "image-result.json", "root.manifest.jsonl", "boot.manifest.jsonl", "external-restore-map.jsonl", "source-observations.jsonl"}


def digest(path, guard):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            guard()
            value.update(block)
    return value.hexdigest()


class ImageRclone(RawRclone):
    def path(self, relative):
        if not isinstance(relative, str) or not OBJECT.fullmatch(relative):
            raise ValueError("unsupported fixed image-object path")
        return self.remote + "/" + relative

    def verify(self, relative, expected, size):
        """Bound readback to expected+1 bytes; never spool a malicious object."""
        self.guard()
        protected_file(Path(self.executable).resolve(strict=True))
        args = [self.executable, "--config", str(self.config), "cat", self.path(relative),
                "--drive-root-folder-id", self.root_folder_id, "--count", str(size + 1),
                "--bwlimit", "8M", "--retries", "1", "--low-level-retries", "2",
                "--contimeout", "30s", "--timeout", "60s"]
        env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "HOME": "/nonexistent",
               "GOMEMLIMIT": "192MiB", "GOGC": "50", "GOMAXPROCS": "2"}
        value, count = hashlib.sha256(), 0
        with tempfile.TemporaryFile() as errors:
            child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=errors, env=env)
            try:
                while True:
                    self.guard()
                    block = child.stdout.read(1024 * 1024)
                    if not block:
                        break
                    count += len(block)
                    value.update(block)
                    if count > size or errors.tell() > 256 * 1024:
                        raise ValueError("image remote object length or diagnostics exceeds bound")
                code = child.wait()
                if code in (3, 4) and count == 0:
                    return None
                if code or count != size or value.hexdigest() != expected:
                    raise ValueError("existing image object failed complete SHA-256 readback")
                self.guard()
                return True
            finally:
                child.stdout.close()
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=10)


def put_verified(store, relative, source, expected, size, guard):
    source = Path(source)
    before = source.lstat()
    if (source.resolve() != source or not stat.S_ISREG(before.st_mode) or before.st_size != size
            or digest(source, guard) != expected):
        raise ValueError("sealed image upload source differs")
    if store.verify(relative, expected, size):
        return "REUSED_VERIFIED"
    store.upload(relative, source)
    if store.verify(relative, expected, size) is not True:
        raise ValueError("new image object has no complete readback")
    after = source.lstat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError("image upload source changed during transfer")
    return "CREATED_READBACK_VERIFIED"


def validate_plan(plan):
    if (plan.get("schema") != "ar-local-system-image-upload-plan-v1" or not re.fullmatch(r"[a-f0-9]{64}", plan["recovery_set_sha256"])
            or not re.fullmatch(r"[a-f0-9]{64}", plan.get("raw_catalog_sha256", "")) or type(plan.get("raw_restore_required")) is not bool
            or not isinstance(plan.get("objects"), list) or not 1 <= len(plan["objects"]) <= 8300):
        raise ValueError("sealed fixed image upload plan required")
    identity = plan["recovery_set_sha256"]
    prefix = "system-images/sets/" + identity + "/"
    seen = set()
    for row in plan["objects"]:
        name, target = row["source"], row["path"]
        allowed = (name in METADATA or name == "recovery-set.json" or re.fullmatch(r"recovery\.img\.part[0-9]{6}\.zst", name)
                   or re.fullmatch(r"tools/pi_(?:system_[a-z_]+|plain_backup_restore|drive_backup_manifest|laptop_backup_source)\.py", name))
        if (not allowed or name in seen or not target.startswith(prefix) or not OBJECT.fullmatch(target)
                or not re.fullmatch(r"[a-f0-9]{64}", row["sha256"]) or type(row["bytes"]) is not int or row["bytes"] < 0):
            raise ValueError("unapproved or duplicate image upload object")
        role = ("metadata/" + row["sha256"] + Path(name).suffix if name in METADATA else
                "tools/" + row["sha256"] + ".py" if name.startswith("tools/") else
                "frames/" + name if name.startswith("recovery.img.part") else "recovery-set.json")
        if target != prefix + role or name == "recovery-set.json" and row["sha256"] != identity:
            raise ValueError("image object role/hash destination differs")
        seen.add(name)
    if "recovery-set.json" not in seen or not METADATA <= seen or not any(name.startswith("recovery.img.part") for name in seen):
        raise ValueError("complete image metadata set required")
    return plan


def upload_plan(input_root, plan, store, work, guard):
    root, work = Path(input_root), Path(work)
    validate_plan(plan)
    identity = plan["recovery_set_sha256"]
    results = []
    for row in plan["objects"]:
        results.append({**row, "result": put_verified(store, row["path"], root / row["source"], row["sha256"], row["bytes"], guard)})
    catalog = {"schema": "ar-local-offsite-system-image-v1", "recovery_set_sha256": identity,
               "objects": plan["objects"], "raw_catalog_sha256": plan["raw_catalog_sha256"],
               "raw_restore_required": plan["raw_restore_required"], "boot_test": "NOT_TESTED"}
    catalog_file = work / "offsite-image-catalog.json"
    with catalog_file.open("x", encoding="ascii", newline="\n") as stream:
        json.dump(catalog, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    checksum = digest(catalog_file, guard)
    target = "system-images/catalogs/" + checksum + ".json"
    put_verified(store, target, catalog_file, checksum, catalog_file.stat().st_size, guard)
    return {"schema": "ar-local-system-image-upload-result-v1", "result": "IMAGE_OBJECTS_FULL_READBACK_VERIFIED",
            "catalog_path": target, "catalog_sha256": checksum, "objects": results,
            "raw_catalog_sha256": plan["raw_catalog_sha256"], "raw_restore_required": plan["raw_restore_required"], "boot_test": "NOT_TESTED"}
