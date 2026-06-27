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
    """Return ``(days, unreadable)`` over the days that have an integrity manifest.

    ``days`` is a list of ``(date, manifest)``; ``unreadable`` is a list of dates
    whose manifest file is present but truncated / malformed / unreadable. A
    present-but-unreadable baseline must NEVER be silently dropped — both callers
    surface it, so a corrupt baseline cannot let the backup report success while
    omitting a ledger day. (A manifest that simply does not exist is not baselined
    and is legitimately absent.)
    """
    days: List = []
    unreadable: List[str] = []
    for date in iter_ledger_dates(epoch, today):
        path = manifest_path(state_dir, date)
        if not path.is_file():
            continue
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            unreadable.append(date)
            continue
        days.append((date, manifest))
    return days, unreadable


def _replica_metadata_matches(dst: Path, expected_files: List[Dict[str, Any]]) -> bool:
    """Cheap, metadata-only check that ``dst`` already holds the baselined files.

    Compares file count + each file's relative path and size against the integrity
    manifest, WITHOUT reading file contents. Replication's job is to get the bytes
    onto the destination; full cryptographic re-hashing is the dedicated ``verify``
    drill's job. This keeps an idempotent re-run O(metadata) instead of O(bytes)
    over the (possibly remote) destination. Any I/O error answers "does not match"
    so the day is recopied rather than aborting the whole run.
    """
    try:
        actual = [p for p in dst.rglob("*") if p.is_file()]
    except OSError:
        return False
    if len(actual) != len(expected_files):
        return False
    for entry in expected_files:
        candidate = dst / entry["path"]
        try:
            if not candidate.is_file() or candidate.stat().st_size != entry["size"]:
                return False
        except OSError:
            return False
    return True


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
    days, unreadable_manifests = _baselined_days(state_dir, epoch, today)
    for date, manifest in days:
        if manifest.get("gap"):
            gaps.append(date)  # an explicit gap day has no partition to replicate
            continue
        src = export_root_for(runs_root, date)
        if not src.is_dir():
            # Baselined but the source partition is gone — surface, never fabricate.
            missing_source.append(date)
            continue
        dst = dest / date / "_exports"
        if dst.is_dir() and _replica_metadata_matches(dst, manifest.get("files") or []):
            skipped.append(date)
            continue
        copytree_atomic(src, dst)
        copied.append(date)
    return {
        "copied": copied,
        "skipped": skipped,
        "gaps": gaps,
        "missing_source": missing_source,
        "unreadable_manifests": unreadable_manifests,
    }


def verify_replica(
    runs_root: Path,
    state_dir: Path,
    dest: Path,
    *,
    epoch: str = LEDGER_EPOCH,
    today: Optional[str] = None,
) -> Dict[str, Any]:
    """Restore drill: re-hash the replica and compare to the source integrity manifest.

    Returns ``{ok, checked, findings}``; findings: UNREADABLE_MANIFEST (corrupt source
    baseline), MISSING_REPLICA (no copy on dest), REPLICA_CHANGED (bytes differ from
    the baseline), UNREADABLE_REPLICA (the replica could not be read back).
    """
    today = today or local_date()
    dest = Path(dest)
    days, unreadable_manifests = _baselined_days(state_dir, epoch, today)
    # A corrupt source baseline is itself a restore-drill failure.
    findings: List[Dict[str, str]] = [
        {"date": date, "issue": "UNREADABLE_MANIFEST"} for date in unreadable_manifests
    ]
    checked = 0
    for date, manifest in days:
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
        # A vanished source partition or a corrupt source baseline is a real alarm.
        return 1 if (summary["missing_source"] or summary["unreadable_manifests"]) else 0

    report = verify_replica(runs_root, state_dir, dest, epoch=args.epoch, today=args.today)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
