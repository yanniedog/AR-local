"""Whole-cgroup image supervision, reusing pinned-PID plain-monitor primitives.

This module does not change the plain producer's UID/NNP/capability policy.
"""
from datetime import datetime
import os
from pathlib import Path
import select
import time
import threading

from pi_plain_drive_resources import (bind_parent_lifetime, cleanup_scope, host_violation,
                                      sample_host, sealed_context, snapshot_member)

MIB = 1024 ** 2
ROOT = Path("/usr/local/lib/ar-local-system-recovery")


class NativeObserver:
    """Bound native queries independently so resource sampling never waits on DBus."""
    def __init__(self, host, packet, owner):
        self.host, self.packet, self.owner = host, packet, owner
        self.stop, self.first = threading.Event(), threading.Event()
        self.last, self.error = None, None
        host.native_timeout = 0.75
        self.thread = threading.Thread(target=self.run, name="image-native-lease", daemon=True)
        self.thread.start()

    def run(self):
        try:
            while not self.stop.is_set():
                job, _ = self.host._job(self.packet)
                keys = {"pid": "owner_pid", "start_ticks": "owner_ticks", "boot_id": "boot_id", "id": "job_id", "invocation_id": "invocation"}
                if any(job.get(key) != self.owner[value] for key, value in keys.items()):
                    raise RuntimeError("native image owner changed")
                lease = self.host._lease(job)
                if (lease.st_dev, lease.st_ino) != (self.owner["device"], self.owner["inode"]):
                    raise RuntimeError("native image lease inode changed")
                if self.host.value() != 0:
                    raise RuntimeError("temporary image policy changed")
                self.last = time.monotonic()
                self.first.set()
                self.stop.wait(0.25)
        except BaseException as error:
            self.error = type(error).__name__ + ":" + str(error)
            self.first.set()

    def check(self):
        if self.error is not None:
            raise RuntimeError(self.error)
        if self.last is None or time.monotonic() - self.last > 1.25:
            raise RuntimeError("native image lease observation became stale")

    def close(self):
        self.stop.set()
        self.thread.join(timeout=0.85)
        if self.thread.is_alive():
            raise RuntimeError("native image observer failed bounded termination")


def context(host, packet, owner):
    from pi_plain_backup_core import packet_runtime_seconds
    current = host.process_identity(os.getpid())
    issued = time.monotonic()
    seconds = (datetime.fromisoformat(packet["expires_at"]) - host.now()).total_seconds()
    return {"schema": "ar-local-system-recovery-attestation-v1", "nonce": packet["nonce"],
            "phase": packet["phase"], "boot_id": host.boot(), "source_closure_sha256": packet["source_closure_sha256"],
            "workspace_id": packet["workspace_id"], "uid": packet["uid"], "gid": packet["gid"],
            "deadline_monotonic": issued + min(packet_runtime_seconds(packet), seconds),
            "monitor": current, "queue": owner, "upload_plan_sha256": packet.get("upload_plan_sha256"),
            "remote": packet.get("remote"), "drive_root_folder_id": packet.get("drive_root_folder_id"),
            "credential_sha256": packet.get("credential_sha256"), "cold_plan_sha256": packet.get("cold_plan_sha256")}


def fork_worker(host, packet, descriptor):
    output = os.open(host.private / "worker.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    parent = os.getpid()
    try:
        pid = os.fork()
    except BaseException:
        os.close(output)
        raise
    if pid == 0:
        try:
            bind_parent_lifetime(parent)
            os.dup2(descriptor, 3, inheritable=True)
            os.dup2(output, 1)
            os.dup2(output, 2)
            for name in os.listdir("/proc/self/fd"):
                if int(name) > 3:
                    try:
                        os.close(int(name))
                    except OSError:
                        pass
            argv = ["/usr/bin/python3", "-I", "-S", "-B", str(ROOT / "launch.py"), packet["nonce"]]
            os.execve(argv[0], argv, {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C", "HOME": "/root"})
        except BaseException:
            os._exit(75)
    os.close(output)
    return pid


def supervise(host, packet, owner):
    controller, intermediates = host._controller(packet)
    excluded = {owner["owner_pid"]: owner["owner_ticks"], controller["pid"]: controller["ticks"],
                os.getpid(): host.process_identity(os.getpid())["ticks"]}
    excluded.update({item["pid"]: item["ticks"] for item in intermediates})
    snapshots = {pid: host.process_identity(pid) for pid in excluded}
    if any(item["ticks"] != excluded[pid] or item["cgroup"] != owner["cgroup"] for pid, item in snapshots.items()):
        raise RuntimeError("trusted image control identity differs")
    started = previous_time = time.monotonic()
    previous, baseline = sample_host(), owner["resource_baseline"]
    if host_violation(previous, baseline, baseline, admission=True):
        raise RuntimeError("host unavailable for image phase")
    payload = context(host, packet, owner)
    descriptor = sealed_context(payload)
    child = child_ticks = status = observer = None
    result = {"schema": "ar-local-system-recovery-resources-v1", "result": "FAIL", "phase": packet["phase"],
              "baseline": baseline, "peak_rss_bytes": 0, "peak_workload_swap_bytes": 0, "samples": 0, "group_clean": False}
    try:
        observer = NativeObserver(host, packet, owner)
        if not observer.first.wait(1):
            raise RuntimeError("initial native image lease proof timed out")
        observer.check()
        child = fork_worker(host, packet, descriptor)
        try:
            child_ticks = host.process_identity(child)["ticks"]
        except Exception:
            handle = os.pidfd_open(child)
            try:
                poll = select.poll()
                poll.register(handle, select.POLLIN)
                if not poll.poll(0):
                    raise
            finally:
                os.close(handle)
        while True:
            observer.check()
            members, rss, swapped = host._members(owner["cgroup"]), 0, 0
            if not set(excluded) <= set(members):
                raise RuntimeError("trusted image controller left cgroup")
            for pid in members:
                accounted = snapshot_member(host, pid, owner["cgroup"], trusted=pid in excluded)
                if accounted is None:
                    continue
                item, memory = accounted
                if pid in excluded and item != snapshots[pid]:
                    raise RuntimeError("trusted image control PID changed")
                rss += memory["rss"]
                swapped += memory["swap"]
                if pid not in excluded and not host.trusted_observer(item, packet) and not host.allowed_worker(item, memory, child, packet):
                    raise RuntimeError("image phase privilege/executable boundary differs")
            current, now = sample_host(), time.monotonic()
            result.update(samples=result["samples"] + 1, peak_rss_bytes=max(result["peak_rss_bytes"], rss),
                          peak_workload_swap_bytes=max(result["peak_workload_swap_bytes"], swapped), last_host_sample=current)
            reason = host_violation(current, baseline, previous)
            if rss >= 640 * MIB:
                reason = "aggregate_rss_early_stop"
            elif swapped:
                reason = "workload_swapped"
            elif now - previous_time > 2:
                reason = "supervision_sample_gap"
            elif now >= payload["deadline_monotonic"]:
                reason = "workload_deadline"
            if reason:
                raise RuntimeError(reason)
            host.space_guard(packet)
            ended, waitstatus = os.waitpid(child, os.WNOHANG)
            if ended:
                status = os.waitstatus_to_exitcode(waitstatus)
                observer.close()
                observer.check()
                if status or set(host._members(owner["cgroup"])) - set(excluded):
                    raise RuntimeError("image phase exit or descendant cleanup failed")
                result.update(result="PASS", group_clean=True, workload_exit_code=0)
                break
            previous, previous_time = current, now
            time.sleep(0.1)
    except BaseException as error:
        result["reason"] = type(error).__name__ + ":" + str(error)
    finally:
        os.close(descriptor)
        if observer is not None:
            try:
                observer.close()
            except Exception as error:
                result.update(result="FAIL", reason=type(error).__name__ + ":" + str(error))
        if child is not None and result["result"] != "PASS":
            result["group_clean"] = cleanup_scope(host, owner["cgroup"], excluded, child, child_ticks, status)
        result["elapsed_seconds"] = time.monotonic() - started
    return result
