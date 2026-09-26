from pathlib import Path

import pytest

from app_payload_network_budget import (
    CORE_MAX_BYTES,
    DETAILS_MAX_BYTES,
    validate_payload_network_budget,
    validate_v2_network_budget,
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


def test_complete_real_history_core_fits_with_existing_companion_assets() -> None:
    # Measured Sept26 core with all 134 published dates, both history schemas.
    # Companion sizes come from the same selected immutable public manifest.
    sizes = {"core": 2_718_749, "details": 2_821_488, "search_index": 671_293,
             "history_banks": 6_504, "bank_history": 20_594,
             "bank_spread_history": 17_169, "rba_calendar": 343}
    from release_transport import OVERHEAD
    manifest = {"files": {key: {"bytes": size + OVERHEAD} for key, size in sizes.items()}}
    report = validate_payload_network_budget(manifest, manifest_bytes=4_000)
    assert report["journeys"]["critical_core"]["bytes"] == sizes["core"] + OVERHEAD
    assert report["journeys"]["all_declared_assets"]["bytes"] == sum(sizes.values()) + len(sizes) * OVERHEAD


def test_total_budget_still_rejects_growth_even_when_each_asset_fits() -> None:
    with pytest.raises(ValueError, match="total bytes"):
        validate_payload_network_budget(_manifest(CORE_MAX_BYTES, DETAILS_MAX_BYTES), manifest_bytes=3_000)


def test_requires_declared_bytes_to_match_local_release_assets(tmp_path: Path) -> None:
    manifest = _manifest(core=4, details=5)
    (tmp_path / "core.gz").write_bytes(b"core")
    (tmp_path / "details.gz").write_bytes(b"wrong!")
    (tmp_path / "search.gz").write_bytes(b"search")
    with pytest.raises(ValueError, match="details local bytes"):
        validate_payload_network_budget(manifest, manifest_bytes=2_000, asset_root=tmp_path)


def test_v2_history_is_on_demand_but_still_has_a_transfer_time_budget() -> None:
    report = validate_v2_network_budget(
        {"files": {"product_history": {"name": "history.gz", "bytes": 125_000}}},
        manifest_bytes=1_200,
    )
    assert report["capabilities"]["product_history"]["seconds"]["1_mbps"] == 1.0
