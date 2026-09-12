"""Unattended encrypted Restic/rclone backups, with independent restore receipts.

No forget/prune/delete operation exists in this interface. Exit 2 means BLOCKED;
exit 1 means FAIL. A committed cloud snapshot is not a verified backup until its
source binding and repository check pass (plus required restore on first/weekly).
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, time as local_time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ar_local_backup_policy import fsync_directory
from ar_local_operation_lock import production_lock
from pi_drive_backup_source import (SCHEMA, canonical_json_bytes, digest, freeze,
    restore_relative, validate_layout, verify_direct_sources, verify_restore)

TZ = ZoneInfo("Australia/Hobart")
TAG = "ar-local-drive-v1"


class Blocked(RuntimeError):
    pass


def now() -> datetime:
    return datetime.now(TZ)


def guard_window() -> None:
    current = now().time().replace(tzinfo=None)
    if local_time(0, 30) <= current < local_time(3, 30):
        raise Blocked("daily ingest quiet window: 00:30-03:30 Australia/Hobart")


def atomic_json(path: Path, value: dict, *, immutable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial-" + uuid.uuid4().hex)
    try:
        with temporary.open("xb") as stream:
            stream.write(canonical_json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        if immutable and path.exists():
            raise ValueError("immutable backup receipt already exists")
        temporary.replace(path)
        fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def request_backup(reason: str, *, spool: Path | None = None) -> Path | None:
    """Non-fatal hook for terminal ingest/repair; the Pi timer drains this queue.

    Disabled unless AR_LOCAL_DRIVE_BACKUP_SPOOL is configured. A new UUID means
    requests arriving during an upload cannot be accidentally acknowledged.
    """
    configured = spool or os.environ.get("AR_LOCAL_DRIVE_BACKUP_SPOOL")
    if not configured:
        return None
    root = Path(configured)
    if not root.is_absolute() or root != root.resolve() or root.is_symlink():
        raise ValueError("backup queue spool is not canonical")
    marker = root / "requests" / (uuid.uuid4().hex + ".json")
    atomic_json(marker, {"schema": SCHEMA, "requested_at": now().isoformat(), "reason": reason[:200]}, immutable=True)
    return marker


@dataclass(frozen=True)
class Config:
    data: Path
    spool: Path
    repository: str
    password: Path
    rclone_config: Path
    controls: list[Path]
    restic: str = "restic"
    rclone: str = "rclone"
    min_free_bytes: int = 2 * 1024**3


def readiness(config: Config, *, remote: bool = False) -> dict:
    reasons = []
    try:
        validate_layout(config.data, config.spool, config.controls)
    except (OSError, ValueError) as error:
        reasons.append(str(error))
    repository = re.fullmatch(r"rclone:([A-Za-z0-9_-]+):([^\r\n]+)", config.repository)
    if not repository or repository[2].strip("/.") == "" or ".." in repository[2].split("/"):
        reasons.append("RESTIC_REPOSITORY must identify a dedicated rclone folder")
    for name, executable in (("restic", config.restic), ("rclone", config.rclone)):
        if not shutil.which(executable):
            reasons.append(f"{name} executable missing")
    for label, path in (("Restic password", config.password), ("rclone credentials", config.rclone_config)):
        if not path.is_absolute() or not path.is_file() or path.is_symlink() or path != path.resolve():
            reasons.append(f"{label} file missing or unsafe")
        elif path.stat().st_size == 0:
            reasons.append(f"{label} file is empty")
        elif os.name == "posix" and path.stat().st_mode & 0o077:
            reasons.append(f"{label} file must have mode 0600")
        if path == config.data or config.data in path.parents:
            reasons.append(f"{label} must be outside source data")
        for control in config.controls:
            if path == control:
                reasons.append(f"{label} cannot be a control source")
    if repository and config.rclone_config.is_file():
        try:
            remote_config = configparser.ConfigParser(interpolation=None)
            remote_config.read(config.rclone_config, encoding="utf-8")
            remote_settings = remote_config[repository[1]]
            token = json.loads(remote_settings.get("token", "{}"))
            if (remote_settings.get("type") != "drive" or remote_settings.get("scope") != "drive.file"
                    or not isinstance(token, dict) or not token.get("refresh_token")):
                reasons.append("rclone remote requires drive.file OAuth scope and a saved refresh token")
        except (OSError, ValueError, KeyError, configparser.Error):
            reasons.append("rclone remote configuration is unavailable")
    if not reasons and remote:
        try:
            Restic(config).run("cat", "config")
        except (Blocked, RuntimeError, OSError) as error:
            reasons.append(str(error))
    return {"schema": SCHEMA, "result": "BLOCKED" if reasons else "PASS", "reasons": reasons,
            "remote_checked": remote and not reasons, "retention": "all snapshots; no pruning"}


class Restic:
    def __init__(self, config: Config):
        self.config = config

    def run(self, *args: str) -> str:
        guard_window()
        cfg = self.config
        env = os.environ.copy()
        env.update(RESTIC_REPOSITORY=cfg.repository, RESTIC_PASSWORD_FILE=str(cfg.password),
                   RCLONE_CONFIG=str(cfg.rclone_config), RESTIC_CACHE_DIR=str(cfg.spool / "cache"),
                   GOMAXPROCS="2", RCLONE_BWLIMIT="8M", RCLONE_TRANSFERS="2")
        # Do not inherit alternative authentication or command hooks.
        for key in ("RESTIC_PASSWORD", "RESTIC_PASSWORD_COMMAND", "RESTIC_REPOSITORY_FILE"):
            env.pop(key, None)
        command = [cfg.restic, "--compression", "auto", "--pack-size", "16", *args]
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen(command, env=env, stdout=stdout, stderr=stderr,
                                       shell=False, start_new_session=os.name == "posix")
            try:
                deadline = time.monotonic() + 20 * 3600
                while process.poll() is None:
                    guard_window()
                    if time.monotonic() > deadline:
                        raise Blocked("backup command deadline exceeded")
                    if shutil.disk_usage(cfg.spool).free < cfg.min_free_bytes:
                        raise Blocked("backup spool free-space floor reached")
                    time.sleep(0.5)
            except BaseException:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    process.wait(timeout=15)
                raise
            if process.returncode != 0:
                # Raw stderr can contain backend URLs, credentials or provider
                # responses. Only the phase and exit code leave this function.
                raise RuntimeError(f"restic {args[0]} failed with exit {process.returncode}; credentials withheld")
            stdout.seek(0)
            output = stdout.read(16 * 1024 * 1024 + 1)
            if len(output) > 16 * 1024 * 1024:
                raise RuntimeError("restic command output exceeded bounded receipt limit")
            return output.decode("utf-8")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _summary(output: str) -> dict:
    records = [json.loads(line) for line in output.splitlines() if line.strip()]
    summaries = [row for row in records if row.get("message_type") == "summary"]
    if len(summaries) != 1 or not re.fullmatch(r"[0-9a-f]{8,64}", str(summaries[0].get("snapshot_id", ""))):
        raise RuntimeError("restic backup did not return exactly one snapshot identity")
    return summaries[0]


def restore_selection(manifest: dict, *, full: bool, rotation: int) -> list[dict]:
    if full:
        return manifest["files"]
    dates = sorted({row["logical_path"].split("/")[2] for row in manifest["files"]
                    if re.match(r"data/runs/\d{4}-\d{2}-\d{2}/", row["logical_path"])})
    chosen = set(dates[-1:])
    if len(dates) > 1:
        chosen.add(dates[rotation % (len(dates) - 1)])
    return [row for row in manifest["files"] if row["logical_path"].startswith(("control/", "data/state/", "sqlite-original/data/state/"))
            or row["sqlite"] and not row["logical_path"].startswith("data/runs/")
            or any(row["logical_path"].startswith((f"data/runs/{date}/", f"sqlite-original/data/runs/{date}/")) for date in chosen)]


def restore_snapshot(config: Config, client: Restic, snapshot: str, manifest: dict,
                     *, full: bool = False, rotation: int = 0, manifest_path: Path | None = None) -> dict:
    rows = restore_selection(manifest, full=full, rotation=rotation)
    if manifest_path:
        rows = [*rows, {"logical_path": "backup/source-manifest.json", "backup_path": manifest_path.as_posix(),
                       "sha256": digest(manifest_path), "size": manifest_path.stat().st_size, "sqlite": False}]
    if not rows or not any(row["sqlite"] for row in rows):
        raise RuntimeError("restore selection has no database")
    required = sum(row["size"] for row in rows) + config.min_free_bytes
    if shutil.disk_usage(config.spool).free < required:
        raise Blocked("insufficient disk for selected restore plus reserve")
    target = Path(tempfile.mkdtemp(prefix="restore-", dir=config.spool))
    try:
        # Exact includes avoid unintentionally restoring the entire 70+ GiB
        # historical source when only a weekly rotating sample was requested.
        include = target / "include.txt"
        include.write_text("\n".join("/" + restore_relative(row["backup_path"]).as_posix() for row in rows) + "\n", encoding="utf-8")
        client.run("restore", snapshot, "--target", str(target), "--include-file", str(include), "--verify")
        return {"snapshot_id": snapshot, "full": full, **verify_restore(target, rows)}
    finally:
        # Only the unique private restore directory created by this call.
        if target.parent != config.spool or target.is_symlink():
            raise ValueError("unsafe restore cleanup target")
        shutil.rmtree(target)


def _restore_due(last: dict, current: datetime) -> bool:
    value = last.get("restore_verified_at")
    return not value or current - datetime.fromisoformat(value) >= timedelta(days=7)


def run_backup(config: Config, *, force: bool = False) -> dict:
    ready = readiness(config)
    if ready["result"] != "PASS":
        raise Blocked("; ".join(ready["reasons"]))
    config.spool.mkdir(parents=True, exist_ok=True, mode=0o700)
    with production_lock(config.spool / "backup.lock", "drive-backup"):
        return _run_locked(config, force=force)


def _run_locked(config: Config, *, force: bool) -> dict:
    guard_window()
    current = now()
    last = _load(config.spool / "latest-verified.json")
    requests = sorted((config.spool / "requests").glob("*.json"))
    if not force and not requests and last.get("backup_date") == current.date().isoformat():
        return {"schema": SCHEMA, "result": "PASS", "action": "NO_WORK", "snapshot_id": last["snapshot_id"]}
    run_id = current.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:12]
    stage = Path(tempfile.mkdtemp(prefix="freeze-", dir=config.spool))
    receipt = {"schema": SCHEMA, "run_id": run_id, "started_at": current.isoformat(),
               "result": "RUNNING", "request_ids": [path.stem for path in requests]}
    atomic_json(config.spool / "receipts" / f"{run_id}.RUNNING.json", receipt, immutable=True)
    try:
        previous_manifest = _load(config.spool / last["manifest_path"]) if last else {}
        if last and digest(config.spool / last["manifest_path"]) != last["manifest_sha256"]:
            raise ValueError("previous source manifest hash differs from accepted receipt")
        def source_guard() -> None:
            guard_window()
            if shutil.disk_usage(config.spool).free < config.min_free_bytes:
                raise Blocked("backup spool free-space floor reached")
        manifest = freeze(config.data, stage, controls=config.controls, guard=source_guard, prior=previous_manifest)
        manifest_path = config.spool / "manifests" / f"{run_id}.json"
        atomic_json(manifest_path, manifest, immutable=True)
        receipt.update(manifest_path=f"manifests/{run_id}.json", manifest_sha256=digest(manifest_path),
                       content_sha256=manifest["content_sha256"])
        client = Restic(config)
        # Check is independent from source freshness. Even no-content-change
        # daily backups verify the repository before acknowledging the request.
        client.run("check")
        unchanged = last.get("content_sha256") == manifest["content_sha256"]
        if unchanged:
            snapshot = last["snapshot_id"]
            remote_manifest = previous_manifest
            receipt.update(action="UNCHANGED", uploaded_bytes=0, snapshot_id=snapshot,
                           manifest_path=last["manifest_path"], manifest_sha256=last["manifest_sha256"])
        else:
            file_list = stage / "files.raw"
            paths = [row["backup_path"] for row in manifest["files"]] + [manifest_path.as_posix()]
            file_list.write_bytes(b"\x00".join(path.encode("utf-8") for path in paths) + b"\x00")
            output = client.run("backup", "--json", "--tag", TAG, "--group-by", "host,tags",
                                "--files-from-raw", str(file_list))
            summary = _summary(output)
            snapshot = summary["snapshot_id"]
            receipt.update(action="BACKUP", snapshot_id=snapshot, summary=summary,
                           uploaded_bytes=summary.get("data_added_packed", summary.get("data_added")))
            remote_manifest = manifest
            client.run("check")
        verify_direct_sources(manifest)
        stats = json.loads(client.run("stats", "--mode", "raw-data", "--json"))
        receipt.update(repository_check="PASS", repository_stored_bytes=stats.get("total_size"))
        due = _restore_due(last, current)
        if due:
            restore = restore_snapshot(config, client, snapshot, remote_manifest,
                                       full=not last, rotation=int(last.get("restore_rotation", 0)),
                                       manifest_path=config.spool / receipt["manifest_path"])
            receipt.update(restore=restore, restore_verified_at=now().isoformat(),
                           restore_rotation=int(last.get("restore_rotation", 0)) + 1)
        else:
            receipt.update(restore={"result": "NOT_DUE"}, restore_verified_at=last["restore_verified_at"],
                           restore_rotation=last.get("restore_rotation", 0))
        receipt.update(result="PASS", finished_at=now().isoformat(), backup_date=current.date().isoformat())
        atomic_json(config.spool / "receipts" / f"{run_id}.PASS.json", receipt, immutable=True)
        atomic_json(config.spool / "latest-verified.json", receipt)
        for path in requests:
            path.unlink(missing_ok=True)
        return receipt
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        receipt.update(result="BLOCKED" if isinstance(error, Blocked) else "FAIL",
                       finished_at=now().isoformat(), error=str(error))
        atomic_json(config.spool / "receipts" / f"{run_id}.{receipt['result']}.json", receipt, immutable=True)
        raise
    finally:
        if stage.parent != config.spool or stage.is_symlink():
            raise ValueError("unsafe freeze cleanup target")
        shutil.rmtree(stage)


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("command", choices=("readiness", "init", "run", "request", "restore"))
    cli.add_argument("--data-root", type=Path, default=Path(os.environ.get("AR_LOCAL_DATA_ROOT", "/srv/ar-local/data")))
    cli.add_argument("--spool", type=Path, default=Path(os.environ.get("AR_LOCAL_DRIVE_BACKUP_SPOOL", "/var/lib/ar-local-drive-backup")))
    cli.add_argument("--repository", default=os.environ.get("RESTIC_REPOSITORY", ""))
    cli.add_argument("--password-file", type=Path, default=Path(os.environ.get("RESTIC_PASSWORD_FILE", "/var/lib/ar-local-drive-backup/credentials/restic.password")))
    cli.add_argument("--rclone-config", type=Path, default=Path(os.environ.get("RCLONE_CONFIG", "/var/lib/ar-local-drive-backup/credentials/rclone.conf")))
    cli.add_argument("--control-file", action="append", type=Path, default=[])
    cli.add_argument("--force", action="store_true", help="audit source now even when today's queue is empty")
    cli.add_argument("--remote", action="store_true", help="also verify repository access")
    cli.add_argument("--full", action="store_true", help="restore and verify all retained source bytes")
    cli.add_argument("--reason", default="terminal-observation")
    return cli


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    config = Config(args.data_root, args.spool, args.repository, args.password_file, args.rclone_config, args.control_file)
    try:
        if args.command == "readiness":
            result = readiness(config, remote=args.remote)
        elif args.command == "request":
            marker = request_backup(args.reason, spool=args.spool)
            result = {"result": "PASS", "queued": marker.name}
        elif args.command == "init":
            result = readiness(config)
            if result["result"] == "PASS":
                config.spool.mkdir(parents=True, exist_ok=True, mode=0o700)
                with production_lock(config.spool / "backup.lock", "drive-backup-init"):
                    Restic(config).run("init", "--repository-version", "2")
                result = {"result": "PASS", "action": "INITIALIZED", "backup": "NOT_RUN"}
        elif args.command == "restore":
            ready = readiness(config)
            if ready["result"] != "PASS":
                raise Blocked("; ".join(ready["reasons"]))
            with production_lock(config.spool / "backup.lock", "drive-restore"):
                last = _load(config.spool / "latest-verified.json")
                if not last:
                    raise Blocked("no accepted backup receipt")
                manifest = _load(config.spool / last["manifest_path"])
                if digest(config.spool / last["manifest_path"]) != last["manifest_sha256"]:
                    raise ValueError("accepted source manifest hash differs")
                result = restore_snapshot(config, Restic(config), last["snapshot_id"], manifest,
                                          full=args.full, manifest_path=config.spool / last["manifest_path"])
                atomic_json(config.spool / "receipts" / ("restore-" + uuid.uuid4().hex + ".json"), result, immutable=True)
        else:
            result = run_backup(config, force=args.force)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        result = {"schema": SCHEMA, "result": "BLOCKED" if isinstance(error, Blocked) else "FAIL", "error": str(error)}
    print(json.dumps(result, sort_keys=True))
    return {"PASS": 0, "BLOCKED": 2}.get(result["result"], 1)


if __name__ == "__main__":
    sys.exit(main())
