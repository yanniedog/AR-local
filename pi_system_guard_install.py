"""Install a NEW fixed image closure from independently verified root staging.

This stdlib-only program imports no staged module until every staged input is
root-controlled, immutable and hash-bound. Default is validation only. Explicit
--install requires an occupied native exclusive host/ar-local queue claim. No
unit, timer, account, sudoers policy or existing queue code is changed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

ROOT = Path("/usr/local/lib/ar-local-system-recovery")
PLAIN = Path("/usr/local/lib/ar-local-plain-backup")
ALIASES = {"broker.py", "parent.py", "launch.py", "reconcile.py", "prepare.py", "start.py"}
MODULES = {"pi_system_guard_" + name + ".py" for name in (
    "policy", "host", "resources", "launch", "parent", "reconcile", "writers", "export", "files", "plan", "packet", "install", "start", "cold")}
MODULES |= {"pi_system_" + name + ".py" for name in (
    "capture", "image", "namespace", "filesystems", "raw_restore", "sparse", "image_restore", "image_rejoin", "image_rejoin_launch", "probe", "drive_transport", "upload_worker", "cold", "cold_worker", "cold_normalize")}
MODULES |= {"pi_plain_backup_transport.py", "pi_plain_backup_attestation.py"}
MODULES |= {"pi_plain_backup_restore.py", "pi_drive_backup_manifest.py", "pi_laptop_backup_source.py"}
PLAIN_FILES = {"pi_plain_backup_core.py", "pi_plain_backup_linux.py", "pi_plain_drive_resources.py", "pi_shared_queue_post_hooks.py"}


def protected(path, *, readonly=True):
    if path.resolve(strict=True) != path:
        raise RuntimeError("canonical immutable root staging required")
    for item in (path, *path.parents):
        info = item.lstat()
        if info.st_uid != 0 or stat.S_ISLNK(info.st_mode) or info.st_mode & (0o222 if item == path and readonly else 0o022):
            raise RuntimeError("independent root staging/ancestry is not immutable")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 16 * 1024 ** 2:
        raise RuntimeError("bounded single-link staged source required")
    return path.read_bytes()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def validate(stage, plan_hash, installer_hash):
    own = Path(__file__).resolve()
    if (sys.platform != "linux" or os.geteuid() != 0 or not sys.flags.isolated or not sys.flags.no_site
            or not sys.dont_write_bytecode or sha(protected(own)) != installer_hash):
        raise RuntimeError("independently hash-approved protected root installer and -I -S -B required")
    raw = protected(stage / "plan.json")
    if not re.fullmatch(r"[a-f0-9]{64}", plan_hash) or sha(raw) != plan_hash:
        raise RuntimeError("independently reviewed installation plan differs")
    plan = json.loads(raw)
    if (plan.get("schema") != "ar-local-system-recovery-install-v1" or plan.get("manual_system_recovery") is not True
            or set(plan.get("files", {})) != ALIASES | MODULES or set(plan.get("plain", {})) != PLAIN_FILES
            or plan["files"]["pi_system_guard_install.py"] != installer_hash):
        raise RuntimeError("complete reviewed image closure required")
    payload = {}
    for target, expected in plan["files"].items():
        name = "pi_system_guard_entry.py" if target in ALIASES else target
        body = protected(stage / name)
        if not re.fullmatch(r"[a-f0-9]{64}", expected) or sha(body) != expected:
            raise RuntimeError("reviewed immutable payload differs")
        payload[target] = body
    for name, expected in plan["plain"].items():
        if sha(protected(PLAIN / name, readonly=False)) != expected:
            raise RuntimeError("qualified incumbent plain control changed")
    if (not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*:plaintext-recovery", plan.get("remote", ""))
            or not re.fullmatch(r"[A-Za-z0-9_-]{10,128}", plan.get("drive_root_folder_id", ""))):
        raise RuntimeError("existing private Drive destination must be pinned")
    wrapper = Path("/usr/local/lib/ar-local-drive-reclaim/pi_drive_reclaim.py")
    if sha(protected(wrapper, readonly=False)) != plan.get("wrapper_sha256"):
        raise RuntimeError("qualified independent recovery wrapper changed")
    if sha(protected(Path("/etc/ar-local/drive-write-hold.json"), readonly=False)) != plan.get("global_hold_sha256"):
        raise RuntimeError("existing global Drive hold changed")
    return plan, payload


def admitted():
    import pwd
    group = Path("/proc/self/cgroup").read_text().strip()
    prefix = "0::/system.slice/"
    if not group.startswith(prefix) or not re.fullmatch(r"ar-local-queue-task-[a-f0-9]{32}\.service", group[len(prefix):]):
        raise RuntimeError("admitted manual installation service required")
    queue = Path("/var/lib/shared-pi-queue/state.json")
    descriptor = os.open(queue, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        raw = os.read(descriptor, 1048577)
        if not stat.S_ISREG(info.st_mode) or len(raw) != info.st_size or len(raw) > 1048576:
            raise RuntimeError("bounded native queue state required")
    finally:
        os.close(descriptor)
    jobs = json.loads(raw).get("jobs", [])
    rows = [job for job in jobs if job.get("unit") == group[len(prefix):]]
    if len(rows) != 1:
        raise RuntimeError("unique actual installation owner required")
    job = rows[0]
    if (job.get("state") != "running" or job.get("project") != "ar-local" or job.get("mode") != "exclusive"
            or set(job.get("resources", [])) != {"ar-local", "host"} or job.get("cgroup") != group[3:]
            or any(other.get("id") != job["id"] and other.get("state") != "waiting" for other in jobs)):
        raise RuntimeError("exclusive host/ar-local installation admission required")
    native = Path("/srv/ar-local/data/state/daily-ingest.lock")
    lease = dict(line.split("=", 1) for line in native.read_text().splitlines())
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    proc = Path("/proc") / str(job["pid"])
    ticks = int((proc / "stat").read_text().rsplit(")", 1)[1].split()[19])
    inherited = (proc / "fd/3").stat()
    info = native.lstat()
    if (lease != {"pid": str(job["pid"]), "boot_id": boot, "role": "shared-pi-host-task:" + job["id"], "recovery": "manual"}
            or boot != job["boot_id"] or ticks != job["start_ticks"] or info.st_uid != pwd.getpwnam("pi").pw_uid
            or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or (info.st_dev, info.st_ino) != (inherited.st_dev, inherited.st_ino)):
        raise RuntimeError("installation native lease kernel identity differs")
    return job


def install(plan, payload):
    import pwd
    # These exact helper bytes were validated before this first staged import.
    import types
    helper = types.ModuleType("approved_image_install_files")
    exec(compile(payload["pi_system_guard_files.py"], "<independently-approved-root-helper>", "exec"), helper.__dict__)
    directory, publish, encoded = helper.directory, helper.publish, helper.encoded
    if ROOT.exists():
        raise RuntimeError("existing image installation is preserved; explicit reviewed migration required")
    account = pwd.getpwnam("pi")
    directory(ROOT, 0o755)
    closure = {}
    for name, body in payload.items():
        publish(ROOT / name, body, 0o555)
        closure[str(ROOT / name)] = sha(body)
    closure.update({str(PLAIN / name): checksum for name, checksum in plan["plain"].items()})
    publish(ROOT / "root-control-manifest.json", encoded(closure), 0o444)
    bundle = ("namespace", "capture", "image", "raw_restore", "filesystems", "sparse")
    publish(ROOT / "backend-approval.json", encoded({"files": {"pi_system_" + name + ".py": plan["files"]["pi_system_" + name + ".py"] for name in bundle}}), 0o444)
    for name in ("control", "inputs", "export", "upload"):
        directory(Path("/var/lib/ar-local-system-recovery-" + name), 0o700)
    directory(Path("/var/lib/ar-local-system-recovery"), 0o700)
    directory(Path("/var/lib/ar-local-system-recovery-handoff"), 0o750, account.pw_gid)
    registry = {"schema": "ar-local-system-recovery-reconcile-v1", "callback": str(ROOT / "reconcile.py"),
                "callback_sha256": plan["files"]["reconcile.py"], "source_closure_sha256": sha(json.dumps(closure, sort_keys=True, separators=(",", ":")).encode()),
                "wrapper_sha256": plan["wrapper_sha256"]}
    publish(Path("/etc/ar-local/system-recovery-reconcile.json"), encoded(registry), 0o444)
    publish(ROOT / "installation.json", encoded({"schema": "ar-local-system-recovery-installation-v1", "plan": plan,
                                                "source_closure_sha256": registry["source_closure_sha256"]}), 0o444)
    return {"result": "INSTALLED_NOT_COMMISSIONED", "source_closure_sha256": registry["source_closure_sha256"], "native_probe": "NOT_TESTED"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--installer-sha256", required=True)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args(argv)
    plan, payload = validate(args.stage, args.plan_sha256, args.installer_sha256)
    if args.install:
        admitted()
        result = install(plan, payload)
    else:
        result = {"result": "VALIDATED_NOT_INSTALLED", "files": len(payload)}
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
