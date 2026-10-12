"""Atomically expose verified app bytes without changing canonical identities."""
from __future__ import annotations

from pathlib import Path

from app_payload_optional_assets import iter_payload_assets
from app_payload_public_github import BRANCH, TAG, PublicGitHubStore, public_asset
from app_payload_revisions_github import write_once
from app_payload_revisions_state import (RevisionError, bundle_sha256, canonical,
                                        decode_document, digest, validate_index, validate_manifest)
from app_payload_secure_upload import validate_publication_contract

MODE = {"mode": "github-public-v1"}


def _selected(manifest, raw, index):
    head = index.get("revision_heads", {}).get(manifest["run_date"])
    revision = manifest.get("payload_revision", {})
    if (not head or head["manifest_sha256"] != digest(raw)
            or head["bundle_sha256"] != bundle_sha256(manifest)
            or head["revision"] != revision.get("revision")
            or revision.get("schema_version") != 1
            or head["bundle_sha256"] != revision.get("bundle_sha256")
            or head["generation_id"] != revision.get("generation_id")
            or head["manifest_url"] != f'https://github.com/{manifest["repo"]}/releases/download/{manifest["tag"]}/manifest.json'):
        raise RevisionError("Public data is not the exact selected canonical revision")


def _inventory(root, manifest, *, bootstrap=False):
    validate_manifest(manifest, root)
    if ((manifest.get("delivery") != MODE and not bootstrap) or manifest.get("enc")
            or not TAG.fullmatch(manifest.get("tag", ""))):
        raise RevisionError("Public data requires a readable direct-delivery immutable edition")
    files = {}
    for _, entry in iter_payload_assets(manifest):
        path = root / entry["name"]
        if not public_asset(path.name) or entry.get("enc") or path.is_symlink():
            raise RevisionError("Private or encrypted descriptor cannot enter public inventory")
        raw = path.read_bytes()
        if len(raw) != entry["bytes"] or digest(raw) != entry["sha256"] or not raw.startswith(b"\x1f\x8b"):
            raise RevisionError("Public asset differs from its readable gzip receipt")
        validate_publication_contract(path.name, raw)
        files[f'tags/{manifest["tag"]}/{path.name}'] = raw
    return files


def _monotonic(previous, incoming, repo):
    if previous is None:
        return
    old = decode_document(previous)
    validate_index(old, repo=repo)
    if not set(old["dates"]).issubset(incoming["dates"]):
        raise RevisionError("Public index cannot lose historical dates")
    for day, head in old.get("revision_heads", {}).items():
        new = incoming.get("revision_heads", {}).get(day)
        if not new or new["revision"] < head["revision"] or (new["revision"] == head["revision"] and new != head):
            raise RevisionError("Public index cannot regress or equivocate")


def publish_companion(archive: Path, canonical_store, state: Path, *, public_store=None, bootstrap=False):
    """Caller holds publication lock; one non-force ref update exposes all data.

    Historical index identities stay unchanged. Old encrypted releases are not
    rewritten; READY supplies historical observations without old core fetches.
    """
    raw = (archive / "manifest.json").read_bytes()
    manifest = decode_document(raw)
    files = _inventory(archive, manifest, bootstrap=bootstrap)
    index_raw = canonical_store.read("app-payload-latest", "dates-index.json", **({"require_encrypted": True} if bootstrap else {}))
    if index_raw is None:
        raise RevisionError("Canonical selection is missing before public mirroring")
    index = decode_document(index_raw)
    validate_index(index, repo=canonical_store.repo)
    _selected(manifest, raw, index)
    files[f'tags/{manifest["tag"]}/manifest.json'] = raw
    if bootstrap:
        # No regeneration, ARE1 migration, invented revision or local-only
        # source is eligible. The reader authenticates existing ARE2 transport.
        for path, expected in files.items():
            if canonical_store.read(manifest["tag"], path.rsplit("/", 1)[1], len(expected), require_encrypted=True) != expected:
                raise RevisionError("Bootstrap differs from authenticated published domain bytes")
    public = public_store or PublicGitHubStore(canonical_store.repo, gh=canonical_store.gh)
    head, tree, existing = public.snapshot()
    if "latest/dates-index.json" in existing:
        _monotonic(public.read(head, "latest/dates-index.json", 8 * 1024 * 1024), index, canonical_store.repo)
    latest_head = index["revision_heads"].get(index["latest_date"])
    if not latest_head:
        raise RevisionError("Selected latest public head is missing")
    latest_tag = f'app-payload-{index["latest_date"]}-r{latest_head["revision"]:06d}'
    latest_path = f"tags/{latest_tag}/manifest.json"
    if latest_path in files:
        latest_raw = files[latest_path]
    elif latest_path in existing:
        latest_raw = public.read(head, latest_path, 8 * 1024 * 1024)
    else:
        raise RevisionError("Publish the selected latest edition before historical public mirroring")
    _selected(decode_document(latest_raw), latest_raw, index)
    files.update({"latest/manifest.json": latest_raw, "latest/dates-index.json": index_raw})
    unchanged = True
    for path, expected in files.items():
        limit = 8 * 1024 * 1024 if path.startswith("latest/") else len(expected)
        observed = public.read(head, path, limit) if path in existing else None
        if observed != expected:
            unchanged = False
            if path.startswith("tags/") and observed is not None:
                raise RevisionError("Immutable public path collision")
    commit = head if unchanged else public.stage(head, tree, files)
    # Verify detached commit bytes before either mutable selector is visible.
    for path, expected in files.items():
        if public.read(commit, path, len(expected)) != expected:
            raise RevisionError("Staged public byte readback failed")
    if bootstrap and canonical_store.read("app-payload-latest", "dates-index.json", require_encrypted=True) != index_raw:
        raise RevisionError("Canonical selection changed during public bootstrap")
    if not unchanged:
        public.promote(head, commit)
    for name in ("manifest.json", "dates-index.json"):
        if public.read(BRANCH, f"latest/{name}", len(files[f"latest/{name}"])) != files[f"latest/{name}"]:
            raise RevisionError("Promoted public selector readback failed")
    write_once(state / f"{commit}.json", canonical({"schema_version": 1, "commit": commit,
        "manifest_sha256": digest(latest_raw), "dates_index_sha256": digest(index_raw), "status": "PASS"}))
