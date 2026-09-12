"""Bounded Linux cgroup RSS supervision when a Pi lacks memory/PSI controllers.

This is sampled containment, not a replacement claim for kernel memory.max.
Only an isolated, undelegated systemd quality unit may invoke the supervisor.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

GIB = 1024**3
SCHEMA = "ar-local-quality-resources-v2"
UNIT = re.compile(r"ar-local-quality-(?:canary|resource-test)-[a-z0-9]+\.service")


@dataclass(frozen=True)
class Limits:
    workload_bytes: int = 3 * GIB
    reserve_bytes: int = 2 * GIB
    margin_bytes: int = GIB // 2
    address_space_bytes: int = 3 * GIB
    sample_seconds: float = 0.1
    max_sample_gap_seconds: float = 2.0
    runtime_seconds: float = 5400.0
    cold_swap_in_bytes: int = 16 * 1024**2

    def validate(self) -> None:
        if (not 0 < self.margin_bytes < self.workload_bytes <= 3 * GIB
                or self.reserve_bytes < 2 * GIB or not 0 < self.address_space_bytes <= 3 * GIB
                or not 0.01 <= self.sample_seconds <= 0.1 or not 0.2 <= self.max_sample_gap_seconds <= 2
                or not 0 < self.runtime_seconds <= 5400
                or type(self.cold_swap_in_bytes) is not int or not 0 <= self.cold_swap_in_bytes <= 16 * 1024**2):
            raise ValueError("resource limits exceed the reviewed maximum or weaken the host reserve")


def numeric_fields(path: Path) -> dict[str, int]:
    result = {}
    for line in path.read_text().splitlines():
        fields = line.replace(":", "").split()
        if len(fields) >= 2 and fields[1].isdigit():
            result[fields[0]] = int(fields[1]) * (1024 if len(fields) > 2 and fields[2] == "kB" else 1)
    return result


def swap_counters(path: Path) -> dict[str, int]:
    values = {}
    for line in path.read_text().splitlines():
        row = line.split()
        if row and row[0] in {"pswpin", "pswpout"}:
            if len(row) != 2 or not row[1].isdigit() or row[0] in values:
                raise ValueError("malformed or duplicate host swap counter")
            values[row[0]] = int(row[1])
    if set(values) != {"pswpin", "pswpout"}:
        raise ValueError("host swap counters are unavailable")
    return values


def host_sample(proc: Path = Path("/proc"), *, page_size_bytes: int | None = None) -> dict:
    memory, vm = numeric_fields(proc / "meminfo"), swap_counters(proc / "vmstat")
    page_size = os.sysconf("SC_PAGE_SIZE") if page_size_bytes is None else page_size_bytes
    pressure_path = proc / "pressure/memory"
    pressure = None
    if pressure_path.exists():
        rows = pressure_path.read_text().splitlines()
        pressure = float(dict(item.split("=") for item in rows[0].split()[1:])["avg10"])
    return {"available_bytes": memory["MemAvailable"], "swap_in_pages": vm["pswpin"],
            "swap_out_pages": vm["pswpout"], "page_size_bytes": page_size, "psi_avg10": pressure}


def swap_progress(sample: dict, baseline: dict, previous: dict | None = None) -> dict:
    page_size = baseline.get("page_size_bytes")
    if type(page_size) is not int or not 1024 <= page_size <= 1024**2 or page_size & (page_size - 1):
        raise ValueError("invalid host page size")
    prior = previous if previous is not None else baseline
    for row in (baseline, prior, sample):
        if type(row.get("page_size_bytes")) is not int or row["page_size_bytes"] != page_size:
            raise ValueError("host page size changed or is unavailable")
        if any(type(row.get(key)) is not int or row[key] < 0 for key in ("swap_in_pages", "swap_out_pages")):
            raise ValueError("invalid or unavailable host swap counter")
    if any(sample[key] < prior[key] or prior[key] < baseline[key] for key in ("swap_in_pages", "swap_out_pages")):
        raise ValueError("host swap counter reset")
    return {"swap_in_bytes": (sample["swap_in_pages"] - baseline["swap_in_pages"]) * page_size,
            "swap_out_bytes": (sample["swap_out_pages"] - baseline["swap_out_pages"]) * page_size}


def host_violation(sample: dict, baseline: dict, limits: Limits, *, admission=False, previous=None) -> str | None:
    progress = swap_progress(sample, baseline, previous)
    needed = limits.reserve_bytes + limits.margin_bytes + (limits.workload_bytes if admission else 0)
    if sample["available_bytes"] < needed:
        return "host_reserve_headroom"
    if progress["swap_out_bytes"]:
        return "host_swap_out_activity"
    if progress["swap_in_bytes"] > limits.cold_swap_in_bytes:
        return "host_cold_swap_in_budget"
    if sample["psi_avg10"] is not None and sample["psi_avg10"] >= 10:
        return "host_memory_pressure"
    return None


def preflight(limits: Limits = Limits(), *, admission=False) -> dict:
    limits.validate()
    if sys.platform != "linux" or not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        raise RuntimeError("Linux pidfd supervision is required")
    first = host_sample()
    time.sleep(0.2)
    second = host_sample()
    reason = host_violation(second, first, limits, admission=admission)
    if reason:
        raise RuntimeError(f"resource preflight blocked: {reason}")
    # Keep the first counters so admission readback counts toward the same
    # operation-wide budget; retain the newer sample to detect any later reset.
    return {**first, "admission_sample": second}


def own_cgroup(proc: Path = Path("/proc"), root: Path = Path("/sys/fs/cgroup")) -> Path:
    rows = (proc / "self/cgroup").read_text().splitlines()
    names = [line[3:] for line in rows if line.startswith("0::")]
    if len(names) != 1 or not names[0].startswith("/system.slice/") or not UNIT.fullmatch(Path(names[0]).name):
        raise RuntimeError("resource supervision requires a dedicated systemd quality service")
    path = root / names[0].lstrip("/")
    if path.resolve() != path or not path.is_dir() or os.access(path / "cgroup.procs", os.W_OK):
        raise RuntimeError("quality cgroup must exist and be undelegated/read-only")
    if any(p.is_dir() for p in path.iterdir()):
        raise RuntimeError("nested cgroups are not permitted in this isolated workload")
    quota, period = (path / "cpu.max").read_text().split()
    if quota == "max" or int(quota) / int(period) > 2 or int((path / "pids.max").read_text()) > 256:
        raise RuntimeError("CPU or process cgroup bound is missing")
    weight = path / "io.weight"
    if not weight.exists():
        weight = path / "io.bfq.weight"
    if weight.read_text().strip() != "default 10":
        raise RuntimeError("I/O scheduling weight must remain 10")
    return path


def members(cgroup: Path) -> set[int]:
    return {int(value) for value in (cgroup / "cgroup.procs").read_text().split()}


def aggregate(cgroup: Path, *, proc: Path = Path("/proc")) -> dict:
    rss = swap = count = 0
    for pid in members(cgroup):
        try:
            values = numeric_fields(proc / str(pid) / "smaps_rollup")
            rss += values["Rss"]
            swap += values["Swap"]
            count += 1
        except (FileNotFoundError, ProcessLookupError):
            # Process exit is normal. A remaining PID with unreadable accounting
            # is never silently omitted from the workload total.
            if pid in members(cgroup):
                raise RuntimeError("live workload process has no readable memory accounting")
    return {"rss_bytes": rss, "swap_bytes": swap, "processes": count}


def signal_members(cgroup: Path, selected_signal: int) -> None:
    for pid in members(cgroup) - {os.getpid()}:
        descriptor = None
        try:
            descriptor = os.pidfd_open(pid, 0)
            # Membership is rechecked after opening a stable process handle;
            # pidfd signaling cannot target a recycled numeric PID.
            if pid in members(cgroup):
                signal.pidfd_send_signal(descriptor, selected_signal)
        except ProcessLookupError:
            pass
        finally:
            if descriptor is not None:
                os.close(descriptor)


def terminate(cgroup: Path, child: subprocess.Popen | None) -> bool:
    signal_members(cgroup, signal.SIGTERM)
    deadline = time.monotonic() + 3
    while members(cgroup) - {os.getpid()} and time.monotonic() < deadline:
        if child:
            child.poll()
        signal_members(cgroup, signal.SIGKILL)
        time.sleep(0.05)
    if child:
        child.wait(timeout=1)
    return not (members(cgroup) - {os.getpid()})


def restrict_address_space(limit: int) -> None:
    import resource
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    bound = min(limit, hard) if hard != resource.RLIM_INFINITY else limit
    resource.setrlimit(resource.RLIMIT_AS, (bound, bound))


def monitor(child: subprocess.Popen, cgroup: Path, limits: Limits, baseline: dict, receipt: dict) -> None:
    started = previous = time.monotonic()
    previous_host = baseline.get("admission_sample", baseline)
    while True:
        sample, host = aggregate(cgroup), host_sample()
        now = time.monotonic()
        gap = now - previous
        receipt.update(samples=receipt["samples"] + 1,
            peak_rss_bytes=max(receipt["peak_rss_bytes"], sample["rss_bytes"]),
            minimum_available_bytes=min(receipt["minimum_available_bytes"], host["available_bytes"]),
            peak_processes=max(receipt["peak_processes"], sample["processes"]),
            maximum_sample_gap_seconds=max(receipt["maximum_sample_gap_seconds"], gap), last_host_sample=host)
        progress = swap_progress(host, baseline, previous_host)
        receipt.update(cold_swap_in_bytes=progress["swap_in_bytes"],
            peak_workload_swap_bytes=max(receipt["peak_workload_swap_bytes"], sample["swap_bytes"]))
        reason = host_violation(host, baseline, limits, previous=previous_host)
        if sample["rss_bytes"] >= limits.workload_bytes - limits.margin_bytes:
            reason = "aggregate_rss_early_stop"
        elif sample["swap_bytes"]:
            reason = "workload_swapped"
        elif gap > limits.max_sample_gap_seconds:
            reason = "supervision_sample_gap"
        elif now - started >= limits.runtime_seconds:
            reason = "workload_timeout"
        if reason:
            raise RuntimeError(reason)
        status = child.poll()
        if status is not None:
            receipt["workload_exit_code"] = status
            if status or members(cgroup) - {os.getpid()}:
                raise RuntimeError("workload_failed_or_left_descendants")
            return
        previous = now
        previous_host = host
        time.sleep(limits.sample_seconds)


def supervise(command: list[str], output: Path, limits: Limits) -> dict:
    limits.validate()
    if not command or not output.is_absolute() or output.resolve() != output or output.exists():
        raise ValueError("command and a new canonical absolute resource receipt path required")
    receipt = {"schema": SCHEMA, "result": "BLOCKED", "mode": "sampled_cgroup_rss",
        "limits": asdict(limits), "command": command, "samples": 0, "peak_rss_bytes": 0, "peak_processes": 0,
        "peak_workload_swap_bytes": 0, "cold_swap_in_bytes": 0,
        "maximum_sample_gap_seconds": 0, "workload_exit_code": None, "group_clean": False}
    child = cgroup = None
    owned = False
    saved_signals = {}
    try:
        cgroup = own_cgroup()
        if members(cgroup) != {os.getpid()}:
            raise RuntimeError("new workload cgroup already contains another process")
        owned = True
        baseline = preflight(limits, admission=True)
        receipt.update(cgroup=str(cgroup), baseline=baseline,
            minimum_available_bytes=min(baseline["available_bytes"], baseline["admission_sample"]["available_bytes"]),
            page_size_bytes=baseline["page_size_bytes"],
            psi_available=baseline["psi_avg10"] is not None,
            kernel_memory_limit_bytes=int((cgroup / "memory.max").read_text()) if (cgroup / "memory.max").exists() else None)
        def interrupted(_signum, _frame):
            raise RuntimeError("supervisor_interrupted")
        for signum in (signal.SIGTERM, signal.SIGINT):
            saved_signals[signum] = signal.signal(signum, interrupted)
        child = subprocess.Popen(command, shell=False, start_new_session=True,
            preexec_fn=lambda: restrict_address_space(limits.address_space_bytes))
        monitor(child, cgroup, limits, baseline, receipt)
        receipt["result"] = "PASS"
    except Exception as error:
        receipt.update(result="FAIL" if child else "BLOCKED", reason=f"{type(error).__name__}: {error}")
    finally:
        for signum, handler in saved_signals.items():
            signal.signal(signum, signal.SIG_IGN)
        if cgroup is not None and owned:
            try:
                receipt["group_clean"] = terminate(cgroup, child)
            except Exception as error:
                receipt.update(group_clean=False, cleanup_error=type(error).__name__)
        if not receipt["group_clean"]:
            receipt["result"] = "FAIL" if child else "BLOCKED"
        receipt["early_stop_overshoot_bytes"] = max(0, receipt["peak_rss_bytes"] - (limits.workload_bytes - limits.margin_bytes))
        for signum, handler in saved_signals.items():
            signal.signal(signum, handler)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x") as stream:
            json.dump(receipt, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    return receipt


def require_receipt(receipt: dict) -> None:
    limits = Limits(**receipt["limits"])
    limits.validate()
    progress = swap_progress(receipt["last_host_sample"], receipt["baseline"], receipt["baseline"].get("admission_sample"))
    if (receipt.get("schema") != SCHEMA or receipt.get("result") != "PASS"
            or receipt.get("mode") != "sampled_cgroup_rss" or receipt.get("group_clean") is not True
            or receipt.get("workload_exit_code") != 0 or receipt.get("samples", 0) < 1
            or receipt.get("peak_rss_bytes", 3 * GIB) >= limits.workload_bytes - limits.margin_bytes
            or receipt.get("minimum_available_bytes", 0) < limits.reserve_bytes + limits.margin_bytes
            or receipt.get("maximum_sample_gap_seconds", 3) > limits.max_sample_gap_seconds
            or any(type(receipt.get(key)) is not int for key in ("page_size_bytes", "cold_swap_in_bytes", "peak_workload_swap_bytes"))
            or receipt.get("page_size_bytes") != receipt["baseline"]["page_size_bytes"]
            or receipt.get("cold_swap_in_bytes") != progress["swap_in_bytes"]
            or receipt.get("peak_workload_swap_bytes") != 0
            or host_violation(receipt["last_host_sample"], receipt["baseline"], limits)):
        raise ValueError("complete successful bounded-resource receipt required")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--runtime-seconds", type=float, default=5400)
    parser.add_argument("--workload-mib", type=int, default=3072)
    parser.add_argument("--margin-mib", type=int, default=512)
    parser.add_argument("--address-space-mib", type=int, default=3072)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    result = supervise(command, args.output, Limits(workload_bytes=args.workload_mib * 1024**2,
        margin_bytes=args.margin_mib * 1024**2, address_space_bytes=args.address_space_mib * 1024**2,
        runtime_seconds=args.runtime_seconds))
    print(json.dumps({"result": result["result"], "resource_receipt": str(args.output)}), flush=True)
    return 0 if result["result"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
