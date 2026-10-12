"""One current-day repair pass inside the supervised, once-only service."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


def repair(watchdog, recovery, day, now, read_pending=None):
    reason = recovery.recovery_block_reason(watchdog.REPO_ROOT, include_ingest_lock=False)
    if reason:
        return {"status": "blocked", "reason": reason}
    observation = recovery.selected_observation(recovery.data_state_root(watchdog.REPO_ROOT), day)
    if observation is None:
        return {"status": "blocked", "reason": "no_verified_current_day_capture; no blind full rerun"}
    pending = (read_pending or watchdog.read_payload_publication_pending)(watchdog.REPO_ROOT)
    if pending:
        pointer = pending.get("pointer", {})
        if (pending.get("run_date") != day or pointer.get("observation_date") != day
                or pending.get("queued_pointers") or pending.get("selection_retry")):
            return {"status": "blocked", "reason": "publication_scope_not_exclusively_today"}
        outcome = watchdog.run_payload_retry(False)
        return {"status": "publication_attempted", "outcome": outcome}
    return recovery.run_same_day_recovery(watchdog.REPO_ROOT, now_utc=now,
                                         dry_run=False, launch=watchdog.run_recovery_ingest)


def main():
    # No direct/manual worker execution outside the admission wrapper.
    receipt = Path(os.environ["AR_LOCAL_DAILY_REPAIR_RECEIPT"])
    now = datetime.now(timezone.utc)
    day = now.astimezone(ZoneInfo("Australia/Hobart")).date().isoformat()
    claim = json.loads(receipt.read_text())
    if (receipt != Path("/var/lib/ar-local-daily-repair") / (day + ".json")
            or claim["invocation"] != os.environ.get("INVOCATION_ID")
            or not any(line.endswith("/ar-local-queue-task-daily-repair.service")
                       for line in Path("/proc/self/cgroup").read_text().splitlines())):
        raise RuntimeError("worker is outside its claimed service invocation")
    repo = Path(os.environ.get("AR_LOCAL_REPO", Path(__file__).resolve().parent))
    sys.path.insert(0, str(repo))
    import pi_daily_watchdog as watchdog
    import pi_cdr_recovery as recovery
    from pi_daily_sync import read_payload_publication_pending
    result = repair(watchdog, recovery, day, now, read_payload_publication_pending)
    with receipt.with_suffix(".result.json").open("x", encoding="utf-8") as stream:
        json.dump({"date": day, "result": result}, stream); stream.flush(); os.fsync(stream.fileno())
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
