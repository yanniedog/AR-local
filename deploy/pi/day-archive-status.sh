#!/bin/bash
set -euo pipefail
python3 - <<'PY'
import json
from pathlib import Path
spool = Path("/var/lib/ar-local-day-archives")
paths = (spool / "progress.jsonl", spool / "meta" / "progress.jsonl")
latest = {}
for path in paths:
    if not path.is_file():
        continue
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        day = row.get("date")
        if isinstance(day, str):
            latest[day] = row
passes = sorted(d for d, r in latest.items() if r.get("result") == "PASS")
fails = sorted(d for d, r in latest.items() if r.get("result") == "FAIL")
print(json.dumps({
    "pass_count": len(passes),
    "fail_count": len(fails),
    "last_pass": passes[-1] if passes else None,
    "fails": fails[:20],
}, indent=2))
PY
if pgrep -f 'pi_daily_cdr_day_archive.py --backfill' >/dev/null; then
  echo BACKFILL_RUNNING
else
  echo BACKFILL_STOPPED
fi
