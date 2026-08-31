"""Build the immutable input archive for the one-time trusted backup bootstrap."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import zipfile
import re


CANONICAL_ORIGIN = "https://github.com/yanniedog/AR-local.git"
FIXED_TIMESTAMP = (2026, 1, 1, 0, 0, 0)
SHA40 = re.compile(r"[0-9a-f]{40}")
SID = re.compile(r"S-1-5-21-(?:[0-9]+-){3}[0-9]+")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-C", str(repo), *args), check=True, capture_output=True, text=True
    ).stdout.strip()


def require_source(repo: Path, commit: str, label: str) -> None:
    if not repo.is_dir() or git(repo, "rev-parse", "HEAD").lower() != commit:
        raise ValueError(f"{label} is not at its exact commit")
    if git(repo, "status", "--porcelain"):
        raise ValueError(f"{label} is dirty")


def clone_exact(source: Path, destination: Path, commit: str) -> None:
    subprocess.run(
        ("git", "-c", "core.autocrlf=false", "clone", "--quiet", "--no-hardlinks", "--no-checkout",
         str(source), str(destination)), check=True
    )
    git(destination, "remote", "set-url", "origin", CANONICAL_ORIGIN)
    git(destination, "-c", "core.autocrlf=false", "checkout", "--quiet", "--detach", commit)
    if git(destination, "rev-parse", "HEAD").lower() != commit or git(destination, "status", "--porcelain"):
        raise ValueError("standalone protected checkout is not exact and clean")
    # Clone reflogs and the checkout-populated index contain timestamps and file
    # stat data.  Remove that nondeterministic metadata, rebuild a canonical
    # tree-only index, and disable future reflogs.  GIT_OPTIONAL_LOCKS=0 in the
    # protected runtime prevents read-only status checks from refreshing it.
    metadata = destination / ".git"
    shutil.rmtree(metadata / "logs", ignore_errors=True)
    shutil.rmtree(metadata / "hooks", ignore_errors=True)
    for name in ("index", "FETCH_HEAD", "ORIG_HEAD", "COMMIT_EDITMSG"):
        (metadata / name).unlink(missing_ok=True)
    git(destination, "config", "core.logAllRefUpdates", "false")
    git(destination, "read-tree", "HEAD")


def copy_plain_tree(source: Path, destination: Path) -> None:
    if source.is_symlink():
        raise ValueError(f"reparse/symlink source is forbidden: {source}")
    destination.mkdir(parents=True)
    for item in sorted(source.iterdir(), key=lambda value: value.name.casefold()):
        if item.is_symlink():
            raise ValueError(f"reparse/symlink source is forbidden: {item}")
        target = destination / item.name
        if item.is_dir():
            copy_plain_tree(item, target)
        elif item.is_file() and item.suffix.lower() not in {".pyc", ".pyo", ".pth", ".egg-link"} and \
                item.name.lower() not in {"sitecustomize.py", "usercustomize.py"} and not item.name.lower().endswith("._pth"):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item, target)


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def write_zip(root: Path, output: Path) -> None:
    files = sorted((path for path in root.rglob("*") if path.is_file()), key=lambda p: p.as_posix().casefold())
    seen: set[str] = set()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = PurePosixPath(path.relative_to(root).as_posix())
            folded = str(relative).casefold()
            if folded in seen:
                raise ValueError(f"case-insensitive duplicate package path: {relative}")
            seen.add(folded)
            info = zipfile.ZipInfo(str(relative), FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100444 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def build(args: argparse.Namespace) -> dict[str, object]:
    if not SHA40.fullmatch(args.candidate_sha) or not SHA40.fullmatch(args.authority_sha):
        raise ValueError("candidate or authority commit is invalid")
    if not SID.fullmatch(args.operator_sid):
        raise ValueError("operator SID is invalid")
    candidate = Path(args.candidate_repo).resolve()
    authority = Path(args.authority_repo).resolve()
    python_root = Path(args.python_root).resolve()
    output = Path(args.output).resolve()
    if output.exists():
        raise ValueError("trusted package output already exists")
    require_source(candidate, args.candidate_sha, "candidate repository")
    require_source(authority, args.authority_sha, "authority repository")
    if not (python_root / "python.exe").is_file():
        raise ValueError("Python runtime root lacks python.exe")
    install_root = str(Path(args.install_root))
    with tempfile.TemporaryDirectory(prefix="ar-trusted-package-") as temporary:
        root = Path(temporary) / "payload"
        root.mkdir()
        clone_exact(candidate, root / "receiver", args.candidate_sha)
        clone_exact(authority, root / "authority", args.authority_sha)
        copy_plain_tree(python_root, root / "python")
        shutil.copyfile(args.launcher, root / "launcher.exe")
        for name in ("run_laptop_backup_trusted_child.ps1", "laptop_backup_dispatcher.py", "laptop_backup_atomic.py"):
            shutil.copyfile(candidate / name, root / name)
        shutil.copyfile(args.dispatcher_manifest, root / "dispatcher-manifest.json")
        (root / "operator.sid").write_text(args.operator_sid, encoding="ascii", newline="")
        (root / "protected.sentinel").write_bytes(b"AR-local trusted launcher sentinel\n")

        def installed(name: str) -> str:
            return str(Path(install_root) / name)

        tools = {name: Path(getattr(args, name)).resolve() for name in ("git", "ssh", "scp", "whoami")}
        trusted = {
            "schema_version": 3,
            "authority_path": installed("authority"),
            "atomic_path": installed("laptop_backup_atomic.py"),
            "atomic_sha256": sha256(root / "laptop_backup_atomic.py"),
            "control_root": str(Path(args.control_root)),
            "dispatcher_path": installed("laptop_backup_dispatcher.py"),
            "dispatcher_sha256": sha256(root / "laptop_backup_dispatcher.py"),
            "git_path": str(tools["git"]), "git_sha256": sha256(tools["git"]),
            "python_path": installed(str(Path("python") / "python.exe")),
            "python_sha256": sha256(root / "python" / "python.exe"),
            "receiver_path": installed("receiver"),
            "scp_path": str(tools["scp"]), "scp_sha256": sha256(tools["scp"]),
            "ssh_path": str(tools["ssh"]), "ssh_sha256": sha256(tools["ssh"]),
            "whoami_path": str(tools["whoami"]), "whoami_sha256": sha256(tools["whoami"]),
        }
        (root / "trusted-child.json").write_bytes(canonical_json(trusted))
        file_hashes = {
            path.relative_to(root).as_posix(): sha256(path)
            for path in root.rglob("*") if path.is_file()
        }
        package_manifest = {
            "schema_version": 1,
            "candidate_code_sha": args.candidate_sha,
            "authority_commit": args.authority_sha,
            "operator_sid": args.operator_sid,
            "install_root": install_root,
            "control_root": str(Path(args.control_root)),
            "files": dict(sorted(file_hashes.items())),
        }
        (root / "package-manifest.json").write_bytes(canonical_json(package_manifest))
        output.parent.mkdir(parents=True, exist_ok=True)
        write_zip(root, output)
    result = {"package": str(output), "sha256": sha256(output), **package_manifest}
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return result


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--candidate-repo", required=True)
    value.add_argument("--candidate-sha", required=True)
    value.add_argument("--authority-repo", required=True)
    value.add_argument("--authority-sha", required=True)
    value.add_argument("--python-root", required=True)
    value.add_argument("--launcher", required=True)
    value.add_argument("--dispatcher-manifest", required=True)
    value.add_argument("--install-root", required=True)
    value.add_argument("--control-root", required=True)
    value.add_argument("--operator-sid", required=True)
    value.add_argument("--git", required=True)
    value.add_argument("--ssh", required=True)
    value.add_argument("--scp", required=True)
    value.add_argument("--whoami", required=True)
    value.add_argument("--output", required=True)
    return value


if __name__ == "__main__":
    build(parser().parse_args())
