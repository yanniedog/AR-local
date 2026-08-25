"""Run the laptop pull backup only when its latest observation is stale."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence

import laptop_pull_backup as receiver


def local_path(target: Path, relative: str) -> Path:
    receiver.validate_relative_path(relative, {})
    parts = PurePosixPath(relative).parts
    candidate = target.joinpath(*parts)
    component = target
    for part in parts:
        component /= part
        if component.is_symlink():
            raise ValueError(f"backup metadata path is symlinked: {relative}")
    resolved = candidate.resolve(strict=True)
    if not receiver.is_within(resolved, target) or not resolved.is_file():
        raise ValueError(f"backup metadata path is unsafe: {relative}")
    return resolved


def manifest_file_hash(manifest: Mapping[str, object], relative: str) -> str | None:
    files = manifest.get("files")
    if not isinstance(files, list):
        return None
    matches = [item for item in files if isinstance(item, Mapping) and item.get("path") == relative]
    return str(matches[0].get("sha256")) if len(matches) == 1 else None


def latest_status(
    target: Path,
    remote: Mapping[str, object] | None,
    *,
    protected_sha: str | None = None,
    plan_commit: str | None = None,
) -> dict[str, object]:
    if not remote:
        return {"status": "STALE", "reason": "Pi has no completed observation"}
    date = str(remote.get("observation_date") or "")
    pointer_path = target / "catalog/latest-verified.json"
    try:
        if pointer_path.is_symlink():
            raise ValueError("latest pointer is symlinked")
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        receipt_path = local_path(target, str(pointer["receipt_path"]))
        if receiver.sha256_file(receipt_path) != pointer.get("receipt_sha256"):
            raise ValueError("latest receipt digest mismatch")
        receipt = json.loads(receipt_path.read_bytes())
        if (
            receipt.get("result") != "PASS"
            or receipt.get("kind") != "observation"
            or receipt.get("observation_date") != date
            or receipt.get("plan_document_id") != receiver.PLAN_DOCUMENT_ID
            or receipt.get("plan_version") != receiver.PLAN_VERSION
            or receipt.get("plan_sha256") != receiver.PLAN_SHA256
            or receipt.get("deviations") != []
        ):
            raise ValueError("latest receipt identity is invalid")
        if protected_sha is not None and receipt.get("protected_code_sha") != protected_sha:
            raise ValueError("latest receipt protected SHA is invalid")
        if plan_commit is not None and receipt.get("plan_git_commit") != plan_commit:
            raise ValueError("latest receipt plan commit is invalid")
        entries = receiver.catalog_entries(target / "catalog/generations.jsonl")
        matches = [
            item for item in entries
            if item.get("entry_sha256") == pointer.get("catalog_entry_sha256")
            and item.get("receipt_path") == pointer.get("receipt_path")
            and item.get("receipt_sha256") == pointer.get("receipt_sha256")
        ]
        if len(matches) != 1:
            raise ValueError("latest pointer is not bound to the catalog")
        manifest_path = local_path(target, receipt_path.with_name("source-manifest.json").relative_to(target).as_posix())
        archive = local_path(target, receipt_path.with_name("observation.tar.zst").relative_to(target).as_posix())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if receiver.sha256_file(manifest_path) != receipt.get("source_manifest_sha256"):
            raise ValueError("latest source manifest digest mismatch")
        receipt_candidate_sha = str(receipt.get("candidate_code_sha") or "")
        receipt_protected_sha = str(receipt.get("protected_code_sha") or "")
        receipt_plan_commit = str(receipt.get("plan_git_commit") or "")
        receiver.validate_manifest(
            manifest,
            "observation",
            receipt_candidate_sha,
            receipt_protected_sha,
            receipt_plan_commit,
        )
        if receiver.sha256_file(archive) != receipt.get("archive_sha256") or archive.stat().st_size != receipt.get("archive_bytes"):
            raise ValueError("latest archive bytes are invalid")
        if manifest_file_hash(manifest, f"data/state/{date}.done.json") != remote.get("completion_marker_sha256"):
            raise ValueError("Pi completion generation changed")
        if manifest_file_hash(manifest, "data/state/observation-pointers-v2/latest-observation.json") != remote.get("pointer_sha256"):
            raise ValueError("Pi observation pointer changed")
        checks = receipt.get("checks")
        if not isinstance(checks, Mapping) or not isinstance(checks.get("observation"), Mapping):
            raise ValueError("latest receipt lacks restore evidence")
        return {
            "status": "UP_TO_DATE",
            "observation_date": date,
            "receipt_path": str(receipt_path),
            "archive_sha256": receipt["archive_sha256"],
            "catalog_sequence": matches[0]["sequence"],
        }
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return {"status": "STALE", "observation_date": date, "reason": str(exc)}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--target", type=Path, required=True)
    value.add_argument("--host", default="ar-local-pi5-lan")
    value.add_argument("--source-helper", type=Path)
    value.add_argument("--recovery-image", type=Path, required=True)
    value.add_argument("--candidate-code-sha", required=True)
    value.add_argument("--protected-code-sha", required=True)
    value.add_argument("--plan-git-commit", required=True)
    value.add_argument("--operator")
    value.add_argument("--check-only", action="store_true")
    return value


def receiver_command(args: argparse.Namespace, command: str) -> list[str]:
    values = [
        sys.executable, str(Path(__file__).resolve().with_name("laptop_pull_backup.py")), command,
        "--target", str(args.target), "--host", args.host,
        "--recovery-image", str(args.recovery_image),
        "--candidate-code-sha", args.candidate_code_sha,
        "--protected-code-sha", args.protected_code_sha,
        "--plan-git-commit", args.plan_git_commit,
    ]
    if args.source_helper:
        values.extend(("--source-helper", str(args.source_helper)))
    if args.operator:
        values.extend(("--operator", args.operator))
    return values


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    preflight = subprocess.run(receiver_command(args, "preflight"), text=True, capture_output=True)
    if preflight.returncode:
        sys.stderr.write(preflight.stderr or preflight.stdout)
        return preflight.returncode
    listing = json.loads(preflight.stdout)
    target = Path(str(listing["target"])).resolve(strict=True)
    status = latest_status(
        target,
        listing.get("latest_observation"),
        protected_sha=args.protected_code_sha,
        plan_commit=args.plan_git_commit,
    )
    if status["status"] == "UP_TO_DATE":
        print(json.dumps({"ok": True, "result": "PASS", "action": "NO_WRITE", **status}, indent=2, sort_keys=True))
        return 0
    if args.check_only:
        print(json.dumps({"ok": False, "result": "BLOCKED", "action": "BACKUP_REQUIRED", **status}, indent=2, sort_keys=True))
        return 1
    return subprocess.run(receiver_command(args, "backup-latest")).returncode


if __name__ == "__main__":
    raise SystemExit(main())
