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


def _write_history_day(runs, date, rows):
    exports = runs / date / "_exports"
    cache = exports / "dashboard-cache" / date
    cache.mkdir(parents=True)
    (cache / "banks.json").write_text(json.dumps({"rates": rows}), encoding="utf-8")
    return exports


def _history_assets_from(exports, run_date):
    return app_payload_mobile.build_history_assets(
        exports,
        run_date=run_date,
        load_json=app_payload._load_json,
        section_filter=app_payload.section_filter,
        normalized_rate_value=app_payload._normalized_rate_value,
    )


def test_build_history_assets_bank_series_and_events(tmp_path):
    runs = tmp_path / "runs"

    def savings(provider, key, rate):
        return {
            "dataset": "Savings",
            "provider": provider,
            "product_key": key,
            "rate": rate,
            "rate_family": "deposit",
        }

    _write_history_day(
        runs, "2026-06-08", [savings("Alpha", "A|1", "0.0500"), savings("Beta", "B|1", "0.0400")]
    )
    # Alpha cuts its only product by 25 bps; Beta drops out for a day.
    _write_history_day(runs, "2026-06-09", [savings("Alpha", "A|1", "0.0475")])
    exports = _write_history_day(
        runs, "2026-06-10", [savings("Alpha", "A|1", "0.0475"), savings("Beta", "B|1", "0.0450")]
    )

    history, bank_history = _history_assets_from(exports, "2026-06-10")

    # Section aggregate asset is unchanged by the combined pass.
    assert history["run_dates"] == ["2026-06-08", "2026-06-09", "2026-06-10"]
    assert [p["date"] for p in history["sections"]["Savings"]["points"]] == history["run_dates"]

    assert bank_history["run_dates"] == history["run_dates"]
    alpha = bank_history["banks"]["Alpha"]["Savings"]
    assert alpha["best"] == [pytest.approx(0.05), pytest.approx(0.0475), pytest.approx(0.0475)]
    assert alpha["median"] == alpha["best"]  # single product
    assert alpha["count"] == [1, 1, 1]
    beta = bank_history["banks"]["Beta"]["Savings"]
    assert beta["best"] == [pytest.approx(0.04), None, pytest.approx(0.045)]
    assert beta["count"] == [1, None, 1]

    # One event: Alpha's matched-product cut. Beta has no baseline after its gap.
    assert bank_history["events"] == [
        {
            "date": "2026-06-09",
            "provider": "Alpha",
            "section": "Savings",
            "dir": "cut",
            "moved": 1,
            "total": 1,
            "avg_bps": -25.0,
        }
    ]


def test_build_history_assets_event_direction_and_threshold(tmp_path):
    runs = tmp_path / "runs"

    def loan(provider, key, rate):
        return {
            "dataset": "Mortgage",
            "provider": provider,
            "product_key": key,
            "rate": rate,
            "rate_family": "lending",
            "rate_type": "VARIABLE",
        }

    _write_history_day(
        runs,
        "2026-06-09",
        [loan("Gamma", "G|1", "0.0600"), loan("Gamma", "G|2", "0.0650"), loan("Gamma", "G|3", "0.0700")],
    )
    # G|1 +25 bps, G|2 -25 bps, G|3 +0.1 bp (below the 5 bps threshold -> ignored).
    exports = _write_history_day(
        runs,
        "2026-06-10",
        [loan("Gamma", "G|1", "0.0625"), loan("Gamma", "G|2", "0.0625"), loan("Gamma", "G|3", "0.07001")],
    )

    _history, bank_history = _history_assets_from(exports, "2026-06-10")

    assert len(bank_history["events"]) == 1
    event = bank_history["events"][0]
    assert event["dir"] == "mixed"
    assert event["moved"] == 2
    assert event["total"] == 3
    assert event["avg_bps"] == pytest.approx(0.0)
    # Mortgage best is the lowest advertised rate.
    gamma = bank_history["banks"]["Gamma"]["Mortgage"]
    assert gamma["best"] == [pytest.approx(0.06), pytest.approx(0.0625)]
    assert gamma["count"] == [3, 3]


def test_dated_tag_naming():
    assert app_payload.dated_tag("2026-06-08") == "app-payload-2026-06-08"
    assert app_payload.is_dated_tag("app-payload-2026-06-08")
    assert not app_payload.is_dated_tag("app-payload-latest")
    assert not app_payload.is_dated_tag("app-payload-not-a-date")
    with pytest.raises(ValueError):
        app_payload.dated_tag("bad")


def test_published_history_dates_derives_from_tags_without_per_release_fetch(monkeypatch):
    # The dates index is built from the dated tag names alone (one tag-list call),
    # not a manifest GET per dated release (the former N+1).
    monkeypatch.setattr(app_payload, "_gh_available", lambda: "gh")
    monkeypatch.setattr(app_payload, "_gh_authed", lambda gh: True)
    monkeypatch.setattr(
        app_payload,
        "_list_payload_release_tags",
        lambda gh, repo: [
            "app-payload-latest",            # rolling -> ignored
            "app-payload-2026-05-19",
            "app-payload-2026-05-13",
            "app-payload-2026-05-12",        # before min_date -> filtered
            "app-payload-not-a-date",        # not a dated tag -> ignored
        ],
    )
    fetches = {"n": 0}

    def fail_on_fetch(*args, **kwargs):
        fetches["n"] += 1
        return ("present", {})

    monkeypatch.setattr(app_payload, "_live_manifest_status", fail_on_fetch)

    dates = app_payload._published_history_dates("yanniedog/AR-local", min_date="2026-05-13")
    assert dates == ["2026-05-13", "2026-05-19"]
    assert fetches["n"] == 0  # no per-release manifest GET


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
        "bank_history": {
            "run_dates": ["2026-06-10"],
            "banks": {"Bank": {"Savings": {"median": [0.04], "best": [0.05], "count": [2]}}},
            "events": [],
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

    assert {"search_index", "history_banks", "bank_history"} <= rolling["files"].keys()
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


@pytest.mark.skipif(not HAS_SAMPLE, reason="2026-05-19 sample export not present")
def test_build_and_publish_dual_computes_payload_once(tmp_path, monkeypatch):
    import shutil

    # Copy the sample so the rolling build (writes into <exports>/app-payload-latest)
    # doesn't pollute the committed fixture.
    exports = tmp_path / "exports"
    shutil.copytree(SAMPLE_EXPORTS, exports)

    calls = {"n": 0}
    real_compute = app_payload._compute_payload

    def counting_compute(*args, **kwargs):
        calls["n"] += 1
        return real_compute(*args, **kwargs)

    monkeypatch.setattr(app_payload, "_compute_payload", counting_compute)
    monkeypatch.setattr(app_payload, "publish_payload", lambda *a, **k: True)
    monkeypatch.setattr(app_payload, "_live_manifest_status", lambda *a, **k: ("absent", None))

    manifest, pub_dated, pub_latest = app_payload.build_and_publish_dual(
        exports, out_dir=tmp_path / "dated"
    )

    # The expensive parse + history scan runs ONCE for both releases, not twice.
    assert calls["n"] == 1
    assert pub_dated is True and pub_latest is True

    dated_manifest = json.loads((tmp_path / "dated" / "manifest.json").read_text())
    latest_manifest = json.loads((exports / "app-payload-latest" / "manifest.json").read_text())
    assert app_payload.dated_tag(manifest["run_date"]) in dated_manifest["files"]["core"]["url"]
    assert app_payload.DEFAULT_TAG in latest_manifest["files"]["core"]["url"]
    # Same precomputed data -> byte-identical core across both releases.
    assert dated_manifest["files"]["core"]["sha256"] == latest_manifest["files"]["core"]["sha256"]


@pytest.mark.skipif(not HAS_SAMPLE, reason="2026-05-19 sample export not present")
def test_build_and_publish_dual_dated_only_skips_rolling(tmp_path, monkeypatch):
    import shutil

    exports = tmp_path / "exports"
    shutil.copytree(SAMPLE_EXPORTS, exports)

    calls = {"n": 0}
    real_compute = app_payload._compute_payload

    def counting_compute(*args, **kwargs):
        calls["n"] += 1
        return real_compute(*args, **kwargs)

    monkeypatch.setattr(app_payload, "_compute_payload", counting_compute)
    monkeypatch.setattr(app_payload, "publish_payload", lambda *a, **k: True)

    manifest, pub_dated, pub_latest = app_payload.build_and_publish_dual(
        exports, out_dir=tmp_path / "dated", update_latest=False
    )

    # Still computes exactly once; no rolling release is built or published.
    assert calls["n"] == 1
    assert pub_dated is True and pub_latest is False
    assert not (exports / "app-payload-latest").exists()
    dated_manifest = json.loads((tmp_path / "dated" / "manifest.json").read_text())
    assert app_payload.dated_tag(manifest["run_date"]) in dated_manifest["files"]["core"]["url"]


def test_package_payload_same_data_packages_both_tags(tmp_path):
    # CI-runnable (no sample/network): proves the compute-once contract — one
    # precomputed payload packages into both the dated and rolling releases with
    # byte-identical core, differing only by the tag in the asset URL.
    run_date = "2026-05-19"
    data = {
        "core": {"schema_version": app_payload.SCHEMA_VERSION, "run_date": run_date, "sections": {}, "brands": {}, "rba": {}},
        "details": {"schema_version": app_payload.SCHEMA_VERSION, "run_date": run_date, "products": {}},
        "run_date": run_date,
        "counts": {"products": 0},
        "search_index": None,
        "history_banks": None,
        "bank_history": None,
    }
    import copy

    original = copy.deepcopy(data)
    dated_tag = app_payload.dated_tag(run_date)
    dated = app_payload._package_payload(data, tmp_path / "dated", tag=dated_tag)
    latest = app_payload._package_payload(data, tmp_path / "latest", tag=app_payload.DEFAULT_TAG)

    # Packaging must not mutate the shared precomputed data (reused across tags).
    assert data == original
    assert dated["files"]["core"]["sha256"] == latest["files"]["core"]["sha256"]
    assert dated_tag in dated["files"]["core"]["url"]
    assert app_payload.DEFAULT_TAG in latest["files"]["core"]["url"]


def test_publish_dry_run_includes_optional_assets(tmp_path, monkeypatch, capsys):
    names = [
        "core.json.gz",
        "details.json.gz",
        "search-index.json.gz",
        "history-banks.json.gz",
        "bank-history.json.gz",
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
                    "bank_history": {"name": names[4]},
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
    assert "bank-history.json.gz" in output


def test_publish_protects_optional_assets_from_pruning(tmp_path, monkeypatch):
    names = [
        "core.json.gz",
        "details.json.gz",
        "search-index.json.gz",
        "history-banks.json.gz",
        "bank-history.json.gz",
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
                    "bank_history": {"name": names[4]},
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
    assert any("bank-history.json.gz" in " ".join(command) for command in uploads)


def test_prune_release_assets_covers_bank_history_prefix(monkeypatch):
    # 49 content-addressed bank-history assets, oldest first; keep window is 48.
    rows = [
        (f"bank-history-2026-04-{i + 1:02d}-{i:012d}.json.gz", f"2026-04-{i + 1:02d}T00:00:00Z")
        for i in range(49)
    ]
    listing = "\n".join(f"{name}\t{created}" for name, created in rows)
    deletes = []

    def fake_run(args, **_kwargs):
        if "view" in args:
            return SimpleNamespace(returncode=0, stdout=listing, stderr="")
        deletes.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(app_payload.subprocess, "run", fake_run)

    deleted = app_payload._prune_release_assets("gh", "owner/repo", "app-payload-latest", set())

    assert deleted == 1
    assert any(rows[0][0] in command for command in deletes), "oldest bank-history asset pruned"


@pytest.mark.skipif(not HAS_SAMPLE, reason="2026-05-19 sample export not present")
def test_publish_noop_without_token(tmp_path, monkeypatch):
    app_payload.build_payload(SAMPLE_EXPORTS, tmp_path)
    # Force the "no gh available" path -> publish is a clean no-op returning False.
    monkeypatch.setattr(app_payload, "_gh_available", lambda: None)
    assert app_payload.publish_payload(tmp_path) is False


# --- ongoing/base-rate join (rate-honesty disclosure) ----------------------- #
def test_attach_ongoing_rate_savings_matches_balance_tier():
    section = [
        {"product_key": "P", "rate": "0.05", "ribbon_deposit_kind": "bonus",
         "balance_min": "0", "balance_max": "250000"},
        {"product_key": "P", "rate": "0.01", "ribbon_deposit_kind": "base",
         "balance_min": "0", "balance_max": "250000"},
    ]
    comp = [dict(r) for r in section]
    app_payload.attach_ongoing_rates(section, comp, "Savings")
    assert comp[0]["ongoing_rate"] == "0.01"
    assert "ongoing_rate" not in comp[1]  # the base row itself is unannotated


def test_attach_ongoing_rate_td_requires_same_term():
    # A 12-month bonus whose product only publishes a 6-month base must NOT
    # borrow that base — it is not this offer's reversion rate.
    section = [
        {"product_key": "T", "rate": "0.052", "ribbon_rate_structure": "bonus", "term_months": 12},
        {"product_key": "T", "rate": "0.028", "ribbon_rate_structure": "base", "term_months": 6},
    ]
    comp = [dict(r) for r in section]
    app_payload.attach_ongoing_rates(section, comp, "TD")
    assert "ongoing_rate" not in comp[0]


def test_attach_ongoing_rate_tolerates_unparseable_balance_max():
    section = [
        {"product_key": "S", "rate": "0.05", "ribbon_deposit_kind": "bonus",
         "balance_min": "0", "balance_max": "unlimited"},
        {"product_key": "S", "rate": "0.01", "ribbon_deposit_kind": "base",
         "balance_min": "50000", "balance_max": "N/A"},
    ]
    comp = [dict(r) for r in section]
    app_payload.attach_ongoing_rates(section, comp, "Savings")  # must not raise
    assert comp[0]["ongoing_rate"] == "0.01"


def test_attach_ongoing_rate_leaves_mortgages_untouched():
    section = [{"product_key": "M", "rate": "0.06", "ribbon_rate_structure": "variable"}]
    comp = [dict(r) for r in section]
    app_payload.attach_ongoing_rates(section, comp, "Mortgage")
    assert "ongoing_rate" not in comp[0]


def test_aggregate_ribbon_prefers_comparison_rate():
    rows = [
        {"product_key": "A", "provider": "X", "rate": "0.05", "comparison_rate": "0.055"},
        {"product_key": "B", "provider": "Y", "rate": "0.06", "comparison_rate": "0.061"},
    ]
    ribbon = app_payload.aggregate_ribbon(rows, "Mortgage")
    # Range is computed on the comparison rates, not the headline rates.
    assert round(ribbon["range"]["min"], 4) == 0.055
    assert round(ribbon["range"]["max"], 4) == 0.061


def test_ribbon_kernel_is_shared_with_dashboard_server():
    # Single source of truth: both the payload builder and the dashboard server
    # must use the same callable, so web and mobile can never diverge on the ribbon
    # rate metric. Guard against a future re-inlining of either copy.
    import cdr_ribbon_normalize
    import cdr_dashboard_server

    assert app_payload.aggregate_ribbon is cdr_ribbon_normalize.aggregate_ribbon
    # The dashboard server binds the same kernel at import; if it ever re-inlined
    # its own ribbon aggregate, this assertion (the bug this PR fixes) would fail.
    assert cdr_dashboard_server.aggregate_ribbon is cdr_ribbon_normalize.aggregate_ribbon


def test_aggregate_ribbon_empty_comparison_falls_back_to_headline():
    # The dashboard server projects comparison_rate as '' on legacy DBs that lack
    # the column, and deposits carry no comparison rate at all. Non-positive and
    # non-parsable comparison rates must also fall back to the headline rate, never
    # dropping the product from the ribbon.
    rows = [
        {"product_key": "A", "provider": "X", "rate": "4.5", "comparison_rate": ""},
        {"product_key": "B", "provider": "Y", "rate": "5.0", "comparison_rate": None},
        {"product_key": "C", "provider": "Z", "rate": "4.0", "comparison_rate": "0"},
        {"product_key": "D", "provider": "W", "rate": "4.2", "comparison_rate": "-1"},
        {"product_key": "E", "provider": "V", "rate": "4.8", "comparison_rate": "foo"},
    ]
    ribbon = app_payload.aggregate_ribbon(rows, "Savings")
    assert ribbon["counts"]["rates"] == 5  # none dropped
    assert round(ribbon["range"]["min"], 4) == 0.04  # C: 4.0 headline (comparison "0")
    assert round(ribbon["range"]["max"], 4) == 0.05  # B: 5.0 headline (comparison None)


def test_compact_history_reshapes_per_day_aggregates():
    import cdr_ribbon_normalize as crn

    d1, d2 = "2026-06-10", "2026-06-11"
    aggs = {
        d1: crn.aggregate_ribbon(
            [
                {"product_key": "A", "provider": "X", "rate": "5.0"},
                {"product_key": "B", "provider": "Y", "rate": "4.0"},
            ],
            "Savings",
        ),
        d2: crn.aggregate_ribbon(
            [{"product_key": "A", "provider": "X", "rate": "5.5"}],
            "Savings",
        ),
    }
    # A gap day (d3) with no aggregate must carry nulls, keeping the series aligned.
    out = crn.compact_history([d1, d2, "2026-06-12"], aggs)
    assert out["run_dates"] == [d1, d2, "2026-06-12"]
    assert [p["date"] for p in out["points"]] == [d1, d2, "2026-06-12"]
    assert round(out["points"][0]["max"], 4) == 0.05  # d1 overall max = 5.0%
    assert out["points"][2]["min"] is None and out["points"][2]["count"] == 0  # gap day
    provider_x = next(p for p in out["providers"] if p["provider"] == "X")
    assert set(provider_x["by_date"]) == {d1, d2}  # X present both days, not the gap
    assert round(provider_x["by_date"][d2]["median"], 4) == 0.055
    # Compact: a handful of points/providers, never the raw per-product rows.
    assert "rates" not in out


def test_compact_history_field_contract_matches_dashboard_client():
    # dashboard/app.js compactChartItems() reads these exact fields off the
    # compact payload to build the chart model; lock them so a server-side reshape
    # change can't silently break the client (which has no JS test harness).
    import cdr_ribbon_normalize as crn

    d1, d2 = "2026-06-10", "2026-06-11"
    aggs = {
        d1: crn.aggregate_ribbon(
            [
                {"product_key": "A", "provider": "X", "rate": "5.0", "comparison_rate": "5.1"},
                {"product_key": "B", "provider": "Y", "rate": "4.0"},
            ],
            "Mortgage",
        ),
        d2: crn.aggregate_ribbon(
            [{"product_key": "A", "provider": "X", "rate": "5.5", "comparison_rate": "5.6"}],
            "Mortgage",
        ),
    }
    out = crn.compact_history([d1, d2], aggs)
    assert set(out) >= {"run_dates", "points", "providers"}
    point_fields = {"date", "min", "max", "mean", "median", "count"}
    for point in out["points"]:
        assert set(point) == point_fields
    stat_fields = {"min", "max", "mean", "median", "count"}
    for provider in out["providers"]:
        assert set(provider) == {"provider", "by_date"}
        for stats in provider["by_date"].values():
            assert set(stats) == stat_fields


def test_history_index_key_matches_dashboard_contract():
    import cdr_dashboard_server as srv

    row = {"provider": "X", "product_key": "P1", "rate": "5.0", "lvr_tier": "70_80"}
    key = srv.history_index_key(row)
    # Joined with the same  separator the dashboard's historyIndexKey uses.
    assert "" in key
    # Rate is intentionally excluded from identity, so two samples of the same
    # product at different rates share a key (a product's history is one series).
    assert srv.history_index_key({**row, "rate": "9.9"}) == key
    # A different product key is a different identity (current-catalogue filtering).
    assert srv.history_index_key({**row, "product_key": "P2"}) != key
