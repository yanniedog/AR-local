"""Retained real Bankwest prize-tier regression plus parser boundary controls."""
from __future__ import annotations

import copy
import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from app_payload_build import build_payload
from cdr_clean_export import parse_banks_run
from cdr_outputs import rebuild_run_db, write_dashboard_cache
from cdr_ribbon_normalize import normalize_deposit_rate_kind
from cdr_savings_conditions import winner_rate_ribbons

FIXTURE = Path(__file__).parent / "fixtures/bankwest_easy_saver_real_2026-09-13.json"


@pytest.fixture
def evidence():
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "779ec130510a3ea160979dfd27111746e332c84b38523f64e97bf5c1d69420fd"
    return json.loads(raw)


@pytest.fixture
def reexport(tmp_path, evidence):
    product = evidence["products"][0]
    run = tmp_path / "2026-09-13"
    leaf = run / "banks" / "Savings" / product["provider"] / product["product_id"]
    leaf.mkdir(parents=True)
    (leaf / "product-detail.json").write_text(json.dumps(product["details_json"]), encoding="utf-8")
    return run, parse_banks_run(run)


def test_real_reexport_changes_only_prize_rate_facets(reexport, evidence):
    _, banks = reexport
    original = evidence["products"][0]["details_json"]
    assert json.loads(banks["products"][0]["details_json"]) == original
    assert len(banks["rates"]) == len(original["depositRates"]) == 13
    for row in banks["rates"]:
        source = original["depositRates"][row["rate_index"] - 1]
        assert float(row["rate"]) == float(source["rate"])
        assert row["rate_type"] == source["depositRateType"]
        assert row["dataset"] == "Savings"
        if row["rate_index"] == 5:
            assert row["account_class"] == "non_standard"
            assert row["ribbon_deposit_kind"] == "introductory"
            assert row["term_months"] == "4"
            assert row["taxonomy_path"] == "SAVINGS.SAVINGS_ACCT.INTRO.TIERED"
            assert row["balance_max"] == "250000.99"
        else:
            assert row["account_class"] == "standard"
            assert row["term_months"] == ""
            assert row["ribbon_deposit_kind"] == normalize_deposit_rate_kind(source["depositRateType"])
            # The retained SQLite export contains the old real normalized rows.
            # Compare every shared field, apart from SQLite's boolean encoding.
            for field, value in evidence["rates"][row["rate_index"] - 1].items():
                if field in row and field != "ribbon_normalized":
                    assert row[field] == value, (row["rate_index"], field)


def test_real_sqlite_and_payload_keep_rate_conditions_and_ordinary_sibling(reexport, evidence, monkeypatch):
    run, banks = reexport
    db = run / "local-cdr.sqlite"
    rebuild_run_db(db, "2026-09-13", banks)
    with sqlite3.connect(db) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT rate,account_class,term_months FROM bank_rates WHERE rate='0.115'").fetchone() == ("0.115", "non_standard", "4")
        assert connection.execute("SELECT rate,account_class FROM bank_rates WHERE rate='0.05'").fetchone() == ("0.05", "standard")
    monkeypatch.setattr("cdr_brand_logos.fetch_register_logos", lambda **kwargs: {})
    monkeypatch.setenv("AR_LOCAL_RBA_OFFICIAL_FETCH", "0")
    exports, output = run / "_exports", run / "payload"
    write_dashboard_cache(exports, "2026-09-13", banks)
    manifest = build_payload(exports, output, tag="app-payload-2026-09-13")
    assets = {key: json.loads(gzip.decompress((output / manifest["files"][key]["name"]).read_bytes()))
              for key in ("core", "details")}
    rows = assets["core"]["sections"]["Savings"]["rates"]
    prize = next(row for row in rows if row["rate_index"] == 5)
    ordinary = next(row for row in rows if row["rate_index"] == 4)
    assert prize["rate"] == "0.115" and prize["ongoing_rate"] == "0.05"
    assert prize["account_class"] == "non_standard" and prize["term_months"] == "4"
    assert ordinary["rate"] == "0.05" and ordinary["account_class"] == "standard"
    details = assets["details"]["products"][prize["product_key"]]
    assert all("winners" not in str(item).lower() for item in details["eligibility"])
    disclosures = [item for item in details["features"] if item.get("name") == "Deposit rate 5 (FIXED)"]
    assert len(disclosures) == 4
    conditions = evidence["products"][0]["details_json"]["depositRates"][4]["tiers"][0]["applicabilityConditions"]
    assert {item["label"] for item in disclosures} >= {f"Tier 1: {item['rateApplicabilityType']}" for item in conditions}
    assert conditions[0]["additionalInfo"] in [item.get("info") for item in disclosures]


def test_tier_conditions_alone_are_sufficient_without_source_mutation(evidence):
    item = copy.deepcopy(evidence["products"][0]["details_json"]["depositRates"][4])
    item.pop("additionalInfo")
    before = copy.deepcopy(item)
    assert winner_rate_ribbons(item) == {"account_class": "non_standard", "term_months": "4", "ribbon_deposit_kind": "introductory"}
    assert item == before


@pytest.mark.parametrize("info", [
    "Enter our competition for a chance to win.",
    "Not available only to winners of the competition.",
    "Competition winners are excluded from this offer.",
    "Employees are not eligible to win the competition.",
    "Available to all eligible customers, including competition winners.",
])
def test_marketing_and_exclusions_do_not_become_winner_restrictions(info):
    # Text-only parser controls, not fabricated financial acceptance data.
    assert winner_rate_ribbons({"additionalInfo": info}) == {}


def test_conflicting_duration_stays_unknown(evidence):
    item = copy.deepcopy(evidence["products"][0]["details_json"]["depositRates"][4])
    item["additionalInfo"] = item["additionalInfo"].replace("four months", "six months")
    assert winner_rate_ribbons(item) == {"account_class": "non_standard"}


def test_rate_level_conditions_and_malformed_siblings(evidence):
    item = copy.deepcopy(evidence["products"][0]["details_json"]["depositRates"][4])
    item.pop("additionalInfo")
    item["applicabilityConditions"] = item.pop("tiers")[0]["applicabilityConditions"] + [None]
    item["tiers"] = [None, {"applicabilityConditions": None}]
    assert winner_rate_ribbons(item)["account_class"] == "non_standard"
