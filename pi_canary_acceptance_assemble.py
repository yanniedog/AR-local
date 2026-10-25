#!/usr/bin/env python3
"""Assemble canary-acceptance.json only from explicit per-gate PASS evidence.

This producer does not invent gate results. Missing files, UNKNOWN, FAIL, or
mismatched target_commit never become true. A passing manifest is written only
when every required gate has a valid evidence file with result == PASS.

Gate evidence shape: contracts/canary-gate-evidence-v1.schema.json
Output shape: contracts/canary-acceptance-v1.schema.json (verified via
pi_canary_acceptance patterns before write).

External / human-supplied gates (no in-repo automated emitter yet):
  - candidate_emulator_matrix
  - candidate_device_matrix
  - shadow_ingest (ops recipe only)
  - producer_contracts (fragmented CI; needs binder receipt)
  - stable_app_compatibility (app/mobile evidence)
Supply those as explicit evidence JSON files; do not hand-edit the assembled
manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import pi_canary_acceptance as canary

GATE_EVIDENCE_SCHEMA_VERSION = 1
ALLOWED_RESULTS = frozenset({"PASS", "FAIL", "UNKNOWN"})


class CanaryAssembleError(ValueError):
    """Gate evidence cannot authorize a canary acceptance manifest."""


def _load_json_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise CanaryAssembleError(f"gate evidence must be a regular file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanaryAssembleError(f"gate evidence unreadable JSON ({path}): {exc}") from exc
    if not isinstance(payload, dict):
        raise CanaryAssembleError(f"gate evidence root must be an object: {path}")
    return payload


def _require_iso_timestamp(value: object, *, field: str, path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CanaryAssembleError(f"{field} must be a non-empty string ({path})")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CanaryAssembleError(
            f"{field} must be ISO-8601 with timezone ({path})"
        ) from exc
    if parsed.tzinfo is None:
        raise CanaryAssembleError(f"{field} must include a timezone ({path})")
    return text


def evaluate_gate_evidence(
    path: Path,
    *,
    expected_gate: str,
    expected_commit: str,
) -> tuple[bool, str]:
    """Return (passed, reason). Never treats missing/UNKNOWN as PASS."""

    try:
        payload = _load_json_object(path)
    except CanaryAssembleError as exc:
        return False, str(exc)

    if payload.get("schema_version") != GATE_EVIDENCE_SCHEMA_VERSION:
        return False, f"{path}: schema_version must be {GATE_EVIDENCE_SCHEMA_VERSION}"
    gate = payload.get("gate")
    if gate != expected_gate:
        return False, f"{path}: gate must be {expected_gate!r} (got {gate!r})"
    result = payload.get("result")
    if result not in ALLOWED_RESULTS:
        return False, f"{path}: result must be one of {sorted(ALLOWED_RESULTS)}"
    target = payload.get("target_commit")
    if not isinstance(target, str) or not canary.COMMIT_RE.fullmatch(target):
        return False, f"{path}: target_commit must be 40 lowercase hex"
    if target != expected_commit:
        return (
            False,
            f"{path}: target_commit mismatch ({target} != {expected_commit})",
        )
    try:
        _require_iso_timestamp(payload.get("completed_at"), field="completed_at", path=path)
    except CanaryAssembleError as exc:
        return False, str(exc)

    evidence = payload.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return False, f"{path}: evidence must be a non-empty array"
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            return False, f"{path}: evidence[{index}] must be an object"
        item_path = item.get("path")
        digest = item.get("sha256")
        if not isinstance(item_path, str) or not item_path.strip():
            return False, f"{path}: evidence[{index}].path must be non-empty"
        if not isinstance(digest, str) or not canary.SHA256_RE.fullmatch(digest):
            return False, f"{path}: evidence[{index}].sha256 must be 64 lowercase hex"
        unexpected = sorted(set(item) - {"path", "sha256"})
        if unexpected:
            return False, f"{path}: evidence[{index}] unexpected fields: {', '.join(unexpected)}"

    unexpected_fields = sorted(
        set(payload) - {"schema_version", "gate", "result", "target_commit", "completed_at", "evidence", "notes"}
    )
    if unexpected_fields:
        return False, f"{path}: unexpected fields: {', '.join(unexpected_fields)}"

    if result == "UNKNOWN":
        return False, f"{path}: result is UNKNOWN (external evidence not supplied)"
    if result != "PASS":
        return False, f"{path}: result is {result} (not PASS)"
    return True, f"{path}: PASS"


def resolve_gate_paths(
    *,
    gate_evidence_dir: Optional[Path],
    gate_files: Mapping[str, Path],
) -> dict[str, Path]:
    """Map each required gate to an evidence path. Missing paths stay absent."""

    resolved: dict[str, Path] = {}
    if gate_evidence_dir is not None:
        if not gate_evidence_dir.is_dir():
            raise CanaryAssembleError(
                f"gate evidence directory does not exist: {gate_evidence_dir}"
            )
        for gate in canary.REQUIRED_ACCEPTANCE_GATES:
            candidate = gate_evidence_dir / f"{gate}.json"
            if candidate.is_file() and not candidate.is_symlink():
                resolved[gate] = candidate
    for gate, path in gate_files.items():
        if gate not in canary.REQUIRED_ACCEPTANCE_GATES:
            raise CanaryAssembleError(f"unknown gate name: {gate}")
        resolved[gate] = path
    return resolved


def collect_gate_results(
    gate_paths: Mapping[str, Path],
    *,
    expected_commit: str,
) -> tuple[dict[str, bool], list[str]]:
    """Evaluate all eight gates. Missing files are failures, never true."""

    gates: dict[str, bool] = {}
    problems: list[str] = []
    for gate in canary.REQUIRED_ACCEPTANCE_GATES:
        path = gate_paths.get(gate)
        if path is None:
            gates[gate] = False
            problems.append(f"{gate}: missing evidence file")
            continue
        passed, reason = evaluate_gate_evidence(
            path,
            expected_gate=gate,
            expected_commit=expected_commit,
        )
        gates[gate] = passed
        if not passed:
            problems.append(f"{gate}: {reason}")
    return gates, problems


def build_acceptance_payload(
    *,
    repository: str,
    target_commit: str,
    candidate_generation: str,
    preservation_snapshot_sha256: str,
    completed_at: str,
    gates: Mapping[str, bool],
) -> dict[str, Any]:
    if not canary.REPOSITORY_RE.fullmatch(repository):
        raise CanaryAssembleError("repository must be owner/name")
    if not canary.COMMIT_RE.fullmatch(target_commit):
        raise CanaryAssembleError("target_commit must be 40 lowercase hex characters")
    if not canary.CANDIDATE_GENERATION_RE.fullmatch(candidate_generation):
        raise CanaryAssembleError(
            "candidate_generation must be 1..128 safe identifier characters"
        )
    if not canary.SHA256_RE.fullmatch(preservation_snapshot_sha256):
        raise CanaryAssembleError(
            "preservation_snapshot_sha256 must be 64 lowercase hex characters"
        )
    _require_iso_timestamp(completed_at, field="completed_at", path=Path("<cli>"))

    failed = [name for name in canary.REQUIRED_ACCEPTANCE_GATES if gates.get(name) is not True]
    if failed:
        raise CanaryAssembleError(
            "required acceptance gates are missing or not evidenced PASS: "
            + ", ".join(failed)
        )

    return {
        "schema_version": canary.SCHEMA_VERSION,
        "repository": repository,
        "target_commit": target_commit,
        "status": "passed",
        "candidate_generation": candidate_generation,
        "preservation_snapshot_sha256": preservation_snapshot_sha256,
        "completed_at": completed_at,
        "acceptance_gates": {
            name: True for name in canary.REQUIRED_ACCEPTANCE_GATES
        },
    }


def encode_manifest(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(payload), sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def write_manifest_if_authorized(
    output: Path,
    payload: Mapping[str, Any],
) -> str:
    """Write only after local contract checks; return SHA-256 of bytes written."""

    raw = encode_manifest(payload)
    if not raw or len(raw) > canary.MAX_MANIFEST_BYTES:
        raise CanaryAssembleError(
            f"manifest size must be 1..{canary.MAX_MANIFEST_BYTES} bytes"
        )
    digest = hashlib.sha256(raw).hexdigest()
    if output.exists():
        raise CanaryAssembleError(f"refusing to overwrite existing file: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    if tmp.exists():
        raise CanaryAssembleError(f"refusing to overwrite existing temp file: {tmp}")
    tmp.write_bytes(raw)
    # Verify with the same consumer rules before promoting.
    canary.verify_canary_acceptance(
        tmp,
        expected_sha256=digest,
        expected_commit=str(payload["target_commit"]),
        expected_repository=str(payload["repository"]),
    )
    tmp.replace(output)
    return digest


def assemble_canary_acceptance(
    *,
    repository: str,
    target_commit: str,
    candidate_generation: str,
    preservation_snapshot_sha256: str,
    completed_at: str,
    output: Path,
    gate_paths: Mapping[str, Path],
) -> tuple[dict[str, Any], str]:
    gates, problems = collect_gate_results(gate_paths, expected_commit=target_commit)
    if problems:
        raise CanaryAssembleError(
            "cannot assemble canary-acceptance.json; unresolved gates:\n- "
            + "\n- ".join(problems)
        )
    payload = build_acceptance_payload(
        repository=repository,
        target_commit=target_commit,
        candidate_generation=candidate_generation,
        preservation_snapshot_sha256=preservation_snapshot_sha256,
        completed_at=completed_at,
        gates=gates,
    )
    digest = write_manifest_if_authorized(output, payload)
    return dict(payload), digest


def _parse_gate_file(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError(
            "expected gate=path (example: preservation_restore=/path/to/file.json)"
        )
    gate, raw_path = value.split("=", 1)
    gate = gate.strip()
    if gate not in canary.REQUIRED_ACCEPTANCE_GATES:
        raise argparse.ArgumentTypeError(f"unknown gate: {gate}")
    if not raw_path.strip():
        raise argparse.ArgumentTypeError(f"empty path for gate {gate}")
    return gate, Path(raw_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--candidate-generation", required=True)
    parser.add_argument("--preservation-snapshot-sha256", required=True)
    parser.add_argument(
        "--completed-at",
        default=None,
        help="ISO-8601 timestamp with timezone (default: now UTC)",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--gate-evidence-dir",
        type=Path,
        default=None,
        help="Directory containing <gate>.json evidence files for each required gate",
    )
    parser.add_argument(
        "--gate-file",
        action="append",
        default=[],
        type=_parse_gate_file,
        metavar="GATE=PATH",
        help="Explicit evidence path for one gate (repeatable; overrides dir entry)",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    completed_at = args.completed_at or datetime.now(timezone.utc).isoformat()
    try:
        gate_files = {gate: path for gate, path in args.gate_file}
        gate_paths = resolve_gate_paths(
            gate_evidence_dir=args.gate_evidence_dir,
            gate_files=gate_files,
        )
        if not gate_paths and args.gate_evidence_dir is None and not args.gate_file:
            raise CanaryAssembleError(
                "provide --gate-evidence-dir and/or one or more --gate-file GATE=PATH"
            )
        payload, digest = assemble_canary_acceptance(
            repository=args.repository,
            target_commit=args.target_commit,
            candidate_generation=args.candidate_generation,
            preservation_snapshot_sha256=args.preservation_snapshot_sha256,
            completed_at=completed_at,
            output=args.output,
            gate_paths=gate_paths,
        )
    except (OSError, CanaryAssembleError, canary.CanaryAcceptanceError) as exc:
        print(f"pi_canary_acceptance_assemble: rejected: {exc}", file=sys.stderr)
        return 2
    print(
        "pi_canary_acceptance_assemble: wrote "
        f"{args.output} sha256={digest} "
        f"target_commit={payload['target_commit']} "
        f"candidate_generation={payload['candidate_generation']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
