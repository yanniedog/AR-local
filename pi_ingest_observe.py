"""Read-only ingest watchdog; never start capture, publication or recovery."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import time


def observe(watchdog, now, read_selected, *, publication_check=None):
    from ar_local_ingest_schedule import latest_daily_due_utc, expected_run_date_for_due
    due = latest_daily_due_utc(now)
    day = expected_run_date_for_due(due)
    publication_started = time.monotonic()
    publication = (publication_check or watchdog.check_publication)(day)
    publication_seconds = round(time.monotonic() - publication_started, 3)
    result = {"observation_only": True, "run_date": day,
              "capture_finalized": read_selected(day) is not None,
              "capture_due": now >= due + timedelta(minutes=30),
              "publication_due": now >= due + timedelta(minutes=90),
              "service_active": watchdog.service_active(),
              "payload_pending": watchdog.payload_publication_pending(watchdog.REPO_ROOT),
              "publication": publication, "publication_check_seconds": publication_seconds,
              "repair_started": False}
    return result


def main():
    repo = Path(os.environ.get("AR_LOCAL_CODE_ROOT", Path(__file__).resolve().parent))
    sys.path.insert(0, str(repo))
    import pi_daily_watchdog as watchdog
    from ar_local_pi_runtime import data_state_root
    from cdr_observation_selection import selected_observation
    from pi_publication_observe import bounded_publication_check
    try:
        result = observe(watchdog, datetime.now(timezone.utc),
                         lambda day: selected_observation(data_state_root(repo), day),
                         publication_check=bounded_publication_check)
    except Exception as error:
        result = {"observation_only": True, "status": "UNKNOWN",
                  "error_category": type(error).__name__, "repair_started": False}
    print(json.dumps(result, sort_keys=True))
    return int(observation_failed(result))


def observation_failed(result):
    return (result.get("status") == "UNKNOWN"
            or (result.get("capture_due") and not result.get("service_active")
                and not result.get("capture_finalized"))
            or (result.get("publication_due")
                and result.get("publication", {}).get("publication_current") is not True))


if __name__ == "__main__":
    raise SystemExit(main())
