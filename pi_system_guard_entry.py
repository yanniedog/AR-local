"""Install identical protected bytes as broker.py/parent.py/launch.py/reconcile.py.

All root import bytes are checked before registering exact module filenames.
An independently reviewed external installer must verify these bytes before the
first execution; self-verification is not a trust anchor for mutable source.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

ROOT = Path("/usr/local/lib/ar-local-system-recovery")
PLAIN = Path("/usr/local/lib/ar-local-plain-backup")
IMAGE_FILES = {"broker.py", "parent.py", "launch.py", "reconcile.py", "prepare.py", "start.py", "pi_system_guard_start.py", "pi_system_guard_policy.py", "pi_system_guard_host.py",
               "pi_system_guard_resources.py", "pi_system_guard_launch.py", "pi_system_guard_parent.py", "pi_system_guard_reconcile.py",
               "pi_system_guard_writers.py", "pi_system_guard_export.py", "pi_system_guard_files.py", "pi_system_guard_plan.py", "pi_system_guard_packet.py", "pi_system_guard_install.py",
               "pi_system_capture.py", "pi_system_image.py", "pi_system_namespace.py", "pi_system_filesystems.py", "pi_system_raw_restore.py",
               "pi_system_sparse.py", "pi_system_image_restore.py", "pi_system_image_rejoin.py", "pi_system_image_rejoin_launch.py", "pi_system_probe.py", "pi_system_drive_transport.py", "pi_system_upload_worker.py",
               "pi_plain_backup_transport.py", "pi_plain_backup_attestation.py", "pi_plain_backup_restore.py", "pi_drive_backup_manifest.py", "pi_laptop_backup_source.py"}
PLAIN_FILES = {"pi_plain_backup_core.py", "pi_plain_backup_linux.py", "pi_plain_drive_resources.py", "pi_shared_queue_post_hooks.py"}


def protected(path):
    if path.resolve() != path:
        raise RuntimeError("noncanonical protected image source")
    for item in (path, *path.parents):
        info = item.lstat()
        if info.st_uid != 0 or stat.S_ISLNK(info.st_mode) or info.st_mode & 0o022:
            raise RuntimeError("image source/ancestry not exclusively root controlled")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 16 * 1024 ** 2:
        raise RuntimeError("unbounded or nonregular image source")


def register_modules(verified_bytes):
    import importlib.abc
    import importlib.util
    allowed = {Path(name).stem: (Path(name), raw) for name, raw in verified_bytes.items()}
    class SealedSource(importlib.abc.Loader):
        def __init__(self, source, raw):
            self.source, self.raw = source, raw
        def create_module(self, spec):
            return None
        def exec_module(self, module):
            # -B stops cache writes, not cache reads. Compile the already
            # hash-verified snapshot; never consult a timestamp-valid .pyc.
            exec(compile(self.raw, str(self.source), "exec"), module.__dict__)
    class FixedModules(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            item = allowed.get(fullname)
            return importlib.util.spec_from_file_location(fullname, item[0], loader=SealedSource(*item)) if item is not None else None
    sys.meta_path.insert(0, FixedModules())


def bootstrap():
    own = Path(__file__).resolve()
    if (sys.platform != "linux" or not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode
            or own.parent != ROOT or own.name not in {"broker.py", "parent.py", "launch.py", "reconcile.py", "prepare.py", "start.py"}
            or (os.geteuid() == 0) != (own.name != "parent.py")):
        raise RuntimeError("fixed protected image entry, UID and Python -I -S -B required")
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines())
    if own.name != "parent.py" and any([int(value) for value in status[key].split()] != [0] * 4 for key in ("Uid", "Gid")):
        raise RuntimeError("root image control requires all four root UID/GID values")
    manifest = ROOT / "root-control-manifest.json"
    protected(manifest)
    document = json.loads(manifest.read_bytes())
    expected = {str(ROOT / name) for name in IMAGE_FILES} | {str(PLAIN / name) for name in PLAIN_FILES}
    if set(document) != expected:
        raise RuntimeError("complete distinct image root closure required")
    verified_bytes = {}
    for name, checksum in document.items():
        path = Path(name)
        protected(path)
        raw = path.read_bytes()
        if not re.fullmatch(r"[a-f0-9]{64}", checksum) or hashlib.sha256(raw).hexdigest() != checksum:
            raise RuntimeError("approved image root import bytes differ")
        verified_bytes[name] = raw
    # Never add either whole control directory to sys.path: even an unrelated
    # root-staged sibling must not shadow a later stdlib import.
    register_modules(verified_bytes)
    return own.name


def main():
    name = bootstrap()
    if name == "start.py":
        from pi_system_guard_start import start
        if len(sys.argv) != 2:
            raise RuntimeError("fixed prepared nonce required")
        print(json.dumps(start(sys.argv[1]), sort_keys=True))
        return 0
    if name == "prepare.py":
        from pi_system_guard_packet import prepare
        if len(sys.argv) not in (4, 5):
            raise RuntimeError("fixed phase, nonce, workspace and optional commissioning nonce required")
        print(json.dumps(prepare(*sys.argv[1:]), sort_keys=True))
        return 0
    if name == "parent.py":
        from pi_system_guard_parent import main as run
        return run(*sys.argv[1:])
    if name == "launch.py":
        from pi_system_guard_launch import main as run
        return run(*sys.argv[1:])
    if name == "reconcile.py":
        from pi_system_guard_reconcile import one_pass
        if len(sys.argv) != 1:
            raise RuntimeError("fixed bounded one-pass image recovery only")
        return one_pass()
    if len(sys.argv) != 3 or sys.argv[1] not in {"acquire", "finish", "recover"} or not re.fullmatch(r"[a-f0-9]{32}", sys.argv[2]):
        raise RuntimeError("fixed broker verb/nonce required")
    import fcntl
    from pi_system_guard_host import ImageHost, STATE
    from pi_system_guard_policy import acquire, finish
    action, nonce = sys.argv[1:]
    private = STATE / nonce
    if private.resolve() != private or private.stat().st_uid != 0 or private.stat().st_mode & 0o077:
        raise RuntimeError("protected image operation state required")
    descriptor = os.open(private / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        host = ImageHost(nonce)
        if action == "acquire":
            result = acquire(host, nonce)
            host.run_worker(host.packet(nonce), host.intent(nonce)["identity"])
        else:
            result = finish(host, nonce, recovery=action == "recover")
        print(json.dumps(result, sort_keys=True))
        return 0
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"result": "BLOCKED", "error": type(error).__name__}))
        raise SystemExit(2)
