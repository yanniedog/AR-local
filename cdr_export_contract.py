"""Immutable export-contract v2 for one preserved CDR observation generation."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from cdr_atomic import atomic_write_json, canonical_json_bytes

SCHEMA_VERSION = 2
NORMALIZATION_VERSION = "legacy-v1"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PROVIDER_STATES = {"complete", "empty", "partial", "failed", "not_attempted"}
_GENERATION_FIELDS = (
    "schema_version",
    "observation_date",
    "normalization_version",
    "observation_state",
    "register_hashes",
    "provider_states",
    "coverage",
    "quarantines",
    "artifacts",
)


@lru_cache(maxsize=1)
def _contract_validator() -> Draft202012Validator:
    schema_path = Path(__file__).resolve().parent / "contracts" / "export-contract-v2.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_records(root: Path) -> list[dict[str, Any]]:
    root = root.expanduser().resolve(strict=True)
    records: list[dict[str, Any]] = []
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": hash_file(path),
            }
        )
    if not records:
        raise ValueError(f"export generation has no artifacts: {root}")
    return records


def _finite_numbers(value: Any, path: str = "$") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite number at {path}")
    if isinstance(value, Mapping):
        for key, child in value.items():
            _finite_numbers(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _finite_numbers(child, f"{path}[{index}]")


def validate_contract(contract: Mapping[str, Any]) -> None:
    try:
        _contract_validator().validate(dict(contract))
    except ValidationError as error:
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        raise ValueError(f"export contract schema violation at {location}: {error.message}") from error
    if contract.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("export contract schema_version must be 2")
    date = str(contract.get("observation_date") or "")
    if not _DATE.fullmatch(date):
        raise ValueError("invalid observation_date")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as error:
        raise ValueError("invalid observation_date") from error
    observed_at = str(contract.get("observed_at") or "")
    try:
        observed_datetime = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("invalid observed_at") from error
    if observed_datetime.tzinfo is None:
        raise ValueError("observed_at must include a timezone offset")
    if contract.get("ledger_state") != "provisional":
        raise ValueError("export contract ledger_state must remain provisional")
    if contract.get("observation_state") not in {"complete", "partial", "failed"}:
        raise ValueError("invalid observation_state")
    source_generation_digest = str(contract.get("source_generation_digest") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", source_generation_digest):
        raise ValueError("invalid source_generation_digest")
    expected_generation_id = generation_id_for(
        date,
        source_generation_digest,
        contract.get("prior_ledger_head"),
    )
    if contract.get("generation_id") != expected_generation_id:
        raise ValueError(
            "generation_id does not match source generation and ledger position"
        )
    source_path = str(contract.get("source_path") or "")
    if not source_path or Path(source_path).is_absolute() or ".." in Path(source_path).parts:
        raise ValueError("export contract source_path must be safe and relative")
    marker_path = str(contract.get("completion_marker_path") or "")
    if not marker_path or Path(marker_path).is_absolute() or ".." in Path(marker_path).parts:
        raise ValueError(
            "export contract completion_marker_path must be safe and relative"
        )
    artifacts = contract.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("export contract requires artifacts")
    artifact_paths: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            raise ValueError("artifact must be an object")
        path = str(artifact.get("path") or "")
        if not path or Path(path).is_absolute() or ".." in Path(path).parts or path in artifact_paths:
            raise ValueError(f"unsafe or duplicate artifact path: {path!r}")
        artifact_paths.add(path)
        if not re.fullmatch(r"[0-9a-f]{64}", str(artifact.get("sha256") or "")):
            raise ValueError(f"invalid artifact sha256: {path}")
        if int(artifact.get("bytes", -1)) < 0:
            raise ValueError(f"invalid artifact byte count: {path}")
    provider_states = contract.get("provider_states")
    if not isinstance(provider_states, list):
        raise ValueError("provider_states must be a list")
    provider_ids: set[str] = set()
    for provider in provider_states:
        if not isinstance(provider, Mapping):
            raise ValueError("provider state must be an object")
        provider_id = str(provider.get("provider_uid") or "")
        state = str(provider.get("state") or "")
        if not provider_id or provider_id in provider_ids or state not in _PROVIDER_STATES:
            raise ValueError("invalid or duplicate provider state")
        provider_ids.add(provider_id)
    coverage = contract.get("coverage")
    if not isinstance(coverage, Mapping):
        raise ValueError("coverage must be an object")
    attempted = int(coverage.get("providers_attempted") or 0)
    state_attempted = sum(
        1 for provider in provider_states if provider.get("state") != "not_attempted"
    )
    if provider_states and attempted != state_attempted:
        raise ValueError("providers_attempted does not reconcile with provider_states")
    if contract.get("observation_state") == "complete":
        if coverage.get("failure_provenance_complete") is not True:
            raise ValueError("complete observation requires complete failure provenance")
        if any(provider.get("state") in {"partial", "failed"} for provider in provider_states):
            raise ValueError("complete observation cannot contain partial/failed providers")
    _finite_numbers(contract)


def contract_digest(contract: Mapping[str, Any]) -> str:
    material = dict(contract)
    material.pop("contract_digest", None)
    material.pop("generation_id", None)
    return hashlib.sha256(canonical_json_bytes(material)).hexdigest()


def source_generation_digest(contract: Mapping[str, Any]) -> str:
    """Identify source semantics without timestamps or mutable ledger position.

    This digest is intentionally independent of ``observed_at`` and
    ``prior_ledger_head``. A process retry after the immutable contract or
    ledger event lands must rediscover the same generation instead of creating
    a second observation solely because time or the ledger head advanced.
    """

    material = {field: contract.get(field) for field in _GENERATION_FIELDS}
    return hashlib.sha256(canonical_json_bytes(material)).hexdigest()


def generation_id_for(
    observation_date: str,
    source_digest: str,
    prior_ledger_head: Optional[str],
) -> str:
    """Bind a source generation to its immutable ledger insertion point."""

    material = {
        "source_generation_digest": source_digest,
        "prior_ledger_head": prior_ledger_head,
    }
    digest = hashlib.sha256(canonical_json_bytes(material)).hexdigest()
    return f"obs-{observation_date}-{digest[:16]}"


def build_contract(
    export_root: Path,
    *,
    observation_date: str,
    observed_at: Optional[str] = None,
    observation_state: str,
    source_path: str,
    completion_marker_path: str,
    coverage: Mapping[str, Any],
    provider_states: Iterable[Mapping[str, Any]] = (),
    register_hashes: Iterable[Mapping[str, Any]] = (),
    quarantines: Iterable[Mapping[str, Any]] = (),
    prior_ledger_head: Optional[str] = None,
    normalization_version: str = NORMALIZATION_VERSION,
    artifacts: Optional[Iterable[Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    contract: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "observation_date": observation_date,
        "observed_at": observed_at or utc_now(),
        "timezone": "Australia/Hobart",
        "normalization_version": normalization_version,
        "ledger_state": "provisional",
        "observation_state": observation_state,
        "source_path": source_path,
        "completion_marker_path": completion_marker_path,
        "register_hashes": [dict(item) for item in register_hashes],
        "provider_states": [dict(item) for item in provider_states],
        "coverage": dict(coverage),
        "quarantines": [dict(item) for item in quarantines],
        "artifacts": (
            [dict(item) for item in artifacts]
            if artifacts is not None
            else artifact_records(export_root)
        ),
        "prior_ledger_head": prior_ledger_head,
    }
    generation_digest = source_generation_digest(contract)
    contract["source_generation_digest"] = generation_digest
    digest = contract_digest(contract)
    contract["generation_id"] = generation_id_for(
        observation_date, generation_digest, prior_ledger_head
    )
    contract["contract_digest"] = digest
    validate_contract(contract)
    return contract


def write_contract(state_dir: Path, contract: Mapping[str, Any]) -> Path:
    validate_contract(contract)
    if source_generation_digest(contract) != contract.get("source_generation_digest"):
        raise ValueError("export contract source generation digest mismatch")
    if contract_digest(contract) != contract.get("contract_digest"):
        raise ValueError("export contract digest mismatch")
    date = str(contract["observation_date"])
    generation_id = str(contract["generation_id"])
    path = state_dir.expanduser().resolve() / "export-contracts-v2" / date / f"{generation_id}.json"
    atomic_write_json(path, contract, create_once=True)
    return path


def load_contract(path: Path) -> dict[str, Any]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    validate_contract(contract)
    if source_generation_digest(contract) != contract.get("source_generation_digest"):
        raise ValueError("export contract source generation digest mismatch")
    if contract_digest(contract) != contract.get("contract_digest"):
        raise ValueError("export contract digest mismatch")
    return contract
