"""Opt-in immutable v1 revisions; all current aliases remain backwards compatible.

The caller must hold the Pi production operation lock throughout this call and
the subsequent legacy alias writes. state_dir must be persistent across runtime
deployments, not an observation's disposable staging directory. A second local
crash-recoverable lock serializes revision reservations and GitHub promotion.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app_payload_common import DEFAULT_REPO, DEFAULT_TAG, HISTORY_MIN_DATE
from app_payload_revisions_github import (
    GitHubRevisionStore, download_manifest_assets, write_once,
)
from app_payload_revisions_state import (
    RevisionError, bundle_sha256, canonical, decode_document, digest,
    reserve_revision, revised_index, revision_delta, revision_tag,
    validate_index, validate_manifest,
)
from ar_local_operation_lock import production_lock


@dataclass(frozen=True)
class RevisionPublication:
    archive_dir: Path
    manifest: dict[str, Any]
    head: dict[str, Any]
    index_changed: bool


def revision_mode_enabled() -> bool:
    value = os.environ.get("AR_LOCAL_PAYLOAD_REVISIONS", "0")
    if value not in {"0", "1"}:
        raise RevisionError("AR_LOCAL_PAYLOAD_REVISIONS must be 0 or 1")
    return value == "1"


def _consumer_commit(value: str | None) -> str:
    commit = value or os.environ.get("AR_APP_REVISION_CONSUMER_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RevisionError("revision publication requires the verified shipped AR-app consumer commit")
    return commit


def _empty_index() -> dict[str, Any]:
    return {"schema_version": 1, "dates": [], "count": 0,
            "min_date": HISTORY_MIN_DATE, "latest_date": ""}


def _timestamp(manifest: dict[str, Any]) -> datetime:
    try:
        timestamp = datetime.fromisoformat(str(manifest["generated_at"]).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("timestamp requires a timezone")
        return timestamp
    except (KeyError, ValueError) as exc:
        raise RevisionError("manifest requires a valid generated_at timestamp") from exc


def _load_selected(
    store: Any, head: dict[str, Any], run_date: str, root: Path,
) -> tuple[Path, dict[str, Any]]:
    tag = revision_tag(run_date, head["revision"])
    if head["manifest_url"] != store.url(tag, "manifest.json"):
        raise RevisionError("selected manifest URL is not the expected immutable revision")
    raw = store.read_url(head["manifest_url"])
    if raw is None or digest(raw) != head["manifest_sha256"]:
        raise RevisionError("selected manifest hash verification failed")
    manifest = decode_document(raw)
    validate_manifest(manifest)
    identity = manifest.get("payload_revision", {})
    if (manifest["run_date"] != run_date or identity.get("schema_version") != 1
            or identity.get("revision") != head["revision"]
            or identity.get("generation_id") != head["generation_id"]
            or identity.get("bundle_sha256") != head["bundle_sha256"]
            or bundle_sha256(manifest) != head["bundle_sha256"]):
        raise RevisionError("selected manifest identity differs from its index head")
    if any(entry["url"] != store.url(tag, entry["name"])
           for entry in manifest["files"].values()):
        raise RevisionError("selected asset URL leaves its immutable revision")
    destination = root / "selected" / tag
    write_once(destination / "manifest.json", raw)
    download_manifest_assets(store, manifest, destination)
    return destination, manifest


def _preserve_alias(
    store: Any, alias: str, root: Path,
) -> tuple[Path, dict[str, Any]] | None:
    raw = store.read(alias, "manifest.json")
    if raw is None:
        return None
    original = decode_document(raw)
    validate_manifest(original)
    # Even a revision-aware alias is captured byte-for-byte. This protects an
    # interrupted migration where its source archive was never committed.
    archive_id = digest(alias.encode("utf-8") + b"\n" + raw)
    tag = f"app-payload-{original['run_date']}-legacy-{archive_id}"
    destination = root / "legacy" / tag
    write_once(destination / "source-manifest.json", raw)
    download_manifest_assets(store, original, destination)
    archived = {**original, "tag": tag, "files": {
        key: {**entry, "url": store.url(tag, entry["name"])}
        for key, entry in original["files"].items()
    }}
    write_once(destination / "manifest.json", canonical(archived))
    write_once(destination / "preservation.json", canonical({
        "schema_version": 1, "source_manifest_sha256": digest(raw),
        "source_tag": alias, "source_manifest_file": "source-manifest.json",
    }))
    paths = [destination / entry["name"] for entry in original["files"].values()]
    paths.extend([destination / "source-manifest.json", destination / "preservation.json",
                  destination / "manifest.json"])
    store.archive(tag, paths)
    return destination, original


def _prepare_archive(
    payload_dir: Path, manifest: dict[str, Any], destination: Path,
    reservation: dict[str, Any], store: Any,
) -> dict[str, Any]:
    tag = revision_tag(manifest["run_date"], reservation["revision"])
    identity = {key: reservation[key] for key in (
        "schema_version", "revision", "generation_id", "bundle_sha256", "parent_revision",
    )}
    archived = {**manifest, "tag": tag, "payload_revision": identity, "files": {
        key: {**entry, "url": store.url(tag, entry["name"])}
        for key, entry in manifest["files"].items()
    }}
    # Identical rebuilds may have a later generated_at. Keep the original exact
    # staged manifest bytes for the reserved bundle after any interruption.
    existing = destination / "manifest.json"
    if existing.exists():
        archived = decode_document(existing.read_bytes())
        if archived.get("payload_revision") != identity or bundle_sha256(archived) != reservation["bundle_sha256"]:
            raise RevisionError("reserved archive identity differs from staged bytes")
    for entry in manifest["files"].values():
        write_once(destination / entry["name"], (payload_dir / entry["name"]).read_bytes())
    write_once(existing, canonical(archived))
    return archived


def publish_revision_bundle(
    payload_dir: Path, *, state_dir: Path, repo: str = DEFAULT_REPO,
    consumer_commit: str | None = None, enabled: bool = False, store: Any = None,
) -> RevisionPublication:
    """Archive, independently verify, then advance one date's selected head.

Explicit ``enabled=True`` and a shipped consumer SHA are required. On success,
publish BOTH legacy dated/latest aliases from ``result.archive_dir`` while still
holding the outer production lock. Skip legacy dates-index regeneration: this
transaction has already preserved all prior dates and revision heads.
    """
    if not enabled:
        raise RevisionError("revision publication is disabled until consumer rollout")
    consumer = _consumer_commit(consumer_commit)
    manifest = decode_document((payload_dir / "manifest.json").read_bytes())
    validate_manifest(manifest, payload_dir)
    _timestamp(manifest)
    state_dir = state_dir.expanduser().resolve()
    backend = store or GitHubRevisionStore(repo)
    with production_lock(state_dir / ".revision-publication.lock", "payload-revisions"):
        return _publish_locked(payload_dir, manifest, state_dir, backend, consumer, repo)


def _publish_locked(
    payload_dir: Path, manifest: dict[str, Any], root: Path, store: Any, consumer: str, repo: str,
) -> RevisionPublication:
    run_date = manifest["run_date"]
    prior_raw = store.read(DEFAULT_TAG, "dates-index.json")
    if prior_raw is None:
        prior_raw = _recover_interrupted_index(root, store, repo=repo)
    index = decode_document(prior_raw) if prior_raw is not None else _empty_index()
    validate_index(index, repo=repo)
    head = index.get("revision_heads", {}).get(run_date)
    previous_root, previous = _load_selected(store, head, run_date, root) if head else (None, None)
    if head and head["bundle_sha256"] == bundle_sha256(manifest):
        write_once(previous_root / f"verified-{digest(prior_raw)}.json", canonical({
            "schema_version": 1, "head": head, "index_sha256": digest(prior_raw),
        }))
        return RevisionPublication(previous_root, previous, head, False)
    if previous and _timestamp(manifest) < _timestamp(previous):
        raise RevisionError("stale publisher: candidate predates the selected manifest")
    parent_revision = head["revision"] if head else None
    pattern = re.compile(rf"app-payload-{re.escape(run_date)}-r([0-9]{{6}})")
    tags = store.tags()
    if prior_raw is None and any(re.fullmatch(r"app-payload-\d{4}-\d{2}-\d{2}", tag)
                                 for tag in tags):
        raise RevisionError("missing dates-index with retained history; restore it before promotion")
    remote_max = max((int(match[1]) for tag in tags
                      if (match := pattern.fullmatch(tag))), default=0)
    destination, reservation = reserve_revision(root / "revisions", manifest,
                                               remote_max=remote_max,
                                               parent_revision=parent_revision)
    if reservation["parent_revision"] != parent_revision:
        raise RevisionError("stale publisher: reserved revision has a superseded parent")
    if head is None:
        dated_previous = _preserve_alias(store, f"app-payload-{run_date}", root)
        rolling_previous = _preserve_alias(store, DEFAULT_TAG, root)
        for preserved in (dated_previous, rolling_previous):
            if preserved and preserved[1]["run_date"] == run_date:
                previous_root, previous = preserved
    archived = _prepare_archive(payload_dir, manifest, destination, reservation, store)
    delta = revision_delta(destination, archived, previous_root, previous)
    write_once(destination / "revision-delta.json", canonical(delta))
    provenance_path = destination / "publication-provenance.json"
    if not provenance_path.exists():
        write_once(provenance_path, canonical({
            "schema_version": 1, "consumer_commit": consumer,
            "candidate_manifest_sha256": digest((payload_dir / "manifest.json").read_bytes()),
            "bundle_sha256": reservation["bundle_sha256"],
        }))
    paths = [destination / entry["name"] for entry in archived["files"].values()]
    paths.extend([destination / "revision-delta.json", destination / "publication-provenance.json",
                  destination / "manifest.json"])
    store.archive(archived["tag"], paths)
    new_head = {key: reservation[key] for key in ("revision", "generation_id", "bundle_sha256")}
    new_head.update(manifest_url=store.url(archived["tag"], "manifest.json"),
                    manifest_sha256=digest((destination / "manifest.json").read_bytes()))
    new_index = revised_index(index, run_date, new_head, repo=repo)
    index_bytes = canonical(new_index)
    promotion_root = destination / "promotions" / digest(index_bytes)
    index_path = promotion_root / "dates-index.json"
    write_once(index_path, index_bytes)
    if prior_raw is not None:
        write_once(promotion_root / "predecessor" / "dates-index.json", prior_raw)
    write_once(promotion_root / "promotion-intent.json", canonical({
        "schema_version": 1, "index_sha256": digest(index_bytes),
        "predecessor_index_sha256": digest(prior_raw) if prior_raw is not None else None,
    }))
    store.replace_index(DEFAULT_TAG, index_path, prior_raw)
    write_once(promotion_root / "promotion-receipt.json", canonical({
        "schema_version": 1, "head": new_head, "index_sha256": digest(index_path.read_bytes()),
        "predecessor_index_sha256": digest(prior_raw) if prior_raw is not None else None,
    }))
    return RevisionPublication(destination, archived, new_head, True)


def _recover_interrupted_index(root: Path, store: Any, *, repo: str = DEFAULT_REPO) -> bytes | None:
    """Recover a killed --clobber from its durable exact predecessor bytes.

    Single-writer publication is enforced by the outer operation lock. Only the
    newest prepared transaction can have removed the current index; the upload
    deliberately has no clobber flag so a newly appearing index wins safely.
    """
    intents = list((root / "revisions").glob("*/r*/promotions/*/promotion-intent.json"))
    if not intents:
        return None
    latest = max(intents, key=lambda path: path.stat().st_mtime_ns)
    intent = decode_document(latest.read_bytes())
    committed = (latest.parent / "promotion-receipt.json").exists()
    predecessor = (latest.parent / "dates-index.json" if committed else
                   latest.parent / "predecessor" / "dates-index.json")
    expected_hash = intent.get("index_sha256" if committed else "predecessor_index_sha256")
    if expected_hash is None:
        return None
    raw = predecessor.read_bytes()
    if digest(raw) != expected_hash:
        raise RevisionError("interrupted promotion predecessor hash mismatch")
    validate_index(decode_document(raw), repo=repo)
    store.restore_missing_index(DEFAULT_TAG, predecessor)
    return raw
