#!/usr/bin/env python3
"""Bind real artifacts into canary-gate-evidence-v1 files (fail-closed).

Each subcommand validates real receipts/scripts before emitting PASS.
Missing prerequisites emit UNKNOWN or FAIL — never invent PASS.

Examples:
  python pi_canary_gate_bind.py producer-contracts \\
    --target-commit <sha> --gate-dir .work/canary-gates/<sha> \\
    --candidate-generation prep-... --preservation-snapshot-sha256 <64hex>

  python pi_canary_gate_bind.py harness \\
    --target-commit <sha> --gate-dir .work/canary-gates/<sha> \\
    --candidate-generation prep-... --preservation-snapshot-sha256 <64hex>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from jsonschema import Draft202012Validator

import pi_canary_acceptance as canary
import pi_canary_gate_emit as emit
from cdr_domain import contract_validation

ROOT = Path(__file__).resolve().parent
CONTRACTS_DIR = ROOT / "contracts"
V3_CONTRACTS = CONTRACTS_DIR / "v3"


class GateBindError(ValueError):
    """Gate cannot be bound from the supplied evidence."""


def _require_commit(value: str) -> str:
    if not canary.COMMIT_RE.fullmatch(value):
        raise GateBindError("target_commit must be 40 lowercase hex")
    return value


def _require_generation(value: Optional[str], *, for_pass: bool) -> Optional[str]:
    if value is None:
        if for_pass:
            raise GateBindError("PASS requires --candidate-generation")
        return None
    if not canary.CANDIDATE_GENERATION_RE.fullmatch(value):
        raise GateBindError("candidate_generation charset/length invalid")
    return value


def _require_snapshot(value: Optional[str], *, for_pass: bool) -> Optional[str]:
    if value is None:
        if for_pass:
            raise GateBindError("PASS requires --preservation-snapshot-sha256")
        return None
    if not canary.SHA256_RE.fullmatch(value):
        raise GateBindError("preservation_snapshot_sha256 must be 64 lowercase hex")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise GateBindError(f"expected regular file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateBindError(f"unreadable JSON ({path}): {exc}") from exc
    if not isinstance(payload, dict):
        raise GateBindError(f"JSON root must be object: {path}")
    return payload


def bind_producer_contracts(
    gate_dir: Path,
    *,
    target_commit: str,
    candidate_generation: str,
    preservation_snapshot_sha256: str,
    contracts_root: Path = CONTRACTS_DIR,
) -> dict[str, Any]:
    """PASS only when every contracts/*.schema.json is a valid Draft 2020-12 schema
    and v3 producer schemas load + digest stably.
    """

    schema_files = sorted(contracts_root.glob("*.schema.json"))
    if not schema_files:
        raise GateBindError(f"no schema files under {contracts_root}")
    findings: list[str] = []
    digests: dict[str, str] = {}
    for path in schema_files:
        digests[path.name] = emit.sha256_file(path)
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
        except Exception as exc:  # noqa: BLE001 — capture any schema defect
            findings.append(f"{path.name}: {type(exc).__name__}: {exc}")
    v3_root = contracts_root / "v3"
    v3_digest: Optional[str] = None
    try:
        contract_validation.load_schemas(v3_root)
        v3_digest = contract_validation.contract_sha256(v3_root)
    except Exception as exc:  # noqa: BLE001
        findings.append(f"v3 contracts: {type(exc).__name__}: {exc}")

    result = "PASS" if not findings else "FAIL"
    receipt = {
        "schema_version": 1,
        "binder": "producer_contracts",
        "target_commit": target_commit,
        "contracts_root": str(contracts_root),
        "schema_count": len(schema_files),
        "schema_sha256": digests,
        "v3_contract_sha256": v3_digest,
        "findings": findings,
        "result": result,
    }
    item = emit.materialize_receipt(
        gate_dir, relative_path="receipts/producer_contracts-receipt.json", payload=receipt
    )
    notes = (
        f"Validated {len(schema_files)} contract schemas"
        + (f"; v3 digest {v3_digest}" if v3_digest else "")
        + (f"; findings={len(findings)}" if findings else "")
    )
    _path, payload = emit.emit_gate_evidence(
        gate_dir,
        gate="producer_contracts",
        result=result,
        target_commit=target_commit,
        evidence_items=[item],
        notes=notes[: emit.MAX_NOTES_CHARS],
        candidate_generation=candidate_generation if result == "PASS" else None,
        preservation_snapshot_sha256=(
            preservation_snapshot_sha256 if result == "PASS" else None
        ),
    )
    return payload


def bind_historical_integrity(
    gate_dir: Path,
    *,
    target_commit: str,
    summary_path: Path,
    candidate_generation: Optional[str],
    preservation_snapshot_sha256: Optional[str],
    min_dates: int = 2,
    allow_scoped_index: bool = False,
) -> dict[str, Any]:
    """PASS only when an audit summary shows dates_passed == dates_checked.

    By default requires dates_checked >= min_dates (2) so a one-date probe cannot
    authorize historical_integrity. Operators may pass allow_scoped_index only for
    explicit tooling drills — not for live canary bind.
    """

    summary = _load_json(summary_path)
    checked = summary.get("dates_checked")
    passed = summary.get("dates_passed")
    index_sha = summary.get("index_sha256")
    findings: list[str] = []
    if not isinstance(checked, int) or not isinstance(passed, int):
        findings.append("dates_checked/dates_passed must be ints")
    elif checked <= 0:
        findings.append("dates_checked must be > 0")
    elif passed != checked:
        findings.append(f"dates_passed {passed} != dates_checked {checked}")
    if not isinstance(index_sha, str) or not canary.SHA256_RE.fullmatch(index_sha or ""):
        findings.append("index_sha256 missing or not 64 hex")
    if (
        isinstance(checked, int)
        and checked > 0
        and checked < min_dates
        and not allow_scoped_index
    ):
        findings.append(
            f"dates_checked {checked} < min_dates {min_dates} "
            "(refuse scoped index without --allow-scoped-index)"
        )
    ok = not findings
    result = "PASS" if ok else "FAIL"
    receipt = {
        "schema_version": 1,
        "binder": "historical_integrity",
        "target_commit": target_commit,
        "summary_path": str(summary_path),
        "summary_sha256": emit.sha256_file(summary_path),
        "dates_checked": checked,
        "dates_passed": passed,
        "index_sha256": index_sha,
        "min_dates": min_dates,
        "allow_scoped_index": allow_scoped_index,
        "findings": findings,
        "result": result,
    }
    item = emit.materialize_receipt(
        gate_dir,
        relative_path="receipts/historical_integrity-receipt.json",
        payload=receipt,
    )
    # Copy the summary bytes into the gate dir so assemble can hash a relative path.
    copied = gate_dir / "receipts" / "historical_integrity-summary.json"
    if not copied.exists():
        emit.write_json_atomic(copied, summary)
    summary_item = {
        "path": "receipts/historical_integrity-summary.json",
        "sha256": emit.sha256_file(copied),
    }
    notes = f"audit dates_passed={passed}/{checked} index_sha256={index_sha}"
    _path, payload = emit.emit_gate_evidence(
        gate_dir,
        gate="historical_integrity",
        result=result,
        target_commit=target_commit,
        evidence_items=[item, summary_item],
        notes=notes[: emit.MAX_NOTES_CHARS],
        candidate_generation=_require_generation(candidate_generation, for_pass=result == "PASS"),
        preservation_snapshot_sha256=_require_snapshot(
            preservation_snapshot_sha256, for_pass=result == "PASS"
        ),
    )
    return payload


def bind_public_candidate_bytes(
    gate_dir: Path,
    *,
    target_commit: str,
    manifest_path: Path,
    asset_paths: Sequence[Path],
    candidate_generation: Optional[str],
    preservation_snapshot_sha256: Optional[str],
) -> dict[str, Any]:
    """PASS when local asset digests match manifest file entries (decoded JSON)."""

    from app_payload_secure_upload import decode_public_bytes

    raw_manifest = manifest_path.read_bytes()
    try:
        plain = decode_public_bytes(raw_manifest, max(len(raw_manifest), 1024 * 1024))
        manifest = json.loads(plain.decode("utf-8"))
    except Exception:
        # Plain JSON manifests (tests / unencrypted) are also accepted.
        try:
            manifest = json.loads(raw_manifest.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise GateBindError(f"manifest not decodable JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise GateBindError("manifest root must be object")
    files = manifest.get("files")
    if not isinstance(files, dict) or "core" not in files:
        raise GateBindError("manifest.files.core required")

    findings: list[str] = []
    checked: list[dict[str, Any]] = []
    evidence_items: list[dict[str, str]] = []
    # Persist decrypted/plain manifest copy for hashing.
    local_manifest = gate_dir / "receipts" / "public_candidate_manifest.json"
    if local_manifest.exists() or local_manifest.is_symlink():
        raise GateBindError(f"refusing overwrite: {local_manifest}")
    local_manifest.parent.mkdir(parents=True, exist_ok=True)
    local_manifest.write_bytes(
        (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")
    )
    evidence_items.append(
        {
            "path": "receipts/public_candidate_manifest.json",
            "sha256": emit.sha256_file(local_manifest),
        }
    )

    by_name = {path.name: path for path in asset_paths}
    for key, entry in files.items():
        if not isinstance(entry, dict):
            findings.append(f"{key}: entry not object")
            continue
        name = Path(str(entry.get("url", entry.get("name", "")))).name
        expected_sha = entry.get("sha256")
        expected_bytes = entry.get("bytes")
        if not isinstance(expected_sha, str) or not canary.SHA256_RE.fullmatch(expected_sha):
            findings.append(f"{key}: bad sha256")
            continue
        path = by_name.get(name)
        if path is None:
            # Try matching by basename of path field
            for candidate in asset_paths:
                if expected_sha in candidate.name or key in candidate.name:
                    path = candidate
                    break
        if path is None or not path.is_file():
            findings.append(f"{key}: asset file missing ({name})")
            continue
        body = path.read_bytes()
        actual = emit.sha256_bytes(body)
        size_ok = expected_bytes is None or (
            isinstance(expected_bytes, int) and len(body) == expected_bytes
        )
        if actual != expected_sha or not size_ok:
            findings.append(
                f"{key}: digest/length mismatch got_sha={actual} "
                f"len={len(body)} expected_sha={expected_sha} expected_len={expected_bytes}"
            )
            continue
        dest = gate_dir / "receipts" / f"public_asset_{key}.meta.json"
        meta = {
            "key": key,
            "source_name": path.name,
            "bytes": len(body),
            "sha256": actual,
        }
        emit.write_json_atomic(dest, meta)
        evidence_items.append(
            {"path": f"receipts/public_asset_{key}.meta.json", "sha256": emit.sha256_file(dest)}
        )
        checked.append(meta)

    result = "PASS" if checked and not findings and "core" in {c["key"] for c in checked} else "FAIL"
    receipt = {
        "schema_version": 1,
        "binder": "public_candidate_bytes",
        "target_commit": target_commit,
        "manifest_source": str(manifest_path),
        "checked": checked,
        "findings": findings,
        "result": result,
    }
    evidence_items.insert(
        0,
        emit.materialize_receipt(
            gate_dir,
            relative_path="receipts/public_candidate_bytes-receipt.json",
            payload=receipt,
        ),
    )
    notes = f"checked={len(checked)} findings={len(findings)}"
    _path, payload = emit.emit_gate_evidence(
        gate_dir,
        gate="public_candidate_bytes",
        result=result,
        target_commit=target_commit,
        evidence_items=evidence_items,
        notes=notes[: emit.MAX_NOTES_CHARS],
        candidate_generation=_require_generation(candidate_generation, for_pass=result == "PASS"),
        preservation_snapshot_sha256=_require_snapshot(
            preservation_snapshot_sha256, for_pass=result == "PASS"
        ),
    )
    return payload


def bind_preservation_restore(
    gate_dir: Path,
    *,
    target_commit: str,
    restore_receipt: Optional[Path],
    candidate_generation: Optional[str],
    preservation_snapshot_sha256: Optional[str],
    ro_inventory: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """PASS only with a restore-acceptance receipt whose result is PASS and
    whose candidate/protected SHAs bind target_commit when present.
    """

    findings: list[str] = []
    receipt_body: dict[str, Any]
    if restore_receipt is None:
        result = "UNKNOWN"
        receipt_body = {
            "schema_version": 1,
            "binder": "preservation_restore",
            "target_commit": target_commit,
            "result": result,
            "reason": "no restore-acceptance receipt supplied",
            "ro_inventory": dict(ro_inventory or {}),
            "findings": [
                "backup.env absent or restore drill not run for this target",
                "supply --restore-receipt from pi_backup_foundation.py restore-drill",
            ],
        }
    else:
        raw = _load_json(restore_receipt)
        receipt_body = {
            "schema_version": 1,
            "binder": "preservation_restore",
            "target_commit": target_commit,
            "source_receipt": str(restore_receipt),
            "source_sha256": emit.sha256_file(restore_receipt),
            "restore_result": raw.get("result"),
            "snapshot_id": raw.get("snapshot_id"),
            "candidate_code_sha": raw.get("candidate_code_sha"),
            "manifest_sha256": raw.get("manifest_sha256"),
            "ro_inventory": dict(ro_inventory or {}),
        }
        if raw.get("result") != "PASS":
            findings.append(f"restore result is {raw.get('result')!r}, not PASS")
        cand = raw.get("candidate_code_sha")
        if isinstance(cand, str) and cand and cand != target_commit:
            findings.append(
                f"candidate_code_sha {cand} does not match target_commit {target_commit}"
            )
        snap = raw.get("manifest_sha256")
        if preservation_snapshot_sha256 and isinstance(snap, str):
            if snap != preservation_snapshot_sha256:
                findings.append("manifest_sha256 != --preservation-snapshot-sha256")
        receipt_body["findings"] = findings
        result = "PASS" if not findings else "FAIL"
        receipt_body["result"] = result

    item = emit.materialize_receipt(
        gate_dir,
        relative_path="receipts/preservation_restore-receipt.json",
        payload=receipt_body,
    )
    notes = receipt_body.get("reason") or f"findings={len(findings)}"
    _path, payload = emit.emit_gate_evidence(
        gate_dir,
        gate="preservation_restore",
        result=result,
        target_commit=target_commit,
        evidence_items=[item],
        notes=str(notes)[: emit.MAX_NOTES_CHARS],
        candidate_generation=_require_generation(candidate_generation, for_pass=result == "PASS"),
        preservation_snapshot_sha256=_require_snapshot(
            preservation_snapshot_sha256, for_pass=result == "PASS"
        ),
    )
    return payload


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
        raw = _load_json(receipt_path)
        findings: list[str] = []
        for key, expected in required_fields.items():
            actual = raw.get(key)
            if actual != expected:
                findings.append(f"{key}: got {actual!r}, expected {expected!r}")
        if raw.get("result") not in {None, "PASS", True, "passed"}:
            # Allow receipts that use status/result PASS
            status = raw.get("status") or raw.get("result")
            if status not in {"PASS", "passed", True}:
                findings.append(f"receipt status/result not PASS ({status!r})")
        result = "PASS" if not findings else "FAIL"
        body = {
            "schema_version": 1,
            "binder": gate,
            "target_commit": target_commit,
            "source_receipt": str(receipt_path),
            "source_sha256": emit.sha256_file(receipt_path),
            "findings": findings,
            "result": result,
        }
    item = emit.materialize_receipt(
        gate_dir,
        relative_path=f"receipts/{gate}-receipt.json",
        payload=body,
    )
    notes = body.get("reason") or f"result={result}"
    _path, payload = emit.emit_gate_evidence(
        gate_dir,
        gate=gate,
        result=result,
        target_commit=target_commit,
        evidence_items=[item],
        notes=str(notes)[: emit.MAX_NOTES_CHARS],
        candidate_generation=_require_generation(candidate_generation, for_pass=result == "PASS"),
        preservation_snapshot_sha256=_require_snapshot(
            preservation_snapshot_sha256, for_pass=result == "PASS"
        ),
    )
    return payload


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


def run_harness(
    gate_dir: Path,
    *,
    target_commit: str,
    candidate_generation: str,
    preservation_snapshot_sha256: str,
    historical_summary: Optional[Path] = None,
    restore_receipt: Optional[Path] = None,
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

    results["producer_contracts"] = bind_producer_contracts(
        gate_dir,
        target_commit=target_commit,
        candidate_generation=candidate_generation,
        preservation_snapshot_sha256=preservation_snapshot_sha256,
    )

    results["preservation_restore"] = bind_preservation_restore(
        gate_dir,
        target_commit=target_commit,
        restore_receipt=restore_receipt,
        candidate_generation=candidate_generation,
        preservation_snapshot_sha256=preservation_snapshot_sha256,
        ro_inventory=inventory,
    )

    if historical_summary is not None:
        results["historical_integrity"] = bind_historical_integrity(
            gate_dir,
            target_commit=target_commit,
            summary_path=historical_summary,
            candidate_generation=candidate_generation,
            preservation_snapshot_sha256=preservation_snapshot_sha256,
        )
    else:
        results["historical_integrity"] = bind_receipt_gate(
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
        )

    if public_manifest is not None:
        results["public_candidate_bytes"] = bind_public_candidate_bytes(
            gate_dir,
            target_commit=target_commit,
            manifest_path=public_manifest,
            asset_paths=list(public_assets),
            candidate_generation=candidate_generation,
            preservation_snapshot_sha256=preservation_snapshot_sha256,
        )
    else:
        results["public_candidate_bytes"] = bind_receipt_gate(
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
        )

    results["shadow_ingest"] = bind_receipt_gate(
        gate_dir,
        gate="shadow_ingest",
        target_commit=target_commit,
        receipt_path=shadow_receipt,
        required_fields={"target_commit": target_commit},
        candidate_generation=candidate_generation,
        preservation_snapshot_sha256=preservation_snapshot_sha256,
        missing_reason=(
            "no isolated shadow-ingest receipt for this target_commit; "
            "run runbook shadow ingest under /srv/ar-local/canary then supply receipt"
        ),
    )
    results["stable_app_compatibility"] = bind_receipt_gate(
        gate_dir,
        gate="stable_app_compatibility",
        target_commit=target_commit,
        receipt_path=stable_app_receipt,
        required_fields={"target_commit": target_commit},
        candidate_generation=candidate_generation,
        preservation_snapshot_sha256=preservation_snapshot_sha256,
        missing_reason=(
            "no stable-app / mobile CI receipt bound to target_commit "
            "(docs/PRODUCT_EVIDENCE_ACCEPTANCE.md)"
        ),
    )
    results["candidate_emulator_matrix"] = bind_receipt_gate(
        gate_dir,
        gate="candidate_emulator_matrix",
        target_commit=target_commit,
        receipt_path=emulator_receipt,
        required_fields={"target_commit": target_commit},
        candidate_generation=candidate_generation,
        preservation_snapshot_sha256=preservation_snapshot_sha256,
        missing_reason="no emulator matrix receipt (P-007) for this target_commit",
    )
    results["candidate_device_matrix"] = bind_receipt_gate(
        gate_dir,
        gate="candidate_device_matrix",
        target_commit=target_commit,
        receipt_path=device_receipt,
        required_fields={"target_commit": target_commit},
        candidate_generation=candidate_generation,
        preservation_snapshot_sha256=preservation_snapshot_sha256,
        missing_reason="no physical-device matrix receipt for this target_commit",
    )

    status = {
        "schema_version": 1,
        "target_commit": target_commit,
        "candidate_generation": candidate_generation,
        "preservation_snapshot_sha256": preservation_snapshot_sha256,
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
    p_hi.add_argument("--min-dates", type=int, default=2)
    p_hi.add_argument(
        "--allow-scoped-index",
        action="store_true",
        help="Allow dates_checked < --min-dates (tooling drills only; not live bind)",
    )

    p_pub = sub.add_parser("public-candidate-bytes", help="Verify local public assets")
    add_common(p_pub, require_pass_bindings=True)
    p_pub.add_argument("--manifest", required=True, type=Path)
    p_pub.add_argument("--asset", action="append", default=[], type=Path)

    p_pr = sub.add_parser("preservation-restore", help="Bind restore-drill receipt")
    add_common(p_pr, require_pass_bindings=False)
    p_pr.add_argument("--restore-receipt", type=Path, default=None)
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
    p_h.add_argument("--restore-receipt", type=Path, default=None)
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
            payload = bind_preservation_restore(
                gate_dir,
                target_commit=target,
                restore_receipt=args.restore_receipt,
                candidate_generation=args.candidate_generation,
                preservation_snapshot_sha256=args.preservation_snapshot_sha256,
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
            status = run_harness(
                gate_dir,
                target_commit=target,
                candidate_generation=args.candidate_generation,
                preservation_snapshot_sha256=args.preservation_snapshot_sha256,
                historical_summary=args.historical_summary,
                restore_receipt=args.restore_receipt,
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
