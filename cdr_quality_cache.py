"""Seal completed source audits from a closed protected run; never promote its result.

The operator supplies the exact original checkout and attests that this operation
is closed. The seal records raw failed/successful run evidence, immutable Git
blobs, runtime identity and a standalone SQLite snapshot. A new protected run
pins the seal's SHA256 and rehashes every observation before using any result.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import json
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import zlib
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path

from cdr_atomic import atomic_write_json
from cdr_quality_sources import AUDIT_VERSION, stat_fingerprint, verify_source
from cdr_quality_sqlite import database_view
from pi_cdr_quality_activate_evidence import junit_result, read, relative, sha

SCHEMA = "ar-local-verified-audit-cache-v1"
RESULT_LIMIT = 128 * 1024 * 1024
REQUIRED_RESULT = {"key", "run_date", "fingerprint", "verified_at", "binding", "database",
                   "generation_id", "contract_digest", "observation_state", "accounting", "products",
                   "sqlite_to_export", "status", "duplicate_product_keys", "missing_product_keys",
                   "invalid_rate_rows", "orphan_rate_rows", "malformed_product_details", "missing_taxonomy_rows",
                   "provider_products", "published_rate_digests", "duplicate_exact_rate_rows"}


def git(source: Path, *args: str) -> bytes:
    return subprocess.run(["git", "--no-optional-locks", "-C", str(source), *args],
                          check=True, capture_output=True, timeout=30).stdout


def semantics(source: Path) -> dict:
    """Bind the complete local import closure plus the contract's schema data.

    These modules contain the unchanged full source audit, including rate
    filtering and SQLite recovery. The new cache/activation orchestration is
    deliberately outside the closure and cannot change a cached calculation.
    """
    pending, files = ["cdr_quality_sources.py"], {}
    while pending:
        name = pending.pop()
        if name in files:
            continue
        path = relative(source, name)
        files[name] = sha(path)
        tree = ast.parse(path.read_bytes(), filename=name)
        for node in ast.walk(tree):
            modules = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                       else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            for module in modules:
                candidate = module.replace(".", "/") + ".py"
                if (source / candidate).is_file() and candidate not in files:
                    pending.append(candidate)
    for name in ("contracts/export-contract-v2.schema.json", "requirements.txt"):
        files[name] = sha(relative(source, name))
    return dict(sorted(files.items()))


def runtime_identity() -> dict:
    packages = {}
    # Distribution names differ between supported system-Python jsonschema
    # generations. Absence is part of the identity, not a new install demand.
    for name in ("jsonschema", "attrs", "jsonschema-specifications", "referencing", "rpds-py", "pyrsistent"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {"python": platform.python_version(), "implementation": platform.python_implementation(),
            "platform": sys.platform, "sqlite": sqlite3.sqlite_version,
            "packages": packages}


def decode_result(blob: bytes, key: str, day: str, fingerprint: str) -> dict | None:
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(blob, RESULT_LIMIT)
        if not decoder.eof or decoder.unused_data:
            return None
        result = json.loads(raw)
        if (not isinstance(result, dict) or not REQUIRED_RESULT <= result.keys()
                or result["key"] != key or result["run_date"] != day or result["fingerprint"] != fingerprint
                or date.fromisoformat(day).isoformat() != day
                or datetime.fromisoformat(result["verified_at"]).tzinfo is None
                or result["database"].get("integrity") != "PASS"
                or not re.fullmatch(r"[0-9a-f]{64}", result["binding"].get("artifact_set_sha256", ""))):
            return None
        return result
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, zlib.error):
        return None


def file_record(path: Path) -> dict:
    return {"sha256": sha(path), "bytes": path.stat().st_size}


def worker_options(command: list[str]) -> dict:
    """Parse the actual unambiguous worker argv, including --option=value."""
    allowed = {"--source", "--production", "--data-root", "--operation", "--python",
               "--dispositions", "--verified-cache", "--verified-cache-sha256"}
    values, offset = {}, 4
    while offset < len(command):
        option, separator, value = command[offset].partition("=")
        offset += 1
        if option not in allowed or option in values:
            raise ValueError("unknown or duplicate original canary worker option")
        if not separator:
            if offset == len(command) or command[offset].startswith("--"):
                raise ValueError("original canary worker option has no value")
            value = command[offset]
            offset += 1
        if not value:
            raise ValueError("original canary worker option has no value")
        values[option] = value
    if not {"--source", "--production", "--data-root", "--operation", "--python"} <= values.keys():
        raise ValueError("complete original canary worker arguments required")
    return values


def origin_evidence(source: Path, operation: Path, expected_commit: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise ValueError("exact original commit required")
    if (git(source, "rev-parse", "HEAD").decode().strip() != expected_commit
            or git(source, "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none")):
        raise ValueError("original protected candidate must still be clean at the expected commit")
    resources = read(operation / "resources.json")
    command = resources.get("command")
    if (resources.get("result") not in {"FAIL", "PASS"} or resources.get("group_clean") is not True
            or not isinstance(command, list) or len(command) < 4
            or command[1:4] != ["-B", str(source / "pi_cdr_quality_activate.py"), "canary-worker"]
            or Path(command[0]).resolve() != Path(sys.executable).resolve()):
        raise ValueError("closed supervised original canary command required")
    options = worker_options(command)
    for option, value in (("--source", str(source)), ("--operation", str(operation))):
        if options[option] != value:
            raise ValueError("original canary command does not bind the supplied paths")
    if Path(options["--python"]).resolve() != Path(sys.executable).resolve():
        raise ValueError("original canary test interpreter differs from the sealing runtime")
    tests = junit_result(operation / "pytest.xml")
    files = semantics(source)
    blobs = {}
    for name in [*files, "pi_cdr_quality_activate.py"]:
        body = git(source, "show", expected_commit + ":" + name)
        if hashlib.sha256(body).hexdigest() != sha(relative(source, name)):
            raise ValueError("original validation source differs from its exact Git blob")
        blobs[name] = git(source, "rev-parse", expected_commit + ":" + name).decode().strip()
    return {"commit": expected_commit, "source": str(source), "operation": str(operation),
            "worker_options": options,
            "resource_result": resources["result"], "resource_reason": resources.get("reason"),
            "tests": {key: tests[key] for key in ("result", "tests", "failures", "errors", "skipped")},
            "semantics": files, "git_blobs": blobs, "runtime": runtime_identity(),
            "runtime_provenance": "measured_at_seal; operator_attests_unchanged_since_original_run"}


def seal_cache(source: Path, operation: Path, output: Path, expected_commit: str, *, attest_closed: bool) -> dict:
    if not attest_closed:
        raise ValueError("operator attestation of the closed protected origin is required")
    for path in (source, operation, output):
        if not path.is_absolute() or path.resolve() != path or any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError("canonical paths without symlinks required")
    if any(a == b or a in b.parents or b in a.parents
           for i, a in enumerate((source, operation, output)) for b in (source, operation, output)[i + 1:]):
        raise ValueError("cache output and origin directories must be separate")
    origin = origin_evidence(source, operation, expected_commit)
    evidence = {name: file_record(operation / name) for name in ("resources.json", "pytest.xml", "canary-service.txt")}
    output.mkdir(parents=True, exist_ok=False)
    for name in evidence:
        shutil.copyfile(operation / name, output / name)
        if file_record(output / name) != evidence[name] or file_record(operation / name) != evidence[name]:
            raise ValueError("origin evidence changed while sealing")
    # database_view recovers journals only in a verified private copy. SQLite
    # backup produces one complete DB; copying an index.sqlite alone loses WAL.
    destination = output / "index.sqlite"
    with database_view(operation / "source-audit/index.sqlite") as (original, _):
        with closing(sqlite3.connect(destination)) as snapshot:
            original.backup(snapshot)
            snapshot.execute("PRAGMA journal_mode=DELETE")
    entries, rejected = {}, 0
    with closing(sqlite3.connect(destination.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        if list(db.execute("PRAGMA integrity_check")) != [("ok",)]:
            raise ValueError("sealed audit index failed integrity check")
        for key, day, fingerprint, version, blob in db.execute("SELECT source_key,run_date,fingerprint,version,result FROM audits"):
            result = decode_result(blob, key, day, fingerprint) if version == AUDIT_VERSION else None
            if result is None:
                rejected += 1
                continue
            entries[key] = {"run_date": day, "fingerprint": fingerprint, "result_sha256": hashlib.sha256(blob).hexdigest()}
    if not entries:
        raise ValueError("origin has no complete exact-version source audits")
    # Close the provenance fence after reading the cache, not just before it.
    if (origin_evidence(source, operation, expected_commit) != origin
            or any(file_record(operation / name) != expected for name, expected in evidence.items())):
        raise ValueError("protected origin changed while sealing")
    manifest = {"schema": SCHEMA, "audit_version": AUDIT_VERSION, "origin": origin,
                "created_at": datetime.now(timezone.utc).isoformat(), "operator_attested_closed": True,
                "acceptance": "NONE; completed source calculations only; original run result remains unchanged",
                "index": file_record(destination), "evidence": evidence, "entries": entries,
                "rejected_entries": rejected}
    path = output / "manifest.json"
    atomic_write_json(path, manifest, create_once=True)
    return {"result": "SEALED", "manifest": str(path), "sha256": sha(path), "entries": len(entries),
            "rejected_entries": rejected, "origin_result": origin["resource_result"]}


class VerifiedAuditCache:
    """Hash-pinned immutable import; no writes to the originating cache or run."""
    def __init__(self, manifest_path: Path, expected_sha256: str, *, source_root: Path | None = None):
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256) or sha(manifest_path) != expected_sha256:
            raise ValueError("verified cache manifest hash mismatch")
        self.manifest = read(manifest_path)
        self.path, self.expected_sha256 = manifest_path, expected_sha256
        manifest = self.manifest
        origin = manifest["origin"]
        if (manifest.get("schema") != SCHEMA or manifest.get("audit_version") != AUDIT_VERSION
                or manifest.get("operator_attested_closed") is not True
                or not re.fullmatch(r"[0-9a-f]{40}", origin.get("commit", ""))
                or origin.get("semantics") != semantics(source_root or Path(__file__).resolve().parent)
                or origin.get("runtime") != runtime_identity() or not manifest.get("entries")):
            raise ValueError("verified cache origin, audit semantics or runtime mismatch")
        self.verify_files()
        resources = read(manifest_path.parent / "resources.json")
        if resources.get("group_clean") is not True or resources.get("result") != origin["resource_result"]:
            raise ValueError("verified cache origin is not a closed run")
        tests = junit_result(manifest_path.parent / "pytest.xml")
        if any(tests[k] != value for k, value in origin["tests"].items()):
            raise ValueError("verified cache original tests mismatch")
        self.db = sqlite3.connect((manifest_path.parent / "index.sqlite").as_uri() + "?mode=ro&immutable=1", uri=True)
        self.reused = 0

    def verify_files(self) -> None:
        if sha(self.path) != self.expected_sha256:
            raise ValueError("verified cache manifest changed during audit")
        records = {"index.sqlite": self.manifest["index"], **self.manifest["evidence"]}
        if set(records) != {"index.sqlite", "resources.json", "pytest.xml", "canary-service.txt"}:
            raise ValueError("verified cache evidence inventory mismatch")
        for name, expected in records.items():
            if file_record(relative(self.path.parent, name)) != expected:
                raise ValueError("verified cache sealed file hash mismatch: " + name)

    def get(self, data_root: Path, source: dict, run_date: str) -> dict | None:
        # Current-day observations always execute the complete current algorithm.
        entry = self.manifest["entries"].get(source["key"])
        if source["run_date"] >= run_date or entry is None:
            return None
        before = stat_fingerprint(source)
        binding = verify_source(data_root, source)  # ALL artifact bytes, including banks.json and retained journals.
        if stat_fingerprint(source) != before:
            raise ValueError("source changed during verified cache byte recheck")
        row = self.db.execute("SELECT run_date,fingerprint,version,result FROM audits WHERE source_key=?", (source["key"],)).fetchone()
        if (row is None or row[0] != entry["run_date"] or row[1] != entry["fingerprint"]
                or row[2] != AUDIT_VERSION or hashlib.sha256(row[3]).hexdigest() != entry["result_sha256"]):
            raise ValueError("verified cache entry differs from sealed provenance")
        result = decode_result(row[3], source["key"], row[0], row[1])
        contract = source["contract"] or {}
        if (result is None or result["run_date"] != source["run_date"] or result["binding"] != binding
                or result["generation_id"] != contract.get("generation_id")
                or result["contract_digest"] != contract.get("contract_digest")
                or result["observation_state"] != contract.get("observation_state", "legacy_unverified")):
            return None  # Changed or incomplete sources run a new full audit.
        result["fingerprint"] = before
        result["cache_reuse"] = {"manifest_sha256": self.expected_sha256, "origin_commit": self.manifest["origin"]["commit"],
                                 "content_verified_at": datetime.now(timezone.utc).isoformat(),
                                 "original_verified_at": result["verified_at"], "all_artifacts_rehashed": True}
        self.reused += 1
        print(f"[cdr-audit] rehashed and reused {source['key']}", flush=True)
        return result

    def close(self) -> None:
        self.db.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--operation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--attest-closed-protected-run", action="store_true",
                        help="Attest this closed run produced the index and its interpreter/dependencies have not changed")
    args = parser.parse_args(argv)
    result = seal_cache(args.source, args.operation, args.output, args.expected_commit,
                        attest_closed=args.attest_closed_protected_run)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
