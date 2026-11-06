"""Start exactly one prepared native image phase; no schedule API exists."""
import json
import os
import re
import subprocess

from pi_system_guard_files import encoded, protected, publish
from pi_system_guard_host import ImageHost, STATE
from pi_system_guard_plan import service_plan
from pi_system_guard_policy import validate


def start(nonce):
    if not re.fullmatch(r"[a-f0-9]{32}", nonce):
        raise RuntimeError("fixed prepared nonce required")
    host = ImageHost(nonce)
    packet = host.packet(nonce)
    validate(packet, nonce, host.now())
    plan = json.loads(protected(STATE / nonce / "service-plan.json"))
    if plan != service_plan(nonce, packet["phase"], packet=packet) or plan["queue_argv_sha256"] != packet["queue_argv_sha256"]:
        raise RuntimeError("native service plan differs from fixed source")
    from pi_shared_queue_post_hooks import approval
    authority = approval(packet["unit"], current=True)
    if authority.get("schema") != "ar-local-system-recovery-authority-v1" or authority.get("phase") != packet["phase"]:
        raise RuntimeError("qualified distinct image queue bridge absent")
    if host.value() != 60 or host.intent(nonce) is not None or host._show(plan["unit"])["LoadState"] != "not-found":
        raise RuntimeError("fresh native unit and unowned policy60 required")
    receipt = STATE / nonce / "start-intent.json"
    publish(receipt, encoded({"result": "START_REQUESTED", "nonce": nonce, "unit": plan["unit"], "phase": packet["phase"]}))
    argv = ["/usr/bin/systemd-run", "--no-block", "--unit=" + plan["unit"], "--collect"]
    argv += ["--property=" + name + "=" + value for name, value in sorted(plan["properties"].items())]
    argv += ["--", *plan["argv"]]
    subprocess.run(argv, check=True, timeout=15, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"})
    # systemd-run acknowledgement proves submission only; runtime acceptance is
    # root completion + resources + phase business receipt, read independently.
    return {"result": "IMAGE_PHASE_SUBMITTED_NOT_ACCEPTED", "nonce": nonce, "unit": plan["unit"]}
