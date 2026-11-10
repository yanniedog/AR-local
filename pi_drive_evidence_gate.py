"""Drive-evidence deployment gate (owner decision 2026-11-10).

Used when no separate local backup disk exists. A deployment is admitted only when:

* the routine Drive day archive holds a recorded archive for the current or the
  previous Hobart day (the raw CDR bytes that can never be fetched again), and
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
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Sequence
from zoneinfo import ZoneInfo

from ar_local_backup_policy import atomic_create_json, atomic_replace_json, load_env, sha256_file

SCHEMA = "ar-local-drive-evidence-v1"
DEFAULT_ENV = Path("/etc/ar-local/day-archive.env")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
MAX_BACKUP_AGE_HOURS = 6
MAX_TOTAL_BYTES = 20 * 1024**3
MIN_FREE_BYTES = 30 * 1024**3
HOBART = ZoneInfo("Australia/Hobart")
TAR_EXCLUDES = ("node_modules", ".venv", "__pycache__", ".pytest_cache")

Runner = Callable[[Sequence[str], int], subprocess.CompletedProcess]


class Blocked(RuntimeError):
    pass


def _run(argv: Sequence[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout, check=False)


def _settings(env_path: Path) -> dict[str, object]:
    values = load_env(env_path)
    remote = values.get("AR_LOCAL_DAY_ARCHIVE_REMOTE", "")
    spool = Path(values.get("AR_LOCAL_DAY_ARCHIVE_SPOOL", ""))
    config = Path(values.get("RCLONE_CONFIG", ""))
    name, sep, path = remote.partition(":")
    if not sep or not name or "/" not in path.strip("/"):
        raise Blocked("day-archive remote is not a folder inside a dedicated Drive root")
    if not spool.is_absolute() or not config.is_absolute():
        raise Blocked("day-archive spool and rclone config must be absolute paths")
    parent = path.strip("/").rsplit("/", 1)[0]
    return {"spool": spool, "config": config, "remote_root": f"{name}:{parent}/pre-deploy-backups"}


def _root(spool: Path) -> Path:
    return spool / "pre-deploy"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _check_shas(protected: str, candidate: str) -> None:
    if not COMMIT_RE.fullmatch(protected) or not COMMIT_RE.fullmatch(candidate):
        raise Blocked("protected and candidate commits must be exact 40-character SHAs")


def day_archive_evidence(spool: Path, now: datetime) -> dict[str, object]:
    """Latest recorded day archive; blocked unless it covers today or yesterday (Hobart)."""
    ledger = spool / "meta" / "raw-progress.jsonl"
    latest: dict | None = None
    for line in ledger.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("kind") == "day" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(row.get("date", ""))):
            if latest is None or str(row["date"]) >= str(latest["date"]):
                latest = row
    if latest is None:
        raise Blocked("day-archive ledger has no recorded day")
    oldest_ok = (now.astimezone(HOBART).date() - timedelta(days=1)).isoformat()
    if str(latest["date"]) < oldest_ok:
        raise Blocked(f"latest Drive day archive is {latest['date']}; need {oldest_ok} or later")
    if not latest.get("remote_name") or not latest.get("coverage") or int(latest.get("bytes") or 0) <= 0:
        raise Blocked("latest Drive day archive record is incomplete")
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
    current = now or _now()
    archive = day_archive_evidence(spool, current)
    sources = {"code-ar-local": repo, "code-site": site_repo, "data-state": data_root / "state"}
    for label, path in sources.items():
        if path.is_symlink() or not path.is_dir():
            raise Blocked(f"backup source is not a real directory: {label}")
    root = _root(spool)
    for sub in (root, root / "receipts", root / "staging"):
        sub.mkdir(mode=0o700, exist_ok=True)
    if shutil.disk_usage(root).free < MIN_FREE_BYTES:
        raise Blocked("insufficient free space for the pre-deployment backup")
    name = f"{current.strftime('%Y%m%dT%H%M%SZ')}-{protected[:12]}"
    stage = root / "staging" / name
    stage.mkdir(mode=0o700)
    try:
        artefacts = []
        for label, path in sources.items():
            target = stage / f"{label}.tar.zst"
            excludes = [f"--exclude={item}" for item in TAR_EXCLUDES]
            done = run(["tar", "--zstd", *excludes, "-cf", str(target), "-C", str(path.parent), path.name], 3600)
            # 1 = a file changed while being read (live checkout or state); recorded, not hidden.
            if done.returncode not in (0, 1) or not target.is_file() or target.stat().st_size == 0:
                raise Blocked(f"tar failed for {label} (exit {done.returncode})")
            artefacts.append({"name": target.name, "bytes": target.stat().st_size, "sha256": sha256_file(target), "tar_exit": done.returncode})
        if sum(int(item["bytes"]) for item in artefacts) > MAX_TOTAL_BYTES:
            raise Blocked("pre-deployment backup exceeds the size cap")
        manifest = {"schema": SCHEMA, "name": name, "created_at": current.isoformat(), "protected_code_sha": protected,
                    "candidate_code_sha": candidate, "artefacts": artefacts}
        manifest_path = stage / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        remote = f"{settings['remote_root']}/{name}"
        base = ["rclone", "--config", str(config)]
        for argv, limit in ((["copy", "--checksum", str(stage), remote], 7200), (["check", "--one-way", str(stage), remote], 3600)):
            done = run([*base, *argv], limit)
            if done.returncode != 0:
                raise Blocked(f"rclone {argv[0]} failed (exit {done.returncode})")
        back = run([*base, "cat", f"{remote}/manifest.json"], 600)
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
        if json.loads(stored.read_text(encoding="utf-8")) != receipt:
            findings.append("backup_receipt_mismatch")
        if receipt.get("schema") != SCHEMA or receipt.get("result") != "PASS":
            findings.append("backup_receipt_not_pass")
        if receipt.get("remote_hash_check") != "PASS" or receipt.get("manifest_readback") != "PASS":
            findings.append("backup_not_verified_on_drive")
        if receipt.get("protected_code_sha") != protected:
            findings.append("current_production_sha_not_backed_up")
        if receipt.get("candidate_code_sha") != candidate:
            findings.append("backup_bound_to_other_candidate")
        age = current - datetime.fromisoformat(str(receipt["created_at"]))
        if age < timedelta(0) or age > timedelta(hours=MAX_BACKUP_AGE_HOURS):
            findings.append("backup_stale_or_future")
    except (OSError, KeyError, TypeError, ValueError):
        findings.append("backup_receipt_missing_or_invalid")
    return {"ok": not findings, "schema": SCHEMA, "mode": "drive-evidence", "created_at": current.isoformat(),
            "protected_code_sha": protected, "candidate_code_sha": candidate, "findings": findings,
            "day_archive": archive, "backup": receipt.get("name"), "backup_remote": receipt.get("remote"),
            "restore_drill": "NOT_TESTED", "boot_proof": "NOT_TESTED"}


def record(kind: str, protected: str, candidate: str, commands: Sequence[str], *, env_path: Path = DEFAULT_ENV,
           now: datetime | None = None) -> dict[str, object]:
    """Append-only deployment or rollback record bound to the backup receipt in force."""
    _check_shas(protected, candidate)
    if kind not in ("deployment", "rollback"):
        raise Blocked("unknown record kind")
    root = _root(_settings(env_path)["spool"])
    current = now or _now()
    latest = root / "latest.json"
    receipt = json.loads(latest.read_text(encoding="utf-8"))
    if receipt.get("protected_code_sha") != protected or receipt.get("candidate_code_sha") != candidate:
        raise Blocked("latest backup receipt is not for this deployment")
    records = root / "deployment-records"
    records.mkdir(mode=0o700, exist_ok=True)
    value = {"schema": SCHEMA, "kind": kind, "result": "PASS" if kind == "deployment" else "ROLLED_BACK",
             "created_at": current.isoformat(), "protected_code_sha": protected, "candidate_code_sha": candidate,
             "backup": receipt.get("name"), "backup_receipt_sha256": hashlib.sha256(latest.read_bytes()).hexdigest(),
             "operator": os.environ.get("USER", "unknown"), "commands": list(commands),
             "restore_drill": "NOT_TESTED", "boot_proof": "NOT_TESTED"}
    atomic_create_json(records / f"{current.strftime('%Y%m%dT%H%M%SZ')}-{kind}-{candidate[:12]}.json", value)
    return value
