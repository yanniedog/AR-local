"""Pi-side native service evidence; no local resolution of remote paths."""
from __future__ import annotations

import json
import shlex
import sys

from pi_observer_unit_contract import (
    COMMAND_TYPE, canonical_remote_repo, command_matches, native_property,
    unprivileged_user, watchdog_snapshot_ok,
)

INGEST_UNITS = {"DAILY": "ar-local-daily.service", "MANUAL": "ar-local-ingest-now.service"}
QUEUE = "/usr/local/lib/shared-pi-queue/pi_shared_queue.py"
QUEUE_STOP = ["/usr/bin/python3", "/usr/local/lib/shared-pi-queue/pi_shared_queue_stop_hook.py"]
BASE_STOP = ["/usr/bin/systemctl", "start", "ar-local-dashboard.service"]
EMPTY_HOOKS = ("CONDITION_JSON", "START_PRE_JSON", "STOP_JSON")


def _post_start_shell(repo, *, working_directory=False):
    verifier = '"$PWD/verify_local.py"' if working_directory else shlex.quote(repo + '/verify_local.py')
    return ('for i in $(seq 1 40); do curl -fsS -o /dev/null --max-time 5 '
            'http://127.0.0.1:8808/api/latest && break; sleep 3; done; '
            f'/usr/bin/python3 {verifier} --base-url=http://127.0.0.1:8808/ '
            '--require-banks-rates --expect-run-date "$(date +%F)" '
            '--history-mode=compact --history-timeout-seconds=90')


def _ingest_definition_script(prefix, unit):
    if INGEST_UNITS.get(prefix) != unit:
        raise ValueError("unknown ingest definition")
    encoded = "".join(char if char.isalnum() else f"_{ord(char):02x}" for char in unit)
    jobs = []
    for field, prop in (("TYPE", "Type"), ("RESTART", "Restart"),
                        ("SEND_SIGKILL", "SendSIGKILL"), ("STOP_TIMEOUT", "TimeoutStopUSec")):
        jobs.append((prefix + '_' + field, ['systemctl', 'show', unit, '-p', prop, '--value']))
    for field, prop in (("EXEC_JSON", "ExecStartEx"), ("STOP_POST_JSON", "ExecStopPostEx"),
                        ("USER_JSON", "User"), ("AMBIENT_CAPS_JSON", "AmbientCapabilities"),
                        ("CONDITION_JSON", "ExecConditionEx"), ("START_PRE_JSON", "ExecStartPreEx"),
                        ("START_POST_JSON", "ExecStartPostEx"), ("STOP_JSON", "ExecStopEx")):
        jobs.append((prefix + '_' + field, ['busctl', '--system', '--json=short', '--timeout=3',
                     'get-property', 'org.freedesktop.systemd1',
                     '/org/freedesktop/systemd1/unit/' + encoded, 'org.freedesktop.systemd1.Service', prop]))
    # Four bounded read-only subprocesses at once: <=12 seconds per unit even
    # when every DBus read stalls. Preserve native Ex flags, never parse the
    # lossy human-readable systemctl ExecStart representation.
    code = '''import concurrent.futures,json,subprocess
jobs=json.loads(%r)
def read(job):
    key,argv=job
    try:
        p=subprocess.run(argv,capture_output=True,text=True,timeout=4,shell=False)
        value=p.stdout.replace('\\n',' ').strip() if p.returncode==0 else ''
    except (OSError,subprocess.SubprocessError):
        value=''
    return key+'='+value
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    for line in pool.map(read,jobs): print(line)
''' % json.dumps(jobs)
    return '/usr/bin/python3 -I -c ' + shlex.quote(code) + '; '


def _producer_argv(repo, prefix):
    argv = ["/usr/bin/python3", repo + "/pi_daily_sync.py", "--banks-only"]
    if prefix == "MANUAL":
        argv.append("--force")
    return [*argv, "--skip-git-sync"]


def _queued_argv(producer):
    return ["/usr/bin/python3", QUEUE, "run", "--project", "ar-local", "--resource", "ar-local",
            "--mode", "exclusive", "--cpu-slots", "3", "--wait-timeout", "21600",
            "--max-runtime", "21600", "--", *producer]


def _dry_ingest_definition(prefix, repo):
    return {
        **{prefix + "_" + field: json.dumps({"type": COMMAND_TYPE, "data": []}) for field in EMPTY_HOOKS},
        prefix + "_AMBIENT_CAPS_JSON": json.dumps({"type": "t", "data": 0}),
        prefix + "_START_POST_JSON": json.dumps({"type": COMMAND_TYPE, "data": [
            ["/usr/bin/systemctl", ["/usr/bin/systemctl", "try-restart", "ar-local-dashboard.service"],
             ["privileged"], 0, 0, 0, 0, 0, 0, 0],
            ["/bin/sh", ["/bin/sh", "-c", _post_start_shell(repo)], [], 0, 0, 0, 0, 0, 0, 0]]}),
        prefix + "_TYPE": "oneshot", prefix + "_RESTART": "no", prefix + "_SEND_SIGKILL": "yes",
        prefix + "_STOP_TIMEOUT": "45s", prefix + "_USER_JSON": json.dumps({"type": "s", "data": "ar-local"}),
        prefix + "_EXEC_JSON": json.dumps({"type": COMMAND_TYPE, "data": [[
            "/usr/bin/python3", _producer_argv(repo, prefix), [], 0, 0, 0, 0, 0, 0, 0]]}),
        prefix + "_STOP_POST_JSON": json.dumps({"type": COMMAND_TYPE, "data": [[
            BASE_STOP[0], BASE_STOP, ["privileged"], 0, 0, 0, 0, 0, 0, 0]]}),
    }


def _base_stop_matches(commands, expected=BASE_STOP):
    # Only the checked-in +systemctl dashboard cleanup has this modifier.
    # Do not weaken the shared unprivileged start/queue/observer matcher.
    if not isinstance(commands, list) or len(commands) != 1:
        return False
    row = commands[0]
    if not isinstance(row, list) or len(row) != 10 or row[2] != ["privileged"]:
        return False
    return command_matches([[row[0], row[1], [], *row[3:]]], expected)


def _additional_hooks_ok(snap, prefix, repo):
    capabilities = native_property(snap.get(prefix + "_AMBIENT_CAPS_JSON"), "t")
    if type(capabilities) is not int or capabilities != 0:
        return False
    if any(native_property(snap.get(prefix + "_" + field), COMMAND_TYPE) != [] for field in EMPTY_HOOKS):
        return False
    post = native_property(snap.get(prefix + "_START_POST_JSON"), COMMAND_TYPE)
    return (isinstance(post, list) and len(post) == 2
            and _base_stop_matches(post[:1], ["/usr/bin/systemctl", "try-restart", "ar-local-dashboard.service"])
            and any(command_matches(post[1:], ["/bin/sh", "-c", _post_start_shell(repo, working_directory=wd)])
                    for wd in (False, True)))


def ingest_definition_ok(snap, prefix):
    """Attest producer role and fences; zero timestamps do not prove a run.

    The commissioned queue needs 6h wait + 6h execution + 1h for inherited
    hooks. Its exact stop hook retains the claim through bounded cleanup.
    A direct producer never borrows the queued profile's larger deadline.
    """
    try:
        if prefix not in INGEST_UNITS:
            return False
        repo = canonical_remote_repo(snap.get("AR_REPO_PHYSICAL"))
        user, uid = snap.get("DAILY_USER"), snap.get("DAILY_USER_UID")
        if (not unprivileged_user(user, uid)
                or native_property(snap.get(prefix + "_USER_JSON"), "s") != user
                or any(snap.get(prefix + "_" + field) != value for field, value in (
                    ("TYPE", "oneshot"), ("RESTART", "no"),
                    ("KILL_MODE", "control-group"), ("SEND_SIGKILL", "yes")))):
            return False
        commands = native_property(snap.get(prefix + "_EXEC_JSON"), COMMAND_TYPE)
        if not _additional_hooks_ok(snap, prefix, repo):
            return False
        producer = _producer_argv(repo, prefix)
        if command_matches(commands, producer):
            start, stop = "6h 15min", "45s"
            if not _base_stop_matches(native_property(snap.get(prefix + "_STOP_POST_JSON"), COMMAND_TYPE)):
                return False
        elif command_matches(commands, _queued_argv(producer)):
            start, stop = "13h", "15min"
            if not command_matches(native_property(snap.get(prefix + "_STOP_POST_JSON"), COMMAND_TYPE), QUEUE_STOP):
                return False
        else:
            return False
        return snap.get(prefix + "_START_TIMEOUT") == start and snap.get(prefix + "_STOP_TIMEOUT") == stop
    except (ValueError, TypeError):
        return False


def _snapshot_script(ar, site, data, remote):
    q_remote = shlex.quote(remote)
    q_ar = shlex.quote(ar)
    q_site = shlex.quote(site)
    q_data = shlex.quote(data)
    q_remote_main = shlex.quote(f"{remote}/main")
    return (
        "set +e; "
        + _ingest_definition_script("DAILY", INGEST_UNITS["DAILY"])
        + _ingest_definition_script("MANUAL", INGEST_UNITS["MANUAL"])
        + f"ar_physical=$(CDPATH= cd {q_ar} 2>/dev/null && pwd -P); "
        f"timeout 12s git -C {q_ar} fetch {q_remote} 2>/dev/null; "
        f"ar_h=$(git -C {q_ar} rev-parse HEAD 2>/dev/null); "
        f"ar_o=$(git -C {q_ar} rev-parse {q_remote_main} 2>/dev/null); "
        f"ar_d=$(git -C {q_ar} status --porcelain | tr '\\n' ';'); "
        f"timeout 12s git -C {q_site} fetch {q_remote} 2>/dev/null; "
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
        f"watchdog_exec=$(busctl --system --json=short --timeout=3 get-property "
        f"org.freedesktop.systemd1 /org/freedesktop/systemd1/unit/ar_2dlocal_2ddaily_2dwatchdog_2eservice "
        f"org.freedesktop.systemd1.Service ExecStartEx 2>/dev/null | tr '\\n' ' '); "
        f"watchdog_start_timeout=$(systemctl show ar-local-daily-watchdog.service -p TimeoutStartUSec --value 2>/dev/null); "
        f"watchdog_user=$(busctl --system --json=short --timeout=3 get-property "
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
            **_dry_ingest_definition("DAILY", ar.rstrip("/")),
            **_dry_ingest_definition("MANUAL", ar.rstrip("/")),
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
        "WATCHDOG_KILL_MODE": "control-group",
        "WATCHDOG_START_TIMEOUT": "1min",
    }
    ok = True
    for field, value in expected.items():
        actual = snap.get(field, "")
        print(f"pi_deploy_verify: {field}: {actual}")
        if actual != value:
            ok = False
    for prefix in INGEST_UNITS:
        if not ingest_definition_ok(snap, prefix):
            print(f"pi_deploy_verify: {prefix}: command, user or bounded lifecycle differs", file=sys.stderr)
            ok = False
    if not watchdog_snapshot_ok(snap):
        print("pi_deploy_verify: watchdog command, user or idle runtime evidence differs", file=sys.stderr)
        ok = False
    if not ok:
        print("pi_deploy_verify: ingest process fencing is not active", file=sys.stderr)
    return ok
