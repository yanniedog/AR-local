"""Only sealed image upload admission, private PID/mount view, Pi UID and NNP."""
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
        raise RuntimeError("root-sealed read-only bounded upload context required")
    os.lseek(descriptor, 0, os.SEEK_SET)
    context = json.loads(os.read(descriptor, 16385))
    if (context.get("schema") != "ar-local-system-recovery-attestation-v1" or context.get("phase") != "upload"
            or context["boot_id"] != Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            or (os.getuid(), os.getgid()) != (context["uid"], context["gid"]) or os.getuid() == 0):
        raise RuntimeError("specific unprivileged image upload context differs")
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines())
    if ([int(value) for value in status["Uid"].split()] != [context["uid"]] * 4
            or [int(value) for value in status["Gid"].split()] != [context["gid"]] * 4):
        raise RuntimeError("all upload UID/GID identities must be the fixed Pi account")
    if status["NoNewPrivs"].strip() != "1" or any(int(status[key].strip(), 16) for key in ("CapEff", "CapPrm", "CapInh", "CapAmb", "CapBnd")):
        raise RuntimeError("image upload requires NNP and every capability dropped")
    if any(Path("/proc/self/ns/" + key).stat().st_ino == context["monitor"]["namespaces"][key] for key in ("pid", "mnt")):
        raise RuntimeError("private PID and mount namespaces required")
    if not os.statvfs("/").f_flag & os.ST_RDONLY or not os.statvfs("/input").f_flag & os.ST_RDONLY:
        raise RuntimeError("image upload root/input views must be read-only")
    credential = Path("/credential.conf")
    before = credential.lstat()
    if before.st_uid != 0 or before.st_gid != context["gid"] or stat.S_IMODE(before.st_mode) != 0o440 or hashlib.sha256(credential.read_bytes()).hexdigest() != context["credential_sha256"]:
        raise RuntimeError("fixed readonly approved OAuth copy differs")
    def guard():
        if time.monotonic() >= context["deadline_monotonic"]:
            raise RuntimeError("image upload deadline reached")
    guard()
    return context, guard


def main():
    context, guard = admission()
    from pi_system_drive_transport import ImageRclone, upload_plan
    path = Path("/input/upload-plan.json")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != context["upload_plan_sha256"]:
        raise RuntimeError("sealed image object plan differs")
    plan = json.loads(raw)
    store = ImageRclone("/credential.conf", context["remote"], context["drive_root_folder_id"], guard)
    result = upload_plan("/input", plan, store, "/scratch", guard)
    with Path("/scratch/upload-result.json").open("x") as stream:
        json.dump(result, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())


if __name__ == "__main__":
    main()
