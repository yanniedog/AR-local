"""Small, strict evidence contract for the operator-approved D-027 activation."""
from __future__ import annotations

import hashlib
import json
import re
import stat
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SCHEMA = "ar-local-quality-activation-v1"
CANARY_SCHEMA = "ar-local-quality-canary-v1"
SHA = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")


def sha(path: Path) -> str:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or path.resolve() != path:
        raise ValueError("evidence must be a canonical, unique regular file")
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read(path: Path) -> dict:
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("evidence JSON exceeds 64 MiB")
    sha(path)
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("evidence must be a JSON object")
    return value


def record(path: Path) -> dict:
    return {"path": str(path), "sha256": sha(path)}


def checked(entry: dict) -> Path:
    path = Path(entry["path"])
    if not path.is_absolute() or not SHA.fullmatch(str(entry.get("sha256", ""))) or sha(path) != entry["sha256"]:
        raise ValueError("evidence hash mismatch")
    return path


def relative(root: Path, name: str) -> Path:
    path = Path(name)
    if path.is_absolute() or not path.parts or any(p in {"..", "."} for p in path.parts) or "\\" in name:
        raise ValueError("unsafe manifest relative path")
    result = root / path
    if result.resolve() != result or any(p.is_symlink() for p in (result, *result.parents)):
        raise ValueError("manifest path traverses a symlink")
    return result


def junit_result(path: Path) -> dict:
    sha(path)
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    if not suites or root.tag not in {"testsuite", "testsuites"}:
        raise ValueError("complete pytest JUnit result required")
    counts = {key: sum(int(s.get(key, "0")) for s in suites) for key in ("tests", "failures", "errors", "skipped")}
    cases = sum(len(s.findall("testcase")) for s in suites)
    if (counts["tests"] != cases or cases < 1 or counts["failures"] or counts["errors"]
            or cases <= counts["skipped"] or any(s.findall(".//failure") or s.findall(".//error") for s in suites)):
        raise ValueError("pytest result is failed, empty or incomplete")
    return {"result": "PASS", **counts, **record(path)}


def ci_binding(value: dict, target: str) -> None:
    """An exported exact-head gate audit; its raw evidence is also hash-bound."""
    if (value.get("result") != "PASS" or value.get("repository") != "yanniedog/AR-local"
            or value.get("merge_commit") != target or not COMMIT.fullmatch(str(value.get("head_commit", "")))
            or value.get("base") != "main" or value.get("merged") is not True
            or value.get("review_dispositions_complete") is not True):
        raise ValueError("missing exact merged-main CI/review binding")
    checks = value.get("required_checks") or {}
    if not checks or checks.get("bot-feedback-gate") != "SUCCESS" or any(v != "SUCCESS" for v in checks.values()):
        raise ValueError("all required exact-head checks must pass")
    if not value.get("evidence"):
        raise ValueError("raw gate/review evidence is required")
    for entry in value["evidence"].values():
        checked(entry)
    from pi_cdr_quality_activate_checks import producer_checks
    producer_checks(value, target)


def app_binding(value: dict, target: str, canary: dict) -> None:
    if (value.get("result") != "PASS" or value.get("producer_commit") != target
            or not COMMIT.fullmatch(str(value.get("app_commit", "")))
            or value.get("revision_protocol") != 1):
        raise ValueError("app acceptance must bind the candidate and revision reader")
    for name in ("mobile_ci", "revision_reader", "headless_audit"):
        entry = value.get(name) or {}
        if entry.get("result") != "PASS":
            raise ValueError(f"app acceptance missing {name}")
        checked(entry)
    from pi_cdr_quality_activate_checks import app_checks
    app_checks(value, canary)


def historical_issue(issue: dict, report: dict) -> bool:
    """Only known legacy data gaps qualify; control-plane corruption never does."""
    code = issue.get("code")
    source = str(issue.get("source") or issue.get("path") or "").replace("\\", "/")
    if code in {"MISSING_TAXONOMY_ROWS", "DUPLICATE_PRODUCT_KEYS"}:
        match = re.fullmatch(r"runs/(\d{4}-\d{2}-\d{2})/_exports", source)
        observed = next((row for row in report.get("sources", []) if row.get("key") == source), {})
        if not observed or observed.get("binding", {}).get("contract_bound") is not False:
            return False
    elif code == "UNDATED_RETAINED_EXPORT":
        match = re.search(r"/runs-archive/_broken-(\d{4}-\d{2}-\d{2})-empty/_exports$", source)
    elif code == "SOURCE_AUDIT_FAILED" and issue.get("detail") == "one finalized daily SQLite database is required":
        match = re.fullmatch(r"runs/(\d{4}-\d{2}-\d{2})/_failed_attempts/[^/]+/exports/_exports", source)
    else:
        return False
    return bool(match and date.fromisoformat(match[1]) < date.fromisoformat(report["run_date"]))


def source_acceptance(report: dict, generation: str, dispositions: dict) -> None:
    from cdr_quality_accounting import canonical_digest
    if report.get("capture", {}).get("status") != "PASS" or report["capture"].get("generation_id") != generation:
        raise ValueError("current canary source is not verified")
    if report.get("ledger", {}).get("ok") is not True or report["ledger"].get("findings"):
        raise ValueError("ledger integrity cannot be waived as a historical finding")
    current = next((row for row in report.get("sources", []) if row.get("generation_id") == generation), None)
    if not current or current.get("sqlite_to_export", {}).get("status") != "PASS":
        raise ValueError("current SQLite-to-export reconciliation missing")
    issues = report.get("issues", [])
    if any(row.get("source") == current["key"] or row.get("code") in {
            "NO_VERIFIED_CURRENT_OBSERVATION", "CURRENT_JSON_EXPORT_UNVERIFIED",
            "LEDGER_INTEGRITY", "INVALID_CONTRACT", "LOG_INCOMPLETE_OR_CHANGED", "LOG_UNREADABLE",
            "PREVIOUSLY_AUDITED_LOG_MISSING", "PREVIOUSLY_AUDITED_SOURCE_MISSING"} for row in issues):
        raise ValueError("current-source violations cannot be waived as historical findings")
    if any(not historical_issue(row, report) for row in issues):
        raise ValueError("issue is not an eligible earlier-day legacy finding")
    findings = {canonical_digest(row) for row in issues}
    if set(dispositions) != findings or any(not isinstance(v, str) or len(v.strip()) < 20 for v in dispositions.values()):
        raise ValueError("each source finding needs an exact, reasoned historical disposition")


def validate_manifest(path: Path, expected_hash: str, *, current: datetime | None = None) -> dict:
    if not SHA.fullmatch(expected_hash) or sha(path) != expected_hash:
        raise ValueError("activation manifest hash mismatch")
    value = read(path)
    if value.get("schema") != SCHEMA or value.get("authority") != "D-027":
        raise ValueError("D-027 activation manifest required")
    for key in ("target_commit", "previous_commit"):
        if not COMMIT.fullmatch(str(value.get(key, ""))):
            raise ValueError("exact candidate and predecessor commits required")
    now = current or datetime.now(timezone.utc)
    created = datetime.fromisoformat(value["created_at"])
    expires = datetime.fromisoformat(value["expires_at"])
    if created.tzinfo is None or expires.tzinfo is None or not created <= now < expires or expires - created > timedelta(hours=6):
        raise ValueError("activation intent expired or has an invalid lifetime")
    root = Path(value["source_root"])
    for key in ("source_root", "production_root", "data_root", "operation_root"):
        directory = Path(value[key])
        if not directory.is_absolute() or directory.resolve() != directory or not directory.is_dir():
            raise ValueError("canonical existing activation directories required")
    roots = [Path(value[k]) for k in ("source_root", "production_root", "data_root")]
    if any(a == b or a in b.parents or b in a.parents for i, a in enumerate(roots) for b in roots[i + 1:]):
        raise ValueError("candidate, production and data roots must be separate")
    operation = Path(value["operation_root"])
    if any(operation == p or p in operation.parents or operation in p.parents for p in roots[1:]):
        raise ValueError("operation root must be outside production and data")
    if not value.get("source_files") or not value.get("changed_files") or not value.get("protected_files"):
        raise ValueError("source, changed-file and protected-data inventories required")
    for name, digest in value["source_files"].items():
        if sha(relative(root, name)) != digest:
            raise ValueError("candidate file inventory changed")
    for name, digest in value["changed_files"].items():
        source = relative(root, name)
        if (source.exists() if digest is None else not source.exists() or sha(source) != digest):
            raise ValueError("candidate changed-file inventory differs")
    for entry in value["evidence"].values():
        checked(entry)
    ci_binding(read(checked(value["evidence"]["ci"])), value["target_commit"])
    canary = read(checked(value["evidence"]["canary"]))
    app_binding(read(checked(value["evidence"]["app"])), value["target_commit"], canary)
    if (canary.get("schema") != CANARY_SCHEMA or canary.get("result") != "PASS"
            or canary.get("target_commit") != value["target_commit"]
            or canary.get("source_files") != value["source_files"]
            or canary.get("protected_files") != value["protected_files"]):
        raise ValueError("canary does not bind the exact source and current protected data")
    junit_result(checked(canary["tests"]))
    source_acceptance(read(checked(canary["source_audit"])), canary["generation_id"], canary["dispositions"])
    candidate = read(checked(canary["candidate_manifest"]))
    if candidate.get("run_date") != canary["run_date"]:
        raise ValueError("candidate payload date mismatch")
    from app_payload_revisions_state import RevisionError, validate_manifest as validate_payload
    try:
        validate_payload(candidate, checked(canary["candidate_manifest"]).parent)
    except RevisionError as error:
        raise ValueError(str(error)) from error
    return value
