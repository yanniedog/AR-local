"""Build a private history catalogue from already acquired, byte-bound releases.

No network, credentials, publication, revision reservation or source writes.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import gzip
import hashlib
import io
import json
from pathlib import Path

from app_payload_bank_catalogue import HistoricalCatalogue, published_evidence
from app_payload_common import VALID_SECTIONS
from app_payload_revisions_state import bundle_sha256, validate_index, validate_manifest

MAX_JSON_BYTES = 64 * 1024 * 1024


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_file(path, limit=MAX_JSON_BYTES):
    if path.resolve() != path.absolute() or not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ValueError("Missing, unsafe or oversized prepack input")
    raw = path.read_bytes()
    if len(raw) > limit:
        raise ValueError("Prepack input changed beyond its byte budget")
    return raw


def read_asset(root, kind, descriptor, day):
    raw = read_file(root / kind / (descriptor["sha256"] + ".gz"))
    if len(raw) != descriptor["bytes"] or digest(raw) != descriptor["sha256"]:
        raise ValueError("Historical asset differs from its selected manifest")
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
        decoded = compressed.read(MAX_JSON_BYTES + 1)
    if len(decoded) > MAX_JSON_BYTES:
        raise ValueError("Historical asset decompression exceeds budget")
    value = json.loads(decoded)
    if not isinstance(value, dict) or value.get("schema_version") != 1 or value.get("run_date") != day:
        raise ValueError("Historical asset has wrong schema or observation date")
    return value


def selected_day(root, index, day):
    head = index["revision_heads"].get(day)
    if head is None:
        raise ValueError("Every prepack date requires an immutable selected head")
    raw = read_file(root / "manifests" / (day + ".json"))
    if digest(raw) != head["manifest_sha256"]:
        raise ValueError("Historical manifest differs from the pinned index")
    manifest = json.loads(raw)
    validate_manifest(manifest)
    revision = manifest.get("payload_revision", {})
    if (manifest["run_date"] != day or bundle_sha256(manifest) != head["bundle_sha256"]
            or any(revision.get(key) != head[key] for key in ("revision", "generation_id", "bundle_sha256"))):
        raise ValueError("Historical manifest has a different selected revision")
    core = read_asset(root, "cores", manifest["files"]["core"], day)
    details = read_asset(root, "details", manifest["files"]["details"], day)
    sections = core.get("sections")
    if (not isinstance(sections, dict) or any(not isinstance(sections.get(section), dict)
            or not isinstance(sections[section].get("rates"), list)
            or any(not isinstance(row, dict) for row in sections[section]["rates"])
            for section in VALID_SECTIONS) or not isinstance(details.get("products"), dict)):
        raise ValueError("Historical core or details has an invalid schema")
    source = {"kind": "published_core", "manifest_sha256": head["manifest_sha256"],
              "core_sha256": manifest["files"]["core"]["sha256"],
              "details_sha256": manifest["files"]["details"]["sha256"]}
    return core, details["products"], source


def prepack(root: Path, output: Path, *, index_sha256: str):
    root, output = root.absolute(), output.absolute()
    if output.exists() or output == root or root.is_relative_to(output):
        raise ValueError("Private output must be a new directory separate from source files")
    raw_index = read_file(root / "dates-index.json")
    if digest(raw_index) != index_sha256:
        raise ValueError("Prepack index differs from its independently verified digest")
    index = json.loads(raw_index)
    validate_index(index)
    observed = index["dates"]
    if not observed or index.get("count") != len(observed):
        raise ValueError("Prepack requires a complete nonempty date index")
    first, last = date.fromisoformat(observed[0]), date.fromisoformat(observed[-1])
    if not 0 < (last - first).days + 1 <= 5000:
        raise ValueError("Prepack date axis exceeds budget")
    dates = [(first + timedelta(days=offset)).isoformat() for offset in range((last - first).days + 1)]
    catalogue = HistoricalCatalogue(dates)
    current = None
    for day in observed:
        current, details, source = selected_day(root, index, day)
        catalogue.observe(day, {section: current["sections"][section]["rates"] for section in VALID_SECTIONS},
                          lambda row, section: published_evidence(row, section, details), source)
    current["bank_rate_history_catalogue"] = catalogue.finish()
    encoded = json.dumps(current, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_JSON_BYTES:
        raise ValueError("Prepacked core exceeds the app JSON byte budget")
    compressed = gzip.compress(encoded, mtime=0)
    packed_catalogue = json.dumps(current["bank_rate_history_catalogue"], ensure_ascii=False,
                                  separators=(",", ":")).encode("utf-8")
    report = {"status": "PASS", "acquisition": "verified_public_inputs", "publication_verified": False,
              "index_sha256": index_sha256, "observed_dates": len(observed), "calendar_dates": len(dates),
              "run_date": observed[-1], "first_date": observed[0],
              "core_sha256": digest(compressed), "core_bytes": len(compressed),
              "core_json_bytes": len(encoded), "catalogue_json_bytes": len(packed_catalogue),
              "catalogue_gzip_bytes": len(gzip.compress(packed_catalogue, mtime=0)),
              "tiers": {section: len(catalogue.sections[section]) for section in VALID_SECTIONS},
              "evidence_count": len(catalogue.evidence), "source_count": len(catalogue.sources)}
    output.mkdir(parents=True)
    (output / "core.json").write_bytes(encoded)
    (output / "core.json.gz").write_bytes(compressed)
    (output / "catalogue.json").write_bytes(packed_catalogue)
    (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--index-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(prepack(args.source, args.output, index_sha256=args.index_sha256)), flush=True)


if __name__ == "__main__":
    main()
