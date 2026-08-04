from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from app_sample import build_app_sample


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
