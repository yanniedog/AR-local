"""Fail-closed Windows OpenSSH transport for the laptop backup receiver."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO


CHUNK = 4 * 1024**2
SSH_POST_EOF_RE = re.compile(
    rb"close - IO is still pending on closed socket\. read:\d+, write:\d+, io:[0-9A-Fa-f]+\r?\n?"
)
REMOTE_HELPER_DIR_RE = re.compile(r"^/tmp/ar-local-laptop-backup\.[A-Za-z0-9]{8}$")
SSH_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
SSH_USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FIXED_SSH_ENDPOINT = ("192.168.20.19", "pi", 22)
FIXED_SSH_HOST_KEY_SHA256 = "4e2433bbc5868e1304f4d4dfd3b833d09cba9e2f9ae3d2586188e4c105b7a836"


def _transport_value(args: object, name: str) -> str:
    value = str(getattr(args, name, "") or "")
    if not value:
        raise ValueError(f"trusted SSH transport lacks {name}")
    return value


def add_transport_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default=os.environ.get("AR_BACKUP_SSH_HOST"))
    parser.add_argument("--ssh-user", default=os.environ.get("AR_BACKUP_SSH_USER"))
    parser.add_argument("--ssh-port", type=int, default=os.environ.get("AR_BACKUP_SSH_PORT"))
    parser.add_argument("--ssh-path", default=os.environ.get("AR_BACKUP_SSH_PATH"))
    parser.add_argument("--ssh-sha256", default=os.environ.get("AR_BACKUP_SSH_SHA256"))
    parser.add_argument("--scp-path", default=os.environ.get("AR_BACKUP_SCP_PATH"))
    parser.add_argument("--scp-sha256", default=os.environ.get("AR_BACKUP_SCP_SHA256"))
    parser.add_argument("--ssh-identity", default=os.environ.get("AR_BACKUP_SSH_IDENTITY"))
    parser.add_argument("--ssh-known-hosts", default=os.environ.get("AR_BACKUP_SSH_KNOWN_HOSTS"))


def _windows_contract_path(value: str, platform: str) -> Path | PureWindowsPath:
    return Path(value) if platform == "nt" else PureWindowsPath(value)


def _trusted_contract(platform: str) -> dict[str, object] | None:
    """Load the protected install contract; direct Windows source runs fail closed."""
    if platform != "nt":
        return None
    root = Path(__file__).resolve().parent.parent
    path = root / "trusted-child.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("trusted SSH contract is unavailable") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 5:
        raise ValueError("trusted SSH contract schema is invalid")
    return value


def _contract_value(contract: dict[str, object], name: str) -> str:
    value = str(contract.get(name, "") or "")
    if not value:
        raise ValueError(f"trusted SSH contract lacks {name}")
    return value


def _same_windows_path(left: object, right: object) -> bool:
    return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(
        os.path.abspath(str(right))
    )


def _validated_executable(
    args: object, name: str, platform: str, contract: dict[str, object] | None
) -> Path | PureWindowsPath:
    executable = _windows_contract_path(_transport_value(args, f"{name}_path"), platform)
    if not executable.is_absolute() or executable.name.lower() != f"{name}.exe":
        raise ValueError("trusted SSH executable must be an absolute OpenSSH path")
    if platform == "nt":
        expected = _transport_value(args, f"{name}_sha256").lower()
        assert contract is not None
        if (
            not _same_windows_path(executable, _contract_value(contract, f"{name}_path"))
            or not hmac.compare_digest(expected, _contract_value(contract, f"{name}_sha256").lower())
        ):
            raise ValueError("trusted SSH executable differs from the protected contract")
        if not SHA256_RE.fullmatch(expected) or not executable.is_file():
            raise ValueError("trusted SSH executable is absent or its hash is invalid")
        if not hmac.compare_digest(sha256_file(Path(executable)), expected):
            raise ValueError("trusted SSH executable hash mismatch")
    return executable


def _validated_contract_file(
    args: object, name: str, platform: str, contract: dict[str, object] | None
) -> Path | PureWindowsPath:
    path = _windows_contract_path(_transport_value(args, name), platform)
    if not path.is_absolute():
        raise ValueError("trusted SSH identity and known_hosts paths must be absolute")
    if platform == "nt":
        assert contract is not None
        contract_name = "ssh_identity" if name == "ssh_identity" else "ssh_known_hosts"
        expected = _contract_value(contract, f"{contract_name}_sha256").lower()
        if (
            not SHA256_RE.fullmatch(expected)
            or not _same_windows_path(path, _contract_value(contract, f"{contract_name}_path"))
            or not Path(path).is_file()
        ):
            raise ValueError("trusted SSH key file differs from the protected contract")
        if not hmac.compare_digest(sha256_file(Path(path)), expected):
            raise ValueError("trusted SSH key file hash mismatch")
        if name == "ssh_known_hosts" and not hmac.compare_digest(expected, FIXED_SSH_HOST_KEY_SHA256):
            raise ValueError("trusted SSH host key is not the fixed backup host key")
    return path


def ssh_options(args: object, *, scp: bool = False, platform: str | None = None) -> list[str]:
    """Return the fixed, non-interactive OpenSSH trust contract."""
    platform = platform or os.name
    contract = _trusted_contract(platform)
    executable = _validated_executable(args, "scp" if scp else "ssh", platform, contract)
    identity = _validated_contract_file(args, "ssh_identity", platform, contract)
    known_hosts = _validated_contract_file(args, "ssh_known_hosts", platform, contract)
    host = _transport_value(args, "host")
    user = _transport_value(args, "ssh_user")
    port = str(getattr(args, "ssh_port", "") or "")
    if not SSH_HOST_RE.fullmatch(host) or ".." in host or not SSH_USER_RE.fullmatch(user):
        raise ValueError("trusted SSH host or user is invalid")
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("trusted SSH port is invalid")
    if (host, user, int(port)) != FIXED_SSH_ENDPOINT:
        raise ValueError("trusted SSH endpoint is not the fixed backup endpoint")
    if contract is not None and (
        host != _contract_value(contract, "ssh_host")
        or user != _contract_value(contract, "ssh_user")
        or int(port) != int(contract.get("ssh_port", 0))
    ):
        raise ValueError("trusted SSH endpoint differs from the protected contract")
    options = [
        str(executable), "-F", "NUL",
        "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
        "-o", "IdentitiesOnly=yes", "-o", "IdentityAgent=none",
        "-o", "PreferredAuthentications=publickey",
        "-o", "PasswordAuthentication=no", "-o", "KbdInteractiveAuthentication=no",
        "-o", "ChallengeResponseAuthentication=no", "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={known_hosts}", "-o", "GlobalKnownHostsFile=NUL",
        "-o", "UpdateHostKeys=no", "-o", "VerifyHostKeyDNS=no",
        "-o", "ForwardAgent=no", "-o", "ClearAllForwardings=yes",
        "-o", "RequestTTY=no", "-i", str(identity), "-P" if scp else "-p", port,
    ]
    if not scp:
        options.extend(("-l", user))
    return options


def ssh_command(args: object, *remote: str, platform: str | None = None) -> list[str]:
    return [*ssh_options(args, platform=platform), _transport_value(args, "host"), *remote]


def scp_command(
    args: object, source: Path, remote: str, *, platform: str | None = None
) -> list[str]:
    destination = f"{_transport_value(args, 'ssh_user')}@{_transport_value(args, 'host')}:{remote}"
    return [*ssh_options(args, scp=True, platform=platform), "-q", str(source), destination]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def stderr_reader(stream: BinaryIO, sink: bytearray) -> None:
    read_available = getattr(stream, "read1", stream.read)
    while True:
        block = read_available(CHUNK)
        if not block:
            return
        sink.extend(block[: max(0, 4 * 1024**2 - len(sink))])


def windows_ssh_post_eof_only(stderr: bytes, *, platform: str | None = None) -> bool:
    """Recognize only the observed Windows OpenSSH post-EOF socket failure."""
    return (platform or os.name) == "nt" and SSH_POST_EOF_RE.fullmatch(stderr) is not None


def ssh_result_acceptable(result: subprocess.CompletedProcess[bytes]) -> bool:
    return (
        (result.returncode == 0 and not result.stderr)
        or windows_ssh_post_eof_only(result.stderr)
    )


def finish_stream_process(
    process: subprocess.Popen[bytes],
    stderr_thread: threading.Thread,
    errors: bytearray,
    *,
    timeout: float = 30,
    drain_timeout: float = 10,
    platform: str | None = None,
) -> int:
    """Finish ssh, accepting only its proven Windows post-EOF hang signature."""
    try:
        code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        deadline = time.monotonic() + drain_timeout
        while not windows_ssh_post_eof_only(bytes(errors), platform=platform) and time.monotonic() < deadline:
            stderr_thread.join(timeout=min(0.1, max(0, deadline - time.monotonic())))
        if not windows_ssh_post_eof_only(bytes(errors), platform=platform):
            raise
        process.kill()
        process.wait(timeout=30)
        stderr_thread.join(timeout=10)
        if stderr_thread.is_alive() or not windows_ssh_post_eof_only(bytes(errors), platform=platform):
            raise RuntimeError("Windows SSH post-EOF termination could not be proven")
        return 0
    stderr_thread.join(timeout=10)
    if stderr_thread.is_alive():
        raise RuntimeError("SSH stderr reader did not terminate")
    if (code or errors) and not windows_ssh_post_eof_only(bytes(errors), platform=platform):
        raise RuntimeError(f"Pi archive stream failed: {bytes(errors).decode('utf-8', 'replace')}")
    return code


def remove_remote_helper(args: object, remote: str) -> None:
    path = PurePosixPath(remote)
    remote_dir = str(path.parent)
    if path.name != "source.py" or not REMOTE_HELPER_DIR_RE.fullmatch(remote_dir):
        raise ValueError("refusing to remove unexpected remote helper path")
    removed = subprocess.run(
        ssh_command(args, "rm", "--", remote),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=30,
        check=False,
    )
    directory = subprocess.run(
        ssh_command(args, "rmdir", "--", remote_dir),
        stdin=subprocess.DEVNULL,
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
        ssh_command(args, "mktemp", "-d", "/tmp/ar-local-laptop-backup.XXXXXXXX"),
        stdin=subprocess.DEVNULL,
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
    try:
        copied = subprocess.run(
            scp_command(args, source, remote),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=30,
        )
        verified = subprocess.run(
            ssh_command(args, "sha256sum", "--", remote),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=30,
        )
        fields = verified.stdout.decode("utf-8", "replace").split()
        mode = subprocess.run(
            ssh_command(args, "stat", "-c", "%a", "--", remote_dir),
            stdin=subprocess.DEVNULL,
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
            raise RuntimeError(
                "failed to transfer and hash-verify reviewed source helper: "
                f"scp={copied.returncode} {copy_error}; verify={verified.returncode} {verify_error}"
            )
    except Exception as transfer_error:
        try:
            remove_remote_helper(args, remote)
        except Exception as cleanup_error:
            raise transfer_error from cleanup_error
        raise
    return remote, helper_sha
