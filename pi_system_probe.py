"""Native guard commissioning with new private fixture files, never Pi data."""
import argparse
import json
import os
import struct
from pathlib import Path
from types import SimpleNamespace

from pi_system_capture import SCHEMA, archive_parts, sha, tree_manifest, write
from pi_system_image import build, require_namespace


def main(work):
    require_namespace()
    work = Path(work)
    if any(work.iterdir()):
        raise RuntimeError("native image probe requires a new empty private workspace")
    from pi_system_guard_files import directory
    previous = os.umask(0o077)
    try:
        public = work / "custody-mode-probe"
        directory(public, 0o750)
        if public.stat().st_mode & 0o777 != 0o750:
            raise RuntimeError("native0077 filtered intended public traversal")
    finally:
        os.umask(previous)
    root, boot = work / "frozen/root", work / "frozen/boot"
    (root / "etc").mkdir(parents=True)
    boot.mkdir(parents=True)
    (root / "etc/fstab").write_text("PARTUUID=12345678-02 / ext4 defaults 0 1\nPARTUUID=12345678-01 /boot/firmware vfat defaults 0 2\n")
    (boot / "cmdline.txt").write_text("console=tty1 root=PARTUUID=12345678-02 rootfstype=ext4 rootwait\n")
    content = root / "probe-bytes"
    content.write_bytes(bytes(range(256)) * 128)
    os.chmod(content, 0o640)
    os.setxattr(content, "user.ar_local_probe", b"\x00\xff\x01")
    acl = struct.pack("<I", 2) + b"".join(struct.pack("<HHI", tag, permission, identifier) for tag, permission, identifier in
        ((1, 6, 0xffffffff), (2, 4, 65534), (4, 4, 0xffffffff), (16, 4, 0xffffffff), (32, 0, 0xffffffff)))
    os.setxattr(content, "system.posix_acl_access", acl)
    os.link(content, root / "hardlink")
    os.symlink("probe-bytes", root / "symlink")
    os.mkfifo(root / "fifo", 0o600)
    os.chmod(boot, 0o755)
    os.chmod(boot / "cmdline.txt", 0o755)
    for path in (boot, boot / "cmdline.txt"):
        os.utime(path, ns=(1700000000 * 10 ** 9, 1700000000 * 10 ** 9))
    settings = {"schema": SCHEMA, "workspace": str(work), "layout": {"disk_id": "12345678", "root_uuid": "probe-source", "boot_uuid": "1111-2222",
                "boot_mount": {"fstype": "vfat", "uid": "0", "gid": "0", "fmask": "0022", "dmask": "0022"}},
                "external_recovery": {"catalog_sha256": "0" * 64}}
    write(work / "workspace.json", settings)
    (work / "external-restore-map.jsonl").write_text("")
    receipt = {"schema": SCHEMA, "result": "ARCHIVED", "raw_restore_required": False, "trees": {}, "scope": "TEST_ONLY_NEW_PRIVATE_FILES",
               "external_restore_map_sha256": sha(work / "external-restore-map.jsonl")}
    for tree, path in (("root", root), ("boot", boot)):
        manifest = work / (tree + ".manifest.jsonl")
        binding = tree_manifest(path, manifest)
        receipt["trees"][tree] = {"manifest": binding, "archives": archive_parts(path, manifest, work, tree)}
    write(work / "capture.json", receipt)
    result = build(SimpleNamespace(workspace=work, include_restored_raw=None))
    if result["result"] != "FILESYSTEM_RESTORE_VERIFIED" or result["filesystem_check"]["result"] != "PASS":
        raise RuntimeError("native private image restoration proof failed")
    write(work / "probe-result.json", {"result": "IMAGE_PRIVATE_FIXTURE_PROBE_PASS", "native_filesystems_verified": True, "umask_permissions_verified": True,
          "scope": "NO_REAL_PI_SOURCE_NO_DRIVE_WRITES", "boot_test": "NOT_TESTED", "image_result_sha256": sha(work / "image-result.json")})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    main(parser.parse_args().workspace)
