"""Offline raw rejoin into a NEW, verified sparse image; no resize or flash API.

Run only inside a reviewed private PID/mount namespace, with a new reassembler
workspace at /scratch and readonly metadata/raw-restore inputs. Physical devices
must be absent. A failed rejoin preserves that private output for inspection.
"""
import argparse
import json
import os
from pathlib import Path
import stat

from pi_system_capture import run, sha, utc, write
from pi_system_filesystems import fat_options
from pi_system_image import (attach_image, check_unmounted_filesystems, require_loop,
                             require_namespace, require_partition, restore_metadata,
                             verify_filesystem_identity, verify_tree)
from pi_system_raw_restore import restore_raw
from pi_system_cold_normalize import normalize


def inputs(work, metadata, accepted):
    work, metadata = Path(work), Path(metadata)
    if work != Path("/scratch") or metadata != Path("/input"):
        raise ValueError("fixed isolated scratch/input paths required")
    recovery = json.loads((metadata / "recovery-set.json").read_text())
    if sha(metadata / "recovery-set.json") != accepted or recovery.get("result") != "IMAGE_AND_FILESYSTEM_VERIFIED":
        raise ValueError("accepted recovery identity differs")
    image_result = json.loads((metadata / "image-result.json").read_text())
    capture = json.loads((metadata / "capture.json").read_text())
    restored = json.loads((work / "image-restore-result.json").read_text())
    if (sha(metadata / "image-result.json") != recovery["image_result_sha256"]
            or image_result.get("result") != "FILESYSTEM_RESTORE_VERIFIED"
            or image_result.get("filesystem_check", {}).get("result") != "PASS"
            or image_result.get("reserved_external_raw_capacity") is not True
            or sha(metadata / "capture.json") != image_result["capture_sha256"]
            or restored.get("result") != "REGULAR_IMAGE_REASSEMBLED_VERIFIED"
            or restored.get("recovery_set_sha256") != accepted
            or restored.get("image_sha256") != recovery["image_sha256"]
            or recovery.get("raw_restore_required") is not True
            or image_result.get("raw_restore_required") is not True
            or capture["settings"]["external_recovery"]["catalog_sha256"] != recovery["catalog_sha256"]):
        raise ValueError("verified raw-capacity-reserved component image required")
    for tree in ("root", "boot"):
        if sha(metadata / (tree + ".manifest.jsonl")) != capture["trees"][tree]["manifest"]["sha256"]:
            raise ValueError("accepted filesystem manifest differs")
    if sha(metadata / "external-restore-map.jsonl") != capture["external_restore_map_sha256"]:
        raise ValueError("accepted exact-source restore map differs")
    image = work / "recovery.img"
    info = image.lstat()
    if (not stat.S_ISREG(info.st_mode) or image.resolve() != image or info.st_nlink != 1
            or info.st_size != recovery["image_bytes"] or sha(image) != recovery["image_sha256"]):
        raise ValueError("new reassembled regular image byte identity differs")
    return recovery, image_result, capture


def rejoin(work, metadata, accepted, raw):
    require_namespace()
    work, metadata, raw = Path(work), Path(metadata), Path(raw)
    if raw != Path("/restored-raw") or not os.statvfs(raw).f_flag & os.ST_RDONLY:
        raise ValueError("fixed readonly exact-source raw workspace required")
    recovery, component, capture = inputs(work, metadata, accepted)
    image = work / "recovery.img"
    descriptor = os.open(image, os.O_RDWR | os.O_NOFOLLOW)
    loop = held = None
    mounted = []
    result = {"schema": "ar-local-system-image-joined-v1", "result": "RUNNING", "started_at": utc(),
              "recovery_set_sha256": accepted, "raw_catalog_sha256": recovery["catalog_sha256"],
              "boot_test": "NOT_TESTED", "original_devices_modified": False}
    write(work / "rejoin-intent.json", result)
    try:
        loop, held = attach_image(image, descriptor, work)
        for tree, number, key in (("root", 2, "root_uuid"), ("boot", 1, "boot_uuid")):
            verify_filesystem_identity(loop, number, image, descriptor, component["identifiers"][key])
            destination = work / ("joined-" + tree)
            destination.mkdir(mode=0o700)
            os.chmod(destination, 0o700)
            options = ["nodev", "nosuid", "noexec", "noatime"]
            if tree == "boot":
                options += fat_options(capture["settings"]["layout"]["boot_mount"])
            run(["/usr/bin/mount", "-o", ",".join(options), require_partition(loop, number, image, descriptor), destination])
            mounted.append(destination)
            verify_tree(destination, metadata / (tree + ".manifest.jsonl"), transforms=component["transforms"][tree], scratch=work)
        full = work / "joined-root.manifest.jsonl"
        result["raw_restore"] = restore_raw(work / "joined-root", raw, metadata / "external-restore-map.jsonl",
                                             recovery["catalog_sha256"], metadata / "root.manifest.jsonl", full)
        restore_metadata(work / "joined-root", full)
        result["root_verify_before_normalization"] = verify_tree(work / "joined-root", full, transforms=component["transforms"]["root"])
        normalized = work / "joined-root.normalized.manifest.jsonl"
        result["offline_normalization"] = normalize(work / "joined-root", full, normalized, accepted, boot=work / "joined-boot")
        restore_metadata(work / "joined-root", normalized)
        result["root_verify"] = verify_tree(work / "joined-root", normalized, transforms=component["transforms"]["root"])
        result["boot_verify"] = verify_tree(work / "joined-boot", metadata / "boot.manifest.jsonl", transforms=component["transforms"]["boot"], scratch=work)
        result.update(result="FULL_OS_AND_EXACT_RAW_RESTORE_VERIFIED", raw_restore_required=False)
    except BaseException as error:
        result.update(result="FAIL", error=type(error).__name__)
        raise
    finally:
        errors = []
        for mount in reversed(mounted):
            try:
                run(["/usr/bin/umount", mount])
            except Exception as error:
                errors.append(type(error).__name__)
        if loop and not errors:
            try:
                require_loop(loop, image, descriptor)
                if result["result"] == "FULL_OS_AND_EXACT_RAW_RESTORE_VERIFIED":
                    result["filesystem_check"] = check_unmounted_filesystems(loop, image, descriptor)
                run(["/usr/sbin/losetup", "--detach", loop])
            except Exception as error:
                errors.append(type(error).__name__)
        if held is not None:
            os.close(held)
        os.close(descriptor)
        if errors:
            result.update(result="FAIL", cleanup_errors=errors)
        if result["result"] == "FULL_OS_AND_EXACT_RAW_RESTORE_VERIFIED":
            result["joined_image_sha256"] = sha(image)
        result["finished_at"] = utc()
        write(work / "image-rejoin-result.json", result)
    if result["result"] != "FULL_OS_AND_EXACT_RAW_RESTORE_VERIFIED":
        raise RuntimeError("raw rejoin filesystem verification/cleanup failed")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recovery-set-sha256", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(rejoin("/scratch", "/input", args.recovery_set_sha256, "/restored-raw")), flush=True)


if __name__ == "__main__":
    main()
