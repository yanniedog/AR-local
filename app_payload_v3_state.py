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


@dataclass(frozen=True)
class CandidateReleaseRecord:
    """One candidate release and its direct Git tag provenance from one census."""

    tag: str
    title: str
    notes: str
    target_commit: str
    draft: bool
    prerelease: bool
    asset_names: tuple[str, ...]


def validate_candidate_release_identity(
    release: Mapping[str, Any],
    tag: str,
    *,
    title: str,
    notes: str,
    target_commit: str,
    direct_tag_target: str | None,
) -> None:
    body = release.get("body")
    if (
        release.get("tag_name") != tag
        or not isinstance(release.get("name"), str)
        or release.get("name") != title
        or not isinstance(body, (str, type(None)))
        or (body or "") != notes
        or release.get("prerelease") is not False
    ):
        raise PromotionError(f"candidate release {tag} metadata differs")
    if release.get("draft") is True:
        if (
            release.get("target_commitish") != target_commit
            or direct_tag_target not in {None, target_commit}
        ):
            raise PromotionError(f"candidate draft {tag} targets another commit")
    elif release.get("draft") is not False or direct_tag_target != target_commit:
        raise PromotionError(f"immutable release {tag} targets another commit")


def release_asset_records(
    release: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    assets = release.get("assets")
    if not isinstance(assets, list) or any(not isinstance(item, Mapping) for item in assets):
        raise PromotionError("candidate release asset metadata is malformed")
    names = [item.get("name") for item in assets]
    if any(not isinstance(name, str) or not name for name in names):
        raise PromotionError("candidate release asset names are malformed")
    records = {str(name): item for name, item in zip(names, assets)}
    if len(records) != len(assets):
        raise PromotionError("candidate release asset names are duplicated")
    return records


def validate_candidate_draft_assets(
    release: Mapping[str, Any], assets: Mapping[str, bytes]
) -> tuple[str, ...]:
    records = release_asset_records(release)
    if not set(records).issubset(assets):
        raise PromotionError("candidate draft contains unexpected assets")
    for name, record in records.items():
        payload = assets[name]
        expected_digest = f"sha256:{sha256(payload)}"
        size = record.get("size")
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size != len(payload)
            or record.get("digest") != expected_digest
        ):
            raise PromotionError(f"candidate draft asset differs: {name}")
    return tuple(sorted(set(assets) - set(records)))


@dataclass(frozen=True)
class CandidateArtifactBindingContract:
    """Reviewed future contract required to bind a run archive to its tree."""

    workflow_path: str
    artifact_name: str
    archive_digest_algorithm: str
    inventory_contract_sha256: str


# A future slice must implement archive-digest verification and an exact
# archive-to-expanded-tree inventory before setting this reviewed contract.
# Merely assigning a value cannot enable execution: the verifier below remains
# fail-closed until that implementation replaces its explicit final rejection.
CANDIDATE_ARTIFACT_BINDING_CONTRACT: CandidateArtifactBindingContract | None = None


def require_candidate_artifact_binding() -> None:
    if CANDIDATE_ARTIFACT_BINDING_CONTRACT is None:
        raise PromotionError(
            "candidate artifact-byte provenance is not locked; execution is blocked"
        )
    raise PromotionError(
        "candidate artifact archive-to-tree verification is not implemented"
    )


@dataclass(frozen=True)
class CandidatePublicationStoreContract:
    """Reviewed future binding to an immutable or atomic v3 publication store."""

    repository: str
    strategy: str
    verification_contract_sha256: str


# AR-local's release immutability cannot be enabled while mutable v1 releases
# remain supported. A future slice must implement and verify a separate immutable
# v3 store or a Git content-addressed publication design before setting this.
CANDIDATE_PUBLICATION_STORE_CONTRACT: CandidatePublicationStoreContract | None = None


def require_candidate_publication_store() -> None:
    if CANDIDATE_PUBLICATION_STORE_CONTRACT is None:
        raise PromotionError(
            "candidate publication store is not locked; execution is blocked"
        )
    raise PromotionError(
        "candidate publication store verification is not implemented"
    )


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
    suffix = ".json.gz" if descriptor["encoding"] == "gzip" else ".json"
    if filename != f"{descriptor['sha256']}{suffix}":
        raise PromotionError("capability URL filename is not its exact SHA-256")
    expected_url = release_url(CANONICAL_REPO, CONTENT_RELEASE_TAG, filename)
    if str(descriptor["url"]) != expected_url:
        raise PromotionError("capability URL is outside the v3 content release")
    return filename


def validate_manifest_head_url(
    head: Mapping[str, Any], repo: str = CANONICAL_REPO
) -> str:
    expected = release_url(
        repo,
        CANDIDATE_TAG_PREFIX + str(head["generation_id"]),
        f"{head['manifest_sha256']}.json",
    )
    if head.get("manifest_url") != expected:
        raise PromotionError(
            "generation head manifest URL is not hash-bound to its candidate"
        )
    return expected


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
    by_event: dict[str, CandidateBundle] = {}
    for candidate in candidates:
        event_digest = str(candidate.manifest["ledger_event_digest"])
        if event_digest in by_event:
            raise PromotionError("candidate census reuses a ledger event digest")
        by_event[event_digest] = candidate
    roots: list[CandidateBundle] = []
    child_by_parent: dict[str, CandidateBundle] = {}
    for candidate in candidates:
        prior = candidate.manifest["prior_ledger_digest"]
        if prior is None:
            roots.append(candidate)
            continue
        if prior not in by_event:
            raise PromotionError("candidate census contains disconnected ledger lineage")
        if prior in child_by_parent:
            raise PromotionError("candidate census branches its ledger lineage")
        child_by_parent[prior] = candidate
    if len(roots) != 1:
        raise PromotionError(
            "candidate census contains disconnected ledger lineage: expected one null root"
        )
    ordered: list[CandidateBundle] = []
    current: CandidateBundle | None = roots[0]
    while current is not None:
        ordered.append(current)
        current = child_by_parent.get(str(current.manifest["ledger_event_digest"]))
    if len(ordered) != len(candidates):
        raise PromotionError("candidate census contains disconnected or cyclic lineage")
    return tuple(ordered)


def complete_heads(census: Sequence[CandidateBundle], repo: str) -> list[dict[str, Any]]:
    latest: dict[str, CandidateBundle] = {}
    for candidate in ordered_census(census):
        if candidate.manifest["observation_state"] != "complete":
            continue
        day = str(candidate.manifest["observation_date"])
        current = latest.get(day)
        if current is None or (
            generation_coordinate(candidate.generation_id)[1]
            > generation_coordinate(current.generation_id)[1]
        ):
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
    observation_head = max(
        ordered, key=lambda item: generation_coordinate(item.generation_id)
    ).head(repo)
    complete_head = max(
        complete, key=lambda item: generation_coordinate(item.generation_id)
    ).head(repo)
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
        validate_manifest_head_url(entry)
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
    "CANDIDATE_PUBLICATION_STORE_CONTRACT",
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
    "CANDIDATE_ARTIFACT_BINDING_CONTRACT",
    "CandidateArtifactBindingContract",
    "CandidateReleaseRecord",
    "CandidateBundle",
    "CandidatePublicationStoreContract",
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
    "release_asset_records",
    "release_url",
    "require_candidate_artifact_binding",
    "require_candidate_publication_store",
    "sha256",
    "strict_object",
    "validate_candidate_release_identity",
    "validate_candidate_draft_assets",
    "validate_dates_index",
    "validate_manifest_head_url",
]
