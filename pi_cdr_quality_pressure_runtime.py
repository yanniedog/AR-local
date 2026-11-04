"""Bind host-pressure and external service observations to one guarded workload.

No service/network access occurs inside the private-network workload. Its parent
owns the read-only companion directory, bound by hash and exact cgroup identity.
"""
from __future__ import annotations

import copy
import math
from pathlib import Path
import re
import time

from pi_cdr_quality_pressure import PressureTracker, require_pressure_receipt
from pi_cdr_quality_service import read_binding, read_service_snapshot, require_service_receipt

PROFILE = "allocation-v1"


def finite(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("invalid pressure observation time")
    return value


class PressureContext:
    def __init__(self, directory: Path, expected_sha256: str, *, unit: str, operation: Path):
        if not re.fullmatch("[0-9a-f]{64}", expected_sha256 or ""):
            raise ValueError("pressure binding digest required")
        if directory != operation / "pressure" or operation.resolve() != operation:
            raise ValueError("pressure directory must belong to this operation")
        self.binding, self.binding_sha256 = read_binding(directory)
        if self.binding_sha256 != expected_sha256 or self.binding["unit"] != unit or self.binding["operation"] != str(operation):
            raise ValueError("pressure companion ownership mismatch")
        self.directory = directory
        self.tracker = None
        self.initial = self.last = None
        self.first_now = self.last_now = None
        self.max_age = self.max_gap = 0.0
        self.observations = 0
        self.peak_psi = None
        self.psi_available = None
        self.failure = None

    def observe(self, host):
        if self.failure is not None:
            raise ValueError("pressure context failure is latched")
        try:
            if host["pressure"]["boot_id"] != self.binding["boot_id"]:
                raise ValueError("pressure service/host boot mismatch")
            psi = host["psi_avg10"]
            if psi is not None:
                finite(psi)
            if self.observations and (psi is not None) != self.psi_available:
                raise ValueError("pressure PSI capability changed")
            self.psi_available = psi is not None
            if psi is not None:
                self.peak_psi = max(self.peak_psi or 0, psi)
                if psi >= 10:
                    raise ValueError("host_memory_pressure")
            snapshot = read_service_snapshot(self.directory, self.binding, self.last, None)
            now = time.monotonic()
            if not 0 <= now - host["pressure"]["monotonic_ns"] / 1e9 <= 2:
                raise ValueError("pressure host/service observation skew")
            age = now - snapshot["finished_monotonic"]
            self.max_age = max(self.max_age, age)
            if self.last_now is not None:
                gap = now - self.last_now
                if not 0 < gap <= 2:
                    raise ValueError("pressure service observation gap")
                self.max_gap = max(self.max_gap, gap)
            else:
                self.initial, self.first_now = copy.deepcopy(snapshot), now
            self.last, self.last_now = copy.deepcopy(snapshot), now
            self.observations += 1
            if self.tracker is None:
                self.tracker = PressureTracker(host)
            else:
                self.tracker.observe(host, now=now)
        except Exception as error:
            self.failure = f"{type(error).__name__}: {error}"
            raise

    def receipt(self):
        host = self.tracker.receipt() if self.tracker is not None else None
        service = None
        if host is not None:
            service = {"schema": "ar-local-service-receipt-v1", "binding": self.binding,
                "binding_sha256": self.binding_sha256, "initial_snapshot": self.initial,
                "last_snapshot": self.last, "observations": self.observations,
                "max_age_s": self.max_age, "max_observation_gap_s": self.max_gap,
                "window_started_monotonic": host["baseline_monotonic_ns"] / 1e9,
                "window_finished_monotonic": host["last_monotonic_ns"] / 1e9,
                "first_observed_monotonic": self.first_now, "last_observed_monotonic": self.last_now}
        return {"profile": PROFILE, "failure": self.failure, "host": host, "service": service,
                "psi_available": self.psi_available, "peak_psi_avg10": self.peak_psi}


def require_pressure_evidence(receipt):
    value = receipt["pressure_evidence"]
    if set(value) != {"profile", "failure", "host", "service", "psi_available", "peak_psi_avg10"}:
        raise ValueError("pressure evidence inventory")
    if value["profile"] != PROFILE or value["failure"] is not None:
        raise ValueError("successful pressure evidence required")
    baseline, last = receipt["baseline"], receipt["last_host_sample"]
    require_pressure_receipt(value["host"], baseline, last)
    count = receipt["samples"]
    if type(count) is not int or value["host"]["observations"] != count + 2 or value["service"]["observations"] != count + 2:
        raise ValueError("pressure observations omit admission or workload samples")
    service = value["service"]
    binding = service["binding"]
    if binding["boot_id"] != baseline["pressure"]["boot_id"] or Path(receipt["cgroup"]).name != binding["unit"]:
        raise ValueError("pressure receipt cgroup/boot mismatch")
    require_service_receipt(service, binding,
        started_monotonic=baseline["pressure"]["monotonic_ns"] / 1e9,
        finished_monotonic=last["pressure"]["monotonic_ns"] / 1e9)
    available = baseline["psi_avg10"] is not None
    if type(value["psi_available"]) is not bool or value["psi_available"] != available or (last["psi_avg10"] is not None) != available:
        raise ValueError("pressure PSI availability binding")
    peak = value["peak_psi_avg10"]
    if available:
        if not max(finite(baseline["psi_avg10"]), finite(last["psi_avg10"])) <= finite(peak) < 10:
            raise ValueError("pressure PSI peak invalid")
    elif peak is not None:
        raise ValueError("unavailable PSI cannot be represented as zero")
