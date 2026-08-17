#!/usr/bin/env python3
"""Install and verify SSH access to the AR-local Raspberry Pi (`ssh ar-local-pi5-lan`).

The Host entries are not hardcoded here: they are read from the single
authoritative source, `docs/UNIVERSAL_ROADMAP.md` section
"SSH from the Windows development machine". When the Pi's LAN or Tailscale
address drifts, update the roadmap and re-run `--install`.

Exit codes:
  0  requested action succeeded
  1  connectivity check failed (SSH reachable path unusable)
  2  invalid flags, unreadable roadmap, or conflicting ~/.ssh/config entries
  3  ssh transport failure (host unreachable, auth refused, key missing)

Examples:
  python ar_local_pi_ssh.py --print
  python ar_local_pi_ssh.py --install
  python ar_local_pi_ssh.py --install --dry-run
  python ar_local_pi_ssh.py --check
  python ar_local_pi_ssh.py --check --host ar-local-pi5
  python ar_local_pi_ssh.py --shell
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parent
ROADMAP_PATH = REPO_ROOT / "docs" / "UNIVERSAL_ROADMAP.md"
ROADMAP_HEADING = "### SSH from the Windows development machine"

DEFAULT_HOST = "ar-local-pi5-lan"
MANAGED_HOST_PREFIX = "ar-local-pi5"
BLOCK_BEGIN = "# >>> ar-local pi ssh (managed by ar_local_pi_ssh.py) >>>"
BLOCK_END = "# <<< ar-local pi ssh (managed by ar_local_pi_ssh.py) <<<"

CHECK_REMOTE_COMMAND = "hostname; hostname -I; date"
SSH_CONNECT_TIMEOUT_SEC = 20
CHECK_TIMEOUT_SEC = 60
SSH_TRANSPORT_EXIT = 255
SSH_CHECK_OPTIONS: tuple[str, ...] = (
    "-o", "BatchMode=yes",
    "-o", f"ConnectTimeout={SSH_CONNECT_TIMEOUT_SEC}",
    "-o", "ServerAliveInterval=15",
    "-o", "ServerAliveCountMax=3",
)

EXIT_OK = 0
EXIT_CHECK_FAIL = 1
EXIT_CONFIG = 2
EXIT_SSH = 3

HOST_LINE_RE = re.compile(r"^\s*Host\s+(?P<names>.+?)\s*$", re.IGNORECASE)
IDENTITY_FILE_RE = re.compile(r"^\s*IdentityFile\s+(?P<path>.+?)\s*$", re.IGNORECASE)


class ConfigError(RuntimeError):
    """Roadmap or ~/.ssh/config is not in a state this tool can act on."""


# ---------------------------------------------------------------------------
# Roadmap parsing (authoritative host entries)
# ---------------------------------------------------------------------------


def read_roadmap_ssh_block(roadmap: Path = ROADMAP_PATH) -> str:
    """Return the ```sshconfig fenced block under the roadmap SSH heading."""
    try:
        text = roadmap.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ConfigError(f"cannot read {roadmap}: {exc}") from exc

    start = text.find(ROADMAP_HEADING)
    if start < 0:
        raise ConfigError(f"{roadmap} is missing section {ROADMAP_HEADING!r}")

    fence = re.compile(r"^```sshconfig\s*$(?P<body>.*?)^```\s*$", re.DOTALL | re.MULTILINE)
    match = fence.search(text, start)
    if match is None:
        raise ConfigError(
            f"{roadmap} section {ROADMAP_HEADING!r} has no ```sshconfig block"
        )

    block = match.group("body").strip("\n")
    hosts = host_aliases(block)
    if DEFAULT_HOST not in hosts:
        raise ConfigError(
            f"roadmap sshconfig block does not define Host {DEFAULT_HOST}"
            f" (found: {', '.join(hosts) or 'none'})"
        )
    return block


def host_aliases(config_text: str) -> list[str]:
    """Host aliases declared in an ssh config fragment, in order."""
    aliases: list[str] = []
    for line in config_text.splitlines():
        match = HOST_LINE_RE.match(line)
        if match is None:
            continue
        for name in match.group("names").split():
            if name not in aliases:
                aliases.append(name)
    return aliases


def identity_files(config_text: str) -> list[str]:
    return [
        match.group("path").strip().strip('"')
        for line in config_text.splitlines()
        if (match := IDENTITY_FILE_RE.match(line)) is not None
    ]


def expand_user_path(raw: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(raw)))


def managed_block(config_text: str) -> str:
    return "\n".join(
        [
            BLOCK_BEGIN,
            "# Source of truth: docs/UNIVERSAL_ROADMAP.md"
            f" ({ROADMAP_HEADING.lstrip('# ')}).",
            "# Regenerate with: npm run pi:ssh:setup",
            "# Manual edits here are overwritten; edit the roadmap instead.",
            config_text,
            BLOCK_END,
            "",
        ]
    )


# ---------------------------------------------------------------------------
# ~/.ssh/config installation
# ---------------------------------------------------------------------------


def ssh_config_path() -> Path:
    override = os.environ.get("AR_PI_SSH_CONFIG", "").strip()
    if override:
        return expand_user_path(override)
    return Path.home() / ".ssh" / "config"


def strip_managed_block(existing: str) -> str:
    """Remove a previously installed managed block, keeping the rest verbatim."""
    pattern = re.compile(
        rf"{re.escape(BLOCK_BEGIN)}.*?{re.escape(BLOCK_END)}\n?",
        re.DOTALL,
    )
    return pattern.sub("", existing)


def conflicting_aliases(unmanaged: str, aliases: Sequence[str]) -> list[str]:
    """Managed aliases also declared outside the managed block.

    ssh takes the first value it finds for each keyword, so a duplicate earlier
    in the file silently wins over the block this tool writes.
    """
    declared = set(host_aliases(unmanaged))
    return [alias for alias in aliases if alias in declared]


def render_config(existing: str, block_body: str) -> str:
    kept = strip_managed_block(existing).rstrip("\n")
    block = managed_block(block_body)
    if not kept:
        return block
    return f"{kept}\n\n{block}"


def install_config(
    block_body: str,
    *,
    path: Path,
    dry_run: bool = False,
    force: bool = False,
) -> str:
    existing = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    aliases = host_aliases(block_body)
    conflicts = conflicting_aliases(strip_managed_block(existing), aliases)
    if conflicts and not force:
        raise ConfigError(
            f"{path} already declares {', '.join(conflicts)} outside the managed block;"
            " ssh would use those entries instead. Remove them, or re-run with --force"
            " to install anyway."
        )

    rendered = render_config(existing, block_body)
    if dry_run:
        return rendered

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _restrict(path.parent, 0o700)
    path.write_text(rendered, encoding="utf-8", newline="\n")
    _restrict(path, 0o600)
    return rendered


def _restrict(path: Path, mode: int) -> None:
    """Tighten permissions where the platform enforces them (POSIX)."""
    if sys.platform == "win32":
        return
    try:
        path.chmod(mode)
    except OSError as exc:  # pragma: no cover - platform/filesystem dependent
        print(f"ar_local_pi_ssh: cannot chmod {path}: {exc}", file=sys.stderr)


def missing_identity_files(block_body: str) -> list[str]:
    return [raw for raw in identity_files(block_body) if not expand_user_path(raw).is_file()]


# ---------------------------------------------------------------------------
# Connectivity check
# ---------------------------------------------------------------------------


def check_command(host: str) -> list[str]:
    return ["ssh", *SSH_CHECK_OPTIONS, host, CHECK_REMOTE_COMMAND]


def run_check(host: str) -> int:
    cmd = check_command(host)
    print(f"ar_local_pi_ssh: {' '.join(cmd[:-1])} {cmd[-1]!r}")
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            shell=False,
            check=False,
            timeout=CHECK_TIMEOUT_SEC,
        )
    except FileNotFoundError:
        print("ar_local_pi_ssh: ssh client not found on PATH", file=sys.stderr)
        return EXIT_SSH
    except subprocess.TimeoutExpired:
        print(
            f"ar_local_pi_ssh: no response from {host} within {CHECK_TIMEOUT_SEC}s",
            file=sys.stderr,
        )
        return EXIT_SSH

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if stdout:
        print(stdout)
    if proc.returncode == 0:
        print(f"ar_local_pi_ssh: OK — {host} reachable")
        return EXIT_OK

    if stderr:
        print(stderr, file=sys.stderr)
    if proc.returncode == SSH_TRANSPORT_EXIT:
        print(
            f"ar_local_pi_ssh: cannot connect to {host}."
            " Onsite? Check the LAN address in docs/UNIVERSAL_ROADMAP.md"
            " (tailscale ping ar-local-pi5) and that the key exists.",
            file=sys.stderr,
        )
        return EXIT_SSH
    print(
        f"ar_local_pi_ssh: remote command on {host} failed ({proc.returncode})",
        file=sys.stderr,
    )
    return EXIT_CHECK_FAIL


def run_shell(host: str) -> int:
    cmd = ["ssh", host]
    print(f"ar_local_pi_ssh: {' '.join(cmd)}")
    try:
        return subprocess.call(cmd, shell=False)
    except FileNotFoundError:
        print("ar_local_pi_ssh: ssh client not found on PATH", file=sys.stderr)
        return EXIT_SSH


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ar_local_pi_ssh.py",
        description="Install and verify SSH access to the AR-local Pi.",
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--print", dest="show", action="store_true",
                        help="print the roadmap Host entries without writing anything")
    action.add_argument("--install", action="store_true",
                        help="write the Host entries into ~/.ssh/config (idempotent)")
    action.add_argument("--check", action="store_true",
                        help=f"run a BatchMode SSH smoke test (default host {DEFAULT_HOST})")
    action.add_argument("--shell", action="store_true",
                        help="open an interactive session on the Pi")
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help=f"SSH alias for --check/--shell (default: {DEFAULT_HOST})")
    parser.add_argument("--dry-run", action="store_true",
                        help="with --install, print the resulting config instead of writing")
    parser.add_argument("--force", action="store_true",
                        help="with --install, proceed despite conflicting existing entries")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.check:
        return run_check(args.host)
    if args.shell:
        return run_shell(args.host)

    try:
        block_body = read_roadmap_ssh_block()
    except ConfigError as exc:
        print(f"ar_local_pi_ssh: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    if args.show:
        print(managed_block(block_body), end="")
        return EXIT_OK

    path = ssh_config_path()
    try:
        rendered = install_config(
            block_body, path=path, dry_run=args.dry_run, force=args.force
        )
    except ConfigError as exc:
        print(f"ar_local_pi_ssh: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except OSError as exc:
        print(f"ar_local_pi_ssh: cannot write {path}: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    aliases = ", ".join(host_aliases(block_body))
    if args.dry_run:
        print(rendered, end="")
        print(f"ar_local_pi_ssh: dry-run — {path} unchanged ({aliases})", file=sys.stderr)
        return EXIT_OK

    print(f"ar_local_pi_ssh: installed {aliases} into {path}")
    missing = missing_identity_files(block_body)
    if missing:
        print(
            "ar_local_pi_ssh: WARNING missing private key(s): "
            + ", ".join(missing)
            + " — copy the key onto this machine before --check",
            file=sys.stderr,
        )
    print(f"ar_local_pi_ssh: next — ssh {DEFAULT_HOST}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
