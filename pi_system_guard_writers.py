"""Durable, exact existing-unit quiescence and restoration for image capture."""
import os
from pathlib import Path
import re
import subprocess

from pi_plain_backup_linux import atomic
from pi_shared_queue_post_hooks import root_json

ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"}
FORBIDDEN = {"ar-local-daily.timer", "tailscaled.service", "ssh.service", "sshd.service", "NetworkManager.service", "systemd-journald.service"}


def active(unit, host):
    if not isinstance(unit, str) or not re.fullmatch(r"[A-Za-z0-9@_.:-]+\.(service|timer)", unit) or unit in FORBIDDEN:
        raise RuntimeError("critical infrastructure/natural schedule cannot be quiesced")
    result = subprocess.check_output(["/usr/bin/systemctl", "show", unit, "--property=ActiveState", "--value"], text=True, env=ENV, timeout=host.remaining_timeout(10)).strip()
    if result not in {"active", "inactive"}:
        raise RuntimeError("writer transitional/failed state requires owner reconciliation")
    return result


def plan_for(packet):
    return root_json(Path("/var/lib/ar-local-system-recovery-inputs") / packet["workspace_id"] / "writer-plan.json")


def quiesce(host, packet):
    if packet["phase"] not in {"baseline", "prepare", "finalize"}:
        return
    plan = plan_for(packet)
    units = set(plan["package_writers"])
    if packet["phase"] == "finalize":
        units.update(plan["application_writers"])
    if not units or len(units) > 64 or plan.get("restore_existing_writers") is not True:
        raise RuntimeError("explicit bounded original-writer restoration authority required")
    original = {unit: active(unit, host) for unit in sorted(units)}
    timers = {unit for unit in units if unit.endswith(".timer") and original[unit] == "active"}
    if not timers <= set(plan.get("restore_existing_timer_units", [])):
        raise RuntimeError("existing timer stop/restore authority must name every exact active timer")
    body = {"schema": "ar-local-system-writers-v1", "nonce": packet["nonce"], "boot_id": host.boot(),
            "phase": "STOPPING", "original": original, "restoration_required": True}
    atomic(host.private / "writer-state.json", body)
    for unit, state in original.items():
        if state == "active":
            subprocess.run(["/usr/bin/systemctl", "stop", unit], check=True, timeout=host.remaining_timeout(30), env=ENV)
        if active(unit, host) != "inactive":
            raise RuntimeError("exact application/package writer did not quiesce")
    body["phase"] = "QUIESCED"
    atomic(host.private / "writer-state.json", body, replace=True)


def restore(host, packet):
    path = host.private / "writer-state.json"
    if not path.exists():
        return True
    body = root_json(path)
    if body["nonce"] != packet["nonce"] or body["boot_id"] != host.boot():
        raise RuntimeError("writer restoration cannot infer cross-boot original state")
    if body["phase"] == "RESTORED":
        return all(active(unit, host) == expected for unit, expected in body["original"].items())
    body["phase"] = "RESTORING"
    atomic(path, body, replace=True)
    for unit, expected in body["original"].items():
        observed = active(unit, host)
        if expected == "active" and observed == "inactive":
            subprocess.run(["/usr/bin/systemctl", "start", unit], check=True, timeout=host.remaining_timeout(30), env=ENV)
        elif expected == "inactive" and observed != "inactive":
            raise RuntimeError("originally inactive writer changed outside image ownership")
        if active(unit, host) != expected:
            raise RuntimeError("original writer state not restored")
    body.update(phase="RESTORED", restoration_required=False)
    atomic(path, body, replace=True)
    return True
