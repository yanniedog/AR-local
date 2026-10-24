"""Root-owned but unprivileged trusted parent; no producer imports before NNP."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path("/usr/local/lib/ar-local-plain-backup")
HANDOFF=Path("/var/lib/ar-local-plain-backup-handoff")
WORK=Path("/var/lib/ar-local-plain-backup-work")


def helper(action,nonce):
    if action not in ("acquire","finish"): raise RuntimeError("fixed helper action only")
    return subprocess.run(["/usr/bin/sudo","-n","/usr/bin/python3","-I","-B",
        str(ROOT/"broker.py"),action,nonce],check=True,capture_output=True,text=True,
        timeout=21630 if action=="acquire" else 30)


def main(nonce):
    if (sys.platform!="linux" or os.geteuid()==0 or not re.fullmatch("[0-9a-f]{32}",nonce)
            or Path(__file__).resolve()!=ROOT/"parent.py"):
        raise RuntimeError("fixed installed unprivileged parent required")
    sys.path.insert(0,str(ROOT))
    from pi_shared_queue_post_hooks import approval, root_json
    authority=approval("ar-local-plain-backup-"+nonce+".service",current=True)
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest()!=authority["parent_sha256"]:
        raise RuntimeError("trusted parent source bytes differ")
    status=dict(line.split(":",1) for line in Path("/proc/self/status").read_text().splitlines())
    if status["NoNewPrivs"].strip()!="0": raise RuntimeError("trusted fixed-helper parent requires NNPfalse")
    plan=root_json(HANDOFF/nonce/"worker.json")
    if plan.get("nonce")!=nonce or plan.get("schema")!="ar-local-plain-backup-worker-v1":
        raise RuntimeError("root-bound worker plan differs")
    fd=os.open("/srv/ar-local/data/state/daily-ingest.lock",os.O_RDONLY|os.O_NOFOLLOW)
    if fd!=3: os.dup2(fd,3,inheritable=True); os.close(fd)
    else: os.set_inheritable(3,True)
    attempted=False
    try:
        # Fixed acquire launches the root-created private mount/PID sandbox and
        # waits with trusted stdlib-only host resource monitoring. Parent never
        # imports or executes producer code in its NNPfalse process.
        attempted=True
        helper("acquire",nonce)
        return 0
    finally:
        # If a worker left descendants, root finish refuses restoration. PID1's
        # independent stop-post then runs only after whole-group termination.
        if attempted: helper("finish",nonce)
        os.close(3)


if __name__=="__main__":
    try:
        if len(sys.argv)!=2: raise RuntimeError("nonce required")
        raise SystemExit(main(sys.argv[1]))
    except Exception as error:
        print(json.dumps({"result":"BLOCKED","error":type(error).__name__}))
        raise SystemExit(2)
