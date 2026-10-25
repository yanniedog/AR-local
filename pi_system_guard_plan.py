"""Fixed one-shot native service plan; no service or timer is created here."""
import hashlib
import json
import re

ROOT = "/usr/local/lib/ar-local-system-recovery"


def service_plan(nonce, phase):
    from pi_system_guard_policy import PHASES
    if not re.fullmatch(r"[a-f0-9]{32}", nonce) or phase not in PHASES:
        raise ValueError("fixed image phase and nonce required")
    runtime, wait = (120, 30) if phase == "PROBE" else (21600, 7200)
    argv = ["/usr/bin/python3", "-B", "/usr/local/lib/shared-pi-queue/pi_shared_queue.py", "run", "--project", "ar-local",
            "--resource", "ar-local", "--resource", "host", "--mode", "exclusive", "--cpu-slots", "1",
            "--max-runtime", str(runtime), "--wait-timeout", str(wait), "--",
            "/usr/bin/python3", "-I", "-S", "-B", ROOT + "/parent.py", nonce]
    return {"unit": "ar-local-plain-backup-" + nonce + ".service", "argv": argv,
            "queue_argv_sha256": hashlib.sha256(json.dumps(argv, separators=(",", ":")).encode()).hexdigest(),
            "properties": {"User": "pi", "Group": "pi", "Type": "notify", "NotifyAccess": "main", "CPUQuota": "100%",
                           "IOWeight": "10", "TasksMax": "64", "RuntimeMaxSec": str(runtime), "TimeoutStartSec": str(wait + 60),
                           "TimeoutStopSec": "45", "KillMode": "control-group", "SendSIGKILL": "yes", "NoNewPrivileges": "no", "UMask": "0077",
                           "ExecStopPost": "+/usr/bin/python3 -I -S -B " + ROOT + "/broker.py recover " + nonce},
            "sudoers_exact_commands": ["/usr/bin/python3 -I -S -B " + ROOT + "/broker.py " + action + " " + nonce for action in ("acquire", "finish")]}
