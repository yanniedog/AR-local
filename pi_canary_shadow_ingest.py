#!/usr/bin/env python3
"""Produce an isolated shadow-ingest receipt for canary gate binding.

Never invents PASS. This script either:
  - emits a PREP/UNKNOWN receipt describing exact operator steps, or
  - validates an already-written isolated canary receipt and rewrites a
    canonical shadow-ingest-receipt.json for ``pi_canary_gate_bind.py``.

It does **not** activate production, mutate production ``--runs`` / ``--state``,
or disable the natural daily timer. Operators must run the isolated ingest
under ``/srv/ar-local/canary/<generation>/`` (shared Pi queue preferred).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

import re

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CANDIDATE_GENERATION_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class ShadowIngestError(ValueError):
    """Shadow ingest receipt cannot be written honestly."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> str:
    """Create-once publish; concurrent writers cannot overwrite via replace."""
    from cdr_atomic import ImmutablePathError, atomic_write_bytes

    if path.is_symlink():
        raise ShadowIngestError(f"refusing to write through symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(dict(payload), sort_keys=True, indent=2) + "\n").encode("utf-8")
    try:
        atomic_write_bytes(path, raw, create_once=True)
    except ImmutablePathError as exc:
        raise ShadowIngestError(str(exc)) from exc
    return hashlib.sha256(raw).hexdigest()


OPERATOR_STEPS = [
    "Confirm daylight outside Australia/Hobart 00:30–02:00 quiet window.",
    "Ensure shared queue idle: python3 /usr/local/lib/shared-pi-queue/pi_shared_queue.py status",
    "Create isolated tree: /srv/ar-local/canary/<generation>/"
    "{source,data/runs,data/state,data/archive-spool,config,evidence}",
    "Detach worktree at exact TARGET_SHA into canary source (do not switch production HEAD).",
    "Write isolated archive env at <canary>/config/day-archive.env with "
    "AR_LOCAL_DAY_ARCHIVE_SPOOL=<canary>/data/archive-spool, "
    "AR_LOCAL_DAY_ARCHIVE_REMOTE=<canary-only-remote>, and "
    "RCLONE_CONFIG=<canary>/config/rclone.conf "
    "(never copy /etc/ar-local/day-archive.env or production rclone remotes).",
    "Export AR_LOCAL_DATA_ROOT=<canary>/data, "
    "AR_LOCAL_DAY_ARCHIVE_ENV=<canary>/config/day-archive.env and "
    "AR_LOCAL_DAY_ARCHIVE_SPOOL=<canary>/data/archive-spool for the canary process only.",
    "Submit via pi-shared-task --project ar-local --resource ar-local --cpu-slots 1 "
    "--max-runtime <bounded> -- env AR_LOCAL_DATA_ROOT=<canary>/data "
    "AR_LOCAL_DAY_ARCHIVE_ENV=<canary>/config/day-archive.env "
    "AR_LOCAL_DAY_ARCHIVE_SPOOL=<canary>/data/archive-spool "
    "python3 <canary>/source/cdr_daily.py "
    "--runs <canary>/data/runs --state <canary>/data/state "
    "--ram-root /dev/shm/ar-local-canary-<generation> --banks-only --ram-stage",
    "Abort if production runs/state OR /var/lib/ar-local-day-archives mtimes change, "
    "or if /etc/ar-local/day-archive.env is read (env must be the canary file).",
    "On exit 0 with exports present, write receipt with gate=shadow_ingest, "
    "result=PASS, target_commit=TARGET_SHA, exit_code=0, exports_dirs=[...], "
    "candidate_generation=<generation>, and preservation_snapshot_sha256=<snap>.",
    "Canonicalize: python pi_canary_shadow_ingest.py canonicalize "
    "--source-receipt <raw> --output <canonical> --target-commit TARGET_SHA",
    "Bind only the canonicalize output: python pi_canary_gate_bind.py "
    "shadow-ingest --receipt <canonical> "
    "--candidate-generation <gen> --preservation-snapshot-sha256 <snap> ...",
]


def emit_template(
    output: Path,
    *,
    target_commit: str,
    candidate_generation: str,
) -> dict[str, Any]:
    if not COMMIT_RE.fullmatch(target_commit):
        raise ShadowIngestError("target_commit must be 40 lowercase hex")
    payload = {
        "schema_version": 1,
        "gate": "shadow_ingest",
        "target_commit": target_commit,
        "candidate_generation": candidate_generation,
        "result": "UNKNOWN",
        "completed_at": utc_now_iso(),
        "reason": "isolated shadow ingest not yet executed for this target_commit",
        "operator_steps": OPERATOR_STEPS,
        "canary_root_pattern": "/srv/ar-local/canary/<generation>",
        "forbidden": [
            "production activate / deploy",
            "mutating production --runs or --state",
            "leaving AR_LOCAL_DATA_ROOT on production while probing writability",
            "using /etc/ar-local/day-archive.env or /var/lib/ar-local-day-archives",
            "disabling ar-local-daily.timer",
            "fabricating PASS without exit 0 + exports",
        ],
    }
    digest = write_json_atomic(output, payload)
    return {"path": str(output), "sha256": digest, "result": "UNKNOWN"}


def validate_and_canonicalize(
    source_receipt: Path,
    output: Path,
    *,
    target_commit: str,
) -> dict[str, Any]:
    if not COMMIT_RE.fullmatch(target_commit):
        raise ShadowIngestError("target_commit must be 40 lowercase hex")
    if not source_receipt.is_file() or source_receipt.is_symlink():
        raise ShadowIngestError(f"source receipt missing: {source_receipt}")
    raw = json.loads(source_receipt.read_text(encoding="utf-8"))
    findings: list[str] = []
    if not isinstance(raw, dict):
        raw = {}
        findings.append("receipt must be a JSON object")
    if type(raw.get("schema_version")) is not int or raw.get("schema_version") != 1:
        findings.append("schema_version must be integer 1")
    source_gate = raw.get("gate")
    if source_gate != "shadow_ingest":
        findings.append(f"source gate mismatch: {source_gate!r} != 'shadow_ingest'")
    if raw.get("target_commit") != target_commit:
        findings.append(
            f"target_commit mismatch: {raw.get('target_commit')!r} != {target_commit!r}"
        )
    if not COMMIT_RE.fullmatch(str(raw.get("target_commit") or "")):
        findings.append("target_commit not 40 lowercase hex")
    status = raw.get("result") or raw.get("status")
    if status != "PASS":
        findings.append(f"result is {status!r}, not PASS")
    if type(raw.get("exit_code")) is not int or raw.get("exit_code") != 0:
        findings.append(f"exit_code must be integer 0, got {raw.get('exit_code')!r}")
    exports_raw = raw.get("exports_dirs", raw.get("exports", []))
    if exports_raw is None:
        exports: list[object] = []
    elif isinstance(exports_raw, list):
        exports = exports_raw
    else:
        findings.append(
            f"exports_dirs/exports must be a list, got {type(exports_raw).__name__}"
        )
        exports = []
    if status == "PASS" and (
        not exports
        or any(not isinstance(path, str) or not path.strip() for path in exports)
    ):
        findings.append("PASS requires non-empty exports_dirs/exports path evidence")
    generation = raw.get("candidate_generation")
    snapshot = raw.get("preservation_snapshot_sha256")
    if not isinstance(generation, str) or not CANDIDATE_GENERATION_RE.fullmatch(generation):
        findings.append(
            "PASS requires candidate_generation matching "
            "^[A-Za-z0-9._:-]{1,128}$"
        )
        generation = None
    if not isinstance(snapshot, str) or not SHA256_RE.fullmatch(snapshot):
        findings.append("PASS requires preservation_snapshot_sha256 (64 lowercase hex)")
        snapshot = None
    result = "PASS" if not findings else "FAIL"
    payload = {
        "schema_version": 1,
        "gate": "shadow_ingest",
        "target_commit": target_commit,
        "result": result,
        "completed_at": utc_now_iso(),
        "source_receipt": str(source_receipt),
        "source_sha256": sha256_file(source_receipt),
        "findings": findings,
        "exports_dirs": exports,
        "candidate_generation": generation,
        "preservation_snapshot_sha256": snapshot,
        "canary_root": raw.get("canary_root"),
        "exit_code": raw.get("exit_code"),
    }
    digest = write_json_atomic(output, payload)
    return {"path": str(output), "sha256": digest, "result": result, "findings": findings}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    t = sub.add_parser("template", help="Emit fail-closed UNKNOWN template + operator steps")
    t.add_argument("--output", type=Path, required=True)
    t.add_argument("--target-commit", required=True)
    t.add_argument("--candidate-generation", required=True)

    v = sub.add_parser("canonicalize", help="Validate live canary receipt → binder input")
    v.add_argument("--source-receipt", type=Path, required=True)
    v.add_argument("--output", type=Path, required=True)
    v.add_argument("--target-commit", required=True)
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "template":
        info = emit_template(
            args.output,
            target_commit=args.target_commit,
            candidate_generation=args.candidate_generation,
        )
        print(json.dumps(info, sort_keys=True))
        return 0
    if args.command == "canonicalize":
        info = validate_and_canonicalize(
            args.source_receipt,
            args.output,
            target_commit=args.target_commit,
        )
        print(json.dumps(info, sort_keys=True))
        return 0 if info["result"] == "PASS" else 1
    raise ShadowIngestError(f"unknown command {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ShadowIngestError as exc:
        print(f"pi_canary_shadow_ingest: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
