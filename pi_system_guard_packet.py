"""Prepare one fixed phase authority; never starts a unit or writes to Drive."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re

from pi_system_guard_files import directory, encoded, protected, publish, sha
from pi_system_guard_host import HANDOFF, ROOT, STATE, WORK
from pi_system_guard_plan import service_plan
from pi_system_guard_policy import PHASES, validate, validate_commissioning

INPUTS = Path("/var/lib/ar-local-system-recovery-inputs")


def expiry_for(phase, now):
    from zoneinfo import ZoneInfo
    local = now.astimezone(ZoneInfo("Australia/Hobart"))
    cutoff = local.replace(hour=0, minute=25, second=0, microsecond=0)
    if cutoff <= local:
        cutoff += timedelta(days=1)
    return min(now + timedelta(seconds=120 if phase == "PROBE" else 21600), cutoff.astimezone(timezone.utc) - timedelta(seconds=1))


def prepare(phase, nonce, workspace_id, coupled_probe=None, previous_phase=None):
    import pwd
    if phase not in PHASES or any(not re.fullmatch(r"[a-f0-9]{32}", item) for item in (nonce, workspace_id)):
        raise RuntimeError("fixed phase and fresh nonce/workspace required")
    receipt = json.loads(protected(ROOT / "installation.json"))
    closure_raw = protected(ROOT / "root-control-manifest.json")
    closure = json.loads(closure_raw)
    for path, checksum in closure.items():
        if sha(protected(Path(path), readonly=Path(path).parent == ROOT)) != checksum:
            raise RuntimeError("qualified image control closure changed")
    closure_hash = sha(json.dumps(closure, sort_keys=True, separators=(",", ":")).encode())
    if receipt.get("source_closure_sha256") != closure_hash or receipt.get("schema") != "ar-local-system-recovery-installation-v1":
        raise RuntimeError("image installation receipt differs")
    account = pwd.getpwnam("pi")
    now = datetime.now(timezone.utc)
    expiry = expiry_for(phase, now)
    budget = {"nonce": nonce, "unit": "ar-local-plain-backup-" + nonce + ".service",
              "mode": "PROBE" if phase == "PROBE" else "RUN_ARCHIVE", "created_at": now.isoformat(),
              "expires_at": expiry.isoformat(), "runtime_seconds": int((expiry-now).total_seconds())}
    service = service_plan(nonce, phase, packet=budget)
    queue = Path("/usr/local/lib/shared-pi-queue")
    names = {"pi_shared_queue.py", "pi_shared_queue_store.py", "pi_shared_queue_policy.py", "pi_shared_queue_native.py", "pi_shared_queue_post_hooks.py"}
    queue_closure = {name: sha(protected(queue / name, readonly=False)) for name in names}
    packet = {**budget, "schema": "ar-local-system-recovery-packet-v1", "phase": phase, "workspace_id": workspace_id,
              "manual_system_recovery": True, "root_control_manifest_sha256": sha(closure_raw),
              "uid": account.pw_uid, "gid": account.pw_gid, "source_closure_sha256": closure_hash,
              "queue_closure": queue_closure, "queue_closure_sha256": sha(json.dumps(queue_closure, sort_keys=True, separators=(",", ":")).encode()),
              "queue_argv_sha256": service["queue_argv_sha256"], "backend_approval_sha256": sha(protected(ROOT / "backend-approval.json")),
              "bwrap_sha256": sha(protected(Path("/usr/bin/bwrap").resolve(), readonly=False)), "setpriv_sha256": sha(protected(Path("/usr/bin/setpriv").resolve(), readonly=False)),
              "sudo_sha256": sha(protected(Path("/usr/bin/sudo").resolve(), readonly=False)),
              "reconcile_registry_sha256": sha(protected(Path("/etc/ar-local/system-recovery-reconcile.json"))),
              "reconcile_wrapper_sha256": receipt["plan"]["wrapper_sha256"], "global_hold_sha256": receipt["plan"]["global_hold_sha256"]}
    for name, key in (("parent.py", "parent_sha256"), ("broker.py", "broker_sha256"), ("pi_system_guard_resources.py", "resources_sha256")):
        packet[key] = closure[str(ROOT / name)]
    if phase != "PROBE":
        if not coupled_probe or not re.fullmatch(r"[a-f0-9]{32}", coupled_probe) or coupled_probe == nonce:
            raise RuntimeError("same-closure native coupled commissioning proof required")
        packet["coupled_probe_nonce"] = coupled_probe
        previous = json.loads(protected(STATE / coupled_probe / "packet.json"))
        proof = json.loads(protected(HANDOFF / coupled_probe / "coupled-probe.json"))
        validate_commissioning(packet, coupled_probe, previous, proof, Path("/proc/sys/kernel/random/boot_id").read_text().strip())
        if phase in {"fetch", "restore", "rejoin"}:
            from pi_system_guard_cold import vendors, predecessor, result_path
            from pi_system_cold import validate_plan
            cold_raw = protected(INPUTS / workspace_id / "cold-plan.json", maximum=16384)
            validate_plan(json.loads(cold_raw))
            vendor = vendors()
            packet.update(cold_plan_sha256=sha(cold_raw), cold_vendor=vendor,
                          cold_vendor_sha256=sha(json.dumps(vendor, sort_keys=True, separators=(",", ":")).encode()))
            if phase != "fetch":
                if not re.fullmatch("[a-f0-9]{32}", previous_phase or ""):
                    raise RuntimeError("actual completed cold predecessor nonce required")
                packet["previous_phase_nonce"] = previous_phase
                if phase == "rejoin":
                    prior = json.loads(protected(result_path(packet), readonly=False))
                    packet["recovery_set_sha256"] = prior["recovery_set_sha256"]
            elif previous_phase is not None:
                raise RuntimeError("cold fetch has no predecessor argument")
            predecessor(packet)
        elif phase == "baseline":
            if (WORK / workspace_id).exists():
                raise RuntimeError("baseline requires a new workspace")
            catalog = protected(INPUTS / workspace_id / "raw-catalog.json")
            protected(INPUTS / workspace_id / "layout.json")
            protected(INPUTS / workspace_id / "writer-plan.json")
            packet["raw_catalog_sha256"] = sha(catalog)
        elif not (WORK / workspace_id / "workspace.json").is_file():
            raise RuntimeError("durable capture workspace required")
    if phase in {"upload", "fetch"}:
        packet.update(remote=receipt["plan"]["remote"], drive_root_folder_id=receipt["plan"]["drive_root_folder_id"])
        if phase == "upload":
            from pi_system_guard_export import plan_for
            packet["manual_image_drive_write"] = True
            packet["upload_plan_sha256"] = sha(encoded(plan_for(workspace_id)))
        else:
            packet["manual_image_drive_read"] = True
        # The owner stages a read-only operation COPY using the qualified plain
        # credential-custody procedure. This builder never changes the original.
        credential = HANDOFF / nonce / "credentials-copy.conf"
        raw = protected(credential, maximum=65536)
        info = credential.stat()
        if info.st_gid != account.pw_gid or info.st_mode & 0o777 != 0o440:
            raise RuntimeError("operation credential COPY must be root:pi0440")
        packet["credential_sha256"] = sha(raw)
    validate(packet, nonce, now)
    private, public = STATE / nonce, HANDOFF / nonce
    if private.exists() or (public.exists() and (phase not in {"upload", "fetch"} or set(path.name for path in public.iterdir()) != {"credentials-copy.conf"})):
        raise RuntimeError("fresh unused operation nonce required")
    directory(private, 0o700)
    directory(public, 0o750, account.pw_gid)
    publish(private / "packet.json", encoded(packet))
    publish(private / "service-plan.json", encoded(service))
    authority = {key: packet[key] for key in ("nonce", "unit", "phase", "mode", "manual_system_recovery", "expires_at",
                                               "source_closure_sha256", "parent_sha256", "resources_sha256", "broker_sha256", "queue_argv_sha256")}
    if phase == "upload":
        authority["manual_image_drive_write"] = True
    if phase == "fetch":
        authority["manual_image_drive_read"] = True
    authority["schema"] = "ar-local-system-recovery-authority-v1"
    publish(public / "approval.json", encoded(authority), 0o440, account.pw_gid)
    return {"result": "IMAGE_PHASE_PREPARED_NOT_STARTED", "phase": phase, "nonce": nonce, "service_plan": str(private / "service-plan.json"),
            "runtime_inputs": service["runtime_inputs"],
            "source_closure_sha256": closure_hash, "expires_at": packet["expires_at"]}
