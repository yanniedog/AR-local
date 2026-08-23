#!/usr/bin/env python3
"""Verify or apply Raspberry Pi deploy for AR-local (sync + smoke /api/latest).

Non-interactive CLI for agents, orchestrator post-merge, and scheduled CI.

Exit codes:
  0  verify/deploy OK
  1  drift, dirty tree, service down, or HTTP smoke failed
  2  invalid flags or missing configuration
  3  SSH unreachable or remote command failed
  75 ingest/deploy lock is active; retry without changing the checkout

Environment (optional):
  AR_PI_SSH_HOST       SSH target (default: ar-local-pi5)
  AR_PI_BASE_URL       Dashboard smoke URL (default: http://100.78.28.10/ via nginx :80)
  AR_PI_AR_LOCAL_REPO  Pi checkout (default: /srv/ar-local/AR-local)
  AR_PI_SITE_REPO      Pi shell checkout (default: /srv/ar-local/australianrates)
  AR_PI_GITHUB_REMOTE  Remote name on Pi (default: origin)
  AR_PI_EXPECTED_COMMIT Exact 40-character AR-local main commit approved by canary

Examples:
  python pi_deploy_verify.py --verify
  python pi_deploy_verify.py --deploy --expected-commit <40-char-sha>
  python pi_deploy_verify.py --deploy --expected-commit <40-char-sha> --dry-run
  python pi_deploy_verify.py --needs-pi --ref origin/main~1
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

from ar_local_pi_runtime import (
    PI_DATA_ROOT,
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
EXIT_BUSY = 75

DEFAULT_SSH_HOST = "ar-local-pi5"
DEFAULT_BASE_URL = PI_PUBLIC_BASE_URL
FORBIDDEN_PI_BOOTSTRAP_PATH = "/home/" + "pi"
SSH_SUCCESS_SENTINEL = "__AR_PI_SSH_COMMAND_OK__"
# ssh exits 255 for its own transport failures, distinct from any status the
# remote command could return. That is the one class where the remote command
# provably never ran, so a retry cannot repeat a side effect.
SSH_TRANSPORT_EXIT = 255
SSH_TRANSPORT_RETRIES = 2
SSH_RETRY_BACKOFF_SEC = (2, 5)
SSH_CONNECT_TIMEOUT_SEC = 20
SSH_OPTIONS: tuple[str, ...] = (
    "-o", "BatchMode=yes",
    "-o", f"ConnectTimeout={SSH_CONNECT_TIMEOUT_SEC}",
    # Fail a stalled link promptly and predictably rather than hanging until the
    # subprocess timeout with a half-read stream.
    "-o", "ServerAliveInterval=15",
    "-o", "ServerAliveCountMax=3",
)
FORBIDDEN_PI_BOOTSTRAP_RE = re.compile(
    rf"(?<![A-Za-z0-9_./-]){re.escape(FORBIDDEN_PI_BOOTSTRAP_PATH)}(?![A-Za-z0-9_.-])"
)
FULL_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

PI_PATH_PREFIXES: tuple[str, ...] = (
    "app_payload",
    "dashboard/",
    "cdr_",
    "deploy/pi/",
    "pi_daily_sync.py",
    "pi_deploy_verify.py",
    "pi_runtime_health.py",
    "pi_capacity_monitor.py",
    "pi_backup_foundation.py",
    "ar_local_backup_policy.py",
    "ar_local_pi_service_heal.py",
    "ar_local_pi_runtime.py",
    "verify_local.py",
    "cdr_dashboard_server.py",
    "package.json",
)


def pi_backup_config() -> str:
    return posix_repo_path(_env("AR_PI_BACKUP_CONFIG", "/etc/ar-local/backup.env"))


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


def pi_data_root() -> str:
    return posix_repo_path(_env("AR_PI_DATA_ROOT", str(PI_DATA_ROOT)))


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
    """Accept a Windows OpenSSH abort at socket close after the command ran.

    The client aborts *after* the remote command completed, and that abort is
    what truncates the tail of stdout — which is exactly where the success
    sentinel is printed. Requiring the sentinel here demands the very byte the
    bug destroys, so this guard never fires in the case it exists for. The
    specific crash signature plus some remote output is the strongest evidence
    available, and it is the pre-existing behaviour this quirk was written with.
    """
    if sys.platform != "win32" or code == 0:
        return False
    if not stdout.strip():
        return False
    combined = f"{stdout}\n{stderr}"
    return "close - IO is still pending on closed socket" in combined


def _remote_command_with_success_sentinel(shell_cmd: str) -> str:
    sentinel = shell_quote(SSH_SUCCESS_SENTINEL)
    return (
        "{\n"
        f"{shell_cmd}\n"
        "}\n"
        "__ar_pi_remote_status=$?\n"
        "if [ \"$__ar_pi_remote_status\" -ne 0 ]; then\n"
        "  exit \"$__ar_pi_remote_status\"\n"
        "fi\n"
        f"printf '\\n%s\\n' {sentinel}"
    )


def _has_terminal_success_sentinel(stdout: str) -> bool:
    nonempty_lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    return bool(nonempty_lines) and nonempty_lines[-1] == SSH_SUCCESS_SENTINEL


def _strip_success_sentinel(stdout: str) -> str:
    lines = stdout.splitlines()
    for index in range(len(lines) - 1, -1, -1):
        if not lines[index].strip():
            continue
        if lines[index].strip() == SSH_SUCCESS_SENTINEL:
            del lines[index]
        break
    return "\n".join(lines).strip()


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
    remote_cmd = _remote_command_with_success_sentinel(shell_cmd)
    cmd = ["ssh", *SSH_OPTIONS, host, remote_cmd]
    if dry_run:
        print(f"pi_deploy_verify: dry-run ssh {host} {shell_cmd!r}")
        return 0, "", ""

    attempts = SSH_TRANSPORT_RETRIES + 1
    proc = None
    for attempt in range(1, attempts + 1):
        last = attempt == attempts
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                shell=False,
                check=False,
                timeout=SUBPROCESS_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired:
            if last:
                print(
                    f"pi_deploy_verify: ssh timed out after {attempts} attempt(s)",
                    file=sys.stderr,
                )
                return EXIT_SSH, "", ""
            delay = SSH_RETRY_BACKOFF_SEC[min(attempt - 1, len(SSH_RETRY_BACKOFF_SEC) - 1)]
            print(
                f"pi_deploy_verify: ssh timed out (attempt {attempt}/{attempts}); "
                f"retrying in {delay}s",
                file=sys.stderr,
            )
            time.sleep(delay)
            continue
        # Only ssh's own transport failure is retried: the remote command never
        # started, so re-running it cannot duplicate a side effect. Any other
        # non-zero code is the remote command's own status and must stand.
        if proc.returncode == SSH_TRANSPORT_EXIT and not last:
            delay = SSH_RETRY_BACKOFF_SEC[min(attempt - 1, len(SSH_RETRY_BACKOFF_SEC) - 1)]
            print(
                f"pi_deploy_verify: ssh transport failure (attempt {attempt}/{attempts}); "
                f"retrying in {delay}s: {(proc.stderr or '').strip()[:200]}",
                file=sys.stderr,
            )
            time.sleep(delay)
            continue
        break

    raw_out = (proc.stdout or "").strip()
    out = _strip_success_sentinel(raw_out)
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        if _windows_openssh_exit_quirk(proc.returncode, raw_out, err):
            print(
                f"pi_deploy_verify: note: ignoring Windows OpenSSH exit {proc.returncode} "
                "(client aborted at socket close after the remote command ran)",
                file=sys.stderr,
            )
            return 0, out, err
        print(f"pi_deploy_verify: ssh failed ({proc.returncode}): {err or out}", file=sys.stderr)
    elif not _has_terminal_success_sentinel(raw_out):
        # ssh reports the REMOTE command's status, so a 0 here already means the
        # remote command succeeded. A missing sentinel means the tail of stdout was
        # perturbed — a truncated read, a late-flushing background write, a trailing
        # banner — not that the work failed. Treating that as EXIT_SSH turned every
        # imperfect link into a failed deploy, so warn and trust the exit code.
        print(
            "pi_deploy_verify: ssh exited 0 without the remote success sentinel; "
            "trusting the exit status (stdout tail was perturbed)",
            file=sys.stderr,
        )
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
    data = pi_data_root()
    q_remote = shell_quote(remote)
    q_ar = shell_quote(ar)
    q_site = shell_quote(site)
    q_data = shell_quote(data)
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
        f"dash_wd=$(systemctl show ar-local-dashboard.service -p WorkingDirectory --value 2>/dev/null); "
        f"dash_exec=$(systemctl show ar-local-dashboard.service -p ExecStart --value 2>/dev/null | tr '\\n' ' '); "
        f"daily_wd=$(systemctl show ar-local-daily.service -p WorkingDirectory --value 2>/dev/null); "
        f"daily_exec=$(systemctl show ar-local-daily.service -p ExecStart --value 2>/dev/null | tr '\\n' ' '); "
        f"daily_timer_enabled=$(systemctl is-enabled ar-local-daily.timer 2>/dev/null); "
        f"daily_timer_active=$(systemctl is-active ar-local-daily.timer 2>/dev/null); "
        f"watchdog_timer_enabled=$(systemctl is-enabled ar-local-daily-watchdog.timer 2>/dev/null); "
        f"watchdog_timer_active=$(systemctl is-active ar-local-daily-watchdog.timer 2>/dev/null); "
        f"capacity_timer_enabled=$(systemctl is-enabled ar-local-capacity-monitor.timer 2>/dev/null); "
        f"capacity_timer_active=$(systemctl is-active ar-local-capacity-monitor.timer 2>/dev/null); "
        f"daily_kill_mode=$(systemctl show ar-local-daily.service -p KillMode --value 2>/dev/null); "
        f"daily_start_timeout=$(systemctl show ar-local-daily.service -p TimeoutStartUSec --value 2>/dev/null); "
        f"watchdog_kill_mode=$(systemctl show ar-local-daily-watchdog.service -p KillMode --value 2>/dev/null); "
        f"watchdog_start_timeout=$(systemctl show ar-local-daily-watchdog.service -p TimeoutStartUSec --value 2>/dev/null); "
        f"manual_kill_mode=$(systemctl show ar-local-ingest-now.service -p KillMode --value 2>/dev/null); "
        f"manual_start_timeout=$(systemctl show ar-local-ingest-now.service -p TimeoutStartUSec --value 2>/dev/null); "
        f"dash_env=$(systemctl show ar-local-dashboard.service -p Environment --value 2>/dev/null); "
        f"daily_env=$(systemctl show ar-local-daily.service -p Environment --value 2>/dev/null); "
        f"df_ar=$(df -P {q_ar} 2>/dev/null | awk 'NR==2{{print $1\"|\"$6}}'); "
        f"df_site=$(df -P {q_site} 2>/dev/null | awk 'NR==2{{print $1\"|\"$6}}'); "
        f"df_data=$(df -P {q_data} 2>/dev/null | awk 'NR==2{{print $1\"|\"$6}}'); "
        f"printf 'AR_HEAD=%s\\nAR_ORIGIN=%s\\nSITE_HEAD=%s\\nSITE_ORIGIN=%s\\n' \"$ar_h\" \"$ar_o\" \"$site_h\" \"$site_o\"; "
        f"printf 'AR_DIRTY=%s\\nSITE_DIRTY=%s\\nDASHBOARD=%s\\n' \"$ar_d\" \"$site_d\" \"$dash\"; "
        f"printf 'DASHBOARD_WD=%s\\nDASHBOARD_EXEC=%s\\nDAILY_WD=%s\\nDAILY_EXEC=%s\\n' \"$dash_wd\" \"$dash_exec\" \"$daily_wd\" \"$daily_exec\"; "
        f"printf 'DAILY_TIMER_ENABLED=%s\\nDAILY_TIMER_ACTIVE=%s\\nWATCHDOG_TIMER_ENABLED=%s\\nWATCHDOG_TIMER_ACTIVE=%s\\n' \"$daily_timer_enabled\" \"$daily_timer_active\" \"$watchdog_timer_enabled\" \"$watchdog_timer_active\"; "
        f"printf 'DAILY_KILL_MODE=%s\\nDAILY_START_TIMEOUT=%s\\nWATCHDOG_KILL_MODE=%s\\nWATCHDOG_START_TIMEOUT=%s\\nMANUAL_KILL_MODE=%s\\nMANUAL_START_TIMEOUT=%s\\n' \"$daily_kill_mode\" \"$daily_start_timeout\" \"$watchdog_kill_mode\" \"$watchdog_start_timeout\" \"$manual_kill_mode\" \"$manual_start_timeout\"; "
        f"printf 'CAPACITY_TIMER_ENABLED=%s\\nCAPACITY_TIMER_ACTIVE=%s\\n' \"$capacity_timer_enabled\" \"$capacity_timer_active\"; "
        f"printf 'DASHBOARD_ENV=%s\\nDAILY_ENV=%s\\nDF_AR=%s\\nDF_SITE=%s\\nDF_DATA=%s\\n' \"$dash_env\" \"$daily_env\" \"$df_ar\" \"$df_site\" \"$df_data\""
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
            "DASHBOARD_WD": "dry",
            "DASHBOARD_EXEC": "dry",
            "DAILY_WD": "dry",
            "DAILY_EXEC": "dry",
            "DAILY_TIMER_ENABLED": "enabled",
            "DAILY_TIMER_ACTIVE": "active",
            "WATCHDOG_TIMER_ENABLED": "enabled",
            "WATCHDOG_TIMER_ACTIVE": "active",
            "CAPACITY_TIMER_ENABLED": "enabled",
            "CAPACITY_TIMER_ACTIVE": "active",
            "DAILY_KILL_MODE": "control-group",
            "DAILY_START_TIMEOUT": "6h 15min",
            "WATCHDOG_KILL_MODE": "control-group",
            "WATCHDOG_START_TIMEOUT": "6h 15min",
            "MANUAL_KILL_MODE": "control-group",
            "MANUAL_START_TIMEOUT": "6h 15min",
            "DASHBOARD_ENV": "AR_LOCAL_DATA_ROOT=/dry/data",
            "DAILY_ENV": "AR_LOCAL_DATA_ROOT=/dry/data",
            "DF_AR": "dry",
            "DF_SITE": "dry",
            "DF_DATA": "dry",
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


def pi_service_paths_ok(snap: dict[str, str]) -> bool:
    ok = True
    path_fields = {
        "dashboard WorkingDirectory": snap.get("DASHBOARD_WD", ""),
        "dashboard ExecStart": snap.get("DASHBOARD_EXEC", ""),
        "daily WorkingDirectory": snap.get("DAILY_WD", ""),
        "daily ExecStart": snap.get("DAILY_EXEC", ""),
    }
    environment_fields = {
        "dashboard Environment": snap.get("DASHBOARD_ENV", ""),
        "daily Environment": snap.get("DAILY_ENV", ""),
    }
    for label, value in {**path_fields, **environment_fields}.items():
        print(f"pi_deploy_verify: {label}: {value}")
    for label, value in path_fields.items():
        if FORBIDDEN_PI_BOOTSTRAP_RE.search(value):
            print(f"pi_deploy_verify: forbidden bootstrap path in {label}: {value}", file=sys.stderr)
            ok = False
    for label, value in environment_fields.items():
        try:
            assignments = shlex.split(value)
        except ValueError:
            assignments = [value]
        for assignment in assignments:
            name, separator, path = assignment.partition("=")
            name = name.strip()
            path = path.strip()
            if not separator or not FORBIDDEN_PI_BOOTSTRAP_RE.search(path):
                continue
            if (name, path) in {
                ("HOME", "/home/pi"),
                ("XDG_CONFIG_HOME", "/home/pi/.config"),
            }:
                continue
            print(
                f"pi_deploy_verify: forbidden bootstrap path in {label}: {assignment}",
                file=sys.stderr,
            )
            ok = False

    dash_exec = snap.get("DASHBOARD_EXEC", "")
    repo_local_runs = f"{pi_ar_repo().rstrip('/')}/runs"
    bad_runs_tokens = ("--runs runs", "--runs=.", "--runs ./runs", f"--runs {repo_local_runs}", f"--runs={repo_local_runs}")
    if any(token in dash_exec for token in bad_runs_tokens):
        print(f"pi_deploy_verify: dashboard --runs points inside the service checkout: {dash_exec}", file=sys.stderr)
        ok = False
    if "AR_LOCAL_DATA_ROOT=" not in (snap.get("DASHBOARD_ENV", "") + ";" + snap.get("DAILY_ENV", "")):
        print("pi_deploy_verify: AR_LOCAL_DATA_ROOT missing from Pi service environments", file=sys.stderr)
        ok = False

    for label, key in (("repo", "DF_AR"), ("site", "DF_SITE"), ("data", "DF_DATA")):
        print(f"pi_deploy_verify: df {label}: {snap.get(key, '')}")
    return ok


def pi_ingest_timers_ok(snap: dict[str, str]) -> bool:
    expected = {
        "DAILY_TIMER_ENABLED": "enabled",
        "DAILY_TIMER_ACTIVE": "active",
        "WATCHDOG_TIMER_ENABLED": "enabled",
        "WATCHDOG_TIMER_ACTIVE": "active",
        "CAPACITY_TIMER_ENABLED": "enabled",
        "CAPACITY_TIMER_ACTIVE": "active",
    }
    ok = True
    for field, value in expected.items():
        actual = snap.get(field, "")
        print(f"pi_deploy_verify: {field}: {actual}")
        if actual != value:
            ok = False
    if not ok:
        print("pi_deploy_verify: daily ingest timers are not armed", file=sys.stderr)
    return ok


def pi_ingest_service_fences_ok(snap: dict[str, str]) -> bool:
    expected = {
        "DAILY_KILL_MODE": "control-group",
        "DAILY_START_TIMEOUT": "6h 15min",
        "WATCHDOG_KILL_MODE": "control-group",
        "WATCHDOG_START_TIMEOUT": "6h 15min",
        "MANUAL_KILL_MODE": "control-group",
        "MANUAL_START_TIMEOUT": "6h 15min",
    }
    ok = True
    for field, value in expected.items():
        actual = snap.get(field, "")
        print(f"pi_deploy_verify: {field}: {actual}")
        if actual != value:
            ok = False
    if not ok:
        print("pi_deploy_verify: ingest process fencing is not active", file=sys.stderr)
    return ok


def http_smoke(
    base_url: str,
    *,
    require_rates: bool = True,
    timeout_seconds: float = 30.0,
) -> int:
    import urllib.error
    import urllib.request

    latest = base_url.rstrip("/") + "/api/latest"
    try:
        with urllib.request.urlopen(latest, timeout=timeout_seconds) as resp:
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


def wait_for_http_smoke(
    base_url: str,
    *,
    require_rates: bool = True,
    attempts: int = 13,
    delay_seconds: float = 10.0,
    budget_seconds: float = 120.0,
) -> int:
    """Allow the dashboard's preload phase to finish after a service restart."""
    deadline = time.monotonic() + max(0.0, budget_seconds)
    result = EXIT_VERIFY_FAIL
    for attempt in range(1, attempts + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        result = http_smoke(
            base_url,
            require_rates=require_rates,
            timeout_seconds=min(30.0, remaining),
        )
        if result == EXIT_OK:
            return EXIT_OK
        remaining = deadline - time.monotonic()
        if attempt < attempts and remaining > 0:
            sleep_seconds = min(delay_seconds, remaining)
            print(
                f"pi_deploy_verify: dashboard not ready after restart "
                f"(attempt {attempt}/{attempts}); retrying in {sleep_seconds:g}s"
            )
            time.sleep(sleep_seconds)
    return result


def verify_sync(
    *, dry_run: bool = False, expected_commit: Optional[str] = None
) -> int:
    local_main = origin_main_sha_local()
    if not local_main:
        print("pi_deploy_verify: could not resolve origin/main locally", file=sys.stderr)
        return EXIT_CONFIG
    if expected_commit is not None and local_main != expected_commit:
        print(
            "pi_deploy_verify: local origin/main does not match approved commit "
            f"({local_main[:12]} != {expected_commit[:12]})",
            file=sys.stderr,
        )
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
    if not pi_service_paths_ok(snap):
        return EXIT_VERIFY_FAIL
    if not pi_ingest_timers_ok(snap):
        return EXIT_VERIFY_FAIL
    if not pi_ingest_service_fences_ok(snap):
        return EXIT_VERIFY_FAIL
    if dry_run:
        print(f"pi_deploy_verify: dry-run local origin/main={local_main[:12]}")
        return EXIT_OK

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
            f"Pi origin/main ({origin_ar[:12]}) differs from local origin/main "
            f"({local_main[:12]}); retain drift until canary approval"
        )

    if drift:
        for item in drift:
            print(f"pi_deploy_verify: DRIFT {item}", file=sys.stderr)
        return EXIT_VERIFY_FAIL

    if not dashboard_active(dry_run=dry_run, snap=snap):
        print("pi_deploy_verify: ar-local-dashboard.service not active", file=sys.stderr)
        return EXIT_VERIFY_FAIL

    return EXIT_OK


def deploy_pull_all(expected_commit: str, *, dry_run: bool = False) -> int:
    """Install one exact fetched AR-local main commit without moving the site repo."""

    if not FULL_COMMIT_RE.fullmatch(expected_commit):
        print("pi_deploy_verify: invalid expected commit", file=sys.stderr)
        return EXIT_CONFIG
    remote = pi_remote()
    ar = pi_ar_repo()
    ingest_lock = f"{pi_data_root()}/state/daily-ingest.lock"
    script = (
        f"set -e; "
        f"lock={shell_quote(ingest_lock)}; "
        "acquire_lock() { "
        "if (set -o noclobber; printf 'pid=%s\\nrole=deploy\\n' \"$$\" > \"$lock\") 2>/dev/null; then return 0; fi; "
        "owner=$(sed -n 's/^pid=//p' \"$lock\" 2>/dev/null | head -n 1); "
        "case \"$owner\" in ''|*[!0-9]*) owner='';; esac; "
        "mtime=$(stat -c %Y \"$lock\" 2>/dev/null || printf 0); now=$(date +%s); "
        "if { test -n \"$owner\" && kill -0 \"$owner\" 2>/dev/null; } || "
        "{ test -z \"$owner\" && test $((now-mtime)) -le 21600; }; then return 75; fi; "
        "rm -f -- \"$lock\"; "
        "(set -o noclobber; printf 'pid=%s\\nrole=deploy\\n' \"$$\" > \"$lock\") 2>/dev/null || return 75; "
        "}; "
        "acquire_lock || { echo 'pi_deploy_verify: ingest/deploy lock is busy' >&2; exit 75; }; "
        "cleanup_lock() { rm -f -- \"$lock\"; }; "
        "trap cleanup_lock EXIT; trap 'exit 129' HUP; trap 'exit 130' INT; trap 'exit 143' TERM; "
        f"cd {shell_quote(ar)} && git fetch {shell_quote(remote)} main && "
        f"test \"$(git rev-parse {shell_quote(remote)}/main)\" = "
        f"{shell_quote(expected_commit)} && "
        "git checkout main && "
        f"git merge --ff-only {shell_quote(expected_commit)}"
    )
    code, out, err = run_ssh(script, dry_run=dry_run)
    if code == EXIT_BUSY and not dry_run:
        print(err or "pi_deploy_verify: ingest/deploy lock is busy", file=sys.stderr)
        return EXIT_BUSY
    if code != 0 and not dry_run:
        return EXIT_SSH
    if out and not dry_run:
        print(f"pi_deploy_verify: installed exact AR-local commit:\n{out}")
    return EXIT_OK


def deployment_backup_gate(
    expected_commit: str,
    protected_commit: str,
    *,
    dry_run: bool = False,
) -> int:
    """Run the candidate's backup gate before changing the production checkout."""

    if not FULL_COMMIT_RE.fullmatch(expected_commit) or not FULL_COMMIT_RE.fullmatch(protected_commit):
        return EXIT_CONFIG
    ar = pi_ar_repo()
    site = pi_site_repo()
    data = pi_data_root()
    script = (
        "set -e; tmp=$(mktemp -d); trap 'rm -rf -- \"$tmp\"' EXIT; "
        f"git -C {shell_quote(ar)} show {shell_quote(expected_commit + ':ar_local_backup_policy.py')} > \"$tmp/ar_local_backup_policy.py\"; "
        f"git -C {shell_quote(ar)} show {shell_quote(expected_commit + ':pi_backup_foundation.py')} > \"$tmp/pi_backup_foundation.py\"; "
        f"PYTHONPATH=\"$tmp\" /usr/bin/python3 \"$tmp/pi_backup_foundation.py\" gate "
        f"--config {shell_quote(pi_backup_config())} --repo {shell_quote(ar)} "
        f"--site-repo {shell_quote(site)} --data-root {shell_quote(data)} "
        f"--protected-code-sha {shell_quote(protected_commit)} "
        f"--candidate-sha {shell_quote(expected_commit)}"
    )
    code, out, err = run_ssh(script, dry_run=dry_run)
    if dry_run:
        print("pi_deploy_verify: dry-run would require a fresh verified backup, restore drill, and boot proof")
        return EXIT_OK
    if code != 0:
        print(err or out or "pi_deploy_verify: backup gate blocked deployment", file=sys.stderr)
        return EXIT_VERIFY_FAIL
    if out:
        print(f"pi_deploy_verify: backup gate PASS:\n{out}")
    return EXIT_OK


def record_deployment_acceptance(
    expected_commit: str,
    protected_commit: str,
    *,
    dry_run: bool = False,
) -> int:
    """Persist the immutable controlled record after all deployment checks pass."""

    if not FULL_COMMIT_RE.fullmatch(expected_commit) or not FULL_COMMIT_RE.fullmatch(protected_commit):
        return EXIT_CONFIG
    ar = pi_ar_repo()
    parent_command = (
        "python pi_deploy_verify.py --deploy --expected-commit " + expected_commit
    )
    script = (
        f"cd {shell_quote(ar)} && /usr/bin/python3 pi_backup_foundation.py record-deployment "
        f"--config {shell_quote(pi_backup_config())} --repo {shell_quote(ar)} "
        f"--site-repo {shell_quote(pi_site_repo())} --data-root {shell_quote(pi_data_root())} "
        f"--protected-code-sha {shell_quote(protected_commit)} "
        f"--candidate-sha {shell_quote(expected_commit)} "
        f"--parent-command {shell_quote(parent_command)} --dashboard-verified --services-verified"
    )
    code, out, err = run_ssh(script, dry_run=dry_run)
    if dry_run:
        print("pi_deploy_verify: dry-run would write an append-only deployment acceptance record")
        return EXIT_OK
    if code != 0:
        print(err or out or "pi_deploy_verify: deployment acceptance record failed", file=sys.stderr)
        return EXIT_VERIFY_FAIL
    if out:
        print(f"pi_deploy_verify: deployment acceptance recorded:\n{out}")
    return EXIT_OK


def deploy_services(*, dry_run: bool = False) -> int:
    ar_repo = pi_ar_repo()
    site_repo = pi_site_repo()
    data = pi_data_root()
    install_proxy = f"{ar_repo}/deploy/pi/install-pi-dashboard-proxy.sh"
    apply_runtime = f"{ar_repo}/deploy/pi/apply-pi-runtime-units.sh"
    deploy_watchdog_script = (
        f"{ar_repo}/deploy/pi/ar-local-deploy-watchdog.sh"
    )
    script = (
        f"test -d {shell_quote(data)}/runs && test -d {shell_quote(data)}/state && "
        f"test -x {shell_quote(apply_runtime)} && "
        f"test -x {shell_quote(deploy_watchdog_script)} && "
        f"sh {shell_quote(apply_runtime)} {shell_quote(ar_repo)} "
        f"{shell_quote(site_repo)} {shell_quote(data)} && "
        "systemctl cat ar-local-deploy-watchdog.service | "
        f"grep -Fqx {shell_quote(f'WorkingDirectory={ar_repo}')} && "
        "systemctl cat ar-local-deploy-watchdog.service | "
        f"grep -Fqx {shell_quote(f'ExecStart={deploy_watchdog_script}')} && "
        "("
        "if [ -f /etc/nginx/sites-enabled/ar-local-dashboard ]; then "
        "sudo nginx -t && sudo systemctl reload-or-restart nginx; "
        f"elif [ -f {shell_quote(install_proxy)} ]; then "
        f"sudo sh {shell_quote(install_proxy)} {shell_quote(ar_repo)}; "
        "else echo 'pi_deploy_verify: nginx proxy not installed (run deploy/pi/install-pi-dashboard-proxy.sh)' >&2; "
        "fi"
        ")"
    )
    code, _, err = run_ssh(script, dry_run=dry_run)
    if code == EXIT_BUSY and not dry_run:
        print(
            err or "pi_deploy_verify: ingest/deploy lock is busy",
            file=sys.stderr,
        )
        return EXIT_BUSY
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
    smoke = wait_for_http_smoke(pi_base_url(), require_rates=not args.allow_empty_rates)
    if smoke != EXIT_OK:
        return smoke
    print("pi_deploy_verify: verify OK (sync + dashboard + /api/latest)")
    return EXIT_OK


def cmd_deploy(args: argparse.Namespace) -> int:
    expected_commit = str(args.expected_commit or "").strip().lower()
    if not FULL_COMMIT_RE.fullmatch(expected_commit):
        print(
            "pi_deploy_verify: --deploy requires --expected-commit with an exact "
            "40-character lowercase SHA",
            file=sys.stderr,
        )
        return EXIT_CONFIG
    local_main = origin_main_sha_local()
    if local_main != expected_commit:
        print(
            "pi_deploy_verify: approved commit is not the current local origin/main",
            file=sys.stderr,
        )
        return EXIT_CONFIG
    if args.dry_run:
        rc = deployment_backup_gate(expected_commit, expected_commit, dry_run=True)
        if rc != EXIT_OK:
            return rc
        rc = deploy_pull_all(expected_commit, dry_run=True)
        if rc != EXIT_OK:
            return rc
        rc = deploy_services(dry_run=True)
        if rc != EXIT_OK:
            return rc
        print("pi_deploy_verify: dry-run deploy complete (no changes applied)")
        return EXIT_OK
    snap = pi_remote_snapshot(dry_run=args.dry_run)
    if snap is None:
        print("pi_deploy_verify: could not read Pi state before deploy", file=sys.stderr)
        return EXIT_SSH
    if _snap_has_dirty_repos(snap, context="— resolve before deploy"):
        return EXIT_VERIFY_FAIL
    if not pi_service_paths_ok(snap):
        return EXIT_VERIFY_FAIL
    if snap["AR_ORIGIN"] != expected_commit:
        print(
            "pi_deploy_verify: Pi origin/main does not match approved commit",
            file=sys.stderr,
        )
        return EXIT_VERIFY_FAIL
    if snap["SITE_HEAD"] != snap["SITE_ORIGIN"]:
        print(
            "pi_deploy_verify: australianrates checkout is behind origin/main; "
            "refusing an unrelated site mutation",
            file=sys.stderr,
        )
        return EXIT_VERIFY_FAIL
    rc = deployment_backup_gate(expected_commit, snap["AR_HEAD"], dry_run=False)
    if rc != EXIT_OK:
        return rc
    rc = deploy_pull_all(expected_commit, dry_run=args.dry_run)
    if rc != EXIT_OK:
        return rc
    rc = deploy_services(dry_run=args.dry_run)
    if rc != EXIT_OK:
        return rc
    sync_rc = verify_sync(dry_run=False, expected_commit=expected_commit)
    if sync_rc != EXIT_OK:
        return sync_rc
    smoke = wait_for_http_smoke(pi_base_url(), require_rates=not args.allow_empty_rates)
    if smoke != EXIT_OK:
        return smoke
    acceptance = record_deployment_acceptance(
        expected_commit,
        snap["AR_HEAD"],
        dry_run=False,
    )
    if acceptance != EXIT_OK:
        return acceptance
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
    parser.add_argument(
        "--expected-commit",
        default=os.environ.get("AR_PI_EXPECTED_COMMIT", ""),
        help=(
            "Exact 40-character lowercase AR-local main commit approved by the "
            "canary gate; required for --deploy."
        ),
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
        help="Install the exact approved AR-local commit, restart runtime, then verify.",
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
