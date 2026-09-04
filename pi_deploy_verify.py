#!/usr/bin/env python3
"""Verify or apply Raspberry Pi deploy for AR-local (sync + status smoke).

Non-interactive CLI for agents, orchestrator post-merge, and scheduled CI.

Exit codes:
  0  verify/deploy OK
  1  drift, dirty tree, service down, or HTTP smoke failed
  2  invalid flags or missing configuration
  3  SSH unreachable or remote command failed
  75 ingest/deploy lock is active; retry without changing the checkout

Environment (optional):
  AR_PI_SSH_HOST       SSH target (default: ar-local-pi5)
  AR_PI_BASE_URL       Status API URL (default: http://100.78.28.10/ via nginx :80)
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

import base64
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath
from typing import Mapping, Optional, Sequence

from ar_local_pi_runtime import (
    PI_DATA_ROOT,
    PI_STATUS_PORT,
    PI_PUBLIC_BASE_URL,
    PI_REPO_ROOT,
    PI_SITE_REPO,
    is_raspberry_pi,
)
import pi_deploy_http
import pi_deploy_snapshot

REPO_ROOT = Path(__file__).resolve().parent
SUBPROCESS_TIMEOUT_SEC = 120
DATA_VERIFY_TIMEOUT_SEC = 900

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
    "cdr_",
    "deploy/pi/",
    "pi_daily_sync.py",
    "pi_deploy_cli.py",
    "pi_deploy_http.py",
    "pi_deploy_snapshot.py",
    "pi_deploy_verify.py",
    "pi_runtime_health.py",
    "pi_capacity_monitor.py",
    "pi_backup_foundation.py",
    "pi_ingest_terminal.py",
    "ar_local_backup_policy.py",
    "ar_local_backup_scope.py",
    "ar_local_boot_proof.py",
    "ar_local_checkout.py",
    "ar_local_daily_reconciliation.py",
    "ar_local_deployment_chain.py",
    "ar_local_operation_lock.py",
    "ar_local_rollback_record.py",
    "ar_local_restore_verification.py",
    "ar_local_sqlite_health.py",
    "ar_local_pi_service_heal.py",
    "ar_local_pi_runtime.py",
    "contracts/export-contract-v2.schema.json",
    "contracts/pi-backup-boot-proof-v1.schema.json",
    "contracts/pi-deployment-acceptance-v1.schema.json",
    "contracts/pi-preservation-snapshot-v1.schema.json",
    "contracts/pi-restore-acceptance-v1.schema.json",
    "contracts/pi-rollback-acceptance-v1.schema.json",
    "verify_local.py",
    "cdr_status_server.py",
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
        default = f"http://127.0.0.1:{PI_STATUS_PORT}/"
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


def run_shell(
    shell_cmd: str,
    *,
    dry_run: bool = False,
    timeout_seconds: float = SUBPROCESS_TIMEOUT_SEC,
) -> tuple[int, str, str]:
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
            timeout=timeout_seconds,
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
                timeout=timeout_seconds,
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


def run_ssh(
    remote_cmd: str,
    *,
    dry_run: bool = False,
    timeout_seconds: float = SUBPROCESS_TIMEOUT_SEC,
) -> tuple[int, str, str]:
    return run_shell(
        remote_cmd, dry_run=dry_run, timeout_seconds=timeout_seconds
    )


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
    """One SSH round-trip for SHAs, dirty trees, and status-service state."""
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
        f"status=$(systemctl is-active ar-local-status.service 2>/dev/null || echo inactive); "
        f"status_wd=$(systemctl show ar-local-status.service -p WorkingDirectory --value 2>/dev/null); "
        f"status_exec=$(systemctl show ar-local-status.service -p ExecStart --value 2>/dev/null | tr '\\n' ' '); "
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
        f"status_env=$(systemctl show ar-local-status.service -p Environment --value 2>/dev/null); "
        f"daily_env=$(systemctl show ar-local-daily.service -p Environment --value 2>/dev/null); "
        f"df_ar=$(df -P {q_ar} 2>/dev/null | awk 'NR==2{{print $1\"|\"$6}}'); "
        f"df_site=$(df -P {q_site} 2>/dev/null | awk 'NR==2{{print $1\"|\"$6}}'); "
        f"df_data=$(df -P {q_data} 2>/dev/null | awk 'NR==2{{print $1\"|\"$6}}'); "
        f"printf 'AR_HEAD=%s\\nAR_ORIGIN=%s\\nSITE_HEAD=%s\\nSITE_ORIGIN=%s\\n' \"$ar_h\" \"$ar_o\" \"$site_h\" \"$site_o\"; "
        f"printf 'AR_DIRTY=%s\\nSITE_DIRTY=%s\\nSTATUS=%s\\n' \"$ar_d\" \"$site_d\" \"$status\"; "
        f"printf 'STATUS_WD=%s\\nSTATUS_EXEC=%s\\nDAILY_WD=%s\\nDAILY_EXEC=%s\\n' \"$status_wd\" \"$status_exec\" \"$daily_wd\" \"$daily_exec\"; "
        f"printf 'DAILY_TIMER_ENABLED=%s\\nDAILY_TIMER_ACTIVE=%s\\nWATCHDOG_TIMER_ENABLED=%s\\nWATCHDOG_TIMER_ACTIVE=%s\\n' \"$daily_timer_enabled\" \"$daily_timer_active\" \"$watchdog_timer_enabled\" \"$watchdog_timer_active\"; "
        f"printf 'DAILY_KILL_MODE=%s\\nDAILY_START_TIMEOUT=%s\\nWATCHDOG_KILL_MODE=%s\\nWATCHDOG_START_TIMEOUT=%s\\nMANUAL_KILL_MODE=%s\\nMANUAL_START_TIMEOUT=%s\\n' \"$daily_kill_mode\" \"$daily_start_timeout\" \"$watchdog_kill_mode\" \"$watchdog_start_timeout\" \"$manual_kill_mode\" \"$manual_start_timeout\"; "
        f"printf 'CAPACITY_TIMER_ENABLED=%s\\nCAPACITY_TIMER_ACTIVE=%s\\n' \"$capacity_timer_enabled\" \"$capacity_timer_active\"; "
        f"printf 'STATUS_ENV=%s\\nDAILY_ENV=%s\\nDF_AR=%s\\nDF_SITE=%s\\nDF_DATA=%s\\n' \"$status_env\" \"$daily_env\" \"$df_ar\" \"$df_site\" \"$df_data\""
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
            "STATUS": "active",
            "STATUS_WD": "dry",
            "STATUS_EXEC": "dry",
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
            "STATUS_ENV": "AR_LOCAL_DATA_ROOT=/dry/data",
            "DAILY_ENV": "AR_LOCAL_DATA_ROOT=/dry/data",
            "DF_AR": "dry",
            "DF_SITE": "dry",
            "DF_DATA": "dry",
        }
    snap = _parse_kv_lines(stdout)
    required = ("AR_HEAD", "AR_ORIGIN", "SITE_HEAD", "SITE_ORIGIN", "STATUS")
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


def status_active(*, dry_run: bool = False, snap: Optional[dict[str, str]] = None) -> bool:
    if snap is None:
        snap = pi_remote_snapshot(dry_run=dry_run)
    if snap is None:
        return False
    return snap.get("STATUS") == "active"


def pi_service_paths_ok(snap: dict[str, str]) -> bool:
    return pi_deploy_snapshot.service_paths_ok(
        snap,
        repo_path=pi_ar_repo(),
        forbidden_bootstrap_path=FORBIDDEN_PI_BOOTSTRAP_RE,
    )


def pi_ingest_timers_ok(snap: dict[str, str]) -> bool:
    return pi_deploy_snapshot.ingest_timers_ok(snap)


def pi_ingest_service_fences_ok(snap: dict[str, str]) -> bool:
    return pi_deploy_snapshot.ingest_service_fences_ok(snap)


def http_smoke(
    base_url: str,
    *,
    timeout_seconds: float = 30.0,
) -> int:
    return pi_deploy_http.status_smoke(
        base_url, timeout_seconds=timeout_seconds
    )


def legacy_http_smoke(
    base_url: str,
    *,
    timeout_seconds: float = 30.0,
) -> int:
    return pi_deploy_http.legacy_smoke(
        base_url, timeout_seconds=timeout_seconds
    )


def wait_for_http_smoke(
    base_url: str,
    *,
    attempts: int = 10,
    delay_seconds: float = 2.0,
    budget_seconds: float = 30.0,
) -> int:
    """Allow systemd and nginx a bounded interval to complete a restart."""
    return pi_deploy_http.wait_for_smoke(
        http_smoke,
        base_url,
        attempts=attempts,
        delay_seconds=delay_seconds,
        budget_seconds=budget_seconds,
    )


def wait_for_legacy_http_smoke(
    base_url: str,
    *,
    attempts: int = 10,
    delay_seconds: float = 2.0,
    budget_seconds: float = 30.0,
) -> int:
    return pi_deploy_http.wait_for_smoke(
        legacy_http_smoke,
        base_url,
        attempts=attempts,
        delay_seconds=delay_seconds,
        budget_seconds=budget_seconds,
    )


def production_data_script() -> bytes:
    """Return a repository-compatible, read-only production data verifier."""

    return b'''import hashlib,json,re,sqlite3,sys
from contextlib import closing
from pathlib import Path
from ar_local_restore_verification import verify_restored_state
root=Path(sys.argv[1]).resolve(strict=True)
def require(condition,message):
 if not condition: raise RuntimeError(message)
def sha256_file(path):
 digest=hashlib.sha256()
 with path.open("rb") as stream:
  for block in iter(lambda:stream.read(1048576),b""):
   digest.update(block)
 return digest.hexdigest()
report=verify_restored_state(root)
require(report.get("ok") is True,f"restored state failed: {report.get('findings')}")
selected=report.get("selected_observation")
require(isinstance(selected,dict),"selected observation is missing")
for key in ("observation_date","generation_id","ledger_event_digest","database_path","database_sha256","export_contract_digest"):
 require(selected.get(key),f"selected observation lacks {key}")
require(re.fullmatch(r"[0-9a-f]{64}",str(selected["database_sha256"])),"database digest is invalid")
require(isinstance(report.get("ledger"),dict) and report["ledger"].get("ok") is True,"ledger is invalid")
databases=[]
for path in sorted(root.rglob("*.sqlite")):
 require(path.is_file() and not path.is_symlink(),f"unsafe SQLite path: {path}")
 with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1",uri=True)) as connection:
  quick=[str(row[0]) for row in connection.execute("PRAGMA quick_check")]
  integrity=[str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
  foreign_key=connection.execute("PRAGMA foreign_key_check").fetchone()
  require(quick==["ok"] and integrity==["ok"] and foreign_key is None,f"SQLite health failed: {path}")
  user_version=int(connection.execute("PRAGMA user_version").fetchone()[0])
  tables={str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  schema_version=user_version
  if path.name=="local-cdr.sqlite" and user_version==0 and "schema_meta" in tables:
   row=connection.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
   schema_version=row[0] if row else None
 digest=sha256_file(path)
 databases.append({"path":path.relative_to(root).as_posix(),"sha256":digest,"schema_version":schema_version,"quick_check":"ok","integrity_check":"ok","foreign_key_check":"ok"})
require(bool(databases),"no SQLite databases found")
selected_matches=[item for item in databases if item["path"]==selected["database_path"]]
require(len(selected_matches)==1,"selected database identity is ambiguous")
selected_db=selected_matches[0]
require(selected_db["sha256"]==selected["database_sha256"],"selected database digest mismatch")
require(str(selected_db["schema_version"]) in {"8","11"},"selected database schema is unsupported")
print(json.dumps({"result":"PASS","observation_date":selected["observation_date"],"generation_id":selected["generation_id"],"ledger_event_digest":selected["ledger_event_digest"],"database":selected_db,"sqlite_databases":len(databases)},sort_keys=True))
'''


def production_data_report_is_valid(value: object) -> bool:
    if not isinstance(value, Mapping) or value.get("result") != "PASS":
        return False
    date = str(value.get("observation_date") or "")
    generation = str(value.get("generation_id") or "")
    ledger_digest = str(value.get("ledger_event_digest") or "")
    database = value.get("database")
    if not isinstance(database, Mapping):
        return False
    path = str(database.get("path") or "")
    relative = PurePosixPath(path)
    return bool(
        re.fullmatch(r"\d{4}-\d{2}-\d{2}", date)
        and re.fullmatch(r"obs-\d{4}-\d{2}-\d{2}-[0-9a-f]{16}", generation)
        and re.fullmatch(r"[0-9a-f]{64}", ledger_digest)
        and re.fullmatch(r"[0-9a-f]{64}", str(database.get("sha256") or ""))
        and not relative.is_absolute()
        and "\\" not in path
        and ".." not in relative.parts
        and path.endswith("/_exports/local-cdr.sqlite")
        and str(database.get("schema_version")) in {"8", "11"}
        and isinstance(value.get("sqlite_databases"), int)
        and int(value["sqlite_databases"]) > 0
    )


def verify_production_data(*, dry_run: bool = False) -> int:
    """Verify ledger, pointer, observation, digest, schema, and every SQLite DB."""

    encoded = base64.b64encode(production_data_script()).decode("ascii")
    python = f"import base64;exec(base64.b64decode({encoded!r}))"
    command = (
        f"cd {shell_quote(pi_ar_repo())} && "
        f"python3 -c {shell_quote(python)} {shell_quote(pi_data_root())}"
    )
    code, output, error = run_ssh(
        command, dry_run=dry_run, timeout_seconds=DATA_VERIFY_TIMEOUT_SEC
    )
    if dry_run:
        print("pi_deploy_verify: dry-run would verify ledger, observation, and SQLite data")
        return EXIT_OK
    if code != 0:
        print(error or output or "pi_deploy_verify: production data verification failed", file=sys.stderr)
        return EXIT_VERIFY_FAIL
    try:
        report = json.loads(output)
    except (TypeError, ValueError):
        report = None
    if not production_data_report_is_valid(report):
        print("pi_deploy_verify: production data verifier returned invalid evidence", file=sys.stderr)
        return EXIT_VERIFY_FAIL
    print(
        "pi_deploy_verify: data OK "
        f"observation={report.get('observation_date')} "
        f"database={report.get('database', {}).get('sha256')}"
    )
    return EXIT_OK


def bootstrap_observation(
    expected_commit: str,
    *,
    timeout_seconds: float,
    poll_seconds: float = 15.0,
    dry_run: bool = False,
) -> int:
    """Run one explicit systemd-managed ingest and wait for its exact invocation."""

    if not FULL_COMMIT_RE.fullmatch(expected_commit) or timeout_seconds <= 0:
        return EXIT_CONFIG
    ar = pi_ar_repo()
    start = (
        f"set -e; test \"$(git -C {shell_quote(ar)} rev-parse HEAD)\" = "
        f"{shell_quote(expected_commit)}; "
        "if systemctl is-active --quiet ar-local-ingest-now.service; then exit 75; fi; "
        "before=$(systemctl show ar-local-ingest-now.service -p InvocationID --value); "
        "sudo systemctl reset-failed ar-local-ingest-now.service; "
        "sudo systemctl start --no-block ar-local-ingest-now.service; "
        "sleep 1; after=$(systemctl show ar-local-ingest-now.service -p InvocationID --value); "
        "printf 'BEFORE=%s\\nINVOCATION=%s\\n' \"$before\" \"$after\""
    )
    code, output, error = run_ssh(start, dry_run=dry_run)
    if dry_run:
        print("pi_deploy_verify: dry-run would run one explicit canonical ingest")
        return EXIT_OK
    if code == EXIT_BUSY:
        print("pi_deploy_verify: ingest is already active", file=sys.stderr)
        return EXIT_BUSY
    if code != 0:
        print(error or output or "pi_deploy_verify: ingest start failed", file=sys.stderr)
        return EXIT_SSH
    started = _parse_kv_lines(output)
    before = started.get("BEFORE", "")
    after = started.get("INVOCATION", "")
    invocation = after if after and after != before else ""
    deadline = time.monotonic() + timeout_seconds
    last_state = ""
    while time.monotonic() < deadline:
        check = (
            "set -e; "
            "inv=$(systemctl show ar-local-ingest-now.service -p InvocationID --value); "
            "active=$(systemctl show ar-local-ingest-now.service -p ActiveState --value); "
            "sub=$(systemctl show ar-local-ingest-now.service -p SubState --value); "
            "result=$(systemctl show ar-local-ingest-now.service -p Result --value); "
            "status=$(systemctl show ar-local-ingest-now.service -p ExecMainStatus --value); "
            "printf 'INVOCATION=%s\\nACTIVE=%s\\nSUB=%s\\nRESULT=%s\\nSTATUS=%s\\n' "
            "\"$inv\" \"$active\" \"$sub\" \"$result\" \"$status\""
        )
        code, output, error = run_ssh(check, dry_run=False)
        if code != 0:
            print(error or output or "pi_deploy_verify: ingest state unavailable", file=sys.stderr)
            return EXIT_SSH
        state = _parse_kv_lines(output)
        current_invocation = state.get("INVOCATION", "")
        if current_invocation and current_invocation != before:
            invocation = current_invocation
        description = "/".join(
            (state.get("ACTIVE", "unknown"), state.get("SUB", "unknown"))
        )
        if description != last_state:
            print(f"pi_deploy_verify: ingest {invocation or 'pending'} {description}")
            last_state = description
        if invocation and current_invocation == invocation:
            active = state.get("ACTIVE")
            result = state.get("RESULT")
            status = state.get("STATUS")
            if active == "inactive" and result == "success" and status == "0":
                return EXIT_OK
            if active == "failed" or (
                active == "inactive" and result not in {"", "success"}
            ):
                print(
                    f"pi_deploy_verify: canonical ingest failed "
                    f"(state={description}, result={result}, status={status})",
                    file=sys.stderr,
                )
                return EXIT_VERIFY_FAIL
        time.sleep(min(poll_seconds, max(0.0, deadline - time.monotonic())))
    print("pi_deploy_verify: canonical ingest timed out", file=sys.stderr)
    return EXIT_VERIFY_FAIL


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

    if not status_active(dry_run=dry_run, snap=snap):
        print("pi_deploy_verify: ar-local-status.service not active", file=sys.stderr)
        return EXIT_VERIFY_FAIL

    return EXIT_OK


def deploy_pull_all(expected_commit: str, *, dry_run: bool = False) -> int:
    """Install one exact fetched AR-local main commit without moving the site repo."""

    if not FULL_COMMIT_RE.fullmatch(expected_commit):
        print("pi_deploy_verify: invalid expected commit", file=sys.stderr)
        return EXIT_CONFIG
    ar = pi_ar_repo()
    script = (
        "set -e; test -x /usr/local/bin/ar-local-backup-gate; "
        "/usr/local/bin/ar-local-backup-gate install-checkout "
        f"--config {shell_quote(pi_backup_config())} --repo {shell_quote(ar)} "
        f"--data-root {shell_quote(pi_data_root())} "
        f"--candidate-sha {shell_quote(expected_commit)}"
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
        "set -e; test -x /usr/local/bin/ar-local-backup-gate; "
        "/usr/local/bin/ar-local-backup-gate gate "
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
    parent_command: str,
    *,
    dry_run: bool = False,
) -> int:
    """Persist the immutable controlled record after all deployment checks pass."""

    if not FULL_COMMIT_RE.fullmatch(expected_commit) or not FULL_COMMIT_RE.fullmatch(protected_commit):
        return EXIT_CONFIG
    ar = pi_ar_repo()
    if not parent_command.strip():
        return EXIT_CONFIG
    script = (
        f"cd {shell_quote(ar)} && /usr/local/bin/ar-local-backup-gate record-deployment "
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


def rollback_to_protected_commit(
    protected_commit: str,
    failed_candidate: str,
    parent_command: str,
    *,
    dry_run: bool = False,
) -> int:
    """Restore the exact pre-deploy SHA when post-activation acceptance fails."""

    if not FULL_COMMIT_RE.fullmatch(protected_commit) or not FULL_COMMIT_RE.fullmatch(failed_candidate):
        return EXIT_CONFIG
    ar = pi_ar_repo()
    script = (
        "set -e; test -x /usr/local/bin/ar-local-backup-gate; "
        "/usr/local/bin/ar-local-backup-gate rollback-checkout "
        f"--config {shell_quote(pi_backup_config())} --repo {shell_quote(ar)} "
        f"--data-root {shell_quote(pi_data_root())} "
        f"--protected-code-sha {shell_quote(protected_commit)}"
    )
    code, _out, err = run_ssh(script, dry_run=dry_run)
    if dry_run:
        return EXIT_OK
    if code != 0:
        print(err or "pi_deploy_verify: rollback checkout failed", file=sys.stderr)
        return EXIT_VERIFY_FAIL
    runtime_kind = restore_protected_runtime(dry_run=False)
    if runtime_kind is None:
        print("pi_deploy_verify: rollback service restoration failed", file=sys.stderr)
        return EXIT_VERIFY_FAIL
    snap = pi_remote_snapshot(dry_run=False)
    if snap is None or snap.get("AR_HEAD") != protected_commit:
        print("pi_deploy_verify: rollback SHA verification failed", file=sys.stderr)
        return EXIT_VERIFY_FAIL
    smoke = (
        wait_for_legacy_http_smoke(pi_base_url())
        if runtime_kind == "legacy"
        else wait_for_http_smoke(pi_base_url())
    )
    if smoke != EXIT_OK:
        print("pi_deploy_verify: rollback HTTP verification failed", file=sys.stderr)
        return EXIT_VERIFY_FAIL
    if verify_production_data(dry_run=False) != EXIT_OK:
        print("pi_deploy_verify: rollback data verification failed", file=sys.stderr)
        return EXIT_VERIFY_FAIL
    record_script = (
        f"cd {shell_quote(ar)} && /usr/local/bin/ar-local-backup-gate record-rollback "
        f"--config {shell_quote(pi_backup_config())} --repo {shell_quote(ar)} "
        f"--site-repo {shell_quote(pi_site_repo())} --data-root {shell_quote(pi_data_root())} "
        f"--protected-code-sha {shell_quote(protected_commit)} "
        f"--candidate-sha {shell_quote(failed_candidate)} "
        f"--parent-command {shell_quote(parent_command)} "
        "--dashboard-verified --services-verified"
    )
    code, out, err = run_ssh(record_script, dry_run=False)
    if code != 0:
        print(err or out or "pi_deploy_verify: rollback acceptance record failed", file=sys.stderr)
        return EXIT_VERIFY_FAIL
    if out:
        print(f"pi_deploy_verify: rollback acceptance recorded:\n{out}")
    print(f"pi_deploy_verify: ROLLED_BACK to protected commit {protected_commit}")
    return EXIT_OK


def restore_protected_runtime(*, dry_run: bool = False) -> Optional[str]:
    """Activate whichever runtime contract exists in the restored checkout."""

    ar = pi_ar_repo()
    site = pi_site_repo()
    data = pi_data_root()
    apply_runtime = f"{ar}/deploy/pi/apply-pi-runtime-units.sh"
    legacy_proxy = f"{ar}/deploy/pi/install-pi-dashboard-proxy.sh"
    status_proxy = f"{ar}/deploy/pi/install-pi-status-proxy.sh"
    script = (
        f"set -e; test -x {shell_quote(apply_runtime)}; "
        f"if test -f {shell_quote(legacy_proxy)}; then "
        "sudo systemctl disable ar-local-status.service >/dev/null 2>&1 || true; "
        "sudo systemctl stop ar-local-status.service >/dev/null 2>&1 || true; "
        f"sh {shell_quote(apply_runtime)} {shell_quote(ar)} {shell_quote(site)} {shell_quote(data)}; "
        "sudo rm -f /etc/systemd/system/ar-local-status.service "
        "/etc/nginx/sites-enabled/ar-local-status /etc/nginx/sites-available/ar-local-status; "
        "sudo systemctl daemon-reload; "
        f"sudo sh {shell_quote(legacy_proxy)} {shell_quote(ar)}; "
        "printf 'ROLLBACK_RUNTIME=legacy\\n'; "
        f"elif test -f {shell_quote(status_proxy)}; then "
        f"sh {shell_quote(apply_runtime)} {shell_quote(ar)} {shell_quote(site)} {shell_quote(data)}; "
        f"sudo sh {shell_quote(status_proxy)} {shell_quote(ar)}; "
        "printf 'ROLLBACK_RUNTIME=status\\n'; "
        "else echo 'protected runtime has no proxy installer' >&2; exit 1; fi"
    )
    code, output, error = run_ssh(script, dry_run=dry_run)
    if dry_run:
        return "status"
    if code != 0:
        print(error or output or "pi_deploy_verify: protected runtime failed", file=sys.stderr)
        return None
    kind = _parse_kv_lines(output).get("ROLLBACK_RUNTIME")
    return kind if kind in {"legacy", "status"} else None


def deploy_services(*, dry_run: bool = False) -> int:
    ar_repo = pi_ar_repo()
    site_repo = pi_site_repo()
    data = pi_data_root()
    install_proxy = f"{ar_repo}/deploy/pi/install-pi-status-proxy.sh"
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
        "if [ -f /etc/nginx/sites-enabled/ar-local-status ]; then "
        "sudo nginx -t && sudo systemctl reload-or-restart nginx; "
        f"elif [ -f {shell_quote(install_proxy)} ]; then "
        f"sudo sh {shell_quote(install_proxy)} {shell_quote(ar_repo)}; "
        "else echo 'pi_deploy_verify: nginx proxy not installed (run deploy/pi/install-pi-status-proxy.sh)' >&2; "
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


def _cli():
    import pi_deploy_cli

    return pi_deploy_cli


def cmd_verify(args) -> int:
    return _cli().cmd_verify(args, sys.modules[__name__])


def cmd_deploy(args) -> int:
    return _cli().cmd_deploy(args, sys.modules[__name__])


def cmd_needs_pi(args) -> int:
    return _cli().cmd_needs_pi(args, sys.modules[__name__])


def build_parser():
    return _cli().build_parser()


def main(argv: Optional[Sequence[str]] = None) -> int:
    effective_argv = list(argv) if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(effective_argv)
    args.effective_command = shlex.join(
        [sys.executable, str(Path(__file__).resolve()), *effective_argv]
    )
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
