"""Read immutable CDR observations and cache versioned full-history audit results."""
from __future__ import annotations

import json
import sqlite3
import stat
import time
import zlib
from datetime import date
from pathlib import Path
from typing import Any

from cdr_export_contract import hash_file as portable_hash_file, load_contract
from cdr_ledger_v2 import verify_event
from cdr_quality_accounting import audit_rows, canonical_digest, rate_rows_digest, product_rows_digest
from cdr_quality_sqlite import database_files, database_view
from pi_cdr_quality_digest import read_digest
from pi_cdr_quality_read_io import dropbehind_required

# v2 adds shared product-detail equality and stronger file replacement identity.
# Cached v1 success did not prove that SQLite details matched publication JSON.
# v3 accepts valid negative RateString values; v4 accounts for evidenced TD reclassification.
# v5 binds source routing fields before deriving export/public coverage.
AUDIT_VERSION = 5


def hash_file(path: Path, *, budget=None) -> str:
    """Use identity-bound required reads in supervised audit scopes only."""
    if dropbehind_required():
        return read_digest(path, budget=budget)[0].sha256
    return portable_hash_file(path, budget=budget)


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


def require_materialized_contract(source: dict) -> None:
    if "contract_ref" in source:
        raise ValueError("contract reference must be explicitly materialized before source auditing")


def _contract_identity(data_root: Path, relative: str) -> tuple[Path, list[int]]:
    path = contained(data_root, relative)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 16 * 1024**2:
        raise ValueError("contract must remain a bounded regular file")
    return path, [*stat_identity(info), info.st_mode, info.st_nlink]


def _contract_hash(path: Path) -> str:
    consumed = 0

    def budget(*, size=0, reserve_bytes=0, entries=0):
        nonlocal consumed
        if consumed + max(size, reserve_bytes) > 16 * 1024**2:
            raise ValueError("contract exceeds bounded read limit")
        consumed += size

    return hash_file(path, budget=budget)


def _read_pinned_contract(data_root: Path, relative: str, expected: dict | None = None) -> tuple[dict, dict]:
    path, before = _contract_identity(data_root, relative)
    digest = _contract_hash(path)
    if expected is not None and (before != expected["identity"] or digest != expected["sha256"]):
        raise ValueError("contract identity or bytes changed since inventory")
    contract = load_contract(path)  # Preserve the complete schema/generation/digest validation.
    if _contract_hash(path) != digest or _contract_identity(data_root, relative)[1] != before:
        raise ValueError("contract changed during inventory/materialization")
    reference = {"path": relative, "identity": before, "sha256": digest,
                 **{key: contract[key] for key in
                    ("source_path", "observation_date", "generation_id", "contract_digest")}}
    if expected is not None and reference != expected:
        raise ValueError("contract routing or digest changed since inventory")
    return contract, reference


def _inventory_contract(data_root: Path, path: Path) -> dict:
    # The full dictionary dies with this call, before the next contract is read.
    contract, reference = _read_pinned_contract(data_root, path.relative_to(data_root).as_posix())
    return {"key": contract["source_path"], "root": contained(data_root, contract["source_path"]),
            "run_date": contract["observation_date"], "contract_ref": reference}


def materialize_source(data_root: Path, source: dict) -> dict:
    """Resolve one pinned inventory entry without mutating the compact inventory."""
    if "contract_ref" not in source:
        return source  # Existing full-contract and genuinely legacy inputs retain their API.
    reference = source["contract_ref"]
    if (source["key"] != reference["source_path"] or source["run_date"] != reference["observation_date"]
            or source["root"] != contained(data_root, reference["source_path"])):
        raise ValueError("inventory source routing differs from its contract reference")
    contract, _ = _read_pinned_contract(data_root, reference["path"], reference)
    result = {key: value for key, value in source.items() if key != "contract_ref"}
    result["contract"] = contract
    return result


def verify_contract_reference(data_root: Path, source: dict) -> None:
    """Close the contract fence before accepting/caching a source calculation."""
    if "contract_ref" not in source:
        return
    reference = source["contract_ref"]
    path, before = _contract_identity(data_root, reference["path"])
    if (before != reference["identity"] or _contract_hash(path) != reference["sha256"]
            or _contract_identity(data_root, reference["path"])[1] != before):
        raise ValueError("contract changed during source audit")


def inventory(data_root: Path) -> tuple[list[dict], list[dict]]:
    """Validate every contract; return compact references plus every legacy export."""
    sources, errors, seen = [], [], set()
    state = data_root / "state"
    started = time.monotonic()
    print("[cdr-audit] inventory contracts start", flush=True)
    for path in sorted((state / "export-contracts-v2").glob("*/*.json")):
        print(f"[cdr-audit] inventory contract {path}", flush=True)
        try:
            source = _inventory_contract(data_root, path)
            sources.append(source)
            seen.add(source["root"])
        except (OSError, ValueError, KeyError) as exc:
            errors.append({"code": "INVALID_CONTRACT", "path": str(path), "detail": str(exc)})
    print(f"[cdr-audit] inventory contracts complete sources={len(sources)} errors={len(errors)} "
          f"elapsed_seconds={time.monotonic() - started:.3f}", flush=True)
    started = time.monotonic()
    print("[cdr-audit] inventory discovery start tree=runs", flush=True)
    candidates = set((data_root / "runs").rglob("_exports"))
    print(f"[cdr-audit] inventory discovery complete tree=runs candidates={len(candidates)} "
          f"elapsed_seconds={time.monotonic() - started:.3f}", flush=True)
    archive = data_root / "runs-archive"
    if archive.is_dir():
        started = time.monotonic()
        print("[cdr-audit] inventory discovery start tree=runs-archive", flush=True)
        candidates.update(archive.rglob("_exports"))
        print(f"[cdr-audit] inventory discovery complete tree=runs-archive candidates={len(candidates)} "
              f"elapsed_seconds={time.monotonic() - started:.3f}", flush=True)
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
    require_materialized_contract(source)
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
    require_materialized_contract(source)
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
