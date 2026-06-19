"""Off-device replication + restore verification for the permanent CDR ledger.

Phase 0A of the audit requires the immutable daily partitions to live on more than
one device, with a tested restore. This is the TOOL for that:

    python -m cdr_ledger_replicate replicate --dest /mnt/ledger-backup
    python -m cdr_ledger_replicate verify    --dest /mnt/ledger-backup

``replicate`` copies each integrity-baselined day's ``_exports`` to ``<dest>/<date>/
_exports`` (idempotent — a day whose replica already matches its integrity manifest
is skipped). ``verify`` re-hashes the replica and compares it to the SOURCE integrity
manifest, i.e. a restore drill: it proves the off-device copy is present and
byte-identical to the ledger baseline.

The operator supplies ``--dest`` (a mounted drive / NAS / rsync-mounted remote) and
schedules these (systemd timer / cron); this module is the tool, not the schedule or
the remote. Run ``cdr_ledger_integrity build`` first so days are baselined.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ar_local_pi_runtime import copytree_atomic, data_runs_root, data_state_root
from cdr_ledger_integrity import (
    KNOWN_GAPS,
    LEDGER_EPOCH,
    export_root_for,
    hash_export_root,
    iter_ledger_dates,
    local_date,
    manifest_path,
)


def _baselined_days(state_dir: Path, epoch: str, today: str):
    """Yield ``(date, manifest)`` for each day that has an integrity manifest."""
    for date in iter_ledger_dates(epoch, today):
        path = manifest_path(state_dir, date)
        if not path.is_file():
            continue
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        yield date, manifest


def replicate(
    runs_root: Path,
    state_dir: Path,
    dest: Path,
    *,
    epoch: str = LEDGER_EPOCH,
    today: Optional[str] = None,
) -> Dict[str, Any]:
    """Copy each baselined non-gap day's ``_exports`` to ``dest/<date>/_exports``.

    Idempotent: a day whose replica already matches its integrity manifest is
    skipped. Returns ``{copied, skipped, gaps, missing_source}``.
    """
    today = today or local_date()
    dest = Path(dest)
    copied: List[str] = []
    skipped: List[str] = []
    gaps: List[str] = []
    missing_source: List[str] = []
    for date, manifest in _baselined_days(state_dir, epoch, today):
        if manifest.get("gap"):
            gaps.append(date)  # an explicit gap day has no partition to replicate
            continue
        src = export_root_for(runs_root, date)
        if not src.is_dir():
            # Baselined but the source partition is gone — surface, never fabricate.
            missing_source.append(date)
            continue
        dst = dest / date / "_exports"
        if dst.is_dir() and hash_export_root(dst) == (manifest.get("files") or []):
            skipped.append(date)
            continue
        copytree_atomic(src, dst)
        copied.append(date)
    return {"copied": copied, "skipped": skipped, "gaps": gaps, "missing_source": missing_source}


def verify_replica(
    runs_root: Path,
    state_dir: Path,
    dest: Path,
    *,
    epoch: str = LEDGER_EPOCH,
    today: Optional[str] = None,
) -> Dict[str, Any]:
    """Restore drill: re-hash the replica and compare to the source integrity manifest.

    Returns ``{ok, checked, findings}``; findings: MISSING_REPLICA (no copy on dest),
    REPLICA_CHANGED (bytes differ from the baseline).
    """
    today = today or local_date()
    dest = Path(dest)
    findings: List[Dict[str, str]] = []
    checked = 0
    for date, manifest in _baselined_days(state_dir, epoch, today):
        if manifest.get("gap"):
            continue
        dst = dest / date / "_exports"
        if not dst.is_dir():
            findings.append({"date": date, "issue": "MISSING_REPLICA"})
            continue
        checked += 1
        try:
            current = hash_export_root(dst)
        except OSError:
            findings.append({"date": date, "issue": "UNREADABLE_REPLICA"})
            continue
        if current != (manifest.get("files") or []):
            findings.append({"date": date, "issue": "REPLICA_CHANGED"})
    return {"ok": not findings, "checked": checked, "findings": findings}


def _resolve_roots(args: argparse.Namespace) -> tuple[Path, Path]:
    repo_root = Path(__file__).resolve().parent
    runs_root = (args.runs.expanduser().resolve() if args.runs else data_runs_root(repo_root))
    state_dir = (args.state.expanduser().resolve() if args.state else data_state_root(repo_root))
    return runs_root, state_dir


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Replicate + verify the CDR ledger off-device.")
    parser.add_argument("command", choices=("replicate", "verify"))
    parser.add_argument("--dest", required=True, help="Destination root (mounted drive / NAS / remote mount).")
    parser.add_argument("--runs", type=Path, default=None)
    parser.add_argument("--state", type=Path, default=None)
    parser.add_argument("--epoch", default=LEDGER_EPOCH)
    parser.add_argument("--today", default=None, help="Override end date YYYY-MM-DD")
    args = parser.parse_args(argv)
    runs_root, state_dir = _resolve_roots(args)
    dest = Path(args.dest).expanduser().resolve()

    if args.command == "replicate":
        summary = replicate(runs_root, state_dir, dest, epoch=args.epoch, today=args.today)
        print(json.dumps(summary, indent=2))
        # A baselined day whose source partition vanished is a real integrity alarm.
        return 1 if summary["missing_source"] else 0

    report = verify_replica(runs_root, state_dir, dest, epoch=args.epoch, today=args.today)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
