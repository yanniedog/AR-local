"""Reconstruct a Pi recovery image using ONLY a new regular file and its loop.

Run in a reviewed private mount namespace with read-only host root/sysfs and
physical block devices absent. No physical-disk argument or flashing mode exists.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import shutil
import stat
import struct
import subprocess
import sys
import time
import uuid
from pathlib import Path

from pi_system_capture import ENV, metadata, run, sha, utc, workspace, write
from pi_system_raw_restore import external_files, restore_raw
from pi_system_filesystems import fat_options
from pi_system_sparse import allocation_bound

SECTOR = 512
BOOT_START = 8192
BOOT_SECTORS = 1048576
ROOT_START = BOOT_START + BOOT_SECTORS


def mbr(disk_id, root_sectors):
    if not 0 < disk_id < 2 ** 32 or not 32768 <= root_sectors <= 2 ** 32 - ROOT_START:
        raise ValueError("invalid MBR geometry")
    body = bytearray(512)
    struct.pack_into("<I", body, 440, disk_id)
    for offset, active, kind, start, size in ((446, 0x80, 0x0C, BOOT_START, BOOT_SECTORS),
                                             (462, 0, 0x83, ROOT_START, root_sectors)):
        struct.pack_into("<B3sB3sII", body, offset, active, b"\xfe\xff\xff", kind, b"\xfe\xff\xff", start, size)
    body[510:] = b"\x55\xaa"
    return bytes(body)


def require_namespace():
    if os.geteuid() != 0 or not os.statvfs("/").f_flag & os.ST_RDONLY:
        raise ValueError("private root worker with a read-only host root is required")
    if not os.statvfs("/sys").f_flag & os.ST_RDONLY:
        raise ValueError("sysfs must be read-only")
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        if any(field.startswith("shared:") for field in line.split(" - ", 1)[0].split()[6:]):
            raise ValueError("shared mount propagation is forbidden")
    for current, dirs, files in os.walk("/dev", followlinks=False):
        for name in files:
            path = Path(current) / name
            if stat.S_ISBLK(path.lstat().st_mode) and not re.fullmatch(r"loop[0-9]+(?:p[12])?", name):
                raise ValueError("physical block device exposed to image worker")


def backing_file(loop):
    if not re.fullmatch(r"/dev/loop[0-9]+", loop):
        raise ValueError("only a newly allocated loop device is permitted")
    text = (Path("/sys/class/block") / Path(loop).name / "loop/backing_file").read_text().strip()
    # Kernel sysfs escapes unusual filenames in backing_file. Workspace paths
    # deliberately use ordinary canonical absolute names to avoid ambiguity.
    if "\\" in text or not text.startswith("/"):
        raise ValueError("ambiguous loop backing path")
    return Path(text)


def require_loop(loop, image, descriptor):
    info = os.fstat(descriptor)
    current = Path(image).lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or current.st_nlink != 1
            or (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino)
            or Path(image).resolve() != image):
        raise ValueError("loop does not exclusively identify this new image inode")
    device = Path(loop).lstat()
    if not stat.S_ISBLK(device.st_mode) or os.major(device.st_rdev) != 7:
        raise ValueError("not a Linux loop device")
    expected = (Path("/sys/class/block") / Path(loop).name / "dev").read_text().strip()
    if expected != f"{os.major(device.st_rdev)}:{os.minor(device.st_rdev)}":
        raise ValueError("loop node differs from its kernel device identity")
    import fcntl
    loop_descriptor = os.open(loop, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        status = bytearray(232)
        fcntl.ioctl(loop_descriptor, 0x4C05, status, True)  # LOOP_GET_STATUS64
        dev, inode, _, offset, limit = struct.unpack_from("<QQQQQ", status)
        if (dev, inode) != (info.st_dev, info.st_ino) or offset or limit:
            raise ValueError("kernel loop identity differs from the new regular image inode")
    finally:
        os.close(loop_descriptor)


def attach_image(image, descriptor, work):
    import fcntl
    control = os.open("/dev/loop-control", os.O_RDWR | os.O_NOFOLLOW)
    try:
        number = fcntl.ioctl(control, 0x4C82)  # LOOP_CTL_GET_FREE; never detach/reuse an occupied loop.
    finally:
        os.close(control)
    if not isinstance(number, int) or not 0 <= number < 2 ** 20:
        raise ValueError("invalid new loop number")
    loop = "/dev/loop" + str(number)
    info = os.fstat(descriptor)
    write(work / "loop-attach-intent.json", {"loop": loop, "image": str(image), "device": info.st_dev,
          "inode": info.st_ino, "result": "ATTACH_PLANNED", "planned_at": utc()})
    os.mknod(loop, stat.S_IFBLK | 0o600, os.makedev(7, number))
    held = None
    try:
        run(["/usr/sbin/losetup", "--partscan", loop, image])
        held = os.open(loop, os.O_RDWR | os.O_NOFOLLOW)
        require_loop(loop, image, descriptor)
        state = bytearray(232)
        fcntl.ioctl(held, 0x4C05, state, True)
        flags = struct.unpack_from("<I", state, 52)[0]
        struct.pack_into("<I", state, 52, flags | 4)  # LO_FLAGS_AUTOCLEAR
        fcntl.ioctl(held, 0x4C04, state)
        info = os.fstat(descriptor)
        write(work / "loop-ownership.json", {"loop": loop, "image": str(image), "device": info.st_dev,
              "inode": info.st_ino, "autoclear": True, "allocated_at": utc()})
        for _ in range(100):
            if all((Path("/sys/class/block") / (Path(loop).name + "p" + str(n)) / "dev").exists() for n in (1, 2)):
                break
            time.sleep(0.1)
        for number in (1, 2):
            kernel = Path("/sys/class/block") / (Path(loop).name + "p" + str(number))
            major, minor = map(int, (kernel / "dev").read_text().split(":"))
            os.mknod(loop + "p" + str(number), stat.S_IFBLK | 0o600, os.makedev(major, minor))
        return loop, held
    except BaseException as error:
        cleanup = "OWNERSHIP_UNCERTAIN_MANUAL_INSPECTION_REQUIRED"
        try:
            require_loop(loop, image, descriptor)
            run(["/usr/sbin/losetup", "--detach", loop])
            cleanup = "OWNED_LOOP_DETACH_REQUESTED"
        except (OSError, ValueError, subprocess.SubprocessError):
            pass  # Never detach a device with an unproved backing inode.
        if held is not None:
            os.close(held)
        write(work / "loop-attach-failure.json", {"loop": loop, "image": str(image), "device": info.st_dev,
              "inode": info.st_ino, "result": "FAIL", "cleanup": cleanup, "error": str(error)})
        raise


def require_partition(loop, number, image, descriptor):
    require_loop(loop, image, descriptor)
    partition = Path(loop + "p" + str(number))
    if number not in {1, 2} or not stat.S_ISBLK(partition.lstat().st_mode):
        raise ValueError("unexpected loop partition")
    sys_path = Path("/sys/class/block") / partition.name
    if sys_path.resolve().parent.name != Path(loop).name:
        raise ValueError("partition does not belong to the owned image loop")
    expected = BOOT_START if number == 1 else ROOT_START
    if int((sys_path / "start").read_text()) != expected:
        raise ValueError("loop partition offset differs")
    device = partition.lstat()
    if (sys_path / "dev").read_text().strip() != f"{os.major(device.st_rdev)}:{os.minor(device.st_rdev)}":
        raise ValueError("partition node differs from its kernel device identity")
    return partition


def verify_filesystem_identity(loop, number, image, descriptor, expected_uuid):
    partition = require_partition(loop, number, image, descriptor)
    value = subprocess.check_output(["/usr/sbin/blkid", "-p", "-s", "UUID", "-o", "value", str(partition)], env=ENV, text=True).strip()
    if value != expected_uuid:
        raise ValueError("new loop filesystem UUID differs from boot configuration")
    return {"uuid": value, "partition": number, "result": "PASS"}


def check_unmounted_filesystems(loop, image, descriptor):
    boot = require_partition(loop, 1, image, descriptor)
    run(["/usr/sbin/fsck.vfat", "-n", boot])
    root = require_partition(loop, 2, image, descriptor)
    run(["/usr/sbin/e2fsck", "-f", "-n", root])
    return {"result": "PASS", "mode": "read-only after unmount; only inode-proved image loop partitions"}


def verify_tree(tree, manifest, *, transforms=None, scratch=None):
    transforms = transforms or {}
    # SQLite keeps large full-path inventories bounded in RAM.
    import sqlite3
    index = Path(scratch if scratch is not None else Path(manifest).parent) / ("restore-check-" + uuid.uuid4().hex + ".sqlite")
    descriptor = os.open(index, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    database = sqlite3.connect(index)
    database.execute("PRAGMA cache_size=-8192")
    database.execute("PRAGMA temp_store=FILE")
    database.execute("CREATE TABLE expected(path TEXT PRIMARY KEY, row_json TEXT)")
    with Path(manifest).open(encoding="ascii") as stream:
        for line in stream:
            row = json.loads(line)
            if row["path"] in transforms:
                row["sha256"] = transforms[row["path"]]["after_sha256"]
            database.execute("INSERT INTO expected VALUES (?,?)", (row["path"], json.dumps(row, sort_keys=True)))
    checked = 0
    for actual in metadata(tree, index.parent / ("restore-links-" + uuid.uuid4().hex + ".sqlite")):
        name = actual["path"]
        expected = database.execute("SELECT row_json FROM expected WHERE path=?", (name,)).fetchone()
        if not expected:
            if name == "lost+found" and not any((Path(tree) / name).iterdir()):
                continue
            raise ValueError("unexpected restored path: " + name)
        if actual != json.loads(expected[0]):
            raise ValueError("restored bytes/ACL/xattrs/ownership/link metadata differ: " + name)
        database.execute("DELETE FROM expected WHERE path=?", (name,))
        checked += 1
    remaining = database.execute("SELECT path FROM expected LIMIT 1").fetchone()
    database.close()
    index.unlink()
    if remaining:
        raise ValueError("missing restored path: " + remaining[0])
    return {"result": "PASS", "entries": checked, "metadata": "mode,uid,gid,mtime_ns,ACL,xattrs,hardlinks,symlinks,special-node-type"}


def extract(archive, target):
    child = subprocess.Popen(["/usr/bin/zstd", "--decompress", "--stdout", str(archive)], stdout=subprocess.PIPE, env=ENV)
    try:
        run(["/usr/bin/tar", "--extract", "--acls", "--xattrs", "--xattrs-include=*", "--numeric-owner",
             "--same-owner", "--sparse", "--warning=no-unknown-keyword", "--file=-", "-C", target], stdin=child.stdout)
        child.stdout.close()
        if child.wait():
            raise RuntimeError("archive decompressor failed")
    finally:
        child.stdout.close()
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=30)


def restore_metadata(tree, manifest):
    with Path(manifest).open(encoding="ascii") as stream:
        for line in stream:
            row = json.loads(line)
            if row["path"] != ".":
                from pi_system_capture import relative
                relative(row["path"])
            path = Path(tree) if row["path"] == "." else Path(tree) / row["path"]
            for parent in path.parents:
                if parent == Path(tree):
                    break
                if parent.is_symlink():
                    raise ValueError("metadata path traverses a restored symlink")
            info = path.lstat()
            if stat.S_IFMT(info.st_mode) != row["type"]:
                raise ValueError("restored node type differs")
            if (info.st_uid, info.st_gid) != (row["uid"], row["gid"]):
                os.chown(path, row["uid"], row["gid"], follow_symlinks=False)
            if not stat.S_ISLNK(info.st_mode) and stat.S_IMODE(info.st_mode) != row["mode"]:
                os.chmod(path, row["mode"], follow_symlinks=False)
            for key in set(os.listxattr(path, follow_symlinks=False)) - set(row["xattrs"]):
                os.removexattr(path, key, follow_symlinks=False)
            for key, value in row["xattrs"].items():
                os.setxattr(path, key, base64.b64decode(value, validate=True), follow_symlinks=False)
            os.utime(path, ns=(info.st_atime_ns, row["mtime_ns"]), follow_symlinks=False)


def rewrite_boot(root, boot, original, identifiers):
    substitutions = {"PARTUUID=" + original["disk_id"] + "-01": "PARTUUID=" + identifiers["disk_id"] + "-01",
                     "PARTUUID=" + original["disk_id"] + "-02": "PARTUUID=" + identifiers["disk_id"] + "-02",
                     "UUID=" + original["root_uuid"]: "UUID=" + identifiers["root_uuid"],
                     "UUID=" + original["boot_uuid"]: "UUID=" + identifiers["boot_uuid"]}
    transforms = {"root": {}, "boot": {}}
    for tree, path, relative in (("root", Path(root) / "etc/fstab", "etc/fstab"),
                                 ("boot", Path(boot) / "cmdline.txt", "cmdline.txt")):
        if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
            raise ValueError("boot configuration must be a regular in-image file")
        before = path.read_bytes()
        after = before.decode("utf-8")
        for old, new in substitutions.items():
            after = after.replace(old, new)
        if tree == "boot":
            values = [token for token in after.split() if token.startswith("root=")]
            if len(values) != 1 or values[0] not in {"root=PARTUUID=" + identifiers["disk_id"] + "-02", "root=UUID=" + identifiers["root_uuid"]}:
                raise ValueError("unrecognized root= boot configuration")
        else:
            roots = [line.split()[0] for line in after.splitlines() if line.strip() and not line.lstrip().startswith("#") and len(line.split()) >= 2 and line.split()[1] == "/"]
            if roots not in [["PARTUUID=" + identifiers["disk_id"] + "-02"], ["UUID=" + identifiers["root_uuid"]]]:
                raise ValueError("unrecognized root filesystem fstab reference")
            boots = [line.split()[0] for line in after.splitlines() if line.strip() and not line.lstrip().startswith("#") and len(line.split()) >= 2 and line.split()[1] in {"/boot", "/boot/firmware"}]
            if boots not in [["PARTUUID=" + identifiers["disk_id"] + "-01"], ["UUID=" + identifiers["boot_uuid"]]]:
                raise ValueError("unrecognized boot filesystem fstab reference")
        info = path.stat()
        descriptor = os.open(path, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(after.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
        transforms[tree][relative] = {"before_sha256": __import__("hashlib").sha256(before).hexdigest(), "after_sha256": sha(path)}
    return transforms


def image_size(manifest):
    size = 0
    entries = 0
    with Path(manifest).open(encoding="ascii") as stream:
        for line in stream:
            row = json.loads(line)
            entries += 1
            if "size" in row and "hardlink_to" not in row:
                size += row["size"]
    return max(4096, (size * 13 // 10 + max(3 * 1024 ** 3, entries * 1024) + 1024 ** 2 - 1) // (1024 ** 2)), entries


def build(args):
    require_namespace()
    work, settings = workspace(args.workspace)
    capture = json.loads((work / "capture.json").read_text())
    if capture["result"] != "ARCHIVED":
        raise ValueError("completed frozen capture required")
    for tree in ("root", "boot"):
        if sha(work / (tree + ".manifest.jsonl")) != capture["trees"][tree]["manifest"]["sha256"]:
            raise ValueError("capture manifest hash differs")
        for part in capture["trees"][tree]["archives"]:
            if not re.fullmatch(tree + r"\.part[0-9]{6}\.tar\.zst", part["path"]) or sha(work / part["path"]) != part["sha256"]:
                raise ValueError("capture archive hash/path differs")
    if sha(work / "external-restore-map.jsonl") != capture["external_restore_map_sha256"]:
        raise ValueError("external restore map hash differs")
    root_mib, entry_count = image_size(work / "root.manifest.jsonl")
    physical_bound = root_mib * 1024 ** 2
    include_raw = getattr(args, "include_restored_raw", None)
    if capture["raw_restore_required"]:
        raw_bytes, raw_entries = 0, 0
        for _, row in external_files(work / "external-restore-map.jsonl"):
            raw_bytes += row["size"]
            raw_entries += 1
        root_mib += (raw_bytes * 13 // 10 + raw_entries * 1024 + 1024 ** 2 - 1) // (1024 ** 2)
        entry_count += raw_entries
        physical_bound += raw_entries * 1024
        if include_raw:
            physical_bound += raw_bytes * 13 // 10
    serial = secrets.token_hex(4).upper()
    identifiers = {"disk_id": format(secrets.randbelow(2 ** 32 - 1) + 1, "08x"),
                   "root_uuid": str(uuid.uuid4()), "boot_uuid": serial[:4] + "-" + serial[4:]}
    original = settings["layout"]
    if identifiers["disk_id"] == original["disk_id"] or identifiers["root_uuid"] == original["root_uuid"]:
        raise ValueError("new image identifiers must not collide with original host")
    image = work / "recovery.img"
    required_free = physical_bound * 2 + 10 * 1024 ** 3
    if shutil.disk_usage(work).free < required_free:
        raise ValueError("insufficient measured free space for image, lossless compressed image and reserve")
    descriptor = os.open(image, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    loop = None
    held_loop = None
    mounted = []
    receipt = {"schema": "ar-local-system-image-v1", "result": "RUNNING", "started_at": utc(),
               "identifiers": identifiers, "boot_test": "NOT_TESTED", "raw_restore_required": capture["raw_restore_required"],
               "capture_sha256": sha(work / "capture.json")}
    receipt["reserved_external_raw_capacity"] = capture["raw_restore_required"] and not include_raw
    write(work / "image-intent.json", receipt)
    try:
        os.ftruncate(descriptor, (ROOT_START + root_mib * 2048) * SECTOR)
        os.pwrite(descriptor, mbr(int(identifiers["disk_id"], 16), root_mib * 2048), 0)
        os.fsync(descriptor)
        loop, held_loop = attach_image(image, descriptor, work)
        boot_part = require_partition(loop, 1, image, descriptor)
        run(["/usr/sbin/mkfs.vfat", "-F", "32", "-n", "bootfs", "-i", identifiers["boot_uuid"].replace("-", ""), boot_part])
        root_part = require_partition(loop, 2, image, descriptor)
        run(["/usr/sbin/mkfs.ext4", "-F", "-U", identifiers["root_uuid"], "-L", "rootfs", "-m", "0",
             "-N", str(entry_count * 11 // 10 + 65536), root_part])
        receipt["filesystem_identities"] = {tree: verify_filesystem_identity(loop, number, image, descriptor, identifiers[key])
            for tree, number, key in (("root", 2, "root_uuid"), ("boot", 1, "boot_uuid"))}
        for tree, number in (("root", 2), ("boot", 1)):
            mount = work / ("image-" + tree)
            mount.mkdir()
            part = require_partition(loop, number, image, descriptor)
            options = ["nodev", "nosuid", "noexec", "noatime"]
            if tree == "boot":
                options += fat_options(original["boot_mount"])
            run(["/usr/bin/mount", "-o", ",".join(options), part, mount])
            mounted.append(mount)
            for part in capture["trees"][tree]["archives"]:
                extract(work / part["path"], mount)
            restore_metadata(mount, work / (tree + ".manifest.jsonl"))
            verify_tree(mount, work / (tree + ".manifest.jsonl"))
        root_manifest = work / "root.manifest.jsonl"
        if include_raw:
            full_manifest = work / "full-root.manifest.jsonl"
            receipt["raw_restore"] = restore_raw(work / "image-root", include_raw, work / "external-restore-map.jsonl",
                settings["external_recovery"]["catalog_sha256"], root_manifest, full_manifest)
            root_manifest = full_manifest
            restore_metadata(work / "image-root", root_manifest)
            verify_tree(work / "image-root", root_manifest)
            receipt["raw_restore_required"] = False
        transforms = rewrite_boot(work / "image-root", work / "image-boot", original, identifiers)
        receipt["restore"] = {tree: verify_tree(work / ("image-" + tree), root_manifest if tree == "root" else work / "boot.manifest.jsonl", transforms=transforms[tree]) for tree in ("root", "boot")}
        receipt.update(result="FILESYSTEM_RESTORE_VERIFIED", transforms=transforms, boot_structure="PASS")
    except BaseException as error:
        receipt.update(result="FAIL", error=type(error).__name__ + ": " + str(error))
        raise
    finally:
        errors = []
        for mount in reversed(mounted):
            try:
                run(["/usr/bin/umount", mount])
            except (OSError, subprocess.SubprocessError) as error:
                errors.append(str(error))
        if loop and not errors:
            try:
                require_loop(loop, image, descriptor)
                if receipt["result"] == "FILESYSTEM_RESTORE_VERIFIED":
                    receipt["filesystem_check"] = check_unmounted_filesystems(loop, image, descriptor)
                run(["/usr/sbin/losetup", "--detach", loop])
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                errors.append(str(error))
        if held_loop is not None:
            os.close(held_loop)
        os.close(descriptor)
        if errors:
            receipt.update(result="FAIL", cleanup_errors=errors)
        receipt["finished_at"] = utc()
        receipt["allocated_image_bytes"] = image.stat().st_blocks * 512
        write(work / "image-result.json", receipt)
    if receipt["result"] != "FILESYSTEM_RESTORE_VERIFIED":
        raise RuntimeError("image cleanup or verification failed")
    return receipt


def image_part(work, image, offset, length, number, image_fingerprint, global_digest):
    import hashlib
    output = work / f"recovery.img.part{number:06d}.zst"
    receipt_path = work / f"recovery.img.part{number:06d}.receipt.json"
    completed = json.loads(receipt_path.read_text()) if receipt_path.exists() else None
    if completed and (completed["offset"] != offset or completed["length"] != length or completed["image_fingerprint"] != image_fingerprint
                      or completed["sha256"] != sha(output)):
        raise ValueError("completed image compression prefix changed")
    if not completed and output.exists():
        if not stat.S_ISREG(output.lstat().st_mode) or output.stat().st_nlink != 1:
            raise ValueError("ambiguous incomplete compressed part")
        output.rename(work / (output.name + ".incomplete-" + uuid.uuid4().hex))
    digest = hashlib.sha256()
    nonzero_bound = 0
    child = destination = None
    if not completed:
        destination = output.open("xb")
        child = subprocess.Popen(["/usr/bin/zstd", "-T1", "-15", "--no-progress", "--stdout"], stdin=subprocess.PIPE, stdout=destination, env=ENV)
    try:
        with image.open("rb") as source:
            source.seek(offset)
            remaining = length
            while remaining:
                block = source.read(min(1024 * 1024, remaining))
                if not block:
                    raise ValueError("regular image truncated during compression")
                digest.update(block)
                global_digest.update(block)
                nonzero_bound += allocation_bound(block)
                if child:
                    child.stdin.write(block)
                remaining -= len(block)
        if child:
            child.stdin.close()
            if child.wait():
                raise RuntimeError("image part compression failed")
            destination.flush()
            os.fsync(destination.fileno())
        elif digest.hexdigest() != completed["image_bytes_sha256"] or completed["reassembled_allocation_bound"] != nonzero_bound:
            raise ValueError("image bytes differ from completed compression prefix")
    finally:
        if child and child.poll() is None:
            child.terminate()
            child.wait(timeout=30)
        if destination:
            destination.close()
    if completed:
        return completed
    run(["/usr/bin/zstd", "--test", output])
    decoded = hashlib.sha256()
    child = subprocess.Popen(["/usr/bin/zstd", "--decompress", "--stdout", output], stdout=subprocess.PIPE, env=ENV)
    try:
        for block in iter(lambda: child.stdout.read(1024 * 1024), b""):
            decoded.update(block)
        if child.wait() or decoded.hexdigest() != digest.hexdigest():
            raise ValueError("compressed part round-trip hash differs")
    finally:
        child.stdout.close()
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=30)
    receipt = {"path": output.name, "offset": offset, "length": length, "image_fingerprint": image_fingerprint,
               "sha256": sha(output), "bytes": output.stat().st_size, "image_bytes_sha256": digest.hexdigest(),
               "reassembled_allocation_bound": nonzero_bound}
    write(receipt_path, receipt)
    return receipt


def compress(args):
    import hashlib
    from pi_system_capture import fingerprint
    work, settings = workspace(args.workspace)
    receipt = json.loads((work / "image-result.json").read_text())
    if receipt["result"] != "FILESYSTEM_RESTORE_VERIFIED" or receipt.get("cleanup_errors"):
        raise ValueError("verified cleanly detached image required before compression")
    capture = json.loads((work / "capture.json").read_text())
    if receipt["capture_sha256"] != sha(work / "capture.json"):
        raise ValueError("image capture identity changed")
    image = work / "recovery.img"
    info = image.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("compression source must be the owned regular image")
    identity = fingerprint(info)
    digest = hashlib.sha256()
    parts = []
    for offset in range(0, info.st_size, 1024 ** 3):
        parts.append(image_part(work, image, offset, min(1024 ** 3, info.st_size - offset), len(parts) + 1, identity, digest))
    if fingerprint(image.lstat()) != identity:
        raise ValueError("image changed during compression")
    result = {"schema": "ar-local-system-recovery-set-v1", "result": "IMAGE_AND_FILESYSTEM_VERIFIED",
              "compression": "zstd-lossless-no-encryption", "image_sha256": digest.hexdigest(), "image_bytes": info.st_size,
              "compressed_parts": parts, "compressed_bytes": sum(part["bytes"] for part in parts),
              "reassembled_allocation_bound": sum(part["reassembled_allocation_bound"] for part in parts),
              "image_result_sha256": sha(work / "image-result.json"), "external_restore_map_sha256": capture["external_restore_map_sha256"],
              "catalog_sha256": settings["external_recovery"]["catalog_sha256"], "raw_restore_required": receipt["raw_restore_required"],
              "boot_test": "NOT_TESTED", "offsite_readback": "NOT_PERFORMED"}
    path = work / "recovery-set.json"
    if path.exists():
        if json.loads(path.read_text()) != result:
            raise ValueError("completed recovery-set identity differs")
    else:
        write(path, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--command", choices=("build", "compress"), default="build")
    parser.add_argument("--include-restored-raw", type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps({"build": build, "compress": compress}[args.command](args)), flush=True)
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps({"result": "FAIL", "error": str(error)}), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
