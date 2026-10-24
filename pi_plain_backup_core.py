"""Fixed-scope root lease policy for a manually authorized plaintext backup.

Pure standard-library policy. No completed new backup is a prerequisite for
creating that backup. Existing source data and the global Restic hold stay intact.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re

NONCE = re.compile(r"[0-9a-f]{32}\Z")


class Blocked(RuntimeError):
    pass


def validate_packet(packet, nonce, now):
    if (not NONCE.fullmatch(nonce or "") or packet.get("schema") != "ar-local-plain-backup-packet-v1"
            or packet.get("nonce") != nonce or packet.get("unit") != "ar-local-plain-backup-" + nonce + ".service"
            or packet.get("manual_plaintext_drive_write") is not True
            or packet.get("data_root") != "/srv/ar-local/data"
            or packet.get("credential_source") != "/var/lib/ar-local-drive-backup/credentials/dedicated-20260913-ready3/rclone-verified-ready3.conf"):
        raise Blocked("specific manual plaintext-backup authority differs")
    expiry = datetime.fromisoformat(packet["expires_at"])
    created = datetime.fromisoformat(packet["created_at"])
    if (expiry.utcoffset() != timezone.utc.utcoffset(expiry) or created.utcoffset() != timezone.utc.utcoffset(created)
            or not 0 < (expiry-created).total_seconds() <= 21600 or not created <= now < expiry):
        raise Blocked("backup authority expired, not yet active, or exceeds six hours")
    for key in ("queue_closure_sha256", "source_closure_sha256", "parent_sha256", "resources_sha256", "bwrap_sha256",
                "credential_sha256", "global_hold_sha256", "broker_sha256", "setpriv_sha256", "reconcile_wrapper_sha256", "reconcile_original_sha256", "reconcile_callback_sha256"):
        if not re.fullmatch("[0-9a-f]{64}", str(packet.get(key, ""))):
            raise Blocked("independently reviewed source/control binding missing")

    if (any(type(packet.get(key)) is not int or packet[key]<=0 for key in ("uid","gid"))
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*:plaintext-recovery",packet.get("remote",""))
            or not re.fullmatch(r"[A-Za-z0-9_-]{10,128}",packet.get("drive_root_folder_id",""))):
        raise Blocked("fixed unprivileged identity/destination binding missing")
    if packet.get("mode") not in ("PROBE","RUN_ARCHIVE"):
        raise Blocked("fixed commissioning or archive mode required")
    if packet["mode"]=="PROBE" and (expiry-created).total_seconds()>120:
        raise Blocked("commissioning probe authority exceeds120 seconds")
    from zoneinfo import ZoneInfo
    # Finish the admitted operation before the natural-ingest quiet window.
    local_end=expiry.astimezone(ZoneInfo("Australia/Hobart"))
    local_start=created.astimezone(ZoneInfo("Australia/Hobart"))
    if (local_start.hour in (1,2) or local_start.hour==3 and local_start.minute<30 or local_start.hour==0 and local_start.minute>=25) or (local_end.hour in (1,2) or local_end.hour==3 and local_end.minute<30 or local_end.hour==0 and local_end.minute>=25):
        raise Blocked("backup authority intersects natural-ingest quiet window")
    if local_start.date()!=local_end.date():
        # Cross-midnight runs may end before 00:25 only.
        if local_end.hour!=0 or local_end.minute>=25:
            raise Blocked("backup authority crosses natural-ingest quiet window")


def acquire(host, nonce):
    packet = host.packet(nonce)
    validate_packet(packet, nonce, host.now())
    if host.intent(nonce) is not None:
        raise Blocked("nonce already has an intent; recover rather than retry")
    if host.value() != 60:
        raise Blocked("unowned measured swappiness60 required")
    # Includes actual unit/callback/queue/native/PID/FD3 checks, source closure,
    # sandbox proof, scoped write authority and existing reconciliation callback.
    identity = host.admission(packet)
    record = {"schema": 1, "nonce": nonce, "phase": "PREPARED", "previous": 60,
              "unit": packet["unit"], "source_closure_sha256": packet["source_closure_sha256"],
              "boot_id": host.boot(), "created_at": host.now().isoformat(),
              "identity": identity, "restore_required": True}
    host.save_intent(nonce, record, create=True)  # fsync before the first sysctl write.
    host.recheck(packet, identity)
    if host.value() != 60:
        raise Blocked("swappiness changed before lease application")
    host.set_value(0)
    if host.value() != 0:
        raise Blocked("temporary zero readback failed")
    record.update(phase="ACTIVE", applied_at=host.now().isoformat())
    host.save_intent(nonce, record)
    host.write_handoff(packet, identity)
    return {"result": "ACQUIRED", "nonce": nonce, "readback": 0}


def finish(host, nonce, *, recovery=False):
    packet = host.packet(nonce)
    if not NONCE.fullmatch(nonce or "") or packet.get("nonce") != nonce:
        raise Blocked("fixed nonce mismatch")
    record = host.intent(nonce)
    if record is None:
        # Root stop-post may run after a pre-acquisition failure. It can close a
        # known, terminal invocation, but must never restore an unowned zero.
        if not recovery or host.value() != 60:
            raise Blocked("no owned lease; never overwrite another zero policy")
        identity = host.no_acquire_identity(packet)
        host.prove_terminal(packet, identity, recovery=True)
        host.quarantine_credential(packet)
        host.complete(packet, identity, result="NOT_ACQUIRED", readback=60)
        return {"result": "NOT_ACQUIRED", "nonce": nonce, "readback": 60}
    if (record.get("schema") != 1 or record.get("nonce") != nonce or record.get("unit") != packet["unit"]
            or record.get("source_closure_sha256") != packet["source_closure_sha256"]
            or record.get("previous") != 60 or record.get("phase") not in ("PREPARED", "ACTIVE", "RESTORING", "RESTORED")):
        raise Blocked("durable ownership differs")
    identity = record["identity"]
    host.prove_terminal(packet, identity, recovery=recovery)
    current = host.value()
    if current not in (0, 60):
        raise Blocked("swappiness changed outside this lease")
    if record["phase"]=="RESTORED" and current!=60:
        raise Blocked("completed lease cannot authorize a later zero")
    if record["boot_id"] != host.boot():
        if not recovery or current != 60:
            raise Blocked("new-boot zero is unattributable; leave it unchanged")
    elif current == 60 and record["phase"] == "ACTIVE":
        raise Blocked("active lease was changed without its restoration intent")
    if record["phase"] != "RESTORED":
        host.observe_terminal(packet,identity,"before_restore")
    host.quarantine_credential(packet)
    if record["phase"] != "RESTORED":
        record.update(phase="RESTORING", restoration_started_at=host.now().isoformat())
        host.save_intent(nonce, record)
        if current == 0:
            host.set_value(60)
        if host.value() != 60:
            raise Blocked("restoration readback failed")
        record.update(phase="RESTORED", restore_required=False, readback=60,
                      restored_at=host.now().isoformat(), restored_boot_id=host.boot())
        host.save_intent(nonce, record)
        host.observe_terminal(packet,identity,"after_restore")
    host.complete(packet, identity, result="RESTORED", readback=60)
    return {"result": "RESTORED", "nonce": nonce, "readback": 60}
