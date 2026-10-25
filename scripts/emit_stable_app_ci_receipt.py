#!/usr/bin/env python3
"""Emit a fail-closed stable_app_compatibility source receipt from mobile CI.

Never invents PASS. Requires:
  - ci_exit_code == 0
  - CI log containing Jest "Test Suites: N passed" and "Tests: M passed" with N,M > 0
  - 40-hex target_commit (AR-local canary freeze) and ar_app_head
  - candidate_generation + preservation_snapshot_sha256 (canonicalize→bind fields)

Canonicalize + bind separately via pi_canary_app_matrix_receipts.py /
pi_canary_gate_bind.py once those land (#1009 / #1005).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CANDIDATE_GENERATION_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
# Allow preceding skipped/failed counts: "Tests: 2 skipped, 5025 passed, 5027 total"
SUITES_RE = re.compile(r"Test Suites:[^\n]*?(\d+)\s+passed")
TESTS_RE = re.compile(r"Tests:[^\n]*?(\d+)\s+passed")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_jest_counts(log_text: str) -> tuple[int, int]:
    suites_matches = SUITES_RE.findall(log_text)
    tests_matches = TESTS_RE.findall(log_text)
    if not suites_matches or not tests_matches:
        return 0, 0
    return int(suites_matches[-1]), int(tests_matches[-1])


def build_receipt(
    *,
    target_commit: str,
    ar_app_head: str,
    log_path: Path,
    ci_exit_code: int,
    candidate_generation: str,
    preservation_snapshot_sha256: str,
    worktree: str | None = None,
) -> dict:
    if not COMMIT_RE.fullmatch(target_commit):
        raise SystemExit("target_commit must be 40 lowercase hex")
    if not COMMIT_RE.fullmatch(ar_app_head):
        raise SystemExit("ar_app_head must be 40 lowercase hex")
    if not CANDIDATE_GENERATION_RE.fullmatch(candidate_generation):
        raise SystemExit(
            "candidate_generation must match ^[A-Za-z0-9._:-]{1,128}$"
        )
    if not SHA256_RE.fullmatch(preservation_snapshot_sha256):
        raise SystemExit("preservation_snapshot_sha256 must be 64 lowercase hex")
    if not log_path.is_file() or log_path.is_symlink():
        raise SystemExit(f"ci log missing: {log_path}")

    log_bytes = log_path.read_bytes()
    log_sha = hashlib.sha256(log_bytes).hexdigest()
    suites, tests = parse_jest_counts(log_bytes.decode("utf-8", errors="replace"))

    findings: list[str] = []
    if ci_exit_code != 0:
        findings.append(f"ci_exit_code={ci_exit_code}, require 0")
    if suites <= 0 or tests <= 0:
        findings.append(f"jest counts not positive (suites={suites}, tests={tests})")

    result = "PASS" if not findings else "FAIL"
    payload: dict = {
        "schema_version": 1,
        "gate": "stable_app_compatibility",
        "target_commit": target_commit,
        "result": result,
        "completed_at": utc_now_iso(),
        "candidate_generation": candidate_generation,
        "preservation_snapshot_sha256": preservation_snapshot_sha256,
        "ar_app_repository": "yanniedog/AR-app",
        "ar_app_head": ar_app_head,
        "ci": {
            "command": "npm run ci",
            "exit_code": int(ci_exit_code),
            "suites": suites,
            "tests": tests,
            "log_path": str(log_path).replace("\\", "/"),
            "log_sha256": log_sha,
        },
        "findings": findings,
        "note": (
            "AR-local candidate trees have no mobile/ (#483). "
            "Receipt binds canary freeze target_commit; CI ran on AR-app head. "
            "RE-FREEZE before assemble if tip moved."
        ),
    }
    if worktree:
        payload["worktree"] = worktree
    return payload


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target-commit", required=True)
    p.add_argument("--ar-app-head", required=True)
    p.add_argument("--ci-log", type=Path, required=True)
    p.add_argument("--ci-exit-code", type=int, required=True)
    p.add_argument("--candidate-generation", required=True)
    p.add_argument("--preservation-snapshot-sha256", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--worktree", default=None)
    args = p.parse_args(argv)

    payload = build_receipt(
        target_commit=args.target_commit.lower(),
        ar_app_head=args.ar_app_head.lower(),
        log_path=args.ci_log,
        ci_exit_code=args.ci_exit_code,
        candidate_generation=args.candidate_generation,
        preservation_snapshot_sha256=args.preservation_snapshot_sha256.lower(),
        worktree=args.worktree,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if args.output.exists() or args.output.is_symlink():
        raise SystemExit(f"refusing to overwrite: {args.output}")
    args.output.write_bytes(raw)
    print(
        json.dumps(
            {
                "path": str(args.output),
                "result": payload["result"],
                "sha256": hashlib.sha256(raw).hexdigest(),
                "suites": payload["ci"]["suites"],
                "tests": payload["ci"]["tests"],
            },
            sort_keys=True,
        )
    )
    return 0 if payload["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
