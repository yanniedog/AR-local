"""Integrity manifests + continuity verification for the permanent CDR ledger.

Provides tamper-evidence and missing-day/gap detection over the immutable daily
partitions, per the Permanent CDR Ledger Invariant (audit Section 2 / Phase 0A).

Each finalized day gets an integrity manifest recording the SHA-256 of every file
in its ``_exports`` partition, the banking rate count, and a hash-chain link to the
previous day's manifest. Known gaps (e.g. 2026-05-14) are recorded as explicit gap
manifests in the chain — never fabricated from later data.

Manifests are DERIVED metadata stored beside the daily completion markers (the
state dir), separate from the immutable ledger bytes they describe. (Re)generating
them never mutates ledger data. True off-device tamper-anchoring is an operational
follow-up; this module makes accidental change / corruption / loss / gap-fill
DETECTABLE against a stored baseline.

CLI:
    python -m cdr_ledger_integrity build    # (re)generate the manifest chain
    python -m cdr_ledger_integrity verify   # exit non-zero on any integrity finding
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

from ar_local_pi_runtime import (
    data_runs_root,
    data_state_root,
    load_exports_manifest,
    manifest_banks_rate_count,
)

# Ledger epoch and the explicit, must-never-be-fabricated gaps.
LEDGER_EPOCH = "2026-05-13"
KNOWN_GAPS = ("2026-05-14",)

_DATE_FMT = "%Y-%m-%d"


def local_date() -> str:
    return datetime.now().strftime(_DATE_FMT)


def _validate_range(epoch: str, today: str) -> None:
    """Reject an inverted range early so it can't masquerade as an empty chain."""
    start = datetime.strptime(epoch, _DATE_FMT).date()
    end = datetime.strptime(today, _DATE_FMT).date()
    if end < start:
        raise ValueError(f"ledger range inverted: today ({today}) is before epoch ({epoch})")


def iter_ledger_dates(epoch: str, today: str) -> Iterable[str]:
    """Yield every YYYY-MM-DD from ``epoch`` to ``today`` inclusive."""
    start = datetime.strptime(epoch, _DATE_FMT).date()
    end = datetime.strptime(today, _DATE_FMT).date()
    day = start
    while day <= end:
        yield day.strftime(_DATE_FMT)
        day += timedelta(days=1)


def _write_json_atomic(path: Path, data: dict) -> None:
    """Write JSON via a temp file + rename so an interrupt can't leave half a file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def export_root_for(runs_root: Path, date: str) -> Path:
    return (runs_root / date / "_exports").resolve()


def manifest_path(state_dir: Path, date: str) -> Path:
    return state_dir / f"{date}.integrity.json"


def _export_root_has_content(root: Path) -> bool:
    return root.is_dir() and any(root.iterdir())


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_export_root(export_root: Path) -> list[dict]:
    """Sorted [{path, sha256, size}] for every file under ``export_root``."""
    files = []
    for path in sorted(p for p in export_root.rglob("*") if p.is_file()):
        rel = path.relative_to(export_root).as_posix()
        files.append({"path": rel, "sha256": hash_file(path), "size": path.stat().st_size})
    return files


def row_count(export_root: Path) -> int:
    manifest = load_exports_manifest(export_root)
    return manifest_banks_rate_count(manifest) if manifest else 0


def chain_sha(record: dict) -> str:
    """Stable hash over the chain-relevant fields (excludes volatile computed_at).

    Includes prev_sha so altering any earlier link cascades through every later
    day's sha — a proper hash chain.
    """
    payload = {
        "date": record.get("date"),
        "gap": bool(record.get("gap")),
        "files": record.get("files") or [],
        "row_count": record.get("row_count", 0),
        "prev_sha": record.get("prev_sha"),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def compute_record(runs_root: Path, date: str, prev_sha: Optional[str], known_gaps: set[str]) -> dict:
    """Build the integrity record for one ledger date (gap or finalized).

    ``known_gaps`` is a set materialized once by the caller (cheap membership in
    the per-date loop).
    """
    export_root = export_root_for(runs_root, date)
    if date in known_gaps:
        return {
            "date": date,
            "gap": True,
            "files": [],
            "row_count": 0,
            "prev_sha": prev_sha,
            "computed_at": datetime.now().isoformat(timespec="seconds"),
        }
    return {
        "date": date,
        "gap": False,
        "files": hash_export_root(export_root),
        "row_count": row_count(export_root),
        "prev_sha": prev_sha,
        "computed_at": datetime.now().isoformat(timespec="seconds"),
    }


def build_chain(
    runs_root: Path,
    state_dir: Path,
    epoch: str = LEDGER_EPOCH,
    today: Optional[str] = None,
    known_gaps: Iterable[str] = KNOWN_GAPS,
) -> dict:
    """Generate/refresh the integrity manifest chain from epoch to today.

    Skips dates with neither partition content nor a known-gap status (not yet
    finalized) so the chain only links real, present days. Returns a summary.
    """
    today = today or local_date()
    _validate_range(epoch, today)
    state_dir.mkdir(parents=True, exist_ok=True)
    gaps = set(known_gaps)
    prev_sha: Optional[str] = None
    written, skipped, gap_days = [], [], []
    for date in iter_ledger_dates(epoch, today):
        is_gap = date in gaps
        if not is_gap and not _export_root_has_content(export_root_for(runs_root, date)):
            skipped.append(date)
            continue
        record = compute_record(runs_root, date, prev_sha, gaps)
        _write_json_atomic(manifest_path(state_dir, date), record)
        prev_sha = chain_sha(record)
        (gap_days if is_gap else written).append(date)
    return {"written": written, "gaps": gap_days, "skipped": skipped, "head_sha": prev_sha}


def verify_chain(
    runs_root: Path,
    state_dir: Path,
    epoch: str = LEDGER_EPOCH,
    today: Optional[str] = None,
    known_gaps: Iterable[str] = KNOWN_GAPS,
) -> dict:
    """Verify partition integrity, continuity links, and gap status.

    Returns ``{"ok": bool, "findings": [...], "checked": int}``. Findings:
      MISSING_MANIFEST, BROKEN_CHAIN, CHANGED (file hashes differ from baseline),
      UNREADABLE, GAP_FABRICATED (content present at a known gap), MISSING_DAY.
    """
    today = today or local_date()
    _validate_range(epoch, today)
    gaps = set(known_gaps)
    findings: list[dict] = []
    prev_sha: Optional[str] = None
    checked = 0
    # Verify only through the latest FINALIZED day (has content, a manifest, or is
    # a known gap). Trailing days after it are not yet ingested (e.g. today before
    # the daily run) and must not be flagged MISSING_DAY (Gemini). Interior missing
    # days within the finalized span are still genuine gaps and are flagged.
    dates = list(iter_ledger_dates(epoch, today))
    latest = -1
    for i, date in enumerate(dates):
        if (
            date in gaps
            or _export_root_has_content(export_root_for(runs_root, date))
            or manifest_path(state_dir, date).is_file()
        ):
            latest = i
    for date in dates[: latest + 1]:
        is_gap = date in gaps
        export_root = export_root_for(runs_root, date)
        has_content = _export_root_has_content(export_root)
        path = manifest_path(state_dir, date)
        if not path.is_file():
            # A day with content but no manifest, or a known gap without a record.
            if has_content or is_gap:
                findings.append({"date": date, "issue": "MISSING_MANIFEST"})
            else:
                findings.append({"date": date, "issue": "MISSING_DAY"})
            continue
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            findings.append({"date": date, "issue": "UNREADABLE", "detail": "manifest"})
            continue
        checked += 1
        if stored.get("prev_sha") != prev_sha:
            findings.append({"date": date, "issue": "BROKEN_CHAIN"})
        if is_gap:
            if has_content:
                findings.append({"date": date, "issue": "GAP_FABRICATED"})
        else:
            try:
                current_files = hash_export_root(export_root) if has_content else []
            except OSError:
                findings.append({"date": date, "issue": "UNREADABLE", "detail": "partition"})
                prev_sha = chain_sha(stored)
                continue
            if not has_content:
                findings.append({"date": date, "issue": "MISSING_DAY"})
            elif current_files != (stored.get("files") or []):
                findings.append({"date": date, "issue": "CHANGED"})
        prev_sha = chain_sha(stored)
    return {"ok": not findings, "findings": findings, "checked": checked}


def _resolve_roots(args: argparse.Namespace) -> tuple[Path, Path]:
    repo_root = Path(__file__).resolve().parent
    runs_root = (args.runs.expanduser().resolve() if args.runs else data_runs_root(repo_root))
    state_dir = (args.state.expanduser().resolve() if args.state else data_state_root(repo_root))
    return runs_root, state_dir


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="CDR ledger integrity manifests + verification.")
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--runs", type=Path, default=None)
    parser.add_argument("--state", type=Path, default=None)
    parser.add_argument("--epoch", default=LEDGER_EPOCH)
    parser.add_argument("--today", default=None, help="Override end date YYYY-MM-DD")
    args = parser.parse_args(argv)
    if args.today is not None:
        try:
            datetime.strptime(args.today, _DATE_FMT)
        except ValueError:
            parser.error(f"invalid --today {args.today!r}; expected YYYY-MM-DD")
    runs_root, state_dir = _resolve_roots(args)
    if args.command == "build":
        summary = build_chain(runs_root, state_dir, args.epoch, args.today)
        print(json.dumps(summary, indent=2))
        return 0
    report = verify_chain(runs_root, state_dir, args.epoch, args.today)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
