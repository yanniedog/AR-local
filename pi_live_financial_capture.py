"""Isolated live financial capture, under the shared queue and resource supervisor."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import signal
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pi_cdr_quality_activate import (clean_commit, control_state, current_state, git, layout,
    main_commit, operation_guard, protected_files, read, record, run, source_files, write)
from pi_cdr_quality_window import add_arguments, deadline, reference, load
from pi_cdr_quality_read_io import require_dropbehind_reads

PRODUCTION = Path("/srv/ar-local/AR-local")
DATA = Path("/srv/ar-local/data")
CANARIES = Path("/srv/ar-local/canary")


def ram_root(args):
    return Path("/dev/shm") / ("ar-local-canary-" + args.operation.name)


def arguments(args, command):
    result = [str(args.python), "-B", str(args.source / Path(__file__).name), command,
              "--source", str(args.source), "--operation", str(args.operation),
              "--expected-commit", args.expected_commit, "--python", str(args.python),
              "--runtime-seconds", str(args.runtime_seconds)]
    if reference(args):
        result += ["--window-authorization", str(args.window_authorization),
                   "--window-authorization-sha256", args.window_authorization_sha256]
    return result


def launch_properties(args, unit, parent_unit, runtime):
    op = args.operation
    return [f"User={getpass.getuser()}", f"WorkingDirectory={args.source}",
            "ProtectSystem=strict", "ProtectHome=true", "PrivateTmp=true", "NoNewPrivileges=true",
            "ProtectControlGroups=true", "RestrictNamespaces=true", "CapabilityBoundingSet=",
            f"ReadOnlyPaths={args.source}", f"ReadOnlyPaths={PRODUCTION}", f"ReadOnlyPaths={DATA}",
            f"ReadWritePaths={op}", f"ReadWritePaths={ram_root(args)}", "InaccessiblePaths=-/etc/ar-local",
            "InaccessiblePaths=-/var/lib/ar-local-drive-backup", "InaccessiblePaths=-/var/lib/ar-local-day-archives",
            "CPUQuota=200%", "IOWeight=10", "TasksMax=256", "MemoryHigh=2500M", "MemoryMax=3G",
            "MemorySwapMax=0", "LimitAS=3G", "OOMPolicy=stop", "KillMode=control-group",
            "TimeoutStopSec=30s", f"RuntimeMaxSec={runtime + 30}s",
            f"BindsTo={parent_unit}", f"After={parent_unit}"]


def environment(args):
    op = args.operation
    return ["/usr/bin/env", "-i", "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8",
            "PYTHONDONTWRITEBYTECODE=1", f"HOME={op / 'home'}", "TMPDIR=/var/tmp",
            f"XDG_CONFIG_HOME={op / 'home/.config'}", "GIT_CONFIG_GLOBAL=/dev/null", "GIT_CONFIG_NOSYSTEM=1",
            f"AR_LOCAL_DATA_ROOT={op / 'data'}", f"AR_LOCAL_PORTABLE_ROOT={op / 'portable'}",
            f"AR_LOCAL_DAY_ARCHIVE_ENV={op / 'config/day-archive.env'}",
            f"AR_LOCAL_DAY_ARCHIVE_SPOOL={op / 'data/archive-spool'}",
            f"RCLONE_CONFIG={op / 'config/rclone.conf'}"]


def remaining_budget(requested, closing, now):
    runtime = min(requested, int((closing - now).total_seconds()) - 180)
    if runtime < 300:
        raise ValueError("insufficient time before operator/quiet cutoff including cleanup reserve")
    return runtime


def preflight(args):
    layout(args.source, PRODUCTION, DATA, args.operation)
    if (args.operation.parent != CANARIES or args.operation.exists()
            or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", args.operation.name)
            or ram_root(args).exists() or ram_root(args).is_symlink()):
        raise ValueError("a new canonical generation directory immediately beneath the canary root is required")
    if args.source != Path(__file__).resolve().parent:
        raise ValueError("execute the launcher from the exact candidate source being qualified")
    if not 300 <= args.runtime_seconds <= 5400:
        raise ValueError("live qualification requires a bounded 300..5400 second budget")
    if clean_commit(args.source) != args.expected_commit or main_commit(args.source) != args.expected_commit:
        raise ValueError("live qualification requires exact clean current main")
    from cdr_ingest_support import FINANCIAL_PRD_INDUSTRIES
    if not {"banking", "non-bank-lending"} <= FINANCIAL_PRD_INDUSTRIES:
        raise ValueError("source does not cover the financial register")
    extension = operation_guard(DATA, PRODUCTION, reference(args), args.expected_commit,
                                args.operation, "live-financial-capture")
    from pi_cdr_recovery import recovery_block_reason
    if recovery_block_reason(PRODUCTION):
        raise ValueError("production operation or source backup is active")
    now = datetime.now(timezone.utc)
    runtime = remaining_budget(args.runtime_seconds, deadline(now, extension), now)
    current_state(DATA)
    return runtime


def stop_owned(unit):
    result = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=10)
    if result.stdout.strip() in {"inactive", "failed", "unknown"}:
        return
    run(["sudo", "-n", "systemctl", "stop", unit], timeout=45)
    result = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=10)
    if result.stdout.strip() not in {"inactive", "failed", "unknown"}:
        raise RuntimeError("owned live-capture unit remains active")


def preserve_failed_stage(source, destination, closing):
    """Bounded copy after unit cleanup; leave RAM evidence in place on any failure."""
    files = size = 0
    if not source.exists():
        return {"result": "NO_STAGE", "source": str(source)}
    destination.mkdir(mode=0o700)
    for root, directories, names in os.walk(source, followlinks=False):
        parent = Path(root)
        if parent.is_symlink() or any((parent / name).is_symlink() for name in directories):
            raise ValueError("linked failed-stage directory")
        target = destination / parent.relative_to(source)
        target.mkdir(mode=0o700, parents=True, exist_ok=True)
        for name in names:
            path = parent / name
            if path.is_symlink() or not path.is_file():
                raise ValueError("non-regular failed-stage evidence")
            with path.open("rb") as incoming, (target / name).open("xb") as outgoing:
                while True:
                    if (closing - datetime.now(timezone.utc)).total_seconds() < 30:
                        raise TimeoutError("failure preservation cutoff; original RAM stage retained")
                    block = incoming.read(1024**2)
                    if not block:
                        break
                    outgoing.write(block)
                    size += len(block)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            files += 1
    return {"result": "COPIED", "files": files, "bytes": size, "source": str(source), "source_deleted": False}


@require_dropbehind_reads()
def capture(args):
    from pi_deploy_queue_claim import inherited_queue_admission, _read_self_cgroup, SHARED_QUEUE_UNIT_RE
    runtime = preflight(args)
    decision = inherited_queue_admission()
    if args.command == "plan":
        return {"result": "READY", "mutated": False, "runtime_seconds": runtime,
                "target_commit": args.expected_commit, "scope": "isolated live capture; no publication or Drive"}
    if args.command == "run":
        if decision != "admit":
            raise ValueError("submit run outside an existing queue claim")
        command = ["/usr/local/bin/pi-shared-task", "--project", "ar-local", "--resource", "ar-local",
                   "--cpu-slots", "3", "--max-runtime", str(runtime + 60), "--wait-timeout", "60", "--",
                   *arguments(args, "queued")]
        run(command, timeout=runtime + 240)
        return read(args.operation / "result.json")
    if decision != "reuse":
        raise ValueError("live capture requires an inherited exclusive AR-local queue claim")
    parent_unit = SHARED_QUEUE_UNIT_RE.search(_read_self_cgroup()).group(1) + ".service"
    args.operation.mkdir(mode=0o700)
    ram_root(args).mkdir(mode=0o700)
    for name in ("home", "config", "data", "data/runs", "data/state", "data/archive-spool"):
        (args.operation / name).mkdir(mode=0o700, parents=True, exist_ok=True)
    config = args.operation / "config"
    (config / "rclone.conf").write_text("[canary_local]\ntype = local\n", encoding="utf-8")
    (config / "rclone.conf").chmod(0o600)
    (config / "day-archive.env").write_text(
        f"AR_LOCAL_DAY_ARCHIVE_SPOOL={args.operation}/data/archive-spool\n"
        f"AR_LOCAL_DAY_ARCHIVE_REMOTE=canary_local:{args.operation}/data/day-archive-remote\n"
        f"RCLONE_CONFIG={config}/rclone.conf\n", encoding="utf-8")
    before = {"production_commit": clean_commit(PRODUCTION), "protected_files": protected_files(DATA),
              "publication_controls": control_state(DATA), "source_files": source_files(args.source)}
    # Source/protected-evidence hashing can be substantial. Revalidate the same
    # absolute authorization immediately before constructing the bounded unit.
    now = datetime.now(timezone.utc)
    extension = load(reference(args), now=now, target=args.expected_commit,
                     operation=args.operation, stage="live-financial-capture")
    closing = deadline(now, extension)
    runtime = remaining_budget(runtime, closing, now)
    unit = f"ar-local-live-capture-{uuid.uuid4().hex[:12]}.service"
    intent = {"schema": "ar-local-live-financial-capture-v1", "target_commit": args.expected_commit,
              "operation": str(args.operation), "source": str(args.source), "unit": unit,
              "parent_queue_unit": parent_unit, "before": before,
              "window_authorization": reference(args), "runtime_seconds": runtime,
              "ram_root": str(ram_root(args)), "absolute_cutoff": closing.isoformat(),
              "resource_policy": "quality-canary-v2: host/workload swap recorded; RSS/reserve/pressure/deadline stops unchanged",
              "started_at": datetime.now(timezone.utc).isoformat()}
    write(args.operation / "intent.json", intent)
    properties = launch_properties(args, unit, parent_unit, runtime)
    command = ["sudo", "-n", "systemd-run", "--wait", "--pipe", "--collect", f"--unit={unit}",
               *[f"--property={p}" for p in properties], *environment(args),
               str(args.python), "-B", str(args.source / "pi_cdr_quality_resources.py"),
               "--output", str(args.operation / "resources.json"), "--runtime-seconds", str(runtime), "--",
               *arguments(args, "worker")]
    result = {**intent, "result": "FAIL"}
    old = {}
    def interrupted(_signum, _frame):
        raise RuntimeError("live qualification interrupted")
    try:
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            old[sig] = signal.signal(sig, interrupted)
        run(command, timeout=runtime + 60, output=args.operation / "capture-service.txt")
        from pi_cdr_quality_resources import require_receipt
        resources = read(args.operation / "resources.json")
        require_receipt(resources, record_host_swap_out=True)
        if resources.get("command") != arguments(args, "worker") or not str(resources.get("cgroup", "")).endswith("/" + unit):
            raise ValueError("resource receipt does not bind the owned worker/unit")
        worker = read(args.operation / "worker.json")
        if worker.get("target_commit") != args.expected_commit or worker.get("result") != "PASS":
            raise ValueError("complete live worker proof missing")
        after = {"production_commit": clean_commit(PRODUCTION), "protected_files": protected_files(DATA),
                 "publication_controls": control_state(DATA), "source_files": source_files(args.source)}
        if before != after:
            raise ValueError("production controls/data or candidate source changed")
        result.update(result="PASS", worker=record(args.operation / "worker.json"),
                      resources=record(args.operation / "resources.json"), coverage=worker["coverage"])
    except BaseException as error:
        result["error_class"] = type(error).__name__
        raise
    finally:
        for sig in old:
            signal.signal(sig, signal.SIG_IGN)
        try:
            stop_owned(unit)
            if result["result"] != "PASS":
                now = datetime.now(timezone.utc)
                extension = load(reference(args), now=now, target=args.expected_commit,
                                 operation=args.operation, stage="live-financial-capture")
                result["failed_stage"] = preserve_failed_stage(ram_root(args), args.operation / "failed-ram", deadline(now, extension))
        except Exception as error:
            result.update(result="FAIL", cleanup_error=type(error).__name__)
        result["completed_at"] = datetime.now(timezone.utc).isoformat()
        write(args.operation / "result.json", result)
        for sig, handler in old.items():
            signal.signal(sig, handler)
    if result["result"] != "PASS":
        raise RuntimeError("live qualification failed or cleanup unverified")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "run", "queued", "worker"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--operation", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--runtime-seconds", type=int, default=5400)
    add_arguments(parser)
    args = parser.parse_args(argv)
    if args.command == "worker":
        from pi_live_financial_worker import worker
        result = worker(args)
    else:
        result = capture(args)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
