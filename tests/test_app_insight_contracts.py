"""Contract tests; optional integrations consume existing real run artifacts only."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest

import app_payload_contracts
import app_payload_build
import app_payload_v2
import cdr_clean_export
import pi_daily_sync

ROOT = Path(__file__).resolve().parents[1]
REAL_EXPORTS = Path(os.environ["AR_LOCAL_REAL_EXPORTS"]) if os.environ.get("AR_LOCAL_REAL_EXPORTS") else None
REAL_MACRO_STORE = (
    Path(os.environ["AR_LOCAL_REAL_MACRO_STORE"])
    if os.environ.get("AR_LOCAL_REAL_MACRO_STORE")
    else None
)


def test_official_product_links_preserve_only_allowlisted_https_metadata():
    # Captured from the real 2026-05-19 AMP Essential Home Loan CDR response.
    record = {
        "additionalInformation": {
            "overviewUri": "https://www.amp.com.au/home-loans/interest-rates-fees",
            "termsUri": "https://www.amp.com.au/bankterms",
            "feesAndPricingUri": (
                "https://www.amp.com.au/content/dam/amp/digitalhub/common/Documents/"
                "HomeLoans/Forms/308006_Home_Loan_Fees_and_Charges_Guide.pdf"
            ),
            "applicationUri": "https://www.amp.com.au/apply",
        }
    }
    cleaned = json.loads(cdr_clean_export.detail_json(record))
    assert set(cleaned["additionalInformation"]) == {
        "overviewUri",
        "termsUri",
        "feesAndPricingUri",
    }
    assert "applicationUri" not in cleaned["additionalInformation"]


def test_official_product_links_reject_non_https_and_credentials():
    record = {
        "additionalInformation": {
            "overviewUri": "http://example.test/product",
            "termsUri": "https://user:secret@example.test/terms",
        }
    }
    assert cdr_clean_export.official_product_links(record) == {}


def test_runtime_contract_validators_reject_ambiguous_or_unbound_payloads():
    with pytest.raises(ValueError, match="standard cohort"):
        app_payload_contracts.validate_product_history(
            {"schema_version": 2, "run_dates": [], "products": {}, "cohort": {"id": "all"}}
        )
    with pytest.raises(ValueError, match="bind core and details"):
        app_payload_contracts.validate_v2_manifest(
            {"schema_version": 2, "base": {}, "files": {"product_history": {}}}
        )


def test_standard_history_filter_never_admits_non_standard_rates():
    # Captured from the real 2026-05-19 AMP and Darling Downs Bank export rows.
    standard = {
        "dataset": "Mortgage",
        "provider": "AMP - My AMP",
        "product_id": "AMP_ESSENTIAL_HL",
        "product_key": (
            "AMP - My AMP|AMP_ESSENTIAL_HL|RESIDENTIAL_MORTGAGES|"
            "AMP Essential Home Loan"
        ),
        "category": "RESIDENTIAL_MORTGAGES",
        "rate": "0.0634",
        "rate_family": "lending",
        "rate_type": "VARIABLE",
        "account_class": "standard",
    }
    non_standard = {
        "dataset": "Mortgage",
        "provider": "Darling Downs Bank",
        "product_id": "L42-_RURAL_LIFESTYLE_LOAN_INVESTMENT_FIXED_INTEREST_ONLY_12_MONTHS",
        "product_key": (
            "Darling Downs Bank|L42-_RURAL_LIFESTYLE_LOAN_INVESTMENT_FIXED_INTEREST_ONLY_"
            "12_MONTHS|RESIDENTIAL_MORTGAGES|RURAL LIFESTYLE LOAN"
        ),
        "category": "RESIDENTIAL_MORTGAGES",
        "rate": "0.0849",
        "rate_family": "lending",
        "rate_type": "FIXED",
        "account_class": "non_standard",
    }
    best, aliases, _sections, excluded = app_payload_v2._standard_best_for_day(
        [standard, non_standard]
    )
    assert len(best) == 1
    assert {key for keys in aliases.values() for key in keys} == {standard["product_key"]}
    assert excluded == {"non_standard": 1, "unclassified": 0, "unkeyed": 0}


def test_history_movements_never_cross_an_observation_gap():
    dates = ["2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04"]
    assert app_payload_v2._moves([0.05, None, 0.06, 0.061], dates) == [
        {
            "date": "2026-08-04",
            "from_rate": 0.06,
            "to_rate": 0.061,
            "bps": 10.0,
        }
    ]


def test_product_aliases_only_receive_dates_the_alias_was_observed(tmp_path, monkeypatch):
    dates = ["2026-08-01", "2026-08-02"]
    rows = {
        dates[0]: [{
            "dataset": "Mortgage", "provider": "Bank", "product_id": "p1",
            "product_key": "Bank|p1|old", "category": "RESIDENTIAL_MORTGAGES",
            "rate": "0.06", "rate_family": "lending", "rate_type": "VARIABLE",
            "account_class": "standard",
        }],
        dates[1]: [{
            "dataset": "Mortgage", "provider": "Bank", "product_id": "p1",
            "product_key": "Bank|p1|new", "category": "RESIDENTIAL_MORTGAGES",
            "rate": "0.055", "rate_family": "lending", "rate_type": "VARIABLE",
            "account_class": "standard",
        }],
    }
    monkeypatch.setattr(app_payload_v2.app_payload_mobile, "_history_dates", lambda *_: dates)
    monkeypatch.setattr(app_payload_v2.app_payload_mobile, "_banks", lambda _root, date: tmp_path / f"{date}.json")
    for date, rates in rows.items():
        (tmp_path / f"{date}.json").write_text(json.dumps({"rates": rates}), encoding="utf-8")
    history = app_payload_v2.build_product_history(tmp_path, run_date=dates[-1])
    assert history["products"]["Bank|p1|old"] == [0.06, None]
    assert history["products"]["Bank|p1|new"] == [None, 0.055]


def test_payload_staging_prune_keeps_only_manifest_referenced_assets(tmp_path):
    current = tmp_path / "core-current.json.gz"
    stale = tmp_path / "core-stale.json.gz"
    current.write_bytes(b"current")
    stale.write_bytes(b"stale")
    (tmp_path / "manifest.json").write_text(
        json.dumps({"files": {"core": {"name": current.name}}}), encoding="utf-8"
    )
    assert pi_daily_sync.prune_payload_staging(tmp_path, "manifest.json") == 1
    assert current.is_file()
    assert not stale.exists()
    assert (tmp_path / "manifest.json").is_file()


def test_rebuild_timestamp_is_not_part_of_content_hashed_coverage():
    coverage = {
        "schema_version": 1,
        "observed_on": "2026-08-04",
        "counts": {},
        "sections": {},
        "provider_failures": [],
        "source_generated_at": "2026-08-04T01:00:00Z",
    }
    banks = {"coverage": coverage}
    first = app_payload_build._stable_payload_coverage(
        banks, {"generated_at": "2026-08-04T01:00:00Z"}, "2026-08-04"
    )
    second = app_payload_build._stable_payload_coverage(
        banks, {"generated_at": "2026-08-04T02:00:00Z"}, "2026-08-04"
    )
    assert first == second
    assert "source_generated_at" not in first


def test_economic_freshness_sanitizes_source_urls():
    con = sqlite3.connect(":memory:")
    con.execute(
        """CREATE TABLE ingest_runs (
            series_id TEXT, last_checked_at TEXT, last_success_at TEXT,
            last_observation_date TEXT, status TEXT, source_url TEXT
        )"""
    )
    con.executemany(
        "INSERT INTO ingest_runs VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("safe", None, None, None, "ok", "https://www.rba.gov.au/data.csv#fragment"),
            ("secret", None, None, None, "failed", "https://user:token@example.test/data"),
        ],
    )
    freshness = app_payload_v2._freshness(con)
    assert freshness["safe"]["source_url"] == "https://www.rba.gov.au/data.csv"
    assert freshness["secret"]["source_url"] is None


def test_plaintext_v2_is_suppressed_when_payload_encryption_is_enabled(monkeypatch):
    monkeypatch.setenv("AR_LOCAL_PAYLOAD_ENC", "true")
    assert pi_daily_sync.v2_publication_allowed() is False
    monkeypatch.setenv("AR_LOCAL_PAYLOAD_ENC", "0")
    assert pi_daily_sync.v2_publication_allowed() is True


def test_daily_v2_uses_the_macro_producers_canonical_store_path():
    from cdr_macro_ingest import DEFAULT_STORE_PATH

    assert pi_daily_sync.DEFAULT_MACRO_STORE_PATH == DEFAULT_STORE_PATH


def test_v2_manifest_validator_enforces_capabilities_and_size_limits():
    asset = {
        "name": "v2-product-history-2026-05-19-aaaaaaaaaaaa.json.gz",
        "sha256": "a" * 64,
        "bytes": app_payload_contracts.MAX_V2_ASSET_BYTES["product_history"] + 1,
        "uncompressed_bytes": 1,
        "encoding": "gzip",
        "url": "https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/asset",
    }
    manifest = {
        "schema_version": 2,
        "base": {"core_sha": "c" * 64, "details_sha": "d" * 64},
        "capabilities": ["product_history"],
        "files": {"product_history": asset},
    }
    with pytest.raises(ValueError, match="compressed size limit"):
        app_payload_contracts.validate_v2_manifest(manifest)
    manifest["files"]["unexpected"] = dict(asset)
    manifest["capabilities"].append("unexpected")
    with pytest.raises(ValueError, match="unknown capability"):
        app_payload_contracts.validate_v2_manifest(manifest)


def test_checked_in_contract_schemas_parse_and_identify_current_versions():
    manifest_schema = json.loads((ROOT / "contracts" / "app-payload-v2.schema.json").read_text())
    asset_schema = json.loads((ROOT / "contracts" / "app-insight-assets.schema.json").read_text())
    assert manifest_schema["properties"]["schema_version"] == {"const": 2}
    assert set(asset_schema["$defs"]) >= {"coverage", "productHistory", "economicOutlook"}


@pytest.mark.skipif(REAL_EXPORTS is None, reason="set AR_LOCAL_REAL_EXPORTS to a real finalized export")
def test_v2_sidecar_builds_from_real_finalized_export_without_mutating_it(tmp_path):
    assert REAL_EXPORTS is not None
    v1_manifest = json.loads((REAL_EXPORTS / "app-payload" / "manifest.json").read_text())
    before = {
        str(path.relative_to(REAL_EXPORTS)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in REAL_EXPORTS.rglob("*")
        if path.is_file()
    }
    manifest = app_payload_v2.build_v2_sidecar(
        REAL_EXPORTS,
        tmp_path,
        v1_manifest=v1_manifest,
        economic_store_path=REAL_MACRO_STORE,
    )
    entry = manifest["files"]["product_history"]
    asset = tmp_path / entry["name"]
    assert hashlib.sha256(asset.read_bytes()).hexdigest() == entry["sha256"]
    history = json.loads(gzip.decompress(asset.read_bytes()))
    app_payload_contracts.validate_product_history(history)
    assert history["cohort"]["id"] == "standard"
    after = {
        str(path.relative_to(REAL_EXPORTS)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in REAL_EXPORTS.rglob("*")
        if path.is_file()
    }
    assert after == before


@pytest.mark.skipif(REAL_MACRO_STORE is None, reason="set AR_LOCAL_REAL_MACRO_STORE to a real macro store")
def test_economic_outlook_uses_real_local_observations():
    assert REAL_MACRO_STORE is not None
    payload = app_payload_v2.build_economic_outlook(
        REAL_MACRO_STORE, generated_at="2026-08-04T00:00:00Z"
    )
    app_payload_contracts.validate_economic_outlook(payload)
    assert payload["series"]
    assert all(1 <= len(series["observations"]) <= 2 for series in payload["series"])
    assert all(series["source_url"].startswith("https://") for series in payload["series"])
