"""Protected live capture and independent register/source reconciliation."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from pi_cdr_quality_read_io import require_dropbehind_reads
from pi_live_financial_stage import verify_directory, verify_stage
from pi_cdr_quality_activate import clean_commit, read, record, relative, run, source_files, write, TZ


def brand_key(row):
    return tuple(str(row.get(k) or "").strip().lower() for k in ("endpoint_url", "brand_name", "legal_entity_name"))


def reconcile_register(exports, status):
    from cdr_ingest_support import iter_banking_brands_from_payload
    from cdr_attempt_evidence_promotion import verify_promoted_attempt_evidence
    if status.get("register_provenance_complete") is not True or status.get("failure_provenance_complete") is not True:
        raise ValueError("register/failure provenance is incomplete")
    attempts = status.get("register_attempts") or []
    expected = {r["sha256"] for r in attempts if r.get("ok") is True}
    if not expected:
        raise ValueError("successful register body digests required")
    journal = verify_promoted_attempt_evidence(exports, status["raw_attempt_journal"])
    found, brands = set(), set()
    for event in journal.evidence_records(recover=False):
        if event.get("context", {}).get("phase") != "register_discovery":
            continue
        if event["status"] != 200 or event["outcome"] != "success" or event["body_sha256"] not in expected:
            continue
        body = relative(journal.root, event["body_path"])
        if body.stat().st_size > 16 * 1024**2:
            raise ValueError("register response exceeds qualification budget")
        raw = body.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != event["body_sha256"]:
            raise ValueError("register response changed")
        found.add(digest)
        brands.update(brand_key(row) for row in iter_banking_brands_from_payload(json.loads(raw)))
    states = status.get("provider_states") or []
    observed = {brand_key(row) for row in states}
    if (found != expected or not brands or observed != brands or len(states) != len(brands)
            or status.get("providers_registered") != len(brands) or status.get("providers_attempted") != len(brands)):
        raise ValueError("not every discovered financial provider has exactly one attempted state")
    return {"registered": len(brands), "attempted": len(states), "register_body_sha256": sorted(found),
            "unresolved_requests": status.get("total"), "provider_states": states,
            "upstream_complete": not bool(status.get("incomplete"))}


def ingest_command(args, run_date, workers):
    from pi_live_financial_capture import ram_root
    op = args.operation
    # Match production's automatic Pi mode and observed staging filesystem.
    # Explicit --ram-stage also moves derived exports to RAM and is not equivalent.
    return [args.python, "-B", args.source / "cdr_daily.py", "--runs", op / "data/runs",
            "--state", op / "data/state", "--date", run_date, "--banks-only",
            "--ram-root", ram_root(args), "--archive-failed-ram-stage", "--workers", str(workers)]


@require_dropbehind_reads()
def worker(args):
    from pi_live_financial_capture import DATA, PRODUCTION, ram_root
    from cdr_quality_audit import audit
    op = args.operation
    if any(os.access(p, os.W_OK) for p in (args.source, DATA, PRODUCTION)):
        raise ValueError("live worker requires read-only source and production mounts")
    intent = read(op / "intent.json")
    if (intent["target_commit"] != args.expected_commit or intent["operation"] != str(op)
            or clean_commit(args.source) != args.expected_commit or source_files(args.source) != intent["before"]["source_files"]):
        raise ValueError("worker does not match exact launch source")
    args.stage_binding = intent["staging"]
    if args.stage_binding["profile"] != args.stage_profile:
        raise ValueError("worker staging profile differs from launch intent")
    stage_before = verify_directory(args.stage_binding)
    from ar_local_launcher_constants import DAILY_WORKER_COUNT
    from cdr_ingest_lib import parse_args
    detail_workers = parse_args([]).detail_workers
    run_date = datetime.now(TZ).date().isoformat()
    command = ingest_command(args, run_date, DAILY_WORKER_COUNT)
    run(command, timeout=args.runtime_seconds, output=op / "ingest.txt")
    marker = read(op / "data/state" / f"{run_date}.done.json")
    staging = verify_stage(marker, args.stage_binding)
    verify_directory(args.stage_binding)
    staging["before_capture_filesystem"] = stage_before
    exports = op / "data/runs" / run_date / "_exports"
    status = read(exports / "ingest-status.json")
    coverage = reconcile_register(exports, status)
    report = audit(op / "data", run_date, scrub=True, public=False, audit_root=op / "audit")
    if report["capture"]["status"] != "PASS" or report["issues"]:
        raise ValueError("fresh live capture did not pass source/ledger/SQLite accounting")
    archives = op / "data/archive-spool/meta/raw-progress.jsonl"
    rows = [json.loads(line) for line in archives.read_text().splitlines() if line.strip()]
    if not any(r.get("result") == "PASS" and r.get("generation_id") == report["capture"]["generation_id"] for r in rows):
        raise ValueError("matching local-only raw archive receipt missing")
    if clean_commit(args.source) != args.expected_commit or source_files(args.source) != intent["before"]["source_files"]:
        raise ValueError("source changed during live capture")
    audit_path = relative(op / "audit", read(op / "audit/latest.json")["path"])
    if read(audit_path) != report:
        raise ValueError("audit pointer does not identify the completed report")
    result = {"schema": "ar-local-live-financial-worker-v1", "result": "PASS", "target_commit": args.expected_commit,
              "run_date": run_date, "generation_id": report["capture"]["generation_id"], "coverage": coverage,
              "concurrency": {"workers": DAILY_WORKER_COUNT, "detail_workers": detail_workers}, "staging": staging,
              "ingest_status": record(exports / "ingest-status.json"), "archive_progress": record(archives),
              "audit_pointer": record(op / "audit/latest.json"), "audit": record(audit_path), "publication": "NOT_ATTEMPTED", "drive": "NOT_ATTEMPTED",
              "scope": "isolated full financial population attempted; upstream failures remain explicit"}
    write(op / "worker.json", result)
    return result
