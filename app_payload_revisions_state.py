"""Durable, additive v1 revision identities and audit differences.

Bundle identity is SHA-256 of canonical UTF-8 JSON: sorted keys, compact
separators, non-ASCII preserved, no NaN. It includes every manifest field except
generated_at, tag, payload_revision, and files; files include every descriptor
field except url. Thus timestamp/alias-only rebuilds are idempotent while details,
optional assets, producer/observation provenance and coverage changes are not.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from ar_local_backup_policy import atomic_create_json

MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
MAX_ASSET_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 256 * 1024 * 1024
HASH_RE = re.compile(r"[0-9a-f]{64}")
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,240}")


class RevisionError(RuntimeError):
    """Publication cannot safely commit the selected revision."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def decode_document(raw: bytes) -> dict[str, Any]:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise RevisionError(f"duplicate document field: {key}")
            result[key] = value
        return result

    if len(raw) > MAX_DOCUMENT_BYTES:
        raise RevisionError("document exceeds its byte budget")
    value = json.loads(raw, object_pairs_hook=unique_pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(
                           RevisionError("non-finite JSON number")))
    if not isinstance(value, dict):
        raise RevisionError("expected a JSON object")
    return value


def validate_date(value: Any) -> str:
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise RevisionError("invalid run_date")
    return value


def revision_tag(run_date: str, revision: int) -> str:
    validate_date(run_date)
    if type(revision) is not int or not 1 <= revision <= 999999:
        raise RevisionError("revision is outside the supported range")
    return f"app-payload-{run_date}-r{revision:06d}"


def validate_manifest(manifest: dict[str, Any], root: Path | None = None) -> None:
    if manifest.get("schema_version") != 1:
        raise RevisionError("revision protocol requires a v1 manifest")
    validate_date(manifest.get("run_date"))
    files = manifest.get("files")
    if not isinstance(files, dict) or not {"core", "details"}.issubset(files):
        raise RevisionError("manifest must describe core and details")
    names: set[str] = set()
    for entry in files.values():
        if not isinstance(entry, dict):
            raise RevisionError("invalid asset descriptor")
        name = entry.get("name", "")
        size = entry.get("bytes")
        if (not isinstance(name, str) or not NAME_RE.fullmatch(name)
                or name in names or name in {
                    "manifest.json", "revision-delta.json", "source-manifest.json",
                    "preservation.json", "publication-provenance.json", "reservation.json",
                }
                or not HASH_RE.fullmatch(str(entry.get("sha256", "")))
                or type(size) is not int or not 0 < size <= MAX_ASSET_BYTES):
            raise RevisionError("unsafe asset name, duplicate, hash or byte count")
        names.add(name)
        if root is not None:
            path = root / name
            if path.is_symlink() or path.resolve().parent != root.resolve():
                raise RevisionError("asset path escapes the payload directory")
            if path.stat().st_size != size or digest(path.read_bytes()) != entry["sha256"]:
                raise RevisionError(f"asset does not match its descriptor: {name}")


def bundle_sha256(manifest: dict[str, Any]) -> str:
    validate_manifest(manifest)
    value = {key: val for key, val in manifest.items()
             if key not in {"generated_at", "tag", "payload_revision", "files"}}
    value["files"] = {key: {k: v for k, v in entry.items() if k != "url"}
                      for key, entry in manifest["files"].items()}
    return digest(canonical(value))


def reserve_revision(
    root: Path, manifest: dict[str, Any], *, remote_max: int,
    parent_revision: int | None,
) -> tuple[Path, dict[str, Any]]:
    """Caller holds the revision lock; reservations survive interruption forever."""
    run_date = validate_date(manifest["run_date"])
    bundle = bundle_sha256(manifest)
    day_root = root / run_date
    day_root.mkdir(parents=True, exist_ok=True)
    largest = remote_max
    for path in sorted(day_root.glob("r*/reservation.json")):
        existing = decode_document(path.read_bytes())
        largest = max(largest, int(existing["revision"]))
        if (existing["bundle_sha256"] == bundle
                and existing["parent_revision"] == parent_revision):
            return path.parent, existing
    reservation = {
        "schema_version": 1, "revision": largest + 1,
        "generation_id": "sha256-" + bundle, "bundle_sha256": bundle,
        "parent_revision": parent_revision, "run_date": run_date,
    }
    revision_tag(run_date, reservation["revision"])
    destination = day_root / f"r{reservation['revision']:06d}"
    destination.mkdir(exist_ok=True)
    atomic_create_json(destination / "reservation.json", reservation)
    return destination, reservation


def validate_index(value: dict[str, Any]) -> None:
    if value.get("schema_version") != 1:
        raise RevisionError("revision protocol requires a v1 dates index")
    dates = value.get("dates")
    if not isinstance(dates, list) or dates != sorted(set(dates)):
        raise RevisionError("invalid dates index")
    for run_date in dates:
        validate_date(run_date)
    if value.get("latest_date", "") != (dates[-1] if dates else ""):
        raise RevisionError("dates index latest_date does not match its dates")
    protocol = value.get("revision_protocol")
    heads = value.get("revision_heads", {})
    if protocol not in (None, 1) or not isinstance(heads, dict) or (heads and protocol != 1):
        raise RevisionError("unsupported revision index protocol")
    for run_date, head in heads.items():
        if run_date not in dates or not isinstance(head, dict):
            raise RevisionError("revision head is not indexed")
        revision_tag(run_date, head.get("revision"))
        for name in ("manifest_sha256", "bundle_sha256"):
            if not HASH_RE.fullmatch(str(head.get(name, ""))):
                raise RevisionError("invalid revision head digest")
        if head.get("generation_id") != "sha256-" + head["bundle_sha256"]:
            raise RevisionError("invalid generation identity")


def revised_index(index: dict[str, Any], run_date: str, head: dict[str, Any]) -> dict[str, Any]:
    validate_index(index)
    result = dict(index)
    result["dates"] = sorted(set(index["dates"]) | {run_date})
    result["count"] = len(result["dates"])
    result["latest_date"] = result["dates"][-1]
    result["revision_protocol"] = 1
    result["revision_heads"] = {**index.get("revision_heads", {}), run_date: head}
    validate_index(result)
    return result


def _asset_json(root: Path, manifest: dict[str, Any], key: str) -> dict[str, Any]:
    from io import BytesIO
    import payload_crypto

    entry = manifest["files"][key]
    raw = (root / entry["name"]).read_bytes()
    if manifest.get("enc"):
        encryption_key = payload_crypto.resolve_key_from_env()
        if not encryption_key:
            raise RevisionError("encrypted revision delta requires the payload key")
        raw = payload_crypto.decrypt_asset(raw, encryption_key)
    with gzip.GzipFile(fileobj=BytesIO(raw)) as stream:
        expanded = stream.read(MAX_EXPANDED_BYTES + 1)
    if len(expanded) > MAX_EXPANDED_BYTES:
        raise RevisionError("expanded asset exceeds its byte budget")
    value = json.loads(expanded)
    if (not isinstance(value, dict) or value.get("schema_version") != 1
            or value.get("run_date") != manifest["run_date"]):
        raise RevisionError("asset schema or run_date differs from its manifest")
    return value


def _products(root: Path, manifest: dict[str, Any]) -> dict[str, str]:
    details = _asset_json(root, manifest, "details").get("products", {})
    return {key: digest(canonical(value)) for key, value in details.items()}


def _rates(root: Path, manifest: dict[str, Any]) -> Counter[str]:
    core = _asset_json(root, manifest, "core")
    return Counter(digest(canonical({"section": name, "rate": row}))
                   for name, section in core.get("sections", {}).items()
                   for row in section.get("rates", []))


def revision_delta(
    root: Path, manifest: dict[str, Any], previous_root: Path | None,
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    """Full product identities and rate fingerprints; changes never imply withdrawal."""
    new_products = _products(root, manifest)
    new_rates = _rates(root, manifest)
    old_products = _products(previous_root, previous) if previous_root and previous else {}
    old_rates = _rates(previous_root, previous) if previous_root and previous else Counter()
    old_files = (previous or {}).get("files", {})
    return {
        "schema_version": 1, "run_date": manifest["run_date"],
        "comparison": "previous_selected_revision" if previous else "initial",
        "products": {
            "added": sorted(new_products.keys() - old_products.keys()),
            "removed": sorted(old_products.keys() - new_products.keys()),
            "corrected": sorted(key for key in new_products.keys() & old_products.keys()
                                if new_products[key] != old_products[key]),
        },
        "rate_rows": {
            "added": dict(sorted((new_rates - old_rates).items())),
            "removed": dict(sorted((old_rates - new_rates).items())),
        },
        "assets_changed": sorted(key for key in set(old_files) | set(manifest["files"])
                                 if old_files.get(key, {}).get("sha256")
                                 != manifest["files"].get(key, {}).get("sha256")),
    }
