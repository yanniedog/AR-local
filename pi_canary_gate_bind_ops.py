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


def _decode_json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    from app_payload_secure_upload import decode_public_bytes

    try:
        plain = decode_public_bytes(raw, max(len(raw), 1024 * 1024))
        payload = json.loads(plain.decode("utf-8"))
    except Exception:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise GateBindError(f"{label} not decodable JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise GateBindError(f"{label} root must be object")
    return payload


def _decode_asset_domain_bytes(raw: bytes, *, expected_bytes: Optional[int]) -> bytes:
    """Authenticate release transport when present; return domain bytes for digest."""

    from app_payload_secure_upload import decode_public_bytes

    limit = max(expected_bytes or 0, len(raw), 1024 * 1024)
    try:
        return decode_public_bytes(raw, limit)
    except Exception:
        # Plain domain bytes (tests / unencrypted channel).
        return raw


def _validate_public_manifest_contract(manifest: Mapping[str, Any]) -> list[str]:
    """Apply the publication-protocol validator for the declared schema version."""

    findings: list[str] = []
    schema_version = manifest.get("schema_version")
    try:
        if schema_version == 1:
            from app_payload_revisions_state import validate_manifest

            validate_manifest(dict(manifest))
        elif schema_version == 2:
            from app_payload_contracts import validate_v2_manifest

            validate_v2_manifest(manifest)
        elif schema_version == 3:
            contract_validation.validate_contract(
                "generation-manifest-v3.schema.json", manifest
            )
            capabilities = manifest.get("capabilities")
            if not isinstance(capabilities, dict) or not capabilities:
                findings.append("v3 manifest.capabilities required")
        else:
            findings.append(f"unsupported manifest schema_version={schema_version!r}")
    except Exception as exc:  # noqa: BLE001
        findings.append(f"manifest contract: {type(exc).__name__}: {exc}")
    return findings


def _public_asset_entries(
    manifest: Mapping[str, Any],
) -> tuple[list[tuple[str, dict[str, Any]]], list[str]]:
    """Enumerate assets by schema version (v3 capabilities vs legacy files)."""

    findings: list[str] = []
    schema_version = manifest.get("schema_version")
    if schema_version == 3:
        capabilities = manifest.get("capabilities")
        if not isinstance(capabilities, dict):
            return [], ["v3 manifest.capabilities must be an object"]
        entries: list[tuple[str, dict[str, Any]]] = []
        for key, entry in capabilities.items():
            if not isinstance(entry, dict):
                findings.append(f"{key}: capability descriptor not object")
                continue
            sha = entry.get("sha256")
            encoding = entry.get("encoding") or "gzip"
            suffix = ".json.gz" if encoding == "gzip" else ".json"
            name = f"{sha}{suffix}" if isinstance(sha, str) else ""
            entries.append(
                (
                    key,
                    {
                        "name": name,
                        "sha256": sha,
                        "bytes": entry.get("compressed_bytes"),
                    },
                )
            )
        return entries, findings

    from app_payload_optional_assets import iter_payload_assets

    files = manifest.get("files")
    if not isinstance(files, dict):
        return [], ["manifest.files required for schema_version 1/2"]
    try:
        return list(iter_payload_assets(manifest)), findings
    except Exception as exc:  # noqa: BLE001
        findings.append(f"iter_payload_assets: {type(exc).__name__}: {exc}")
        return list(files.items()), findings


def bind_public_candidate_bytes(
    gate_dir: Path,
    *,
    target_commit: str,
    manifest_path: Path,
    asset_paths: Sequence[Path],
    candidate_generation: Optional[str],
    preservation_snapshot_sha256: Optional[str],
) -> dict[str, Any]:
    """PASS when decoded public assets match a schema-valid, identity-bound manifest."""

    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise GateBindError(f"expected regular manifest file: {manifest_path}")
    raw_manifest = manifest_path.read_bytes()
    manifest = _decode_json_object(raw_manifest, label="manifest")
    findings: list[str] = []

    schema_version = manifest.get("schema_version")
    findings.extend(_validate_public_manifest_contract(manifest))

    # Bind candidate identity when the manifest declares it.
    producer = (
        manifest.get("producer_commit")
        or manifest.get("git_commit")
        or manifest.get("source_commit")
    )
    source_obs = manifest.get("source_observation")
    if isinstance(source_obs, Mapping):
        producer = producer or source_obs.get("producer_commit") or source_obs.get(
            "git_commit"
        )
    if isinstance(producer, str) and canary.COMMIT_RE.fullmatch(producer):
        if producer != target_commit:
            findings.append(
                f"manifest producer/git commit {producer} != target_commit {target_commit}"
            )
    else:
        findings.append(
            "manifest missing producer/git commit binding to target_commit"
        )

    if candidate_generation:
        declared_gen = (
            manifest.get("candidate_generation")
            or manifest.get("generation_id")
            or (source_obs.get("generation_id") if isinstance(source_obs, Mapping) else None)
            or manifest.get("tag")
        )
        if declared_gen is None:
            findings.append(
                "manifest missing candidate_generation/generation_id/tag required "
                f"to bind candidate_generation {candidate_generation!r}"
            )
        elif str(declared_gen) != candidate_generation:
            findings.append(
                f"manifest generation/tag {declared_gen!r} != "
                f"candidate_generation {candidate_generation!r}"
            )

    checked: list[dict[str, Any]] = []
    evidence_items: list[dict[str, str]] = [
        emit.materialize_bytes(
            gate_dir,
            relative_path="receipts/public_candidate_manifest.source",
            raw=raw_manifest,
        )
    ]
    local_manifest = emit.materialize_receipt(
        gate_dir,
        relative_path="receipts/public_candidate_manifest.json",
        payload=manifest,
    )
    evidence_items.append(local_manifest)

    by_name = {path.name: path for path in asset_paths}
    asset_iter, enum_findings = _public_asset_entries(manifest)
    findings.extend(enum_findings)
    required_keys = {key for key, _entry in asset_iter}

    for key, entry in asset_iter:
        if not isinstance(entry, dict):
            findings.append(f"{key}: entry not object")
            continue
        name = Path(str(entry.get("name") or entry.get("url") or "")).name
        expected_sha = entry.get("sha256")
        expected_bytes = entry.get("bytes")
        if not isinstance(expected_sha, str) or not canary.SHA256_RE.fullmatch(expected_sha):
            findings.append(f"{key}: bad sha256")
            continue
        path = by_name.get(name)
        if path is None:
            for candidate in asset_paths:
                if expected_sha in candidate.name or key in candidate.name:
                    path = candidate
                    break
        if path is None or not path.is_file() or path.is_symlink():
            findings.append(f"{key}: asset file missing ({name})")
            continue
        wire = path.read_bytes()
        try:
            body = _decode_asset_domain_bytes(
                wire, expected_bytes=expected_bytes if isinstance(expected_bytes, int) else None
            )
        except Exception as exc:  # noqa: BLE001
            findings.append(f"{key}: transport decode failed: {type(exc).__name__}: {exc}")
            continue
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
        dest_rel = f"receipts/public_asset_{key}.meta.json"
        meta = {
            "key": key,
            "source_name": path.name,
            "wire_bytes": len(wire),
            "domain_bytes": len(body),
            "sha256": actual,
        }
        evidence_items.append(
            emit.materialize_receipt(gate_dir, relative_path=dest_rel, payload=meta)
        )
        checked.append(meta)

    checked_keys = {c["key"] for c in checked}
    assets_complete = bool(required_keys) and required_keys.issubset(checked_keys)
    # v1 files.core is mandatory; v2 references core via base.core_sha, not files.core.
    if schema_version == 1 and "core" not in checked_keys:
        assets_complete = False
    result = "PASS" if assets_complete and not findings else "FAIL"
    receipt = {
        "schema_version": 1,
        "binder": "public_candidate_bytes",
        "target_commit": target_commit,
        "candidate_generation": candidate_generation,
        "manifest_schema_version": schema_version,
        "manifest_source": str(manifest_path),
        "checked": checked,
        "required_keys": sorted(required_keys),
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
        raw = _load_json(restore_receipt)
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
        raw = _load_json(receipt_path)
        findings: list[str] = []
        for key, expected in required_fields.items():
            actual = raw.get(key)
            if actual != expected:
                findings.append(f"{key}: got {actual!r}, expected {expected!r}")
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


