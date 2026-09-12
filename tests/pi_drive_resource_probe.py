"""Operator-only tiny local-backend proof; never reads production/cloud data.

Run in the private systemd sandbox documented in GOOGLE_DRIVE_BACKUP.md.
This is a resource probe, not evidence of Google Drive backup commissioning.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import time
from dataclasses import replace
from datetime import datetime, time as clock_time
from pathlib import Path
from zoneinfo import ZoneInfo

import pi_drive_backup_resources as resources


def guard():
    current = datetime.now(ZoneInfo("Australia/Hobart")).time().replace(tzinfo=None)
    if clock_time(0, 30) <= current < clock_time(3, 30):
        raise RuntimeError("daily ingest quiet window")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_restic(root):
    root.mkdir(mode=0o700)
    (root / "source").mkdir()
    password = root / "password"
    password.write_text(secrets.token_urlsafe(32))
    password.chmod(0o600)
    config = root / "rclone.conf"
    config.write_text("[private_fixture]\ntype = local\n")
    config.chmod(0o600)
    env = {**os.environ, "RESTIC_REPOSITORY": f"rclone:private_fixture:{root}/repository",
        "RESTIC_PASSWORD_FILE": str(password), "RCLONE_CONFIG": str(config),
        "RESTIC_CACHE_DIR": str(root / "cache"), "RCLONE_BWLIMIT": "8M", "RCLONE_TRANSFERS": "2"}
    for key in ("RESTIC_PASSWORD", "RESTIC_PASSWORD_COMMAND", "RESTIC_REPOSITORY_FILE"):
        env.pop(key, None)
    def restic(*args):
        result = subprocess.run(["restic", "--compression", "auto", "--pack-size", "16", *args],
            env=env, capture_output=True, timeout=60, check=False)
        if result.returncode:
            raise RuntimeError(f"local fixture restic {args[0]} exit {result.returncode}; output withheld")
        return result.stdout.decode()
    source = root / "source"
    database = source / "resource-probe.sqlite"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE resource_probe (iteration INTEGER PRIMARY KEY)")
        db.execute("INSERT INTO resource_probe VALUES (1)")
    (source / "eight-mib.bin").write_bytes(os.urandom(8 * resources.MIB))
    restic("init", "--repository-version", "2")
    first = restic("backup", "--json", str(source))
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO resource_probe VALUES (2)")
    second = restic("backup", "--json", str(source))
    restic("check")
    snapshots = json.loads(restic("snapshots", "--json"))
    latest = next(json.loads(line)["snapshot_id"] for line in second.splitlines() if json.loads(line).get("message_type") == "summary")
    restored = root / "restored"
    restic("restore", latest, "--target", str(restored), "--verify")
    selected = restored / source.as_posix().lstrip("/")
    hashes = {item.name: sha(item) for item in source.iterdir()}
    if hashes != {item.name: sha(item) for item in selected.iterdir()}:
        raise RuntimeError("local restore hash mismatch")
    with sqlite3.connect((selected / database.name).as_uri() + "?mode=ro", uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)] or db.execute("SELECT iteration FROM resource_probe ORDER BY iteration").fetchall() != [(1,), (2,)]:
            raise RuntimeError("local fixture restore integrity failed")
    def summary(output):
        return next(json.loads(line) for line in output.splitlines() if json.loads(line).get("message_type") == "summary")
    proof = {"result": "PASS", "scope": "tiny local Restic plus rclone backend; no cloud or production data",
        "snapshots": len(snapshots), "file_sha256": hashes,
        "first_added_packed": summary(first)["data_added_packed"],
        "second_added_packed": summary(second)["data_added_packed"], "sqlite_integrity": "ok"}
    (root / "verification.json").write_text(json.dumps(proof, indent=2) + "\n")
    # This temporary local-only encryption key is not a real backup credential.
    password.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("normal", "memory", "orphan", "child"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--child-action", choices=("normal", "memory", "orphan"))
    args = parser.parse_args()
    if args.mode == "child":
        if args.child_action == "normal":
            local_restic(args.output / "fixture")
        elif args.child_action == "memory":
            blocks = []
            for _ in range(20):
                blocks.append(bytearray(8 * resources.MIB))
                time.sleep(.03)
            time.sleep(10)
        else:
            subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        return 0
    args.output.mkdir(parents=True, mode=0o700)
    limits = replace(resources.Limits(), runtime_seconds=120)
    if args.mode == "memory":
        limits = replace(limits, workload_bytes=64 * resources.MIB, margin_bytes=8 * resources.MIB,
                         reserve_bytes=2552 * resources.MIB)
    result = resources.supervise([sys.executable, str(Path(__file__).resolve()), "child", "--output", str(args.output),
        "--child-action", args.mode], args.output / "resources.json", limits, guard=guard)
    expected = "PASS" if args.mode == "normal" else "FAIL"
    passed = result["result"] == expected and result["group_clean"] is True
    print(json.dumps({"probe": args.mode, "expected": expected, "result": result["result"], "verified": passed}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
