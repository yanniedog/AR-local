"""Enroll the Pi rclone remote without printing OAuth tokens or credentials.

Run on the Pi through an SSH tunnel for 127.0.0.1:53682. Only the loopback
authorization URL and a final status are emitted. Existing credentials are never
overwritten. A successful enrollment is not a successful backup.
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import queue
import re
import secrets
import subprocess
import tempfile
import threading
import time
from pathlib import Path


AUTH_URL = re.compile(r"http://127\.0\.0\.1:53682/auth\?state=[A-Za-z0-9_-]+")


def filtered_url(line: str) -> str | None:
    found = AUTH_URL.search(line)
    return found.group(0) if found else None


def credentials_directory(path: Path) -> None:
    if os.name != "posix":
        raise ValueError("Run enrollment on the Pi; forward its OAuth port over SSH")
    if not path.is_absolute() or path != path.resolve() or path.is_symlink():
        raise ValueError("credentials directory must be an absolute canonical path")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise ValueError("credentials directory must be owned by this user with mode 0700")


def write_new_password(directory: Path) -> dict:
    credentials_directory(directory)
    path = directory / "restic.password"
    with path.open("xb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write((secrets.token_urlsafe(48) + "\n").encode("ascii"))
        stream.flush()
        os.fsync(stream.fileno())
    return {"result": "PASS", "action": "PASSWORD_CREATED", "backup": "NOT_RUN",
            "recovery_key": "Store restic.password separately in your password manager before commissioning"}


def _read_output(stream, output: queue.Queue) -> None:
    try:
        for line in iter(stream.readline, ""):
            value = filtered_url(line)
            if value:
                output.put(value)
    finally:
        stream.close()


def enroll(directory: Path, *, rclone: str = "rclone", timeout: int = 900) -> dict:
    credentials_directory(directory)
    destination = directory / "rclone.conf"
    if destination.exists() or destination.is_symlink():
        raise ValueError("rclone.conf already exists; inspect readiness before a deliberate credential rotation")
    descriptor, temporary_name = tempfile.mkstemp(prefix="enroll-", suffix=".conf", dir=directory)
    os.fchmod(descriptor, 0o600)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        command = [rclone, "--config", str(temporary), "config", "create", "ar_local_drive", "drive",
                   "scope=drive.file", "config_is_local=true", "config_auth_no_browser=true",
                   "config_change_team_drive=false"]
        env = {key: value for key, value in os.environ.items() if not key.startswith("RCLONE_")}
        process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace", shell=False)
        output: queue.Queue = queue.Queue()
        reader = threading.Thread(target=_read_output, args=(process.stdout, output), daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    raise TimeoutError("OAuth enrollment expired; no credentials installed")
                try:
                    print(json.dumps({"result": "AUTHORIZATION_REQUIRED", "url": output.get(timeout=0.5)}), flush=True)
                except queue.Empty:
                    pass
            reader.join(timeout=2)
            if process.returncode:
                raise RuntimeError(f"rclone enrollment failed with exit {process.returncode}; provider output withheld")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        saved = configparser.ConfigParser(interpolation=None)
        saved.read(temporary, encoding="utf-8")
        remote = saved["ar_local_drive"]
        token = json.loads(remote.get("token", "{}"))
        if (remote.get("type") != "drive" or remote.get("scope") != "drive.file"
                or not isinstance(token, dict) or not token.get("refresh_token")):
            raise ValueError("OAuth did not produce the expected Drive scope and refresh token")
        # Exclusive creation prevents replacing credentials from another enrollment.
        with destination.open("xb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(temporary.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        return {"result": "PASS", "action": "OAUTH_ENROLLED", "scope": "drive.file", "backup": "NOT_RUN"}
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("oauth", "password"))
    parser.add_argument("--credentials-dir", type=Path, required=True)
    parser.add_argument("--rclone", default="rclone")
    args = parser.parse_args(argv)
    try:
        result = (enroll(args.credentials_dir, rclone=args.rclone) if args.command == "oauth"
                  else write_new_password(args.credentials_dir))
    except configparser.Error:
        result = {"result": "BLOCKED", "error": "Invalid private rclone configuration; details withheld", "backup": "NOT_RUN"}
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        # No raw provider text or token-bearing config is emitted, even on failure.
        result = {"result": "BLOCKED", "error": str(error), "backup": "NOT_RUN"}
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if result["result"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
