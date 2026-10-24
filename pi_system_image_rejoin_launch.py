"""Root-owned offline launcher for rejoining a NEW regular recovery image.

Use independently hash-reviewed immutable root staging before first execution.
This utility grants no privilege and accepts no physical-device/mount argument.
It is for an isolated Linux recovery workspace; live Pi phases use their broker.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys


def protected(path):
    if path.resolve(strict=True) != path:
        raise ValueError("canonical readonly protected recovery code required")
    for node in (path, *path.parents):
        info = node.lstat()
        if info.st_uid != 0 or stat.S_ISLNK(info.st_mode) or info.st_mode & (0o222 if node == path else 0o022):
            raise ValueError("recovery code ancestry is not exclusively root controlled")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 1024 ** 2:
        raise ValueError("bounded single-link recovery code required")
    return path.read_bytes()


def command(bundle, work, metadata, raw, accepted):
    # Called only after the root launcher validates the complete module closure.
    from pi_system_namespace import argv_for
    argv = argv_for(bundle, work, "build", [], restored_raw=raw)
    index = argv.index("--cap-drop")
    argv[index:index] = ["--ro-bind", str(bundle / "pi_system_image_rejoin.py"), "/code/pi_system_image_rejoin.py",
                         "--ro-bind", str(metadata), "/input"]
    index = argv.index("/usr/bin/python3")
    argv[index:] = ["/usr/bin/python3", "-E", "-s", "-S", "-B", "/code/pi_system_image_rejoin.py", "--recovery-set-sha256", accepted]
    return argv


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("image-workspace", "metadata", "restored-raw", "source-approval"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--source-approval-sha256", required=True)
    parser.add_argument("--recovery-set-sha256", required=True)
    args = parser.parse_args(argv)
    if os.geteuid() != 0 or not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode:
        raise ValueError("independently protected root entry and Python -I -S -B required")
    own = Path(__file__).resolve()
    if own.name != "pi_system_image_rejoin_launch.py":
        raise ValueError("fixed independently approved recovery launcher required")
    raw = protected(args.source_approval)
    if hashlib.sha256(raw).hexdigest() != args.source_approval_sha256:
        raise ValueError("independently approved recovery source hash differs")
    approved = json.loads(raw)["files"]
    names = {"pi_system_" + name + ".py" for name in ("namespace", "capture", "image", "raw_restore", "filesystems", "sparse", "image_rejoin", "image_rejoin_launch")}
    if set(approved) != names:
        raise ValueError("complete offline recovery closure required")
    verified = {}
    for name, expected in approved.items():
        verified[name] = protected(own.parent / name)
        if hashlib.sha256(verified[name]).hexdigest() != expected:
            raise ValueError("independently reviewed recovery code changed")
    # Load exactly the approved namespace module without adding its directory to
    # sys.path; the worker receives individually bound fixed filenames only.
    import types
    module = types.ModuleType("pi_system_namespace")
    module.__file__ = str(own.parent / "pi_system_namespace.py")
    exec(compile(verified["pi_system_namespace.py"], module.__file__, "exec"), module.__dict__)
    sys.modules["pi_system_namespace"] = module
    work = args.image_workspace
    for path in (work, args.metadata, args.restored_raw):
        if not path.is_absolute() or path.resolve() != path or not path.is_dir() or path.is_symlink():
            raise ValueError("canonical fixed recovery directories required")
    if work.stat().st_uid != 0 or work.stat().st_mode & 0o077:
        raise ValueError("new reassembler workspace must be root-owned private")
    if any(a == b or a in b.parents or b in a.parents for a, b in ((work, args.metadata), (work, args.restored_raw))):
        raise ValueError("recovery inputs must remain outside writable image workspace")
    subprocess.run(command(own.parent, work, args.metadata, args.restored_raw, args.recovery_set_sha256),
                   check=True, close_fds=True, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"})


if __name__ == "__main__":
    main()
