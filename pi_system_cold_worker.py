"""Sealed read-only Drive fetch or independent cap0 ROOT cold restore."""
import hashlib
import json
import os
from pathlib import Path
import stat
import time


def admission(descriptor=3):
    import fcntl
    info = os.fstat(descriptor)
    seals = fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL
    if (info.st_uid != 0 or info.st_nlink != 0 or not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 16384
            or stat.S_IMODE(info.st_mode) != 0o400 or fcntl.fcntl(descriptor, fcntl.F_GET_SEALS) != seals
            or fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY):
        raise RuntimeError("root-sealed read-only cold context required")
    os.lseek(descriptor, 0, os.SEEK_SET)
    context = json.loads(os.read(descriptor, 16385))
    phase = context.get("phase")
    if (context.get("schema") != "ar-local-system-recovery-attestation-v1" or phase not in {"fetch", "restore"}
            or context["boot_id"] != Path("/proc/sys/kernel/random/boot_id").read_text().strip()):
        raise RuntimeError("specific same-boot cold phase required")
    uid, gid = (context["uid"], context["gid"]) if phase == "fetch" else (0, 0)
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines())
    if ([int(value) for value in status["Uid"].split()] != [uid] * 4
            or [int(value) for value in status["Gid"].split()] != [gid] * 4
            or status["NoNewPrivs"].strip() != "1" or os.getgroups() not in ([[], [0]] if phase == "restore" else [[]])
            or any(int(status[key].strip(), 16) for key in ("CapEff", "CapPrm", "CapInh", "CapAmb", "CapBnd"))):
        raise RuntimeError("exact cold identities, NNP and every capability dropped required")
    if (any(Path("/proc/self/ns/" + key).stat().st_ino == context["monitor"]["namespaces"][key] for key in ("pid", "mnt"))
            or Path("/proc/self/ns/user").stat().st_ino != context["monitor"]["namespaces"]["user"]):
        raise RuntimeError("private cold PID/mount namespaces and unchanged UID mapping required")
    if not os.statvfs("/").f_flag & os.ST_RDONLY or not os.statvfs("/input").f_flag & os.ST_RDONLY:
        raise RuntimeError("cold root and independent input must be readonly")
    raw = Path("/input/cold-plan.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != context["cold_plan_sha256"]:
        raise RuntimeError("independent cold catalog identity plan changed")
    plan = json.loads(raw)
    if phase == "fetch":
        credential = Path("/credential.conf")
        before = credential.lstat()
        if (before.st_uid != 0 or before.st_gid != context["gid"] or stat.S_IMODE(before.st_mode) != 0o440
                or hashlib.sha256(credential.read_bytes()).hexdigest() != context["credential_sha256"]):
            raise RuntimeError("readonly approved operation credential COPY differs")
    elif (not os.statvfs("/mirror").f_flag & os.ST_RDONLY or os.stat("/scratch").st_uid != 0
          or Path("/credential.conf").exists()):
        raise RuntimeError("independent ROOT restore requires sealed readonly mirror and no credential")
    def guard():
        if time.monotonic() >= context["deadline_monotonic"]:
            raise RuntimeError("bounded cold phase deadline reached")
    guard()
    return context, plan, guard


def main():
    context, plan, guard = admission()
    from pi_system_cold import fetch, restore
    if context["phase"] == "fetch":
        from pi_plain_backup_transport import Rclone
        from pi_system_drive_transport import ImageRclone
        arguments = ("/credential.conf", context["remote"], context["drive_root_folder_id"], guard)
        result = fetch("/scratch", plan, Rclone(*arguments), ImageRclone(*arguments), guard)
        target = Path("/scratch") / ("fetch-result-" + context["nonce"] + ".json")
    else:
        result = restore("/scratch", "/mirror", plan, guard)
        target = Path("/scratch/cold-restore-result.json")
    result.update(source_closure_sha256=context["source_closure_sha256"], cold_plan_sha256=context["cold_plan_sha256"],
                  nonce=context["nonce"], workspace_id=context["workspace_id"])
    with target.open("x") as stream:
        json.dump(result, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())


if __name__ == "__main__":
    main()
