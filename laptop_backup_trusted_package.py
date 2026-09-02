"""Build the immutable input archive for the one-time trusted backup bootstrap."""

from __future__ import annotations

import argparse
import base64
import binascii
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
SSH_HOST = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")
SSH_USER = re.compile(r"[a-z_][a-z0-9_-]{0,31}")
SSH_ED25519_KEY = re.compile(r"ssh-ed25519 [A-Za-z0-9+/]+={0,2}(?: [^\r\n]+)?")
FIXED_SSH_USER = "pi"
FIXED_SSH_PORT = 22
FIXED_SSH_HOST_KEY_BLOB_SHA256 = "84569741c26189ddf0076b4c327e84b8c9df3d9c60cc6688f432190078a9ea7e"


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


def pinned_known_host(path: Path, host: str, port: int) -> bytes:
    expected = host if port == 22 else f"[{host}]:{port}"
    matches: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        fields = raw.split()
        if len(fields) >= 3 and expected in fields[0].split(","):
            key = " ".join(fields[1:])
            if not SSH_ED25519_KEY.fullmatch(key):
                raise ValueError("pinned SSH host key must be one ssh-ed25519 key")
            try:
                key_blob = base64.b64decode(fields[2], validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError("pinned SSH host key encoding is invalid") from exc
            if hashlib.sha256(key_blob).hexdigest() != FIXED_SSH_HOST_KEY_BLOB_SHA256:
                raise ValueError("pinned SSH host key fingerprint is invalid")
            matches.append(f"{expected} {key}")
    if len(matches) != 1:
        raise ValueError("known_hosts must contain exactly one pinned key for the authenticated SSH host")
    return (matches[0] + "\n").encode("ascii")


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
    if (not SSH_HOST.fullmatch(args.ssh_host) or ".." in args.ssh_host or
            not SSH_USER.fullmatch(args.ssh_user) or not 1 <= args.ssh_port <= 65535):
        raise ValueError("trusted SSH host, user, or port is invalid")
    if args.ssh_user != FIXED_SSH_USER or args.ssh_port != FIXED_SSH_PORT:
        raise ValueError("trusted package SSH user or port is not the backup contract")
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
        for name in (
            "run_laptop_backup_trusted_child.ps1", "laptop_backup_dispatcher.py",
            "laptop_backup_dispatcher_security.py", "laptop_backup_atomic.py",
        ):
            shutil.copyfile(candidate / name, root / name)
        shutil.copyfile(args.dispatcher_manifest, root / "dispatcher-manifest.json")
        identity = Path(args.ssh_identity).resolve(strict=True)
        identity_bytes = identity.read_bytes()
        if not (identity_bytes.startswith(b"-----BEGIN OPENSSH PRIVATE KEY-----\n") and
                identity_bytes.rstrip().endswith(b"-----END OPENSSH PRIVATE KEY-----")):
            raise ValueError("SSH identity is not an OpenSSH private key")
        (root / "ssh").mkdir()
        known_host_bytes = pinned_known_host(
            Path(args.ssh_known_hosts).resolve(strict=True), args.ssh_host, args.ssh_port
        )
        (root / "ssh" / "known_hosts").write_bytes(known_host_bytes)
        (root / "operator.sid").write_text(args.operator_sid, encoding="ascii", newline="")
        (root / "protected.sentinel").write_bytes(b"AR-local trusted launcher sentinel\n")

        def installed(name: str) -> str:
            return str(Path(install_root) / name)

        tools = {name: Path(getattr(args, name)).resolve() for name in ("git", "ssh", "scp", "whoami")}
        trusted = {
            "schema_version": 5,
            "authority_path": installed("authority"),
            "atomic_path": installed("laptop_backup_atomic.py"),
            "atomic_sha256": sha256(root / "laptop_backup_atomic.py"),
            "control_root": str(Path(args.control_root)),
            "dispatcher_path": installed("laptop_backup_dispatcher.py"),
            "dispatcher_sha256": sha256(root / "laptop_backup_dispatcher.py"),
            "dispatcher_security_path": installed("laptop_backup_dispatcher_security.py"),
            "dispatcher_security_sha256": sha256(root / "laptop_backup_dispatcher_security.py"),
            "git_path": str(tools["git"]), "git_sha256": sha256(tools["git"]),
            "python_path": installed(str(Path("python") / "python.exe")),
            "python_sha256": sha256(root / "python" / "python.exe"),
            "receiver_path": installed("receiver"),
            "scp_path": str(tools["scp"]), "scp_sha256": sha256(tools["scp"]),
            "ssh_host": args.ssh_host,
            "ssh_identity_path": installed(str(Path("ssh") / "id")),
            "ssh_identity_sha256": hashlib.sha256(identity_bytes).hexdigest(),
            "ssh_known_hosts_path": installed(str(Path("ssh") / "known_hosts")),
            "ssh_known_hosts_sha256": sha256(root / "ssh" / "known_hosts"),
            "ssh_path": str(tools["ssh"]), "ssh_sha256": sha256(tools["ssh"]),
            "ssh_port": args.ssh_port, "ssh_user": args.ssh_user,
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
    value.add_argument("--ssh-host", required=True)
    value.add_argument("--ssh-user", default="pi")
    value.add_argument("--ssh-port", type=int, default=22)
    value.add_argument("--ssh-identity", required=True)
    value.add_argument("--ssh-known-hosts", required=True)
    value.add_argument("--whoami", required=True)
    value.add_argument("--output", required=True)
    return value


if __name__ == "__main__":
    build(parser().parse_args())
