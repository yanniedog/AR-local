"""Fail-closed Windows OpenSSH transport for the laptop backup receiver."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path, PurePosixPath


CHUNK = 4 * 1024**2
SSH_POST_EOF_RE = re.compile(
    rb"close - IO is still pending on closed socket\. read:\d+, write:\d+, io:[0-9A-Fa-f]+\r?\n?"
)
REMOTE_HELPER_DIR_RE = re.compile(r"^/tmp/ar-local-laptop-backup\.[A-Za-z0-9]{8}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def windows_ssh_post_eof_only(stderr: bytes, *, platform: str | None = None) -> bool:
    """Recognize only the observed Windows OpenSSH post-EOF socket failure."""
    return (platform or os.name) == "nt" and SSH_POST_EOF_RE.fullmatch(stderr) is not None


def ssh_result_acceptable(result: subprocess.CompletedProcess[bytes]) -> bool:
    return (
        (result.returncode == 0 and not result.stderr)
        or windows_ssh_post_eof_only(result.stderr)
    )


def remove_remote_helper(args: object, remote: str) -> None:
    path = PurePosixPath(remote)
    remote_dir = str(path.parent)
    if path.name != "source.py" or not REMOTE_HELPER_DIR_RE.fullmatch(remote_dir):
        raise ValueError("refusing to remove unexpected remote helper path")
    removed = subprocess.run(
        ("ssh", "-o", "BatchMode=yes", args.host, "rm", "--", remote),
        capture_output=True,
        timeout=30,
        check=False,
    )
    directory = subprocess.run(
        ("ssh", "-o", "BatchMode=yes", args.host, "rmdir", "--", remote_dir),
        capture_output=True,
        timeout=30,
        check=False,
    )
    failures = [
        f"{label}={result.returncode} {result.stderr.decode('utf-8', 'replace')}"
        for label, result in (("rm", removed), ("rmdir", directory))
        if not ssh_result_acceptable(result)
    ]
    if failures:
        raise RuntimeError("remote helper cleanup failed: " + "; ".join(failures))


def install_remote_helper(args: object) -> tuple[str, str]:
    source = Path(args.source_helper).resolve(strict=True)
    helper_sha = sha256_file(source)
    created = subprocess.run(
        (
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            args.host, "mktemp", "-d", "/tmp/ar-local-laptop-backup.XXXXXXXX",
        ),
        capture_output=True,
        timeout=30,
    )
    remote_dir = created.stdout.decode("utf-8", "replace").strip()
    if not ssh_result_acceptable(created) or not REMOTE_HELPER_DIR_RE.fullmatch(remote_dir):
        raise RuntimeError(
            "failed to create private remote helper directory: "
            + created.stderr.decode("utf-8", "replace")
        )
    remote = f"{remote_dir}/source.py"
    copied = subprocess.run(
        (
            "scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            str(source), f"{args.host}:{remote}",
        ),
        capture_output=True,
    )
    verified = subprocess.run(
        (
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            args.host, "sha256sum", "--", remote,
        ),
        capture_output=True,
        timeout=30,
    )
    fields = verified.stdout.decode("utf-8", "replace").split()
    mode = subprocess.run(
        (
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            args.host, "stat", "-c", "%a", "--", remote_dir,
        ),
        capture_output=True,
        timeout=30,
    )
    if (
        not ssh_result_acceptable(verified)
        or fields != [helper_sha, remote]
        or not ssh_result_acceptable(mode)
        or mode.stdout != b"700\n"
    ):
        copy_error = copied.stderr.decode("utf-8", "replace")
        verify_error = verified.stderr.decode("utf-8", "replace")
        remove_remote_helper(args, remote)
        raise RuntimeError(
            "failed to transfer and hash-verify reviewed source helper: "
            f"scp={copied.returncode} {copy_error}; verify={verified.returncode} {verify_error}"
        )
    return remote, helper_sha
