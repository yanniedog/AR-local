"""Whole-worker Drive resource supervision on Linux, including Go descendants.

RSS is sampled, conservatively summed across an isolated undelegated cgroup.
There is no claim of a hard aggregate memory limit when memcg is unavailable.
Go virtual address reservations are deliberately not constrained by RLIMIT_AS.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from pi_cdr_quality_resources import (aggregate, host_sample, host_violation,
    members, numeric_fields, preflight, swap_progress, terminate)

MIB = 1024**2
SCHEMA = "ar-local-drive-resources-v1"
UNIT = re.compile(r"ar-local-drive-(?:backup|commission-[a-z0-9]+|resource-test-[a-z0-9]+)\.service")


@dataclass(frozen=True)
class Limits:
    workload_bytes: int = 768 * MIB
    margin_bytes: int = 128 * MIB
    reserve_bytes: int = 2432 * MIB
    sample_seconds: float = 0.1
    max_sample_gap_seconds: float = 2.0
    runtime_seconds: float = 20 * 3600
    cold_swap_in_bytes: int = 16 * MIB

    def validate(self):
        if (not 0 < self.margin_bytes < self.workload_bytes <= 768 * MIB
                or self.reserve_bytes + self.margin_bytes < 2560 * MIB
                or not 0.01 <= self.sample_seconds <= 0.1
                or not 0.2 <= self.max_sample_gap_seconds <= 2
                or not 0 < self.runtime_seconds <= 20 * 3600
                or type(self.cold_swap_in_bytes) is not int or not 0 <= self.cold_swap_in_bytes <= 16 * MIB):
            raise ValueError("Drive resource limits weaken the reviewed bounds")


def own_cgroup(proc=Path("/proc"), root=Path("/sys/fs/cgroup")):
    names = [line[3:] for line in (proc / "self/cgroup").read_text().splitlines() if line.startswith("0::")]
    if len(names) != 1 or Path(names[0]).parent.as_posix() != "/system.slice" or not UNIT.fullmatch(Path(names[0]).name):
        raise RuntimeError("Drive operation requires its isolated systemd service")
    path = root / names[0].lstrip("/")
    if path.resolve() != path or not path.is_dir() or os.access(path / "cgroup.procs", os.W_OK):
        raise RuntimeError("Drive cgroup must be canonical and undelegated/read-only")
    if any(p.is_dir() for p in path.iterdir()):
        raise RuntimeError("Drive workload may not create nested cgroups")
    quota, period = (path / "cpu.max").read_text().split()
    if quota == "max" or not 0 < int(quota) <= int(period) or not 0 < int((path / "pids.max").read_text()) <= 64:
        raise RuntimeError("Drive CPU/process limits are missing")
    weight = path / "io.weight"
    if not weight.exists():
        weight = path / "io.bfq.weight"
    if weight.read_text().strip() != "default 10":
        raise RuntimeError("Drive I/O scheduling weight must be 10")
    return path


def process_peaks(cgroup, receipt):
    """Record executable names and address reservations, never argv or env."""
    peaks = receipt.setdefault("process_peaks", {})
    for pid in members(cgroup):
        try:
            root = Path("/proc") / str(pid)
            name = (root / "comm").read_text().strip()
            values = numeric_fields(root / "status")
            previous = peaks.setdefault(name, {"rss_bytes": 0, "virtual_bytes": 0})
            previous["rss_bytes"] = max(previous["rss_bytes"], values.get("VmRSS", 0))
            previous["virtual_bytes"] = max(previous["virtual_bytes"], values.get("VmSize", 0))
        except (FileNotFoundError, ProcessLookupError):
            pass  # Mandatory memory accounting is independently performed by aggregate().


def monitor(child, cgroup, limits, baseline, receipt, guard):
    started = previous = time.monotonic()
    previous_host = baseline.get("admission_sample", baseline)
    while True:
        guard()
        sample, host = aggregate(cgroup), host_sample()
        process_peaks(cgroup, receipt)
        current = time.monotonic()
        gap = current - previous
        progress = swap_progress(host, baseline, previous_host)
        receipt.update(samples=receipt["samples"] + 1,
            peak_rss_bytes=max(receipt["peak_rss_bytes"], sample["rss_bytes"]),
            peak_processes=max(receipt["peak_processes"], sample["processes"]),
            peak_workload_swap_bytes=max(receipt["peak_workload_swap_bytes"], sample["swap_bytes"]),
            minimum_available_bytes=min(receipt["minimum_available_bytes"], host["available_bytes"]),
            maximum_sample_gap_seconds=max(receipt["maximum_sample_gap_seconds"], gap),
            last_host_sample=host, cold_swap_in_bytes=progress["swap_in_bytes"],
            elapsed_seconds=current - started)
        reason = host_violation(host, baseline, limits, previous=previous_host)
        if sample["rss_bytes"] >= limits.workload_bytes - limits.margin_bytes:
            reason = "aggregate_rss_early_stop"
        elif sample["swap_bytes"]:
            reason = "workload_swapped"
        elif gap > limits.max_sample_gap_seconds:
            reason = "supervision_sample_gap"
        elif current - started >= limits.runtime_seconds:
            reason = "workload_timeout"
        if reason:
            raise RuntimeError(reason)
        status = child.poll()
        if status is not None:
            receipt["workload_exit_code"] = status
            if status or members(cgroup) - {os.getpid()}:
                raise RuntimeError("workload_failed_or_left_descendants")
            return
        previous, previous_host = current, host
        time.sleep(limits.sample_seconds)


def supervise(command, output: Path, limits=Limits(), *, guard=lambda: None):
    limits.validate()
    if not command or not output.is_absolute() or output.resolve() != output or output.exists():
        raise ValueError("new canonical resource receipt path and command required")
    receipt = {"schema": SCHEMA, "result": "BLOCKED", "mode": "sampled_cgroup_rss",
        "limits": asdict(limits), "samples": 0, "peak_rss_bytes": 0, "peak_processes": 0,
        "maximum_sample_gap_seconds": 0, "workload_exit_code": None, "group_clean": False,
        "peak_workload_swap_bytes": 0, "cold_swap_in_bytes": 0,
        "go_memory_limit": "192MiB soft per process", "address_space_limit": None}
    child = cgroup = None
    owned, handlers = False, {}
    try:
        cgroup = own_cgroup()
        if members(cgroup) != {os.getpid()}:
            raise RuntimeError("Drive cgroup already contains another process")
        owned = True
        guard()
        baseline = preflight(limits, admission=True)
        receipt.update(cgroup=str(cgroup), baseline=baseline,
            minimum_available_bytes=min(baseline["available_bytes"], baseline["admission_sample"]["available_bytes"]),
            page_size_bytes=baseline["page_size_bytes"], psi_available=baseline["psi_avg10"] is not None,
            kernel_memory_limit_bytes=(cgroup / "memory.max").read_text().strip() if (cgroup / "memory.max").exists() else None)
        def interrupted(_signum, _frame):
            raise RuntimeError("supervisor_interrupted")
        for signum in (signal.SIGTERM, signal.SIGINT):
            handlers[signum] = signal.signal(signum, interrupted)
        env = os.environ.copy()
        env.update(GOMEMLIMIT="192MiB", GOGC="50", GOMAXPROCS="2")
        # Intentionally no preexec_fn/RLIMIT_AS: Go reserves virtual memory.
        child = subprocess.Popen(command, shell=False, start_new_session=True, env=env)
        monitor(child, cgroup, limits, baseline, receipt, guard)
        receipt["result"] = "PASS"
    except Exception as error:
        receipt.update(result="FAIL" if child else "BLOCKED", reason=f"{type(error).__name__}: {error}")
    finally:
        for signum in handlers:
            signal.signal(signum, signal.SIG_IGN)
        if cgroup is not None and owned:
            try:
                receipt["group_clean"] = terminate(cgroup, child)
            except Exception as error:
                receipt.update(group_clean=False, cleanup_error=type(error).__name__)
        if not receipt["group_clean"]:
            receipt["result"] = "FAIL" if child else "BLOCKED"
        receipt["early_stop_overshoot_bytes"] = max(0, receipt["peak_rss_bytes"] - (limits.workload_bytes - limits.margin_bytes))
        for signum, handler in handlers.items():
            signal.signal(signum, handler)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x") as stream:
            json.dump(receipt, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    return receipt


def require_receipt(receipt):
    try:
        limits = Limits(**receipt["limits"])
        limits.validate()
        progress = swap_progress(receipt["last_host_sample"], receipt["baseline"], receipt["baseline"].get("admission_sample"))
        integers = ("page_size_bytes", "cold_swap_in_bytes", "peak_workload_swap_bytes", "peak_rss_bytes", "minimum_available_bytes", "samples")
        if (receipt.get("schema") != SCHEMA or receipt.get("result") != "PASS"
                or receipt.get("mode") != "sampled_cgroup_rss" or receipt.get("group_clean") is not True
                or type(receipt.get("workload_exit_code")) is not int or receipt["workload_exit_code"] != 0
                or any(type(receipt.get(key)) is not int or receipt[key] < 0 for key in integers)
                or receipt["samples"] < 1 or receipt["peak_rss_bytes"] >= limits.workload_bytes - limits.margin_bytes
                or receipt["minimum_available_bytes"] < limits.reserve_bytes + limits.margin_bytes
                or not 0 <= receipt["maximum_sample_gap_seconds"] <= limits.max_sample_gap_seconds
                or not 0 <= receipt["elapsed_seconds"] < limits.runtime_seconds
                or receipt["page_size_bytes"] != receipt["baseline"]["page_size_bytes"]
                or receipt["cold_swap_in_bytes"] != progress["swap_in_bytes"]
                or receipt["peak_workload_swap_bytes"] != 0
                or host_violation(receipt["last_host_sample"], receipt["baseline"], limits)):
            raise ValueError("resource bounds failed")
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("complete successful Drive resource receipt required") from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime-seconds", type=float, default=20 * 3600)
    parser.add_argument("--workload-mib", type=int, default=768)
    parser.add_argument("--margin-mib", type=int, default=128)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    from pi_drive_backup import guard_window
    result = supervise(args.command[1:] if args.command[:1] == ["--"] else args.command, args.output,
        Limits(workload_bytes=args.workload_mib * MIB, margin_bytes=args.margin_mib * MIB,
               reserve_bytes=max(2432, 2560 - args.margin_mib) * MIB, runtime_seconds=args.runtime_seconds), guard=guard_window)
    print(json.dumps({"result": result["result"], "resource_receipt": str(args.output)}))
    return 0 if result["result"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
