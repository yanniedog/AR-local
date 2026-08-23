"""Schema validation and immutable evidence capture for physical boot proofs."""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Mapping

from jsonschema import Draft202012Validator, FormatChecker

from ar_local_backup_policy import (
    BackupPolicy,
    COMMIT_RE,
    SHA256_RE,
    atomic_copy_verified,
    atomic_create_json,
    record_is_fresh,
    sha256_file,
    validate_plan_identity,
)

BOOT_SCHEMA = Path(__file__).resolve().parent / "contracts/pi-backup-boot-proof-v1.schema.json"


def _json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = json.loads(BOOT_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_boot_proof(
    path: Path,
    policy: BackupPolicy,
    now: datetime,
    candidate_sha: str | None = None,
) -> dict[str, object]:
    proof = _json(path)
    findings = [
        "boot_schema_invalid:"
        + ".".join(str(part) for part in error.absolute_path)
        + f":{error.validator}"
        for error in sorted(_validator().iter_errors(proof), key=lambda item: list(item.absolute_path))
    ]
    if proof.get("result") != "PASS":
        findings.append("boot_result_not_pass")
    if not validate_plan_identity(proof, policy):
        findings.append("plan_identity_mismatch")
    if candidate_sha is not None and proof.get("candidate_code_sha") != candidate_sha:
        findings.append("boot_candidate_sha_mismatch")
    if not COMMIT_RE.fullmatch(str(proof.get("candidate_code_sha") or "")):
        findings.append("boot_candidate_sha_invalid")
    if proof.get("backup_device_id") != policy.expected_source:
        findings.append("boot_device_id_mismatch")
    if not record_is_fresh(proof, policy.max_boot_proof_age_hours, now):
        findings.append("boot_proof_stale_or_future")
    evidence = proof.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        findings.append("boot_evidence_invalid")
    else:
        for item in evidence:
            if not isinstance(item, Mapping):
                findings.append("boot_evidence_invalid")
                continue
            evidence_path = Path(str(item.get("path") or ""))
            digest = str(item.get("sha256") or "")
            if not evidence_path.is_absolute() or not evidence_path.is_file() or not SHA256_RE.fullmatch(digest):
                findings.append(f"boot_evidence_missing:{evidence_path}")
            elif sha256_file(evidence_path) != digest:
                findings.append(f"boot_evidence_hash_mismatch:{evidence_path}")
    for field in ("network", "dashboard", "ingest_timers", "storage_identity"):
        value = proof.get(field)
        if not isinstance(value, Mapping) or value.get("ok") is not True:
            findings.append(f"boot_{field}_not_verified")
    storage = proof.get("storage_identity")
    if isinstance(storage, Mapping):
        expected_storage = {
            "source": policy.expected_source,
            "mountpoint": str(policy.mountpoint),
            "fstype": policy.expected_fstype,
        }
        if any(storage.get(key) != value for key, value in expected_storage.items()):
            findings.append("boot_storage_identity_mismatch")
    deviations = proof.get("deviations")
    if not isinstance(deviations, list):
        findings.append("boot_deviations_invalid")
    elif deviations or proof.get("deviation_authorization") is not None:
        findings.append("boot_deviation_not_authorized_by_gate")
    return {"ok": not findings, "findings": findings, "proof": proof}


def archive_boot_evidence(boot_proof: Path, archive_root: Path) -> list[Path]:
    """Preserve the original proof and every referenced artifact create-once."""

    proof = _json(boot_proof)
    original = archive_root / "boot-proof.original.json"
    atomic_create_json(original, proof)
    archived_entries: list[dict[str, object]] = []
    artifact_paths: list[Path] = []
    for index, item in enumerate(proof.get("evidence") or []):
        if not isinstance(item, Mapping):
            raise ValueError("boot evidence entry is invalid")
        source = Path(str(item["path"]))
        digest = str(item["sha256"])
        target = archive_root / "artifacts" / f"{index:04d}.bin"
        atomic_copy_verified(source, target, digest)
        artifact_paths.append(target)
        archived_entries.append(
            {"path": str(target.resolve()), "sha256": digest, "original_path": str(source)}
        )
    archived = archive_root / "boot-proof.archived.json"
    atomic_create_json(archived, {**proof, "evidence": archived_entries})
    return [original, archived, *artifact_paths]
