"""Encrypted retention of finalized daily payloads, without app promotion.

Callers verify the source completion/contract and hold the production lock. This
module never selects a revision, updates aliases/indexes, or queues Drive work.
The separate archive namespace cannot be discovered as a consumer dated tag.
"""
from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from app_payload_bank_history_asset import retag_namespace
from app_payload_build import _compute_payload, _package_payload
from app_payload_common import DEFAULT_REPO
from app_payload_optional_assets import iter_payload_assets
from app_payload_revisions_github import GitHubRevisionStore, write_once
from app_payload_revisions_state import (
    RevisionError, _asset_json, bundle_sha256, canonical, decode_document,
    digest, validate_manifest,
)
from ar_local_operation_lock import production_lock


@dataclass(frozen=True)
class ArchivePublication:
    archive_dir: Path
    manifest: dict[str, Any]
    tag: str
    manifest_url: str
    manifest_sha256: str


def _retention(source: Mapping[str, Any], coverage: Mapping[str, Any],
               run_date: str, promotion_reason: str) -> dict[str, Any]:
    if (source.get("observation_date") != run_date
            or source.get("observation_state") not in {"complete", "partial"}
            or not isinstance(source.get("generation_id"), str)
            or not source["generation_id"]
            or not re.fullmatch("[0-9a-f]{64}", str(source.get("contract_digest", "")))
            or not isinstance(coverage, Mapping) or not coverage
            or not isinstance(promotion_reason, str) or not promotion_reason):
        raise RevisionError("archive requires finalized source identity and truthful coverage")
    return {"schema_version": 1, "mode": "archive_only", "selected_for_app": False,
            "observation_state": source["observation_state"],
            "promotion_reason": promotion_reason, "contract_coverage": dict(coverage)}


def archive_payload_bundle(
    payload_dir: Path, *, state_dir: Path, contract_coverage: Mapping[str, Any],
    promotion_reason: str, repo: str = DEFAULT_REPO, store: Any = None,
) -> ArchivePublication:
    """Preserve a verified payload and independently read back every encrypted asset.

    Identical domain bundles have a deterministic tag. Local staging and remote
    manifest reuse preserve exact bytes after interruption or local state loss.
    ``promotion_reason`` reports the ordinary gate decision; it cannot waive it.
    """
    manifest = decode_document((payload_dir / "manifest.json").read_bytes())
    validate_manifest(manifest, payload_dir)
    for kind in ("core", "details"):
        _asset_json(payload_dir, manifest, kind)
    source = manifest.get("source_observation")
    if not isinstance(source, Mapping):
        raise RevisionError("archive requires source_observation")
    manifest["retention"] = _retention(source, contract_coverage,
                                       manifest["run_date"], promotion_reason)
    # A retained snapshot has no live ingest schedule or consumer revision head.
    manifest.pop("schedule", None)
    manifest.pop("payload_revision", None)
    manifest["repo"] = repo
    bundle = bundle_sha256(manifest)
    tag = f"app-payload-archive-{manifest['run_date']}-{bundle}"
    backend = store or GitHubRevisionStore(repo)
    root = state_dir.expanduser().resolve()
    with production_lock(root / ".archive-publication.lock", "payload-archive"):
        return _archive_locked(payload_dir, manifest, root / tag, backend, tag, bundle)


def _archive_locked(payload_dir: Path, manifest: dict[str, Any], destination: Path,
                    store: Any, tag: str, bundle: str) -> ArchivePublication:
    archived = {**manifest, "tag": tag, "files": {
        key: {**entry, "url": store.url(tag, entry["name"])}
        for key, entry in manifest["files"].items()}}
    retag_namespace(archived, url=lambda name: store.url(tag, name))
    target = destination / "manifest.json"
    retained = target.read_bytes() if target.exists() else store.read(
        tag, "manifest.json", require_encrypted=True)
    if retained is not None:
        archived = decode_document(retained)
        validate_manifest(archived)
        if (archived.get("tag") != tag or bundle_sha256(archived) != bundle
                or any(entry.get("url") != store.url(tag, entry["name"])
                       for _, entry in iter_payload_assets(archived))):
            raise RevisionError("immutable archive manifest differs from candidate")
    for _, entry in iter_payload_assets(manifest):
        write_once(destination / entry["name"], (payload_dir / entry["name"]).read_bytes())
    write_once(target, retained if retained is not None else canonical(archived))
    validate_manifest(archived, destination)
    paths = [destination / entry["name"] for _, entry in iter_payload_assets(archived)]
    paths.append(target)  # Commit marker is uploaded last.
    store.archive(tag, paths)
    # Recheck the complete set even for resumed uploads, with ARE2 required.
    for path in paths:
        expected = path.read_bytes()
        if store.read(tag, path.name, max(len(expected), 1), require_encrypted=True) != expected:
            raise RevisionError(f"encrypted archive readback failed: {path.name}")
    return ArchivePublication(destination, archived, tag, store.url(tag, "manifest.json"),
                              digest(target.read_bytes()))


def build_and_archive_payload(
    exports_dir: Path, *, state_dir: Path, contract_coverage: Mapping[str, Any],
    source_observation: Mapping[str, Any], promotion_reason: str,
    repo: str = DEFAULT_REPO, store: Any = None,
) -> ArchivePublication:
    """Build a dated core/details snapshot and retain it without any promotion.

    Source contract/ledger validation belongs to the caller, under its production
    lock. The ordinary app completeness policy does not control retention.
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="archive-build-", dir=state_dir) as temporary:
        output = Path(temporary)
        data = _compute_payload(exports_dir, contract_coverage=contract_coverage,
                                archive_snapshot=True, include_history=False)
        data["source_observation"] = dict(source_observation)
        _package_payload(data, output, repo=repo, tag="archive-staging")
        return archive_payload_bundle(output, state_dir=state_dir,
                                      contract_coverage=contract_coverage,
                                      promotion_reason=promotion_reason, repo=repo, store=store)
