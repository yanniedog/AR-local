"""Ready history is required, receipt-bound, and delivered beside legacy data."""
import copy
import gzip
import json
from pathlib import Path

import pytest

from app_payload_bank_history_asset import canonical, digest
from app_payload_bank_history_ready_asset import NAMESPACE, descriptor, decode_envelope
from app_payload_optional_assets import iter_payload_assets
from app_payload_revisions_state import validate_manifest
from tests.test_app_payload_bank_history_asset import real_bundle


def test_committed_ready_fixture_reproduces_from_retained_observations():
    from tests.test_app_payload_bank_catalogue import FIXTURE, packed
    from app_payload_bank_history_ready_asset import compile_ready
    catalogue = packed(json.loads(FIXTURE.read_bytes())["observations"])
    actual = compile_ready(catalogue)
    fixture = json.loads((Path(__file__).parent / "fixtures/history-ready-real.json").read_bytes())
    assert actual == fixture


def test_ready_compiler_matches_reviewed_lvr_interval_consumer():
    from app_payload_bank_history_ready_asset import compiler_identity, _invoke
    # Independent pin exported from the matching AR-app LVR interval change.
    # Publication still requires that consumer to be released and verified.
    expected = "19ab18920ab6400be627d32d3df9be39416b826c6b83d0c6f90ac9440ec15676"
    assert compiler_identity()[1] == expected
    ready = json.loads((Path(__file__).parent / "fixtures/history-ready-real.json").read_bytes())
    assert ready["compiler_sha256"] == expected
    assert _invoke(ready, validate=True) == expected
    ready["compiler_sha256"] = "fbd65b58c421e99518ccbfd375f42b16c40c7b45d29a07dad09c084c42b762f3"
    with pytest.raises(ValueError, match="compilation/validation failed"):
        _invoke(ready, validate=True)


@pytest.mark.parametrize("encrypted", [False, True])
def test_ready_history_is_bound_and_both_raw_formats_remain(tmp_path, monkeypatch, encrypted):
    import payload_crypto
    key = bytes(range(32)) if encrypted else None
    monkeypatch.setattr(payload_crypto, "resolve_key_from_env", lambda: key)
    manifest, catalogue, _ = real_bundle(tmp_path, enc_key=key)
    assert "url" not in manifest[NAMESPACE]["file"]
    assert NAMESPACE not in manifest["files"]
    assert {"bank_rate_history_catalogue", "bank_rate_history_catalogue_packed", NAMESPACE} <= set(manifest)
    entry = descriptor(manifest)
    wire = (tmp_path / entry["name"]).read_bytes()
    assert digest(wire) == entry["sha256"] and len(wire) == entry["bytes"]
    ready = decode_envelope(payload_crypto.decrypt_asset(wire, key) if key else wire,
                            run_date=manifest["run_date"], core_sha256=manifest["files"]["core"]["sha256"])
    assert ready["run_dates"] == catalogue["run_dates"]
    assert ready["sources"] == catalogue["sources"]
    assert ready["semantic_revision"] == "ar-history-ready-v1"
    validate_manifest(manifest, tmp_path)


@pytest.mark.parametrize("field", ["run_date", "core_sha256", "compiler_sha256"])
def test_ready_rejects_wrong_receipt_authority(tmp_path, field):
    import base64
    manifest, _, _ = real_bundle(tmp_path)
    entry = descriptor(manifest)
    value = json.loads(gzip.decompress((tmp_path / entry["name"]).read_bytes()))
    if field == "compiler_sha256":
        ready = json.loads(gzip.decompress(base64.b64decode(value["catalogue"]["gzip_base64"])))
        ready[field] = "0" * 64
        raw = canonical(ready)
        value["catalogue"] = {"bytes": len(raw), "sha256": digest(raw),
                              "gzip_base64": base64.b64encode(gzip.compress(raw, mtime=0)).decode()}
    else:
        value[field] = "2020-01-01" if field == "run_date" else "0" * 64
    with pytest.raises(ValueError):
        decode_envelope(gzip.compress(canonical(value), mtime=0),
                        run_date=manifest["run_date"], core_sha256=manifest["files"]["core"]["sha256"])


def test_ready_compilation_failure_defers_publication(tmp_path, monkeypatch):
    import app_payload_bank_history_ready_asset as asset
    def fail(_):
        raise ValueError("Ready history unavailable; publication deferred")
    monkeypatch.setattr(asset, "compile_ready", fail)
    with pytest.raises(ValueError, match="publication deferred"):
        real_bundle(tmp_path)
    assert not (tmp_path / "manifest.json").exists()


@pytest.mark.parametrize("budget", ["INNER_JSON_MAX_BYTES", "OUTER_JSON_MAX_BYTES", "ASSET_MAX_BYTES"])
def test_ready_processing_limits_cannot_fall_back_to_slow_history(tmp_path, monkeypatch, budget):
    import app_payload_bank_history_ready_asset as asset
    monkeypatch.setattr(asset, budget, 1)
    with pytest.raises(ValueError, match="publication deferred"):
        real_bundle(tmp_path)
    assert not (tmp_path / "manifest.json").exists()


def test_ready_compiler_artifact_must_match_its_reviewed_pin(tmp_path, monkeypatch):
    import app_payload_bank_history_ready_asset as asset
    (tmp_path / "compiler.cjs").write_bytes(b"invalid compiler control")
    (tmp_path / "compiler-manifest.json").write_text(json.dumps({
        "sha256": "0" * 64, "semantic_revision": asset.SEMANTIC_REVISION}))
    monkeypatch.setattr(asset, "COMPILER_ROOT", tmp_path)
    with pytest.raises(ValueError, match="reviewed pin"):
        asset.compiler_identity()


def test_ready_interrupted_upload_never_promotes_a_partial_inventory(tmp_path):
    from tests.test_app_payload_revisions import MemoryStore, publish
    from app_payload_revisions_state import RevisionError
    manifest, _, _ = real_bundle(tmp_path / "payload")
    store = MemoryStore()
    store.fail_asset = manifest[NAMESPACE]["file"]["name"]
    with pytest.raises(RevisionError, match="interrupted upload"):
        publish(tmp_path, store)
    assert store.promotions == 0
    store.fail_asset = None
    result = publish(tmp_path, store)
    entry = descriptor(result.manifest)
    ready = decode_envelope(store.read_url(entry["url"]), run_date=manifest["run_date"],
                             core_sha256=manifest["files"]["core"]["sha256"])
    assert ready["semantic_revision"] == "ar-history-ready-v1"


def test_ready_priority_omits_packed_only_and_cannot_exceed_budget(tmp_path, monkeypatch):
    import app_payload_network_budget as budget
    first, _, _ = real_bundle(tmp_path / "first")
    necessary = sum(entry["bytes"] for key, entry in iter_payload_assets(first) if key != "bank_rate_history_catalogue_packed")
    monkeypatch.setattr(budget, "ROLLING_TOTAL_MAX_BYTES", necessary)
    manifest, _, _ = real_bundle(tmp_path / "second")
    assert NAMESPACE in manifest and "bank_rate_history_catalogue" in manifest
    assert "bank_rate_history_catalogue_packed" not in manifest
    validate_manifest(manifest, tmp_path / "second")
    monkeypatch.setattr(budget, "ROLLING_TOTAL_MAX_BYTES", necessary - 1)
    with pytest.raises(ValueError, match="Ready history exceeds.*publication deferred"):
        real_bundle(tmp_path / "third")
    assert not (tmp_path / "third" / "manifest.json").exists()


def test_ready_identity_is_part_of_publication_confirmation(tmp_path):
    from pi_daily_sync import _same_payload_revision
    manifest, _, _ = real_bundle(tmp_path)
    changed = copy.deepcopy(manifest)
    changed[NAMESPACE]["file"]["bytes"] += 1
    assert not _same_payload_revision(manifest, changed)
    changed.pop(NAMESPACE)
    assert not _same_payload_revision(manifest, changed)


@pytest.mark.parametrize("fault", ["url", "eager", "name"])
def test_ready_cannot_override_routing_or_join_eager_files(tmp_path, fault):
    manifest, _, _ = real_bundle(tmp_path)
    if fault == "eager":
        manifest["files"][NAMESPACE] = manifest.pop(NAMESPACE)["file"]
    else:
        manifest[NAMESPACE]["file"][fault] = "https://example.invalid" if fault == "url" else "../escape"
    with pytest.raises(ValueError):
        list(iter_payload_assets(manifest))
