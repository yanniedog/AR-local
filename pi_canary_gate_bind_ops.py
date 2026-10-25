#!/usr/bin/env python3
"""Gate binder operations extracted for modularity (fail-closed)."""

from __future__ import annotations

import json
import subprocess
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


def _git_show_bytes(commit: str, relpath: str, *, repo: Path = ROOT) -> bytes:
    """Return blob bytes for ``commit:relpath`` or raise GateBindError."""

    try:
        return subprocess.check_output(
            ["git", "-C", str(repo), "show", f"{commit}:{relpath}"],
            stderr=subprocess.STDOUT,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = ""
        if isinstance(exc, subprocess.CalledProcessError) and exc.output:
            detail = f": {exc.output.decode('utf-8', errors='replace')[:200]}"
        raise GateBindError(
            f"cannot read {relpath} from commit {commit}{detail}"
        ) from exc


def _normalize_git_text(raw: bytes) -> bytes:
    """Normalize CRLF so Windows checkout autocrlf cannot false-fail binding."""

    return raw.replace(b"\r\n", b"\n")


def _verify_file_matches_commit(
    path: Path, *, commit: str, relpath: str, findings: list[str]
) -> None:
    """Record a finding when on-disk bytes differ from ``commit:relpath``.

    Prefer ``git diff`` (respects attributes) and fall back to LF-normalized
    content compare when the working tree uses CRLF on Windows.
    """

    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "diff", "--quiet", commit, "--", relpath],
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        findings.append(f"git diff unavailable for {relpath}: {exc}")
        return
    if proc.returncode == 0:
        return
    if proc.returncode not in (0, 1):
        findings.append(
            f"git diff failed for {relpath} vs {commit} (exit {proc.returncode})"
        )
        return
    try:
        expected = _normalize_git_text(_git_show_bytes(commit, relpath))
    except GateBindError as exc:
        findings.append(str(exc))
        return
    actual = _normalize_git_text(path.read_bytes())
    if actual != expected:
        findings.append(
            f"{relpath} on disk differs from {commit}:{relpath} "
            f"(disk_sha256={emit.sha256_bytes(actual)} "
            f"commit_sha256={emit.sha256_bytes(expected)})"
        )


def _receipt_outcome_is_pass(raw: Mapping[str, Any]) -> bool:
    """True only when the receipt explicitly reports a successful outcome."""

    for key in ("result", "status"):
        value = raw.get(key)
        if value in ("PASS", "passed", True):
            return True
    return False


def _copy_source_receipt(
    gate_dir: Path, *, source: Path, relative_path: str
) -> dict[str, str]:
    """Preserve original receipt bytes under the gate dir as evidence."""

    if source.is_symlink() or not source.is_file():
        raise GateBindError(f"expected regular source receipt: {source}")
    return emit.materialize_bytes(
        gate_dir, relative_path=relative_path, raw=source.read_bytes()
    )


def _load_preserved_receipt(gate_dir: Path, source_item: Mapping[str, str]) -> dict[str, Any]:
    """Parse the preserved receipt snapshot (never re-read the mutable source)."""

    rel = str(source_item.get("path") or "").strip()
    if not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
        raise GateBindError(f"invalid preserved receipt path: {rel!r}")
    return _load_json(gate_dir / rel)



def bind_producer_contracts(
    gate_dir: Path,
    *,
    target_commit: str,
    candidate_generation: str,
    preservation_snapshot_sha256: str,
    contracts_root: Path = CONTRACTS_DIR,
) -> dict[str, Any]:
    """PASS only when every contracts/*.schema.json is a valid Draft 2020-12 schema
    and v3 producer schemas load + digest stably, and on-disk contract bytes match
    the requested ``target_commit`` blobs (exact-tested deployment binding).
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
        if contracts_root.resolve() == CONTRACTS_DIR.resolve():
            _verify_file_matches_commit(
                path,
                commit=target_commit,
                relpath=f"contracts/{path.name}",
                findings=findings,
            )
    v3_root = contracts_root / "v3"
    v3_digest: Optional[str] = None
    try:
        v3_schemas = contract_validation.load_schemas(v3_root)
        for name, schema in v3_schemas.items():
            try:
                Draft202012Validator.check_schema(schema)
            except Exception as exc:  # noqa: BLE001 — capture any schema defect
                findings.append(f"v3/{name}: {type(exc).__name__}: {exc}")
        v3_digest = contract_validation.contract_sha256(v3_root)
    except Exception as exc:  # noqa: BLE001
        findings.append(f"v3 contracts: {type(exc).__name__}: {exc}")
    if contracts_root.resolve() == CONTRACTS_DIR.resolve() and v3_root.is_dir():
        for path in sorted(v3_root.rglob("*.schema.json")):
            rel = path.relative_to(ROOT).as_posix()
            _verify_file_matches_commit(
                path, commit=target_commit, relpath=rel, findings=findings
            )

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
    expected_index_path: Optional[Path] = None,
) -> dict[str, Any]:
    """PASS only when an audit summary shows dates_passed == dates_checked.

    By default requires dates_checked >= min_dates (2) so a one-date probe cannot
    authorize historical_integrity. ``allow_scoped_index`` is tooling-drill-only:
    it never emits an authorizing PASS (scoped drills stay non-authorizing).

    Authorizing PASS also requires ``expected_index_path`` whose bytes hash to the
    summary ``index_sha256`` and whose date population equals ``dates_checked``.
    """

    from cdr_history_validation import ordered_dates

    summary = _load_json(summary_path)
    checked = summary.get("dates_checked")
    passed = summary.get("dates_passed")
    index_sha = summary.get("index_sha256")
    findings: list[str] = []
    expected_index_sha: Optional[str] = None
    expected_index_dates: Optional[int] = None
    if not isinstance(checked, int) or not isinstance(passed, int):
        findings.append("dates_checked/dates_passed must be ints")
    elif checked <= 0:
        findings.append("dates_checked must be > 0")
    elif passed != checked:
        findings.append(f"dates_passed {passed} != dates_checked {checked}")
    if not isinstance(index_sha, str) or not canary.SHA256_RE.fullmatch(index_sha or ""):
        findings.append("index_sha256 missing or not 64 hex")
    if isinstance(checked, int) and checked > 0 and checked < min_dates:
        findings.append(
            f"dates_checked {checked} < min_dates {min_dates} "
            "(scoped index cannot authorize historical_integrity)"
        )
    if expected_index_path is None:
        findings.append(
            "expected dates index required to authorize historical_integrity "
            "(pass --expected-index)"
        )
    elif expected_index_path.is_symlink() or not expected_index_path.is_file():
        findings.append(f"expected index must be a regular file: {expected_index_path}")
    else:
        raw_index = expected_index_path.read_bytes()
        expected_index_sha = emit.sha256_bytes(raw_index)
        if isinstance(index_sha, str) and expected_index_sha != index_sha:
            findings.append(
                f"expected index sha256 {expected_index_sha} != "
                f"summary index_sha256 {index_sha}"
            )
        try:
            index_obj = json.loads(raw_index.decode("utf-8"))
            dates = ordered_dates(index_obj)
            expected_index_dates = len(dates)
            if isinstance(checked, int) and checked != expected_index_dates:
                findings.append(
                    f"dates_checked {checked} != expected index population "
                    f"{expected_index_dates}"
                )
        except Exception as exc:  # noqa: BLE001
            findings.append(
                f"expected index invalid: {type(exc).__name__}: {exc}"
            )
    if allow_scoped_index:
        # Explicit drill flag: never authorize. Keep FAIL even when dates match.
        findings.append(
            "allow_scoped_index is tooling-drill-only; refusing authorizing PASS"
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
        "expected_index_path": str(expected_index_path) if expected_index_path else None,
        "expected_index_sha256": expected_index_sha,
        "expected_index_dates": expected_index_dates,
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




def bind_preservation_restore(
    gate_dir: Path,
    *,
    target_commit: str,
    restore_receipt: Optional[Path],
    candidate_generation: Optional[str],
    preservation_snapshot_sha256: Optional[str],
    protected_code_sha: Optional[str] = None,
    ro_inventory: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """PASS only with a restore-acceptance receipt whose result is PASS.

    ``candidate_code_sha`` on the receipt is the restored/protected baseline
    (see ``validate_restore_acceptance``), not the proposed canary target.
    The gate evidence itself is still labeled with ``target_commit``.
    """

    findings: list[str] = []
    evidence_items: list[dict[str, str]] = []
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
        source_item = _copy_source_receipt(
            gate_dir,
            source=restore_receipt,
            relative_path="receipts/preservation_restore-source.json",
        )
        evidence_items.append(source_item)
        raw = _load_preserved_receipt(gate_dir, source_item)
        receipt_body = {
            "schema_version": 1,
            "binder": "preservation_restore",
            "target_commit": target_commit,
            "protected_code_sha": protected_code_sha,
            "source_receipt": str(restore_receipt),
            "source_sha256": source_item["sha256"],
            "restore_result": raw.get("result"),
            "restore_acceptance_version": raw.get("restore_acceptance_version"),
            "snapshot_id": raw.get("snapshot_id"),
            "candidate_code_sha": raw.get("candidate_code_sha"),
            "manifest_sha256": raw.get("manifest_sha256"),
            "ro_inventory": dict(ro_inventory or {}),
        }
        if raw.get("result") != "PASS":
            findings.append(f"restore result is {raw.get('result')!r}, not PASS")
        if raw.get("restore_acceptance_version") != 1:
            findings.append(
                f"restore_acceptance_version is {raw.get('restore_acceptance_version')!r}, "
                "expected 1"
            )
        checks = raw.get("checks")
        if not isinstance(checks, Mapping) or checks.get("ok") is not True:
            findings.append("restore checks.ok must be true")
        cand = raw.get("candidate_code_sha")
        if not isinstance(cand, str) or not canary.COMMIT_RE.fullmatch(cand or ""):
            findings.append("candidate_code_sha missing or not 40 hex")
        elif not protected_code_sha:
            findings.append(
                "PASS requires --protected-code-sha matching receipt candidate_code_sha"
            )
        elif cand != protected_code_sha:
            findings.append(
                f"candidate_code_sha {cand} != protected_code_sha {protected_code_sha}"
            )
        snap = raw.get("manifest_sha256")
        if not isinstance(snap, str) or not canary.SHA256_RE.fullmatch(snap or ""):
            findings.append("manifest_sha256 missing or not 64 hex")
        elif preservation_snapshot_sha256 and snap != preservation_snapshot_sha256:
            findings.append("manifest_sha256 != --preservation-snapshot-sha256")
        # Soft schema check against restore-acceptance contract when available.
        schema_path = CONTRACTS_DIR / "pi-restore-acceptance-v1.schema.json"
        if schema_path.is_file():
            try:
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
                Draft202012Validator(schema).validate(raw)
            except Exception as exc:  # noqa: BLE001
                findings.append(
                    f"restore receipt schema: {type(exc).__name__}: {exc}"
                )
        receipt_body["findings"] = findings
        result = "PASS" if not findings else "FAIL"
        receipt_body["result"] = result

    item = emit.materialize_receipt(
        gate_dir,
        relative_path="receipts/preservation_restore-receipt.json",
        payload=receipt_body,
    )
    evidence_items.insert(0, item)
    notes = receipt_body.get("reason") or f"findings={len(findings)}"
    _path, payload = emit.emit_gate_evidence(
        gate_dir,
        gate="preservation_restore",
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

from pi_canary_gate_bind_public import bind_public_candidate_bytes  # noqa: E402
from pi_canary_gate_bind_receipts import bind_receipt_gate  # noqa: E402

__all__ = (
    "CONTRACTS_DIR",
    "GateBindError",
    "ROOT",
    "bind_historical_integrity",
    "bind_preservation_restore",
    "bind_producer_contracts",
    "bind_public_candidate_bytes",
    "bind_receipt_gate",
)
