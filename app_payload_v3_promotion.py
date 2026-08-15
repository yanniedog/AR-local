"""Dormant, append-only GitHub promotion for validated payload-v3 candidates.

Nothing imports this module from the daily producer.  The CLI is validation-only
unless ``--execute`` is supplied explicitly.  Remote writes use immutable release
assets plus non-force, parent-bound commits on dedicated control branches.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.parse
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

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
_PRODUCER_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class PromotionError(RuntimeError):
    """A fail-closed candidate or remote-state error."""


class ConcurrencyError(PromotionError):
    """The repository-wide owner token or expected branch head changed."""


class RemoteNotFound(PromotionError):
    """A required public object does not exist."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PromotionError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_json_constant(token: str) -> None:
    raise PromotionError(f"non-finite JSON number is forbidden: {token}")


def _strict_object(payload: bytes, label: str) -> dict[str, Any]:
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


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _generation_coordinate(generation_id: str) -> tuple[str, int]:
    match = _GENERATION.fullmatch(str(generation_id))
    if not match:
        raise PromotionError("candidate has an invalid generation_id")
    try:
        date.fromisoformat(match.group("date"))
    except ValueError as error:
        raise PromotionError("candidate generation_id has an invalid date") from error
    return match.group("date"), int(match.group("revision"))


def _release_url(repo: str, tag: str, filename: str) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}/{filename}"


def _asset_filename(descriptor: Mapping[str, Any]) -> str:
    validate_asset_descriptor(descriptor)
    parsed = urllib.parse.urlparse(str(descriptor["url"]))
    filename = PurePosixPath(parsed.path).name
    if filename != f"{descriptor['sha256']}.json.gz":
        raise PromotionError("capability URL filename is not its exact SHA-256")
    expected_url = _release_url(CANONICAL_REPO, CONTENT_RELEASE_TAG, filename)
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
        return _sha256(self.manifest_bytes)

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
            "manifest_url": _release_url(
                repo, self.candidate_tag, self.manifest_filename
            ),
        }


@dataclass(frozen=True)
class PromotionResult:
    generation_id: str
    candidate_tag: str
    dry_run: bool
    index_commit: str | None = None
    pointer_commit: str | None = None
    pointer_changed: bool = False
    dates_index_changed: bool = False


def _read_exact_file(path: Path, expected_bytes: int, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise PromotionError(f"{label} is not a regular file")
    if path.stat().st_size != expected_bytes:
        raise PromotionError(f"{label} byte count disagrees with its descriptor")
    return path.read_bytes()


def load_candidate(directory: Path) -> CandidateBundle:
    """Load and fully revalidate a create-once local candidate directory."""

    supplied = Path(directory)
    if supplied.is_symlink() or not supplied.is_dir():
        raise PromotionError("candidate directory must be a real directory")
    directory = supplied.resolve()
    entries = {entry.name: entry for entry in directory.iterdir()}
    manifest_names = [name for name in entries if _MANIFEST_NAME.fullmatch(name)]
    if len(manifest_names) != 1:
        raise PromotionError("candidate directory must contain exactly one manifest")
    manifest_path = entries[manifest_names[0]]
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise PromotionError("candidate manifest must be a regular file")
    if manifest_path.stat().st_size > V3_MANIFEST_LIMIT_BYTES:
        raise PromotionError("candidate manifest exceeds its byte limit")
    manifest_bytes = manifest_path.read_bytes()
    if manifest_path.name != f"{_sha256(manifest_bytes)}.json":
        raise PromotionError("candidate manifest filename does not match its exact bytes")
    manifest = _strict_object(manifest_bytes, "candidate manifest")
    validate_contract("generation-manifest-v3.schema.json", manifest)

    capability_bytes: dict[str, bytes] = {}
    expected_names = {manifest_path.name}
    for capability, descriptor in manifest["capabilities"].items():
        filename = _asset_filename(descriptor)
        expected_names.add(filename)
        try:
            path = entries[filename]
        except KeyError as error:
            raise PromotionError(f"candidate capability is missing: {capability}") from error
        payload = _read_exact_file(
            path, int(descriptor["compressed_bytes"]), f"candidate {capability}"
        )
        if _sha256(payload) != descriptor["sha256"]:
            raise PromotionError(f"candidate {capability} SHA-256 does not match")
        capability_bytes[capability] = payload
    if set(entries) != expected_names:
        raise PromotionError("candidate directory contains unexpected files")
    validate_generation_manifest(manifest, capability_bytes)
    if directory.name != manifest["generation_id"]:
        raise PromotionError("candidate directory name must equal generation_id")
    return CandidateBundle(directory, manifest, manifest_bytes, capability_bytes)


class PromotionBackend(Protocol):
    def acquire_lock(self, owner_token: str, target_commit: str) -> str: ...

    def release_lock(self, owner_token: str) -> str: ...

    def ensure_release(
        self,
        tag: str,
        *,
        title: str,
        notes: str,
        target_commit: str,
        exact_metadata: bool,
    ) -> None: ...

    def put_immutable_asset(self, tag: str, name: str, payload: bytes) -> None: ...

    def list_candidate_tags(self) -> Sequence[str]: ...

    def list_asset_names(self, tag: str) -> Sequence[str]: ...

    def fetch_url(self, url: str, max_bytes: int) -> bytes: ...

    def control_head(self) -> str | None: ...

    def fetch_control_file(self, commit: str, path: str) -> bytes | None: ...

    def prepare_control_commit(
        self,
        parent: str | None,
        files: Mapping[str, bytes],
        message: str,
    ) -> str: ...

    def install_control_head(
        self, expected_head: str | None, prepared_head: str
    ) -> None: ...


def _remote_bundle(
    backend: PromotionBackend,
    manifest_url: str,
    expected_manifest_sha256: str | None = None,
) -> CandidateBundle:
    manifest_bytes = backend.fetch_url(manifest_url, V3_MANIFEST_LIMIT_BYTES)
    if len(manifest_bytes) > V3_MANIFEST_LIMIT_BYTES:
        raise PromotionError("remote generation manifest exceeds its byte limit")
    if expected_manifest_sha256 and _sha256(manifest_bytes) != expected_manifest_sha256:
        raise PromotionError("remote manifest SHA-256 does not match its pointer")
    manifest = _strict_object(manifest_bytes, "remote generation manifest")
    validate_contract("generation-manifest-v3.schema.json", manifest)
    capabilities: dict[str, bytes] = {}
    for name, descriptor in manifest["capabilities"].items():
        validate_asset_descriptor(descriptor)
        maximum = int(descriptor["compressed_bytes"])
        payload = backend.fetch_url(str(descriptor["url"]), maximum)
        if len(payload) != maximum or _sha256(payload) != descriptor["sha256"]:
            raise PromotionError(f"remote {name} bytes disagree with their descriptor")
        capabilities[name] = payload
    validate_generation_manifest(manifest, capabilities)
    return CandidateBundle(Path(manifest["generation_id"]), manifest, manifest_bytes, capabilities)


def _pointer_resources(
    pointer: Mapping[str, Any], backend: PromotionBackend
) -> tuple[dict[str, bytes], dict[str, Mapping[str, bytes]]]:
    manifests: dict[str, bytes] = {}
    capabilities: dict[str, Mapping[str, bytes]] = {}
    for head in (pointer["latest_observation"], pointer["latest_complete"]):
        generation_id = str(head["generation_id"])
        if generation_id in manifests:
            continue
        bundle = _remote_bundle(
            backend, str(head["manifest_url"]), str(head["manifest_sha256"])
        )
        if bundle.generation_id != generation_id:
            raise PromotionError("remote pointer head resolves to another generation")
        manifests[generation_id] = bundle.manifest_bytes
        capabilities[generation_id] = bundle.capability_bytes
    return manifests, capabilities


def load_pointer(
    payload: bytes | None, backend: PromotionBackend
) -> tuple[dict[str, Any] | None, dict[str, bytes], dict[str, Mapping[str, bytes]]]:
    if payload is None:
        return None, {}, {}
    if len(payload) > V3_POINTER_LIMIT_BYTES:
        raise PromotionError("rolling pointer exceeds its byte limit")
    pointer = _strict_object(payload, "rolling generation pointer")
    validate_contract("generation-pointer-v3.schema.json", pointer)
    manifests, capabilities = _pointer_resources(pointer, backend)
    validate_generation_pointer(pointer, manifests, capabilities)
    return pointer, manifests, capabilities


def _same_coordinate(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return (
        left["observation_date"], left["generation_revision"]
    ) == (right["observation_date"], right["generation_revision"])


def build_pointer(
    candidate: CandidateBundle,
    *,
    generated_at: str,
    previous_bytes: bytes | None,
    previous_pointer: Mapping[str, Any] | None,
    previous_manifests: Mapping[str, bytes],
    previous_capabilities: Mapping[str, Mapping[str, bytes]],
    repo: str = CANONICAL_REPO,
) -> bytes:
    """Build a monotonic pointer transition; return prior bytes for a no-op."""

    head = candidate.head(repo)
    if previous_pointer is None:
        if head["observation_state"] != "complete":
            raise PromotionError("the first v3 pointer requires a complete generation")
        observation = complete = head
    else:
        old_observation = dict(previous_pointer["latest_observation"])
        old_complete = dict(previous_pointer["latest_complete"])
        for old in (old_observation, old_complete):
            if _same_coordinate(old, head) and old != head:
                raise PromotionError(
                    "same-date generation revision is already bound to immutable bytes"
                )
        coordinate = _generation_coordinate(candidate.generation_id)
        observation = (
            head
            if coordinate > _generation_coordinate(old_observation["generation_id"])
            else old_observation
        )
        complete = old_complete
        if head["observation_state"] == "complete" and coordinate > _generation_coordinate(
            old_complete["generation_id"]
        ):
            complete = head
        if observation == old_observation and complete == old_complete:
            return previous_bytes or b""

    pointer = {
        "schema_version": 3,
        "generated_at": generated_at,
        "contract_sha256": contract_sha256(),
        "latest_observation": observation,
        "latest_complete": complete,
    }
    encoded = canonical_json_bytes(pointer)
    manifests = dict(previous_manifests)
    capabilities = dict(previous_capabilities)
    manifests[candidate.generation_id] = candidate.manifest_bytes
    capabilities[candidate.generation_id] = candidate.capability_bytes
    kwargs: dict[str, Any] = {}
    if previous_bytes is not None:
        kwargs = {
            "previous_pointer_bytes": previous_bytes,
            "expected_previous_pointer_sha256": _sha256(previous_bytes),
        }
    validate_generation_pointer(pointer, manifests, capabilities, **kwargs)
    return encoded


def _validate_dates_index(value: Mapping[str, Any]) -> None:
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
        coordinate = _generation_coordinate(generation_id)
        if coordinate != (observation_date, revision):
            raise PromotionError("complete dates index coordinate does not reconcile")
        if not _SHA256.fullmatch(generation_digest) or not generation_digest.startswith(
            generation_id.rsplit("-", 1)[1]
        ):
            raise PromotionError("complete dates index generation digest is invalid")
        if not _SHA256.fullmatch(manifest_sha256):
            raise PromotionError("complete dates index manifest hash is invalid")
        expected_url = _release_url(
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
    _validate_dates_index(value)
    if previous_bytes is not None:
        if len(previous_bytes) > V3_DATES_INDEX_LIMIT_BYTES:
            raise PromotionError("prior complete dates index exceeds its byte limit")
        previous = _strict_object(previous_bytes, "prior complete dates index")
        _validate_dates_index(previous)
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


def _tag_generation(tag: str) -> str:
    if not tag.startswith(CANDIDATE_TAG_PREFIX):
        raise PromotionError("unexpected v3 candidate tag")
    generation_id = tag[len(CANDIDATE_TAG_PREFIX) :]
    _generation_coordinate(generation_id)
    return generation_id


def _assert_coordinate_available(tags: Sequence[str], candidate: CandidateBundle) -> None:
    coordinate = _generation_coordinate(candidate.generation_id)
    for tag in tags:
        generation_id = _tag_generation(tag)
        if (
            _generation_coordinate(generation_id) == coordinate
            and generation_id != candidate.generation_id
        ):
            raise PromotionError(
                "another immutable generation already owns this date and revision"
            )


def _verified_complete_heads(
    backend: PromotionBackend, tags: Sequence[str], repo: str
) -> list[dict[str, Any]]:
    coordinates: dict[tuple[str, int], str] = {}
    latest_by_date: dict[str, dict[str, Any]] = {}
    for tag in sorted(set(tags)):
        generation_id = _tag_generation(tag)
        asset_names = list(backend.list_asset_names(tag))
        manifests = [name for name in asset_names if _MANIFEST_NAME.fullmatch(name)]
        if len(manifests) != 1 or asset_names != manifests:
            raise PromotionError(
                f"candidate release {tag} must contain only its unique manifest"
            )
        manifest_name = manifests[0]
        url = _release_url(repo, tag, manifest_name)
        bundle = _remote_bundle(backend, url, manifest_name[:-5])
        if bundle.generation_id != generation_id:
            raise PromotionError("candidate tag and remote generation_id disagree")
        coordinate = _generation_coordinate(generation_id)
        prior = coordinates.setdefault(coordinate, generation_id)
        if prior != generation_id:
            raise PromotionError("multiple generations occupy one date/revision coordinate")
        if bundle.manifest["observation_state"] != "complete":
            continue
        head = bundle.head(repo)
        existing = latest_by_date.get(str(head["observation_date"]))
        if existing is None or head["generation_revision"] > existing["generation_revision"]:
            latest_by_date[str(head["observation_date"])] = head
    return [latest_by_date[key] for key in sorted(latest_by_date)]


def _candidate_notes(candidate: CandidateBundle) -> str:
    return canonical_json_bytes(
        {
            "schema_version": 3,
            "generation_id": candidate.generation_id,
            "manifest_sha256": candidate.manifest_sha256,
        }
    ).decode("utf-8")


def promote_candidate(
    directory: Path,
    backend: PromotionBackend | None = None,
    *,
    repo: str = CANONICAL_REPO,
    execute: bool = False,
    expected_producer_commit: str | None = None,
    generated_at: Callable[[], str] = _utc_now,
    failure_hook: Callable[[str], None] | None = None,
) -> PromotionResult:
    """Validate or transactionally promote one candidate with the pointer last."""

    if repo != CANONICAL_REPO:
        raise PromotionError("v3 contracts are locked to yanniedog/AR-local")
    candidate = load_candidate(directory)
    if expected_producer_commit is not None:
        if not _PRODUCER_COMMIT.fullmatch(expected_producer_commit):
            raise PromotionError("expected producer commit must be exactly 40 lowercase hex")
        if candidate.manifest["producer_commit"] != expected_producer_commit:
            raise PromotionError(
                "candidate producer_commit differs from its trusted Actions run"
            )
    elif execute:
        raise PromotionError("remote promotion requires a trusted producer commit")
    if not execute:
        return PromotionResult(candidate.generation_id, candidate.candidate_tag, True)
    if backend is None:
        from app_payload_v3_github import GitHubPromotionBackend

        backend = GitHubPromotionBackend(repo)
    hook = failure_hook or (lambda _stage: None)
    owner_token = uuid.uuid4().hex
    backend.acquire_lock(owner_token, str(candidate.manifest["producer_commit"]))
    try:
        hook("after_lock_acquired")
        control_head = backend.control_head()
        previous_pointer_bytes = (
            backend.fetch_control_file(control_head, POINTER_FILENAME)
            if control_head
            else None
        )
        previous_index_bytes = (
            backend.fetch_control_file(control_head, DATES_INDEX_FILENAME)
            if control_head
            else None
        )
        previous_pointer, manifests, capabilities = load_pointer(
            previous_pointer_bytes, backend
        )
        tags_before = list(backend.list_candidate_tags())
        _assert_coordinate_available(tags_before, candidate)

        for capability, descriptor in candidate.manifest["capabilities"].items():
            parsed = urllib.parse.urlparse(str(descriptor["url"]))
            parts = PurePosixPath(parsed.path).parts
            try:
                release_index = parts.index("download") + 1
                tag = parts[release_index]
            except (ValueError, IndexError) as error:
                raise PromotionError("capability URL has no release tag") from error
            backend.ensure_release(
                tag,
                title="AR payload v3 content-addressed assets",
                notes="Append-only content-addressed payload-v3 capability assets.",
                target_commit=str(candidate.manifest["producer_commit"]),
                exact_metadata=False,
            )
            backend.put_immutable_asset(
                tag, _asset_filename(descriptor), candidate.capability_bytes[capability]
            )
        hook("after_content_uploaded")

        backend.ensure_release(
            candidate.candidate_tag,
            title=f"AR payload v3 candidate {candidate.generation_id}",
            notes=_candidate_notes(candidate),
            target_commit=str(candidate.manifest["producer_commit"]),
            exact_metadata=True,
        )
        backend.put_immutable_asset(
            candidate.candidate_tag,
            candidate.manifest_filename,
            candidate.manifest_bytes,
        )
        hook("after_candidate_uploaded")
        remote_candidate = _remote_bundle(
            backend,
            candidate.head(repo)["manifest_url"],
            candidate.manifest_sha256,
        )
        if remote_candidate.manifest_bytes != candidate.manifest_bytes:
            raise PromotionError("public candidate manifest differs from local bytes")
        hook("after_candidate_verified")

        tags = list(backend.list_candidate_tags())
        if candidate.candidate_tag not in tags:
            raise PromotionError("candidate listing omitted the newly verified release")
        _assert_coordinate_available(tags, candidate)
        complete_heads = _verified_complete_heads(backend, tags, repo)
        timestamp = generated_at()
        index_bytes = build_dates_index(
            complete_heads,
            generated_at=timestamp,
            previous_bytes=previous_index_bytes,
        )
        pointer_bytes = build_pointer(
            candidate,
            generated_at=timestamp,
            previous_bytes=previous_pointer_bytes,
            previous_pointer=previous_pointer,
            previous_manifests=manifests,
            previous_capabilities=capabilities,
            repo=repo,
        )

        index_changed = index_bytes != previous_index_bytes
        pointer_changed = pointer_bytes != previous_pointer_bytes
        index_commit: str | None = None
        pointer_commit: str | None = None
        prepared_head = control_head
        if index_changed:
            index_commit = backend.prepare_control_commit(
                prepared_head,
                {DATES_INDEX_FILENAME: index_bytes},
                f"payload-v3 dates index for {candidate.generation_id}",
            )
            prepared_head = index_commit
            downloaded_index = backend.fetch_control_file(
                index_commit, DATES_INDEX_FILENAME
            )
            if downloaded_index != index_bytes:
                raise PromotionError("public complete dates index verification failed")
            _validate_dates_index(
                _strict_object(downloaded_index, "published complete dates index")
            )
        hook("after_index_written")

        # When the index changes, re-commit even an unchanged pointer after it.
        # Both commits remain unreferenced until one final control-ref CAS, so a
        # backend failure before that CAS cannot expose a half-published index.
        if pointer_changed or index_changed:
            current_pointer = (
                backend.fetch_control_file(control_head, POINTER_FILENAME)
                if control_head
                else None
            )
            if current_pointer != previous_pointer_bytes:
                raise ConcurrencyError("rolling pointer changed before its CAS commit")
            hook("before_pointer_cas")
            pointer_commit = backend.prepare_control_commit(
                prepared_head,
                {POINTER_FILENAME: pointer_bytes},
                f"promote payload-v3 {candidate.generation_id}",
            )
            downloaded_pointer = backend.fetch_control_file(
                pointer_commit, POINTER_FILENAME
            )
            if downloaded_pointer != pointer_bytes:
                raise PromotionError("public rolling pointer verification failed")
            published, published_manifests, published_capabilities = load_pointer(
                downloaded_pointer, backend
            )
            if published is None:
                raise PromotionError("published rolling pointer is absent")
            validate_generation_pointer(
                published, published_manifests, published_capabilities
            )
            if backend.control_head() != control_head:
                raise ConcurrencyError("control branch changed before its final CAS")
            backend.install_control_head(control_head, pointer_commit)
            if backend.control_head() != pointer_commit:
                raise ConcurrencyError("control branch did not install the prepared head")
            hook("after_pointer_written")
        return PromotionResult(
            candidate.generation_id,
            candidate.candidate_tag,
            False,
            index_commit=index_commit,
            pointer_commit=pointer_commit,
            pointer_changed=pointer_changed,
            dates_index_changed=index_changed,
        )
    finally:
        backend.release_lock(owner_token)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate or explicitly execute dormant payload-v3 promotion."
    )
    parser.add_argument("--candidate-dir", required=True)
    parser.add_argument("--repo", default=CANONICAL_REPO)
    parser.add_argument(
        "--expected-producer-commit",
        help="Exact trusted candidate-workflow head SHA; required with --execute.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Perform remote writes. Omit for the safe validation-only default.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = promote_candidate(
        Path(args.candidate_dir),
        repo=args.repo,
        execute=args.execute,
        expected_producer_commit=args.expected_producer_commit,
    )
    print(json.dumps(result.__dict__, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CANONICAL_REPO",
    "CANDIDATE_TAG_PREFIX",
    "CONTROL_BRANCH",
    "DATES_INDEX_FILENAME",
    "LOCK_BRANCH",
    "POINTER_FILENAME",
    "CandidateBundle",
    "ConcurrencyError",
    "PromotionError",
    "PromotionResult",
    "build_dates_index",
    "build_pointer",
    "load_candidate",
    "load_pointer",
    "promote_candidate",
]
