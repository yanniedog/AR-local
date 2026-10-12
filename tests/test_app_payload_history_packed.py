"""Packed history keeps retained observations and legacy publication compatible."""
import copy
import gzip
import json
from pathlib import Path

import pytest

from app_payload_bank_history_asset import NAMESPACE as LEGACY, canonical, digest, encode_envelope as legacy_encode
from app_payload_bank_history_packed_asset import NAMESPACE, descriptor, decode_envelope
from app_payload_history_packed import pack, unpack
from app_payload_optional_assets import iter_payload_assets
from app_payload_revisions_state import bundle_sha256, validate_manifest, RevisionError
from tests.test_app_payload_bank_history_asset import real_bundle
from tests.test_app_payload_revisions import MemoryStore, publish


@pytest.mark.parametrize("encrypted", [False, True])
def test_both_formats_preserve_exact_observations_and_old_wire_bytes(tmp_path, monkeypatch, encrypted):
    import payload_crypto
    key = bytes(range(32)) if encrypted else None
    monkeypatch.setattr(payload_crypto, "resolve_key_from_env", lambda: key)
    manifest, catalogue, original = real_bundle(tmp_path, enc_key=key)
    assert "url" not in manifest[NAMESPACE]["file"]
    file = descriptor(manifest)
    raw = (tmp_path / file["name"]).read_bytes()
    wire = payload_crypto.decrypt_asset(raw, key) if key else raw
    assert decode_envelope(wire, run_date=manifest["run_date"], core_sha256=manifest["files"]["core"]["sha256"]) == catalogue
    old = legacy_encode(catalogue, run_date=manifest["run_date"], core_sha256=manifest["files"]["core"]["sha256"])
    assert (tmp_path / manifest[LEGACY]["file"]["name"]).read_bytes() == (payload_crypto.encrypt_asset(old, key) if key else old)
    assert original[LEGACY] == catalogue
    assert set(manifest["files"]) == {"core", "details"}
    validate_manifest(manifest, tmp_path)


def test_url_free_namespace_retains_old_client_bundle_preimage(tmp_path):
    from app_payload_bank_history_asset import retag_namespace
    manifest, _, _ = real_bundle(tmp_path)
    namespace = copy.deepcopy(manifest[NAMESPACE])
    identity = bundle_sha256(manifest)
    manifest["tag"] = f"app-payload-{manifest['run_date']}-r000001"
    retag_namespace(manifest, url=lambda name: f"https://github.com/{manifest['repo']}/releases/download/{manifest['tag']}/{name}")
    assert manifest[NAMESPACE] == namespace
    assert bundle_sha256(manifest) == identity
    assert f"/{manifest['tag']}/" in descriptor(manifest)["url"]
    # This is the shipped old app's preimage algorithm, which knows only LEGACY.
    value = {key: val for key, val in manifest.items() if key not in {"generated_at", "tag", "payload_revision", "files"}}
    value["files"] = {key: {k: v for k, v in entry.items() if k != "url"} for key, entry in manifest["files"].items()}
    value[LEGACY] = {**value[LEGACY], "file": {key: val for key, val in value[LEGACY]["file"].items() if key != "url"}}
    assert digest(canonical(value)) == identity


@pytest.mark.parametrize("fault", ["url", "name", "sha256", "bytes", "enc", "eager"])
def test_descriptor_rejects_untrusted_or_misplaced_assets(tmp_path, fault):
    manifest, _, _ = real_bundle(tmp_path)
    file = manifest[NAMESPACE]["file"]
    if fault == "eager":
        manifest["files"][NAMESPACE] = manifest.pop(NAMESPACE)["file"]
    else:
        file[fault] = {"url": "https://example.invalid/a", "name": "../a", "sha256": "x", "bytes": True, "enc": {}}[fault]
    with pytest.raises(ValueError):
        list(iter_payload_assets(manifest))


@pytest.mark.parametrize("fault", ["core_sha256", "run_date", "inner-sha", "inner-bytes"])
def test_packed_envelope_rejects_wrong_authority_or_corruption(tmp_path, fault):
    manifest, _, _ = real_bundle(tmp_path)
    value = json.loads(gzip.decompress((tmp_path / descriptor(manifest)["name"]).read_bytes()))
    if fault == "inner-sha": value["catalogue"]["sha256"] = "0" * 64
    elif fault == "inner-bytes": value["catalogue"]["bytes"] += 1
    elif fault == "core_sha256": value[fault] = "0" * 64
    else: value[fault] = "2026-01-01"
    with pytest.raises(ValueError):
        decode_envelope(gzip.compress(canonical(value), mtime=0), run_date=manifest["run_date"], core_sha256=manifest["files"]["core"]["sha256"])


@pytest.mark.parametrize("nodes", [[[0, "A"]], [0, [0, "gA"]], [0, [0, "g"]], [[0, ""], [1, 0, "A"]], [float("nan")], [10 ** 400]])
def test_malformed_dictionary_cannot_expand(nodes):
    with pytest.raises(ValueError):
        unpack({"format": "ar-history-dag-v1", "root": len(nodes) - 1, "nodes": nodes})


def test_dictionary_interns_repeated_values_and_handles_unicode_and_keys():
    value = {"schema_version": 2, "__proto__": {"constructor": "☀️😀"}, "repeated": [{"a": True, "b": None}] * 40}
    packed = pack(value)
    assert unpack(packed) == value
    assert len(packed["nodes"]) < 20
    assert pack(value) == packed


def test_language_interoperability_fixture_is_stable():
    fixture = json.loads((Path(__file__).parent / "fixtures/history-dag-v1-interoperability.json").read_text(encoding="utf-8"))
    assert pack(fixture["value"]) == fixture["packed"]
    assert unpack(fixture["packed"]) == fixture["value"]


def test_optional_decoded_budget_preserves_legacy_only(tmp_path, monkeypatch):
    import app_payload_bank_history_packed_asset as asset
    monkeypatch.setattr(asset, "INNER_JSON_MAX_BYTES", 1)
    manifest, _, _ = real_bundle(tmp_path)
    assert NAMESPACE not in manifest and LEGACY in manifest
    validate_manifest(manifest, tmp_path)


def test_optional_structural_budget_preserves_legacy_only(tmp_path, monkeypatch):
    import app_payload_history_packed as codec
    monkeypatch.setattr(codec, "MAX_NODES", 1)
    manifest, _, _ = real_bundle(tmp_path)
    assert NAMESPACE not in manifest and LEGACY in manifest
    validate_manifest(manifest, tmp_path)


def test_dictionary_rejects_exponential_logical_expansion():
    from app_payload_history_packed import _references, PackedBudgetError
    nodes = ["value"]
    for index in range(30):
        nodes.append([0, _references([index, index])])
    with pytest.raises(PackedBudgetError, match="expansion"):
        unpack({"format": "ar-history-dag-v1", "root": len(nodes) - 1, "nodes": nodes})


def test_optional_combined_budget_does_not_relax_legacy_limits(tmp_path, monkeypatch):
    import app_payload_network_budget as budget
    first, _, _ = real_bundle(tmp_path / "first")
    old_bytes = sum(entry["bytes"] for key, entry in iter_payload_assets(first) if key != NAMESPACE)
    monkeypatch.setattr(budget, "ROLLING_TOTAL_MAX_BYTES", old_bytes)
    manifest, _, _ = real_bundle(tmp_path / "second")
    assert NAMESPACE not in manifest and LEGACY in manifest
    validate_manifest(manifest, tmp_path / "second")


def test_interrupted_packed_upload_is_not_promoted_and_resumes(tmp_path):
    manifest, catalogue, _ = real_bundle(tmp_path / "payload")
    store = MemoryStore()
    store.fail_asset = manifest[NAMESPACE]["file"]["name"]
    with pytest.raises(RevisionError, match="interrupted upload"):
        publish(tmp_path, store)
    assert store.promotions == 0
    store.fail_asset = None
    result = publish(tmp_path, store)
    assert result.manifest[NAMESPACE] == manifest[NAMESPACE]
    assert result.head["bundle_sha256"] == bundle_sha256(manifest)
    file = descriptor(result.manifest)
    assert decode_envelope(store.read_url(file["url"]), run_date=manifest["run_date"], core_sha256=manifest["files"]["core"]["sha256"]) == catalogue


def test_legacy_publication_confirmation_includes_packed_identity(tmp_path):
    from pi_daily_sync import _same_payload_revision
    manifest, _, _ = real_bundle(tmp_path)
    changed = copy.deepcopy(manifest)
    changed[NAMESPACE]["file"]["bytes"] += 1
    assert not _same_payload_revision(manifest, changed)
    changed.pop(NAMESPACE)
    assert not _same_payload_revision(manifest, changed)


def test_are2_upload_and_readback_include_packed_asset(tmp_path, monkeypatch):
    from app_payload_secure_upload import secure_upload, decode_public_bytes
    from release_transport import MAGIC
    key = tmp_path / "private.key"
    key.write_text(bytes(range(32)).hex())
    monkeypatch.setenv("AR_LOCAL_PAYLOAD_KEY_FILE", str(key))
    manifest, _, _ = real_bundle(tmp_path / "payload")
    path = tmp_path / "payload" / descriptor(manifest)["name"]
    original = path.read_bytes()
    def uploaded(args, **kwargs):
        wire = Path(args[4]).read_bytes()
        assert wire.startswith(MAGIC)
        assert decode_public_bytes(wire, len(original), require_encrypted=True) == original
    secure_upload(["gh", "release", "upload", manifest["tag"], str(path)], runner=uploaded)
    assert path.read_bytes() == original
