"""Pure payload-v3 candidate, census, pointer, and dates-index state rules."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from cdr_domain.contract_validation import (
    contract_sha256,
    validate_asset_descriptor,
    validate_contract,
    validate_generation_manifest,
    validate_generation_pointer,
)
from cdr_domain.serialize import canonical_json_bytes


CANONICAL_REPO = "yanniedog/AR-local"
CONTENT_RELEASE_TAG = "app-payload-gen"
CANDIDATE_TAG_PREFIX = "app-payload-v3-candidate-"
CONTROL_BRANCH = "app-payload-v3-control"
LOCK_BRANCH = "app-payload-v3-promotion-lock"
POINTER_FILENAME = "generation-pointer-v3.json"
DATES_INDEX_FILENAME = "complete-dates-index-v3.json"
LOCK_FILENAME = "promotion-lock-v3.json"
V3_MANIFEST_LIMIT_BYTES = 64 * 1024
V3_POINTER_LIMIT_BYTES = 64 * 1024
V3_DATES_INDEX_LIMIT_BYTES = 8 * 1024 * 1024
V3_LOCK_LIMIT_BYTES = 64 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GENERATION = re.compile(
    r"^gen-(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})-r"
    r"(?P<revision>[0-9]{4})-(?P<digest>[0-9a-f]{12})$"
)
_MANIFEST_NAME = re.compile(r"^[0-9a-f]{64}\.json$")


class PromotionError(RuntimeError):
    """A fail-closed candidate or remote-state error."""


class ConcurrencyError(PromotionError):
    """The repository-wide owner token or expected branch head changed."""


class RemoteNotFound(PromotionError):
    """A required public object does not exist."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PromotionError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_json_constant(token: str) -> None:
    raise PromotionError(f"non-finite JSON number is forbidden: {token}")


def strict_object(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PromotionError(f"{label} is not unambiguous UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise PromotionError(f"{label} must be a JSON object")
    return value


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def generation_coordinate(generation_id: str) -> tuple[str, int]:
    match = _GENERATION.fullmatch(str(generation_id))
    if not match:
        raise PromotionError("candidate has an invalid generation_id")
    try:
        date.fromisoformat(match.group("date"))
    except ValueError as error:
        raise PromotionError("candidate generation_id has an invalid date") from error
    return match.group("date"), int(match.group("revision"))


def release_url(repo: str, tag: str, filename: str) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}/{filename}"


def asset_filename(descriptor: Mapping[str, Any]) -> str:
    validate_asset_descriptor(descriptor)
    parsed = urllib.parse.urlparse(str(descriptor["url"]))
    filename = PurePosixPath(parsed.path).name
    if filename != f"{descriptor['sha256']}.json.gz":
        raise PromotionError("capability URL filename is not its exact SHA-256")
    expected_url = release_url(CANONICAL_REPO, CONTENT_RELEASE_TAG, filename)
    if str(descriptor["url"]) != expected_url:
        raise PromotionError("capability URL is outside the v3 content release")
    return filename


@dataclass(frozen=True)
class CandidateBundle:
    directory: Path
    manifest: Mapping[str, Any]
    manifest_bytes: bytes
    capability_bytes: Mapping[str, bytes]

    @property
    def generation_id(self) -> str:
        return str(self.manifest["generation_id"])

    @property
    def manifest_sha256(self) -> str:
        return sha256(self.manifest_bytes)

    @property
    def manifest_filename(self) -> str:
        return f"{self.manifest_sha256}.json"

    @property
    def candidate_tag(self) -> str:
        return CANDIDATE_TAG_PREFIX + self.generation_id

    def head(self, repo: str = CANONICAL_REPO) -> dict[str, Any]:
        return {
            "generation_id": self.generation_id,
            "generation_revision": self.manifest["generation_revision"],
            "generation_digest": self.manifest["generation_digest"],
            "manifest_sha256": self.manifest_sha256,
            "observation_date": self.manifest["observation_date"],
            "observation_state": self.manifest["observation_state"],
            "manifest_url": release_url(
                repo, self.candidate_tag, self.manifest_filename
            ),
        }


def _read_exact_file(path: Path, expected_bytes: int, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise PromotionError(f"{label} is not a regular file")
    if path.stat().st_size != expected_bytes:
        raise PromotionError(f"{label} byte count disagrees with its descriptor")
    return path.read_bytes()


def load_candidate(directory: Path) -> CandidateBundle:
    supplied = Path(directory)
    if supplied.is_symlink() or not supplied.is_dir():
        raise PromotionError("candidate directory must be a real directory")
    directory = supplied.resolve()
    entries = {entry.name: entry for entry in directory.iterdir()}
    manifests = [name for name in entries if _MANIFEST_NAME.fullmatch(name)]
    if len(manifests) != 1:
        raise PromotionError("candidate directory must contain exactly one manifest")
    manifest_path = entries[manifests[0]]
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise PromotionError("candidate manifest must be a regular file")
    if manifest_path.stat().st_size > V3_MANIFEST_LIMIT_BYTES:
        raise PromotionError("candidate manifest exceeds its byte limit")
    manifest_bytes = manifest_path.read_bytes()
    if manifest_path.name != f"{sha256(manifest_bytes)}.json":
        raise PromotionError("candidate manifest filename does not match its exact bytes")
    manifest = strict_object(manifest_bytes, "candidate manifest")
    validate_contract("generation-manifest-v3.schema.json", manifest)
    capability_bytes: dict[str, bytes] = {}
    expected_names = {manifest_path.name}
    for capability, descriptor in manifest["capabilities"].items():
        filename = asset_filename(descriptor)
        expected_names.add(filename)
        try:
            path = entries[filename]
        except KeyError as error:
            raise PromotionError(f"candidate capability is missing: {capability}") from error
        payload = _read_exact_file(
            path, int(descriptor["compressed_bytes"]), f"candidate {capability}"
        )
        if sha256(payload) != descriptor["sha256"]:
            raise PromotionError(f"candidate {capability} SHA-256 does not match")
        capability_bytes[capability] = payload
    if set(entries) != expected_names:
        raise PromotionError("candidate directory contains unexpected files")
    validate_generation_manifest(manifest, capability_bytes)
    if directory.name != manifest["generation_id"]:
        raise PromotionError("candidate directory name must equal generation_id")
    return CandidateBundle(directory, manifest, manifest_bytes, capability_bytes)


def ordered_census(candidates: Sequence[CandidateBundle]) -> tuple[CandidateBundle, ...]:
    if not candidates:
        raise PromotionError("verified candidate census is empty")
    by_coordinate: dict[tuple[str, int], CandidateBundle] = {}
    for candidate in candidates:
        coordinate = generation_coordinate(candidate.generation_id)
        if coordinate in by_coordinate:
            raise PromotionError("multiple generations occupy one date/revision coordinate")
        by_coordinate[coordinate] = candidate
    ordered = tuple(by_coordinate[key] for key in sorted(by_coordinate))
    if ordered[0].manifest["prior_ledger_digest"] is not None:
        raise PromotionError("first candidate generation must start at a null ledger prior")
    for previous, current in zip(ordered, ordered[1:]):
        if current.manifest["prior_ledger_digest"] != previous.manifest["ledger_event_digest"]:
            raise PromotionError("candidate census contains disconnected ledger lineage")
    return ordered


def complete_heads(census: Sequence[CandidateBundle], repo: str) -> list[dict[str, Any]]:
    latest: dict[str, CandidateBundle] = {}
    for candidate in ordered_census(census):
        if candidate.manifest["observation_state"] != "complete":
            continue
        day = str(candidate.manifest["observation_date"])
        latest[day] = candidate
    return [latest[day].head(repo) for day in sorted(latest)]


def build_pointer(
    census: Sequence[CandidateBundle],
    *,
    generated_at: str,
    previous_bytes: bytes | None,
    previous_pointer: Mapping[str, Any] | None,
    previous_manifests: Mapping[str, bytes],
    previous_capabilities: Mapping[str, Mapping[str, bytes]],
    repo: str = CANONICAL_REPO,
) -> bytes:
    ordered = ordered_census(census)
    complete = [
        candidate
        for candidate in ordered
        if candidate.manifest["observation_state"] == "complete"
    ]
    if not complete:
        raise PromotionError("v3 pointer requires at least one complete generation")
    observation_head = ordered[-1].head(repo)
    complete_head = complete[-1].head(repo)
    if previous_pointer is not None and (
        observation_head == previous_pointer["latest_observation"]
        and complete_head == previous_pointer["latest_complete"]
    ):
        return previous_bytes or b""
    pointer = {
        "schema_version": 3,
        "generated_at": generated_at,
        "contract_sha256": contract_sha256(),
        "latest_observation": observation_head,
        "latest_complete": complete_head,
    }
    encoded = canonical_json_bytes(pointer)
    manifests = dict(previous_manifests)
    capabilities = dict(previous_capabilities)
    for candidate in ordered:
        manifests[candidate.generation_id] = candidate.manifest_bytes
        capabilities[candidate.generation_id] = candidate.capability_bytes
    kwargs: dict[str, Any] = {}
    if previous_bytes is not None:
        kwargs = {
            "previous_pointer_bytes": previous_bytes,
            "expected_previous_pointer_sha256": sha256(previous_bytes),
        }
    validate_generation_pointer(pointer, manifests, capabilities, **kwargs)
    return encoded


def validate_dates_index(value: Mapping[str, Any]) -> None:
    expected = {"schema_version", "generated_at", "contract_sha256", "count", "dates"}
    if set(value) != expected or value.get("schema_version") != 3:
        raise PromotionError("complete dates index has unsupported fields")
    if value.get("contract_sha256") != contract_sha256():
        raise PromotionError("complete dates index contract SHA is stale")
    dates = value.get("dates")
    count = value.get("count")
    if (
        not isinstance(dates, list)
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count != len(dates)
    ):
        raise PromotionError("complete dates index count does not reconcile")
    generated_at = value.get("generated_at")
    if not isinstance(generated_at, str):
        raise PromotionError("complete dates index generated_at is invalid")
    try:
        parsed_generated_at = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise PromotionError("complete dates index generated_at is invalid") from error
    if parsed_generated_at.tzinfo is None:
        raise PromotionError("complete dates index generated_at requires a timezone")
    previous_date = ""
    for entry in dates:
        if not isinstance(entry, dict) or entry.get("observation_state") != "complete":
            raise PromotionError("complete dates index contains a non-complete entry")
        required = {
            "generation_id",
            "generation_revision",
            "generation_digest",
            "manifest_sha256",
            "observation_date",
            "observation_state",
            "manifest_url",
        }
        if set(entry) != required:
            raise PromotionError("complete dates index entry fields are unsupported")
        generation_id = entry["generation_id"]
        observation_date = entry["observation_date"]
        revision = entry["generation_revision"]
        generation_digest = entry["generation_digest"]
        manifest_sha256 = entry["manifest_sha256"]
        if (
            not isinstance(generation_id, str)
            or not isinstance(observation_date, str)
            or isinstance(revision, bool)
            or not isinstance(revision, int)
            or not isinstance(generation_digest, str)
            or not isinstance(manifest_sha256, str)
        ):
            raise PromotionError("complete dates index entry types are invalid")
        coordinate = generation_coordinate(generation_id)
        if coordinate != (observation_date, revision):
            raise PromotionError("complete dates index coordinate does not reconcile")
        if not _SHA256.fullmatch(generation_digest) or not generation_digest.startswith(
            generation_id.rsplit("-", 1)[1]
        ):
            raise PromotionError("complete dates index generation digest is invalid")
        if not _SHA256.fullmatch(manifest_sha256):
            raise PromotionError("complete dates index manifest hash is invalid")
        expected_url = release_url(
            CANONICAL_REPO,
            CANDIDATE_TAG_PREFIX + generation_id,
            f"{manifest_sha256}.json",
        )
        if entry["manifest_url"] != expected_url:
            raise PromotionError("complete dates index manifest URL is not hash-bound")
        if observation_date <= previous_date:
            raise PromotionError("complete dates index entries are not strictly ordered")
        previous_date = observation_date


def build_dates_index(
    heads: Sequence[Mapping[str, Any]],
    *,
    generated_at: str,
    previous_bytes: bytes | None,
) -> bytes:
    ordered = [dict(head) for head in sorted(heads, key=lambda item: item["observation_date"])]
    value = {
        "schema_version": 3,
        "generated_at": generated_at,
        "contract_sha256": contract_sha256(),
        "count": len(ordered),
        "dates": ordered,
    }
    validate_dates_index(value)
    if previous_bytes is not None:
        if len(previous_bytes) > V3_DATES_INDEX_LIMIT_BYTES:
            raise PromotionError("prior complete dates index exceeds its byte limit")
        previous = strict_object(previous_bytes, "prior complete dates index")
        validate_dates_index(previous)
        prior_heads = {item["observation_date"]: item for item in previous["dates"]}
        current_heads = {item["observation_date"]: item for item in ordered}
        for day, prior in prior_heads.items():
            current = current_heads.get(day)
            if current is None or current["generation_revision"] < prior["generation_revision"]:
                raise PromotionError("complete dates index cannot drop or regress a prior date")
            if current["generation_revision"] == prior["generation_revision"] and current != prior:
                raise PromotionError("complete dates index cannot rebind a prior revision")
        if {**previous, "generated_at": generated_at} == value:
            return previous_bytes
    encoded = canonical_json_bytes(value)
    if len(encoded) > V3_DATES_INDEX_LIMIT_BYTES:
        raise PromotionError("complete dates index exceeds its byte limit")
    return encoded


__all__ = [
    "CANONICAL_REPO",
    "CANDIDATE_TAG_PREFIX",
    "CONTENT_RELEASE_TAG",
    "CONTROL_BRANCH",
    "DATES_INDEX_FILENAME",
    "LOCK_BRANCH",
    "LOCK_FILENAME",
    "POINTER_FILENAME",
    "V3_DATES_INDEX_LIMIT_BYTES",
    "V3_LOCK_LIMIT_BYTES",
    "V3_MANIFEST_LIMIT_BYTES",
    "V3_POINTER_LIMIT_BYTES",
    "CandidateBundle",
    "ConcurrencyError",
    "PromotionError",
    "RemoteNotFound",
    "asset_filename",
    "build_dates_index",
    "build_pointer",
    "complete_heads",
    "generation_coordinate",
    "load_candidate",
    "ordered_census",
    "release_url",
    "sha256",
    "strict_object",
    "validate_dates_index",
]
