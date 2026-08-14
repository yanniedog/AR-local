"""Tests for the immutable Pi canary acceptance contract."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pi_canary_acceptance  # noqa: E402


COMMIT = "a" * 40
REPOSITORY = "yanniedog/AR-local"


def acceptance_payload() -> dict:
    return {
        "schema_version": 1,
        "repository": REPOSITORY,
        "target_commit": COMMIT,
        "status": "passed",
        "candidate_generation": "shadow-2026-08-15-001",
        "preservation_snapshot_sha256": "b" * 64,
        "completed_at": "2026-08-15T01:30:00+10:00",
        "acceptance_gates": {
            name: True for name in pi_canary_acceptance.REQUIRED_ACCEPTANCE_GATES
        },
    }


def write_manifest(path: Path, payload: dict) -> str:
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def verify(path: Path, digest: str) -> dict:
    return pi_canary_acceptance.verify_canary_acceptance(
        path,
        expected_sha256=digest,
        expected_commit=COMMIT,
        expected_repository=REPOSITORY,
    )


def test_accepts_hash_bound_manifest_for_exact_commit(tmp_path: Path) -> None:
    path = tmp_path / "canary-acceptance.json"
    digest = write_manifest(path, acceptance_payload())

    assert verify(path, digest)["target_commit"] == COMMIT


def test_checked_in_schema_matches_runtime_contract() -> None:
    schema = json.loads(
        (ROOT / "contracts" / "canary-acceptance-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(acceptance_payload())
    assert set(schema["required"]) == set(pi_canary_acceptance.REQUIRED_FIELDS)
    assert set(schema["properties"]["acceptance_gates"]["required"]) == set(
        pi_canary_acceptance.REQUIRED_ACCEPTANCE_GATES
    )


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("target_commit", "c" * 40, "target_commit"),
        ("repository", "attacker/example", "repository"),
        ("status", "pending", "status"),
        ("preservation_snapshot_sha256", "unknown", "preservation_snapshot_sha256"),
        ("completed_at", "2026-08-15", "timezone"),
    ],
)
def test_rejects_wrong_identity_or_incomplete_status(
    tmp_path: Path, field: str, value: str, error: str
) -> None:
    payload = acceptance_payload()
    payload[field] = value
    path = tmp_path / "canary-acceptance.json"
    digest = write_manifest(path, payload)

    with pytest.raises(pi_canary_acceptance.CanaryAcceptanceError, match=error):
        verify(path, digest)


@pytest.mark.parametrize("gate", pi_canary_acceptance.REQUIRED_ACCEPTANCE_GATES)
def test_rejects_each_missing_or_failed_acceptance_gate(
    tmp_path: Path, gate: str
) -> None:
    payload = acceptance_payload()
    payload["acceptance_gates"][gate] = False
    path = tmp_path / "canary-acceptance.json"
    digest = write_manifest(path, payload)

    with pytest.raises(pi_canary_acceptance.CanaryAcceptanceError, match=gate):
        verify(path, digest)


def test_rejects_bytes_that_do_not_match_approved_digest(tmp_path: Path) -> None:
    path = tmp_path / "canary-acceptance.json"
    write_manifest(path, acceptance_payload())

    with pytest.raises(pi_canary_acceptance.CanaryAcceptanceError, match="mismatch"):
        verify(path, "f" * 64)


@pytest.mark.parametrize("container", ["manifest", "gates"])
def test_rejects_unversioned_extension_fields(tmp_path: Path, container: str) -> None:
    payload = acceptance_payload()
    if container == "manifest":
        payload["extra"] = True
    else:
        payload["acceptance_gates"]["extra"] = True
    path = tmp_path / "canary-acceptance.json"
    digest = write_manifest(path, payload)

    with pytest.raises(pi_canary_acceptance.CanaryAcceptanceError, match="unexpected"):
        verify(path, digest)


def test_rejects_oversized_manifest_before_parsing(tmp_path: Path) -> None:
    path = tmp_path / "canary-acceptance.json"
    raw = b"{" + b" " * pi_canary_acceptance.MAX_MANIFEST_BYTES
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()

    with pytest.raises(pi_canary_acceptance.CanaryAcceptanceError, match="size"):
        verify(path, digest)
