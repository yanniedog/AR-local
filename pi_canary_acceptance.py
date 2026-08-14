#!/usr/bin/env python3
"""Validate the immutable acceptance record required for Pi activation."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence


SCHEMA_VERSION = 1
MAX_MANIFEST_BYTES = 64 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
CANDIDATE_GENERATION_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
REQUIRED_ACCEPTANCE_GATES = (
    "preservation_restore",
    "historical_integrity",
    "shadow_ingest",
    "producer_contracts",
    "stable_app_compatibility",
    "candidate_emulator_matrix",
    "candidate_device_matrix",
    "public_candidate_bytes",
)
REQUIRED_FIELDS = (
    "schema_version",
    "repository",
    "target_commit",
    "status",
    "candidate_generation",
    "preservation_snapshot_sha256",
    "completed_at",
    "acceptance_gates",
)


class CanaryAcceptanceError(ValueError):
    """The canary manifest is not safe to authorize for activation."""


def _required_string(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise CanaryAcceptanceError(f"{name} must be a non-empty string")
    return value.strip()


def verify_canary_acceptance(
    path: Path,
    *,
    expected_sha256: str,
    expected_commit: str,
    expected_repository: str,
) -> dict[str, Any]:
    """Return a verified manifest or raise ``CanaryAcceptanceError``."""

    if not SHA256_RE.fullmatch(expected_sha256):
        raise CanaryAcceptanceError("expected SHA-256 must be 64 lowercase hex characters")
    if not COMMIT_RE.fullmatch(expected_commit):
        raise CanaryAcceptanceError("expected commit must be 40 lowercase hex characters")
    if not REPOSITORY_RE.fullmatch(expected_repository):
        raise CanaryAcceptanceError("expected repository must be owner/name")
    if path.is_symlink() or not path.is_file():
        raise CanaryAcceptanceError("manifest must be one regular non-symlink file")

    raw = path.read_bytes()
    if not raw or len(raw) > MAX_MANIFEST_BYTES:
        raise CanaryAcceptanceError(
            f"manifest size must be 1..{MAX_MANIFEST_BYTES} bytes"
        )
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(actual_sha256, expected_sha256):
        raise CanaryAcceptanceError(
            f"manifest SHA-256 mismatch ({actual_sha256} != {expected_sha256})"
        )

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanaryAcceptanceError(f"manifest is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise CanaryAcceptanceError("manifest root must be an object")
    unexpected_fields = sorted(set(payload) - set(REQUIRED_FIELDS))
    if unexpected_fields:
        raise CanaryAcceptanceError(
            "manifest contains unexpected fields: " + ", ".join(unexpected_fields)
        )
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise CanaryAcceptanceError(
            f"schema_version must be {SCHEMA_VERSION}"
        )
    if _required_string(payload, "repository") != expected_repository:
        raise CanaryAcceptanceError("manifest repository does not match deployment repository")
    if _required_string(payload, "target_commit") != expected_commit:
        raise CanaryAcceptanceError("manifest target_commit does not match approved commit")
    if payload.get("status") != "passed":
        raise CanaryAcceptanceError("manifest status must be passed")
    candidate_generation = _required_string(payload, "candidate_generation")
    if not CANDIDATE_GENERATION_RE.fullmatch(candidate_generation):
        raise CanaryAcceptanceError(
            "candidate_generation must be 1..128 safe identifier characters"
        )
    snapshot_sha256 = _required_string(payload, "preservation_snapshot_sha256")
    if not SHA256_RE.fullmatch(snapshot_sha256):
        raise CanaryAcceptanceError(
            "preservation_snapshot_sha256 must be 64 lowercase hex characters"
        )
    completed_at = _required_string(payload, "completed_at")
    try:
        completed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CanaryAcceptanceError("completed_at must be an ISO-8601 timestamp") from exc
    if completed.tzinfo is None:
        raise CanaryAcceptanceError("completed_at must include a timezone")

    gates = payload.get("acceptance_gates")
    if not isinstance(gates, dict):
        raise CanaryAcceptanceError("acceptance_gates must be an object")
    unexpected_gates = sorted(set(gates) - set(REQUIRED_ACCEPTANCE_GATES))
    if unexpected_gates:
        raise CanaryAcceptanceError(
            "acceptance_gates contains unexpected fields: "
            + ", ".join(unexpected_gates)
        )
    failed = [name for name in REQUIRED_ACCEPTANCE_GATES if gates.get(name) is not True]
    if failed:
        raise CanaryAcceptanceError(
            "required acceptance gates are missing or not true: " + ", ".join(failed)
        )
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-repository", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = verify_canary_acceptance(
            args.manifest,
            expected_sha256=args.expected_sha256,
            expected_commit=args.expected_commit,
            expected_repository=args.expected_repository,
        )
    except (OSError, CanaryAcceptanceError) as exc:
        print(f"pi_canary_acceptance: rejected: {exc}", file=sys.stderr)
        return 2
    print(
        "pi_canary_acceptance: verified "
        f"target_commit={payload['target_commit']} "
        f"candidate_generation={payload['candidate_generation']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
