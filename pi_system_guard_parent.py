"""Unprivileged, source-qualified queue parent; fixed image helper verbs only."""
import hashlib
import os
from pathlib import Path
import re
import subprocess

ROOT = Path("/usr/local/lib/ar-local-system-recovery")


def helper(action, nonce):
    if action not in {"acquire", "finish"}:
        raise RuntimeError("fixed image helper action required")
    return subprocess.run(["/usr/bin/sudo", "-n", "/usr/bin/python3", "-I", "-S", "-B", str(ROOT / "broker.py"), action, nonce],
                          capture_output=True, text=True, check=True, timeout=21630 if action == "acquire" else 30)


def main(nonce):
    if os.geteuid() == 0 or not re.fullmatch(r"[a-f0-9]{32}", nonce):
        raise RuntimeError("fixed nonroot image parent nonce required")
    from pi_shared_queue_post_hooks import approval
    authority = approval("ar-local-plain-backup-" + nonce + ".service", current=True)
    if authority["schema"] != "ar-local-system-recovery-authority-v1" or hashlib.sha256((ROOT / "parent.py").read_bytes()).hexdigest() != authority["parent_sha256"]:
        raise RuntimeError("image authority/parent source differs")
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines())
    if status["NoNewPrivs"].strip() != "0":
        raise RuntimeError("fixed helper parent requires its native privilege boundary")
    descriptor = os.open("/srv/ar-local/data/state/daily-ingest.lock", os.O_RDONLY | os.O_NOFOLLOW)
    if descriptor != 3:
        os.dup2(descriptor, 3, inheritable=True)
        os.close(descriptor)
    else:
        os.set_inheritable(3, True)
    try:
        try:
            helper("acquire", nonce)
        finally:
            helper("finish", nonce)
    finally:
        os.close(3)
    return 0
