"""Fixed one-shot native service plan; no service or timer is created here."""
import hashlib
import json
import re
from pi_plain_backup_core import packet_runtime_seconds

ROOT = "/usr/local/lib/ar-local-system-recovery"


def service_plan(nonce, phase, *, packet):
    from pi_system_guard_policy import PHASES
    if not re.fullmatch(r"[a-f0-9]{32}", nonce) or phase not in PHASES:
        raise ValueError("fixed image phase and nonce required")
    if (packet.get("nonce") != nonce or packet.get("unit") != "ar-local-plain-backup-" + nonce + ".service"
            or packet.get("mode") != ("PROBE" if phase == "PROBE" else "RUN_ARCHIVE")):
        raise ValueError("frozen image packet runtime identity differs")
    runtime, wait = packet_runtime_seconds(packet), 0
    argv = ["/usr/bin/python3", "-B", "/usr/local/lib/shared-pi-queue/pi_shared_queue.py", "run", "--project", "ar-local",
            "--resource", "ar-local", "--resource", "host", "--mode", "exclusive", "--cpu-slots", "1",
            "--max-runtime", str(runtime), "--wait-timeout", str(wait), "--",
            "/usr/bin/python3", "-I", "-S", "-B", ROOT + "/parent.py", nonce]
    return {"unit": "ar-local-plain-backup-" + nonce + ".service", "argv": argv,
            "runtime_inputs": {key: packet[key] for key in ("nonce", "unit", "mode", "created_at", "expires_at", "runtime_seconds")},
            "queue_argv_sha256": hashlib.sha256(json.dumps(argv, separators=(",", ":")).encode()).hexdigest(),
            "properties": {"User": "pi", "Group": "pi", "Type": "notify", "NotifyAccess": "main", "CPUQuota": "100%",
                           "IOWeight": "10", "TasksMax": "64", "RuntimeMaxSec": str(runtime), "TimeoutStartSec": str(wait + 60),
                           "TimeoutStopSec": "45", "KillMode": "control-group", "SendSIGKILL": "yes", "NoNewPrivileges": "no", "UMask": "0077",
                           "ExecStopPost": "+/usr/bin/python3 -I -S -B " + ROOT + "/broker.py recover " + nonce},
            "sudoers_exact_commands": ["/usr/bin/python3 -I -S -B " + ROOT + "/broker.py " + action + " " + nonce for action in ("acquire", "finish")]}
