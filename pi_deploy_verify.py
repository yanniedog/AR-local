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
  AR_PI_BASE_URL       Dashboard smoke URL (default: http://100.78.28.10/ via nginx :80)
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
    PI_PUBLIC_BASE_URL,
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
DEFAULT_BASE_URL = PI_PUBLIC_BASE_URL

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


def posix_repo_path(path: str) -> str:
    """Remote Linux paths only (Windows Path defaults must not reach ssh)."""
    return path.replace("\\", "/")


def pi_ar_repo() -> str:
    return posix_repo_path(_env("AR_PI_AR_LOCAL_REPO", "/srv/ar-local/AR-local"))


def pi_site_repo() -> str:
    return posix_repo_path(_env("AR_PI_SITE_REPO", "/srv/ar-local/australianrates"))


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


def _windows_openssh_exit_quirk(code: int, stdout: str, stderr: str) -> bool:
    """Windows OpenSSH often returns a failure code after successful remote output."""
    if sys.platform != "win32" or code == 0:
        return False
    if not stdout.strip():
        return False
    combined = f"{stdout}\n{stderr}"
    return "close - IO is still pending on closed socket" in combined


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
        if _windows_openssh_exit_quirk(proc.returncode, out, err):
            if err:
                print(f"pi_deploy_verify: note: ignoring Windows OpenSSH exit {proc.returncode}", file=sys.stderr)
            return 0, out, err
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


def _parse_kv_lines(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip()
    return out


def _normalize_dirty_field(raw: str) -> str:
    return (raw or "").strip().strip(";")


def _dirty_field_text(raw: str) -> str:
    return _normalize_dirty_field(raw).replace(";", "\n")


def _snap_has_dirty_repos(snap: dict[str, str], *, context: str = "") -> bool:
    suffix = f" {context}" if context else ""
    found = False
    for label, key in (("AR-local", "AR_DIRTY"), ("australianrates", "SITE_DIRTY")):
        dirty = _normalize_dirty_field(snap.get(key, ""))
        if dirty:
            print(
                f"pi_deploy_verify: dirty tree ({label}){suffix}:\n{_dirty_field_text(dirty)}",
                file=sys.stderr,
            )
            found = True
    return found


def pi_remote_snapshot(*, dry_run: bool = False) -> Optional[dict[str, str]]:
    """One SSH round-trip for SHAs, dirty trees, and dashboard state."""
    remote = pi_remote()
    ar = pi_ar_repo()
    site = pi_site_repo()
    q_remote = shell_quote(remote)
    q_ar = shell_quote(ar)
    q_site = shell_quote(site)
    q_remote_main = shell_quote(f"{remote}/main")
    script = (
        f"set +e; "
        f"git -C {q_ar} fetch {q_remote} 2>/dev/null; "
        f"ar_h=$(git -C {q_ar} rev-parse HEAD 2>/dev/null); "
        f"ar_o=$(git -C {q_ar} rev-parse {q_remote_main} 2>/dev/null); "
        f"ar_d=$(git -C {q_ar} status --porcelain | tr '\\n' ';'); "
        f"git -C {q_site} fetch {q_remote} 2>/dev/null; "
        f"site_h=$(git -C {q_site} rev-parse HEAD 2>/dev/null); "
        f"site_o=$(git -C {q_site} rev-parse {q_remote_main} 2>/dev/null); "
        f"site_d=$(git -C {q_site} status --porcelain | tr '\\n' ';'); "
        f"dash=$(systemctl is-active ar-local-dashboard.service 2>/dev/null || echo inactive); "
        f"printf 'AR_HEAD=%s\\nAR_ORIGIN=%s\\nSITE_HEAD=%s\\nSITE_ORIGIN=%s\\n' \"$ar_h\" \"$ar_o\" \"$site_h\" \"$site_o\"; "
        f"printf 'AR_DIRTY=%s\\nSITE_DIRTY=%s\\nDASHBOARD=%s\\n' \"$ar_d\" \"$site_d\" \"$dash\""
    )
    code, stdout, _ = run_ssh(script, dry_run=dry_run)
    if dry_run:
        return {
            "AR_HEAD": "dry",
            "AR_ORIGIN": "dry",
            "SITE_HEAD": "dry",
            "SITE_ORIGIN": "dry",
            "AR_DIRTY": "",
            "SITE_DIRTY": "",
            "DASHBOARD": "active",
        }
    snap = _parse_kv_lines(stdout)
    required = ("AR_HEAD", "AR_ORIGIN", "SITE_HEAD", "SITE_ORIGIN", "DASHBOARD")
    if all(snap.get(k) for k in required):
        return snap
    if code != 0:
        return None
    missing = [k for k in required if not snap.get(k)]
    print(
        f"pi_deploy_verify: incomplete Pi snapshot (missing {', '.join(missing)}); remote output:\n{stdout[:500]}",
        file=sys.stderr,
    )
    return None


def pi_tree_clean(repo_path: str, *, dry_run: bool = False) -> bool:
    snap = pi_remote_snapshot(dry_run=dry_run)
    if snap is None:
        return False
    key = "AR_DIRTY" if repo_path == pi_ar_repo() else "SITE_DIRTY"
    dirty = _normalize_dirty_field(snap.get(key, ""))
    if dirty:
        print(f"pi_deploy_verify: dirty tree at {repo_path}:\n{_dirty_field_text(dirty)}", file=sys.stderr)
        return False
    return True


def dashboard_active(*, dry_run: bool = False, snap: Optional[dict[str, str]] = None) -> bool:
    if snap is None:
        snap = pi_remote_snapshot(dry_run=dry_run)
    if snap is None:
        return False
    return snap.get("DASHBOARD") == "active"


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

    snap = pi_remote_snapshot(dry_run=dry_run)
    if snap is None:
        print("pi_deploy_verify: could not read Pi sync state (SSH)", file=sys.stderr)
        return EXIT_SSH

    head_ar = snap["AR_HEAD"]
    origin_ar = snap["AR_ORIGIN"]
    head_site = snap["SITE_HEAD"]
    origin_site = snap["SITE_ORIGIN"]

    if _snap_has_dirty_repos(snap):
        return EXIT_VERIFY_FAIL

    print(f"pi_deploy_verify: local origin/main={local_main[:12]}")
    print(f"pi_deploy_verify: Pi AR-local HEAD={head_ar[:12]} origin/main={origin_ar[:12]}")
    print(f"pi_deploy_verify: Pi australianrates HEAD={head_site[:12]} origin/main={origin_site[:12]}")

    drift: list[str] = []
    if head_ar != origin_ar:
        drift.append(f"AR-local not on {pi_remote()}/main (HEAD {head_ar[:12]} != {origin_ar[:12]})")
    if head_site != origin_site:
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

    if not dashboard_active(dry_run=dry_run, snap=snap):
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


def deploy_pull_all(*, dry_run: bool = False) -> int:
    """One SSH session for both repos (fewer connections; helps Windows OpenSSH)."""
    remote = pi_remote()
    ar = pi_ar_repo()
    site = pi_site_repo()
    script = (
        f"set -e; "
        f"cd {shell_quote(ar)} && git fetch {shell_quote(remote)} && git checkout main && "
        f"git pull --ff-only {shell_quote(remote)} main; "
        f"cd {shell_quote(site)} && git fetch {shell_quote(remote)} && git checkout main && "
        f"git pull --ff-only {shell_quote(remote)} main"
    )
    code, out, _ = run_ssh(script, dry_run=dry_run)
    if code != 0 and not dry_run:
        return EXIT_SSH
    if out and not dry_run:
        print(f"pi_deploy_verify: pull AR-local + australianrates:\n{out}")
    return EXIT_OK


def deploy_services(*, dry_run: bool = False) -> int:
    ar_repo = pi_ar_repo()
    install_proxy = f"{ar_repo}/deploy/pi/install-pi-dashboard-proxy.sh"
    script = (
        "sudo systemctl restart ar-local-dashboard.service && "
        "(sudo systemctl restart ar-local-daily.timer || true) && "
        "("
        "if [ -f /etc/nginx/sites-enabled/ar-local-dashboard ]; then "
        "sudo nginx -t && sudo systemctl reload nginx; "
        f"elif [ -x {shell_quote(install_proxy)} ]; then "
        f"sudo sh {shell_quote(install_proxy)} {shell_quote(ar_repo)}; "
        "else echo 'pi_deploy_verify: nginx proxy not installed (run deploy/pi/install-pi-dashboard-proxy.sh)' >&2; "
        "fi"
        ")"
    )
    code, _, _ = run_ssh(script, dry_run=dry_run)
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
    snap = pi_remote_snapshot(dry_run=args.dry_run)
    if snap is None:
        print("pi_deploy_verify: could not read Pi state before deploy", file=sys.stderr)
        return EXIT_SSH
    if _snap_has_dirty_repos(snap, context="— resolve before deploy"):
        return EXIT_VERIFY_FAIL
    rc = deploy_pull_all(dry_run=args.dry_run)
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
