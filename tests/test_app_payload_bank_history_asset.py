"""Core-bound lazy history, using retained real CDR rows and evidence."""
import copy
import gzip
import json
from pathlib import Path

import pytest

from app_payload_bank_history_asset import (
    NAMESPACE, canonical, decode_envelope, digest, retag_namespace,
)
from app_payload_build import _package
from app_payload_common import DEFAULT_TAG
from app_payload_optional_assets import iter_payload_assets
from app_payload_revisions import _preserve_alias
from app_payload_revisions_state import RevisionError, bundle_sha256, validate_manifest
from tests.test_app_payload_bank_catalogue import FIXTURE, packed
from tests.test_app_payload_revisions import MemoryStore, REPO, publish


def real_bundle(root, *, enc_key=None):
    observations = json.loads(FIXTURE.read_bytes())["observations"]
    observation = observations[-1]
    catalogue = packed(observations)
    core = {"schema_version": 1, "run_date": observation["date"],
            "sections": {key: {"rates": rows} for key, rows in observation["sections"].items()},
            "bank_rate_history": {"schema_version": 1}, NAMESPACE: catalogue}
    details = {"schema_version": 1, "run_date": observation["date"], "products": observation["details"]}
    manifest = _package(core, details, observation["date"], root, repo=REPO, tag=DEFAULT_TAG,
                        counts={}, enc_key=enc_key)
    return manifest, catalogue, core


@pytest.mark.parametrize("encrypted", [False, True])
def test_packaging_keeps_legacy_core_small_and_binds_optional_envelope(tmp_path, monkeypatch, encrypted):
    import payload_crypto
    key = bytes(range(32)) if encrypted else None
    monkeypatch.setattr(payload_crypto, "resolve_key_from_env", lambda: key)
    manifest, catalogue, original = real_bundle(tmp_path, enc_key=key)
    assert set(manifest["files"]) == {"core", "details"}
    entry = manifest[NAMESPACE]["file"]
    raw_core = (tmp_path / manifest["files"]["core"]["name"]).read_bytes()
    raw_history = (tmp_path / entry["name"]).read_bytes()
    assert manifest["files"]["core"]["bytes"] <= 512 * 1024
    assert digest(raw_history) == entry["sha256"] and len(raw_history) == entry["bytes"]
    core = json.loads(gzip.decompress(payload_crypto.decrypt_asset(raw_core, key) if key else raw_core))
    assert NAMESPACE not in core and "bank_rate_history" not in core
    assert original[NAMESPACE] == catalogue  # Wire projection does not mutate reducers' internal state.
    decoded = decode_envelope(payload_crypto.decrypt_asset(raw_history, key) if key else raw_history,
                              run_date=manifest["run_date"], core_sha256=manifest["files"]["core"]["sha256"])
    assert decoded == catalogue
    validate_manifest(manifest, tmp_path)
    assert list(dict(iter_payload_assets(manifest))) == ["core", "details", NAMESPACE]


@pytest.mark.parametrize("fault", ["core", "date", "sha", "bytes", "base64", "schema"])
def test_envelope_rejects_misbound_or_corrupt_archive(tmp_path, fault):
    manifest, _, _ = real_bundle(tmp_path)
    raw = (tmp_path / manifest[NAMESPACE]["file"]["name"]).read_bytes()
    value = json.loads(gzip.decompress(raw))
    if fault == "core": value["core_sha256"] = "0" * 64
    elif fault == "date": value["run_date"] = "2026-05-19"
    elif fault == "sha": value["catalogue"]["sha256"] = "0" * 64
    elif fault == "bytes": value["catalogue"]["bytes"] -= 1
    elif fault == "base64": value["catalogue"]["gzip_base64"] += "\n"
    else: value["schema_version"] = True
    with pytest.raises(ValueError):
        decode_envelope(gzip.compress(canonical(value), mtime=0), run_date=manifest["run_date"],
                        core_sha256=manifest["files"]["core"]["sha256"])


def test_archive_limits_are_enforced_before_expansion(tmp_path, monkeypatch):
    import app_payload_bank_history_asset as transport
    manifest, _, _ = real_bundle(tmp_path)
    raw = (tmp_path / manifest[NAMESPACE]["file"]["name"]).read_bytes()
    monkeypatch.setattr(transport, "INNER_JSON_MAX_BYTES", 1)
    with pytest.raises(ValueError, match="descriptor"):
        decode_envelope(raw, run_date=manifest["run_date"], core_sha256=manifest["files"]["core"]["sha256"])
    monkeypatch.setattr(transport, "OUTER_JSON_MAX_BYTES", 1)
    with pytest.raises(ValueError, match="budget"):
        decode_envelope(raw, run_date=manifest["run_date"], core_sha256=manifest["files"]["core"]["sha256"])


def test_optional_namespace_binds_identity_but_routing_does_not(tmp_path):
    manifest, _, _ = real_bundle(tmp_path)
    original = copy.deepcopy(manifest)
    before = bundle_sha256(manifest)
    manifest["tag"] = "app-payload-" + manifest["run_date"] + "-r000001"
    retag_namespace(manifest, url=lambda name: f"https://github.com/{REPO}/releases/download/{manifest['tag']}/{name}")
    assert bundle_sha256(manifest) == before and original[NAMESPACE] != manifest[NAMESPACE]
    manifest[NAMESPACE]["file"]["bytes"] += 1
    assert bundle_sha256(manifest) != before
    manifest[NAMESPACE]["file"]["url"] = "https://example.invalid/untrusted"
    with pytest.raises(ValueError, match="URL"):
        bundle_sha256(manifest)


def test_misplaced_namespace_cannot_be_eagerly_loaded(tmp_path):
    manifest, _, _ = real_bundle(tmp_path)
    manifest["files"][NAMESPACE] = manifest.pop(NAMESPACE)["file"]
    with pytest.raises(ValueError, match="outside legacy"):
        list(iter_payload_assets(manifest))


def test_interrupted_publication_never_selects_missing_history_and_resumes_exact_bytes(tmp_path):
    manifest, catalogue, _ = real_bundle(tmp_path / "payload")
    entry = manifest[NAMESPACE]["file"]
    store = MemoryStore()
    store.fail_asset = entry["name"]
    with pytest.raises(RevisionError, match="interrupted upload"):
        publish(tmp_path, store)
    assert store.promotions == 0 and (DEFAULT_TAG, "dates-index.json") not in store.objects
    store.fail_asset = None
    result = publish(tmp_path, store)
    adopted = result.manifest[NAMESPACE]["file"]
    assert adopted["sha256"] == entry["sha256"] and result.head["revision"] == 1
    assert adopted["url"] == store.url(result.manifest["tag"], entry["name"])
    assert bundle_sha256(result.manifest) == bundle_sha256(manifest)
    raw = store.read_url(adopted["url"])
    assert decode_envelope(raw, run_date=manifest["run_date"],
                           core_sha256=manifest["files"]["core"]["sha256"]) == catalogue
    again = publish(tmp_path, store)
    assert again.head == result.head and not again.index_changed


def test_preservation_retags_namespace_without_losing_original_receipt(tmp_path):
    manifest, _, _ = real_bundle(tmp_path / "payload")
    store = MemoryStore()
    store.objects[(DEFAULT_TAG, "manifest.json")] = canonical(manifest)
    for _, entry in iter_payload_assets(manifest):
        store.objects[(DEFAULT_TAG, entry["name"])] = (tmp_path / "payload" / entry["name"]).read_bytes()
    destination, original = _preserve_alias(store, DEFAULT_TAG, tmp_path / "state")
    archived = json.loads((destination / "manifest.json").read_bytes())
    assert (destination / "source-manifest.json").read_bytes() == canonical(manifest)
    assert original == manifest and bundle_sha256(archived) == bundle_sha256(manifest)
    assert archived[NAMESPACE]["file"]["url"] == store.url(archived["tag"], manifest[NAMESPACE]["file"]["name"])


def test_are2_upload_and_readback_include_optional_asset(tmp_path, monkeypatch):
    from app_payload_secure_upload import secure_upload, decode_public_bytes
    from release_transport import MAGIC
    key = tmp_path / "private.key"
    key.write_text(bytes(range(32)).hex())
    monkeypatch.setenv("AR_LOCAL_PAYLOAD_KEY_FILE", str(key))
    manifest, _, _ = real_bundle(tmp_path / "payload")
    path = tmp_path / "payload" / manifest[NAMESPACE]["file"]["name"]
    original = path.read_bytes()
    def uploaded(args, **kwargs):
        wire = Path(args[4]).read_bytes()
        assert wire.startswith(MAGIC)
        assert decode_public_bytes(wire, len(original), require_encrypted=True) == original
    secure_upload(["gh", "release", "upload", DEFAULT_TAG, str(path)], runner=uploaded)
    assert path.read_bytes() == original
