"""Bounded private Linux resource fixture, never application acceptance data."""
import json
import os
from pathlib import Path
import resource
import sys
import time

mode, output = sys.argv[1], Path(sys.argv[2])
children = []
if mode in {"aggregate", "orphan"}:
    for _ in range(2):
        pid = os.fork()
        if pid == 0:
            os.setsid()
            blocks = []
            for _ in range(12 if mode == "aggregate" else 0):
                blocks.append(bytearray(2 * 1024**2))
                time.sleep(0.05)
            time.sleep(30)
            os._exit(0)
        children.append(pid)
output.write_text(json.dumps({"parent": os.getpid(), "children": children, "rlimit_as": resource.getrlimit(resource.RLIMIT_AS)}))
if mode == "aslimit":
    try:
        value = bytearray(128 * 1024**2)
    except MemoryError:
        print("RLIMIT_AS_BLOCKED", flush=True)
    else:
        raise RuntimeError("address-space bound was not enforced")
elif mode == "readonly":
    try:
        Path(__file__).with_name("unexpected-write-probe").write_text("read-only source proof failed")
    except OSError:
        print("SANDBOX_READONLY", flush=True)
    else:
        raise RuntimeError("fixture source was writable")
elif mode in {"aggregate", "timeout"}:
    time.sleep(30)
elif mode == "pass":
    time.sleep(0.4)
print("RESOURCE_FIXTURE_COMPLETED", flush=True)
