#!/usr/bin/env python3
"""Public-candidate-bytes binder and helpers (fail-closed)."""

from __future__ import annotations

import gzip
import io
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import pi_canary_acceptance as canary
import pi_canary_gate_emit as emit
from cdr_domain import contract_validation
from pi_canary_gate_bind_checks import validate_v1_payload_root
from pi_canary_gate_bind_ops import (
    GateBindError,
    _require_generation,
    _require_snapshot,
)

def _validate_v2_asset_gzip(kind: str, raw: bytes, entry: Mapping[str, Any]) -> None:
    """Match publication path: decompress gzip assets and check expansion budgets."""

    from app_payload_contracts import MAX_V2_ASSET_UNCOMPRESSED_BYTES

    encoding = entry.get("encoding") or "gzip"
    if encoding != "gzip":
        raise ValueError(f"{kind}: encoding must be gzip, got {encoding!r}")
    uncompressed = entry.get("uncompressed_bytes")
    if type(uncompressed) is not int or uncompressed < 1:
        raise ValueError(f"{kind}: uncompressed_bytes required")
    budget = MAX_V2_ASSET_UNCOMPRESSED_BYTES.get(kind)
    if budget is None:
        raise ValueError(f"{kind}: unknown v2 asset kind")
    total = 0
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            if total > budget:
                raise ValueError(f"{kind}: gzip expansion exceeds budget")
    if total != uncompressed:
        raise ValueError(
            f"{kind}: uncompressed size mismatch got={total} expected={uncompressed}"
        )


def _resolve_asset_by_sha(
    asset_paths: Sequence[Path], *, expected_sha: str
) -> Optional[tuple[Path, bytes]]:
    """Locate an asset whose domain bytes hash to ``expected_sha``."""

    for path in asset_paths:
        if path.is_symlink() or not path.is_file():
            continue
        wire = path.read_bytes()
        try:
            body = _decode_asset_domain_bytes(wire, expected_bytes=None)
        except Exception:  # noqa: BLE001 — try next candidate
            continue
        if emit.sha256_bytes(body) == expected_sha:
            return path, body
        # Also accept wire digest when transport is identity.
        if emit.sha256_bytes(wire) == expected_sha:
            return path, wire
    return None


def _verify_v2_base_assets(
    gate_dir: Path,
    *,
    manifest: Mapping[str, Any],
    asset_paths: Sequence[Path],
    evidence_items: list[dict[str, str]],
    checked: list[dict[str, Any]],
) -> list[str]:
    """Require base.core_sha / base.details_sha bytes before authorizing v2 PASS.

    Mirrors ``app_payload_v2_archive.archive_v2`` which verifies both base assets
    against the bound v1 hashes before accepting the bundle.
    """

    findings: list[str] = []
    base = manifest.get("base")
    if not isinstance(base, Mapping):
        return ["v2 base object required"]
    for kind in ("core", "details"):
        expected_sha = base.get(f"{kind}_sha")
        if not isinstance(expected_sha, str) or not canary.SHA256_RE.fullmatch(expected_sha):
            findings.append(f"base.{kind}_sha missing or not 64 hex")
            continue
        resolved = _resolve_asset_by_sha(asset_paths, expected_sha=expected_sha)
        if resolved is None:
            findings.append(
                f"base.{kind}_sha asset missing (expected sha256={expected_sha})"
            )
            continue
        path, body = resolved
        key = f"base_{kind}"
        meta = {
            "key": key,
            "source_name": path.name,
            "domain_bytes": len(body),
            "sha256": expected_sha,
        }
        evidence_items.append(
            emit.materialize_receipt(
                gate_dir,
                relative_path=f"receipts/public_asset_{key}.meta.json",
                payload=meta,
            )
        )
        checked.append(meta)
    return findings

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


def _v2_identity_from_base_manifest(
    manifest: Mapping[str, Any], asset_paths: Sequence[Path]
) -> tuple[Optional[str], Optional[Any]]:
    """Recover producer/generation from a v1 base manifest matching ``base.core_sha``."""

    base = manifest.get("base")
    if not isinstance(base, Mapping):
        return None, None
    core_sha = base.get("core_sha")
    if not isinstance(core_sha, str) or not canary.SHA256_RE.fullmatch(core_sha):
        return None, None
    for path in asset_paths:
        if path.is_symlink() or not path.is_file():
            continue
        name = path.name.lower()
        if "manifest-v2" in name or "manifest" not in name:
            continue
        try:
            raw = path.read_bytes()
            obj = _decode_json_object(raw, label=f"base-manifest:{path.name}")
        except Exception:  # noqa: BLE001
            continue
        if obj.get("schema_version") != 1:
            continue
        files = obj.get("files")
        if not isinstance(files, Mapping):
            continue
        core = files.get("core")
        if not isinstance(core, Mapping) or core.get("sha256") != core_sha:
            continue
        producer = (
            obj.get("producer_commit")
            or obj.get("git_commit")
            or obj.get("source_commit")
        )
        source_obs = obj.get("source_observation")
        if isinstance(source_obs, Mapping):
            producer = producer or source_obs.get("producer_commit") or source_obs.get(
                "git_commit"
            )
        gen = (
            obj.get("candidate_generation")
            or obj.get("generation_id")
            or (source_obs.get("generation_id") if isinstance(source_obs, Mapping) else None)
            or obj.get("tag")
        )
        return (
            producer if isinstance(producer, str) else None,
            gen,
        )
    return None, None


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
    declared_gen = (
        manifest.get("candidate_generation")
        or manifest.get("generation_id")
        or (source_obs.get("generation_id") if isinstance(source_obs, Mapping) else None)
        or manifest.get("tag")
    )
    # v2 sidecars historically omitted identity; recover from a validated v1 base
    # manifest among supplied assets whose core hash matches base.core_sha.
    if schema_version == 2 and (
        not (isinstance(producer, str) and canary.COMMIT_RE.fullmatch(producer or ""))
        or (candidate_generation and declared_gen is None)
    ):
        base_prod, base_gen = _v2_identity_from_base_manifest(manifest, asset_paths)
        if not (isinstance(producer, str) and canary.COMMIT_RE.fullmatch(producer or "")):
            producer = base_prod
        if candidate_generation and declared_gen is None:
            declared_gen = base_gen
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
    capability_bytes: dict[str, bytes] = {}
    domain_by_name: dict[str, bytes] = {}

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
        if schema_version == 2:
            try:
                _validate_v2_asset_gzip(key, body, entry)
            except Exception as exc:  # noqa: BLE001
                findings.append(f"{key}: v2 gzip validation: {type(exc).__name__}: {exc}")
                continue
        capability_bytes[key] = body
        if name:
            domain_by_name[name] = body
        dest_rel = f"receipts/public_asset_{key}.meta.json"
        meta = {
            "key": key,
            "name": name,
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
    # v2: publication preservation also requires the bound v1 base assets.
    if schema_version == 2:
        base_findings = _verify_v2_base_assets(
            gate_dir,
            manifest=manifest,
            asset_paths=asset_paths,
            evidence_items=evidence_items,
            checked=checked,
        )
        findings.extend(base_findings)
        if base_findings:
            assets_complete = False
        checked_keys = {c["key"] for c in checked}
    # Match publication path: decompress + core/coverage checks before authorizing bytes.
    if schema_version == 3 and assets_complete:
        try:
            contract_validation.validate_generation_manifest(
                manifest, {key: capability_bytes[key] for key in required_keys}
            )
        except Exception as exc:  # noqa: BLE001
            findings.append(f"v3 generation validation: {type(exc).__name__}: {exc}")
    # v1: historical catalogue/packed/ready envelopes must bind to files.core.
    if schema_version == 1 and assets_complete:
        hist_findings = validate_v1_payload_root(manifest, domain_by_name)
        findings.extend(hist_findings)
        if hist_findings:
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
