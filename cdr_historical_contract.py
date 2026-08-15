"""Strict primitives for the dormant legacy historical-candidate contract."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parent
CONTRACT_ROOT = ROOT / "contracts" / "historical"
SCHEMAS = {
    "corpus_lock": CONTRACT_ROOT / "corpus-lock-v1.schema.json",
    "source_manifest": CONTRACT_ROOT / "source-manifest-v1.schema.json",
    "additions_audit": CONTRACT_ROOT / "additions-audit-v1.schema.json",
    "candidate_manifest": CONTRACT_ROOT / "candidate-manifest-v1.schema.json",
    "history_index": CONTRACT_ROOT / "history-index-v1.schema.json",
    "acceptance_report": CONTRACT_ROOT / "acceptance-report-v1.schema.json",
}
CORPUS_LOCK_PATH = CONTRACT_ROOT / "corpus-lock-v1.json"
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
SQLITE_TRANSIENT_SUFFIXES = (".sqlite-shm", ".sqlite-wal")
CANDIDATE_ID_RE = re.compile(
    r"^hist-(\d{4}-\d{2}-\d{2})-v(\d{4})-r(\d{4})-([0-9a-f]{12})$"
)
FORBIDDEN_OPERATIONAL_KEYS = {
    "latest",
    "latest_url",
    "publisher",
    "publisher_id",
    "release",
    "release_id",
    "release_tag",
    "url",
    "download_url",
    "promotion_state",
    "complete",
}


class HistoricalContractError(ValueError):
    """Raised when historical evidence fails a closed contract boundary."""


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise HistoricalContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json_bytes(payload: bytes, *, source: str = "JSON") -> Any:
    try:
        # The preservation tooling emitted a small number of PowerShell JSON
        # manifests with a UTF-8 BOM. Their raw bytes remain hash-bound; parsing
        # accepts that marker without normalizing or rewriting the evidence.
        text = payload.decode("utf-8-sig")
        return json.loads(
            text,
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                HistoricalContractError(f"non-finite JSON value in {source}: {value}")
            ),
        )
    except UnicodeDecodeError as error:
        raise HistoricalContractError(f"{source} is not UTF-8") from error
    except json.JSONDecodeError as error:
        raise HistoricalContractError(f"invalid {source}: {error}") from error


def load_strict_json(path: Path) -> Any:
    return strict_json_bytes(path.read_bytes(), source=str(path))


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise HistoricalContractError(f"value is not canonical JSON: {error}") from error


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path, *, chunk_bytes: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_bytes):
            digest.update(chunk)
    return digest.hexdigest()


def portable_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise HistoricalContractError(f"invalid portable path: {value!r}")
    if not value.isascii():
        raise HistoricalContractError(f"portable path must be ASCII: {value!r}")
    pure = PurePosixPath(value)
    if pure.is_absolute() or pure.drive or any(part in {"", ".", ".."} for part in pure.parts):
        raise HistoricalContractError(f"unsafe portable path: {value!r}")
    if ":" in pure.parts[0]:
        raise HistoricalContractError(f"drive-qualified portable path: {value!r}")
    return pure.as_posix()


def unique_portable_paths(values: Iterable[str]) -> tuple[str, ...]:
    paths: list[str] = []
    folded: dict[str, str] = {}
    for raw in values:
        value = portable_path(raw)
        key = value.casefold()
        if key in folded:
            raise HistoricalContractError(
                f"case-fold path collision: {folded[key]!r} and {value!r}"
            )
        folded[key] = value
        paths.append(value)
    return tuple(paths)


def _schema(name: str) -> Mapping[str, Any]:
    value = load_strict_json(SCHEMAS[name])
    if not isinstance(value, dict):
        raise HistoricalContractError(f"schema {name} is not an object")
    Draft202012Validator.check_schema(value)
    return value


def validate_schema(name: str, value: Mapping[str, Any]) -> dict[str, Any]:
    Draft202012Validator(_schema(name), format_checker=FormatChecker()).validate(value)
    _reject_operational_fields(value)
    return dict(value)


def _reject_operational_fields(value: Any, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in FORBIDDEN_OPERATIONAL_KEYS:
                raise HistoricalContractError(f"operational field forbidden at {path}.{key}")
            _reject_operational_fields(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_operational_fields(child, path=f"{path}[{index}]")


def validate_source_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    result = validate_schema("source_manifest", value)
    artifacts = result["artifacts"]
    unique_portable_paths(item["path"] for item in artifacts)
    if any(
        item["path"].casefold().endswith(SQLITE_TRANSIENT_SUFFIXES)
        for item in artifacts
    ):
        raise HistoricalContractError(
            "SQLite WAL and SHM sidecars cannot be candidate inputs"
        )
    digest = sha256_bytes(canonical_json_bytes(artifacts))
    if result["artifact_set_sha256"] != digest:
        raise HistoricalContractError("artifact_set_sha256 does not bind artifacts")
    return result


def candidate_identity(value: Mapping[str, Any]) -> str:
    body = dict(value)
    body.pop("candidate_id", None)
    return sha256_bytes(canonical_json_bytes(body))


def validate_candidate(value: Mapping[str, Any]) -> dict[str, Any]:
    result = validate_schema("candidate_manifest", value)
    match = CANDIDATE_ID_RE.fullmatch(result["candidate_id"])
    if not match:
        raise HistoricalContractError("candidate_id is malformed")
    coordinate = result["coordinate"]
    identity = candidate_identity(result)
    expected = (
        f"hist-{coordinate['date']}-v{coordinate['variant_ordinal']:04d}"
        f"-r{coordinate['revision_ordinal']:04d}-{identity[:12]}"
    )
    if result["candidate_id"] != expected:
        raise HistoricalContractError("candidate_id does not bind canonical candidate identity")
    relation = result["lineage"]["relation"]
    parents = (
        result["lineage"]["parent_candidate_sha256"],
        result["lineage"]["parent_source_manifest_sha256"],
    )
    if relation == "legacy_external_correction":
        if coordinate["revision_ordinal"] <= 1 or not all(parents):
            raise HistoricalContractError("correction requires same-date parent digests")
    elif any(parent is not None for parent in parents):
        raise HistoricalContractError("root and parallel projections cannot claim parents")
    if relation == "parallel_projection" and coordinate["variant_ordinal"] <= 1:
        raise HistoricalContractError("parallel projection requires variant ordinal greater than one")
    unique_portable_paths(item["path"] for item in result["artifacts"])
    if any(
        item["path"].casefold().endswith(SQLITE_TRANSIENT_SUFFIXES)
        for item in result["artifacts"]
    ):
        raise HistoricalContractError(
            "SQLite WAL and SHM sidecars cannot be candidate artifacts"
        )
    unique_portable_paths(item["path"] for item in result["tool"]["files"])
    return result


def validate_history_index(value: Mapping[str, Any]) -> dict[str, Any]:
    result = validate_schema("history_index", value)
    dates = [item["date"] for item in result["dates"]]
    if dates != sorted(dates) or len(dates) != len(set(dates)):
        raise HistoricalContractError("history dates must be unique and sorted")
    gaps = [item["date"] for item in result["gaps"]]
    if gaps != ["2026-05-14", "2026-06-26"] or set(gaps) & set(dates):
        raise HistoricalContractError("history gaps must be exact and separate")
    candidates = [candidate for item in result["dates"] for candidate in item["candidates"]]
    if result["candidate_count"] != len(candidates):
        raise HistoricalContractError("candidate_count does not match index")
    if len({item["candidate_id"] for item in candidates}) != len(candidates):
        raise HistoricalContractError("candidate IDs must be unique")
    return result


def validate_contract_tree() -> dict[str, Any]:
    lock = load_strict_json(CONTRACT_ROOT / "contract-lock.json")
    if not isinstance(lock, dict) or lock.get("activation_state") != "dormant":
        raise HistoricalContractError("historical contract must remain dormant")
    expected = sorted(path.name for path in SCHEMAS.values())
    if lock.get("schemas") != expected:
        raise HistoricalContractError("contract lock does not list the exact schemas")
    for name in SCHEMAS:
        _schema(name)
    corpus = load_strict_json(CORPUS_LOCK_PATH)
    if not isinstance(corpus, dict):
        raise HistoricalContractError("corpus lock is not an object")
    validate_schema("corpus_lock", corpus)
    stable = corpus["immutable_critical_population"]
    transient = corpus["transient_evidence_population"]
    critical = corpus["critical_population"]
    if stable["files"] + transient["files"] != critical["files"] or stable[
        "bytes"
    ] + transient["bytes"] != critical["bytes"]:
        raise HistoricalContractError(
            "candidate and transient populations do not partition critical evidence"
        )
    if transient["candidate_input"] is not False:
        raise HistoricalContractError("SQLite transient evidence cannot be a candidate input")
    if corpus["gaps"] != [
        {"date": "2026-05-14", "status": "known_gap"},
        {"date": "2026-06-26", "status": "unclassified_gap"},
    ]:
        raise HistoricalContractError("corpus gap lock differs from evidence")
    return corpus
