"""Independent, standard-library-only runtime reader; never imports receiver code.

Invoke this source file with -I -S -B and externally verified source/config hashes.
It prints evidence to stdout, writes no artifacts and cannot accept A3 or A4.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


GIT_READ_OPTIONS = ["--no-optional-locks", "-c", "core.fsmonitor=false",
                    "-c", "core.untrackedCache=false"]
STATUS_OPTIONS = ["status", "--porcelain=v1", "--untracked-files=all",
                  "--ignore-submodules=none"]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path,
            "runtime path must be absolute and canonical")
    for item in (path, *path.parents):
        require(not item.is_symlink()
                and not (getattr(item.lstat(), "st_file_attributes", 0) & 0x400),
                "runtime path contains a link or reparse point")
    return path


def digest(path):
    value = hashlib.sha256()
    with canonical(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024**2), b""):
            value.update(chunk)
    return value.hexdigest()


def clean_environment():
    # Git environment overrides may redirect a -C read to a different repository.
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("GIT_", "PYTHON"))}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    return env


def run(argv):
    return subprocess.run(argv, capture_output=True, text=True, check=True,
                          stdin=subprocess.DEVNULL, timeout=30,
                          env=clean_environment()).stdout.strip()


def verify_git(git, root, expected, runner=run):
    prefix = [git, *GIT_READ_OPTIONS, "-C", root]
    head = runner([*prefix, "rev-parse", "HEAD"])
    status = runner([*prefix, *STATUS_OPTIONS])
    require(head == expected, "runtime commit differs from approved identity")
    require(not status, "runtime checkout is dirty")
    return head


def ssh_prefix(config):
    pins = config["transport"]
    require(pins["ssh_user"] == "pi" and pins["ssh_port"] == 22
            and pins["ssh_logical_host"] == "ar-local-pi5",
            "SSH logical identity changed")
    for field in ("ssh", "ssh_identity", "ssh_known_hosts"):
        require(digest(pins[field + "_path"]) == pins[field + "_sha256"],
                "SSH executable or key-file digest mismatch")
    options = ["BatchMode=yes", "ConnectTimeout=10", "IdentitiesOnly=yes",
               "IdentityAgent=none", "PreferredAuthentications=publickey",
               "PubkeyAuthentication=yes", "GSSAPIAuthentication=no",
               "PasswordAuthentication=no", "KbdInteractiveAuthentication=no",
               "ChallengeResponseAuthentication=no", "StrictHostKeyChecking=yes",
               "HostKeyAlias=ar-local-pi5", "HostKeyAlgorithms=ssh-ed25519",
               "UserKnownHostsFile=" + pins["ssh_known_hosts_path"],
               "GlobalKnownHostsFile=NUL", "UpdateHostKeys=no", "VerifyHostKeyDNS=no",
               "ForwardAgent=no", "ClearAllForwardings=yes", "RequestTTY=no"]
    argv = [pins["ssh_path"], "-F", "NUL"]
    for option in options:
        argv.extend(("-o", option))
    return [*argv, "-i", pins["ssh_identity_path"], "-p", "22", "-l", "pi",
            config["lan_fallback_ipv4"]]


def verify(config_path, config_sha, receiver_sha, production_sha):
    # Configuration bytes are authenticated BEFORE parsing or using their paths.
    raw = canonical(config_path).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == config_sha, "configuration changed")
    config = json.loads(raw)
    require(config["candidate_sha"] == receiver_sha
            and config["protected_sha"] == production_sha, "configuration pins changed")
    require(config["authority"] == "D-015-USER-SESSION-NO-UAC", "authority changed")
    canonical(config["receiver"])
    for field in ("python", "git"):
        require(digest(config[field + "_path"]) == config[field + "_sha256"],
                "local executable digest mismatch")
    require(Path(sys.executable).resolve() == Path(config["python_path"]),
            "Python executable differs from configuration")
    commands = []

    def record_run(argv):
        commands.append(argv)
        return run(argv)

    verify_git(config["git_path"], config["receiver"], receiver_sha, record_run)
    known = canonical(config["transport"]["ssh_known_hosts_path"])
    before = (digest(known), known.stat().st_mtime_ns)
    prefix = ssh_prefix(config)

    def remote(argv):
        # Only fixed Git arguments are sent remotely; no supplied shell text.
        return record_run([*prefix, *argv])

    verify_git("/usr/bin/git", "/srv/ar-local/AR-local", production_sha, remote)
    require(before == (digest(known), known.stat().st_mtime_ns), "known-hosts state changed")
    require(hashlib.sha256(canonical(config_path).read_bytes()).hexdigest() == config_sha,
            "configuration changed during read")
    return {"runtime_binding": "PASS", "receiver_sha": receiver_sha,
            "production_sha": production_sha, "production_clean": True,
            "known_hosts_unchanged": True, "config_sha256": config_sha,
            "exact_commands": commands, "receiver_code_executed": False,
            "physical_recovery": "BLOCKED", "natural_trigger": "UNVERIFIED"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("config", "config-sha256", "receiver-sha", "production-sha"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    try:
        require(sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode,
                "runtime reader requires -I -S -B")
        value = verify(args.config, args.config_sha256, args.receiver_sha, args.production_sha)
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps({"runtime_binding": "FAIL", "error": str(error)}))
        return 1
    print(json.dumps(value, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
