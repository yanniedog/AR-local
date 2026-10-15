"""Read-only publication subprocess with a whole-check deadline below systemd's 60s."""
from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys

CHECK_SECONDS = 35
MAX_RESULT_BYTES = 1024 * 1024


def unknown(category):
    return {"status": "UNKNOWN", "error_category": category,
            "publication_current": False, "publication_issues": ["publication_check_unverified"],
            "manifest_run_date": "", "dates_index_latest_date": "", "generated_at": "",
            "manifest_error": category, "dates_index_error": None}


def bounded_publication_check(day, *, run=None):
    """A socket timeout does not bound DNS, redirects or an entire response body."""
    run = run or subprocess.run
    try:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError("invalid date")
        completed = run([sys.executable, "-B", str(Path(__file__).resolve()), "--check", day],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=CHECK_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
        if completed.returncode or len(completed.stdout) > MAX_RESULT_BYTES:
            return unknown("PublicationCheckFailed")
        value = json.loads(completed.stdout)
        if not isinstance(value, dict) or type(value.get("publication_current")) is not bool:
            raise ValueError("invalid publication result")
        if value["publication_current"] and (
                value.get("manifest_run_date") != day or value.get("dates_index_latest_date") != day
                or value.get("manifest_error") is not None or value.get("dates_index_error") is not None
                or value.get("publication_issues") != []):
            raise ValueError("contradictory current result")
        return value
    except subprocess.TimeoutExpired:
        # subprocess.run kills and waits for this network-only Python child.
        return unknown("PublicationCheckTimeout")
    except (OSError, ValueError, TypeError):
        return unknown("PublicationCheckInvalid")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or argv[0] != "--check":
        raise ValueError("read-only publication check requires one date")
    day = argv[1]
    if date.fromisoformat(day).isoformat() != day:
        raise ValueError("invalid date")
    repo = Path(os.environ.get("AR_LOCAL_CODE_ROOT", Path(__file__).resolve().parent))
    sys.path.insert(0, str(repo))
    from pi_payload_freshness import check_publication
    print(json.dumps(check_publication(day), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
