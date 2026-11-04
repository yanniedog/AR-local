"""Explicit Nov4 manual archive proof; never discovered by scheduled calls.

The four reviewed continuity modules and original preboot document are immutable
inputs, pinned here rather than selected by a caller-supplied module or callback.
This verifies historical terminal continuity, not runtime/deployment acceptance.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import sys
import types

from ar_local_operation_lock import OwnedProductionLock

DAY = "2026-11-04"
BOOT = "86e5cf0a-5470-4ab3-954d-2dcdb2f05574"
PREFLIGHT_SHA = "dcff5fc802cf2c2763c900f0e4086e2bcb7aa5527ac989e76942a15b81b9a040"
PINS = {
    "binding.py": "450dd921320ee607fafc81380c51e279f613ca12fb94482a5812e105ac4a4564",
    "continuity_v4_nov4.py": "3c41f10e55da21ac62e252c892364a3785c390477b5462588d191c883f116f64",
    "reboot_reader_nov4.py": "31da95853ae431e4240f35c11581727fc58fac846b2fca28551b2aa128b43c79",
    "guarded_reboot_v2_frozen.py": "23ba99ad2e7357d63c5461ad03accbaebf02c28c2f4ce51993997b5fba6617c2",
}


def checked(path: Path, expected: str, limit=2 * 1024**2) -> bytes:
    if path.absolute() != path.resolve() or not path.is_file():
        raise ValueError("noncanonical manual proof input")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("manual proof input changed")
    return raw


def _binding(directory: Path):
    _require_interpreter()
    # The frozen binding verifies helper hashes again when loading each helper.
    for name, digest in PINS.items():
        checked(directory / name, digest)
    path = directory / "binding.py"
    module = types.ModuleType("archive_nov4_binding")
    module.__file__ = str(path)
    exec(compile(checked(path, PINS[path.name]), str(path), "exec"), module.__dict__)
    return module


def _require_interpreter():
    # Frozen helpers use assertions. Their byte pins must not change, and their
    # checks must remain executable, including imports performed by the binding.
    if sys.flags.optimize != 0:
        raise ValueError("manual proof requires an unoptimized interpreter")


def _require_activity(host, unit: str):
    jobs, activity = host["queue_jobs"], host["unit_activity"]
    if (not isinstance(jobs, list) or len(jobs) != 1
            or not isinstance(jobs[0], dict) or jobs[0].get("unit") != unit):
        raise ValueError("manual proof queue inventory changed")
    expected = {unit + ":active", unit + ":members"}
    if (not isinstance(activity, list) or len(activity) != 2
            or any(not isinstance(item, str) for item in activity) or set(activity) != expected):
        raise ValueError("manual proof requires complete own-unit activity")
    job, row = jobs[0], host["units"][unit]
    # ownership() == live alone also permits a nonempty inactive cgroup. Require
    # the reader's complete running-unit record, bound to that authenticated job.
    if (not isinstance(row, dict) or row.get("Id") != unit or row.get("LoadState") != "loaded"
            or row.get("ActiveState") != "active" or row.get("Job") != ""
            or row.get("MainPID") != str(job["pid"]) or int(row["MainPID"]) <= 0
            or not isinstance(row.get("ControlPID"), str) or not row["ControlPID"].isdigit()
            or row.get("ControlGroup") != "/system.slice/" + unit
            or row["ControlGroup"] != job["cgroup"]
            or not row.get("InvocationID") or row["InvocationID"] != job["invocation_id"]):
        raise ValueError("manual proof running unit is incomplete or changed")


def _require_host(binding, host, unit: str, owner: OwnedProductionLock | None):
    """Repeat full host admission without hiding or rewriting the native lease."""
    _require_activity(host, unit)
    if owner is None:
        binding.require_idle_host(host, unit)
        return
    if host["blockers"] or host["production_head"] != binding.PREVIOUS:
        raise ValueError("manual proof host admission changed")
    if (owner.path != Path("/srv/ar-local/data/state/daily-ingest.lock")
            or owner.role != "daily-payload-archive"
            or host["native_lease"] != owner.verified_record()):
        raise ValueError("manual proof native lease differs from live owner")
    for name in ("ar-local-daily.timer", "ar-local-day-archive.timer", "ar-local-runtime-health.timer"):
        if host["units"][name]["ActiveState"] != "active":
            raise ValueError("manual proof timer restoration not proven")


def _owned_compare(binding, before, fresh, unit: str, owner: OwnedProductionLock):
    """Preserve compare(), replacing only absent lease with this live acquisition."""
    binding.validate_preboot(before)
    if (fresh["schema"] != 1 or fresh["target"] != binding.TARGET
            or fresh["previous"] != binding.PREVIOUS):
        raise ValueError("manual proof capture identity changed")
    result = binding.base.admit(before["continuity"], fresh["continuity"])
    if datetime.fromisoformat(fresh["continuity"]["at_hobart"]) <= datetime.fromisoformat(before["continuity"]["at_hobart"]):
        raise ValueError("manual proof capture is not newer")
    host = fresh["host"]
    _require_host(binding, host, unit, owner)
    if host["identity"]["boot_id"] != fresh["continuity"]["boot_id"]:
        raise ValueError("manual proof host boot differs")
    if fresh["installed"] != before["installed"]:
        raise ValueError("installed workers/timers changed")
    binding.load("guarded_reboot_v2_frozen.py").same_host(before["host"], host, rebooted=True)
    return result


@dataclass(frozen=True)
class ManualArchiveProof:
    path: Path
    sha256: str

    def verify(self, day: str, *, owner: OwnedProductionLock | None = None) -> dict:
        _require_interpreter()
        if date.fromisoformat(day).isoformat() != day or day > DAY or self.sha256 != PREFLIGHT_SHA:
            raise ValueError("manual proof is bound to one original date and capture")
        document = json.loads(checked(self.path, self.sha256))
        if document["schema"] != "nov4-boot-default-preflight-v1" or document["acceptance"] is not False:
            raise ValueError("invalid original preboot capture")
        sys.path.insert(0, "/usr/local/lib/shared-pi-queue")
        binding = _binding(self.path.parent)
        before = document["continuity"]
        binding.validate_preboot(before)
        fresh = binding.capture(before["continuity"]["boot_id"], before["installed_receipt"])
        if fresh["continuity"]["boot_id"] != BOOT:
            raise ValueError("manual proof boot differs")
        unit = binding.own_queue_unit(fresh["host"])
        if unit is None:
            raise ValueError("manual archive requires authenticated exclusive queue ownership")
        _require_activity(fresh["host"], unit)
        result = (binding.compare(before, fresh, allowed_unit=unit) if owner is None
                  else _owned_compare(binding, before, fresh, unit, owner))
        final = binding.reader.snapshot()
        if binding.own_queue_unit(final) != unit or final["identity"]["boot_id"] != BOOT:
            raise ValueError("manual proof queue or boot changed")
        _require_host(binding, final, unit, owner)
        binding.load("guarded_reboot_v2_frozen.py").same_host(fresh["host"], final)
        return {"proof_sha256": self.sha256, "day": DAY, "boot_id": BOOT,
                "generation": result["generation"], "result": "CONTINUITY_VERIFIED_ONLY"}
