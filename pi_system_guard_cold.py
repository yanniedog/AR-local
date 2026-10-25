"""Fixed cold-recovery paths, qualified vendor bindings and phase delegation."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from pi_system_guard_files import directory, encoded, protected, publish, sha

ROOT = Path("/usr/local/lib/ar-local-system-recovery")
PLAIN = Path("/usr/local/lib/ar-local-plain-backup")
WORK = Path("/var/lib/ar-local-system-recovery")
INPUTS = Path("/var/lib/ar-local-system-recovery-inputs")
STATE = Path("/var/lib/ar-local-system-recovery-control")
HANDOFF = Path("/var/lib/ar-local-system-recovery-handoff")
PHASES = {"fetch", "restore", "rejoin"}
CODE = {"pi_system_cold.py", "pi_system_cold_worker.py", "pi_system_drive_transport.py", "pi_plain_backup_transport.py",
        "pi_plain_backup_attestation.py", "pi_plain_backup_restore.py", "pi_drive_backup_manifest.py", "pi_laptop_backup_source.py",
        "pi_system_image_restore.py", "pi_system_sparse.py"}


def vendors():
    receipt = json.loads(protected(Path("/var/lib/ar-local-plain-backup-control/installation.json"), maximum=1024 ** 2, readonly=False))
    result = {name: digest for name, digest in receipt["plan"]["producer"].items() if name.startswith("zstandard/")}
    if not result or "zstandard/__init__.py" not in result or not any(name.endswith(".so") for name in result):
        raise RuntimeError("qualified native zstandard package closure absent")
    for name, expected in result.items():
        if (not re.fullmatch(r"zstandard/[A-Za-z0-9_.-]+", name) or "__pycache__" in name
                or not re.fullmatch("[a-f0-9]{64}", expected)
                or sha(protected(PLAIN / "source" / name, readonly=False)) != expected):
            raise RuntimeError("qualified raw producer vendor source changed")
    return result


def input_plan(packet):
    from pi_system_cold import validate_plan
    raw = protected(INPUTS / packet["workspace_id"] / "cold-plan.json", maximum=16384)
    if sha(raw) != packet["cold_plan_sha256"]:
        raise RuntimeError("independent cold catalog plan changed")
    return validate_plan(json.loads(raw))


def result_path(packet):
    return WORK / packet["workspace_id"] / "cold-restore" / packet["previous_phase_nonce"] / "cold-restore-result.json"


def image_work(packet):
    return WORK / packet["workspace_id"] / "cold-restore" / packet["previous_phase_nonce"] / "image"


def predecessor(packet):
    if packet["phase"] == "fetch":
        return
    nonce = packet.get("previous_phase_nonce", "")
    if not re.fullmatch("[a-f0-9]{32}", nonce) or nonce == packet["nonce"]:
        raise RuntimeError("distinct completed cold predecessor required")
    old = json.loads(protected(STATE / nonce / "packet.json"))
    complete = json.loads(protected(HANDOFF / nonce / "completion.json", readonly=False))
    resources = json.loads(protected(STATE / nonce / "resources.json", readonly=False))
    expected = "fetch" if packet["phase"] == "restore" else "restore"
    if (old.get("phase") != expected or any(old.get(key) != packet[key] for key in
            ("workspace_id", "cold_plan_sha256", "source_closure_sha256", "cold_vendor_sha256",
             "root_control_manifest_sha256", "queue_closure_sha256"))
            or complete.get("schema") != "ar-local-system-recovery-root-completion-v1"
            or complete.get("nonce") != nonce or complete.get("unit") != old.get("unit")
            or complete.get("result") != "RESTORED" or complete.get("phase") != expected or complete.get("resource_acceptance") != "PASS"
            or complete.get("source_closure_sha256") != packet["source_closure_sha256"]
            or complete.get("root_control_manifest_sha256") != packet["root_control_manifest_sha256"]
            or complete.get("queue_closure_sha256") != packet["queue_closure_sha256"]
            or complete.get("cold_plan_sha256") != packet["cold_plan_sha256"]
            or complete.get("cold_vendor_sha256") != packet["cold_vendor_sha256"]
            or complete.get("stop_post_verified") is not True or complete.get("readback") != 60
            or any(complete.get(key) is not True for key in ("untrusted_processes_gone", "owned_loop_terminal", "writers_restored"))
            or resources.get("schema") != "ar-local-system-recovery-resources-v1" or resources.get("phase") != expected
            or resources.get("result") != "PASS" or resources.get("group_clean") is not True):
        raise RuntimeError("actual completed same-closure cold predecessor is unproved")
    if expected == "fetch" and complete.get("credential_custody") != "QUARANTINED":
        raise RuntimeError("cold fetch credential copy custody incomplete")
    if expected == "restore":
        raw = protected(result_path(packet), readonly=False)
        value = json.loads(raw)
        if (value.get("result") != "COLD_RAW_AND_IMAGE_RESTORED_VERIFIED"
                or complete.get("cold_result_sha256") != sha(raw)
                or value.get("source_closure_sha256") != packet["source_closure_sha256"]
                or value.get("cold_plan_sha256") != packet["cold_plan_sha256"]
                or value.get("recovery_set_sha256") != packet["recovery_set_sha256"]):
            raise RuntimeError("independent root cold restore receipt differs")


def controls(packet):
    input_plan(packet)
    actual = vendors()
    if actual != packet["cold_vendor"] or sha(json.dumps(actual, sort_keys=True, separators=(",", ":")).encode()) != packet["cold_vendor_sha256"]:
        raise RuntimeError("cold runtime vendor closure changed")
    predecessor(packet)


def seal_downloads(path, uid):
    """Only after proved fetch cgroup cleanup, beneath a private ROOT ancestor."""
    if path.resolve() != path or not path.is_dir() or path.parent.stat().st_uid != 0 or path.parent.stat().st_mode & 0o077:
        raise RuntimeError("private derived cold download root required")
    for base, dirs, files in os.walk(path, followlinks=False):
        for name in [Path(base), *(Path(base) / item for item in dirs), *(Path(base) / item for item in files)]:
            info = name.lstat()
            if (stat.S_ISLNK(info.st_mode) or info.st_uid not in (0, uid)
                    or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))
                    or stat.S_ISREG(info.st_mode) and info.st_nlink != 1):
                raise RuntimeError("unsafe derived cold object; preserve and refuse")
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                os.fchown(descriptor, 0, 0)
                os.fchmod(descriptor, 0o700 if stat.S_ISDIR(info.st_mode) else 0o400)
            finally:
                os.close(descriptor)


def setup(packet):
    work = WORK / packet["workspace_id"]
    marker = {"schema": "ar-local-system-cold-workspace-v1", "cold_plan_sha256": packet["cold_plan_sha256"],
              "source_closure_sha256": packet["source_closure_sha256"]}
    if work.exists():
        if json.loads(protected(work / "cold-workspace.json")) != marker:
            raise RuntimeError("existing capture or cold workspace identity differs")
    else:
        if packet["phase"] != "fetch":
            raise RuntimeError("cold fetch must create the new workspace")
        directory(work, 0o700)
        publish(work / "cold-workspace.json", encoded(marker))
    downloads = work / "cold-download"
    if packet["phase"] == "fetch":
        if (work / "download-sealed.json").exists():
            raise RuntimeError("sealed cold inputs cannot return to a writable fetch")
        if not downloads.exists():
            downloads.mkdir(mode=0o700)
            os.chown(downloads, packet["uid"], packet["gid"])
            os.chmod(downloads, 0o700)
        info = downloads.lstat()
        if (downloads.resolve() != downloads or not stat.S_ISDIR(info.st_mode) or info.st_uid != packet["uid"]
                or info.st_gid != packet["gid"] or stat.S_IMODE(info.st_mode) != 0o700):
            raise RuntimeError("fixed private Pi fetch directory changed")
    elif packet["phase"] == "restore":
        seal_downloads(downloads, packet["uid"])
        if not (work / "download-sealed.json").exists():
            publish(work / "download-sealed.json", encoded(marker))
        directory(work / "cold-restore", 0o700)
        target = work / "cold-restore" / packet["nonce"]
        if target.exists():
            raise RuntimeError("new cold restore output required; preserve failed artifacts")
        directory(target, 0o700)
    else:
        info = (image_work(packet) / "recovery.img").lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1:
            raise RuntimeError("new ROOT-owned reassembled regular image required")
        if (image_work(packet) / "rejoin-intent.json").exists():
            raise RuntimeError("ambiguous prior rejoin output is preserved; never retry it")


def command(packet):
    phase, work = packet["phase"], WORK / packet["workspace_id"]
    if phase == "rejoin":
        from pi_system_image_rejoin_launch import command as joined
        return joined(ROOT, image_work(packet), work / "cold-download/image",
                      work / "cold-restore" / packet["previous_phase_nonce"] / "raw", packet["recovery_set_sha256"])
    args = ["/usr/bin/bwrap", "--die-with-parent", "--new-session", "--unshare-pid", "--unshare-ipc", "--unshare-uts"]
    if phase == "restore":
        args += ["--unshare-net"]
    args += ["--tmpfs", "/", "--dir", "/etc", "--dir", "/code", "--dir", "/code/zstandard", "--dir", "/scratch", "--dir", "/input"]
    for path in ("/usr", "/lib", "/lib64", "/bin", "/sbin"):
        if Path(path).exists():
            args += ["--ro-bind", path, path]
    if phase == "fetch":
        for path in ("/etc/hosts", "/etc/nsswitch.conf", "/etc/resolv.conf", "/etc/ssl"):
            if Path(path).exists():
                args += ["--ro-bind", str(Path(path).resolve()), path]
    for name in sorted(CODE):
        args += ["--ro-bind", str(ROOT / name), "/code/" + name]
    for name in sorted(packet["cold_vendor"]):
        args += ["--ro-bind", str(PLAIN / "source" / name), "/code/" + name]
    args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/run", "--ro-bind", "/sys", "/sys",
             "--ro-bind", str(INPUTS / packet["workspace_id"] / "cold-plan.json"), "/input/cold-plan.json"]
    scratch = work / "cold-download" if phase == "fetch" else work / "cold-restore" / packet["nonce"]
    args += ["--bind", str(scratch), "/scratch"]
    if phase == "fetch":
        args += ["--ro-bind", str(HANDOFF / packet["nonce"] / "credentials-copy.conf"), "/credential.conf"]
    else:
        args += ["--ro-bind", str(work / "cold-download"), "/mirror"]
    args += ["--cap-drop", "ALL", "--cap-add", "CAP_SETPCAP"]
    if phase == "fetch":
        args += ["--cap-add", "CAP_SETUID", "--cap-add", "CAP_SETGID"]
    args += ["--remount-ro", "/", "--clearenv", "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "LC_ALL", "C",
             "--setenv", "SQLITE_TMPDIR", "/scratch", "--chdir", "/scratch", "--", "/usr/bin/setpriv"]
    if phase == "fetch":
        args += ["--reuid", str(packet["uid"]), "--regid", str(packet["gid"]), "--clear-groups"]
    args += ["--no-new-privs", "--inh-caps=-all", "--ambient-caps=-all", "--bounding-set=-all", "--",
             "/usr/bin/python3", "-E", "-s", "-S", "-B", "/code/pi_system_cold_worker.py"]
    return args


def terminal_result(packet):
    """Read only receipts written by supervised cap0/root recovery code."""
    plan = input_plan(packet)
    if packet["phase"] == "restore":
        path = WORK / packet["workspace_id"] / "cold-restore" / packet["nonce"] / "cold-restore-result.json"
        raw = protected(path, readonly=False)
        result = json.loads(raw)
        if (result.get("result") != "COLD_RAW_AND_IMAGE_RESTORED_VERIFIED" or result.get("nonce") != packet["nonce"]
                or result.get("workspace_id") != packet["workspace_id"]
                or result.get("cold_plan_sha256") != packet["cold_plan_sha256"]
                or result.get("source_closure_sha256") != packet["source_closure_sha256"]
                or result.get("raw", {}).get("result") != "FILES_RESTORED_VERIFIED"
                or result.get("raw", {}).get("catalog_sha256") != plan["raw_catalog_sha256"]
                or result.get("image", {}).get("result") != "REGULAR_IMAGE_REASSEMBLED_VERIFIED"
                or result.get("image", {}).get("recovery_set_sha256") != result.get("recovery_set_sha256")
                or any(result.get(key) != plan[key] for key in ("raw_catalog_sha256", "image_catalog_sha256"))):
            raise RuntimeError("actual independent ROOT cold restore result differs")
    else:
        raw = protected(image_work(packet) / "image-rejoin-result.json", readonly=False)
        result = json.loads(raw)
        if (result.get("result") != "FULL_OS_AND_EXACT_RAW_RESTORE_VERIFIED"
                or result.get("filesystem_check", {}).get("result") != "PASS"
                or any(result.get(key, {}).get("result") != "PASS" for key in
                       ("root_verify_before_normalization", "root_verify", "boot_verify"))
                or result.get("offline_normalization", {}).get("result") != "OFFLINE_RUNTIME_CUSTODY_RETIRED"
                or result.get("offline_normalization", {}).get("persistent_boot_policy") != "NEW_OFFLINE_EXPLICIT_SYSCTL60"
                or any(not re.fullmatch("[a-f0-9]{64}", result.get("offline_normalization", {}).get(key, ""))
                       for key in ("receipt_sha256", "manifest_sha256", "original_manifest_sha256"))
                or result.get("cleanup_errors") or result.get("raw_restore_required") is not False
                or result.get("raw_catalog_sha256") != plan["raw_catalog_sha256"]
                or result.get("recovery_set_sha256") != packet["recovery_set_sha256"]
                or not re.fullmatch("[a-f0-9]{64}", result.get("joined_image_sha256", ""))):
            raise RuntimeError("actual full joined image/cleanup proof differs")
    return sha(raw), result
