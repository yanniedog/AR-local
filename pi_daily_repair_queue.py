"""Use the installed queue, retaining this repair invocation through its stop hook.

Only this process's unit allowlist changes; shared queue/health code stays intact.
"""
from pathlib import Path
import os
import sys

UNIT = "ar-local-queue-task-daily-repair.service"
QUEUE_ROOT = Path("/usr/local/lib/shared-pi-queue")


def main():
    if not any(line.endswith("/" + UNIT) for line in
               Path("/proc/self/cgroup").read_text().splitlines()):
        raise RuntimeError("repair queue adapter requires its exact service")
    sys.path.insert(0, str(QUEUE_ROOT))
    if sys.argv[1:] == ["--restore-dashboard"]:
        import pi_shared_queue_stop_hook as hook
        hook.FIXED_AR_UNITS = frozenset(hook.FIXED_AR_UNITS) | {UNIT}
        return hook.main()
    import pi_shared_queue as queue
    queue.FIXED_AR_UNITS = frozenset(queue.FIXED_AR_UNITS) | {UNIT}
    return queue.main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
