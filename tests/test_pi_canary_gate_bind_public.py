"""Public-candidate bytes binder tests (split from gate bind)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pi_canary_acceptance as canary  # noqa: E402
import pi_canary_gate_bind as bind  # noqa: E402
import pi_canary_gate_emit as emit  # noqa: E402

COMMIT = subprocess.check_output(
    ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True, encoding="utf-8"
).strip()
FAKE_COMMIT = "a" * 40
GENERATION = "prep-test-001"
SNAPSHOT = "c" * 64


def test_public_candidate_rejects_incomplete_v1_manifest(tmp_path: Path) -> None:
    manifest = {
        "schema_version": 1,
        "producer_commit": COMMIT,
        "files": {
            "core": {"name": "core.json.gz", "sha256": "a" * 64, "bytes": 1},
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_public_candidate_bytes(
        gate_dir,
        target_commit=COMMIT,
        manifest_path=manifest_path,
        asset_paths=[],
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
    )
    assert payload["result"] == "FAIL"
    receipt = json.loads(
        (gate_dir / "receipts" / "public_candidate_bytes-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert any("manifest contract" in f for f in receipt["findings"])


def test_public_candidate_enumerates_v3_capabilities(tmp_path: Path) -> None:
    fixture = ROOT / "contracts" / "v3" / "fixtures" / "valid-generation-manifest-v3.json"
    manifest = json.loads(fixture.read_text(encoding="utf-8"))
    manifest["producer_commit"] = COMMIT
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_public_candidate_bytes(
        gate_dir,
        target_commit=COMMIT,
        manifest_path=manifest_path,
        asset_paths=[],
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
    )
    # Missing asset bytes → FAIL, but must not demand legacy files.core.
    assert payload["result"] == "FAIL"
    receipt = json.loads(
        (gate_dir / "receipts" / "public_candidate_bytes-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert "core" in receipt.get("required_keys", [])
    assert not any("files.core" in f for f in receipt["findings"])
    assert not any("manifest.files" in f for f in receipt["findings"])


def _rebind_v3_manifest_identity(manifest: dict) -> str:
    """Retarget producer_commit and refresh generation_id/digest for local bind tests."""
    from cdr_domain.contract_validation import generation_manifest_digest

    manifest["producer_commit"] = COMMIT
    digest = generation_manifest_digest(manifest)
    manifest["generation_digest"] = digest
    revision = int(manifest["generation_revision"])
    generation_id = (
        f"gen-{manifest['observation_date']}-r{revision:04d}-{digest[:12]}"
    )
    manifest["generation_id"] = generation_id
    return generation_id


def test_public_candidate_v3_rejects_hash_ok_but_invalid_payload(tmp_path: Path) -> None:
    """Hash/length match alone must not PASS; validate_generation_manifest must run."""
    fixture = ROOT / "contracts" / "v3" / "fixtures" / "valid-generation-manifest-v3.json"
    manifest = json.loads(fixture.read_text(encoding="utf-8"))
    # Non-gzip bytes declared as gzip: digest matches but publication path rejects.
    bogus = b"not-a-gzip-stream-but-hashed"
    bogus_sha = hashlib.sha256(bogus).hexdigest()
    core = dict(manifest["capabilities"]["core"])
    core["encoding"] = "gzip"
    core["sha256"] = bogus_sha
    core["compressed_bytes"] = len(bogus)
    core["uncompressed_bytes"] = 4096
    core["url"] = (
        "https://github.com/yanniedog/AR-local/releases/download/"
        f"app-payload-gen/{bogus_sha}.json.gz"
    )
    manifest["capabilities"] = {"core": core}
    generation_id = _rebind_v3_manifest_identity(manifest)
    asset = tmp_path / f"{bogus_sha}.json.gz"
    asset.write_bytes(bogus)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_public_candidate_bytes(
        gate_dir,
        target_commit=COMMIT,
        manifest_path=manifest_path,
        asset_paths=[asset],
        candidate_generation=generation_id,
        preservation_snapshot_sha256=SNAPSHOT,
    )
    assert payload["result"] == "FAIL"
    receipt = json.loads(
        (gate_dir / "receipts" / "public_candidate_bytes-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert any("v3 generation validation" in f for f in receipt["findings"])


def test_public_candidate_v3_passes_with_fixture_core(tmp_path: Path) -> None:
    fixture = ROOT / "contracts" / "v3" / "fixtures" / "valid-generation-manifest-v3.json"
    core_path = ROOT / "contracts" / "v3" / "fixtures" / "valid-canonical-core-v3.json"
    manifest = json.loads(fixture.read_text(encoding="utf-8"))
    generation_id = _rebind_v3_manifest_identity(manifest)
    core_bytes = core_path.read_bytes()
    sha = hashlib.sha256(core_bytes).hexdigest()
    assert sha == manifest["capabilities"]["core"]["sha256"]
    asset = tmp_path / f"{sha}.json"
    asset.write_bytes(core_bytes)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_public_candidate_bytes(
        gate_dir,
        target_commit=COMMIT,
        manifest_path=manifest_path,
        asset_paths=[asset],
        candidate_generation=generation_id,
        preservation_snapshot_sha256=SNAPSHOT,
    )
    assert payload["result"] == "PASS"


def test_public_candidate_requires_manifest_generation(tmp_path: Path) -> None:
    core_body = b'{"ok":true}'
    core_sha = hashlib.sha256(core_body).hexdigest()
    asset = tmp_path / "core.json.gz"
    asset.write_bytes(core_body)
    manifest = {
        "schema_version": 1,
        "producer_commit": COMMIT,
        "files": {
            "core": {"name": "core.json.gz", "sha256": core_sha, "bytes": len(core_body)},
            "details": {
                "name": "details.json.gz",
                "sha256": core_sha,
                "bytes": len(core_body),
            },
        },
    }
    details = tmp_path / "details.json.gz"
    details.write_bytes(core_body)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_public_candidate_bytes(
        gate_dir,
        target_commit=COMMIT,
        manifest_path=manifest_path,
        asset_paths=[asset, details],
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
    )
    assert payload["result"] == "FAIL"
    receipt = json.loads(
        (gate_dir / "receipts" / "public_candidate_bytes-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert any("missing candidate_generation" in f for f in receipt["findings"])


def test_public_candidate_v2_does_not_require_files_core(tmp_path: Path) -> None:
    # Minimal v2 shape: files only product_history/economic_outlook; core via base assets.
    hist = b'{"history":true}'
    hist_sha = hashlib.sha256(hist).hexdigest()
    econ = b'{"econ":true}'
    econ_sha = hashlib.sha256(econ).hexdigest()
    core = b'{"core":true}'
    details = b'{"details":true}'
    core_sha = hashlib.sha256(core).hexdigest()
    details_sha = hashlib.sha256(details).hexdigest()
    hist_path = tmp_path / "product_history.json.gz"
    econ_path = tmp_path / "economic_outlook.json.gz"
    core_path = tmp_path / "core.json.gz"
    details_path = tmp_path / "details.json.gz"
    hist_path.write_bytes(hist)
    econ_path.write_bytes(econ)
    core_path.write_bytes(core)
    details_path.write_bytes(details)
    manifest = {
        "schema_version": 2,
        "producer_commit": COMMIT,
        "candidate_generation": GENERATION,
        "base": {"core_sha": core_sha, "details_sha": details_sha},
        "files": {
            "product_history": {
                "name": "product_history.json.gz",
                "sha256": hist_sha,
                "bytes": len(hist),
            },
            "economic_outlook": {
                "name": "economic_outlook.json.gz",
                "sha256": econ_sha,
                "bytes": len(econ),
            },
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_public_candidate_bytes(
        gate_dir,
        target_commit=COMMIT,
        manifest_path=manifest_path,
        asset_paths=[hist_path, econ_path, core_path, details_path],
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
    )
    receipt = json.loads(
        (gate_dir / "receipts" / "public_candidate_bytes-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    # Contract validation may still fail v2 shape; never invent a files.core demand.
    assert "core" not in receipt.get("required_keys", [])
    assert not any("files.core" in f for f in receipt["findings"])
    if not any("manifest contract" in f for f in receipt["findings"]):
        assert payload["result"] == "PASS"
        assert {"base_core", "base_details"}.issubset(
            {c["key"] for c in receipt["checked"]}
        )


def test_public_candidate_v2_rejects_missing_base_assets(tmp_path: Path) -> None:
    """PASS must not authorize v2 when base.core_sha / details_sha bytes are absent."""
    hist = b'{"history":true}'
    hist_sha = hashlib.sha256(hist).hexdigest()
    econ = b'{"econ":true}'
    econ_sha = hashlib.sha256(econ).hexdigest()
    hist_path = tmp_path / "product_history.json.gz"
    econ_path = tmp_path / "economic_outlook.json.gz"
    hist_path.write_bytes(hist)
    econ_path.write_bytes(econ)
    manifest = {
        "schema_version": 2,
        "producer_commit": COMMIT,
        "candidate_generation": GENERATION,
        "base": {"core_sha": "d" * 64, "details_sha": "e" * 64},
        "files": {
            "product_history": {
                "name": "product_history.json.gz",
                "sha256": hist_sha,
                "bytes": len(hist),
            },
            "economic_outlook": {
                "name": "economic_outlook.json.gz",
                "sha256": econ_sha,
                "bytes": len(econ),
            },
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_public_candidate_bytes(
        gate_dir,
        target_commit=COMMIT,
        manifest_path=manifest_path,
        asset_paths=[hist_path, econ_path],
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
    )
    assert payload["result"] == "FAIL"
    receipt = json.loads(
        (gate_dir / "receipts" / "public_candidate_bytes-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert any("base.core_sha asset missing" in f for f in receipt["findings"])
    assert any("base.details_sha asset missing" in f for f in receipt["findings"])


def test_public_candidate_v1_rejects_historical_envelope_wrong_core(
    tmp_path: Path,
) -> None:
    """Hash-valid historical envelope bound to a different core must not PASS."""
    import gzip

    from app_payload_bank_history_asset import (
        ASSET_KIND,
        NAMESPACE,
        digest,
        encode_envelope,
    )

    day = "2026-05-19"
    repo = "yanniedog/AR-local"
    tag = f"app-payload-{day}-r000001"
    core_doc = {
        "schema_version": 1,
        "run_date": day,
        "sections": {"Mortgage": {"rates": []}},
    }
    details_doc = {"schema_version": 1, "run_date": day, "products": {}}
    core_raw = gzip.compress(
        json.dumps(core_doc, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        mtime=0,
    )
    details_raw = gzip.compress(
        json.dumps(details_doc, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        mtime=0,
    )
    core_sha = digest(core_raw)
    details_sha = digest(details_raw)
    core_name = f"core-{day}-{core_sha[:12]}.json.gz"
    details_name = f"details-{day}-{details_sha[:12]}.json.gz"
    core_path = tmp_path / core_name
    details_path = tmp_path / details_name
    core_path.write_bytes(core_raw)
    details_path.write_bytes(details_raw)
    # Envelope claims a different core than files.core — publication rejects this.
    wrong_core = "b" * 64
    hist_wire = encode_envelope(
        {"schema_version": 2, "entries": []},
        run_date=day,
        core_sha256=wrong_core,
    )
    hist_sha = digest(hist_wire)
    hist_name = f"{ASSET_KIND}-{day}-{hist_sha[:12]}.json.gz"
    hist_path = tmp_path / hist_name
    hist_path.write_bytes(hist_wire)
    manifest = {
        "schema_version": 1,
        "run_date": day,
        "generated_at": "2026-05-19T04:00:00Z",
        "repo": repo,
        "tag": tag,
        "producer_commit": COMMIT,
        "candidate_generation": GENERATION,
        "files": {
            "core": {
                "name": core_name,
                "bytes": len(core_raw),
                "sha256": core_sha,
                "url": f"https://github.com/{repo}/releases/download/{tag}/{core_name}",
            },
            "details": {
                "name": details_name,
                "bytes": len(details_raw),
                "sha256": details_sha,
                "url": (
                    f"https://github.com/{repo}/releases/download/{tag}/{details_name}"
                ),
            },
        },
        NAMESPACE: {
            "schema_version": 1,
            "file": {
                "name": hist_name,
                "bytes": len(hist_wire),
                "sha256": hist_sha,
                "url": f"https://github.com/{repo}/releases/download/{tag}/{hist_name}",
            },
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_public_candidate_bytes(
        gate_dir,
        target_commit=COMMIT,
        manifest_path=manifest_path,
        asset_paths=[core_path, details_path, hist_path],
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
    )
    assert payload["result"] == "FAIL"
    receipt = json.loads(
        (gate_dir / "receipts" / "public_candidate_bytes-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert any("v1 local/historical validation" in f for f in receipt["findings"])


def test_validate_v1_payload_root_stages_domain_bytes_not_wire() -> None:
    """Root validation must use verified domain bytes, never release wire blobs."""
    import gzip

    from pi_canary_gate_bind_checks import validate_v1_payload_root

    day = "2026-05-19"
    core_doc = {
        "schema_version": 1,
        "run_date": day,
        "sections": {"Mortgage": {"rates": []}},
    }
    details_doc = {"schema_version": 1, "run_date": day, "products": {}}
    core_raw = gzip.compress(
        json.dumps(core_doc, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        mtime=0,
    )
    details_raw = gzip.compress(
        json.dumps(details_doc, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        mtime=0,
    )
    core_sha = hashlib.sha256(core_raw).hexdigest()
    details_sha = hashlib.sha256(details_raw).hexdigest()
    core_name = f"core-{day}-{core_sha[:12]}.json.gz"
    details_name = f"details-{day}-{details_sha[:12]}.json.gz"
    manifest = {
        "schema_version": 1,
        "run_date": day,
        "generated_at": "2026-05-19T04:00:00Z",
        "repo": "yanniedog/AR-local",
        "tag": f"app-payload-{day}-r000001",
        "producer_commit": COMMIT,
        "files": {
            "core": {"name": core_name, "bytes": len(core_raw), "sha256": core_sha},
            "details": {
                "name": details_name,
                "bytes": len(details_raw),
                "sha256": details_sha,
            },
        },
    }
    ok = validate_v1_payload_root(
        manifest, {core_name: core_raw, details_name: details_raw}
    )
    assert ok == []
    # Ciphertext / wrong wire must not be treated as domain bytes.
    wire = b"ARE2" + b"0" * 80
    bad = validate_v1_payload_root(
        manifest, {core_name: wire, details_name: details_raw}
    )
    assert bad and any("v1 local/historical validation" in f for f in bad)
    missing = validate_v1_payload_root(manifest, {core_name: core_raw})
    assert any("missing staged domain bytes" in f for f in missing)


def test_public_candidate_v2_rejects_hash_ok_but_invalid_gzip(tmp_path: Path) -> None:
    """v2 gzip encoding must be validated even when compressed hash/length match."""
    import gzip

    # Build a schema-valid v2 manifest with non-gzip payload bytes that hash-match.
    bogus = b"not-a-gzip-stream-but-hashed"
    bogus_sha = hashlib.sha256(bogus).hexdigest()
    plain = b'{"ok":true}'
    plain_gz = gzip.compress(plain, mtime=0)
    # One asset is valid gzip so contract/shape can pass; the other is bogus.
    hist_sha = hashlib.sha256(bogus).hexdigest()
    econ_sha = hashlib.sha256(plain_gz).hexdigest()
    hist_path = tmp_path / "product_history.json.gz"
    econ_path = tmp_path / "economic_outlook.json.gz"
    hist_path.write_bytes(bogus)
    econ_path.write_bytes(plain_gz)
    manifest = {
        "schema_version": 2,
        "producer_commit": COMMIT,
        "candidate_generation": GENERATION,
        "capabilities": ["product_history", "economic_outlook"],
        "base": {"core_sha": "d" * 64, "details_sha": "e" * 64},
        "files": {
            "product_history": {
                "name": "product_history.json.gz",
                "sha256": hist_sha,
                "bytes": len(bogus),
                "uncompressed_bytes": 4096,
                "encoding": "gzip",
                "url": (
                    "https://github.com/yanniedog/AR-local/releases/download/"
                    f"app-payload-v2/{hist_sha}"
                ),
            },
            "economic_outlook": {
                "name": "economic_outlook.json.gz",
                "sha256": econ_sha,
                "bytes": len(plain_gz),
                "uncompressed_bytes": len(plain),
                "encoding": "gzip",
                "url": (
                    "https://github.com/yanniedog/AR-local/releases/download/"
                    f"app-payload-v2/{econ_sha}"
                ),
            },
        },
    }
    # Silence unused — keep sha naming aligned with Codex finding.
    assert hist_sha == bogus_sha
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_public_candidate_bytes(
        gate_dir,
        target_commit=COMMIT,
        manifest_path=manifest_path,
        asset_paths=[hist_path, econ_path],
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
    )
    assert payload["result"] == "FAIL"
    receipt = json.loads(
        (gate_dir / "receipts" / "public_candidate_bytes-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert any("v2 gzip validation" in f for f in receipt["findings"])

