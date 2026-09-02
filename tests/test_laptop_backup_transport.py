"""Transport-specific safety tests for the laptop pull-backup protocol."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import threading
from argparse import Namespace
from pathlib import Path, PureWindowsPath

import pytest

import laptop_backup_transport as transport
import laptop_pull_backup as receiver


def _native_transport_args(tmp_path: Path, **values: object) -> Namespace:
    ssh = tmp_path / "ssh.exe"
    scp = tmp_path / "scp.exe"
    identity = tmp_path / "id"
    known_hosts = tmp_path / "known_hosts"
    ssh.write_bytes(b"mock ssh executable")
    scp.write_bytes(b"mock scp executable")
    identity.write_bytes(b"mock private key")
    known_hosts.write_bytes(b"fixed known host")
    defaults: dict[str, object] = {
        "host": "192.168.20.19", "ssh_user": "pi", "ssh_port": 22,
        "ssh_path": str(ssh.resolve()), "ssh_sha256": hashlib.sha256(ssh.read_bytes()).hexdigest(),
        "scp_path": str(scp.resolve()), "scp_sha256": hashlib.sha256(scp.read_bytes()).hexdigest(),
        "ssh_identity": str(identity.resolve()),
        "ssh_known_hosts": str(known_hosts.resolve()),
    }
    defaults.update(values)
    return Namespace(**defaults)


def _portable_transport_args(**values: object) -> Namespace:
    defaults: dict[str, object] = {
        "host": "192.168.20.19", "ssh_user": "pi", "ssh_port": 22,
        "ssh_path": r"C:\Windows\System32\OpenSSH\ssh.exe", "ssh_sha256": "a" * 64,
        "scp_path": r"C:\Windows\System32\OpenSSH\scp.exe", "scp_sha256": "b" * 64,
        "ssh_identity": r"C:\Program Files\AR-local\ssh\id",
        "ssh_known_hosts": r"C:\Program Files\AR-local\ssh\known_hosts",
    }
    defaults.update(values)
    return Namespace(**defaults)


def trusted_transport_args(tmp_path: Path | None = None, **values: object) -> Namespace:
    if os.name == "nt":
        if tmp_path is None:
            raise AssertionError("native Windows transport tests require an isolated executable fixture")
        return _native_transport_args(tmp_path, **values)
    return _portable_transport_args(**values)


def _native_contract(args: Namespace) -> dict[str, object]:
    return {
        "schema_version": 5,
        "ssh_host": args.host,
        "ssh_user": args.ssh_user,
        "ssh_port": args.ssh_port,
        "ssh_path": args.ssh_path,
        "ssh_sha256": args.ssh_sha256,
        "scp_path": args.scp_path,
        "scp_sha256": args.scp_sha256,
        "ssh_identity_path": args.ssh_identity,
        "ssh_identity_sha256": transport.sha256_file(Path(args.ssh_identity)),
        "ssh_known_hosts_path": args.ssh_known_hosts,
        "ssh_known_hosts_sha256": transport.FIXED_SSH_HOST_KEY_SHA256,
    }


def _authenticate_native_fixture(
    monkeypatch: pytest.MonkeyPatch, args: Namespace
) -> None:
    if os.name != "nt":
        return
    contract = _native_contract(args)
    host_key_hash = transport.sha256_file(Path(args.ssh_known_hosts))
    contract["ssh_known_hosts_sha256"] = host_key_hash
    monkeypatch.setattr(transport, "FIXED_SSH_HOST_KEY_SHA256", host_key_hash)
    monkeypatch.setattr(transport, "_trusted_contract", lambda _platform: contract)


def test_windows_ssh_post_eof_signature_is_exact() -> None:
    expected = b"close - IO is still pending on closed socket. read:1, write:0, io:000001AB\r\n"
    assert transport.windows_ssh_post_eof_only(expected, platform="nt")
    assert not transport.windows_ssh_post_eof_only(expected + b"remote failure\n", platform="nt")


def test_ssh_command_has_no_path_agent_user_config_or_interactive_fallback(tmp_path: Path) -> None:
    args = _portable_transport_args()
    command = transport.ssh_command(args, "printf", "PASS", platform="posix")
    assert command[0] == args.ssh_path
    assert command[-3:] == [args.host, "printf", "PASS"]
    required = {
        "NUL", "BatchMode=yes", "IdentitiesOnly=yes", "IdentityAgent=none",
        "PreferredAuthentications=publickey", "PasswordAuthentication=no",
        "KbdInteractiveAuthentication=no", "ChallengeResponseAuthentication=no",
        "StrictHostKeyChecking=yes", f"UserKnownHostsFile={args.ssh_known_hosts}",
        "GlobalKnownHostsFile=NUL", "UpdateHostKeys=no", "VerifyHostKeyDNS=no",
        "ForwardAgent=no", "ClearAllForwardings=yes", "RequestTTY=no",
        args.ssh_identity, args.ssh_user, args.host,
    }
    assert required.issubset(set(command))
    assert command[:3] == [args.ssh_path, "-F", "NUL"]
    assert "ssh" not in command and "scp" not in command


def test_windows_transport_paths_validate_on_portable_ci() -> None:
    args = _portable_transport_args()
    command = transport.ssh_options(args, platform="posix")
    assert command[0] == args.ssh_path
    with pytest.raises(ValueError, match="absolute OpenSSH path"):
        transport.ssh_options(_portable_transport_args(ssh_path="ssh.exe"), platform="posix")


def test_native_transport_refuses_uninstalled_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = tmp_path / "receiver" / "laptop_backup_transport.py"
    module.parent.mkdir()
    module.write_text("# fixture\n", encoding="utf-8")
    monkeypatch.setattr(transport, "__file__", str(module))
    with pytest.raises(ValueError, match="contract is unavailable"):
        transport._trusted_contract("nt")


def test_native_transport_requires_protected_hash_bound_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    args = _native_transport_args(tmp_path)
    contract = _native_contract(args)
    Path(args.ssh_known_hosts).write_bytes(b"fixed known host")
    contract["ssh_known_hosts_sha256"] = transport.sha256_file(Path(args.ssh_known_hosts))
    monkeypatch.setattr(transport, "FIXED_SSH_HOST_KEY_SHA256", contract["ssh_known_hosts_sha256"])
    monkeypatch.setattr(transport, "_trusted_contract", lambda _platform: contract)
    assert transport.ssh_options(args, platform="nt")[0] == args.ssh_path
    args.ssh_sha256 = "0" * 64
    with pytest.raises(ValueError, match="differs from the protected contract"):
        transport.ssh_options(args, platform="nt")
    args.ssh_sha256 = contract["ssh_sha256"]
    Path(args.ssh_identity).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="key file hash mismatch"):
        transport.ssh_options(args, platform="nt")


def test_transport_rejects_non_backup_endpoint() -> None:
    with pytest.raises(ValueError, match="fixed backup endpoint"):
        transport.ssh_options(_portable_transport_args(host="192.0.2.10"), platform="posix")


def test_hung_windows_ssh_is_killed_only_after_proven_post_eof() -> None:
    signature = bytearray(b"close - IO is still pending on closed socket. read:1, write:0, io:000001AB\r\n")

    class Process:
        killed = False
        waits = 0

        def wait(self, timeout: float) -> int:
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired(("ssh",), timeout)
            return -9

        def kill(self) -> None:
            self.killed = True

    class Thread:
        def join(self, timeout: float) -> None:
            assert timeout <= 10

        def is_alive(self) -> bool:
            return False

    process = Process()
    assert transport.finish_stream_process(
        process, Thread(), signature, timeout=0.01, platform="nt"
    ) == 0
    assert process.killed


def test_hung_ssh_without_post_eof_proof_fails_closed() -> None:
    class Process:
        def wait(self, timeout: float) -> int:
            raise subprocess.TimeoutExpired(("ssh",), timeout)

    class Thread:
        def join(self, timeout: float) -> None:
            pass

    with pytest.raises(subprocess.TimeoutExpired):
        transport.finish_stream_process(
            Process(), Thread(), bytearray(), timeout=0.01, drain_timeout=0.01
        )


def test_delayed_complete_post_eof_signature_is_bounded_and_accepted() -> None:
    errors = bytearray(b"close - IO is still pending")
    complete = b"close - IO is still pending on closed socket. read:1, write:0, io:000001AB\r\n"

    class Process:
        killed = False
        waits = 0

        def wait(self, timeout: float) -> int:
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired(("ssh",), timeout)
            return -9

        def kill(self) -> None:
            self.killed = True

    class Thread:
        joins = 0

        def join(self, timeout: float) -> None:
            self.joins += 1
            if self.joins == 2:
                errors[:] = complete

        def is_alive(self) -> bool:
            return False

    process = Process()
    assert transport.finish_stream_process(
        process, Thread(), errors, timeout=0.01, drain_timeout=1, platform="nt"
    ) == 0
    assert process.killed


def test_post_eof_signature_is_read_from_live_pipe_before_process_exit() -> None:
    signature = b"close - IO is still pending on closed socket. read:1, write:0, io:000001AB\r\n"
    command = [
        sys.executable,
        "-c",
        "import sys,time; sys.stderr.buffer.write(" + repr(signature) + "); sys.stderr.flush(); time.sleep(30)",
    ]
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert process.stderr is not None
    errors = bytearray()
    thread = threading.Thread(target=receiver.stderr_reader, args=(process.stderr, errors), daemon=True)
    thread.start()
    try:
        assert transport.finish_stream_process(
            process, thread, errors, timeout=0.1, drain_timeout=2, platform="nt"
        ) == 0
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
    assert bytes(errors) == signature


def test_helper_copy_accepts_spurious_windows_status_only_after_remote_hash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    helper = tmp_path / "helper.py"
    helper.write_text("print('safe')\n", encoding="utf-8")
    digest = receiver.sha256_file(helper)
    remote_dir = "/tmp/ar-local-laptop-backup.Ab12Cd34"
    remote = f"{remote_dir}/source.py"
    post_eof = b"close - IO is still pending on closed socket. read:1, write:0, io:000001AB\r\n"
    results = iter((
        subprocess.CompletedProcess(("ssh",), 3221226356, f"{remote_dir}\n".encode(), post_eof),
        subprocess.CompletedProcess(("scp",), 1, b"", b""),
        subprocess.CompletedProcess(("ssh",), 3221226356, f"{digest}  {remote}\n".encode(), post_eof),
        subprocess.CompletedProcess(("ssh",), 3221226356, b"700\n", post_eof),
    ))
    monkeypatch.setattr(transport.subprocess, "run", lambda *_args, **_kwargs: next(results))
    monkeypatch.setattr(transport, "windows_ssh_post_eof_only", lambda value: value.startswith(b"close - IO"))
    args = trusted_transport_args(tmp_path, source_helper=helper)
    _authenticate_native_fixture(monkeypatch, args)
    assert transport.install_remote_helper(args) == (remote, digest)


def test_helper_transport_detaches_scheduled_task_stdin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    helper = tmp_path / "helper.py"
    helper.write_text("print('safe')\n", encoding="utf-8")
    digest = receiver.sha256_file(helper)
    remote_dir = "/tmp/ar-local-laptop-backup.Ab12Cd34"
    remote = f"{remote_dir}/source.py"
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    results = iter((
        subprocess.CompletedProcess(("ssh",), 0, f"{remote_dir}\n".encode(), b""),
        subprocess.CompletedProcess(("scp",), 0, b"", b""),
        subprocess.CompletedProcess(("ssh",), 0, f"{digest}  {remote}\n".encode(), b""),
        subprocess.CompletedProcess(("ssh",), 0, b"700\n", b""),
    ))

    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append((args, kwargs))
        return next(results)

    monkeypatch.setattr(transport.subprocess, "run", run)
    args = trusted_transport_args(tmp_path, source_helper=helper)
    _authenticate_native_fixture(monkeypatch, args)
    assert transport.install_remote_helper(args) == (remote, digest)
    assert len(calls) == 4
    assert all(kwargs.get("stdin") is subprocess.DEVNULL for _args, kwargs in calls)
    assert calls[1][1].get("timeout") == 30


def test_helper_timeout_removes_only_verified_remote_temporary_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    helper = tmp_path / "helper.py"
    helper.write_text("print('safe')\n", encoding="utf-8")
    remote_dir = "/tmp/ar-local-laptop-backup.Ab12Cd34"
    calls: list[tuple[object, ...]] = []

    def run(command: tuple[object, ...], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        if PureWindowsPath(str(command[0])).name == "ssh.exe" and "mktemp" in command:
            return subprocess.CompletedProcess(command, 0, f"{remote_dir}\n".encode(), b"")
        if PureWindowsPath(str(command[0])).name == "scp.exe":
            return subprocess.CompletedProcess(command, 0, b"", b"")
        if "sha256sum" in command:
            raise subprocess.TimeoutExpired(command, 30)
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(transport.subprocess, "run", run)
    args = trusted_transport_args(tmp_path, source_helper=helper)
    _authenticate_native_fixture(monkeypatch, args)
    with pytest.raises(subprocess.TimeoutExpired):
        transport.install_remote_helper(args)
    assert any("rm" in command for command in calls)
    assert any("rmdir" in command for command in calls)


def test_helper_cleanup_failure_preserves_transfer_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    helper = tmp_path / "helper.py"
    helper.write_text("print('safe')\n", encoding="utf-8")
    remote_dir = "/tmp/ar-local-laptop-backup.Ab12Cd34"
    transfer_command: tuple[object, ...] | None = None

    def run(command: tuple[object, ...], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        nonlocal transfer_command
        if PureWindowsPath(str(command[0])).name == "ssh.exe" and "mktemp" in command:
            return subprocess.CompletedProcess(command, 0, f"{remote_dir}\n".encode(), b"")
        if PureWindowsPath(str(command[0])).name == "scp.exe":
            return subprocess.CompletedProcess(command, 0, b"", b"")
        if "sha256sum" in command:
            transfer_command = command
            raise subprocess.TimeoutExpired(command, 30)
        if "rm" in command:
            raise subprocess.TimeoutExpired(command, 30)
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(transport.subprocess, "run", run)
    args = trusted_transport_args(tmp_path, source_helper=helper)
    _authenticate_native_fixture(monkeypatch, args)
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        transport.install_remote_helper(args)
    assert caught.value.cmd == transfer_command
    assert isinstance(caught.value.__cause__, subprocess.TimeoutExpired)


def test_remote_helper_cleanup_reports_real_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = []
    results = iter((
        subprocess.CompletedProcess(("ssh",), 1, b"", b"permission denied\n"),
        subprocess.CompletedProcess(("ssh",), 1, b"", b"directory not empty\n"),
    ))

    def run(*args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(args)
        return next(results)

    monkeypatch.setattr(transport.subprocess, "run", run)
    args = trusted_transport_args(tmp_path)
    _authenticate_native_fixture(monkeypatch, args)
    with pytest.raises(RuntimeError, match="cleanup failed"):
        transport.remove_remote_helper(
            args, "/tmp/ar-local-laptop-backup.Ab12Cd34/source.py"
        )
    assert len(calls) == 2
