"""Read-only public shadow review; never schedules, enables or publishes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdr_public_rates_publication import MAX_SHADOW_BYTES, validate_shadow_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--programme-id", action="append", required=True)
    args = parser.parse_args()
    try:
        path = args.report
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SHADOW_BYTES:
            raise ValueError("shadow_report_missing_or_oversized")
        report = json.loads(path.read_bytes())
        result = validate_shadow_report(report, set(args.programme_id))
    except (ValueError, OSError, TypeError, KeyError) as error:
        print(json.dumps({"status": "unresolved", "reasonCode": str(error), "activation": "not_performed"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
