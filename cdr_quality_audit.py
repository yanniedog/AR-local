#!/usr/bin/env python3
"""Audit current CDR coverage in the context of every retained observation and ingest log.

Derived reports/index only; no ingest, source edits, repairs or publication occur
here. The 04:00 Codex owner uses this evidence for gated repairs. Exit 0 PASS,
1 WARN, 2 FAIL, 3 BLOCKED. A weekly --scrub re-hashes the entire retained history;
daily runs recheck every inventory and ledger binding and fully audit today's
sources. Cached prior source results always disclose their verification time.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ar_local_operation_lock import production_lock
from cdr_atomic import atomic_write_json
from cdr_ledger_v2 import verify_ledger
from cdr_observation_selection import selected_observation
from cdr_quality_history import history_context
from cdr_quality_logs import audit_logs
from cdr_quality_public import audit_public
from cdr_quality_sources import AuditIndex, audit_source, inventory, read_object, stat_fingerprint


def source_issues(result: dict) -> list[dict]:
    issues = []
    for key in ("duplicate_product_keys", "missing_product_keys", "invalid_rate_rows", "orphan_rate_rows",
                "malformed_product_details", "missing_taxonomy_rows"):
        value = result[key]
        if value:
            issues.append({"code": key.upper(), "source": result["key"],
                           "count": len(value) if isinstance(value, (list, dict)) else value})
    return issues


def collect_sources(data_root: Path, index: AuditIndex, run_date: str, scrub: bool,
                    verified_cache=None) -> tuple[list, list, int]:
    sources, issues = inventory(data_root)
    results, cached = [], 0
    for source in sources:
        try:
            fingerprint = stat_fingerprint(source)
            result = (verified_cache.get(data_root, source, run_date) if verified_cache else
                      index.get(source["key"], fingerprint) if not scrub and source["run_date"] != run_date else None)
            if result is None:
                print(f"[cdr-audit] checking {source['key']}", flush=True)
                result = audit_source(data_root, source)
                result["verified_at"] = datetime.now(timezone.utc).isoformat()
                index.put(result)
            else:
                cached += 1
                if verified_cache:
                    index.put(result)
            results.append(result)
            issues.extend(source_issues(result))
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, sqlite3.Error) as exc:
            issues.append({"code": "SOURCE_AUDIT_FAILED", "source": source["key"], "detail": str(exc)})
    old = {row[0] for row in index.db.execute("SELECT source_key FROM audits")}
    if verified_cache:
        old.update(verified_cache.manifest["entries"])
    for missing in sorted(old - {row["key"] for row in sources}):
        issues.append({"code": "PREVIOUSLY_AUDITED_SOURCE_MISSING", "source": missing})
    return results, issues, cached


def audit(data_root: Path, run_date: str, *, scrub: bool = False, public: bool = True,
          app_report: Path | None = None, audit_root: Path | None = None,
          verified_cache: Path | None = None, verified_cache_sha256: str | None = None) -> dict:
    if bool(verified_cache) != bool(verified_cache_sha256) or (verified_cache and not scrub):
        raise ValueError("verified cache requires its pinned SHA256 and a full byte scrub")
    if date.fromisoformat(run_date).isoformat() != run_date:
        raise ValueError("audit date must be YYYY-MM-DD")
    data_root = data_root.expanduser().resolve(strict=True)
    if not (data_root / "runs").is_dir() or not (data_root / "state").is_dir():
        raise ValueError("data root requires runs and state directories")
    requested_output = audit_root.expanduser().absolute() if audit_root else data_root / "state/quality-audit"
    if any(path.is_symlink() for path in (requested_output, *requested_output.parents)):
        raise ValueError("audit output cannot traverse symlinks")
    output = requested_output.resolve()
    if audit_root and output.is_relative_to(data_root):
        raise ValueError("custom audit root must be outside the source data root")
    # This is a separate derived-output lock, never the Pi production-operation
    # lock. Concurrent audits of the same index fail promptly; ingest continues.
    # The existing helper safely recovers a dead owner's lock after interruption.
    with production_lock(output / ".audit.lock", "cdr-quality-audit"):
        options = ({"verified_cache": verified_cache, "verified_cache_sha256": verified_cache_sha256}
                   if verified_cache else {})
        return _audit_locked(data_root, run_date, output=output, scrub=scrub,
                             public=public, app_report=app_report, **options)


def _audit_locked(data_root: Path, run_date: str, *, output: Path, scrub: bool,
                  public: bool, app_report: Path | None, verified_cache: Path | None = None,
                  verified_cache_sha256: str | None = None) -> dict:
    from cdr_quality_cache import VerifiedAuditCache
    cache = VerifiedAuditCache(verified_cache, verified_cache_sha256) if verified_cache else None
    index = None
    try:
        index = AuditIndex(output / "index.sqlite")
        results, issues, cached = (collect_sources(data_root, index, run_date, scrub, cache) if cache
                                   else collect_sources(data_root, index, run_date, scrub))
        ledger = verify_ledger(data_root / "state", verify_artifacts=False)
        issues.extend({"code": "LEDGER_INTEGRITY", **finding} for finding in ledger["findings"])
        logs = audit_logs(data_root, index, scrub=scrub)
        if cache:
            cache.verify_files()
    finally:
        if index is not None:
            index.close()
        if cache:
            cache.close()
    issues.extend(logs["errors"])
    for log in logs["files"]:
        if log["invalid_jsonl_lines"] or log["overlong_lines"] or not log["stable"]:
            issues.append({"code": "LOG_INCOMPLETE_OR_CHANGED", "path": log["path"]})
    selected = selected_observation(data_root / "state", run_date)
    generation = (selected or {}).get("contract", {}).get("generation_id")
    current = next((r for r in results if generation and r["generation_id"] == generation), None)
    if current is None:
        issues.append({"code": "NO_VERIFIED_CURRENT_OBSERVATION", "run_date": run_date})
    elif current["sqlite_to_export"]["status"] != "PASS":
        issues.append({"code": "CURRENT_JSON_EXPORT_UNVERIFIED"})
    publication = {"status": "BLOCKED", "reason": "no_current_source" if current is None else "public_check_disabled"}
    if current and public:
        try:
            publication = audit_public(current)
            issues.extend(publication["issues"])
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
            publication = {"status": "BLOCKED", "reason": str(exc)}
    consumer = read_object(app_report) if app_report else {"status": "BLOCKED", "reason": "shipping_app_audit_not_supplied"}
    if app_report and (consumer.get("run_date") != run_date or consumer.get("manifest_sha256") != publication.get("manifest_sha256")):
        consumer = {"status": "BLOCKED", "reason": "app_audit_does_not_bind_to_current_public_manifest"}
    history = history_context(results, current)
    warnings = []
    if any(not r["binding"]["contract_bound"] for r in results):
        warnings.append("legacy_sources_lack_original_contract_binding")
    if current and (current["observation_state"] != "complete" or current["status"].get("total")):
        warnings.append("current_upstream_coverage_incomplete")
    if history["missing_retained_dates"]:
        warnings.append("historical_calendar_gaps")
    if history["absent_since_previous_observed_day"]:
        warnings.append("product_membership_changes_require_disposition")
    status = "FAIL" if issues or consumer.get("status") == "FAIL" else "BLOCKED" if publication["status"] == "BLOCKED" or consumer["status"] == "BLOCKED" else "WARN" if warnings or consumer["status"] == "WARN" else "PASS"
    source_summaries = [{k: v for k, v in row.items() if k != "products"} for row in results]
    report = {"schema_version": 1, "audit_id": uuid.uuid4().hex, "audited_at": datetime.now(timezone.utc).isoformat(),
              "run_date": run_date, "status": status, "scrub": scrub, "cached_observations": cached,
              "capture": {"status": "PASS" if current else "FAIL", "generation_id": generation,
                          "coverage": current["accounting"] if current else None},
              "sources": source_summaries, "history": history, "ledger": ledger, "logs": logs,
              "publication": publication, "consumer": consumer, "issues": issues, "warnings": warnings,
              "backup": {"status": "UNVERIFIED", "receipt": "read independent Drive backup status; never inferred from ingest"}}
    if cache:
        report["verified_cache"] = {"manifest_sha256": verified_cache_sha256,
            "origin_commit": cache.manifest["origin"]["commit"],
            "origin_result": cache.manifest["origin"]["resource_result"],
            "reused_observations": cache.reused, "all_source_artifacts_rehashed": True}
    target = output / "reports" / run_date / f"{report['audit_id']}.json"
    atomic_write_json(target, report, create_once=True)
    atomic_write_json(output / "latest.json", {"schema_version": 1, "path": target.relative_to(output).as_posix(),
                                              "run_date": run_date, "status": status, "audit_id": report["audit_id"]})
    print(json.dumps({"status": status, "report": str(target), "sources": len(results), "cached": cached,
                      "issues": len(issues), "warnings": warnings}), flush=True)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--date", default=datetime.now(ZoneInfo("Australia/Hobart")).date().isoformat())
    parser.add_argument("--scrub", action="store_true")
    parser.add_argument("--no-public", action="store_true", help="Source-only diagnostic, never full acceptance")
    parser.add_argument("--app-audit", type=Path)
    parser.add_argument("--audit-root", type=Path, help="Optional isolated derived-output directory outside source data")
    parser.add_argument("--verified-cache", type=Path, help="Sealed historical calculations; requires --scrub and its SHA256")
    parser.add_argument("--verified-cache-sha256")
    args = parser.parse_args(argv)
    try:
        date.fromisoformat(args.date)
        report = audit(args.data_root, args.date, scrub=args.scrub, public=not args.no_public,
                       app_report=args.app_audit, audit_root=args.audit_root,
                       verified_cache=args.verified_cache, verified_cache_sha256=args.verified_cache_sha256)
        return {"PASS": 0, "WARN": 1, "FAIL": 2, "BLOCKED": 3}[report["status"]]
    except (OSError, ValueError, KeyError, RuntimeError, TypeError, sqlite3.Error) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
