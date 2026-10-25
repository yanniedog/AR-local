#!/usr/bin/env python3
"""Bind real artifacts into canary-gate-evidence-v1 files (fail-closed).

Each subcommand validates real receipts/scripts before emitting PASS.
Missing prerequisites emit UNKNOWN or FAIL — never invent PASS.

Examples:
  python pi_canary_gate_bind.py producer-contracts \
    --target-commit <sha> --gate-dir .work/canary-gates/<sha> \
    --candidate-generation prep-... --preservation-snapshot-sha256 <64hex>

  python pi_canary_gate_bind.py harness \
    --target-commit <sha> --gate-dir .work/canary-gates/<sha> \
    --candidate-generation prep-... --preservation-snapshot-sha256 <64hex>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import pi_canary_gate_emit as emit
from pi_canary_gate_bind_ops import (
    CONTRACTS_DIR,
    GateBindError,
    ROOT,
    _require_commit,
    _require_generation,
    _require_snapshot,
    bind_historical_integrity,
    bind_preservation_restore,
    bind_producer_contracts,
    bind_public_candidate_bytes,
)
from pi_canary_gate_bind_receipts import bind_receipt_gate

def collect_pi_readonly_inventory() -> dict[str, Any]:
    """Best-effort read-only SSH inventory for preservation/shadow blockers."""

    script = r"""
set -e
echo '{'
echo '"hostname":"'"$(hostname)"'",'
echo '"pi_head":"'"$(git -C /srv/ar-local/AR-local rev-parse HEAD 2>/dev/null || echo unknown)"'",'
echo '"backup_gate":"'"$(test -x /usr/local/bin/ar-local-backup-gate && echo present || echo absent)"'",'
echo '"backup_lib":"'"$(test -d /usr/local/lib/ar-local-backup && echo present || echo absent)"'",'
echo '"backup_env":"'"$(test -f /etc/ar-local/backup.env && echo present || echo absent)"'",'
echo '"canary_dir":"'"$(test -d /srv/ar-local/canary && echo present || echo absent)"'",'
echo '"latest_backup":"'"$(find /srv /var/lib /media -maxdepth 5 -name latest-backup.json 2>/dev/null | head -1)"'",'
echo '"latest_restore":"'"$(find /srv /var/lib /media -maxdepth 5 -name latest-restore.json 2>/dev/null | head -1)"'"'
echo '}'
"""
    try:
        proc = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=8",
                "ar-local-pi5",
                "bash",
                "-s",
            ],
            input=script,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": proc.stderr.strip() or f"ssh exit {proc.returncode}",
            "stdout": proc.stdout[-2000:],
        }
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": "non-JSON ssh inventory", "stdout": proc.stdout[-2000:]}
    payload["ok"] = True
    return payload


def _emit_binder_rejection(
    gate_dir: Path,
    *,
    gate: str,
    target_commit: str,
    reason: str,
    candidate_generation: Optional[str],
    preservation_snapshot_sha256: Optional[str],
) -> dict[str, Any]:
    """Record a FAIL gate when a binder raises instead of aborting the harness."""

    body = {
        "schema_version": 1,
        "binder": gate,
        "target_commit": target_commit,
        "result": "FAIL",
        "reason": reason[: emit.MAX_NOTES_CHARS],
        "findings": [reason[:512]],
    }
    item = emit.materialize_receipt(
        gate_dir,
        relative_path=f"receipts/{gate}-rejection.json",
        payload=body,
    )
    _path, payload = emit.emit_gate_evidence(
        gate_dir,
        gate=gate,
        result="FAIL",
        target_commit=target_commit,
        evidence_items=[item],
        notes=reason[: emit.MAX_NOTES_CHARS],
        candidate_generation=candidate_generation,
        preservation_snapshot_sha256=preservation_snapshot_sha256,
    )
    return payload


def _run_binder(
    gate_dir: Path,
    *,
    gate: str,
    target_commit: str,
    candidate_generation: Optional[str],
    preservation_snapshot_sha256: Optional[str],
    call,
) -> dict[str, Any]:
    try:
        return call()
    except (GateBindError, emit.GateEmitError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return _emit_binder_rejection(
            gate_dir,
            gate=gate,
            target_commit=target_commit,
            reason=f"{type(exc).__name__}: {exc}",
            candidate_generation=candidate_generation,
            preservation_snapshot_sha256=preservation_snapshot_sha256,
        )


def run_harness(
    gate_dir: Path,
    *,
    target_commit: str,
    candidate_generation: str,
    preservation_snapshot_sha256: str,
    historical_summary: Optional[Path] = None,
    expected_historical_index: Optional[Path] = None,
    restore_receipt: Optional[Path] = None,
    protected_code_sha: Optional[str] = None,
    public_manifest: Optional[Path] = None,
    public_assets: Sequence[Path] = (),
    shadow_receipt: Optional[Path] = None,
    stable_app_receipt: Optional[Path] = None,
    emulator_receipt: Optional[Path] = None,
    device_receipt: Optional[Path] = None,
    skip_ssh: bool = False,
) -> dict[str, Any]:
    """Attempt all eight gates; write status.json; never fabricate PASS."""

    gate_dir.mkdir(parents=True, exist_ok=True)
    (gate_dir / "receipts").mkdir(parents=True, exist_ok=True)
    inventory = {} if skip_ssh else collect_pi_readonly_inventory()
    if inventory:
        emit.write_json_atomic(
            gate_dir / "receipts" / "pi-readonly-inventory.json", inventory
        )

    results: dict[str, Any] = {}
    common = dict(
        gate_dir=gate_dir,
        target_commit=target_commit,
        candidate_generation=candidate_generation,
        preservation_snapshot_sha256=preservation_snapshot_sha256,
    )

    results["producer_contracts"] = _run_binder(
        gate_dir,
        gate="producer_contracts",
        target_commit=target_commit,
        candidate_generation=candidate_generation,
        preservation_snapshot_sha256=preservation_snapshot_sha256,
        call=lambda: bind_producer_contracts(**common),
    )

    results["preservation_restore"] = _run_binder(
        gate_dir,
        gate="preservation_restore",
        target_commit=target_commit,
        candidate_generation=candidate_generation,
        preservation_snapshot_sha256=preservation_snapshot_sha256,
        call=lambda: bind_preservation_restore(
            gate_dir,
            target_commit=target_commit,
            restore_receipt=restore_receipt,
            candidate_generation=candidate_generation,
            preservation_snapshot_sha256=preservation_snapshot_sha256,
            protected_code_sha=protected_code_sha,
            ro_inventory=inventory,
        ),
    )

    if historical_summary is not None:
        results["historical_integrity"] = _run_binder(
            gate_dir,
            gate="historical_integrity",
            target_commit=target_commit,
            candidate_generation=candidate_generation,
            preservation_snapshot_sha256=preservation_snapshot_sha256,
            call=lambda: bind_historical_integrity(
                gate_dir,
                target_commit=target_commit,
                summary_path=historical_summary,
                candidate_generation=candidate_generation,
                preservation_snapshot_sha256=preservation_snapshot_sha256,
                expected_index_path=expected_historical_index,
            ),
        )
    else:
        results["historical_integrity"] = _run_binder(
            gate_dir,
            gate="historical_integrity",
            target_commit=target_commit,
            candidate_generation=candidate_generation,
            preservation_snapshot_sha256=preservation_snapshot_sha256,
            call=lambda: bind_receipt_gate(
                gate_dir,
                gate="historical_integrity",
                target_commit=target_commit,
                receipt_path=None,
                required_fields={},
                candidate_generation=candidate_generation,
                preservation_snapshot_sha256=preservation_snapshot_sha256,
                missing_reason=(
                    "no cdr_public_history_audit.py summary.json supplied; "
                    "run audit then --historical-summary"
                ),
            ),
        )

    if public_manifest is not None:
        results["public_candidate_bytes"] = _run_binder(
            gate_dir,
            gate="public_candidate_bytes",
            target_commit=target_commit,
            candidate_generation=candidate_generation,
            preservation_snapshot_sha256=preservation_snapshot_sha256,
            call=lambda: bind_public_candidate_bytes(
                gate_dir,
                target_commit=target_commit,
                manifest_path=public_manifest,
                asset_paths=list(public_assets),
                candidate_generation=candidate_generation,
                preservation_snapshot_sha256=preservation_snapshot_sha256,
            ),
        )
    else:
        results["public_candidate_bytes"] = _run_binder(
            gate_dir,
            gate="public_candidate_bytes",
            target_commit=target_commit,
            candidate_generation=candidate_generation,
            preservation_snapshot_sha256=preservation_snapshot_sha256,
            call=lambda: bind_receipt_gate(
                gate_dir,
                gate="public_candidate_bytes",
                target_commit=target_commit,
                receipt_path=None,
                required_fields={},
                candidate_generation=candidate_generation,
                preservation_snapshot_sha256=preservation_snapshot_sha256,
                missing_reason=(
                    "no public manifest/assets supplied; download release then "
                    "--public-manifest + --public-asset"
                ),
            ),
        )

    for gate_name, receipt, missing in (
        (
            "shadow_ingest",
            shadow_receipt,
            "no isolated shadow-ingest receipt for this target_commit; "
            "run runbook shadow ingest under /srv/ar-local/canary then supply receipt",
        ),
        (
            "stable_app_compatibility",
            stable_app_receipt,
            "no stable-app / mobile CI receipt bound to target_commit "
            "(docs/PRODUCT_EVIDENCE_ACCEPTANCE.md)",
        ),
        (
            "candidate_emulator_matrix",
            emulator_receipt,
            "no emulator matrix receipt (P-007) for this target_commit",
        ),
        (
            "candidate_device_matrix",
            device_receipt,
            "no physical-device matrix receipt for this target_commit",
        ),
    ):
        results[gate_name] = _run_binder(
            gate_dir,
            gate=gate_name,
            target_commit=target_commit,
            candidate_generation=candidate_generation,
            preservation_snapshot_sha256=preservation_snapshot_sha256,
            call=lambda g=gate_name, r=receipt, m=missing: bind_receipt_gate(
                gate_dir,
                gate=g,
                target_commit=target_commit,
                receipt_path=r,
                required_fields={"target_commit": target_commit},
                candidate_generation=candidate_generation,
                preservation_snapshot_sha256=preservation_snapshot_sha256,
                missing_reason=m,
            ),
        )

    status = {
        "schema_version": 1,
        "target_commit": target_commit,
        "candidate_generation": candidate_generation,
        "preservation_snapshot_sha256": preservation_snapshot_sha256,
        "protected_code_sha": protected_code_sha,
        "gates": {
            name: {
                "result": payload.get("result"),
                "notes": payload.get("notes"),
            }
            for name, payload in results.items()
        },
        "pi_readonly": inventory,
        "assemble_ready": all(
            payload.get("result") == "PASS" for payload in results.values()
        ),
    }
    emit.write_json_atomic(gate_dir / "status.json", status)
    return status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser, *, require_pass_bindings: bool) -> None:
        p.add_argument("--target-commit", required=True)
        p.add_argument("--gate-dir", required=True, type=Path)
        p.add_argument(
            "--candidate-generation",
            required=require_pass_bindings,
            default=None,
        )
        p.add_argument(
            "--preservation-snapshot-sha256",
            required=require_pass_bindings,
            default=None,
        )

    p_pc = sub.add_parser("producer-contracts", help="Validate contracts/*.schema.json")
    add_common(p_pc, require_pass_bindings=True)

    p_hi = sub.add_parser("historical-integrity", help="Bind audit summary.json")
    add_common(p_hi, require_pass_bindings=True)
    p_hi.add_argument("--summary", required=True, type=Path)
    p_hi.add_argument(
        "--expected-index",
        type=Path,
        default=None,
        help=(
            "Candidate/authorizing dates-index.json whose SHA-256 and date "
            "population must match the audit summary (required for PASS)"
        ),
    )
    p_hi.add_argument("--min-dates", type=int, default=2)
    p_hi.add_argument(
        "--allow-scoped-index",
        action="store_true",
        help=(
            "Mark this run as a tooling drill; never emits authorizing PASS "
            "(scoped indexes remain non-authorizing)"
        ),
    )

    p_pub = sub.add_parser("public-candidate-bytes", help="Verify local public assets")
    add_common(p_pub, require_pass_bindings=True)
    p_pub.add_argument("--manifest", required=True, type=Path)
    p_pub.add_argument("--asset", action="append", default=[], type=Path)

    p_pr = sub.add_parser("preservation-restore", help="Bind restore-drill receipt")
    add_common(p_pr, require_pass_bindings=False)
    p_pr.add_argument("--restore-receipt", type=Path, default=None)
    p_pr.add_argument(
        "--protected-code-sha",
        default=None,
        help="Protected/restored baseline commit that receipt candidate_code_sha must match",
    )
    p_pr.add_argument("--skip-ssh", action="store_true")

    for gate, help_text in (
        ("shadow-ingest", "Bind shadow ingest receipt"),
        ("stable-app-compatibility", "Bind stable-app receipt"),
        ("candidate-emulator-matrix", "Bind emulator matrix receipt"),
        ("candidate-device-matrix", "Bind device matrix receipt"),
    ):
        p = sub.add_parser(gate, help=help_text)
        add_common(p, require_pass_bindings=False)
        p.add_argument("--receipt", type=Path, default=None)

    p_h = sub.add_parser("harness", help="Attempt all eight gates + status.json")
    add_common(p_h, require_pass_bindings=True)
    p_h.add_argument("--historical-summary", type=Path, default=None)
    p_h.add_argument("--expected-historical-index", type=Path, default=None)
    p_h.add_argument("--restore-receipt", type=Path, default=None)
    p_h.add_argument(
        "--protected-code-sha",
        default=None,
        help="Protected/restored baseline commit for preservation_restore binding",
    )
    p_h.add_argument("--public-manifest", type=Path, default=None)
    p_h.add_argument("--public-asset", action="append", default=[], type=Path)
    p_h.add_argument("--shadow-receipt", type=Path, default=None)
    p_h.add_argument("--stable-app-receipt", type=Path, default=None)
    p_h.add_argument("--emulator-receipt", type=Path, default=None)
    p_h.add_argument("--device-receipt", type=Path, default=None)
    p_h.add_argument("--skip-ssh", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        target = _require_commit(args.target_commit)
        gate_dir: Path = args.gate_dir
        gate_dir.mkdir(parents=True, exist_ok=True)
        (gate_dir / "receipts").mkdir(parents=True, exist_ok=True)

        if args.command == "producer-contracts":
            payload = bind_producer_contracts(
                gate_dir,
                target_commit=target,
                candidate_generation=args.candidate_generation,
                preservation_snapshot_sha256=args.preservation_snapshot_sha256,
            )
        elif args.command == "historical-integrity":
            payload = bind_historical_integrity(
                gate_dir,
                target_commit=target,
                summary_path=args.summary,
                candidate_generation=args.candidate_generation,
                preservation_snapshot_sha256=args.preservation_snapshot_sha256,
                min_dates=args.min_dates,
                allow_scoped_index=args.allow_scoped_index,
                expected_index_path=args.expected_index,
            )
        elif args.command == "public-candidate-bytes":
            payload = bind_public_candidate_bytes(
                gate_dir,
                target_commit=target,
                manifest_path=args.manifest,
                asset_paths=args.asset,
                candidate_generation=args.candidate_generation,
                preservation_snapshot_sha256=args.preservation_snapshot_sha256,
            )
        elif args.command == "preservation-restore":
            inventory = {} if args.skip_ssh else collect_pi_readonly_inventory()
            protected = args.protected_code_sha
            if protected is not None:
                protected = _require_commit(protected)
            payload = bind_preservation_restore(
                gate_dir,
                target_commit=target,
                restore_receipt=args.restore_receipt,
                candidate_generation=args.candidate_generation,
                preservation_snapshot_sha256=args.preservation_snapshot_sha256,
                protected_code_sha=protected,
                ro_inventory=inventory,
            )
        elif args.command in {
            "shadow-ingest",
            "stable-app-compatibility",
            "candidate-emulator-matrix",
            "candidate-device-matrix",
        }:
            gate_map = {
                "shadow-ingest": "shadow_ingest",
                "stable-app-compatibility": "stable_app_compatibility",
                "candidate-emulator-matrix": "candidate_emulator_matrix",
                "candidate-device-matrix": "candidate_device_matrix",
            }
            gate = gate_map[args.command]
            payload = bind_receipt_gate(
                gate_dir,
                gate=gate,
                target_commit=target,
                receipt_path=args.receipt,
                required_fields={"target_commit": target},
                candidate_generation=args.candidate_generation,
                preservation_snapshot_sha256=args.preservation_snapshot_sha256,
                missing_reason=f"no receipt supplied for {gate}",
            )
        elif args.command == "harness":
            protected = args.protected_code_sha
            if protected is not None:
                protected = _require_commit(protected)
            status = run_harness(
                gate_dir,
                target_commit=target,
                candidate_generation=args.candidate_generation,
                preservation_snapshot_sha256=args.preservation_snapshot_sha256,
                historical_summary=args.historical_summary,
                expected_historical_index=args.expected_historical_index,
                restore_receipt=args.restore_receipt,
                restore_manifest=args.restore_manifest,
                protected_code_sha=protected,
                public_manifest=args.public_manifest,
                public_assets=args.public_asset,
                shadow_receipt=args.shadow_receipt,
                stable_app_receipt=args.stable_app_receipt,
                emulator_receipt=args.emulator_receipt,
                device_receipt=args.device_receipt,
                skip_ssh=args.skip_ssh,
            )
            print(json.dumps(status["gates"], indent=2, sort_keys=True))
            print(
                f"pi_canary_gate_bind: harness wrote {gate_dir / 'status.json'} "
                f"assemble_ready={status['assemble_ready']}"
            )
            return 0 if status["assemble_ready"] else 2
        else:
            raise GateBindError(f"unknown command {args.command}")

        print(
            f"pi_canary_gate_bind: {payload['gate']} result={payload['result']} "
            f"-> {gate_dir / (payload['gate'] + '.json')}"
        )
        return 0 if payload["result"] == "PASS" else 2
    except (OSError, GateBindError, emit.GateEmitError) as exc:
        print(f"pi_canary_gate_bind: rejected: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
