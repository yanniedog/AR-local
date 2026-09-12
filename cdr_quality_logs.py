"""Inventory and read every retained operational/failure log, caching unchanged bytes."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from cdr_quality_accounting import canonical_digest
from cdr_quality_sources import contained, stat_identity

ERROR_WORDS = re.compile(r"\b(error|failed|failure|exception|withheld|timeout|success|completed)\b", re.I)
MAX_LINE_BYTES = 16 * 1024 * 1024
LOG_AUDIT_VERSION = 2


def log_paths(data_root: Path) -> list[Path]:
    paths = set()
    for namespace in ("logs", "runs", "runs-archive", "state/ingest-failures", "state/cdr-recovery-v1",
                      "state/ingest-terminal", "state/ingest-terminal-v1", "state/ingest-executions"):
        root = data_root / namespace
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            name = path.name.lower()
            if namespace == "logs" or namespace.startswith("state/") or name.endswith((".log", ".jsonl")) or any(s in name for s in ("failure", "error")):
                paths.add(path)
    return sorted(paths)


def scan_log(path: Path) -> dict:
    if path.is_symlink():
        raise ValueError("log cannot be a symlink")
    before = path.stat()
    digest, words, categories = hashlib.sha256(), Counter(), Counter()
    lines, bad_json, overlong = 0, 0, 0
    structured = path.suffix.lower() == ".jsonl"
    with path.open("rb") as stream:
        while True:
            raw = stream.readline(MAX_LINE_BYTES + 1)
            if not raw:
                break
            digest.update(raw)
            lines += 1
            if len(raw) > MAX_LINE_BYTES:
                overlong += 1
                while raw and not raw.endswith(b"\n"):
                    raw = stream.readline(MAX_LINE_BYTES + 1)
                    digest.update(raw)
                continue
            text = raw.decode("utf-8", errors="replace")
            words.update(word.lower() for word in ERROR_WORDS.findall(text))
            if structured:
                try:
                    row = json.loads(raw)
                    if not isinstance(row, dict):
                        raise ValueError("object required")
                    for key in ("failure_category", "phase", "status", "outcome"):
                        value = row.get(key)
                        if isinstance(value, (str, int, bool)):
                            categories[f"{key}:{value}"] += 1
                except (ValueError, UnicodeError):
                    bad_json += 1
    after = path.stat()
    return {"sha256": digest.hexdigest(), "bytes": after.st_size, "lines": lines,
            "terms": dict(words), "structured_counts": dict(categories), "invalid_jsonl_lines": bad_json,
            "overlong_lines": overlong, "stable": stat_identity(before) == stat_identity(after)}


def audit_logs(data_root: Path, index, *, scrub: bool = False) -> dict:
    index.db.execute("CREATE TABLE IF NOT EXISTS log_audits (path TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL)")
    reports, errors, cached = [], [], 0
    for path in log_paths(data_root):
        key = path.relative_to(data_root).as_posix()
        try:
            contained(data_root, key)
            stat = path.stat()
            fingerprint = canonical_digest([LOG_AUDIT_VERSION, *stat_identity(stat)])
            prior = index.db.execute("SELECT fingerprint,result FROM log_audits WHERE path=?", (key,)).fetchone()
            if prior and prior[0] == fingerprint and not scrub:
                result = json.loads(prior[1])
                cached += 1
            else:
                result = scan_log(path)
                if result["stable"]:
                    index.db.execute("INSERT OR REPLACE INTO log_audits VALUES(?,?,?)", (key, fingerprint, json.dumps(result)))
                    index.db.commit()
            reports.append({"path": key, **result})
        except (OSError, ValueError) as exc:
            errors.append({"code": "LOG_UNREADABLE", "path": key, "detail": str(exc)})
    old = {r[0] for r in index.db.execute("SELECT path FROM log_audits")}
    for missing in sorted(old - {row["path"] for row in reports}):
        errors.append({"code": "PREVIOUSLY_AUDITED_LOG_MISSING", "path": missing})
    return {"files": reports, "errors": errors, "cached_files": cached,
            "failed_attempt_roots": sorted(str(p.relative_to(data_root)) for p in (data_root / "runs").glob("*/_failed_attempts/*") if p.is_dir())}
