from pathlib import Path

import pytest

from app_payload_network_budget import (
    CORE_MAX_BYTES,
    DETAILS_MAX_BYTES,
    validate_payload_network_budget,
)


def _manifest(core: int = 240_000, details: int = 3_250_000) -> dict:
    return {
        "files": {
            "core": {"name": "core.gz", "bytes": core},
            "details": {"name": "details.gz", "bytes": details},
            "search_index": {"name": "search.gz", "bytes": 800_000},
        }
    }


def test_reports_slow_network_time_for_each_user_journey() -> None:
    report = validate_payload_network_budget(_manifest(), manifest_bytes=3_000)
    assert report["journeys"]["critical_core"]["seconds"]["1_mbps"] == 1.92
    assert report["journeys"]["current_standard_home"]["seconds"]["1_mbps"] == 27.92
    assert report["journeys"]["deep_search"]["seconds"]["0.5_mbps"] == 68.64


@pytest.mark.parametrize(
    ("key", "size", "message"),
    (("core", CORE_MAX_BYTES + 1, "core bytes"), ("details", DETAILS_MAX_BYTES + 1, "details bytes")),
)
def test_rejects_payload_growth_past_compressed_byte_budget(key: str, size: int, message: str) -> None:
    manifest = _manifest()
    manifest["files"][key]["bytes"] = size
    with pytest.raises(ValueError, match=message):
        validate_payload_network_budget(manifest, manifest_bytes=3_000)


def test_requires_declared_bytes_to_match_local_release_assets(tmp_path: Path) -> None:
    manifest = _manifest(core=4, details=5)
    (tmp_path / "core.gz").write_bytes(b"core")
    (tmp_path / "details.gz").write_bytes(b"wrong!")
    (tmp_path / "search.gz").write_bytes(b"search")
    with pytest.raises(ValueError, match="details local bytes"):
        validate_payload_network_budget(manifest, manifest_bytes=2_000, asset_root=tmp_path)

