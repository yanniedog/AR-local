#!/usr/bin/env python3
"""Receipt-gate binder extracted for modularity (fail-closed)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional

import pi_canary_gate_emit as emit
from pi_canary_gate_bind_checks import append_gate_specific_receipt_findings
from pi_canary_gate_bind_ops import (
    _copy_source_receipt,
    _load_preserved_receipt,
    _receipt_outcome_is_pass,
    _require_generation,
    _require_snapshot,
)

def bind_receipt_gate(
    gate_dir: Path,
    *,
    gate: str,
    target_commit: str,
    receipt_path: Optional[Path],
    required_fields: Mapping[str, Any],
    candidate_generation: Optional[str],
    preservation_snapshot_sha256: Optional[str],
    missing_reason: str,
) -> dict[str, Any]:
    """Generic binder: PASS when receipt JSON matches required field values."""

    evidence_items: list[dict[str, str]] = []
    if receipt_path is None:
        result = "UNKNOWN"
        body = {
            "schema_version": 1,
            "binder": gate,
            "target_commit": target_commit,
            "result": result,
            "reason": missing_reason,
        }
    else:
        source_item = _copy_source_receipt(
            gate_dir,
            source=receipt_path,
            relative_path=f"receipts/{gate}-source.json",
        )
        evidence_items.append(source_item)
        raw = _load_preserved_receipt(gate_dir, source_item)
        findings: list[str] = []
        for key, expected in required_fields.items():
            actual = raw.get(key)
            if actual != expected:
                findings.append(f"{key}: got {actual!r}, expected {expected!r}")
        # Reject cross-gate substitution (e.g. shadow_ingest receipt as device matrix).
        receipt_gate = raw.get("gate")
        if receipt_gate is None and isinstance(raw.get("binder"), str):
            receipt_gate = raw.get("binder")
        if receipt_gate is None:
            findings.append(
                f"receipt missing gate identity required to bind gate {gate!r}"
            )
        elif receipt_gate != gate:
            findings.append(f"gate: got {receipt_gate!r}, expected {gate!r}")
        if not _receipt_outcome_is_pass(raw):
            status = raw.get("status") if "status" in raw else raw.get("result")
            findings.append(f"receipt status/result not explicit PASS ({status!r})")
        # Conflicting failure indicators must reject even if result claims PASS.
        for fail_key in ("error", "failed", "failure"):
            if raw.get(fail_key) not in (None, False, "", []):
                findings.append(f"receipt has failure indicator {fail_key}={raw.get(fail_key)!r}")
        if raw.get("status") in {"FAIL", "FAILED", "failed", False} and raw.get("result") in {
            "PASS",
            "passed",
            True,
        }:
            findings.append("receipt status conflicts with result PASS")
        # Do not relabel an older generation/snapshot receipt as PASS for a new bind.
        if candidate_generation is not None:
            receipt_gen = raw.get("candidate_generation")
            if receipt_gen is None:
                findings.append(
                    "receipt missing candidate_generation required to bind this generation"
                )
            elif receipt_gen != candidate_generation:
                findings.append(
                    f"candidate_generation: got {receipt_gen!r}, expected {candidate_generation!r}"
                )
        if preservation_snapshot_sha256 is not None:
            receipt_snap = raw.get("preservation_snapshot_sha256")
            if receipt_snap is None:
                findings.append(
                    "receipt missing preservation_snapshot_sha256 required to bind this snapshot"
                )
            elif receipt_snap != preservation_snapshot_sha256:
                findings.append(
                    "preservation_snapshot_sha256: "
                    f"got {receipt_snap!r}, expected {preservation_snapshot_sha256!r}"
                )
        # Labels alone are not enough: enforce gate-specific test evidence (canonicalize bar).
        if _receipt_outcome_is_pass(raw) and receipt_gate == gate:
            append_gate_specific_receipt_findings(gate, raw, findings)
        result = "PASS" if not findings else "FAIL"
        body = {
            "schema_version": 1,
            "binder": gate,
            "target_commit": target_commit,
            "source_receipt": str(receipt_path),
            "source_sha256": source_item["sha256"],
            "findings": findings,
            "result": result,
        }
    item = emit.materialize_receipt(
        gate_dir,
        relative_path=f"receipts/{gate}-receipt.json",
        payload=body,
    )
    evidence_items.insert(0, item)
    notes = body.get("reason") or f"result={result}"
    _path, payload = emit.emit_gate_evidence(
        gate_dir,
        gate=gate,
        result=result,
        target_commit=target_commit,
        evidence_items=evidence_items,
        notes=str(notes)[: emit.MAX_NOTES_CHARS],
        candidate_generation=_require_generation(candidate_generation, for_pass=result == "PASS"),
        preservation_snapshot_sha256=_require_snapshot(
            preservation_snapshot_sha256, for_pass=result == "PASS"
        ),
    )
    return payload


