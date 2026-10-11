"""One-time, explicitly selected transport-only migration of published data."""
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path

from app_payload_optional_assets import iter_payload_assets
from app_payload_public_companion import _inventory, _selected, publish_companion
from app_payload_public_github import TAG, public_asset
from app_payload_revisions_github import GitHubRevisionStore, write_once
from app_payload_revisions_state import RevisionError, decode_document, digest, validate_index, validate_manifest
from ar_local_operation_lock import production_lock

REPO = "yanniedog/AR-local"


class LegacyDeliveryMigrationReader:
    """Explicit migration source only; never used by ongoing publication/apps.

    This existing HTTPS service authenticates ARE2 and returns its unchanged
    domain bytes. Every received object still needs its canonical SHA receipt.
    No service deployment, login, key retrieval or decryption fallback occurs.
    """
    repo, gh = REPO, "gh"

    def read(self, tag, name, limit=8 * 1024 * 1024, *, require_encrypted=False):
        if (not require_encrypted or not (TAG.fullmatch(tag) or tag == "app-payload-latest")
                or not (public_asset(name) or name == "dates-index.json")):
            raise RevisionError("Migration read is outside authenticated app inventory")
        url = f"https://ar-app-data.jkokavec.workers.dev/v1/release/{tag}/{name}"
        request = urllib.request.Request(url, headers={"User-Agent": "AustralianRates/1.0", "Accept-Encoding": "identity", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read(limit + 1)
        if len(raw) > limit or raw.startswith((b"ARE1", b"ARE2")):
            raise RevisionError("Migration source did not return bounded authenticated domain bytes")
        return raw


def prepare(reader, destination: Path, expected_manifest_sha256: str):
    if not re.fullmatch(r"[a-f0-9]{64}", expected_manifest_sha256):
        raise RevisionError("Bootstrap requires the reviewed exact selected manifest SHA256")
    index_raw = reader.read("app-payload-latest", "dates-index.json", require_encrypted=True)
    if index_raw is None:
        raise RevisionError("Published selection is missing")
    index = decode_document(index_raw)
    validate_index(index, repo=REPO)
    day = index["latest_date"]
    head = index.get("revision_heads", {}).get(day)
    if not head or head["manifest_sha256"] != expected_manifest_sha256:
        raise RevisionError("Current selected manifest differs from reviewed bootstrap identity")
    tag = f'app-payload-{day}-r{head["revision"]:06d}'
    raw = reader.read(tag, "manifest.json", require_encrypted=True)
    if raw is None or digest(raw) != expected_manifest_sha256:
        raise RevisionError("Published bootstrap manifest receipt differs")
    manifest = decode_document(raw)
    validate_manifest(manifest)
    _selected(manifest, raw, index)
    if manifest.get("enc"):
        raise RevisionError("Bootstrap cannot transform historical inner ARE1 encryption")
    entries = list(iter_payload_assets(manifest))
    if any(not public_asset(entry["name"]) or entry.get("enc") for _, entry in entries):
        raise RevisionError("Bootstrap inventory includes private or inner-encrypted objects")
    write_once(destination / "manifest.json", raw)
    write_once(destination / "dates-index.json", index_raw)
    for _, entry in entries:
        raw = reader.read(tag, entry["name"], entry["bytes"], require_encrypted=True)
        if raw is None or len(raw) != entry["bytes"] or digest(raw) != entry["sha256"]:
            raise RevisionError("Published bootstrap asset receipt differs")
        write_once(destination / entry["name"], raw)
    _inventory(destination, manifest, bootstrap=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--legacy-service-migration", action="store_true")
    parser.add_argument("--publish", action="store_true", help="Promote only after reviewed code/test gates; default prepares local evidence")
    args = parser.parse_args()
    reader = LegacyDeliveryMigrationReader() if args.legacy_service_migration else GitHubRevisionStore(REPO)
    with production_lock(args.state.resolve() / ".public-bootstrap.lock", "public-data-bootstrap"):
        manifest = prepare(reader, args.output.resolve(), args.expected_manifest_sha256)
        if args.publish:
            publish_companion(args.output.resolve(), reader, args.state.resolve(), bootstrap=True)
    print(json.dumps({"status": "PUBLISHED" if args.publish else "PREPARED", "canonical_tag": manifest["tag"],
                      "manifest_sha256": args.expected_manifest_sha256,
                      "source": "legacy_authenticated_delivery" if args.legacy_service_migration else "authenticated_release"}))


if __name__ == "__main__":
    main()
