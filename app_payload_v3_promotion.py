"""Dormant orchestration for transactional payload-v3 GitHub promotion."""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
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

from app_payload_v3_state import (
    CANONICAL_REPO,
    CANDIDATE_TAG_PREFIX,
    CONTROL_BRANCH,
    DATES_INDEX_FILENAME,
    LOCK_BRANCH,
    POINTER_FILENAME,
    V3_MANIFEST_LIMIT_BYTES,
    V3_POINTER_LIMIT_BYTES,
    CandidateBundle,
    CandidateReleaseRecord,
    ConcurrencyError,
    PromotionError,
    build_dates_index,
    build_pointer,
    complete_heads,
    generation_coordinate,
    load_candidate,
    ordered_census,
    release_url,
    require_candidate_artifact_binding,
    sha256,
    strict_object,
    validate_dates_index,
)


_MANIFEST_NAME = re.compile(r"^[0-9a-f]{64}\.json$")
_PRODUCER_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class PromotionResult:
    generation_id: str
    candidate_tag: str
    dry_run: bool
    index_commit: str | None = None
    pointer_commit: str | None = None
    pointer_changed: bool = False
    dates_index_changed: bool = False


class PromotionBackend(Protocol):
    def verify_candidate_run(self, run_id: str) -> str: ...

    def verify_candidate_artifact(
        self, run_id: str, candidate: CandidateBundle
    ) -> str: ...

    def acquire_lock(self, owner_token: str, target_commit: str) -> str: ...

    def renew_lock(self, owner_token: str) -> str: ...

    def release_lock(self, owner_token: str) -> str: ...

    def publish_candidate_release(
        self,
        tag: str,
        *,
        title: str,
        notes: str,
        target_commit: str,
        assets: Mapping[str, bytes],
        owner_token: str,
    ) -> None: ...

    def verify_candidate_release(
        self,
        tag: str,
        *,
        title: str,
        notes: str,
        target_commit: str,
    ) -> None: ...

    def verify_immutable_asset(self, tag: str, name: str, payload: bytes) -> None: ...

    def list_candidate_releases(self) -> Sequence[CandidateReleaseRecord]: ...

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
    if expected_manifest_sha256 and sha256(manifest_bytes) != expected_manifest_sha256:
        raise PromotionError("remote manifest SHA-256 does not match its pointer")
    manifest = strict_object(manifest_bytes, "remote generation manifest")
    validate_contract("generation-manifest-v3.schema.json", manifest)
    capabilities: dict[str, bytes] = {}
    for name, descriptor in manifest["capabilities"].items():
        validate_asset_descriptor(descriptor)
        maximum = int(descriptor["compressed_bytes"])
        payload = backend.fetch_url(str(descriptor["url"]), maximum)
        if len(payload) != maximum or sha256(payload) != descriptor["sha256"]:
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
    pointer = strict_object(payload, "rolling generation pointer")
    validate_contract("generation-pointer-v3.schema.json", pointer)
    manifests, capabilities = _pointer_resources(pointer, backend)
    validate_generation_pointer(pointer, manifests, capabilities)
    return pointer, manifests, capabilities


def _tag_generation(tag: str) -> str:
    if not tag.startswith(CANDIDATE_TAG_PREFIX):
        raise PromotionError("unexpected v3 candidate tag")
    generation_id = tag[len(CANDIDATE_TAG_PREFIX) :]
    generation_coordinate(generation_id)
    return generation_id


def _assert_coordinate_available(tags: Sequence[str], candidate: CandidateBundle) -> None:
    coordinate = generation_coordinate(candidate.generation_id)
    for tag in tags:
        generation_id = _tag_generation(tag)
        if generation_coordinate(generation_id) == coordinate and generation_id != candidate.generation_id:
            raise PromotionError(
                "another immutable generation already owns this date and revision"
            )


def _candidate_notes(candidate: CandidateBundle) -> str:
    return canonical_json_bytes(
        {
            "schema_version": 3,
            "generation_id": candidate.generation_id,
            "manifest_sha256": candidate.manifest_sha256,
        }
    ).decode("utf-8")


def _candidate_release_assets(
    candidate: CandidateBundle,
) -> tuple[dict[str, bytes], list[tuple[str, str, bytes]]]:
    candidate_assets = {candidate.manifest_filename: candidate.manifest_bytes}
    published_assets: list[tuple[str, str, bytes]] = []
    for capability, descriptor in candidate.manifest["capabilities"].items():
        parsed = urllib.parse.urlparse(str(descriptor["url"]))
        parts = PurePosixPath(parsed.path).parts
        try:
            tag = parts[parts.index("download") + 1]
        except (ValueError, IndexError) as error:
            raise PromotionError("capability URL has no release tag") from error
        name = f"{descriptor['sha256']}.json.gz"
        payload = candidate.capability_bytes[capability]
        if tag == candidate.candidate_tag:
            existing = candidate_assets.get(name)
            if existing is not None and existing != payload:
                raise PromotionError("candidate assets reuse a filename with different bytes")
            candidate_assets[name] = payload
        else:
            published_assets.append((tag, name, payload))
    return candidate_assets, published_assets


def _verified_census(
    backend: PromotionBackend,
    releases: Sequence[CandidateReleaseRecord],
    repo: str,
) -> tuple[CandidateBundle, ...]:
    candidates: list[CandidateBundle] = []
    tags = [release.tag for release in releases]
    if len(tags) != len(set(tags)):
        raise PromotionError("candidate census contains duplicate releases")
    for release in sorted(releases, key=lambda item: item.tag):
        tag = release.tag
        generation_id = _tag_generation(tag)
        asset_names = list(release.asset_names)
        if len(asset_names) != len(set(asset_names)):
            raise PromotionError(f"candidate release {tag} repeats an asset name")
        manifests = [name for name in asset_names if _MANIFEST_NAME.fullmatch(name)]
        if len(manifests) != 1:
            raise PromotionError(
                f"candidate release {tag} must contain its unique manifest"
            )
        manifest_name = manifests[0]
        bundle = _remote_bundle(
            backend, release_url(repo, tag, manifest_name), manifest_name[:-5]
        )
        expected_assets, _ = _candidate_release_assets(bundle)
        if set(asset_names) != set(expected_assets):
            raise PromotionError(
                f"candidate release {tag} has an unexpected immutable asset set"
            )
        if bundle.generation_id != generation_id:
            raise PromotionError("candidate tag and remote generation_id disagree")
        if (
            release.title != f"AR payload v3 candidate {generation_id}"
            or release.notes != _candidate_notes(bundle)
            or release.target_commit != str(bundle.manifest["producer_commit"])
            or release.draft
            or release.prerelease
        ):
            raise PromotionError(
                f"immutable release {tag} metadata or tag target differs"
            )
        candidates.append(bundle)
    return ordered_census(candidates)


def _prospective_census(
    backend: PromotionBackend,
    releases: Sequence[CandidateReleaseRecord],
    candidate: CandidateBundle,
    repo: str,
) -> tuple[CandidateBundle, ...]:
    drafts = [release for release in releases if release.draft]
    if any(release.tag != candidate.candidate_tag for release in drafts):
        raise PromotionError("candidate census contains an unrelated draft release")
    if len(drafts) > 1:
        raise PromotionError("candidate census contains ambiguous draft releases")
    if drafts:
        draft = drafts[0]
        expected_assets, _ = _candidate_release_assets(candidate)
        if (
            len(draft.asset_names) != len(set(draft.asset_names))
            or draft.title != f"AR payload v3 candidate {candidate.generation_id}"
            or draft.notes != _candidate_notes(candidate)
            or draft.target_commit != str(candidate.manifest["producer_commit"])
            or draft.prerelease
            or not set(draft.asset_names).issubset(expected_assets)
        ):
            raise PromotionError("invoked candidate draft is not an exact resumable draft")
    published = [release for release in releases if not release.draft]
    verified = _verified_census(backend, published, repo) if published else ()
    matching = [item for item in verified if item.candidate_tag == candidate.candidate_tag]
    if matching:
        if len(matching) != 1 or matching[0].manifest_bytes != candidate.manifest_bytes:
            raise PromotionError("published candidate differs from the local candidate")
        return verified
    return ordered_census((*verified, candidate))


def promote_candidate(
    directory: Path,
    backend: PromotionBackend | None = None,
    *,
    repo: str = CANONICAL_REPO,
    execute: bool = False,
    expected_producer_commit: str | None = None,
    candidate_run_id: str | None = None,
    generated_at: Callable[[], str] = _utc_now,
    failure_hook: Callable[[str], None] | None = None,
) -> PromotionResult:
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
    if execute and candidate_run_id is None:
        raise PromotionError("remote promotion requires a candidate run ID")
    if not execute:
        return PromotionResult(candidate.generation_id, candidate.candidate_tag, True)
    require_candidate_artifact_binding()
    from app_payload_v3_github import require_consumer_contract_parity
    require_consumer_contract_parity(contract_sha256())
    if backend is None:
        from app_payload_v3_github import GitHubPromotionBackend
        backend = GitHubPromotionBackend(repo)
    artifact_commit = backend.verify_candidate_artifact(
        candidate_run_id or "", candidate
    )
    if artifact_commit != expected_producer_commit:
        raise PromotionError(
            "verified candidate artifact differs from the expected producer commit"
        )
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
        releases_before = list(backend.list_candidate_releases())
        _assert_coordinate_available(
            [release.tag for release in releases_before], candidate
        )
        prospective_census = _prospective_census(
            backend, releases_before, candidate, repo
        )
        timestamp = generated_at()
        prospective_index_bytes = build_dates_index(
            complete_heads(prospective_census, repo),
            generated_at=timestamp,
            previous_bytes=previous_index_bytes,
        )
        prospective_pointer_bytes = build_pointer(
            prospective_census,
            generated_at=timestamp,
            previous_bytes=previous_pointer_bytes,
            previous_pointer=previous_pointer,
            previous_manifests=manifests,
            previous_capabilities=capabilities,
            repo=repo,
        )
        candidate_assets, published_assets = _candidate_release_assets(candidate)
        for tag, name, payload in published_assets:
            backend.verify_immutable_asset(tag, name, payload)
        hook("after_content_uploaded")
        backend.publish_candidate_release(
            candidate.candidate_tag,
            title=f"AR payload v3 candidate {candidate.generation_id}",
            notes=_candidate_notes(candidate),
            target_commit=str(candidate.manifest["producer_commit"]),
            assets=candidate_assets,
            owner_token=owner_token,
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
        releases = list(backend.list_candidate_releases())
        tags = [release.tag for release in releases]
        if candidate.candidate_tag not in tags:
            raise PromotionError("candidate listing omitted the newly verified release")
        _assert_coordinate_available(tags, candidate)
        census = _verified_census(backend, releases, repo)
        if not any(
            item.generation_id == candidate.generation_id
            and item.manifest_bytes == candidate.manifest_bytes
            for item in census
        ):
            raise PromotionError("verified census does not contain the local candidate")
        index_bytes = build_dates_index(
            complete_heads(census, repo),
            generated_at=timestamp,
            previous_bytes=previous_index_bytes,
        )
        pointer_bytes = build_pointer(
            census,
            generated_at=timestamp,
            previous_bytes=previous_pointer_bytes,
            previous_pointer=previous_pointer,
            previous_manifests=manifests,
            previous_capabilities=capabilities,
            repo=repo,
        )
        if (
            index_bytes != prospective_index_bytes
            or pointer_bytes != prospective_pointer_bytes
        ):
            raise ConcurrencyError(
                "verified candidate census changed after its prospective control preflight"
            )
        index_changed = index_bytes != previous_index_bytes
        pointer_changed = pointer_bytes != previous_pointer_bytes
        index_commit: str | None = None
        pointer_commit: str | None = None
        prepared_head = control_head
        if index_changed:
            backend.renew_lock(owner_token)
            index_commit = backend.prepare_control_commit(
                prepared_head,
                {DATES_INDEX_FILENAME: index_bytes},
                f"payload-v3 dates index for {candidate.generation_id}",
            )
            prepared_head = index_commit
            downloaded_index = backend.fetch_control_file(index_commit, DATES_INDEX_FILENAME)
            if downloaded_index != index_bytes:
                raise PromotionError("public complete dates index verification failed")
            validate_dates_index(
                strict_object(downloaded_index, "published complete dates index")
            )
        hook("after_index_written")
        if pointer_changed or index_changed:
            current_pointer = (
                backend.fetch_control_file(control_head, POINTER_FILENAME)
                if control_head
                else None
            )
            if current_pointer != previous_pointer_bytes:
                raise ConcurrencyError("rolling pointer changed before its CAS commit")
            hook("before_pointer_cas")
            backend.renew_lock(owner_token)
            pointer_commit = backend.prepare_control_commit(
                prepared_head,
                {POINTER_FILENAME: pointer_bytes},
                f"promote payload-v3 {candidate.generation_id}",
            )
            downloaded_pointer = backend.fetch_control_file(pointer_commit, POINTER_FILENAME)
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
            backend.renew_lock(owner_token)
            if backend.control_head() != control_head:
                raise ConcurrencyError("control branch changed during final lock renewal")
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
    parser = argparse.ArgumentParser(description="Validate or execute payload-v3 promotion.")
    parser.add_argument("--candidate-dir", required=True)
    parser.add_argument("--repo", default=CANONICAL_REPO)
    parser.add_argument(
        "--candidate-run-id",
        help="Canonical candidate-workflow run ID; required with --execute.",
    )
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


def _verified_execution_backend(
    repo: str,
    candidate_run_id: str | None,
    expected_producer_commit: str | None,
) -> PromotionBackend:
    if candidate_run_id is None or expected_producer_commit is None:
        raise PromotionError(
            "--execute requires a candidate run ID and expected producer commit"
        )
    from app_payload_v3_github import GitHubPromotionBackend

    require_candidate_artifact_binding()
    backend = GitHubPromotionBackend(repo)
    verified_commit = backend.verify_candidate_run(candidate_run_id)
    if verified_commit != expected_producer_commit:
        raise PromotionError(
            "verified candidate run differs from the expected producer commit"
        )
    return backend


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    backend = (
        _verified_execution_backend(
            args.repo,
            args.candidate_run_id,
            args.expected_producer_commit,
        )
        if args.execute
        else None
    )
    result = promote_candidate(
        Path(args.candidate_dir),
        backend,
        repo=args.repo,
        execute=args.execute,
        expected_producer_commit=args.expected_producer_commit,
        candidate_run_id=args.candidate_run_id,
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
    "_verified_execution_backend",
]
