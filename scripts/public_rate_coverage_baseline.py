"""Build a dated baseline from existing public JSON captures; no network I/O."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdr_atomic import atomic_write_json
from cdr_public_rates_coverage import coverage_baseline


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--register", type=Path, required=True)
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bodies = []
    for path, ceiling in ((args.register, 16 * 1024**2), (args.core, 64 * 1024**2)):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > ceiling:
            raise ValueError("public_baseline_capture_missing_or_oversized")
        body = path.read_bytes()
        if len(body) > ceiling:
            raise ValueError("public_baseline_capture_oversized")
        bodies.append(body)
    value = coverage_baseline(json.loads(bodies[0]), json.loads(bodies[1]),
        register_sha256=hashlib.sha256(bodies[0]).hexdigest(), core_sha256=hashlib.sha256(bodies[1]).hexdigest())
    atomic_write_json(args.output, value, create_once=True)
    print(json.dumps({"baselineRunDate": value["baselineRunDate"], "counts": value["counts"], "publication": "disabled"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
