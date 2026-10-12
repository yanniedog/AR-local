"""Read-only ingest watchdog; never start capture, publication or recovery."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys


def observe(watchdog, now, read_selected):
    day = now.astimezone(watchdog.HOBART).date().isoformat()
    publication = watchdog.check_publication(day)
    result = {"observation_only": True, "run_date": day,
              "capture_finalized": read_selected(day) is not None,
              "service_active": watchdog.service_active(),
              "payload_pending": watchdog.payload_publication_pending(watchdog.REPO_ROOT),
              "publication": publication, "repair_started": False}
    return result


def main():
    repo = Path(os.environ.get("AR_LOCAL_CODE_ROOT", Path(__file__).resolve().parent))
    sys.path.insert(0, str(repo))
    import pi_daily_watchdog as watchdog
    from ar_local_pi_runtime import data_state_root
    from cdr_observation_selection import selected_observation
    try:
        result = observe(watchdog, datetime.now(timezone.utc),
                         lambda day: selected_observation(data_state_root(repo), day))
    except Exception as error:
        result = {"observation_only": True, "status": "UNKNOWN",
                  "error_category": type(error).__name__, "repair_started": False}
    print(json.dumps(result, sort_keys=True))
    return int(result.get("status") == "UNKNOWN" or
               (not result.get("service_active") and
                (not result.get("capture_finalized") or
                 result.get("publication", {}).get("publication_current") is not True)))


if __name__ == "__main__":
    raise SystemExit(main())
