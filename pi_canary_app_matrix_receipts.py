#!/usr/bin/env python3
"""Fail-closed receipt templates for stable-app / emulator / device canary gates.

Never invents PASS. Emits UNKNOWN templates with exact operator steps, or
canonicalizes a real lab/CI receipt that already contains target_commit + PASS.
External-lab gates remain UNKNOWN until operators supply hashed lab evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import re

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
API_LEVEL_RE = re.compile(r"^[1-9][0-9]{0,2}$")
NON_EMPTY_STR = object()

GATES = (
    "stable_app_compatibility",
    "candidate_emulator_matrix",
    "candidate_device_matrix",
)

OPERATOR_STEPS: dict[str, list[str]] = {
    "stable_app_compatibility": [
        "Checkout exact TARGET_SHA (or mobile tree pinned to that commit).",
        "cd mobile && npm ci && npm run ci (Jest + script tests + doctor + typecheck + lint).",
        "Record package versions, APK/IPA digests if built, and CI log path.",
        "Write receipt JSON with gate=stable_app_compatibility, target_commit=TARGET_SHA, "
        "result=PASS, and ci={command,suites,tests}.",
        "Do not reuse PASS from a different candidate SHA (e.g. prior product-evidence head).",
        "Canonicalize: python pi_canary_app_matrix_receipts.py canonicalize "
        "--gate stable_app_compatibility --source-receipt <raw> --output <canonical> "
        "--target-commit TARGET_SHA",
        "Bind only the canonicalize output: python pi_canary_gate_bind.py "
        "stable-app-compatibility --receipt <canonical> ...",
    ],
    "candidate_emulator_matrix": [
        "Use released/candidate APK for TARGET_SHA only (docs/PRODUCT_EVIDENCE_ACCEPTANCE.md P-007).",
        "Agreed Android emulator: clean install + upgrade path.",
        "Exercise current + repaired historical acquisition; capture screenshots/logs.",
        "Preserve emulator userdata_snapshot path + userdata_snapshot_sha256 in receipt.",
        "Write receipt with gate=candidate_emulator_matrix, target_commit, "
        "devices=[{avd,api,abi,install_upgrade:true,acquisition_checks:true,"
        "userdata_snapshot,userdata_snapshot_sha256,result}], result=PASS|FAIL.",
        "Emulator PASS does not imply physical-device or native-v2 acceptance.",
        "Canonicalize: python pi_canary_app_matrix_receipts.py canonicalize "
        "--gate candidate_emulator_matrix --source-receipt <raw> --output <canonical> "
        "--target-commit TARGET_SHA",
        "Bind only the canonicalize output: python pi_canary_gate_bind.py "
        "candidate-emulator-matrix --receipt <canonical> ...",
    ],
    "candidate_device_matrix": [
        "Physical devices only; do not infer from emulator PASS.",
        "Install candidate build bound to TARGET_SHA on each required device.",
        "Record model, OS version, ABI, install_upgrade=true, acquisition_checks=true.",
        "Attach lab_run_id and evidence_archive_sha256.",
        "Write receipt with gate=candidate_device_matrix, target_commit, devices=[...], "
        "result=PASS only if matrix complete.",
        "Canonicalize: python pi_canary_app_matrix_receipts.py canonicalize "
        "--gate candidate_device_matrix --source-receipt <raw> --output <canonical> "
        "--target-commit TARGET_SHA",
        "Bind only the canonicalize output: python pi_canary_gate_bind.py "
        "candidate-device-matrix --receipt <canonical> ...",
    ],
}


class AppMatrixError(ValueError):
    """App matrix receipt cannot be written honestly."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> str:
    """Create-once publish; concurrent writers cannot overwrite via replace."""
    from cdr_atomic import ImmutablePathError, atomic_write_bytes

    if path.is_symlink():
        raise AppMatrixError(f"refusing to write through symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(dict(payload), sort_keys=True, indent=2) + "\n").encode("utf-8")
    try:
        atomic_write_bytes(path, raw, create_once=True)
    except ImmutablePathError as exc:
        raise AppMatrixError(str(exc)) from exc
    return hashlib.sha256(raw).hexdigest()


def emit_template(gate: str, output: Path, *, target_commit: str) -> dict[str, Any]:
    if gate not in GATES:
        raise AppMatrixError(f"unknown gate: {gate}")
    if not COMMIT_RE.fullmatch(target_commit):
        raise AppMatrixError("target_commit must be 40 lowercase hex")
    payload = {
        "schema_version": 1,
        "gate": gate,
        "target_commit": target_commit,
        "result": "UNKNOWN",
        "completed_at": utc_now_iso(),
        "reason": f"no lab/CI receipt bound to {target_commit} for {gate}",
        "operator_steps": OPERATOR_STEPS[gate],
        "external_lab_only": gate != "stable_app_compatibility",
        "forbidden": [
            "fabricating PASS",
            "binding a receipt from a different target_commit",
            "inferring device PASS from emulator",
            "inferring canary gate PASS from docs checklists alone",
        ],
    }
    digest = write_json_atomic(output, payload)
    return {"gate": gate, "path": str(output), "sha256": digest, "result": "UNKNOWN"}


def canonicalize(
    gate: str,
    source: Path,
    output: Path,
    *,
    target_commit: str,
) -> dict[str, Any]:
    if gate not in GATES:
        raise AppMatrixError(f"unknown gate: {gate}")
    if not COMMIT_RE.fullmatch(target_commit):
        raise AppMatrixError("target_commit must be 40 lowercase hex")
    raw = json.loads(source.read_text(encoding="utf-8"))
    findings: list[str] = []
    if not isinstance(raw, dict):
        raw = {}
        findings.append("receipt must be a JSON object")
    if raw.get("schema_version") != 1:
        findings.append("schema_version must be 1")
    if raw.get("gate") != gate:
        findings.append(f"gate is {raw.get('gate')!r}, not {gate!r}")
    if raw.get("target_commit") != target_commit:
        findings.append(
            f"target_commit mismatch: {raw.get('target_commit')!r} != {target_commit!r}"
        )
    status = raw.get("result") or raw.get("status")
    if status != "PASS":
        findings.append(f"result is {status!r}, not PASS")
    if gate == "stable_app_compatibility" and status == "PASS":
        ci = raw.get("ci")
        if not isinstance(ci, dict) or ci.get("command") != "npm run ci":
            findings.append("stable-app PASS requires ci.command='npm run ci'")
        elif any(
            type(ci.get(field)) is not int or ci[field] <= 0
            for field in ("suites", "tests")
        ):
            findings.append("stable-app PASS requires positive integer ci.suites and ci.tests")
    if gate.endswith("_matrix") and status == "PASS":
        devices = raw.get("devices")
        if not isinstance(devices, list) or not devices:
            findings.append("matrix PASS requires non-empty devices[]")
        else:
            required_fields = (
                ("avd", "api", "abi")
                if gate == "candidate_emulator_matrix"
                else ("model", "os", "abi", "install_upgrade", "acquisition_checks")
            )
            for index, device in enumerate(devices):
                if not isinstance(device, dict):
                    findings.append(f"devices[{index}] must be an object")
                    continue
                missing = [
                    field
                    for field in required_fields
                    if field not in device or device[field] in (None, "", [], {})
                ]
                if missing:
                    findings.append(
                        f"devices[{index}] missing required fields: {', '.join(missing)}"
                    )
                if device.get("result") != "PASS":
                    findings.append(f"devices[{index}].result must be PASS")
                if gate == "candidate_device_matrix":
                    for bool_field in ("install_upgrade", "acquisition_checks"):
                        if bool_field in device and device[bool_field] is not True:
                            findings.append(
                                f"devices[{index}].{bool_field} must be true for PASS"
                            )
    result = "PASS" if not findings else "FAIL"
    payload = {
        "schema_version": 1,
        "gate": gate,
        "target_commit": target_commit,
        "result": result,
        "completed_at": utc_now_iso(),
        "source_receipt": str(source),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "findings": findings,
    }
    digest = write_json_atomic(output, payload)
    return {
        "gate": gate,
        "path": str(output),
        "sha256": digest,
        "result": result,
        "findings": findings,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    t = sub.add_parser("template", help="Emit UNKNOWN template for one or all gates")
    t.add_argument("--gate", choices=GATES, action="append")
    t.add_argument("--output-dir", type=Path, required=True)
    t.add_argument("--target-commit", required=True)
    c = sub.add_parser("canonicalize", help="Validate lab/CI receipt → binder input")
    c.add_argument("--gate", required=True, choices=GATES)
    c.add_argument("--source-receipt", type=Path, required=True)
    c.add_argument("--output", type=Path, required=True)
    c.add_argument("--target-commit", required=True)
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "template":
        gates = args.gate or list(GATES)
        infos = []
        for gate in gates:
            out = args.output_dir / f"{gate}-template.json"
            infos.append(emit_template(gate, out, target_commit=args.target_commit))
        print(json.dumps(infos, indent=2))
        return 0
    if args.command == "canonicalize":
        info = canonicalize(
            args.gate,
            args.source_receipt,
            args.output,
            target_commit=args.target_commit,
        )
        print(json.dumps(info, sort_keys=True))
        return 0 if info["result"] == "PASS" else 1
    raise AppMatrixError(f"unknown command {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AppMatrixError as exc:
        print(f"pi_canary_app_matrix_receipts: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
