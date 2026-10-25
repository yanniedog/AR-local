"""Fixed exact-phase root launch; no shell, candidate path or physical disk API."""
import json
import os
from pathlib import Path
import sys

from pi_shared_queue_post_hooks import root_json
from pi_system_guard_host import ImageHost, ROOT, WORK


def sandbox_command(packet):
    phase, work = packet["phase"], WORK / packet["workspace_id"]
    if phase in {"fetch", "restore", "rejoin"}:
        from pi_system_guard_cold import command
        return command(packet)
    if phase == "upload":
        from pi_system_guard_export import EXPORT, UPLOAD
        args = ["/usr/bin/bwrap", "--die-with-parent", "--new-session", "--unshare-pid", "--unshare-ipc", "--unshare-uts",
                "--tmpfs", "/", "--dir", "/etc", "--dir", "/code", "--dir", "/scratch", "--dir", "/input"]
        for path in ("/usr", "/lib", "/lib64", "/bin", "/sbin"):
            if Path(path).exists():
                args += ["--ro-bind", path, path]
        for path in ("/etc/hosts", "/etc/nsswitch.conf", "/etc/resolv.conf", "/etc/ssl"):
            if Path(path).exists():
                args += ["--ro-bind", str(Path(path).resolve()), path]
        for name in ("pi_system_upload_worker.py", "pi_system_drive_transport.py", "pi_plain_backup_transport.py", "pi_plain_backup_attestation.py"):
            args += ["--ro-bind", str(ROOT / name), "/code/" + name]
        args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/run", "--ro-bind", "/sys", "/sys",
                 "--ro-bind", str(EXPORT / packet["nonce"]), "/input",
                 "--bind", str(UPLOAD / packet["nonce"]), "/scratch", "--ro-bind", str(ImageHost(packet["nonce"]).public / "credentials-copy.conf"), "/credential.conf",
                 "--cap-drop", "ALL", "--cap-add", "CAP_SETUID", "--cap-add", "CAP_SETGID", "--cap-add", "CAP_SETPCAP",
                 "--remount-ro", "/", "--clearenv", "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "LC_ALL", "C", "--chdir", "/scratch", "--",
                 "/usr/bin/setpriv", "--reuid", str(packet["uid"]), "--regid", str(packet["gid"]), "--clear-groups", "--no-new-privs",
                 "--inh-caps=-all", "--ambient-caps=-all", "--bounding-set=-all", "--", "/usr/bin/python3", "-E", "-s", "-S", "-B", "/code/pi_system_upload_worker.py"]
        return args
    from pi_system_namespace import argv_for
    if phase == "PROBE":
        args = argv_for(ROOT, work, "build", [], probe=True)
        start = args.index("/usr/bin/python3")
        args[start:] = ["/usr/bin/python3", "-E", "-s", "-S", "-B", "/code/pi_system_probe.py", "--workspace", "/scratch"]
        return args
    extra = []
    if phase == "baseline":
        prefix = "/source/root/var/lib/ar-local-system-recovery-inputs/" + packet["workspace_id"] + "/"
        extra = ["--layout", prefix + "layout.json", "--catalog", prefix + "raw-catalog.json", "--file-index", prefix + "raw-index.jsonl", "--catalog-sha256", packet["raw_catalog_sha256"]]
    receipt = work / "quiescence-child.json" if phase == "finalize" else None
    package = work / (phase + "-package-proof.json") if phase in {"baseline", "prepare", "finalize"} else None
    return argv_for(ROOT, work, phase, extra, receipt, package_receipt=package)


def main(nonce):
    host = ImageHost(nonce)
    packet = host.packet(nonce)
    if packet["phase"] in {"fetch", "restore", "rejoin"}:
        from pi_system_guard_cold import controls, setup
        controls(packet)
        setup(packet)
        args = sandbox_command(packet)
        os.execve(args[0], args, {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"})
    if packet["phase"] in {"PROBE", "upload"}:
        if packet["phase"] == "PROBE":
            (WORK / packet["workspace_id"]).mkdir(mode=0o700)
            os.chmod(WORK / packet["workspace_id"], 0o700)
        else:
            from pi_system_guard_export import prepare_export
            prepare_export(packet)
        args = sandbox_command(packet)
        os.execve(args[0], args, {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"})
    from pi_system_guard_writers import quiesce, restore
    from pi_system_namespace import main as namespace
    quiesce(host, packet)
    arguments = [packet["phase"], "--host-workspace", str(WORK / packet["workspace_id"]),
                 "--source-approval", str(ROOT / "backend-approval.json"), "--source-approval-sha256", packet["backend_approval_sha256"]]
    if packet["phase"] in {"baseline", "prepare", "finalize"}:
        arguments += ["--writer-plan", "/var/lib/ar-local-system-recovery-inputs/" + packet["workspace_id"] + "/writer-plan.json"]
    if packet["phase"] == "baseline":
        command = sandbox_command(packet)
        start = command.index("/code/pi_system_capture.py")
        worker = command[start + 2:]
        # Only the four baseline data bindings, never the fixed workspace/source controls.
        for name in ("--layout", "--catalog", "--file-index", "--catalog-sha256"):
            index = worker.index(name)
            arguments += [name, worker[index + 1]]
    try:
        return namespace(arguments)
    finally:
        restore(host, packet)
