"""Read immutable CDR observations and cache versioned full-history audit results."""
from __future__ import annotations

import json
import sqlite3
import zlib
from datetime import date
from pathlib import Path
from typing import Any

from cdr_export_contract import hash_file, load_contract
from cdr_ledger_v2 import verify_event
from cdr_quality_accounting import audit_rows, canonical_digest, rate_rows_digest, product_rows_digest
from cdr_quality_sqlite import database_files, database_view

# v2 adds shared product-detail equality and stronger file replacement identity.
# Cached v1 success did not prove that SQLite details matched publication JSON.
# v3 accepts valid negative RateString values; v4 accounts for evidenced TD reclassification.
# v5 binds source routing fields before deriving export/public coverage.
AUDIT_VERSION = 5


def read_object(path: Path) -> dict:
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError(f"metadata exceeds 32 MiB: {path.name}")
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError(f"object required: {path.name}")
    return result


def contained(root: Path, relative: str) -> Path:
    part = Path(relative)
    if not relative or part.is_absolute() or ".." in part.parts or "\\" in relative:
        raise ValueError("source path must be relative and contained")
    child = root / part
    for item in (child, *child.parents):
        if item == root:
            break
        if item.is_symlink():
            raise ValueError("source path cannot traverse symlinks")
    child.resolve().relative_to(root.resolve())
    return child


def inventory(data_root: Path) -> tuple[list[dict], list[dict]]:
    """Include every contract plus legacy primary/revision/archive/failed export."""
    sources, errors, seen = [], [], set()
    state = data_root / "state"
    for path in sorted((state / "export-contracts-v2").glob("*/*.json")):
        try:
            contract = load_contract(path)
            root = contained(data_root, contract["source_path"])
            sources.append({"key": contract["source_path"], "root": root,
                            "run_date": contract["observation_date"], "contract": contract})
            seen.add(root)
        except (OSError, ValueError, KeyError) as exc:
            errors.append({"code": "INVALID_CONTRACT", "path": str(path), "detail": str(exc)})
    candidates = set((data_root / "runs").rglob("_exports"))
    archive = data_root / "runs-archive"
    if archive.is_dir():
        candidates.update(archive.rglob("_exports"))
    for root in sorted(candidates):
        if root in seen:
            continue
        try:
            root = contained(data_root, root.relative_to(data_root).as_posix())
        except ValueError as exc:
            errors.append({"code": "UNSAFE_RETAINED_EXPORT", "path": str(root), "detail": str(exc)})
            continue
        dates = []
        for part in root.relative_to(data_root).parts:
            try:
                dates.append(date.fromisoformat(part).isoformat())
            except ValueError:
                pass
        if not dates:
            errors.append({"code": "UNDATED_RETAINED_EXPORT", "path": str(root)})
            continue
        sources.append({"key": root.relative_to(data_root).as_posix(), "root": root,
                        "run_date": dates[0], "contract": None,
                        "failed_attempt": "_failed_attempts" in root.parts})
    return sorted(sources, key=lambda s: (s["run_date"], s["key"])), errors


def source_files(source: dict) -> list[tuple[Path, dict | None]]:
    root, contract = source["root"], source["contract"]
    names = ["local-cdr.sqlite", f"banks-{source['run_date']}.sqlite", "ingest-status.json",
             "failures.txt", "ingest-failures.json", "ingest-errors.json",
             f"dashboard-cache/{source['run_date']}/banks.json"]
    paths = {contained(root, name) for name in names if (root / name).is_file()}
    for db in (root / "local-cdr.sqlite", root / f"banks-{source['run_date']}.sqlite"):
        paths.update(database_files(db))
    if contract:
        records = {contained(root, row["path"]): row for row in contract["artifacts"]}
        for path in paths - records.keys():
            # SHM and empty journals do not add database content. Any other
            # newly introduced audit input must not inherit contract-bound proof.
            if path.name.endswith("-shm") or (path.name.endswith(("-wal", "-journal")) and path.stat().st_size == 0):
                continue
            raise ValueError(f"audit input is not bound by export contract: {path.name}")
        return [(path, records.get(path)) for path in sorted(records.keys() | paths)]
    return [(path, None) for path in sorted(paths)]


def stat_fingerprint(source: dict) -> str:
    values = []
    for path, _ in source_files(source):
        stat = path.stat()
        values.append([str(path.relative_to(source["root"])), *stat_identity(stat)])
    return canonical_digest([AUDIT_VERSION, (source["contract"] or {}).get("contract_digest"), values])


def stat_identity(info) -> tuple[int, ...]:
    """Detect replacements even when retained size and modification time match."""
    return info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_dev, info.st_ino


def verify_source(data_root: Path, source: dict) -> dict:
    contained(data_root, source["root"].relative_to(data_root).as_posix())
    contract = source["contract"]
    if contract:
        event_path = data_root / "state/ledger-v2/events" / source["run_date"] / f"{contract['generation_id']}.json"
        event = read_object(event_path)
        verify_event(data_root / "state", event)
        if event["contract_digest"] != contract["contract_digest"]:
            raise ValueError("ledger contract identity mismatch")
    total, hashes = 0, {}
    for path, record in source_files(source):
        if not path.is_file() or path.is_symlink():
            raise ValueError("required source artifact missing or linked")
        digest = hash_file(path)
        if record and (digest != record["sha256"] or path.stat().st_size != record["bytes"]):
            raise ValueError(f"artifact binding mismatch: {path.name}")
        total += path.stat().st_size
        hashes[path.relative_to(source["root"]).as_posix()] = digest
    return {"contract_bound": contract is not None, "files": len(hashes), "bytes": total,
            "artifact_set_sha256": canonical_digest(hashes)}


def read_database(root: Path, run_date: str) -> tuple[list[dict], list[dict], dict]:
    paths = [p for p in (root / "local-cdr.sqlite", root / f"banks-{run_date}.sqlite") if p.is_file()]
    if len(paths) != 1:
        raise ValueError("one finalized daily SQLite database is required")
    path = paths[0]
    with database_view(path) as (db, snapshot):
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        checks = {name: [tuple(row) for row in db.execute(f"PRAGMA {name}")]
                  for name in ("quick_check", "integrity_check", "foreign_key_check")}
        if checks["quick_check"] != [("ok",)] or checks["integrity_check"] != [("ok",)] or checks["foreign_key_check"]:
            raise ValueError("SQLite integrity check failed")
        products = [dict(row) for row in db.execute("SELECT * FROM bank_products WHERE run_date=?", (run_date,))]
        rates = [dict(row) for row in db.execute("SELECT * FROM bank_rates WHERE run_date=?", (run_date,))]
        for product in products:
            product.pop("id", None)
        for row in rates:
            row.pop("id", None)
        rows = db.execute("SELECT run_date FROM runs").fetchall()
        if run_date not in {r[0] for r in rows}:
            raise ValueError("database does not contain its observation date")
    return products, rates, {"sha256": snapshot["source_sha256"], "integrity": "PASS", "path": path.name, **snapshot}


def audit_source(data_root: Path, source: dict) -> dict:
    before = stat_fingerprint(source)
    binding = verify_source(data_root, source)
    products, rates, database = read_database(source["root"], source["run_date"])
    # The compact SQLite rate table omits category and rate_index. Reconcile
    # shared financial fields first; audit the richer JSON only after that.
    result = None
    json_path = source["root"] / "dashboard-cache" / source["run_date"] / "banks.json"
    if json_path.is_file():
        if json_path.stat().st_size > 512 * 1024 * 1024:
            raise ValueError("JSON export exceeds 512 MiB audit budget")
        exported = json.loads(json_path.read_bytes())
        exported_products, exported_rates = exported.get("products") or [], exported.get("rates") or []
        if (len(exported_products) != len(products) or len(exported_rates) != len(rates)
                or sorted(p.get("product_key") or "" for p in products) != sorted(p.get("product_key") or "" for p in exported_products)
                or product_rows_digest(exported_products) != product_rows_digest(products)
                or rate_rows_digest(exported_rates, sqlite_fields=True) != rate_rows_digest(rates, sqlite_fields=True)):
            raise ValueError("SQLite rows and publication JSON export do not reconcile")
        result = audit_rows(exported_products, exported_rates)
        result["sqlite_to_export"] = {"status": "PASS", "json_sha256": hash_file(json_path)}
    else:
        product_category = {(p.get("dataset"), p.get("product_key")): p.get("category") for p in products}
        for row in rates:
            row["category"] = product_category.get((row.get("dataset"), row.get("product_key")))
        result = audit_rows(products, rates)
        result["sqlite_to_export"] = {"status": "UNVERIFIED", "reason": "retained JSON export missing"}
    status_path = source["root"] / "ingest-status.json"
    status = read_object(status_path) if status_path.is_file() else {}
    # All provider/failure summaries are retained. Full raw journals remain bound
    # by the contract and can be inspected for every issue; do not truncate them.
    fields = ("provider_states", "index_diagnostics", "providers_attempted", "providers_registered",
              "by_failure_category", "by_phase", "by_provider", "by_provider_failure_category",
              "by_status", "by_retryable", "total", "failure_provenance_complete",
              "register_provenance_complete", "corrupt_records", "unattributed_records",
              "unresolved_requests", "unresolved_requests_complete", "raw_attempt_journal")
    result.update({"key": source["key"], "run_date": source["run_date"], "binding": binding,
                   "database": database, "status": {k: status[k] for k in fields if k in status},
                   "generation_id": (source["contract"] or {}).get("generation_id"),
                   "observation_state": (source["contract"] or {}).get("observation_state", "legacy_unverified"),
                   "contract_digest": (source["contract"] or {}).get("contract_digest"),
                   "fingerprint": before})
    if stat_fingerprint(source) != before:
        raise ValueError("source changed during audit")
    return result


class AuditIndex:
    """Derived and rebuildable; never writes to any historical observation DB."""
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise ValueError("derived audit index cannot be a symlink")
        self.db = sqlite3.connect(path, timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS audits (source_key TEXT PRIMARY KEY, run_date TEXT NOT NULL, fingerprint TEXT NOT NULL, version INTEGER NOT NULL, result BLOB NOT NULL)")
        self.db.execute("CREATE INDEX IF NOT EXISTS audits_date ON audits(run_date)")

    def get(self, key: str, fingerprint: str) -> dict | None:
        row = self.db.execute("SELECT result FROM audits WHERE source_key=? AND fingerprint=? AND version=?",
                              (key, fingerprint, AUDIT_VERSION)).fetchone()
        if row is None:
            return None
        try:
            decoder = zlib.decompressobj()
            raw = decoder.decompress(row[0], 128 * 1024 * 1024)
            if not decoder.eof or decoder.unused_data:
                return None
            result = json.loads(raw)
            if (not isinstance(result, dict) or result.get("key") != key
                    or result.get("fingerprint") != fingerprint):
                return None
            return result
        except (ValueError, UnicodeError, zlib.error):
            # The cache is disposable. Re-audit source bytes after corruption;
            # never let a damaged cache stand in for original observation proof.
            return None

    def put(self, result: dict) -> None:
        body = json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.db.execute("INSERT OR REPLACE INTO audits VALUES(?,?,?,?,?)",
                        (result["key"], result["run_date"], result["fingerprint"], AUDIT_VERSION, zlib.compress(body)))
        self.db.commit()

    def close(self) -> None:
        self.db.close()
