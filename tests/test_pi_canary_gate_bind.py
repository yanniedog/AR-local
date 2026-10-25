"""Tests for canary gate emit/bind helpers (no fabricated live acceptance)."""

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


def test_emit_refuses_pass_without_bindings(tmp_path: Path) -> None:
    receipt = emit.materialize_receipt(
        tmp_path, relative_path="receipts/x.json", payload={"ok": True}
    )
    with pytest.raises(emit.GateEmitError, match="PASS requires"):
        emit.emit_gate_evidence(
            tmp_path,
            gate="producer_contracts",
            result="PASS",
            target_commit=FAKE_COMMIT,
            evidence_items=[receipt],
        )


def test_emit_unknown_without_pass_bindings(tmp_path: Path) -> None:
    receipt = emit.materialize_receipt(
        tmp_path, relative_path="receipts/x.json", payload={"ok": True}
    )
    path, payload = emit.emit_gate_evidence(
        tmp_path,
        gate="shadow_ingest",
        result="UNKNOWN",
        target_commit=FAKE_COMMIT,
        evidence_items=[receipt],
        notes="missing receipt",
    )
    assert path.is_file()
    assert payload["result"] == "UNKNOWN"
    assert "candidate_generation" not in payload


def test_producer_contracts_pass_on_real_repo_schemas(tmp_path: Path) -> None:
    payload = bind.bind_producer_contracts(
        tmp_path,
        target_commit=COMMIT,
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
    )
    assert payload["result"] == "PASS"
    assert payload["target_commit"] == COMMIT
    assert (tmp_path / "producer_contracts.json").is_file()
    assert (tmp_path / "receipts" / "producer_contracts-receipt.json").is_file()


def test_historical_integrity_fail_when_summary_incomplete(tmp_path: Path) -> None:
    summary = tmp_path / "summary.json"
    summary.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dates_checked": 2,
                "dates_passed": 1,
                "index_sha256": "d" * 64,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_historical_integrity(
        gate_dir,
        target_commit=COMMIT,
        summary_path=summary,
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
    )
    assert payload["result"] == "FAIL"


def test_historical_integrity_refuses_scoped_one_date_by_default(tmp_path: Path) -> None:
    summary = tmp_path / "summary.json"
    summary.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dates_checked": 1,
                "dates_passed": 1,
                "index_sha256": "d" * 64,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_historical_integrity(
        gate_dir,
        target_commit=COMMIT,
        summary_path=summary,
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
    )
    assert payload["result"] == "FAIL"


def test_historical_integrity_scoped_flag_never_authorizes(tmp_path: Path) -> None:
    summary = tmp_path / "summary.json"
    summary.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dates_checked": 2,
                "dates_passed": 2,
                "index_sha256": "d" * 64,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_historical_integrity(
        gate_dir,
        target_commit=COMMIT,
        summary_path=summary,
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
        allow_scoped_index=True,
    )
    assert payload["result"] == "FAIL"


def test_write_json_atomic_publishes_via_replace(tmp_path: Path) -> None:
    path = tmp_path / "out.json"
    digest = emit.write_json_atomic(path, {"ok": True})
    assert path.is_file()
    assert digest == emit.sha256_file(path)
    with pytest.raises(emit.GateEmitError, match="overwrite"):
        emit.write_json_atomic(path, {"ok": False})


def test_write_json_atomic_preserves_peer_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TOCTOU: peer owns destination after exists-check; do not unlink it."""

    path = tmp_path / "peer.json"
    path.write_text('{"peer": true}\n', encoding="utf-8")
    before = path.read_bytes()
    target = path.resolve()
    orig_exists = Path.exists
    orig_is_symlink = Path.is_symlink

    def fake_exists(self: Path) -> bool:
        try:
            if self.resolve() == target:
                return False
        except OSError:
            pass
        return orig_exists(self)

    def fake_is_symlink(self: Path) -> bool:
        try:
            if self.resolve() == target:
                return False
        except OSError:
            pass
        return orig_is_symlink(self)

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)
    with pytest.raises(FileExistsError):
        emit.write_json_atomic(path, {"hijack": True})
    assert path.read_bytes() == before


def test_historical_integrity_requires_expected_index_binding(tmp_path: Path) -> None:
    index = {
        "dates": ["2026-01-01", "2026-01-02", "2026-01-03"],
        "revision_heads": {},
    }
    index_raw = (json.dumps(index, sort_keys=True) + "\n").encode("utf-8")
    index_path = tmp_path / "dates-index.json"
    index_path.write_bytes(index_raw)
    index_sha = hashlib.sha256(index_raw).hexdigest()
    # Scoped two-date audit claiming the full-index digest must still FAIL.
    summary = tmp_path / "summary.json"
    summary.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dates_checked": 2,
                "dates_passed": 2,
                "index_sha256": index_sha,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_historical_integrity(
        gate_dir,
        target_commit=COMMIT,
        summary_path=summary,
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
        expected_index_path=index_path,
    )
    assert payload["result"] == "FAIL"
    receipt = json.loads(
        (gate_dir / "receipts" / "historical_integrity-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert any("population" in f for f in receipt["findings"])


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


def test_receipt_gate_validates_preserved_bytes_not_source_reread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the producer rewrites the source after copy, binder must use preserved bytes."""
    import pi_canary_gate_bind_ops as ops

    receipt = tmp_path / "r.json"
    fail_body = {
        "gate": "shadow_ingest",
        "target_commit": COMMIT,
        "result": "FAIL",
        "candidate_generation": GENERATION,
        "preservation_snapshot_sha256": SNAPSHOT,
    }
    pass_body = {
        "gate": "shadow_ingest",
        "target_commit": COMMIT,
        "result": "PASS",
        "candidate_generation": GENERATION,
        "preservation_snapshot_sha256": SNAPSHOT,
    }
    receipt.write_text(json.dumps(fail_body) + "\n", encoding="utf-8")
    original = ops._copy_source_receipt

    def copy_then_rewrite(gate_dir, *, source, relative_path):
        item = original(gate_dir, source=source, relative_path=relative_path)
        source.write_text(json.dumps(pass_body) + "\n", encoding="utf-8")
        return item

    monkeypatch.setattr(ops, "_copy_source_receipt", copy_then_rewrite)
    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_receipt_gate(
        gate_dir,
        gate="shadow_ingest",
        target_commit=COMMIT,
        receipt_path=receipt,
        required_fields={"target_commit": COMMIT},
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
        missing_reason="unused",
    )
    assert payload["result"] == "FAIL"
    preserved = json.loads(
        (gate_dir / "receipts" / "shadow_ingest-source.json").read_text(encoding="utf-8")
    )
    assert preserved["result"] == "FAIL"


def test_receipt_gate_rejects_missing_explicit_pass(tmp_path: Path) -> None:
    receipt = tmp_path / "r.json"
    receipt.write_text(
        json.dumps({"gate": "shadow_ingest", "target_commit": COMMIT, "status": "FAIL"})
        + "\n",
        encoding="utf-8",
    )
    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_receipt_gate(
        gate_dir,
        gate="shadow_ingest",
        target_commit=COMMIT,
        receipt_path=receipt,
        required_fields={"target_commit": COMMIT},
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
        missing_reason="unused",
    )
    assert payload["result"] == "FAIL"
    assert (gate_dir / "receipts" / "shadow_ingest-source.json").is_file()


def test_receipt_gate_rejects_generation_relabel(tmp_path: Path) -> None:
    receipt = tmp_path / "r.json"
    receipt.write_text(
        json.dumps(
            {
                "gate": "shadow_ingest",
                "target_commit": COMMIT,
                "result": "PASS",
                "candidate_generation": "prep-old",
                "preservation_snapshot_sha256": SNAPSHOT,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_receipt_gate(
        gate_dir,
        gate="shadow_ingest",
        target_commit=COMMIT,
        receipt_path=receipt,
        required_fields={"target_commit": COMMIT},
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
        missing_reason="unused",
    )
    assert payload["result"] == "FAIL"


def test_receipt_gate_rejects_cross_gate_substitution(tmp_path: Path) -> None:
    receipt = tmp_path / "r.json"
    receipt.write_text(
        json.dumps(
            {
                "gate": "shadow_ingest",
                "target_commit": COMMIT,
                "result": "PASS",
                "candidate_generation": GENERATION,
                "preservation_snapshot_sha256": SNAPSHOT,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_receipt_gate(
        gate_dir,
        gate="candidate_device_matrix",
        target_commit=COMMIT,
        receipt_path=receipt,
        required_fields={"target_commit": COMMIT},
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
        missing_reason="unused",
    )
    assert payload["result"] == "FAIL"
    body = json.loads(
        (gate_dir / "receipts" / "candidate_device_matrix-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert any("gate:" in f and "shadow_ingest" in f for f in body["findings"])


def test_receipt_gate_rejects_shadow_without_exit_exports(tmp_path: Path) -> None:
    """Labeled PASS without exit_code/exports must not authorize shadow_ingest."""
    receipt = tmp_path / "r.json"
    receipt.write_text(
        json.dumps(
            {
                "gate": "shadow_ingest",
                "target_commit": COMMIT,
                "result": "PASS",
                "candidate_generation": GENERATION,
                "preservation_snapshot_sha256": SNAPSHOT,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_receipt_gate(
        gate_dir,
        gate="shadow_ingest",
        target_commit=COMMIT,
        receipt_path=receipt,
        required_fields={"target_commit": COMMIT},
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
        missing_reason="unused",
    )
    assert payload["result"] == "FAIL"
    body = json.loads(
        (gate_dir / "receipts" / "shadow_ingest-receipt.json").read_text(encoding="utf-8")
    )
    assert any("exit_code" in f for f in body["findings"])
    assert any("exports" in f for f in body["findings"])


def test_receipt_gate_passes_shadow_with_exit_exports(tmp_path: Path) -> None:
    receipt = tmp_path / "r.json"
    receipt.write_text(
        json.dumps(
            {
                "gate": "shadow_ingest",
                "target_commit": COMMIT,
                "result": "PASS",
                "exit_code": 0,
                "exports_dirs": ["/srv/ar-local/canary/exports/day"],
                "candidate_generation": GENERATION,
                "preservation_snapshot_sha256": SNAPSHOT,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_receipt_gate(
        gate_dir,
        gate="shadow_ingest",
        target_commit=COMMIT,
        receipt_path=receipt,
        required_fields={"target_commit": COMMIT},
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
        missing_reason="unused",
    )
    assert payload["result"] == "PASS"


def test_receipt_gate_rejects_empty_device_matrix(tmp_path: Path) -> None:
    """Matrix labels alone (empty devices / FAIL rows) must not authorize PASS."""
    receipt = tmp_path / "r.json"
    receipt.write_text(
        json.dumps(
            {
                "gate": "candidate_device_matrix",
                "target_commit": COMMIT,
                "result": "PASS",
                "devices": [{"model": "Pixel", "result": "FAIL"}],
                "candidate_generation": GENERATION,
                "preservation_snapshot_sha256": SNAPSHOT,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_receipt_gate(
        gate_dir,
        gate="candidate_device_matrix",
        target_commit=COMMIT,
        receipt_path=receipt,
        required_fields={"target_commit": COMMIT},
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
        missing_reason="unused",
    )
    assert payload["result"] == "FAIL"
    body = json.loads(
        (gate_dir / "receipts" / "candidate_device_matrix-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert any("devices[0].result must be PASS" in f for f in body["findings"])


def test_producer_contracts_reject_mismatched_target(tmp_path: Path) -> None:
    payload = bind.bind_producer_contracts(
        tmp_path,
        target_commit=FAKE_COMMIT,
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
    )
    assert payload["result"] == "FAIL"


def test_producer_contracts_reject_invalid_v3_metaschema(tmp_path: Path) -> None:
    """Syntactically valid but metaschema-invalid v3 schema must FAIL (not digest-only PASS)."""
    import shutil

    from cdr_domain import contract_validation

    contracts_root = tmp_path / "contracts"
    contracts_root.mkdir()
    # Top-level schema must be Draft 2020-12 valid so only the v3 defect is exercised.
    (contracts_root / "top.schema.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    v3_src = ROOT / "contracts" / "v3"
    v3_dst = contracts_root / "v3"
    v3_dst.mkdir()
    for name in contract_validation.SCHEMA_FILES:
        shutil.copy2(v3_src / name, v3_dst / name)
    bad = v3_dst / "canonical-core-v3.schema.json"
    schema = json.loads(bad.read_text(encoding="utf-8"))
    schema["type"] = 42  # invalid JSON Schema type keyword
    bad.write_text(json.dumps(schema) + "\n", encoding="utf-8")

    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_producer_contracts(
        gate_dir,
        target_commit=COMMIT,
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
        contracts_root=contracts_root,
    )
    assert payload["result"] == "FAIL"
    receipt = json.loads(
        (gate_dir / "receipts" / "producer_contracts-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert any(
        f.startswith("v3/canonical-core-v3.schema.json:") for f in receipt["findings"]
    )


def test_harness_isolates_malformed_receipt(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")
    status = bind.run_harness(
        tmp_path / "gates",
        target_commit=COMMIT,
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
        shadow_receipt=bad,
        skip_ssh=True,
    )
    assert status["assemble_ready"] is False
    assert (tmp_path / "gates" / "status.json").is_file()
    assert status["gates"]["shadow_ingest"]["result"] == "FAIL"
    assert status["gates"]["producer_contracts"]["result"] == "PASS"


def test_harness_fail_closed_without_external_receipts(tmp_path: Path) -> None:
    status = bind.run_harness(
        tmp_path / "gates",
        target_commit=COMMIT,
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
        skip_ssh=True,
    )
    assert status["assemble_ready"] is False
    assert status["gates"]["producer_contracts"]["result"] == "PASS"
    for gate in (
        "preservation_restore",
        "historical_integrity",
        "shadow_ingest",
        "stable_app_compatibility",
        "candidate_emulator_matrix",
        "candidate_device_matrix",
        "public_candidate_bytes",
    ):
        assert status["gates"][gate]["result"] in {"UNKNOWN", "FAIL"}
    # Assembler must refuse.
    import pi_canary_acceptance_assemble as assemble

    gate_dir = tmp_path / "gates"
    with pytest.raises(assemble.CanaryAssembleError, match="unresolved gates"):
        assemble.assemble_canary_acceptance(
            repository="yanniedog/AR-local",
            target_commit=COMMIT,
            candidate_generation=GENERATION,
            preservation_snapshot_sha256=SNAPSHOT,
            completed_at="2026-10-26T00:00:00+00:00",
            output=tmp_path / "canary-acceptance.json",
            gate_paths={g: gate_dir / f"{g}.json" for g in canary.REQUIRED_ACCEPTANCE_GATES},
        )
    assert not (tmp_path / "canary-acceptance.json").exists()


def test_sha256_helpers_stable() -> None:
    raw = b"abc"
    assert emit.sha256_bytes(raw) == hashlib.sha256(raw).hexdigest()
