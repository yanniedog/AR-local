from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from app_sample import build_app_sample
import payload_crypto


def _write_source(root: Path) -> None:
    rows = [
        {
            "provider": "Bank A",
            "product_key": f"a-{index}",
            "product_name": f"A {index}",
            "rate": rate,
            "comparison_rate": rate,
        }
        for index, rate in enumerate(["0.0700", "0.0600", "0.0500"])
    ]
    rows.append({
        "provider": "Bank A",
        "product_key": "a-zero",
        "product_name": "Token rate",
        "rate": "0",
        "comparison_rate": "0",
    })
    core = {
        "schema_version": 1,
        "run_date": "2026-08-04",
        "sections": {
            "Mortgage": {"rates": rows, "ribbon": {}},
            "Savings": {"rates": rows, "ribbon": {}},
            "TD": {"rates": rows, "ribbon": {}},
        },
        "brands": {"Bank A": {"short": "A", "color": "#000000"}},
        "rba": [],
    }
    details = {
        "schema_version": 1,
        "run_date": "2026-08-04",
        "products": {
            f"a-{index}": {"fees": [], "features": [], "eligibility": [], "constraints": []}
            for index in range(3)
        },
    }
    files = {}
    for kind, value in (("core", core), ("details", details)):
        data = gzip.compress(json.dumps(value).encode())
        name = f"{kind}.json.gz"
        (root / name).write_bytes(data)
        files[kind] = {
            "name": name,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "url": f"https://example.invalid/{name}",
        }
    (root / "manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "run_date": "2026-08-04",
        "generated_at": "2026-08-04T00:00:00Z",
        "app_min_version": "1.0.0",
        "counts": {"failures": 2},
        "files": files,
    }))


def test_builds_small_self_contained_sample(tmp_path: Path) -> None:
    source = tmp_path / "source"
    output = tmp_path / "sample"
    source.mkdir()
    _write_source(source)

    manifest = build_app_sample(source, output)

    assert manifest["run_date"] == "2026-08-04"
    assert manifest["counts"]["rates"] == 6
    assert manifest["counts"]["providers"] == 1
    assert manifest["files"]["core"]["name"] == "core.json"
    assert manifest["files"]["details"]["name"] == "details.json"
    assert manifest["files"]["core"]["url"] == "bundled://sample/core.json"
    for kind in ("core", "details"):
        data = (output / f"{kind}.json").read_bytes()
        assert len(data) == manifest["files"][kind]["bytes"]
        assert hashlib.sha256(data).hexdigest() == manifest["files"][kind]["sha256"]
    core = json.loads((output / "core.json").read_text())
    assert [row["rate"] for row in core["sections"]["Mortgage"]["rates"]] == ["0.0500", "0.0600"]
    assert [row["rate"] for row in core["sections"]["Savings"]["rates"]] == ["0.0700", "0.0600"]


def test_normalizes_percent_rates_and_skips_invalid_fallbacks(tmp_path: Path) -> None:
    source = tmp_path / "source"
    output = tmp_path / "sample"
    source.mkdir()
    _write_source(source)
    manifest = json.loads((source / "manifest.json").read_text())
    core_path = source / manifest["files"]["core"]["name"]
    core = json.loads(gzip.decompress(core_path.read_bytes()))
    for section in core["sections"].values():
        section["rates"] = [
            {"provider": "Bank A", "product_key": "valid", "rate": "5.0", "comparison_rate": "0"},
            {"provider": "Bank A", "product_key": "zero", "rate": "0", "comparison_rate": "0"},
            {"provider": "Invalid Bank", "product_key": "invalid-zero", "rate": "0", "comparison_rate": "0"},
            {"provider": "Invalid Bank", "product_key": "invalid-text", "rate": "call us", "comparison_rate": None},
        ]
    compressed = gzip.compress(json.dumps(core).encode())
    core_path.write_bytes(compressed)
    manifest["files"]["core"].update(
        bytes=len(compressed), sha256=hashlib.sha256(compressed).hexdigest()
    )
    (source / "manifest.json").write_text(json.dumps(manifest))

    build_app_sample(source, output)

    sample = json.loads((output / "core.json").read_text())
    for section in sample["sections"].values():
        assert [row["product_key"] for row in section["rates"]] == ["valid"]
        assert section["ribbon"]["counts"] == {
            "rates": 1,
            "products": 1,
            "providers": 1,
        }
        assert section["ribbon"]["range"]["min"] == 0.05
        assert section["ribbon"]["providers"][0]["provider"] == "Bank A"


def test_decrypts_verified_encrypted_source_assets(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    output = tmp_path / "sample"
    source.mkdir()
    _write_source(source)
    manifest = json.loads((source / "manifest.json").read_text())
    key = bytes(range(32))
    key_path = tmp_path / "payload.key"
    key_path.write_text(key.hex())
    monkeypatch.setenv(payload_crypto.ENV_KEY_FILE, str(key_path))

    manifest["enc"] = {"alg": payload_crypto.ALG, "key_id": payload_crypto.key_id(key)}
    for entry in manifest["files"].values():
        path = source / entry["name"]
        encrypted = payload_crypto.encrypt_asset(path.read_bytes(), key)
        encrypted_path = path.with_suffix(path.suffix + ".enc")
        encrypted_path.write_bytes(encrypted)
        path.unlink()
        entry.update(
            name=encrypted_path.name,
            bytes=len(encrypted),
            sha256=hashlib.sha256(encrypted).hexdigest(),
            enc=manifest["enc"],
        )
    (source / "manifest.json").write_text(json.dumps(manifest))

    result = build_app_sample(source, output)

    assert result["counts"]["rates"] == 6
