"""Schema tests for the mobile-app payload builder (app_payload.py).

These build the payload from the checked-in 2026-05-19 sample export when it is
present, and otherwise unit-test the pure helpers so the suite still runs in CI
environments without the large run artifacts.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app_payload  # noqa: E402

SAMPLE_EXPORTS = ROOT / "runs" / "2026-05-19" / "_exports"
HAS_SAMPLE = (SAMPLE_EXPORTS / "dashboard-cache" / "latest.json").exists()


# --------------------------------------------------------------------------- #
# Pure-helper unit tests (always run)
# --------------------------------------------------------------------------- #
def test_section_filter_mortgage_excludes_discount():
    assert app_payload.section_filter("Mortgage", {"rate": "0.05", "rate_family": "lending", "rate_type": "VARIABLE"})
    assert not app_payload.section_filter("Mortgage", {"rate": "0.05", "rate_family": "lending", "rate_type": "DISCOUNT"})
    assert not app_payload.section_filter("Mortgage", {"rate": "0.05", "rate_family": "deposit"})
    assert not app_payload.section_filter("Mortgage", {"rate": "", "rate_family": "lending"})


def test_section_filter_deposit():
    assert app_payload.section_filter("Savings", {"rate": "0.045", "rate_family": "deposit"})
    assert app_payload.section_filter("TD", {"rate": "0.05", "rate_family": "deposit"})
    assert not app_payload.section_filter("Savings", {"rate": "0.05", "rate_family": "lending"})


def test_aggregate_ribbon_stats():
    rows = [
        {"provider": "A", "product_key": "A|1", "rate": "0.04"},
        {"provider": "A", "product_key": "A|2", "rate": "0.06"},
        {"provider": "B", "product_key": "B|1", "rate": "0.05"},
    ]
    agg = app_payload.aggregate_ribbon(rows, "Savings")
    assert agg["counts"] == {"rates": 3, "products": 3, "providers": 2}
    assert agg["range"]["min"] == pytest.approx(0.04)
    assert agg["range"]["max"] == pytest.approx(0.06)
    assert agg["range"]["median"] == pytest.approx(0.05)
    assert agg["range"]["mean"] == pytest.approx(0.05)


def test_aggregate_ribbon_handles_percent_style():
    # A product whose raw rate is > 1 is treated as percent-style and divided by 100.
    rows = [{"provider": "A", "product_key": "A|1", "rate": "5.0"}]
    agg = app_payload.aggregate_ribbon(rows, "Savings")
    assert agg["range"]["min"] == pytest.approx(0.05)


def test_rba_series_parsed_from_dashboard_js():
    series = app_payload.load_rba_series(ROOT / "dashboard")
    assert series, "expected RBA entries parsed from dashboard/rba-cash-rate.js"
    assert all(set(e) == {"date", "rate"} for e in series)
    assert series == sorted(series, key=lambda e: e["date"]), "entries should be ascending by date"


def test_build_brands_shortcodes_and_color():
    brands = app_payload.build_brands(["Some New Bank"], {"some new bank": "SNB"})
    assert brands["Some New Bank"]["short"] == "SNB"
    assert brands["Some New Bank"]["color"].startswith("#")
    # deterministic colour
    assert brands["Some New Bank"]["color"] == app_payload.build_brands(["Some New Bank"], {})["Some New Bank"]["color"]


def test_load_brand_logos_embeds_available_png_and_skips_oversized(tmp_path):
    dashboard = tmp_path / "dashboard"
    logos = tmp_path / "banks"
    dashboard.mkdir()
    logos.mkdir()
    (dashboard / "ar-bank-brand.js").write_text(
        "'ANZ': {\n"
        "  short: 'ANZ',\n"
        "  icon: '/assets/banks/anz.png',\n"
        "  aliases: ['ANZ Bank'],\n"
        "},\n"
        "'Huge Bank': { short: 'Huge', icon: '/assets/banks/huge.png' },\n",
        encoding="utf-8",
    )
    (logos / "anz.png").write_bytes(b"\x89PNG\r\n\x1a\nsmall")
    (logos / "huge.png").write_bytes(b"x" * (app_payload.MAX_EMBEDDED_LOGO_BYTES + 1))

    loaded = app_payload.load_brand_logos(dashboard, logos)

    assert set(loaded) == {"anz", "anz bank"}
    assert loaded["anz"].startswith("data:image/png;base64,")
    brands = app_payload.build_brands(
        ["ANZ Bank Australia Limited", "No Logo Bank"],
        {"anz": "ANZ"},
        loaded,
    )
    assert brands["ANZ Bank Australia Limited"]["logo"] == loaded["anz"]
    assert brands["ANZ Bank Australia Limited"]["short"] == "ANZ"
    assert "logo" not in brands["No Logo Bank"]


def test_brand_lookup_normalization_is_centralized_and_first_wins():
    values = {}
    app_payload._put_brand_lookup(values, ["Bank of Melbourne"], "first")
    app_payload._put_brand_lookup(values, ["Melbourne Bank"], "second")

    assert app_payload._brand_lookup_keys("The Melbourne Bank Limited") == (
        "the melbourne bank limited",
        "melbourne",
    )
    assert app_payload._get_brand_lookup(values, "The Melbourne Bank Limited") == "first"


# --------------------------------------------------------------------------- #
# End-to-end build against the sample export (skipped when absent)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not HAS_SAMPLE, reason="2026-05-19 sample export not present")
def test_build_payload_end_to_end(tmp_path):
    manifest = app_payload.build_payload(SAMPLE_EXPORTS, tmp_path)

    assert manifest["schema_version"] == app_payload.SCHEMA_VERSION
    assert manifest["run_date"] == "2026-05-19"
    assert manifest["counts"]["products"] > 0

    # Manifest sha256/bytes match the files on disk, and URLs point at the tag.
    for key in ("core", "details"):
        entry = manifest["files"][key]
        blob = (tmp_path / entry["name"]).read_bytes()
        assert len(blob) == entry["bytes"]
        assert hashlib.sha256(blob).hexdigest() == entry["sha256"]
        assert entry["url"].endswith(entry["name"])
        assert app_payload.DEFAULT_TAG in entry["url"]

    core = json.loads(gzip.decompress((tmp_path / manifest["files"]["core"]["name"]).read_bytes()))
    assert set(core["sections"]) == set(app_payload.VALID_SECTIONS)
    for section in app_payload.VALID_SECTIONS:
        data = core["sections"][section]
        assert data["rates"], f"{section} should have rate rows"
        rng = data["ribbon"]["range"]
        assert rng["min"] is not None and rng["max"] is not None
        assert 0 < rng["min"] <= rng["max"] < 1, "rates should be normalized fractions"
        # every row carries the identity fields the app keys on
        for row in data["rates"][:50]:
            assert row.get("product_key") and row.get("provider") and row.get("rate")
    assert core["brands"], "brands map should be populated"
    assert core["rba"], "RBA series should be embedded"

    details = json.loads(gzip.decompress((tmp_path / manifest["files"]["details"]["name"]).read_bytes()))
    assert details["products"], "details should be keyed by product_key"
    sample_key = next(iter(details["products"]))
    entry = details["products"][sample_key]
    assert any(k in entry for k in ("fees", "features", "eligibility", "constraints", "description"))


@pytest.mark.skipif(not HAS_SAMPLE, reason="2026-05-19 sample export not present")
def test_build_is_deterministic(tmp_path):
    a = app_payload.build_payload(SAMPLE_EXPORTS, tmp_path / "a")
    b = app_payload.build_payload(SAMPLE_EXPORTS, tmp_path / "b")
    # gzip mtime is pinned to 0, so identical input yields identical core bytes.
    assert a["files"]["core"]["sha256"] == b["files"]["core"]["sha256"]
    assert a["files"]["details"]["sha256"] == b["files"]["details"]["sha256"]


@pytest.mark.skipif(not HAS_SAMPLE, reason="2026-05-19 sample export not present")
def test_publish_noop_without_token(tmp_path, monkeypatch):
    app_payload.build_payload(SAMPLE_EXPORTS, tmp_path)
    # Force the "no gh available" path -> publish is a clean no-op returning False.
    monkeypatch.setattr(app_payload, "_gh_available", lambda: None)
    assert app_payload.publish_payload(tmp_path) is False
