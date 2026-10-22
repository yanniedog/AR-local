"""Pi-side native service evidence; no local resolution of remote paths."""
from __future__ import annotations

import json
import shlex
import sys

from pi_observer_unit_contract import COMMAND_TYPE, watchdog_snapshot_ok


def _snapshot_script(ar, site, data, remote):
    q_remote = shlex.quote(remote)
    q_ar = shlex.quote(ar)
    q_site = shlex.quote(site)
    q_data = shlex.quote(data)
    q_remote_main = shlex.quote(f"{remote}/main")
    return (
        f"set +e; "
        f"ar_physical=$(CDPATH= cd {q_ar} 2>/dev/null && pwd -P); "
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
        f"watchdog_exec=$(busctl --system --json=short --timeout=10 get-property "
        f"org.freedesktop.systemd1 /org/freedesktop/systemd1/unit/ar_2dlocal_2ddaily_2dwatchdog_2eservice "
        f"org.freedesktop.systemd1.Service ExecStartEx 2>/dev/null | tr '\\n' ' '); "
        f"watchdog_start_timeout=$(systemctl show ar-local-daily-watchdog.service -p TimeoutStartUSec --value 2>/dev/null); "
        f"watchdog_user=$(busctl --system --json=short --timeout=10 get-property "
        f"org.freedesktop.systemd1 /org/freedesktop/systemd1/unit/ar_2dlocal_2ddaily_2dwatchdog_2eservice "
        f"org.freedesktop.systemd1.Service User 2>/dev/null | tr '\\n' ' '); "
        f"daily_user=$(systemctl show ar-local-daily.service -p User --value 2>/dev/null); "
        f"daily_user_uid=$(id -u -- \"$daily_user\" 2>/dev/null); "
        f"watchdog_active=$(systemctl show ar-local-daily-watchdog.service -p ActiveState --value 2>/dev/null); "
        f"watchdog_sub=$(systemctl show ar-local-daily-watchdog.service -p SubState --value 2>/dev/null); "
        f"watchdog_main=$(systemctl show ar-local-daily-watchdog.service -p MainPID --value 2>/dev/null); "
        f"watchdog_control=$(systemctl show ar-local-daily-watchdog.service -p ControlPID --value 2>/dev/null); "
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
        f"printf 'WATCHDOG_EXEC_JSON=%s\\n' \"$watchdog_exec\"; "
        f"printf 'AR_REPO_PHYSICAL=%s\\nDAILY_USER=%s\\nDAILY_USER_UID=%s\\nWATCHDOG_USER_JSON=%s\\n' \"$ar_physical\" \"$daily_user\" \"$daily_user_uid\" \"$watchdog_user\"; "
        f"printf 'WATCHDOG_ACTIVE_STATE=%s\\nWATCHDOG_SUB_STATE=%s\\nWATCHDOG_MAIN_PID=%s\\nWATCHDOG_CONTROL_PID=%s\\n' \"$watchdog_active\" \"$watchdog_sub\" \"$watchdog_main\" \"$watchdog_control\"; "
        f"printf 'CAPACITY_TIMER_ENABLED=%s\\nCAPACITY_TIMER_ACTIVE=%s\\n' \"$capacity_timer_enabled\" \"$capacity_timer_active\"; "
        f"printf 'DASHBOARD_ENV=%s\\nDAILY_ENV=%s\\nDF_AR=%s\\nDF_SITE=%s\\nDF_DATA=%s\\n' \"$dash_env\" \"$daily_env\" \"$df_ar\" \"$df_site\" \"$df_data\""
    )


def _dry_snapshot(ar):
    return {
            "AR_HEAD": "dry",
            "AR_REPO_PHYSICAL": ar.rstrip("/"),
            "DAILY_USER": "ar-local", "DAILY_USER_UID": "1000",
            "WATCHDOG_USER_JSON": json.dumps({"type": "s", "data": "ar-local"}),
            "WATCHDOG_ACTIVE_STATE": "inactive", "WATCHDOG_SUB_STATE": "dead",
            "WATCHDOG_MAIN_PID": "0", "WATCHDOG_CONTROL_PID": "0",
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
            "WATCHDOG_START_TIMEOUT": "1min",
            "WATCHDOG_EXEC_JSON": json.dumps({"type": COMMAND_TYPE, "data": [
                ["/usr/bin/python3", ["/usr/bin/python3", "-B", f"{ar.rstrip('/')}/pi_ingest_observe.py"],
                 [], 0, 0, 0, 0, 0, 0, 0]]}),
            "MANUAL_KILL_MODE": "control-group",
            "MANUAL_START_TIMEOUT": "6h 15min",
            "DASHBOARD_ENV": "AR_LOCAL_DATA_ROOT=/dry/data",
            "DAILY_ENV": "AR_LOCAL_DATA_ROOT=/dry/data",
            "DF_AR": "dry",
            "DF_SITE": "dry",
            "DF_DATA": "dry",
    }


def remote_snapshot(*, ar, site, data, remote, run, parse, dry_run=False):
    """One SSH round-trip for SHAs, dirty trees, and native service evidence."""
    code, stdout, _ = run(_snapshot_script(ar, site, data, remote), dry_run=dry_run)
    if dry_run:
        return _dry_snapshot(ar)
    snap = parse(stdout)
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


def pi_ingest_service_fences_ok(snap: dict[str, str]) -> bool:
    expected = {
        "DAILY_KILL_MODE": "control-group",
        "DAILY_START_TIMEOUT": "6h 15min",
        "WATCHDOG_KILL_MODE": "control-group",
        "WATCHDOG_START_TIMEOUT": "1min",
        "MANUAL_KILL_MODE": "control-group",
        "MANUAL_START_TIMEOUT": "6h 15min",
    }
    ok = True
    for field, value in expected.items():
        actual = snap.get(field, "")
        print(f"pi_deploy_verify: {field}: {actual}")
        if actual != value:
            ok = False
    if not watchdog_snapshot_ok(snap):
        print("pi_deploy_verify: watchdog command, user or idle runtime evidence differs", file=sys.stderr)
        ok = False
    if not ok:
        print("pi_deploy_verify: ingest process fencing is not active", file=sys.stderr)
    return ok
