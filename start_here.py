"""Cross-platform Start Here menu: daily ingest, dashboard, schedule, git update, DB summary."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import sqlite3
import urllib.error
import urllib.request

from ar_local_git import git_compare_upstream, git_pull_ff_only
from ar_local_launcher_constants import (
    CRON_BEGIN,
    CRON_END,
    DAILY_WORKER_COUNT,
    ENV_DB_QUICK_CHECK,
    ENV_DB_QUICK_CHECK_ALT,
    INGEST_EXTRA_ARGS,
    SCHEDULE_UTC_HOUR,
    SCHEDULE_UTC_MINUTE,
    SYSTEMD_UNIT_NAME,
    TASK_NAME,
)
from ar_local_pi_runtime import data_runs_root, data_state_root
from ar_local_platform import HostKind, host_kind, platform_label
from ar_local_subprocess import run_checked

REPO_ROOT = Path(__file__).resolve().parent


def runs_dir_for_repo(repo: Path) -> Path:
    return data_runs_root(repo)


def state_dir_for_repo(repo: Path) -> Path:
    return data_state_root(repo)


RUNS_DIR = runs_dir_for_repo(REPO_ROOT)
STATE_DIR = state_dir_for_repo(REPO_ROOT)
DB_STATS_SNAPSHOT = STATE_DIR / "last_db_stats.json"


def resolve_python_argv() -> List[str]:
    exe = shutil.which("python")
    if exe:
        return [exe]
    exe = shutil.which("python3")
    if exe:
        return [exe]
    launcher = shutil.which("py")
    if launcher and sys.platform == "win32":
        return [launcher, "-3"]
    print("Python was not found. Install Python 3.10+ or add it to PATH.", file=sys.stderr)
    raise SystemExit(1)


def latest_run_date() -> Optional[str]:
    if not RUNS_DIR.is_dir():
        return None
    dates: List[str] = []
    for p in RUNS_DIR.iterdir():
        if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name):
            dates.append(p.name)
    if not dates:
        return None
    return sorted(dates)[-1]


def require_latest_run_date() -> str:
    d = latest_run_date()
    if not d:
        print("No run folders found. Run CDR ingest first (menu option 1).", file=sys.stderr)
        raise SystemExit(1)
    return d


def invoke_daily(force: bool) -> None:
    py = resolve_python_argv()
    args = [
        *py,
        str(REPO_ROOT / "cdr_daily.py"),
        "--runs",
        str(RUNS_DIR),
        "--state",
        str(STATE_DIR),
        "--workers",
        str(DAILY_WORKER_COUNT),
    ]
    if force:
        args.append("--force")
    run_checked(args, cwd=REPO_ROOT)


def invoke_rebuild() -> None:
    d = require_latest_run_date()
    py = resolve_python_argv()
    run_checked([*py, str(REPO_ROOT / "cdr_outputs.py"), str(RUNS_DIR / d)], cwd=REPO_ROOT)


def open_dashboard() -> None:
    d = require_latest_run_date()
    exports = RUNS_DIR / d / "_exports"
    if not exports.is_dir():
        invoke_rebuild()
    port_file = Path(tempfile.gettempdir()) / f"ar-cdr-dashboard-{os.urandom(8).hex()}.json"
    py = resolve_python_argv()
    argv = [
        *py,
        str(REPO_ROOT / "cdr_dashboard_server.py"),
        "--exports",
        str(exports),
        "--port",
        "auto",
        "--port-file",
        str(port_file),
    ]
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        argv,
        cwd=str(REPO_ROOT),
        creationflags=creationflags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
    )
    deadline = time.time() + 30.0
    url: Optional[str] = None
    try:
        while time.time() < deadline:
            if proc.poll() is not None:
                print(f"Dashboard server exited with code {proc.returncode}.", file=sys.stderr)
                raise SystemExit(1)
            if port_file.is_file():
                try:
                    data = json.loads(port_file.read_text(encoding="utf-8"))
                    url = str(data.get("url") or "")
                except (OSError, json.JSONDecodeError):
                    url = None
                if url:
                    health = url.rstrip("/") + "/api/latest"
                    try:
                        with urllib.request.urlopen(health, timeout=2):
                            pass
                        webbrowser.open(url)
                        print(f"\nDashboard opened: {url}\nServer process: {proc.pid}\n")
                        return
                    except (urllib.error.URLError, OSError):
                        pass
            time.sleep(0.5)
        print("Dashboard server did not become ready within 30 seconds.", file=sys.stderr)
        proc.kill()
        raise SystemExit(1)
    finally:
        port_file.unlink(missing_ok=True)


def install_windows_scheduled_task(
    hour_utc: int = SCHEDULE_UTC_HOUR,
    minute_utc: int = SCHEDULE_UTC_MINUTE,
) -> None:
    ps1 = REPO_ROOT / "install_daily_task.ps1"
    if not ps1.is_file():
        print("install_daily_task.ps1 missing.", file=sys.stderr)
        raise SystemExit(1)
    utc_at = f"{hour_utc:02d}:{minute_utc:02d}"
    run_checked(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ps1),
            "-RunAtUtc",
            "-UtcAt",
            utc_at,
            "-ExtraArgs",
            INGEST_EXTRA_ARGS,
        ],
        cwd=REPO_ROOT,
    )
    print(
        f"Registered Windows scheduled task '{TASK_NAME}' "
        f"daily at {utc_at} UTC (Task Scheduler XML; DST-stable)."
    )


def _cron_block(py: str, repo: Path) -> List[str]:
    repo_q = shlex.quote(str(repo))
    py_q = shlex.quote(py)
    script_q = shlex.quote(str(repo / "cdr_daily.py"))
    runs_q = shlex.quote(str(runs_dir_for_repo(repo)))
    state_q = shlex.quote(str(state_dir_for_repo(repo)))
    line = (
        f"{SCHEDULE_UTC_MINUTE} {SCHEDULE_UTC_HOUR} * * * cd {repo_q} && "
        f"{py_q} {script_q} --runs {runs_q} --state {state_q} --workers {DAILY_WORKER_COUNT}"
    )
    return [CRON_BEGIN, "CRON_TZ=UTC", line, CRON_END]


def read_user_crontab_raw() -> str:
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, shell=False)
    if r.returncode != 0:
        err = (r.stderr or "").lower()
        out = (r.stdout or "").lower()
        if "no crontab" in err or "no crontab" in out:
            return ""
        raise RuntimeError((r.stderr or r.stdout or "crontab -l failed").strip())
    return r.stdout or ""


def write_user_crontab_raw(content: str) -> None:
    r = subprocess.run(["crontab", "-"], input=content, text=True, shell=False)
    if r.returncode != 0:
        raise RuntimeError("crontab install failed")


def merge_crontab_block(new_lines: List[str]) -> None:
    raw = read_user_crontab_raw()
    lines = raw.splitlines()
    out: List[str] = []
    i = 0
    while i < len(lines):
        if lines[i].strip() == CRON_BEGIN:
            while i < len(lines) and lines[i].strip() != CRON_END:
                i += 1
            if i < len(lines) and lines[i].strip() == CRON_END:
                i += 1
            continue
        out.append(lines[i])
        i += 1
    if out and out[-1].strip():
        out.append("")
    out.extend(new_lines)
    write_user_crontab_raw("\n".join(out) + "\n")


def install_linux_cron() -> None:
    py = resolve_python_argv()[0]
    block = _cron_block(py, REPO_ROOT)
    merge_crontab_block(block)
    print(f"Installed user crontab block ({SCHEDULE_UTC_HOUR:02d}:{SCHEDULE_UTC_MINUTE:02d} UTC daily):")
    for ln in block:
        print(f"  {ln}")


def remove_linux_cron() -> None:
    raw = read_user_crontab_raw()
    lines = raw.splitlines()
    out: List[str] = []
    i = 0
    changed = False
    while i < len(lines):
        if lines[i].strip() == CRON_BEGIN:
            changed = True
            while i < len(lines) and lines[i].strip() != CRON_END:
                i += 1
            if i < len(lines) and lines[i].strip() == CRON_END:
                i += 1
            continue
        out.append(lines[i])
        i += 1
    if changed:
        write_user_crontab_raw("\n".join(out) + ("\n" if out else ""))
    print("Removed AR-local crontab block." if changed else "No AR-local crontab block found.")


def show_linux_cron() -> None:
    try:
        raw = read_user_crontab_raw()
    except RuntimeError as e:
        print(e)
        return
    inside = False
    for line in raw.splitlines():
        if line.strip() == CRON_BEGIN:
            inside = True
        if inside:
            print(line)
        if line.strip() == CRON_END:
            inside = False


def systemd_user_dir() -> Path:
    cfg = Path.home() / ".config" / "systemd" / "user"
    cfg.mkdir(parents=True, exist_ok=True)
    return cfg


def systemd_unit_path() -> Path:
    return systemd_user_dir() / SYSTEMD_UNIT_NAME


def _systemd_exec_word(path: Path) -> str:
    s = str(path)
    if any(c in s for c in (' ', '"', '\t')):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def write_boot_systemd_unit() -> None:
    py = resolve_python_argv()[0]
    script = REPO_ROOT / "cdr_daily.py"
    wd = _systemd_exec_word(REPO_ROOT)
    exec_line = (
        f"{_systemd_exec_word(Path(py))} {_systemd_exec_word(script)} "
        f"--runs {_systemd_exec_word(RUNS_DIR)} --state {_systemd_exec_word(STATE_DIR)} "
        f"--workers {DAILY_WORKER_COUNT}"
    )
    unit = f"""[Unit]
Description=AR-local CDR daily ingest on boot (skips if today already done)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory={wd}
ExecStart={exec_line}

[Install]
WantedBy=default.target
"""
    systemd_unit_path().write_text(unit, encoding="utf-8")


def systemctl_user(*args: str) -> None:
    run_checked(["systemctl", "--user", *args])


def boot_service_available() -> bool:
    if host_kind() == HostKind.WINDOWS:
        return False
    if shutil.which("systemctl") is None:
        return False
    return Path("/run/systemd/system").exists() or Path("/usr/lib/systemd/system").exists()


def enable_boot_ingest() -> None:
    if not boot_service_available():
        print("systemd user session not available on this host.", file=sys.stderr)
        raise SystemExit(1)
    write_boot_systemd_unit()
    systemctl_user("daemon-reload")
    systemctl_user("enable", SYSTEMD_UNIT_NAME)
    print(f"Enabled user service {SYSTEMD_UNIT_NAME} (runs cdr_daily on boot; skips if today is done).")


def disable_boot_ingest() -> None:
    if not boot_service_available():
        print("systemd user session not available on this host.", file=sys.stderr)
        raise SystemExit(1)
    r = subprocess.run(
        ["systemctl", "--user", "disable", SYSTEMD_UNIT_NAME, "--now"],
        capture_output=True,
        text=True,
        shell=False,
    )
    if r.returncode != 0 and r.stderr:
        print(r.stderr.strip(), file=sys.stderr)
    print(f"Disabled user service {SYSTEMD_UNIT_NAME} (if it was installed).")


def status_boot_ingest() -> None:
    if not boot_service_available():
        print("Boot ingest service: N/A (Windows or no systemd).")
        return
    p = systemd_unit_path()
    print(f"Unit file: {p} ({'exists' if p.is_file() else 'missing'})")
    r = subprocess.run(
        ["systemctl", "--user", "is-enabled", SYSTEMD_UNIT_NAME],
        capture_output=True,
        text=True,
        shell=False,
    )
    print(f"enabled: {(r.stdout or '').strip() or r.stderr.strip()}")


def default_db_path() -> Path:
    d = latest_run_date()
    if not d:
        raise RuntimeError("No runs folder.")
    return RUNS_DIR / d / "_exports" / "local-cdr.sqlite"


def _env_wants_db_quick_check() -> bool:
    for key in (ENV_DB_QUICK_CHECK, ENV_DB_QUICK_CHECK_ALT):
        v = os.environ.get(key, "").strip().lower()
        if v in ("1", "true", "yes", "y"):
            return True
    return False


def collect_db_stats(db_path: Path) -> Dict[str, Any]:
    if not db_path.is_file():
        raise RuntimeError(f"Database not found: {db_path}")

    wal = db_path.with_name(db_path.name + "-wal")
    shm = db_path.with_name(db_path.name + "-shm")
    total_bytes = db_path.stat().st_size
    if wal.is_file():
        total_bytes += wal.stat().st_size
    if shm.is_file():
        total_bytes += shm.stat().st_size

    now = datetime.now(timezone.utc)
    with contextlib.closing(sqlite3.connect(str(db_path))) as con:
        con.row_factory = sqlite3.Row
        cur = con.execute("SELECT MAX(run_date) AS d FROM runs")
        row = cur.fetchone()
        run_date = row["d"] if row else None
        if not run_date:
            run_date = con.execute("SELECT MAX(run_date) FROM bank_products").fetchone()[0]
        if not run_date:
            raise RuntimeError("No data in database.")

        def cnt(sql: str, params: Tuple[Any, ...] = (run_date,)) -> int:
            r2 = con.execute(sql, params).fetchone()
            return int(r2[0] or 0)

        banks = cnt(
            "SELECT COUNT(DISTINCT provider) FROM bank_products WHERE run_date = ?",
            (run_date,),
        )
        energy_providers = cnt(
            "SELECT COUNT(DISTINCT provider) FROM energy_plans WHERE run_date = ?",
            (run_date,),
        )
        energy_products = cnt("SELECT COUNT(*) FROM energy_plans WHERE run_date = ?", (run_date,))
        bank_products_n = cnt("SELECT COUNT(*) FROM bank_products WHERE run_date = ?", (run_date,))
        mort_p = cnt(
            "SELECT COUNT(*) FROM bank_products WHERE run_date = ? AND dataset = 'Mortgage'",
            (run_date,),
        )
        sav_p = cnt(
            "SELECT COUNT(*) FROM bank_products WHERE run_date = ? AND dataset = 'Savings'",
            (run_date,),
        )
        td_p = cnt(
            "SELECT COUNT(*) FROM bank_products WHERE run_date = ? AND dataset = 'TD'",
            (run_date,),
        )
        mort_r = cnt(
            "SELECT COUNT(*) FROM bank_rates WHERE run_date = ? AND dataset = 'Mortgage'",
            (run_date,),
        )
        sav_r = cnt(
            "SELECT COUNT(*) FROM bank_rates WHERE run_date = ? AND dataset = 'Savings'",
            (run_date,),
        )
        td_r = cnt(
            "SELECT COUNT(*) FROM bank_rates WHERE run_date = ? AND dataset = 'TD'",
            (run_date,),
        )

        tables = (
            "bank_products",
            "bank_rates",
            "bank_items",
            "energy_plans",
            "energy_items",
        )
        total_rows = 0
        for t in tables:
            total_rows += cnt(f"SELECT COUNT(*) FROM {t} WHERE run_date = ?", (run_date,))

        gen_row = con.execute(
            "SELECT generated_at FROM runs WHERE run_date = ?",
            (run_date,),
        ).fetchone()
        generated_at = str(gen_row[0]) if gen_row else ""

        page_count = int(con.execute("PRAGMA page_count").fetchone()[0])
        page_size = int(con.execute("PRAGMA page_size").fetchone()[0])
        freelist = int(con.execute("PRAGMA freelist_count").fetchone()[0])
        journal_mode = str(con.execute("PRAGMA journal_mode").fetchone()[0])
        if _env_wants_db_quick_check():
            qck = con.execute("PRAGMA quick_check").fetchone()
            integrity = str(qck[0]) if qck else "unknown"
        else:
            integrity = "skipped (set AR_LOCAL_DB_QUICK_CHECK=1 or DB_QUICK_CHECK=1 to run)"

    wal_size = wal.stat().st_size if wal.is_file() else 0
    db_mtime = datetime.fromtimestamp(db_path.stat().st_mtime, tz=timezone.utc)

    prev_snap: Optional[Dict[str, Any]] = None
    if DB_STATS_SNAPSHOT.is_file():
        try:
            prev_snap = json.loads(DB_STATS_SNAPSHOT.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prev_snap = None

    snap = {
        "captured_at_utc": now.isoformat(),
        "run_date": run_date,
        "db_path": str(db_path),
        "total_bytes_on_disk": total_bytes,
        "page_count": page_count,
        "freelist_count": freelist,
        "wal_bytes": wal_size,
    }
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    DB_STATS_SNAPSHOT.write_text(json.dumps(snap, indent=2), encoding="utf-8")

    delta_note = "N/A (first snapshot)"
    if prev_snap:
        try:
            prev_t = datetime.fromisoformat(prev_snap["captured_at_utc"].replace("Z", "+00:00"))
            age = (now - prev_t).total_seconds()
            if age > 0 and age <= 86400:
                delta_bytes = total_bytes - int(prev_snap.get("total_bytes_on_disk", 0))
                delta_pages = page_count - int(prev_snap.get("page_count", 0))
                delta_note = (
                    f"Since last menu view ({age / 3600:.1f}h): "
                    f"delta bytes on disk {delta_bytes:+d}, delta pages {delta_pages:+d} (approx, not OS I/O)"
                )
            else:
                delta_note = "Previous snapshot older than 24h; showing deltas would be misleading."
        except (KeyError, ValueError, TypeError):
            delta_note = "Could not compare to previous snapshot."

    labels = [
        ("Metric", "Value"),
        ("Host", platform_label()),
        ("DB path", str(db_path)),
        ("Latest run_date in DB", run_date),
        ("runs.generated_at", generated_at),
        ("Distinct banks (providers)", str(banks)),
        ("Energy providers", str(energy_providers)),
        ("Energy products (plans)", str(energy_products)),
        ("Bank products (all)", str(bank_products_n)),
        ("Mortgage products (bank_products)", str(mort_p)),
        ("Savings products (bank_products)", str(sav_p)),
        ("TD products (bank_products)", str(td_p)),
        ("Mortgage rate rows (bank_rates)", str(mort_r)),
        ("Savings rate rows (bank_rates)", str(sav_r)),
        ("TD rate rows (bank_rates)", str(td_r)),
        ("Total rows (latest run, all tables)", str(total_rows)),
        ("DB file bytes (main+wal+shm)", str(total_bytes)),
        ("WAL bytes", str(wal_size)),
        ("DB main file mtime (UTC)", db_mtime.isoformat()),
        ("PRAGMA page_size", str(page_size)),
        ("PRAGMA page_count", str(page_count)),
        ("PRAGMA freelist_count", str(freelist)),
        ("PRAGMA journal_mode", journal_mode),
        ("PRAGMA quick_check", str(integrity)),
        ("Reads/writes last 24h (SQLite)", "Not tracked by SQLite (no portable counter); use WAL/size/mtime and snapshot deltas."),
        ("Approx. change since last menu open", delta_note),
    ]
    return {"table": labels}


def print_db_summary() -> None:
    env_path = os.environ.get("AR_LOCAL_DB")
    if env_path:
        db_path = Path(env_path).expanduser().resolve()
    else:
        try:
            db_path = default_db_path()
        except RuntimeError as e:
            print(e, file=sys.stderr)
            raise SystemExit(1)
    stats = collect_db_stats(db_path)
    rows = stats["table"]
    w0 = max(len(r[0]) for r in rows)
    w1 = max(len(r[1]) for r in rows)
    for a, b in rows:
        print(f"{a.ljust(w0)}  {b.ljust(w1)}")


def menu_git_update() -> None:
    behind, _up, msg = git_compare_upstream(REPO_ROOT)
    print(msg)
    if behind is None or behind == 0:
        return
    a = input("Pull latest with git pull --ff-only? [y/N]: ").strip().lower()
    if a == "y":
        git_pull_ff_only(REPO_ROOT)
        print("Update complete.")


def menu_schedule() -> None:
    kind = host_kind()
    if kind == HostKind.WINDOWS:
        install_windows_scheduled_task()
        return
    if kind in (HostKind.RASPBERRY_PI, HostKind.LINUX_OTHER):
        print("1. Install / replace crontab entry (20:00 UTC daily)")
        print("2. Remove AR-local crontab entry")
        print("3. Show AR-local crontab block")
        c = input("Choose [1-3]: ").strip()
        if c == "1":
            install_linux_cron()
        elif c == "2":
            remove_linux_cron()
        elif c == "3":
            show_linux_cron()
        else:
            print("Cancelled.")
        return
    print("Scheduling not automated for this platform.")


def interactive_menu() -> None:
    while True:
        latest = latest_run_date() or "none"
        print("")
        print("Australian Rates local CDR")
        print(f"Host: {platform_label()}")
        print(f"Latest run folder: {latest}")
        print("")
        print("1. Run/update today's CDR data")
        print("2. Force rerun today's CDR data")
        print("3. Rebuild Excel/JSON/SQLite for latest run")
        print("4. Open dashboard")
        print("5. Install or adjust daily schedule (20:00 UTC)")
        print("6. Check GitHub / git: update available and pull")
        print("7. Show database summary")
        if boot_service_available():
            print("8. Boot ingest service (systemd user): enable / disable / status")
        print("0. Exit")
        print("")
        choice = input("Choose: ").strip()
        try:
            if choice == "1":
                invoke_daily(False)
            elif choice == "2":
                invoke_daily(True)
            elif choice == "3":
                invoke_rebuild()
            elif choice == "4":
                open_dashboard()
            elif choice == "5":
                menu_schedule()
            elif choice == "6":
                menu_git_update()
            elif choice == "7":
                print_db_summary()
            elif choice == "8" and boot_service_available():
                print("a. Enable boot ingest   b. Disable   s. Status")
                sub = input("Choose: ").strip().lower()
                if sub == "a":
                    enable_boot_ingest()
                elif sub == "b":
                    disable_boot_ingest()
                elif sub == "s":
                    status_boot_ingest()
            elif choice == "0":
                return
            else:
                print("Invalid choice.")
        except SystemExit:
            raise
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
        input("Press Enter to continue...")


def boot_ingest_main() -> None:
    invoke_daily(False)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AR-local Start Here launcher.")
    p.add_argument(
        "--action",
        choices=("menu", "daily", "force", "rebuild", "dashboard", "schedule", "git-status", "db-summary"),
        default="menu",
    )
    p.add_argument("--boot-ingest", action="store_true", help="Run daily ingest once (for systemd oneshot).")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.boot_ingest:
        boot_ingest_main()
        return 0
    act = args.action
    if act == "menu":
        interactive_menu()
        return 0
    if act == "daily":
        invoke_daily(False)
    elif act == "force":
        invoke_daily(True)
    elif act == "rebuild":
        invoke_rebuild()
    elif act == "dashboard":
        open_dashboard()
    elif act == "schedule":
        menu_schedule()
    elif act == "git-status":
        behind, _up, msg = git_compare_upstream(REPO_ROOT)
        print(msg)
        if behind:
            print(f"(commits behind: {behind})")
    elif act == "db-summary":
        print_db_summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
