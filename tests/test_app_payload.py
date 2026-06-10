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
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app_payload  # noqa: E402
import app_payload_mobile  # noqa: E402

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


def test_build_dates_index_sorted_and_bounded():
    index = app_payload.build_dates_index(
        ["2026-06-08", "2026-05-13", "2026-05-12", "bad"],
        min_date=app_payload.HISTORY_MIN_DATE,
    )
    assert index["dates"] == ["2026-05-13", "2026-06-08"]
    assert index["count"] == 2
    assert index["min_date"] == app_payload.HISTORY_MIN_DATE
    assert index["latest_date"] == "2026-06-08"
    assert "dates-index.json" in index["dates_index_url"]
    assert "{run_date}" in index["dated_manifest_url_pattern"]


def test_history_payload_discovers_sibling_run_exports(tmp_path):
    runs = tmp_path / "runs"
    current_exports = None
    for date, rate in (("2026-06-09", "0.04"), ("2026-06-10", "0.05")):
        exports = runs / date / "_exports"
        cache = exports / "dashboard-cache" / date
        cache.mkdir(parents=True)
        (cache / "banks.json").write_text(
            json.dumps(
                {
                    "rates": [
                        {
                            "dataset": "Savings",
                            "provider": "Bank",
                            "product_key": f"Bank|{date}",
                            "rate": rate,
                            "rate_family": "deposit",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        current_exports = exports

    history = app_payload_mobile.build_history_banks(
        current_exports,
        run_date="2026-06-10",
        load_json=app_payload._load_json,
        section_filter=app_payload.section_filter,
        normalized_rate_value=app_payload._normalized_rate_value,
    )

    assert history["run_dates"] == ["2026-06-09", "2026-06-10"]
    assert [point["date"] for point in history["sections"]["Savings"]["points"]] == history["run_dates"]


def test_dated_tag_naming():
    assert app_payload.dated_tag("2026-06-08") == "app-payload-2026-06-08"
    assert app_payload.is_dated_tag("app-payload-2026-06-08")
    assert not app_payload.is_dated_tag("app-payload-latest")
    assert not app_payload.is_dated_tag("app-payload-not-a-date")
    with pytest.raises(ValueError):
        app_payload.dated_tag("bad")


def test_is_rolling_tag():
    assert app_payload.is_rolling_tag("app-payload-latest")
    assert not app_payload.is_rolling_tag("app-payload-2026-06-08")


def test_optional_assets_are_rolling_only(tmp_path):
    kwargs = {
        "repo": app_payload.DEFAULT_REPO,
        "counts": {},
        "search_index": {"products": {"Bank|1": "bank product"}},
        "history_banks": {
            "sections": {
                "Savings": {
                    "points": [{"date": "2026-06-10", "min": 0.04, "max": 0.05}]
                }
            }
        },
    }
    rolling = app_payload._package(
        {"schema_version": 1},
        {"schema_version": 1},
        "2026-06-10",
        tmp_path / "rolling",
        tag=app_payload.DEFAULT_TAG,
        **kwargs,
    )
    dated = app_payload._package(
        {"schema_version": 1},
        {"schema_version": 1},
        "2026-06-10",
        tmp_path / "dated",
        tag=app_payload.dated_tag("2026-06-10"),
        **kwargs,
    )

    assert {"search_index", "history_banks"} <= rolling["files"].keys()
    assert set(dated["files"]) == {"core", "details"}


def test_dated_release_title():
    assert app_payload.dated_release_title("2026-06-08") == "Australian Rates payload — 2026-06-08"


def test_release_title_format():
    assert app_payload.release_title("2026-06-08") == "Australian Rates payload — latest (2026-06-08)"
    assert app_payload.release_title("2026-05-19") == "Australian Rates payload — latest (2026-05-19)"


def test_release_display_title():
    assert app_payload.release_display_title("app-payload-latest", "2026-06-08") == (
        "Australian Rates payload — latest (2026-06-08)"
    )
    assert app_payload.release_display_title("app-payload-2026-06-08", "2026-06-08") == (
        "Australian Rates payload — 2026-06-08"
    )


def test_manifest_should_replace_rolling_blocks_older_run_date():
    live = {"run_date": "2026-06-08", "generated_at": "2026-06-08T10:00:00Z"}
    ok, reason = app_payload._manifest_should_replace(
        "present",
        live,
        our_run_date="2026-06-07",
        our_gen="2026-06-07T10:00:00Z",
        tag="app-payload-latest",
        force=False,
    )
    assert not ok
    assert reason == "live_newer"


def test_manifest_should_replace_rolling_allows_newer_run_date():
    live = {"run_date": "2026-06-07", "generated_at": "2026-06-07T10:00:00Z"}
    ok, reason = app_payload._manifest_should_replace(
        "present",
        live,
        our_run_date="2026-06-08",
        our_gen="2026-06-08T10:00:00Z",
        tag="app-payload-latest",
        force=False,
    )
    assert ok
    assert reason == "ok"


def test_manifest_should_replace_dated_ignores_other_dates_on_rolling():
    """Dated tag guard only compares same-day generated_at, not cross-date rolling state."""
    live = {"run_date": "2026-06-08", "generated_at": "2026-06-08T10:00:00Z"}
    ok, reason = app_payload._manifest_should_replace(
        "present",
        live,
        our_run_date="2026-06-07",
        our_gen="2026-06-07T10:00:00Z",
        tag="app-payload-2026-06-07",
        force=False,
    )
    assert ok
    assert reason == "ok"


def test_manifest_should_replace_dated_blocks_same_day_correction_race():
    live = {"run_date": "2026-06-07", "generated_at": "2026-06-07T12:00:00Z"}
    ok, reason = app_payload._manifest_should_replace(
        "present",
        live,
        our_run_date="2026-06-07",
        our_gen="2026-06-07T10:00:00Z",
        tag="app-payload-2026-06-07",
        force=False,
    )
    assert not ok
    assert reason == "live_newer"


def test_update_release_title_calls_gh_release_edit(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr(app_payload.subprocess, "run", fake_run)
    ok = app_payload._update_release_title(
        "/usr/bin/gh", "yanniedog/AR-local", "app-payload-latest", "2026-06-08"
    )
    assert ok is True
    assert calls == [
        [
            "/usr/bin/gh",
            "release",
            "edit",
            "app-payload-latest",
            "--repo",
            "yanniedog/AR-local",
            "--title",
            "Australian Rates payload — latest (2026-06-08)",
        ]
    ]




def test_update_release_title_nonzero_exit(monkeypatch):
    def fake_run(cmd, **kwargs):
        class Result:
            returncode = 1
            stdout = ""
            stderr = "edit failed"

        return Result()

    monkeypatch.setattr(app_payload.subprocess, "run", fake_run)
    ok = app_payload._update_release_title(
        "/usr/bin/gh", "yanniedog/AR-local", "app-payload-latest", "2026-06-08"
    )
    assert ok is False


def test_update_release_title_exception(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise OSError("timeout")

    monkeypatch.setattr(app_payload.subprocess, "run", fake_run)
    ok = app_payload._update_release_title(
        "/usr/bin/gh", "yanniedog/AR-local", "app-payload-latest", "2026-06-08"
    )
    assert ok is False
def test_update_release_title_skips_blank_run_date():
    assert app_payload._update_release_title("/usr/bin/gh", "owner/repo", "tag", "") is False


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


def test_publish_dry_run_includes_optional_assets(tmp_path, monkeypatch, capsys):
    names = [
        "core.json.gz",
        "details.json.gz",
        "search-index.json.gz",
        "history-banks.json.gz",
    ]
    for name in names:
        (tmp_path / name).write_bytes(b"asset")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "run_date": "2026-06-10",
                "generated_at": "2026-06-10T00:00:00Z",
                "files": {
                    "core": {"name": names[0]},
                    "details": {"name": names[1]},
                    "search_index": {"name": names[2]},
                    "history_banks": {"name": names[3]},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(app_payload, "_gh_available", lambda: "gh")
    monkeypatch.setattr(app_payload, "_gh_authed", lambda _gh: True)

    assert app_payload.publish_payload(tmp_path, dry_run=True) is False

    output = capsys.readouterr().out
    assert "search-index.json.gz" in output
    assert "history-banks.json.gz" in output


def test_publish_protects_optional_assets_from_pruning(tmp_path, monkeypatch):
    names = ["core.json.gz", "details.json.gz", "search-index.json.gz", "history-banks.json.gz"]
    for name in names:
        (tmp_path / name).write_bytes(b"asset")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "run_date": "2026-06-10",
                "generated_at": "2026-06-10T00:00:00Z",
                "files": {
                    "core": {"name": names[0]},
                    "details": {"name": names[1]},
                    "search_index": {"name": names[2]},
                    "history_banks": {"name": names[3]},
                },
            }
        ),
        encoding="utf-8",
    )
    uploads = []
    protected = {}
    monkeypatch.setattr(app_payload, "_gh_available", lambda: "gh")
    monkeypatch.setattr(app_payload, "_gh_authed", lambda _gh: True)
    monkeypatch.setattr(app_payload, "_live_manifest_status", lambda _repo, _tag: ("missing", None))
    monkeypatch.setattr(app_payload, "_update_release_title", lambda *_args: True)
    monkeypatch.setattr(
        app_payload,
        "_prune_release_assets",
        lambda _gh, _repo, _tag, keep: protected.update(keep=keep) or 0,
    )

    def fake_run(args, **_kwargs):
        uploads.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(app_payload.subprocess, "run", fake_run)

    assert app_payload.publish_payload(tmp_path) is True
    assert protected["keep"] == set(names)
    assert any("history-banks.json.gz" in " ".join(command) for command in uploads)


@pytest.mark.skipif(not HAS_SAMPLE, reason="2026-05-19 sample export not present")
def test_publish_noop_without_token(tmp_path, monkeypatch):
    app_payload.build_payload(SAMPLE_EXPORTS, tmp_path)
    # Force the "no gh available" path -> publish is a clean no-op returning False.
    monkeypatch.setattr(app_payload, "_gh_available", lambda: None)
    assert app_payload.publish_payload(tmp_path) is False
