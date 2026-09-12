"""Immutable v2 evidence, independent of the v1 numbered revision identity.

The caller holds the production publication lock. Archives preserve the exact
selector bytes, all declared insights, and the v1 core/details base. No archive
is pruned. A separate receipt supplies archive URLs without rewriting sources.
"""
from __future__ import annotations

import gzip
import io
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from app_payload_contracts import (MAX_V2_ASSET_BYTES, MAX_V2_ASSET_UNCOMPRESSED_BYTES,
                                  MAX_V2_MANIFEST_BYTES, validate_v2_manifest)
from app_payload_revisions_github import GitHubRevisionStore, write_once
from app_payload_revisions_state import (MAX_DOCUMENT_BYTES, RevisionError, canonical,
                                        decode_document, digest, validate_date, validate_manifest)

MANIFEST = "manifest-v2.json"
BASE_MANIFEST = "base-manifest.json"
RECEIPT = "preservation.json"


def read_manifest(raw: bytes) -> dict:
    if len(raw) > MAX_V2_MANIFEST_BYTES:
        raise RevisionError("v2 manifest exceeds its byte budget")
    manifest = decode_document(raw)
    validate_v2_manifest(manifest)
    validate_date(manifest.get("run_date"))
    try:
        timestamp = datetime.fromisoformat(str(manifest["generated_at"]).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("timezone required")
    except (KeyError, ValueError) as exc:
        raise RevisionError("v2 manifest requires an aware generation timestamp") from exc
    names = {MANIFEST, BASE_MANIFEST, RECEIPT}
    for kind, entry in manifest["files"].items():
        name = entry["name"]
        if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name)
                or name in names or name in {".", ".."}
                or not re.fullmatch(r"[0-9a-f]{64}", str(entry["sha256"]))
                or type(entry["bytes"]) is not int or not 0 < entry["bytes"] <= MAX_V2_ASSET_BYTES[kind]
                or type(entry["uncompressed_bytes"]) is not int
                or not 0 < entry["uncompressed_bytes"] <= MAX_V2_ASSET_UNCOMPRESSED_BYTES[kind]
                or urlsplit(str(entry["url"])).path.rsplit("/", 1)[-1] != name):
            raise RevisionError("unsafe v2 asset descriptor")
        names.add(name)
    return manifest


def archive_tag(raw: bytes) -> str:
    manifest = read_manifest(raw)
    return f"app-payload-v2-{manifest['run_date']}-{digest(raw)}"


def is_archive_tag(tag: str) -> bool:
    return bool(re.fullmatch(r"app-payload-v2-\d{4}-\d{2}-\d{2}-[0-9a-f]{64}", tag))


def _checked(raw: bytes | None, entry: dict) -> bytes:
    if raw is None or len(raw) != entry["bytes"] or digest(raw) != entry["sha256"]:
        raise RevisionError(f"v2 preservation asset hash/size mismatch: {entry['name']}")
    return raw


def _insight_bytes(raw: bytes, kind: str, entry: dict) -> None:
    total = 0
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_V2_ASSET_UNCOMPRESSED_BYTES[kind]:
                raise RevisionError("v2 preservation asset expansion exceeds its budget")
    if total != entry["uncompressed_bytes"]:
        raise RevisionError("v2 preservation uncompressed size mismatch")


def _base(store, tag: str, source_tag: str, manifest: dict) -> tuple[bytes, dict]:
    # On retry v1 may already have advanced. Only the same hash-addressed
    # archive can supply the former base; never substitute the new v1 selector.
    raw = store.read(tag, BASE_MANIFEST, MAX_DOCUMENT_BYTES)
    if raw is None:
        raw = store.read(source_tag, "manifest.json", MAX_DOCUMENT_BYTES)
    if raw is None:
        raise RevisionError("v2 preservation has no matching v1 base manifest")
    base = decode_document(raw)
    validate_manifest(base)
    if any(base["files"][kind]["sha256"] != manifest["base"][f"{kind}_sha"]
           for kind in ("core", "details")):
        raise RevisionError("v2 preservation v1 base does not match")
    return raw, base


def archive_v2(raw: bytes, root: Path, *, store, source_tag: str,
               payload_dir: Path | None = None) -> str:
    manifest = read_manifest(raw)
    tag = archive_tag(raw)
    destination = root / tag
    base_raw, base = _base(store, tag, source_tag, manifest)
    paths, entries = [], {}
    for kind, entry in [*manifest["files"].items(),
                        *((f"base_{kind}", base["files"][kind]) for kind in ("core", "details"))]:
        name = entry["name"]
        if name in {MANIFEST, BASE_MANIFEST, RECEIPT} or name in entries:
            raise RevisionError("v2 preservation asset name collision")
        url = urlsplit(str(entry.get("url") or ""))
        if (url.scheme != "https" or url.netloc != "github.com" or url.query or url.fragment
                or not url.path.startswith(f"/{store.repo}/releases/download/")
                or url.path.rsplit("/", 1)[-1] != name):
            raise RevisionError("v2 preservation asset URL leaves its repository")
        if payload_dir is not None and kind in manifest["files"]:
            path = payload_dir / name
            if (path.is_symlink() or path.resolve().parent != payload_dir.resolve()
                    or path.stat().st_size != entry["bytes"]):
                raise RevisionError("incoming v2 asset size mismatch")
            content = path.read_bytes()
        else:
            content = store.read(tag, name, entry["bytes"])
            if content is None:
                content = store.read_url(entry["url"], entry["bytes"])
        content = _checked(content, entry)
        if kind in manifest["files"]:
            _insight_bytes(content, kind, entry)
        write_once(destination / name, content)
        paths.append(destination / name)
        entries[name] = {"kind": kind, "sha256": entry["sha256"], "bytes": entry["bytes"],
                         "source_url": entry["url"], "archive_url": store.url(tag, name)}
    write_once(destination / BASE_MANIFEST, base_raw)
    write_once(destination / MANIFEST, raw)
    write_once(destination / RECEIPT, canonical({
        "schema": "ar-local-v2-preservation-v1", "manifest_sha256": digest(raw),
        "base_manifest_sha256": digest(base_raw), "manifest_file": MANIFEST,
        "base_manifest_file": BASE_MANIFEST, "files": entries,
    }))
    # Receipt is uploaded last. The backend independently reads every exact file,
    # including on interrupted retries, and refuses immutable collisions.
    store.archive(tag, [*paths, destination / BASE_MANIFEST, destination / MANIFEST,
                        destination / RECEIPT])
    return tag


def preserve_current_v2(root: Path, *, repo: str, tag: str, gh: str | None = None,
                        store=None) -> bytes | None:
    backend = store or GitHubRevisionStore(repo, gh=gh)
    raw = backend.read(tag, MANIFEST, MAX_V2_MANIFEST_BYTES)
    if raw is not None:
        archive_v2(raw, root, store=backend, source_tag=tag)
    return raw
