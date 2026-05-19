#!/usr/bin/env python3
"""Verify or apply Raspberry Pi deploy for AR-local (sync + smoke /api/latest).

Non-interactive CLI for agents, orchestrator post-merge, and scheduled CI.

Exit codes:
  0  verify/deploy OK
  1  drift, dirty tree, service down, or HTTP smoke failed
  2  invalid flags or missing configuration
  3  SSH unreachable or remote command failed

Environment (optional):
  AR_PI_SSH_HOST       SSH target (default: ar-local-pi5)
  AR_PI_BASE_URL       Dashboard smoke URL (default: http://100.78.28.10:8808/)
  AR_PI_AR_LOCAL_REPO  Pi checkout (default: /srv/ar-local/AR-local)
  AR_PI_SITE_REPO      Pi shell checkout (default: /srv/ar-local/australianrates)
  AR_PI_GITHUB_REMOTE  Remote name on Pi (default: origin)

Examples:
  python pi_deploy_verify.py --verify
  python pi_deploy_verify.py --deploy
  python pi_deploy_verify.py --deploy --dry-run
  python pi_deploy_verify.py --needs-pi --ref origin/main~1
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

from ar_local_pi_runtime import (
    PI_DASHBOARD_PORT,
    PI_REPO_ROOT,
    PI_SITE_REPO,
    is_raspberry_pi,
    manifest_banks_rate_count,
)

REPO_ROOT = Path(__file__).resolve().parent
SUBPROCESS_TIMEOUT_SEC = 120

EXIT_OK = 0
EXIT_VERIFY_FAIL = 1
EXIT_CONFIG = 2
EXIT_SSH = 3

DEFAULT_SSH_HOST = "ar-local-pi5"
DEFAULT_BASE_URL = f"http://100.78.28.10:{PI_DASHBOARD_PORT}/"

PI_PATH_PREFIXES: tuple[str, ...] = (
    "dashboard/",
    "cdr_",
    "deploy/pi/",
    "pi_daily_sync.py",
    "pi_deploy_verify.py",
    "ar_local_pi_runtime.py",
    "verify_local.py",
    "cdr_dashboard_server.py",
    "package.json",
)


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip() or default


def ssh_host() -> str:
    return _env("AR_PI_SSH_HOST", DEFAULT_SSH_HOST)


def pi_ar_repo() -> str:
    return _env("AR_PI_AR_LOCAL_REPO", str(PI_REPO_ROOT))


def pi_site_repo() -> str:
    return _env("AR_PI_SITE_REPO", str(PI_SITE_REPO))


def pi_base_url() -> str:
    if on_pi_host():
        default = f"http://127.0.0.1:{PI_DASHBOARD_PORT}/"
        return _env("AR_PI_BASE_URL", default).rstrip("/") + "/"
    return _env("AR_PI_BASE_URL", DEFAULT_BASE_URL).rstrip("/") + "/"


def pi_remote() -> str:
    return _env("AR_PI_GITHUB_REMOTE", "origin")


def run_local(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        shell=False,
        check=False,
        timeout=SUBPROCESS_TIMEOUT_SEC,
    )


def shell_quote(value: str) -> str:
    return shlex.quote(value)


def on_pi_host() -> bool:
    if os.environ.get("AR_PI_VERIFY_LOCAL", "").strip() in ("1", "true", "yes"):
        return True
    return is_raspberry_pi()


def run_shell(shell_cmd: str, *, dry_run: bool = False) -> tuple[int, str, str]:
    if on_pi_host():
        if dry_run:
            print(f"pi_deploy_verify: dry-run local {shell_cmd!r}")
            return 0, "", ""
        proc = subprocess.run(
            ["bash", "-lc", shell_cmd],
            shell=False,
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            check=False,
            timeout=SUBPROCESS_TIMEOUT_SEC,
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if proc.returncode != 0:
            print(f"pi_deploy_verify: local command failed ({proc.returncode}): {err or out}", file=sys.stderr)
        return proc.returncode, out, err

    host = ssh_host()
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", host, shell_cmd]
    if dry_run:
        print(f"pi_deploy_verify: dry-run ssh {host} {shell_cmd!r}")
        return 0, "", ""
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        shell=False,
        check=False,
        timeout=SUBPROCESS_TIMEOUT_SEC,
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        print(f"pi_deploy_verify: ssh failed ({proc.returncode}): {err or out}", file=sys.stderr)
    return proc.returncode, out, err


def run_ssh(remote_cmd: str, *, dry_run: bool = False) -> tuple[int, str, str]:
    return run_shell(remote_cmd, dry_run=dry_run)


def origin_main_sha_local() -> Optional[str]:
    fetch = run_local(["git", "fetch", "origin", "main"])
    if fetch.returncode != 0:
        print(f"pi_deploy_verify: git fetch failed: {fetch.stderr.strip()}", file=sys.stderr)
        return None
    rev = run_local(["git", "rev-parse", "origin/main"])
    if rev.returncode != 0:
        return None
    return rev.stdout.strip()


def git_rev_on_pi(repo_path: str) -> tuple[Optional[str], Optional[str]]:
    remote = pi_remote()
    script = (
        f"cd {shell_quote(repo_path)} && git fetch {shell_quote(remote)} 2>/dev/null; "
        f"git rev-parse HEAD; git rev-parse {shell_quote(remote + '/main')}"
    )
    code, out, _ = run_ssh(script)
    if code != 0:
        return None, None
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None, None
    return lines[0], lines[1]


def pi_tree_clean(repo_path: str, *, dry_run: bool = False) -> bool:
    code, out, _ = run_ssh(
        f"cd {shell_quote(repo_path)} && git status --porcelain",
        dry_run=dry_run,
    )
    if dry_run:
        return True
    if code != 0:
        return False
    if out.strip():
        print(f"pi_deploy_verify: dirty tree at {repo_path}:\n{out}", file=sys.stderr)
        return False
    return True


def dashboard_active(*, dry_run: bool = False) -> bool:
    code, out, _ = run_ssh(
        "systemctl is-active ar-local-dashboard.service 2>/dev/null || echo inactive",
        dry_run=dry_run,
    )
    if dry_run:
        return True
    return code == 0 and out.strip() == "active"


def http_smoke(base_url: str, *, require_rates: bool = True) -> int:
    import urllib.error
    import urllib.request

    latest = base_url.rstrip("/") + "/api/latest"
    try:
        with urllib.request.urlopen(latest, timeout=30.0) as resp:
            if int(resp.status) != 200:
                print(f"pi_deploy_verify: {latest} HTTP {resp.status}", file=sys.stderr)
                return EXIT_VERIFY_FAIL
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"pi_deploy_verify: {latest} HTTP {exc.code}", file=sys.stderr)
        return EXIT_VERIFY_FAIL
    except Exception as exc:
        print(f"pi_deploy_verify: {latest} failed: {exc}", file=sys.stderr)
        return EXIT_VERIFY_FAIL

    rates = manifest_banks_rate_count(payload)
    run_date = payload.get("run_date")
    if require_rates and rates <= 0:
        print(
            f"pi_deploy_verify: /api/latest run_date={run_date!r} banks_counts.rates={rates}",
            file=sys.stderr,
        )
        return EXIT_VERIFY_FAIL
    print(f"pi_deploy_verify: HTTP OK {latest} run_date={run_date} rates={rates}")
    return EXIT_OK


def verify_sync(*, dry_run: bool = False) -> int:
    local_main = origin_main_sha_local()
    if not local_main:
        print("pi_deploy_verify: could not resolve origin/main locally", file=sys.stderr)
        return EXIT_CONFIG

    for repo_path in (pi_ar_repo(), pi_site_repo()):
        if not pi_tree_clean(repo_path, dry_run=dry_run):
            return EXIT_VERIFY_FAIL

    head_ar, origin_ar = git_rev_on_pi(pi_ar_repo())
    head_site, origin_site = git_rev_on_pi(pi_site_repo())
    if not head_ar or not origin_ar:
        print("pi_deploy_verify: could not read AR-local SHAs on Pi", file=sys.stderr)
        return EXIT_SSH

    print(f"pi_deploy_verify: local origin/main={local_main[:12]}")
    print(f"pi_deploy_verify: Pi AR-local HEAD={head_ar[:12]} origin/main={origin_ar[:12]}")
    if head_site and origin_site:
        print(f"pi_deploy_verify: Pi australianrates HEAD={head_site[:12]} origin/main={origin_site[:12]}")

    drift: list[str] = []
    if head_ar != origin_ar:
        drift.append(f"AR-local not on {pi_remote()}/main (HEAD {head_ar[:12]} != {origin_ar[:12]})")
    if head_site and origin_site and head_site != origin_site:
        drift.append(
            f"australianrates not on {pi_remote()}/main (HEAD {head_site[:12]} != {origin_site[:12]})"
        )
    if origin_ar != local_main:
        drift.append(
            f"Pi origin/main ({origin_ar[:12]}) behind local origin/main ({local_main[:12]}) — run --deploy"
        )

    if drift:
        for item in drift:
            print(f"pi_deploy_verify: DRIFT {item}", file=sys.stderr)
        return EXIT_VERIFY_FAIL

    if not dashboard_active(dry_run=dry_run):
        print("pi_deploy_verify: ar-local-dashboard.service not active", file=sys.stderr)
        return EXIT_VERIFY_FAIL

    return EXIT_OK


def deploy_pull(repo_path: str, *, dry_run: bool = False) -> int:
    remote = pi_remote()
    cmd = (
        f"cd {shell_quote(repo_path)} && git fetch {shell_quote(remote)} && "
        f"git checkout main && git pull --ff-only {shell_quote(remote)} main"
    )
    code, out, _ = run_ssh(cmd, dry_run=dry_run)
    if code != 0 and not dry_run:
        return EXIT_SSH
    if out and not dry_run:
        print(f"pi_deploy_verify: {repo_path}:\n{out}")
    return EXIT_OK


def deploy_services(*, dry_run: bool = False) -> int:
    for cmd in (
        "sudo systemctl restart ar-local-dashboard.service",
        "sudo systemctl restart ar-local-daily.timer || true",
    ):
        code, _, _ = run_ssh(cmd, dry_run=dry_run)
        if code != 0 and not dry_run:
            return EXIT_SSH
    return EXIT_OK


def paths_touch_pi_deploy(paths: Sequence[str]) -> bool:
    for raw in paths:
        p = raw.replace("\\", "/").lstrip("./")
        for prefix in PI_PATH_PREFIXES:
            if p.startswith(prefix) or p == prefix.rstrip("/"):
                return True
    return False


def changed_files_since(ref: str) -> list[str]:
    proc = run_local(["git", "diff", "--name-only", ref, "HEAD"])
    if proc.returncode != 0:
        proc = run_local(["git", "diff", "--name-only", ref])
    if proc.returncode != 0:
        return []
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]


def cmd_verify(args: argparse.Namespace) -> int:
    code = verify_sync(dry_run=args.dry_run)
    if code != EXIT_OK:
        return code
    if args.dry_run:
        print(f"pi_deploy_verify: dry-run would smoke {pi_base_url()}")
        return EXIT_OK
    smoke = http_smoke(pi_base_url(), require_rates=not args.allow_empty_rates)
    if smoke != EXIT_OK:
        return smoke
    print("pi_deploy_verify: verify OK (sync + dashboard + /api/latest)")
    return EXIT_OK


def cmd_deploy(args: argparse.Namespace) -> int:
    for repo_path in (pi_ar_repo(), pi_site_repo()):
        if not pi_tree_clean(repo_path, dry_run=args.dry_run):
            return EXIT_VERIFY_FAIL
        rc = deploy_pull(repo_path, dry_run=args.dry_run)
        if rc != EXIT_OK:
            return rc
    rc = deploy_services(dry_run=args.dry_run)
    if rc != EXIT_OK:
        return rc
    if args.dry_run:
        print("pi_deploy_verify: dry-run deploy complete (no changes applied)")
        return EXIT_OK
    sync_rc = verify_sync(dry_run=False)
    if sync_rc != EXIT_OK:
        return sync_rc
    smoke = http_smoke(pi_base_url(), require_rates=not args.allow_empty_rates)
    if smoke != EXIT_OK:
        return smoke
    print("pi_deploy_verify: deploy OK")
    return EXIT_OK


def cmd_needs_pi(args: argparse.Namespace) -> int:
    files = changed_files_since(args.ref)
    if not files:
        print(f"pi_deploy_verify: no changed files since {args.ref}")
        return EXIT_OK
    if paths_touch_pi_deploy(files):
        print(f"pi_deploy_verify: Pi deploy recommended ({len(files)} files; pi-touching paths present)")
        for path in sorted(files):
            if paths_touch_pi_deploy([path]):
                print(f"  {path}")
        return EXIT_OK
    print(f"pi_deploy_verify: no Pi-touching paths in {len(files)} files since {args.ref}")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify or apply Pi deploy (sync /srv/ar-local to origin/main, smoke dashboard).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print SSH actions without executing remote changes (deploy) or HTTP (verify).",
    )
    parser.add_argument(
        "--allow-empty-rates",
        action="store_true",
        help="Pass HTTP smoke when /api/latest has zero banks_counts.rates.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--verify",
        action="store_true",
        help="Check Pi SHAs vs origin/main, dashboard active, and GET /api/latest.",
    )
    mode.add_argument(
        "--deploy",
        action="store_true",
        help="git pull --ff-only on Pi repos, restart dashboard + daily timer, then --verify.",
    )
    mode.add_argument(
        "--needs-pi",
        action="store_true",
        help="Exit 0 if changed files since --ref touch Pi deploy paths (orchestrator gate).",
    )
    parser.add_argument(
        "--ref",
        default="origin/main~1",
        help="Git ref for --needs-pi diff base (default: origin/main~1).",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.needs_pi:
        return cmd_needs_pi(args)
    if args.verify:
        return cmd_verify(args)
    if args.deploy:
        return cmd_deploy(args)
    parser.error("no mode selected")
    return EXIT_CONFIG


if __name__ == "__main__":
    sys.exit(main())
