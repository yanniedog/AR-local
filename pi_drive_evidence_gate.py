"""Drive-evidence deployment gate (owner decision 2026-11-10).

Used when no separate local backup disk exists. A deployment is admitted only when:

* the routine Drive day archive holds a recorded ``PASS`` ``wire_raw`` archive
  for the current or the previous Hobart day (the raw CDR bytes that can never
  be fetched again), and
* a pre-deployment backup of the code checkouts and ``data/state`` was uploaded
  to the same dedicated Drive remote, hash-checked there and read back, for the
  exact protected and candidate commits, within ``MAX_BACKUP_AGE_HOURS``.

It does not claim a restore drill or boot proof. Nothing here deletes or rewrites
production data; the only writes are under the day-archive spool and to Drive.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Sequence
from zoneinfo import ZoneInfo

from ar_local_backup_policy import atomic_create_json, atomic_replace_json, load_env, sha256_file
from pi_drive_backup_hold import Blocked as HoldBlocked, require_writes_allowed

SCHEMA = "ar-local-drive-evidence-v1"
DEFAULT_ENV = Path("/etc/ar-local/day-archive.env")
DEFAULT_DRIVE_BACKUP_SPOOL = Path("/var/lib/ar-local-drive-backup")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
REMOTE_NAME_RE = re.compile(r"[a-zA-Z0-9_-]+")
MAX_BACKUP_AGE_HOURS = 6
MAX_TOTAL_BYTES = 20 * 1024**3
MIN_FREE_BYTES = 30 * 1024**3
HOBART = ZoneInfo("Australia/Hobart")
TAR_EXCLUDES = (".env", ".env.*", "node_modules", ".venv", "__pycache__", ".pytest_cache")

Runner = Callable[[Sequence[str], int], subprocess.CompletedProcess]


class Blocked(RuntimeError):
    pass


def _run(argv: Sequence[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout, check=False)


def _require_drive_writes_allowed(spool: Path) -> None:
    try:
        require_writes_allowed(spool)
        backup_spool = Path(
            os.environ.get("AR_LOCAL_DRIVE_BACKUP_SPOOL", str(DEFAULT_DRIVE_BACKUP_SPOOL))
        )
        if backup_spool.resolve() != spool.resolve():
            require_writes_allowed(backup_spool)
    except (HoldBlocked, OSError) as exc:
        raise Blocked(str(exc)) from exc


def _check_no_symlinks(*paths: Path) -> None:
    for path in paths:
        if path.is_symlink():
            raise Blocked(f"refusing symlink path: {path}")


def _settings(env_path: Path) -> dict[str, object]:
    values = load_env(env_path)
    remote = values.get("AR_LOCAL_DAY_ARCHIVE_REMOTE", "")
    spool = Path(values.get("AR_LOCAL_DAY_ARCHIVE_SPOOL", ""))
    config = Path(values.get("RCLONE_CONFIG", ""))
    name, sep, path = remote.partition(":")
    segments = [seg for seg in path.strip("/").split("/") if seg]
    if (
        not sep
        or not REMOTE_NAME_RE.fullmatch(name)
        or len(segments) < 2
        or any(seg in (".", "..") for seg in segments)
    ):
        raise Blocked("day-archive remote is not a folder inside a dedicated Drive root")
    if not spool.is_absolute() or not config.is_absolute():
        raise Blocked("day-archive spool and rclone config must be absolute paths")
    parent = "/".join(segments[:-1])
    return {"spool": spool, "config": config, "remote_root": f"{name}:{parent}/pre-deploy-backups"}


def _root(spool: Path) -> Path:
    return spool / "pre-deploy"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _check_shas(protected: str, candidate: str) -> None:
    if not COMMIT_RE.fullmatch(protected) or not COMMIT_RE.fullmatch(candidate):
        raise Blocked("protected and candidate commits must be exact 40-character SHAs")


def day_archive_evidence(spool: Path, now: datetime) -> dict[str, object]:
    """Latest recorded PASS wire_raw day archive for today or yesterday (Hobart)."""
    _check_no_symlinks(spool, spool / "meta")
    ledger = spool / "meta" / "raw-progress.jsonl"
    _check_no_symlinks(ledger)
    today = now.astimezone(HOBART).date()
    oldest_ok = (today - timedelta(days=1)).isoformat()
    today_str = today.isoformat()
    latest: dict | None = None
    for line in ledger.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or row.get("kind") != "day":
            continue
        if row.get("result") != "PASS" or row.get("coverage") != "wire_raw":
            continue
        if not row.get("remote_name") or int(row.get("bytes") or 0) <= 0:
            continue
        row_date = str(row.get("date", ""))
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row_date):
            continue
        if not (oldest_ok <= row_date <= today_str):
            continue
        if latest is None or row_date >= str(latest["date"]):
            latest = row
    if latest is None:
        raise Blocked(f"day-archive ledger has no PASS wire_raw day between {oldest_ok} and {today_str}")
    return {key: latest.get(key) for key in ("date", "generation_id", "coverage", "bytes", "remote_name", "recorded_at")}


def create_backup(
    repo: Path,
    site_repo: Path,
    data_root: Path,
    protected: str,
    candidate: str,
    *,
    env_path: Path = DEFAULT_ENV,
    run: Runner = _run,
    now: datetime | None = None,
) -> dict[str, object]:
    _check_shas(protected, candidate)
    settings = _settings(env_path)
    spool, config = settings["spool"], settings["config"]
    _require_drive_writes_allowed(spool)
    current = now or _now()
    archive = day_archive_evidence(spool, current)
    sources = {"code-ar-local": repo, "code-site": site_repo, "data-state": data_root / "state"}
    for label, path in sources.items():
        if path.is_symlink() or not path.is_dir():
            raise Blocked(f"backup source is not a real directory: {label}")
    head_done = run(["git", "-C", str(repo), "rev-parse", "HEAD"], 30)
    if head_done.returncode != 0 or head_done.stdout.strip() != protected:
        raise Blocked("protected checkout HEAD does not match protected_code_sha")
    root = _root(spool)
    _check_no_symlinks(spool, root, root / "receipts", root / "staging")
    try:
        for sub in (root, root / "receipts", root / "staging"):
            sub.mkdir(mode=0o700, exist_ok=True)
    except OSError as exc:
        raise Blocked(f"unable to prepare pre-deploy spool directory: {exc}") from exc
    if shutil.disk_usage(root).free < MIN_FREE_BYTES:
        raise Blocked("insufficient free space for the pre-deployment backup")
    name = f"{current.strftime('%Y%m%dT%H%M%SZ')}-{protected[:12]}-{secrets.token_hex(4)}"
    stage = root / "staging" / name
    stage.mkdir(mode=0o700)
    try:
        artefacts = []
        for label, path in sources.items():
            target = stage / f"{label}.tar.zst"
            excludes = [f"--exclude={item}" for item in TAR_EXCLUDES]
            done = run(["tar", "--zstd", *excludes, "-cf", str(target), "-C", str(path.parent), path.name], 300)
            if done.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
                raise Blocked(f"tar failed for {label} (exit {done.returncode})")
            artefacts.append({"name": target.name, "bytes": target.stat().st_size, "sha256": sha256_file(target), "tar_exit": done.returncode})
        if sum(int(item["bytes"]) for item in artefacts) > MAX_TOTAL_BYTES:
            raise Blocked("pre-deployment backup exceeds the size cap")
        manifest = {"schema": SCHEMA, "name": name, "created_at": current.isoformat(), "protected_code_sha": protected,
                    "candidate_code_sha": candidate, "artefacts": artefacts}
        manifest_path = stage / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        remote = f"{settings['remote_root']}/{name}"
        base = ["rclone", "--config", str(config)]
        for argv, limit in ((["copy", "--checksum", str(stage), remote], 900), (["check", "--one-way", str(stage), remote], 450)):
            done = run([*base, *argv], limit)
            if done.returncode != 0:
                raise Blocked(f"rclone {argv[0]} failed (exit {done.returncode})")
        back = run([*base, "cat", f"{remote}/manifest.json"], 120)
        if back.returncode != 0 or back.stdout.encode("utf-8") != manifest_path.read_bytes():
            raise Blocked("Drive read-back of the backup manifest did not match")
        receipt = {**manifest, "result": "PASS", "remote": remote, "remote_hash_check": "PASS", "manifest_readback": "PASS",
                   "manifest_sha256": sha256_file(manifest_path), "day_archive": archive,
                   "restore_drill": "NOT_TESTED", "boot_proof": "NOT_TESTED"}
        atomic_create_json(root / "receipts" / f"{name}.json", receipt)
        atomic_replace_json(root / "latest.json", receipt)
        return {"ok": True, **receipt}
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def gate(protected: str, candidate: str, *, env_path: Path = DEFAULT_ENV, now: datetime | None = None) -> dict[str, object]:
    _check_shas(protected, candidate)
    spool = _settings(env_path)["spool"]
    current = now or _now()
    findings: list[str] = []
    try:
        _require_drive_writes_allowed(spool)
    except Blocked as error:
        findings.append(f"drive_write_hold: {error}")
    try:
        _check_no_symlinks(spool, _root(spool), _root(spool) / "latest.json")
    except Blocked as error:
        findings.append(str(error))
    archive: dict[str, object] | None = None
    try:
        archive = day_archive_evidence(spool, current)
    except (Blocked, OSError, ValueError) as error:
        findings.append(f"day_archive: {error}")
    receipt: dict = {}
    try:
        latest = _root(spool) / "latest.json"
        receipt = json.loads(latest.read_text(encoding="utf-8"))
        stored = _root(spool) / "receipts" / f"{receipt['name']}.json"
        _check_no_symlinks(stored)
        if json.loads(stored.read_text(encoding="utf-8")) != receipt:
            findings.append("backup_receipt_mismatch")
        if receipt.get("schema") != SCHEMA or receipt.get("result") != "PASS":
            findings.append("backup_receipt_not_pass")
        if receipt.get("remote_hash_check") != "PASS" or receipt.get("manifest_readback") != "PASS":
            findings.append("backup_not_verified_on_drive")
        if any(int(item.get("tar_exit", -1)) != 0 for item in receipt.get("artefacts") or []):
            findings.append("backup_tar_nonzero_exit")
        if receipt.get("protected_code_sha") != protected:
            findings.append("current_production_sha_not_backed_up")
        if receipt.get("candidate_code_sha") != candidate:
            findings.append("backup_bound_to_other_candidate")
        age = current - datetime.fromisoformat(str(receipt["created_at"]))
        if age < timedelta(0) or age > timedelta(hours=MAX_BACKUP_AGE_HOURS):
            findings.append("backup_stale_or_future")
    except (Blocked, OSError, KeyError, TypeError, ValueError):
        findings.append("backup_receipt_missing_or_invalid")
    return {"ok": not findings, "schema": SCHEMA, "mode": "drive-evidence", "created_at": current.isoformat(),
            "protected_code_sha": protected, "candidate_code_sha": candidate, "findings": findings,
            "day_archive": archive, "backup": receipt.get("name"), "backup_remote": receipt.get("remote"),
            "restore_drill": "NOT_TESTED", "boot_proof": "NOT_TESTED"}


def record(kind: str, protected: str, candidate: str, commands: Sequence[str], *, env_path: Path = DEFAULT_ENV,
           now: datetime | None = None, repo: Path | None = None, run: Runner = _run) -> dict[str, object]:
    """Append-only deployment or rollback record bound to a passing gate and immutable receipt."""
    _check_shas(protected, candidate)
    if kind not in ("deployment", "rollback"):
        raise Blocked("unknown record kind")
    if repo is not None:
        expected_head = candidate if kind == "deployment" else protected
        head_done = run(["git", "-C", str(repo), "rev-parse", "HEAD"], 30)
        if head_done.returncode != 0 or head_done.stdout.strip() != expected_head:
            raise Blocked(f"active checkout HEAD does not match expected {kind} SHA")
    current = now or _now()
    report = gate(protected, candidate, env_path=env_path, now=current)
    if not report.get("ok") or not report.get("backup"):
        raise Blocked(f"drive gate failed for record: {report.get('findings')}")
    spool = _settings(env_path)["spool"]
    root = _root(spool)
    records = root / "deployment-records"
    _check_no_symlinks(spool, root, records)
    stored = root / "receipts" / f"{report['backup']}.json"
    _check_no_symlinks(stored)
    receipt = json.loads(stored.read_text(encoding="utf-8"))
    if receipt.get("protected_code_sha") != protected or receipt.get("candidate_code_sha") != candidate:
        raise Blocked("backup receipt is not for this deployment")
    records.mkdir(mode=0o700, exist_ok=True)
    value = {"schema": SCHEMA, "kind": kind, "result": "PASS" if kind == "deployment" else "ROLLED_BACK",
             "created_at": current.isoformat(), "protected_code_sha": protected, "candidate_code_sha": candidate,
             "backup": receipt.get("name"), "backup_receipt_sha256": hashlib.sha256(stored.read_bytes()).hexdigest(),
             "operator": os.environ.get("USER", "unknown"), "commands": list(commands),
             "restore_drill": "NOT_TESTED", "boot_proof": "NOT_TESTED"}
    atomic_create_json(records / f"{current.strftime('%Y%m%dT%H%M%SZ')}-{kind}-{candidate[:12]}-{secrets.token_hex(4)}.json", value)
    return value
