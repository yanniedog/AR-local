"""Cold recovery from hash-pinned Drive objects; never uploads or executes them.

Downloads can reuse only complete SHA/size-verified objects. Failed partials
remain private. The independently supervised root restore phase repeats every
catalog/object check from a sealed readonly mirror before accepting any result.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import uuid

from pi_system_drive_transport import validate_plan as image_objects


def digest(path, guard):
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 ** 2), b""):
            guard()
            result.update(block)
    return result.hexdigest()


def validate_plan(plan):
    if (set(plan) != {"schema", "raw_catalog_sha256", "raw_catalog_bytes", "image_catalog_sha256", "image_catalog_bytes"}
            or plan["schema"] != "ar-local-system-cold-plan-v1"
            or any(not re.fullmatch("[a-f0-9]{64}", plan[key]) for key in ("raw_catalog_sha256", "image_catalog_sha256"))
            or any(type(plan[key]) is not int or not 0 < plan[key] <= 32 * 1024 ** 2
                   for key in ("raw_catalog_bytes", "image_catalog_bytes"))):
        raise ValueError("independently pinned raw/image catalog identities and bounded sizes required")
    return plan


def existing(path, expected, size, guard):
    info = path.lstat()
    if (path.resolve() != path or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_size != size or digest(path, guard) != expected):
        raise ValueError("cold object failed complete size/SHA verification; preserve it")


def download(store, relative, destination, expected, size, guard):
    """Read only bounded rclone cat; no upload/copyto/delete transfer API."""
    if not re.fullmatch("[a-f0-9]{64}", expected) or type(size) is not int or size < 0:
        raise ValueError("exact cold object digest and size required")
    remote = store.path(relative)  # Separate strict image/raw remote whitelists.
    destination = Path(destination)
    if destination.exists():
        existing(destination, expected, size, guard)
        return
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.parent.resolve() != destination.parent or destination.is_symlink():
        raise ValueError("canonical private cold download required")
    if shutil.disk_usage(destination.parent).free < size + 10 * 1024 ** 3:
        raise ValueError("cold download capacity reserve unavailable")
    partial = destination.with_name(destination.name + ".partial." + uuid.uuid4().hex)
    args = [store.executable, "--config", str(store.config), "cat", remote, "--drive-root-folder-id", store.root_folder_id,
            "--count", str(size + 1), "--bwlimit", "8M", "--retries", "1", "--low-level-retries", "2",
            "--contimeout", "30s", "--timeout", "60s"]
    env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "HOME": "/nonexistent", "GOMEMLIMIT": "192MiB", "GOGC": "50", "GOMAXPROCS": "2"}
    from pi_plain_backup_attestation import protected_file
    protected_file(Path(store.executable).resolve(strict=True))
    count, checksum = 0, hashlib.sha256()
    with partial.open("xb") as output, tempfile.TemporaryFile() as errors:
        child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=errors, env=env)
        try:
            while True:
                guard()
                block = child.stdout.read(1024 ** 2)
                if not block:
                    break
                count += len(block)
                if count > size or errors.tell() > 256 * 1024:
                    raise ValueError("cold remote object exceeded exact bound")
                checksum.update(block)
                output.write(block)
            if child.wait() or count != size or checksum.hexdigest() != expected:
                raise ValueError("cold download full readback differs")
            output.flush()
            os.fsync(output.fileno())
        finally:
            child.stdout.close()
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=10)
    guard()
    os.link(partial, destination)
    partial.unlink()  # Only this new, fully verified private transfer alias.
    existing(destination, expected, size, guard)


def image_catalog(path, plan, guard):
    existing(path, plan["image_catalog_sha256"], plan["image_catalog_bytes"], guard)
    value = json.loads(Path(path).read_bytes())
    if (value.get("schema") != "ar-local-offsite-system-image-v1" or value.get("raw_catalog_sha256") != plan["raw_catalog_sha256"]
            or value.get("raw_restore_required") is not True):
        raise ValueError("cold image/raw recovery catalogs are not bound")
    image_objects({**value, "schema": "ar-local-system-image-upload-plan-v1"})
    return value


def raw_objects(path, plan, callback, guard):
    """Stream the catalog; original SQLite+WAL and committed views stay separate."""
    from pi_plain_backup_restore import object_arrays
    existing(path, plan["raw_catalog_sha256"], plan["raw_catalog_bytes"], guard)
    def pack(row):
        item = row["descriptor"]
        if (item.get("schema") != "ar-local-plain-pack-v1" or item.get("compression") != "zstd-lossless-no-encryption"
                or not re.fullmatch("[a-f0-9]{64}", item["pack_id"])):
            raise ValueError("unsupported cold raw pack")
        callback("packs/" + item["pack_id"] + "/archive.tar.zst", item["archive_sha256"], item["archive_bytes"])
    value = object_arrays(path, {"packs": pack, "excluded_paths": lambda item: None}, guard)
    if value.get("schema") != "ar-local-plain-catalog-v1" or not value.get("packs"):
        raise ValueError("complete bound raw catalog required")
    index = value["file_index"]
    if (index.get("schema") != "ar-local-plain-file-index-v1"
            or index.get("path") != "manifests/" + index["sha256"] + ".jsonl"):
        raise ValueError("bound raw index path differs")
    callback(index["path"], index["sha256"], index["bytes"])
    return value


def fetch(work, plan, raw_store, image_store, guard):
    work = Path(work)
    validate_plan(plan)
    for name in ("raw", "image"):
        (work / name).mkdir(mode=0o700, exist_ok=True)
    raw_path = work / "raw/catalogs" / (plan["raw_catalog_sha256"] + ".json")
    download(raw_store, "catalogs/" + raw_path.name, raw_path, plan["raw_catalog_sha256"], plan["raw_catalog_bytes"], guard)
    catalog_path = work / "image-catalog.json"
    download(image_store, "system-images/catalogs/" + plan["image_catalog_sha256"] + ".json", catalog_path,
             plan["image_catalog_sha256"], plan["image_catalog_bytes"], guard)
    catalog = image_catalog(catalog_path, plan, guard)
    missing = sum(row["bytes"] for row in catalog["objects"] if not (work / "image" / row["source"]).exists())
    def count(path, checksum, size):
        nonlocal missing
        if type(size) is not int or size < 0:
            raise ValueError("invalid declared raw object size")
        if not (work / "raw" / path).exists():
            missing += size
    raw_objects(raw_path, plan, count, guard)
    if shutil.disk_usage(work).free < missing + 10 * 1024 ** 3:
        raise ValueError("complete cold mirror capacity unavailable")
    for row in catalog["objects"]:
        download(image_store, row["path"], work / "image" / row["source"], row["sha256"], row["bytes"], guard)
    raw_objects(raw_path, plan, lambda path, checksum, size: download(raw_store, path, work / "raw" / path, checksum, size, guard), guard)
    result = {"schema": "ar-local-system-cold-fetch-v1", "result": "HASH_PINNED_OBJECTS_DOWNLOADED",
              "raw_catalog_sha256": plan["raw_catalog_sha256"], "image_catalog_sha256": plan["image_catalog_sha256"],
              "cloud_writes": False, "independent_root_restore": "REQUIRED"}
    return result


def verify_mirror(work, plan, guard):
    """Called by the cap0 ROOT restorer, not an accepted Pi-worker verdict."""
    work = Path(work)
    catalog = image_catalog(work / "image-catalog.json", validate_plan(plan), guard)
    for row in catalog["objects"]:
        existing(work / "image" / row["source"], row["sha256"], row["bytes"], guard)
    raw_path = work / "raw/catalogs" / (plan["raw_catalog_sha256"] + ".json")
    raw_objects(raw_path, plan, lambda path, checksum, size: existing(work / "raw" / path, checksum, size, guard), guard)
    return catalog


def restore(work, mirror, plan, guard):
    from pi_plain_backup_restore import restore as raw_restore
    from pi_system_image_restore import reassemble
    work, mirror = Path(work), Path(mirror)
    catalog = verify_mirror(mirror, plan, guard)
    from pi_plain_backup_restore import object_arrays
    source_bytes = files = 0
    def size(row):
        nonlocal source_bytes, files
        item = row["descriptor"]
        if any(type(item[key]) is not int or item[key] < 0 for key in ("source_bytes", "files")):
            raise ValueError("invalid cold restore capacity descriptor")
        source_bytes += item["source_bytes"]
        files += item["files"]
    object_arrays(mirror / "raw/catalogs" / (plan["raw_catalog_sha256"] + ".json"),
                  {"packs": size, "excluded_paths": lambda item: None}, guard)
    recovery = json.loads((mirror / "image/recovery-set.json").read_bytes())
    if recovery.get("catalog_sha256") != plan["raw_catalog_sha256"]:
        raise ValueError("recovery image and independent raw catalog differ")
    allocation = recovery.get("reassembled_allocation_bound", recovery["image_bytes"])
    if type(allocation) is not int or allocation < 0:
        raise ValueError("invalid restored image allocation")
    # Raw workspace plus later raw insertion into the sparse image; logical
    # unused ext4 capacity is not charged as dense allocation.
    required = source_bytes * 2 + allocation + files * 2048 + 10 * 1024 ** 3
    if shutil.disk_usage(work).free < required:
        raise ValueError("complete cold raw/image/join capacity reserve unavailable")
    if hasattr(os, "statvfs") and os.statvfs(work).f_favail < files * 4 + 100000:
        raise ValueError("complete cold raw restore inode reserve unavailable")
    raw = raw_restore(mirror / "raw", mirror / "raw/catalogs" / (plan["raw_catalog_sha256"] + ".json"),
                      plan["raw_catalog_sha256"], work / "raw", guard=guard)
    guard()
    image = reassemble(mirror / "image", mirror / "image/recovery-set.json", catalog["recovery_set_sha256"], work / "image")
    guard()
    return {"schema": "ar-local-system-cold-restore-v1", "result": "COLD_RAW_AND_IMAGE_RESTORED_VERIFIED",
            "raw_catalog_sha256": plan["raw_catalog_sha256"], "image_catalog_sha256": plan["image_catalog_sha256"],
            "recovery_set_sha256": catalog["recovery_set_sha256"], "raw": raw, "image": image,
            "raw_rejoin_required": True, "boot_test": "NOT_TESTED", "cloud_writes": False}
