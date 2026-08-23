#!/usr/bin/env python3
"""Create, restore-test, and gate AR-local off-device preservation snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import shlex
import sqlite3
import stat
import subprocess
import sys
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from ar_local_backup_policy import (
    BackupPolicy,
    COMMIT_RE,
    SHA256_RE,
    atomic_create_json,
    atomic_replace_json,
    canonical_json_bytes,
    fsync_directory,
    mount_preflight,
    record_is_fresh,
    sha256_file,
    utc_now,
    validate_plan_identity,
)
from ar_local_boot_proof import archive_boot_evidence, validate_boot_proof
from ar_local_checkout import install_candidate, rollback_candidate
from ar_local_deployment_chain import reconcile_deployment_chain
from ar_local_operation_lock import production_lock, recovery_lock_path
DEFAULT_CONFIG = Path("/etc/ar-local/backup.env")
DEFAULT_BOOT_PROOF = Path("/etc/ar-local/backup-boot-proof.json")
SECRET_PATHS = (
    Path("/etc/ar-local/app-payload.env"),
    Path("/etc/ar-local/notify.env"),
    Path("/etc/ar-local/payload.key"),
)
REQUIRED_DAILY_TABLES = {
    "schema_meta",
    "runs",
    "bank_products",
    "bank_rates",
    "bank_items",
    "bank_product_facts",
    "bank_product_changes",
}
REQUIRED_MACRO_TABLES = {"series_observations", "ingest_runs"}
DAILY_SCHEMA_VERSION = "8"
REQUIRED_DAILY_COLUMNS = {
    "runs": {"run_date", "generated_at", "banks_counts_json"},
    "bank_products": {"run_date", "provider", "product_id", "product_key"},
    "bank_rates": {"run_date", "product_key", "rate", "comparison_rate"},
    "bank_items": {"run_date", "item_group", "product_key"},
    "bank_product_facts": {"run_date", "product_key", "fact_id", "canonical_key"},
    "bank_product_changes": {"run_date", "event_id", "product_id", "event_type"},
}
MACRO_COUNT_QUERIES = {
    "series_observations": "SELECT COUNT(*) FROM series_observations",
    "ingest_runs": "SELECT COUNT(*) FROM ingest_runs",
}


def _json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _run(command: Sequence[str], cwd: Path | None = None) -> str:
    """Run an argv-only internal command; callers provide fixed git verbs, never shell text."""

    if not command or command[0] != "git":
        raise ValueError("only internal git argv commands are allowed")
    # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
    result = subprocess.run(
        tuple(command), cwd=cwd, text=True, capture_output=True, timeout=300, shell=False
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"command failed: {command[0]}")
    return result.stdout.strip()


def _remove_tree(path: Path) -> None:
    def clear_readonly(function, failing_path, _error) -> None:
        os.chmod(failing_path, stat.S_IWRITE)
        function(failing_path)

    shutil.rmtree(path, onerror=clear_readonly)


def _fsync_tree(root: Path) -> None:
    """Flush copied payload bytes and directory entries before publication."""

    if os.name == "nt":
        return
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
    directories = [path for path in root.rglob("*") if path.is_dir()]
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        fsync_directory(directory)
    fsync_directory(root)


def git_state(repo: Path) -> dict[str, object]:
    sha = _run(("git", "rev-parse", "HEAD"), repo)
    status = _run(("git", "status", "--porcelain"), repo)
    return {"path": str(repo.resolve()), "commit": sha, "clean": not status, "status": status.splitlines()}


def verify_plan_document(policy: BackupPolicy, repo: Path) -> dict[str, object]:
    path = repo / "docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md"
    findings: list[str] = []
    try:
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != policy.plan_raw_sha256:
            findings.append("plan_raw_sha256_mismatch")
        text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        if text.count(policy.plan_sha256) != 2:
            findings.append("plan_controlled_digest_occurrence_mismatch")
        canonical = text.replace(policy.plan_sha256, "PLAN_SHA256_PENDING").encode("utf-8")
        if hashlib.sha256(canonical).hexdigest() != policy.plan_sha256:
            findings.append("plan_controlled_sha256_mismatch")
        commit = _run(("git", "log", "-1", "--format=%H", "--", path.relative_to(repo).as_posix()), repo)
        if commit != policy.plan_git_commit:
            findings.append("plan_git_commit_mismatch")
    except (OSError, UnicodeError, RuntimeError, ValueError) as exc:
        findings.append(f"plan_verification_error:{type(exc).__name__}")
    return {"ok": not findings, "findings": findings, "path": str(path)}


def _copy_regular_tree(source: Path, destination: Path, *, exclude: set[Path] | None = None) -> None:
    excluded = {path.resolve() for path in (exclude or set())}
    for item in sorted(source.rglob("*")):
        if item.is_symlink():
            raise ValueError(f"snapshot source contains symlink: {item}")
        if item.is_dir():
            continue
        if not item.is_file():
            raise ValueError(f"snapshot source contains non-regular file: {item}")
        if item.stat().st_nlink != 1:
            raise ValueError(f"snapshot source contains hardlink: {item}")
        if item.resolve() in excluded:
            continue
        before = item.stat()
        target = destination / item.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        after = item.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeError(f"snapshot source changed during copy: {item}")
        if sha256_file(item) != sha256_file(target):
            raise RuntimeError(f"snapshot copy hash mismatch: {item}")


def _tree_metadata(source: Path, exclude: set[Path]) -> dict[str, tuple[int, int]]:
    excluded = {path.resolve() for path in exclude}
    result: dict[str, tuple[int, int]] = {}
    for item in sorted(source.rglob("*")):
        if item.is_symlink():
            raise ValueError(f"snapshot source contains symlink: {item}")
        if item.is_dir() or item.resolve() in excluded:
            continue
        if not item.is_file() or item.stat().st_nlink != 1:
            raise ValueError(f"snapshot source is not a unique regular file: {item}")
        info = item.stat()
        result[item.relative_to(source).as_posix()] = (info.st_size, info.st_mtime_ns)
    return result


def _sqlite_backup(source: Path, destination: Path) -> dict[str, object]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"file:{source.as_posix()}?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True, timeout=30)) as src, closing(
        sqlite3.connect(destination, timeout=30)
    ) as dst:
        source_quick = src.execute("PRAGMA quick_check").fetchone()[0]
        source_tables = {row[0] for row in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = sorted(REQUIRED_MACRO_TABLES - source_tables)
        if source_quick != "ok" or missing:
            raise ValueError(f"macro source validation failed: quick_check={source_quick}, missing={missing}")
        source_counts = {
            name: src.execute(MACRO_COUNT_QUERIES[name]).fetchone()[0]
            for name in sorted(REQUIRED_MACRO_TABLES)
        }
        src.backup(dst)
        quick_check = dst.execute("PRAGMA quick_check").fetchone()[0]
        user_version = dst.execute("PRAGMA user_version").fetchone()[0]
        page_count = dst.execute("PRAGMA page_count").fetchone()[0]
        target_counts = {
            name: dst.execute(MACRO_COUNT_QUERIES[name]).fetchone()[0]
            for name in sorted(REQUIRED_MACRO_TABLES)
        }
    if quick_check != "ok":
        raise ValueError(f"SQLite backup failed quick_check: {source}")
    if source_counts != target_counts:
        raise ValueError("macro backup row counts changed")
    return {"source": str(source), "path": str(destination), "source_quick_check": source_quick, "quick_check": quick_check, "user_version": user_version, "page_count": page_count, "table_counts": target_counts}


def _manifest_entries(root: Path) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            entries.append({"path": path.relative_to(root).as_posix(), "size": path.stat().st_size, "sha256": sha256_file(path)})
    return entries


def _category_summary(entries: list[dict[str, object]]) -> dict[str, dict[str, int]]:
    categories: dict[str, dict[str, int]] = {}
    for entry in entries:
        path = str(entry["path"])
        if path.startswith("data/runs/"):
            if "raw-attempt" in path or "/_failed_attempts/" in path:
                category = "raw_attempt_evidence"
            elif path.endswith("/local-cdr.sqlite"):
                category = "daily_sqlite"
            else:
                category = "run_exports_and_state"
        elif path.startswith("data/state/export-contracts-v2/"):
            category = "export_contracts"
        elif path.startswith("data/state/ledger-v2/"):
            category = "ledger"
        elif path.startswith("data/state/observation-pointers-v2/"):
            category = "observation_pointers"
        elif "app-payload" in path:
            category = "publication_state"
        else:
            category = path.split("/", 1)[0]
        summary = categories.setdefault(category, {"files": 0, "bytes": 0})
        summary["files"] += 1
        summary["bytes"] += int(entry["size"])
    return categories


def _secret_metadata() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in SECRET_PATHS:
        record: dict[str, object] = {"path": str(path), "exists": path.exists()}
        if path.exists():
            info = path.stat()
            record.update({"uid": info.st_uid, "gid": info.st_gid, "mode": oct(info.st_mode & 0o777)})
        records.append(record)
    return records


def preflight(policy: BackupPolicy, repo: Path, site_repo: Path, data_root: Path, *, probe: bool = True) -> dict[str, object]:
    report = mount_preflight(policy, (repo, site_repo, data_root), perform_probe=probe)
    plan = verify_plan_document(policy, repo)
    report["findings"].extend(plan["findings"])
    report["ok"] = not report["findings"]
    report["plan_document"] = plan
    report.update({"created_at": utc_now(), **policy.plan_identity(), "repo": str(repo), "site_repo": str(site_repo), "data_root": str(data_root)})
    return report


def create_snapshot(
    policy: BackupPolicy,
    repo: Path,
    site_repo: Path,
    data_root: Path,
    macro_db: Path,
    operator: str,
    exact_commands: list[str] | None = None,
    *,
    config_path: Path = DEFAULT_CONFIG,
) -> dict[str, object]:
    check = preflight(policy, repo, site_repo, data_root)
    if not check["ok"]:
        raise RuntimeError(f"backup preflight failed: {check['findings']}")
    repos = {"ar_local": git_state(repo), "site": git_state(site_repo)}
    if not all(state["clean"] for state in repos.values()):
        raise RuntimeError("production checkout is dirty")
    created_at = utc_now()
    snapshot_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:12]
    staging = policy.backup_dir / f".partial-{snapshot_id}"
    final = policy.backup_dir / "snapshots" / snapshot_id
    staging.mkdir(parents=True, mode=0o700)
    lock = data_root / "state" / "daily-ingest.lock"
    try:
        with production_lock(lock, "backup"):
            snapshots_root = policy.backup_dir / "snapshots"
            if snapshots_root.is_symlink() or (
                snapshots_root.exists() and not snapshots_root.is_dir()
            ):
                raise RuntimeError("snapshot root is not a real directory")
            snapshot_children = list(snapshots_root.iterdir()) if snapshots_root.is_dir() else []
            if any(path.is_symlink() or not path.is_dir() for path in snapshot_children):
                raise RuntimeError("snapshot root contains an invalid entry")
            retained_snapshots = (
                snapshot_children if snapshots_root.is_dir() else []
            )
            if len(retained_snapshots) >= policy.retention_count:
                raise RuntimeError(
                    "snapshot retention ceiling reached; archive/removal requires a separately authorized decision"
                )
            macro = macro_db.resolve()
            if not macro.is_file():
                raise ValueError(f"macro database is missing: {macro}")
            macro_exclusions = {macro, Path(str(macro) + "-wal"), Path(str(macro) + "-shm")}
            exclusions = macro_exclusions | {lock.resolve(), recovery_lock_path(lock).resolve()}
            before = _tree_metadata(data_root, exclusions)
            required_free = max(policy.min_free_bytes, sum(size for size, _mtime in before.values()) + macro.stat().st_size + 1024**3)
            if shutil.disk_usage(policy.backup_dir).free < required_free:
                raise RuntimeError(f"backup target lacks source-size headroom: required={required_free}")
            _copy_regular_tree(data_root, staging / "data", exclude=exclusions)
            if _tree_metadata(data_root, exclusions) != before:
                raise RuntimeError("production data changed during snapshot")
            macro_report = _sqlite_backup(macro, staging / "macro/local-macro.sqlite")
            system_root = staging / "system"
            system_configuration: list[dict[str, object]] = []
            for source in (
                Path("/etc/fstab"),
                Path("/etc/nginx/sites-available/ar-local-dashboard"),
                config_path,
            ):
                if source.is_symlink():
                    raise ValueError(f"system configuration is a symlink: {source}")
                if source.is_file():
                    target = system_root / source.relative_to(source.anchor)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    info = source.stat()
                    system_configuration.append(
                        {
                            "path": str(source),
                            "snapshot_path": target.relative_to(staging).as_posix(),
                            "uid": info.st_uid,
                            "gid": info.st_gid,
                            "mode": oct(info.st_mode & 0o777),
                            "sha256": sha256_file(target),
                        }
                    )
            unit_root = Path("/etc/systemd/system")
            systemd_enablement: list[dict[str, str]] = []
            if unit_root.is_dir():
                for source in sorted(unit_root.glob("ar-local*")):
                    if source.is_file() and not source.is_symlink():
                        target = system_root / source.relative_to("/")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, target)
                    elif source.is_dir() and not source.is_symlink():
                        _copy_regular_tree(source, system_root / source.relative_to("/"))
                for wants in sorted(unit_root.glob("*.wants")):
                    for link in sorted(wants.glob("ar-local*")):
                        if link.is_symlink():
                            systemd_enablement.append(
                                {"path": str(link), "target": os.readlink(link)}
                            )
            bundles = staging / "code"
            bundles.mkdir()
            for name, source in (("AR-local", repo), ("australianrates", site_repo)):
                _run(("git", "bundle", "create", str((bundles / f"{name}.bundle").resolve()), "HEAD"), source)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    entries = _manifest_entries(staging)
    manifest: dict[str, object] = {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "created_at": created_at,
        "operator": operator,
        "started_at": created_at,
        "completed_at": utc_now(),
        "exact_commands": exact_commands or [],
        "deviations": [],
        "deviation_authorization": None,
        **policy.plan_identity(),
        "candidate_code_sha": repos["ar_local"]["commit"],
        "repositories": repos,
        "source_paths": {"data": str(data_root), "repo": str(repo), "site_repo": str(site_repo), "macro_db": str(macro_db.resolve())},
        "secret_locations": _secret_metadata(),
        "system_configuration": system_configuration,
        "systemd_enablement": systemd_enablement,
        "exclusions": [
            {"path": str(lock), "reason": "transient backup lock"},
            {"path": str(recovery_lock_path(lock)), "reason": "persistent stale-recovery mutex"},
        ],
        "macro_backup": macro_report,
        "source_data_bytes": sum(size for size, _mtime in before.values()),
        "category_summary": _category_summary(entries),
        "files": entries,
        "result": "PASS",
    }
    manifest_path = staging / "manifest.json"
    with manifest_path.open("wb") as stream:
        stream.write(canonical_json_bytes(manifest))
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_tree(staging)
    final.parent.mkdir(parents=True, exist_ok=True)
    staging.replace(final)
    fsync_directory(final.parent)
    manifest_archive = policy.backup_dir / "manifests" / f"{snapshot_id}.json"
    atomic_create_json(manifest_archive, manifest)
    receipt = {**policy.plan_identity(), "schema_version": 1, "snapshot_id": snapshot_id, "created_at": created_at, "started_at": created_at, "completed_at": utc_now(), "operator": operator, "candidate_code_sha": repos["ar_local"]["commit"], "exact_commands": exact_commands or [], "evidence": [{"path": str(manifest_archive), "sha256": sha256_file(manifest_archive)}], "deviations": [], "deviation_authorization": None, "manifest_sha256": sha256_file(final / "manifest.json"), "result": "PASS"}
    atomic_create_json(policy.backup_dir / "receipts" / f"{snapshot_id}.backup.json", receipt)
    atomic_replace_json(policy.backup_dir / "latest-backup.json", receipt)
    return receipt


def verify_snapshot(snapshot: Path) -> dict[str, object]:
    findings: list[str] = []
    if snapshot.is_symlink() or not snapshot.is_dir():
        return {"ok": False, "findings": ["invalid_snapshot_root"], "manifest": {}}
    manifest_path = snapshot / "manifest.json"
    if manifest_path.is_symlink():
        return {"ok": False, "findings": ["invalid_manifest_symlink"], "manifest": {}}
    try:
        manifest = _json(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "findings": [f"invalid_manifest:{exc}"], "manifest": {}}
    entries = manifest.get("files")
    if not isinstance(entries, list):
        return {"ok": False, "findings": ["invalid_manifest_files"], "manifest": manifest}
    expected_paths: set[str] = set()
    root = snapshot.resolve()
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            findings.append(f"invalid_entry:{index}")
            continue
        relative_text = entry.get("path")
        relative = Path(str(relative_text or ""))
        size = entry.get("size")
        digest = str(entry.get("sha256") or "")
        if (
            not relative_text
            or relative.is_absolute()
            or ".." in relative.parts
            or not isinstance(size, int)
            or size < 0
            or not SHA256_RE.fullmatch(digest)
            or relative.as_posix() in expected_paths
        ):
            findings.append(f"invalid_entry:{index}")
            continue
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            findings.append(f"path_escape:{relative.as_posix()}")
            continue
        expected_paths.add(relative.as_posix())
        if not path.is_file() or path.is_symlink():
            findings.append(f"missing:{relative.as_posix()}")
        elif path.stat().st_size != size or sha256_file(path) != digest:
            findings.append(f"changed:{relative.as_posix()}")
    snapshot_paths = list(snapshot.rglob("*"))
    for path in snapshot_paths:
        if path.is_symlink():
            findings.append(f"symlink:{path.relative_to(snapshot).as_posix()}")
        elif not path.is_dir() and not path.is_file():
            findings.append(f"special:{path.relative_to(snapshot).as_posix()}")
    actual_paths = {
        path.relative_to(snapshot).as_posix()
        for path in snapshot_paths
        if path.is_file() and not path.is_symlink() and path.name != "manifest.json"
    }
    for extra in sorted(actual_paths - expected_paths):
        findings.append(f"unmanifested:{extra}")
    return {"ok": not findings, "findings": findings, "manifest": manifest}


def _daily_export_reconciliation(database: Path) -> dict[str, object]:
    banks_files = sorted(database.parent.glob("banks-*.json"))
    if len(banks_files) != 1:
        raise ValueError("daily export must contain exactly one banks JSON")
    banks = _json(banks_files[0])
    run_date = banks_files[0].stem.removeprefix("banks-")
    expected = {key: len(value) for key, value in banks.items() if isinstance(value, list)}
    with closing(
        sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    ) as connection:
        run = connection.execute("SELECT run_date, banks_counts_json FROM runs").fetchall()
        actual = {
            "products": connection.execute("SELECT COUNT(*) FROM bank_products").fetchone()[0],
            "rates": connection.execute("SELECT COUNT(*) FROM bank_rates").fetchone()[0],
            "product_facts": connection.execute("SELECT COUNT(*) FROM bank_product_facts").fetchone()[0],
            "product_changes": connection.execute("SELECT COUNT(*) FROM bank_product_changes").fetchone()[0],
        }
        for group in ("fees", "features", "eligibility", "constraints"):
            actual[group] = connection.execute(
                "SELECT COUNT(*) FROM bank_items WHERE item_group = ?", (group,)
            ).fetchone()[0]
    if len(run) != 1 or run[0][0] != run_date or json.loads(run[0][1]) != expected:
        raise ValueError("runs metadata does not match banks export")
    for key, count in actual.items():
        if count != expected.get(key, 0):
            raise ValueError(f"database count mismatch for {key}")
    dashboard = _json(database.parent / "dashboard-cache/latest.json")
    if dashboard.get("run_date") != run_date or dashboard.get("banks_counts") != expected:
        raise ValueError("dashboard manifest does not match banks export")
    return {"run_date": run_date, "counts": actual, "banks_json": banks_files[0].name}


def _completion_marker_valid(
    marker: Mapping[str, object], state_dir: Path, observation_date: str
) -> bool:
    from cdr_export_contract import load_contract
    from cdr_ledger_v2 import ledger_root, verify_event_artifacts

    try:
        if marker.get("finalization_schema_version") != 2 or marker.get("ledger_state") != "finalized":
            return False
        if marker.get("run_date") != observation_date:
            return False
        counts = marker.get("banks_counts") or marker.get("banks") or {}
        if not isinstance(counts, Mapping) or int(counts.get("rates") or 0) <= 0:
            return False
        relative = Path(str(marker.get("export_contract_path") or ""))
        if relative.is_absolute() or ".." in relative.parts:
            return False
        contract_path = (state_dir / relative).resolve()
        if not contract_path.is_relative_to(state_dir.resolve()):
            return False
        contract = load_contract(contract_path)
        if contract.get("generation_id") != marker.get("generation_id"):
            return False
        if contract.get("observation_date") != observation_date:
            return False
        if contract.get("observation_state") != marker.get("observation_state"):
            return False
        if contract.get("contract_digest") != marker.get("export_contract_digest"):
            return False
        event_path = ledger_root(state_dir) / "events" / observation_date / f"{contract['generation_id']}.json"
        event = _json(event_path)
        verify_event_artifacts(state_dir, event)
        return event.get("event_digest") == marker.get("ledger_event_digest")
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


def _pointer_matches_marker(
    pointer: Mapping[str, object], marker: Mapping[str, object], state_dir: Path
) -> bool:
    """Bind every publication-consumed pointer field to verified source evidence."""

    from cdr_export_contract import load_contract

    try:
        relative = Path(str(marker["export_contract_path"]))
        contract_path = (state_dir / relative).resolve()
        if relative.is_absolute() or ".." in relative.parts or not contract_path.is_relative_to(state_dir.resolve()):
            return False
        contract = load_contract(contract_path)
        expected = {
            "schema_version": 2,
            "observation_date": marker["run_date"],
            "generation_id": marker["generation_id"],
            "observation_state": marker["observation_state"],
            "ledger_event_digest": marker["ledger_event_digest"],
            "marker_path": str(pointer["marker_path"]),
            "export_path": contract["source_path"],
        }
        return dict(pointer) == expected
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


def _verify_restored_state(data_root: Path) -> dict[str, object]:
    from cdr_export_contract import load_contract
    from cdr_ledger_v2 import verify_ledger

    findings: list[str] = []
    sqlite_results: list[dict[str, object]] = []
    for path in sorted(data_root.rglob("*.sqlite")):
        try:
            with closing(
                sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            ) as connection:
                result = connection.execute("PRAGMA quick_check").fetchone()[0]
            sqlite_record: dict[str, object] = {
                "path": path.relative_to(data_root).as_posix(),
                "quick_check": result,
            }
            sqlite_results.append(sqlite_record)
            if result != "ok":
                findings.append(f"sqlite_quick_check:{path}")
            if path.name == "local-cdr.sqlite":
                with closing(
                    sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
                ) as connection:
                    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                missing = sorted(REQUIRED_DAILY_TABLES - tables)
                if missing:
                    findings.append(f"daily_schema_missing:{path}:{','.join(missing)}")
                else:
                    with closing(
                        sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
                    ) as connection:
                        schema_version = connection.execute(
                            "SELECT value FROM schema_meta WHERE key = 'version'"
                        ).fetchone()
                        if not schema_version or schema_version[0] != DAILY_SCHEMA_VERSION:
                            findings.append(f"daily_schema_version_mismatch:{path}")
                        for table, columns in REQUIRED_DAILY_COLUMNS.items():
                            actual_columns = {
                                row[0]
                                for row in connection.execute(
                                    "SELECT name FROM pragma_table_info(?)", (table,)
                                )
                            }
                            if not set(columns).issubset(actual_columns):
                                findings.append(f"daily_columns_missing:{path}:{table}")
                    try:
                        sqlite_record["export_reconciliation"] = _daily_export_reconciliation(path)
                    except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
                        findings.append(f"daily_export_mismatch:{path}:{exc}")
        except sqlite3.Error:
            findings.append(f"sqlite_unreadable:{path}")
    state = data_root / "state"
    for path in sorted((state / "export-contracts-v2").glob("*/*.json")):
        try:
            load_contract(path)
        except (OSError, ValueError, json.JSONDecodeError):
            findings.append(f"invalid_contract:{path.relative_to(data_root)}")
    if (state / "ledger-v2").exists():
        try:
            ledger = verify_ledger(state)
            if not ledger.get("ok"):
                findings.append("ledger_verification_failed")
        except (OSError, ValueError, json.JSONDecodeError):
            ledger = {"ok": False}
            findings.append("ledger_unreadable")
    else:
        ledger = {"ok": False, "reason": "missing"}
        findings.append("ledger_missing")
    for pointer in sorted((state / "observation-pointers-v2").glob("*.json")):
        try:
            value = _json(pointer)
            relative = Path(str(value.get("marker_path") or ""))
            if relative.is_absolute() or ".." in relative.parts or not (state / relative).resolve().is_relative_to(state.resolve()):
                findings.append(f"pointer_escape:{pointer.name}")
            elif not (state / relative).is_file():
                findings.append(f"pointer_target_missing:{pointer.name}")
            else:
                marker = _json(state / relative)
                if not _completion_marker_valid(marker, state, str(value.get("observation_date") or "")):
                    findings.append(f"pointer_marker_invalid:{pointer.name}")
                elif not _pointer_matches_marker(value, marker, state):
                    findings.append(f"pointer_fields_mismatch:{pointer.name}")
        except (OSError, ValueError, json.JSONDecodeError):
            findings.append(f"pointer_invalid:{pointer.name}")
    return {"ok": not findings, "findings": findings, "sqlite": sqlite_results, "ledger": ledger}


def restore_drill(
    policy: BackupPolicy,
    snapshot_id: str,
    scratch_root: Path,
    operator: str,
    exact_commands: list[str] | None = None,
) -> dict[str, object]:
    started_at = utc_now()
    snapshot = policy.backup_dir / "snapshots" / snapshot_id
    verified = verify_snapshot(snapshot)
    if not verified["ok"]:
        raise ValueError(f"snapshot verification failed: {verified['findings']}")
    configured_scratch = scratch_root.expanduser()
    if not configured_scratch.is_absolute():
        raise ValueError("scratch restore root must be absolute")
    scratch_root = configured_scratch.resolve(strict=False)
    if configured_scratch != scratch_root or configured_scratch.is_symlink():
        raise ValueError("scratch restore root must be a canonical non-symlink path")
    for forbidden in (policy.mountpoint.resolve(), policy.backup_dir.resolve()):
        if scratch_root == forbidden or forbidden in scratch_root.parents or scratch_root in forbidden.parents:
            raise ValueError("scratch restore must be outside backup storage")
    scratch_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not scratch_root.is_dir() or scratch_root.is_symlink():
        raise ValueError("scratch restore root is not a real directory")
    destination = scratch_root / f"restore-{snapshot_id}-{uuid.uuid4().hex[:8]}"
    destination.mkdir(parents=True)
    snapshot_bytes = sum(int(item.get("size") or 0) for item in verified["manifest"]["files"])
    if shutil.disk_usage(scratch_root).free < snapshot_bytes + 1024**3:
        destination.rmdir()
        raise ValueError("scratch storage lacks restore headroom")
    try:
        shutil.copytree(snapshot / "data", destination / "data")
        result = _verify_restored_state(destination / "data")
        macro_source = snapshot / "macro/local-macro.sqlite"
        macro_target = destination / "macro/local-macro.sqlite"
        macro_target.parent.mkdir(parents=True)
        shutil.copy2(macro_source, macro_target)
        with closing(
            sqlite3.connect(f"file:{macro_target.as_posix()}?mode=ro", uri=True)
        ) as connection:
            macro_quick = connection.execute("PRAGMA quick_check").fetchone()[0]
            macro_tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            macro_counts = {
                name: connection.execute(MACRO_COUNT_QUERIES[name]).fetchone()[0]
                for name in sorted(REQUIRED_MACRO_TABLES & macro_tables)
            }
        result["macro"] = {"quick_check": macro_quick, "tables": sorted(macro_tables), "counts": macro_counts}
        missing_macro = sorted(REQUIRED_MACRO_TABLES - macro_tables)
        if macro_quick != "ok" or missing_macro:
            result["ok"] = False
            result["findings"].append(f"macro_validation_failed:{','.join(missing_macro)}")
    finally:
        try:
            _remove_tree(destination)
        except OSError as exc:
            if "result" not in locals():
                raise
            result["ok"] = False
            result["findings"].append(f"scratch_cleanup_failed:{type(exc).__name__}")
    manifest_sha = sha256_file(snapshot / "manifest.json")
    receipt = {**policy.plan_identity(), "schema_version": 1, "snapshot_id": snapshot_id, "created_at": utc_now(), "started_at": started_at, "completed_at": utc_now(), "operator": operator, "candidate_code_sha": verified["manifest"].get("candidate_code_sha"), "manifest_sha256": manifest_sha, "scratch_path": str(destination), "scratch_retained": False, "exact_commands": exact_commands or [], "deviations": [], "deviation_authorization": None, "checks": result, "result": "PASS" if result["ok"] else "FAIL"}
    receipt_name = f"{snapshot_id}.restore.{uuid.uuid4().hex}.json"
    receipt_path = policy.backup_dir / "receipts" / receipt_name
    atomic_create_json(receipt_path, receipt)
    atomic_replace_json(
        policy.backup_dir / "latest-restore.json",
        {**receipt, "receipt_path": receipt_path.relative_to(policy.backup_dir).as_posix()},
    )
    return receipt


def gate(
    policy: BackupPolicy,
    repo: Path,
    site_repo: Path,
    data_root: Path,
    protected_code_sha: str,
    candidate_sha: str,
    boot_proof: Path,
    operator: str = "unknown",
    exact_commands: list[str] | None = None,
) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    if not COMMIT_RE.fullmatch(protected_code_sha) or not COMMIT_RE.fullmatch(candidate_sha):
        return {"ok": False, "created_at": utc_now(), **policy.plan_identity(), "protected_code_sha": protected_code_sha, "candidate_code_sha": candidate_sha, "operator": operator, "exact_commands": exact_commands or [], "deviations": [], "deviation_authorization": None, "findings": ["invalid_code_sha"], "result": "BLOCKED"}
    mount = preflight(policy, repo, site_repo, data_root)
    findings = list(mount["findings"])
    evidence_binding: dict[str, object] | None = None
    try:
        backup = _json(policy.backup_dir / "latest-backup.json")
        snapshot_id = str(backup["snapshot_id"])
        backup_receipt_path = policy.backup_dir / "receipts" / f"{snapshot_id}.backup.json"
        receipt = _json(backup_receipt_path)
        restore_pointer = _json(policy.backup_dir / "latest-restore.json")
        restore_path = (policy.backup_dir / str(restore_pointer["receipt_path"])).resolve()
        if not restore_path.is_relative_to((policy.backup_dir / "receipts").resolve()):
            raise ValueError("restore receipt path escapes receipt directory")
        restore = _json(restore_path)
        manifest = policy.backup_dir / "snapshots" / snapshot_id / "manifest.json"
        manifest_archive = policy.backup_dir / "manifests" / f"{snapshot_id}.json"
        if backup != receipt or not validate_plan_identity(receipt, policy):
            findings.append("backup_receipt_mismatch")
        if receipt.get("candidate_code_sha") != protected_code_sha:
            findings.append("current_production_sha_not_backed_up")
        if receipt.get("manifest_sha256") != sha256_file(manifest):
            findings.append("snapshot_manifest_digest_mismatch")
        if receipt.get("manifest_sha256") != sha256_file(manifest_archive):
            findings.append("snapshot_manifest_archive_digest_mismatch")
        snapshot_report = verify_snapshot(manifest.parent)
        if not snapshot_report["ok"]:
            findings.append("snapshot_contents_failed_verification")
        if not record_is_fresh(receipt, policy.max_backup_age_hours, now):
            findings.append("backup_stale_or_future")
        pointer_material = dict(restore_pointer)
        pointer_material.pop("receipt_path", None)
        if restore != pointer_material:
            findings.append("restore_pointer_mismatch")
        if restore.get("snapshot_id") != snapshot_id or restore.get("result") != "PASS" or restore.get("manifest_sha256") != receipt.get("manifest_sha256"):
            findings.append("restore_receipt_mismatch")
        if not validate_plan_identity(restore, policy) or not record_is_fresh(restore, policy.max_restore_age_hours, now):
            findings.append("restore_receipt_stale_or_wrong_plan")
        evidence_binding = {
            "snapshot_id": snapshot_id,
            "backup_receipt_path": backup_receipt_path.relative_to(policy.backup_dir).as_posix(),
            "restore_receipt_path": restore_path.relative_to(policy.backup_dir).as_posix(),
            "manifest_archive_path": manifest_archive.relative_to(policy.backup_dir).as_posix(),
            "manifest_sha256": receipt.get("manifest_sha256"),
        }
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        findings.append("backup_or_restore_receipt_missing_or_invalid")
    try:
        boot = validate_boot_proof(boot_proof, policy, now, candidate_sha)
        findings.extend(boot["findings"])
        if evidence_binding is not None:
            evidence_binding["boot_proof_sha256"] = sha256_file(boot_proof)
    except (OSError, ValueError, json.JSONDecodeError):
        findings.append("boot_proof_missing_or_invalid")
    return {"ok": not findings, "created_at": utc_now(), **policy.plan_identity(), "protected_code_sha": protected_code_sha, "candidate_code_sha": candidate_sha, "operator": operator, "exact_commands": exact_commands or [], "deviations": [], "deviation_authorization": None, "evidence_binding": evidence_binding if not findings else None, "findings": findings, "result": "PASS" if not findings else "BLOCKED"}


def record_deployment_acceptance(
    policy: BackupPolicy,
    repo: Path,
    site_repo: Path,
    data_root: Path,
    protected_code_sha: str,
    candidate_sha: str,
    boot_proof: Path,
    operator: str,
    exact_commands: list[str],
    *,
    dashboard_verified: bool,
    services_verified: bool,
) -> dict[str, object]:
    started_at = utc_now()
    gate_report = gate(
        policy,
        repo,
        site_repo,
        data_root,
        protected_code_sha,
        candidate_sha,
        boot_proof,
        operator,
        exact_commands,
    )
    if not gate_report["ok"]:
        raise ValueError(f"deployment evidence gate failed: {gate_report['findings']}")
    repository = git_state(repo)
    if not repository["clean"] or repository["commit"] != candidate_sha:
        raise ValueError("deployed checkout is not the exact clean candidate")
    if not dashboard_verified or not services_verified:
        raise ValueError("dashboard and service verification must precede acceptance")
    binding = gate_report.get("evidence_binding")
    if not isinstance(binding, Mapping):
        raise ValueError("deployment gate did not return immutable evidence identities")
    backup_root = policy.backup_dir.resolve()
    bound_paths: dict[str, Path] = {}
    for key in ("backup_receipt_path", "restore_receipt_path", "manifest_archive_path"):
        relative = Path(str(binding.get(key) or ""))
        resolved = (backup_root / relative).resolve()
        if relative.is_absolute() or ".." in relative.parts or not resolved.is_relative_to(backup_root):
            raise ValueError(f"bound deployment evidence escapes backup storage: {key}")
        bound_paths[key] = resolved
    snapshot_id = str(binding.get("snapshot_id") or "")
    backup_receipt = bound_paths["backup_receipt_path"]
    restore_receipt = bound_paths["restore_receipt_path"]
    manifest_archive = bound_paths["manifest_archive_path"]
    backup = _json(backup_receipt)
    restore = _json(restore_receipt)
    if (
        backup.get("snapshot_id") != snapshot_id
        or restore.get("snapshot_id") != snapshot_id
        or backup.get("result") != "PASS"
        or restore.get("result") != "PASS"
        or not validate_plan_identity(backup, policy)
        or not validate_plan_identity(restore, policy)
        or backup.get("manifest_sha256") != binding.get("manifest_sha256")
        or restore.get("manifest_sha256") != binding.get("manifest_sha256")
        or sha256_file(manifest_archive) != binding.get("manifest_sha256")
        or sha256_file(boot_proof) != binding.get("boot_proof_sha256")
    ):
        raise ValueError("immutable evidence no longer matches the snapshot accepted by the gate")
    completed_at = utc_now()
    records_root = policy.backup_dir / "deployment-records"
    records_root.mkdir(parents=True, exist_ok=True)
    if records_root.is_symlink() or not records_root.resolve().is_relative_to(backup_root):
        raise ValueError("deployment record root is not confined to backup storage")
    fsync_directory(records_root.parent)
    with production_lock(records_root / ".chain.lock", "deployment-record"):
        head_path = records_root / "head.json"
        sequence, previous_record_sha256 = reconcile_deployment_chain(records_root, policy)
        record_id = f"{sequence:020d}-{uuid.uuid4().hex}-{candidate_sha}"
        deployment_evidence_root = policy.backup_dir / "deployment-evidence"
        deployment_evidence_root.mkdir(parents=True, exist_ok=True)
        if deployment_evidence_root.is_symlink() or not deployment_evidence_root.resolve().is_relative_to(backup_root):
            raise ValueError("deployment evidence root is not confined to backup storage")
        boot_evidence = archive_boot_evidence(
            boot_proof,
            deployment_evidence_root / record_id,
            str(binding["boot_proof_sha256"]),
        )
        evidence_paths = (backup_receipt, restore_receipt, manifest_archive, *boot_evidence)
        evidence = [
            {"path": str(path.resolve()), "sha256": sha256_file(path)} for path in evidence_paths
        ]
        record: dict[str, object] = {
            "schema_version": 1,
            "sequence": sequence,
            **policy.plan_identity(),
            "protected_code_sha": protected_code_sha,
            "candidate_code_sha": candidate_sha,
            "operator": operator,
            "started_at": started_at,
            "completed_at": completed_at,
            "exact_commands": exact_commands,
            "evidence": evidence,
            "previous_record_sha256": previous_record_sha256,
            "checks": {
                "backup_gate": "PASS",
                "clean_candidate_checkout": "PASS",
                "services": "PASS",
                "dashboard": "PASS",
            },
            "deviations": [],
            "deviation_authorization": None,
            "result": "PASS",
        }
        record_path = records_root / f"{record_id}.record.json"
        atomic_create_json(record_path, record)
        record_sha256 = sha256_file(record_path)
        atomic_replace_json(
            head_path,
            {
                "schema_version": 1,
                "sequence": sequence,
                "record_path": record_path.relative_to(records_root).as_posix(),
                "record_sha256": record_sha256,
            },
        )
    return {**record, "record_path": str(record_path), "record_sha256": record_sha256}


def _paths(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    return args.repo.resolve(), args.site_repo.resolve(), args.data_root.resolve()


def main(argv: Sequence[str] | None = None) -> int:
    effective_argv = list(argv) if argv is not None else sys.argv[1:]
    exact_command = shlex.join([sys.executable, str(Path(__file__).resolve()), *effective_argv])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "snapshot", "verify", "restore-drill", "gate", "verify-boot-proof", "install-checkout", "rollback-checkout", "record-deployment"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--repo", type=Path, default=Path("/srv/ar-local/AR-local"))
    parser.add_argument("--site-repo", type=Path, default=Path("/srv/ar-local/australianrates"))
    parser.add_argument("--data-root", type=Path, default=Path("/srv/ar-local/data"))
    parser.add_argument("--macro-db", type=Path, default=None)
    parser.add_argument("--snapshot-id")
    parser.add_argument("--scratch-root", type=Path, default=Path("/srv/ar-local/restore-drills"))
    parser.add_argument("--operator", default=os.environ.get("USER", "unknown"))
    parser.add_argument("--candidate-sha")
    parser.add_argument("--protected-code-sha")
    parser.add_argument("--boot-proof", type=Path, default=DEFAULT_BOOT_PROOF)
    parser.add_argument("--parent-command", action="append", default=[])
    parser.add_argument("--dashboard-verified", action="store_true")
    parser.add_argument("--services-verified", action="store_true")
    args = parser.parse_args(argv)
    try:
        policy = BackupPolicy.from_env_file(args.config)
        repo, site_repo, data_root = _paths(args)
        if args.command == "preflight":
            report = preflight(policy, repo, site_repo, data_root)
        elif args.command == "snapshot":
            macro_db = (args.macro_db or (repo / "state/local-macro.sqlite")).resolve()
            report = create_snapshot(policy, repo, site_repo, data_root, macro_db, args.operator, [exact_command], config_path=args.config)
        elif args.command == "verify":
            if not args.snapshot_id:
                raise ValueError("--snapshot-id is required")
            report = verify_snapshot(policy.backup_dir / "snapshots" / args.snapshot_id)
        elif args.command == "restore-drill":
            if not args.snapshot_id:
                raise ValueError("--snapshot-id is required")
            report = restore_drill(policy, args.snapshot_id, args.scratch_root, args.operator, [exact_command])
        elif args.command == "verify-boot-proof":
            report = validate_boot_proof(args.boot_proof, policy, datetime.now(timezone.utc))
        elif args.command == "gate":
            if not args.candidate_sha or not args.protected_code_sha:
                raise ValueError("--candidate-sha and --protected-code-sha are required")
            report = gate(policy, repo, site_repo, data_root, args.protected_code_sha, args.candidate_sha, args.boot_proof, args.operator, [exact_command])
        elif args.command == "install-checkout":
            if not args.candidate_sha:
                raise ValueError("--candidate-sha is required")
            report = install_candidate(repo, data_root, args.candidate_sha)
        elif args.command == "rollback-checkout":
            if not args.protected_code_sha:
                raise ValueError("--protected-code-sha is required")
            report = rollback_candidate(repo, data_root, args.protected_code_sha)
        else:
            if not args.candidate_sha or not args.protected_code_sha:
                raise ValueError("--candidate-sha and --protected-code-sha are required")
            report = record_deployment_acceptance(
                policy,
                repo,
                site_repo,
                data_root,
                args.protected_code_sha,
                args.candidate_sha,
                args.boot_proof,
                args.operator,
                [*args.parent_command, exact_command],
                dashboard_verified=args.dashboard_verified,
                services_verified=args.services_verified,
            )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report.get("ok", report.get("result") == "PASS") else 1
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "result": "BLOCKED", "error": str(exc)}), file=sys.stderr)
        lock_busy = args.command in {"install-checkout", "rollback-checkout"} and str(exc).startswith(
            "production lock"
        )
        return 75 if lock_busy else 1


if __name__ == "__main__":
    raise SystemExit(main())
