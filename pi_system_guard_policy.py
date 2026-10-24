"""Distinct fixed image admission; legacy plaintext producer policy is unchanged."""
from datetime import datetime, time, timedelta, timezone
import re

from pi_plain_backup_core import Blocked, finish

PHASES = {"PROBE", "baseline", "prepare", "finalize", "archive", "build", "compress", "upload"}


def validate(packet, nonce, now):
    if (not re.fullmatch(r"[a-f0-9]{32}", nonce or "") or packet.get("nonce") != nonce
            or packet.get("schema") != "ar-local-system-recovery-packet-v1"
            or packet.get("manual_system_recovery") is not True
            or packet.get("unit") != "ar-local-plain-backup-" + nonce + ".service"
            or packet.get("phase") not in PHASES
            or packet.get("mode") != ("PROBE" if packet["phase"] == "PROBE" else "RUN_ARCHIVE")
            or not re.fullmatch(r"[a-f0-9]{32}", packet.get("workspace_id", ""))):
        raise Blocked("fixed image authority, phase or workspace differs")
    created, expiry = map(datetime.fromisoformat, (packet["created_at"], packet["expires_at"]))
    limit = 120 if packet["phase"] == "PROBE" else 21600
    if (created.utcoffset() != timezone.utc.utcoffset(created) or expiry.utcoffset() != timezone.utc.utcoffset(expiry)
            or not 0 < (expiry - created).total_seconds() <= limit or not created <= now < expiry):
        raise Blocked("bounded image authority expired or not active")
    from zoneinfo import ZoneInfo
    start, end = created.astimezone(ZoneInfo("Australia/Hobart")), expiry.astimezone(ZoneInfo("Australia/Hobart"))
    date = start.date()
    while date <= end.date():
        lower = datetime.combine(date, time(0, 25), start.tzinfo)
        upper = datetime.combine(date, time(3, 30), start.tzinfo)
        if start < upper and end >= lower:
            raise Blocked("image phase intersects natural-ingest quiet window")
        date += timedelta(days=1)
    hashes = ("source_closure_sha256", "queue_closure_sha256", "parent_sha256", "resources_sha256", "broker_sha256",
              "bwrap_sha256", "setpriv_sha256", "backend_approval_sha256", "queue_argv_sha256",
              "reconcile_registry_sha256", "reconcile_wrapper_sha256", "global_hold_sha256", "sudo_sha256")
    if any(not re.fullmatch(r"[a-f0-9]{64}", str(packet.get(key, ""))) for key in hashes):
        raise Blocked("independent image/control source binding missing")
    if any(type(packet.get(key)) is not int or packet[key] <= 0 for key in ("uid", "gid")):
        raise Blocked("fixed nonroot parent/transport account required")
    if packet["phase"] == "upload" and packet.get("manual_image_drive_write") is not True:
        raise Blocked("specific image-object write authority absent")
    if packet["phase"] == "upload" and any(not re.fullmatch(r"[a-f0-9]{64}", packet.get(key, "")) for key in ("upload_plan_sha256", "credential_sha256")):
        raise Blocked("sealed image upload/credential binding absent")


def acquire(host, nonce):
    packet = host.packet(nonce)
    validate(packet, nonce, host.now())
    if host.intent(nonce) is not None or host.value() != 60:
        raise Blocked("fresh image intent and unowned measured swappiness60 required")
    identity = host.admission(packet)
    record = {"schema": 1, "nonce": nonce, "phase": "PREPARED", "previous": 60,
              "unit": packet["unit"], "source_closure_sha256": packet["source_closure_sha256"],
              "boot_id": host.boot(), "created_at": host.now().isoformat(), "identity": identity, "restore_required": True}
    host.save_intent(nonce, record, create=True)
    host.recheck(packet, identity)
    if host.value() != 60:
        raise Blocked("image lease policy changed before temporary zero")
    host.set_value(0)
    if host.value() != 0:
        raise Blocked("temporary zero readback failed")
    record.update(phase="ACTIVE", applied_at=host.now().isoformat())
    host.save_intent(nonce, record)
    host.write_handoff(packet, identity)
    return {"result": "ACQUIRED", "nonce": nonce, "readback": 0}
