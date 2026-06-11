"""Tests for payload_crypto and its app_payload integration (Phase A)."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

cryptography = pytest.importorskip("cryptography")

import app_payload
import payload_crypto

KEY = bytes(range(32))


def test_round_trip() -> None:
    plain = gzip.compress(b'{"hello":"world"}')
    blob = payload_crypto.encrypt_asset(plain, KEY)
    assert blob[:4] == payload_crypto.MAGIC
    assert payload_crypto.decrypt_asset(blob, KEY) == plain


def test_deterministic_for_identical_input() -> None:
    plain = b"same-day rebuild must stay content-addressable"
    assert payload_crypto.encrypt_asset(plain, KEY) == payload_crypto.encrypt_asset(plain, KEY)


def test_distinct_plaintexts_get_distinct_nonces() -> None:
    a = payload_crypto.encrypt_asset(b"payload-a", KEY)
    b = payload_crypto.encrypt_asset(b"payload-b", KEY)
    assert a[4:16] != b[4:16]


def test_wrong_key_fails() -> None:
    blob = payload_crypto.encrypt_asset(b"secret", KEY)
    with pytest.raises(Exception):
        payload_crypto.decrypt_asset(blob, bytes(32))


def test_rejects_non_encrypted_blob() -> None:
    with pytest.raises(ValueError):
        payload_crypto.decrypt_asset(b"plainbytes", KEY)


def test_load_key_validates_length(tmp_path: Path) -> None:
    short = tmp_path / "short.key"
    short.write_text("abcd", encoding="utf-8")
    with pytest.raises(ValueError):
        payload_crypto.load_key(short)
    good = tmp_path / "good.key"
    good.write_text(KEY.hex() + "\n", encoding="utf-8")
    assert payload_crypto.load_key(good) == KEY


def test_resolve_key_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(payload_crypto.ENV_FLAG, raising=False)
    assert payload_crypto.resolve_key_from_env() is None
    key_file = tmp_path / "payload.key"
    key_file.write_text(KEY.hex(), encoding="utf-8")
    monkeypatch.setenv(payload_crypto.ENV_FLAG, "1")
    monkeypatch.setenv(payload_crypto.ENV_KEY_FILE, str(key_file))
    assert payload_crypto.resolve_key_from_env() == KEY


def test_package_encrypts_assets_and_marks_manifest(tmp_path: Path) -> None:
    core = {"schema_version": 1, "run_date": "2026-06-11", "sections": {}}
    details = {"schema_version": 1, "run_date": "2026-06-11", "products": {}}
    manifest = app_payload._package(
        core,
        details,
        "2026-06-11",
        tmp_path,
        repo="o/r",
        tag="app-payload-latest",
        counts={},
        enc_key=KEY,
    )
    assert manifest["enc"]["alg"] == "aes-256-gcm"
    assert manifest["enc"]["key_id"] == payload_crypto.key_id(KEY)
    core_entry = manifest["files"]["core"]
    assert core_entry["name"].endswith(".json.gz.enc")
    assert core_entry["enc"]["alg"] == "aes-256-gcm"
    blob = (tmp_path / core_entry["name"]).read_bytes()
    assert blob[:4] == payload_crypto.MAGIC  # ciphertext on disk, not gzip
    decrypted = json.loads(gzip.decompress(payload_crypto.decrypt_asset(blob, KEY)))
    assert decrypted == core


def test_package_stays_plaintext_without_key(tmp_path: Path) -> None:
    core = {"schema_version": 1, "run_date": "2026-06-11", "sections": {}}
    details = {"schema_version": 1, "run_date": "2026-06-11", "products": {}}
    manifest = app_payload._package(
        core, details, "2026-06-11", tmp_path, repo="o/r", tag="app-payload-latest", counts={}
    )
    assert "enc" not in manifest
    name = manifest["files"]["core"]["name"]
    assert name.endswith(".json.gz")
    assert gzip.decompress((tmp_path / name).read_bytes())
