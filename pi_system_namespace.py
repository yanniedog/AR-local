"""Root operator entry point for fixed, private system-backup workers.

No installer, sudoers rule, shell protocol or service mutation is provided.
Execute only independently hash-reviewed, root-owned read-only staged copies.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

BUNDLE = ("pi_system_namespace.py", "pi_system_capture.py", "pi_system_image.py", "pi_system_raw_restore.py", "pi_system_filesystems.py")
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"}
UNIT = re.compile(r"[A-Za-z0-9@_.:-]+\.(?:service|timer)")
PACKAGE_UNITS = {"apt-daily.service", "apt-daily.timer", "apt-daily-upgrade.service", "apt-daily-upgrade.timer"}
PACKAGE_LOCKS = ("/var/lib/dpkg/lock-frontend", "/var/lib/dpkg/lock", "/var/lib/apt/lists/lock", "/var/cache/apt/archives/lock")


def trusted_file(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError("staged source must be canonical and not symlinked")
    for entry in (*reversed(path.parents), path):
        info = entry.lstat()
        if info.st_uid != 0 or info.st_mode & (0o222 if entry == path else 0o022) or stat.S_ISLNK(info.st_mode):
            raise ValueError("staged source/ancestors must be exclusively root controlled and source read-only")
    if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_nlink != 1:
        raise ValueError("staged source must be a regular file with one link")


def writer_states(plan):
    units = plan["application_writers"]
    if not units or len(set(units)) != len(units) or any(not isinstance(unit, str) or not UNIT.fullmatch(unit) for unit in units):
        raise ValueError("explicit exact application-writer unit inventory required")
    result = {}
    for unit in units:
        state = subprocess.check_output(["/usr/bin/systemctl", "show", unit, "--property=ActiveState", "--value"], env=ENV, text=True).strip()
        if state not in {"inactive", "failed"}:
            raise ValueError("application writer is not quiesced: " + unit)
        result[unit] = state
    return result


def phase_arguments(phase, arguments):
    if phase != "baseline":
        if arguments:
            raise ValueError("this fixed phase accepts no additional worker arguments")
        return []
    names = {"--layout", "--catalog", "--file-index", "--catalog-sha256"}
    values = {}
    if len(arguments) != 8:
        raise ValueError("baseline requires exactly its four reviewed input bindings")
    for name, value in zip(arguments[::2], arguments[1::2]):
        if name not in names or name in values:
            raise ValueError("unknown or duplicate worker argument")
        if name == "--catalog-sha256":
            if not re.fullmatch(r"[a-f0-9]{64}", value):
                raise ValueError("invalid catalog digest")
        elif not value.startswith("/source/root/") or str(PurePosixPath(value)) != value or ".." in PurePosixPath(value).parts:
            raise ValueError("baseline input must be a canonical read-only source path")
        values[name] = value
    return arguments


@contextmanager
def package_lockset(plan):
    """Hold the existing native apt/dpkg record locks without writing bytes."""
    import fcntl
    units = plan["package_writers"]
    if not PACKAGE_UNITS <= set(units):
        raise ValueError("complete apt service/timer inventory required")
    before = writer_states({"application_writers": units})
    descriptors, identities = [], []
    try:
        for name in PACKAGE_LOCKS:
            path = Path(name)
            descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
            descriptors.append(descriptor)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or path.resolve() != path:
                raise ValueError("existing package lock inode is not exclusively root controlled")
            fcntl.lockf(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            identities.append({"path": name, "device": info.st_dev, "inode": info.st_ino})
        audit = subprocess.check_output(["/usr/bin/dpkg", "--audit"], env=ENV, text=True)
        if audit.strip():
            raise ValueError("package database reports an unfinished operation")
        status = hashlib.sha256(Path("/var/lib/dpkg/status").read_bytes()).hexdigest()
        yield {"schema": "ar-local-package-quiescence-v1", "result": "NATIVE_PACKAGE_LOCKS_HELD",
               "units": before, "locks": identities, "dpkg_status_sha256": status,
               "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip()}
        if writer_states({"application_writers": units}) != before or hashlib.sha256(Path("/var/lib/dpkg/status").read_bytes()).hexdigest() != status:
            raise ValueError("package writer state changed during capture phase")
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def argv_for(bundle, work, phase, additional, child_receipt=None, restored_raw=None, package_receipt=None):
    arguments = ["/usr/bin/bwrap", "--die-with-parent", "--new-session", "--unshare-pid", "--unshare-net", "--unshare-ipc", "--unshare-uts",
                 "--tmpfs", "/", "--dir", "/source", "--dir", "/scratch", "--dir", "/code"]
    for runtime in ("/usr", "/lib", "/lib64", "/bin", "/sbin", "/etc"):
        if Path(runtime).exists():
            arguments += ["--ro-bind", runtime, runtime]
    arguments += ["--ro-bind", "/sys", "/sys", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--tmpfs", "/run"]
    if phase in {"baseline", "prepare", "finalize"}:
        arguments += ["--ro-bind", "/", "/source/root", "--ro-bind", "/boot/firmware", "/source/boot"]
        for runtime in ("dev", "proc", "sys", "run", "tmp"):
            arguments += ["--tmpfs", "/source/root/" + runtime]
    arguments += ["--bind", str(work), "/scratch"]
    # The child imports its script directory without site packages. Bind only
    # approved filenames, so an unreviewed sibling cannot shadow the stdlib.
    for name in BUNDLE:
        arguments += ["--ro-bind", str(bundle / name), "/code/" + name]
    arguments += ["--cap-drop", "ALL"]
    for capability in ("CAP_DAC_OVERRIDE", "CAP_DAC_READ_SEARCH", "CAP_CHOWN", "CAP_FOWNER", "CAP_FSETID", "CAP_SETFCAP", "CAP_MKNOD"):
        arguments += ["--cap-add", capability]
    if phase == "build":
        arguments += ["--cap-add", "CAP_SYS_ADMIN", "--dev-bind", "/dev/loop-control", "/dev/loop-control"]
    if child_receipt:
        arguments += ["--ro-bind", str(child_receipt), "/quiescence.json"]
    if restored_raw:
        arguments += ["--ro-bind", str(restored_raw), "/restored-raw"]
    if package_receipt:
        arguments += ["--ro-bind", str(package_receipt), "/package-proof.json"]
    arguments += ["--remount-ro", "/", "--clearenv", "--setenv", "PATH", ENV["PATH"],
                  "--setenv", "LANG", ENV["LANG"], "--setenv", "SQLITE_TMPDIR", "/scratch", "--chdir", "/", "--"]
    if phase in {"build", "compress"}:
        arguments += ["/usr/bin/python3", "-E", "-s", "-S", "-B", "/code/pi_system_image.py", "--command", phase, *additional, "--workspace", "/scratch"]
        if restored_raw:
            arguments += ["--include-restored-raw", "/restored-raw"]
    else:
        arguments += ["/usr/bin/python3", "-E", "-s", "-S", "-B", "/code/pi_system_capture.py", phase, *additional, "--workspace", "/scratch"]
        if phase == "baseline":
            arguments += ["--root", "/source/root", "--boot", "/source/boot", "--workspace-source-relative", work.relative_to("/").as_posix()]
        if phase == "finalize":
            arguments += ["--quiescence", "/quiescence.json"]
        if phase in {"baseline", "prepare", "finalize"}:
            arguments += ["--package-proof", "/package-proof.json"]
    return arguments


def main(argv=None):
    if not sys.flags.isolated or not sys.flags.no_site:
        raise ValueError("protected root entry requires Python -I -S")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("baseline", "prepare", "finalize", "archive", "build", "compress"))
    parser.add_argument("--host-workspace", required=True, type=Path)
    parser.add_argument("--source-approval", required=True, type=Path)
    parser.add_argument("--source-approval-sha256", required=True)
    parser.add_argument("--writer-plan", type=Path)
    parser.add_argument("--restored-raw-workspace", type=Path)
    args, additional = parser.parse_known_args(argv)
    additional = phase_arguments(args.phase, additional)
    if args.restored_raw_workspace:
        path = args.restored_raw_workspace
        if args.phase != "build" or not path.is_absolute() or path.resolve() != path or not path.is_dir():
            raise ValueError("raw restore input must be an existing canonical directory for build only")
    if os.geteuid() != 0:
        raise ValueError("root operator required; no privilege is granted by this tool")
    bundle = Path(__file__).resolve().parent
    trusted_file(args.source_approval)
    approval_bytes = args.source_approval.read_bytes()
    if hashlib.sha256(approval_bytes).hexdigest() != args.source_approval_sha256:
        raise ValueError("independent source approval hash differs")
    approval = json.loads(approval_bytes)
    if set(approval["files"]) != set(BUNDLE):
        raise ValueError("source approval must cover the complete fixed bundle")
    for name in BUNDLE:
        path = bundle / name
        trusted_file(path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != approval["files"][name]:
            raise ValueError("staged source differs from independent review")
    work = args.host_workspace
    if not re.fullmatch(r"/var/lib/ar-local-system-recovery/[a-z0-9-]+", str(work)) or work.resolve() != work:
        raise ValueError("only a new dedicated system-image workspace is supported")
    for parent in reversed(work.parents):
        if not parent.exists():
            parent.mkdir(mode=0o700)
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("workspace ancestors must be root controlled")
    if args.phase == "baseline":
        work.mkdir(mode=0o700)
    if work.lstat().st_uid != 0 or work.lstat().st_mode & 0o077 or not stat.S_ISDIR(work.lstat().st_mode):
        raise ValueError("workspace must be a root-owned private directory")
    child_receipt, before = None, None
    if args.phase == "finalize":
        if not args.writer_plan:
            raise ValueError("finalize requires the operator's complete reviewed writer plan")
        trusted_file(args.writer_plan)
        plan = json.loads(args.writer_plan.read_text())
        before = writer_states(plan)
        child_receipt = work / "quiescence-child.json"
        body = {**plan, "schema": "ar-local-system-quiescence-v1", "result": "QUIESCED",
                "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(), "observed_states": before,
                "writer_inventory_sha256": hashlib.sha256(args.writer_plan.read_bytes()).hexdigest()}
        with child_receipt.open("x") as stream:
            json.dump(body, stream)
            stream.flush()
            os.fsync(stream.fileno())
        child_receipt.chmod(0o400)
    if args.phase in {"baseline", "prepare", "finalize"}:
        if not args.writer_plan:
            raise ValueError("capture phases require the protected writer/package plan")
        trusted_file(args.writer_plan)
        plan = json.loads(args.writer_plan.read_text())
        with package_lockset(plan) as packages:
            package_receipt = work / (args.phase + "-package-proof.json")
            with package_receipt.open("x") as stream:
                json.dump(packages, stream)
                stream.flush()
                os.fsync(stream.fileno())
            package_receipt.chmod(0o400)
            subprocess.run(argv_for(bundle, work, args.phase, additional, child_receipt, args.restored_raw_workspace, package_receipt), env=ENV, check=True, close_fds=True)
    else:
        subprocess.run(argv_for(bundle, work, args.phase, additional, child_receipt, args.restored_raw_workspace), env=ENV, check=True, close_fds=True)
    if before is not None:
        after = writer_states(plan)
        if before != after:
            raise ValueError("application writer state changed during final capture")
        with (work / "quiescence-accepted.json").open("x") as stream:
            json.dump({"result": "PASS", "before": before, "after": after,
                       "frozen_sha256": hashlib.sha256((work / "frozen.json").read_bytes()).hexdigest()}, stream)
            stream.flush()
            os.fsync(stream.fileno())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps({"result": "FAIL", "error": str(error)}), flush=True)
        raise SystemExit(2)
