import json
import sqlite3
from copy import deepcopy
from pathlib import Path

import app_payload_mobile
import cdr_outputs
import openpyxl
from cdr_product_facts import audit_records, clean_fact_rows, compact_facts, extract_product_facts


FIXTURE = Path(__file__).parent / "fixtures" / "product_facts_real_2026-05-19.json"


def captured():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["products"]


def test_real_cdr_facts_are_typed_unique_grouped_and_currency_safe():
    products = captured()
    up = products[0]["record"]
    facts = extract_product_facts(up, "Mortgage|Up|up-home")
    assert len({fact["fact_id"] for fact in facts}) == len(facts)
    assert next(fact for fact in facts if fact["canonical_key"] == "rate.advertised")["value"] == 0.057
    max_lvr = next(fact for fact in facts if fact["canonical_key"] == "constraint.value" and fact["unit"] == "fraction")
    assert max_lvr["value"] == 0.9
    min_age = next(fact for fact in facts if fact["canonical_key"] == "eligibility.value")
    assert (min_age["value"], min_age["unit"]) == (18.0, "year")
    usd = extract_product_facts(products[1]["record"], "Savings|Bank Australia|basic")
    amount = next(fact for fact in usd if fact["canonical_key"] == "fee.amount")
    assert (amount["value"], amount["unit"]) == (175.0, "USD")


def test_real_tier_emits_explicit_fraction_range_and_preserves_leaves():
    facts = extract_product_facts(captured()[2]["record"], "Mortgage|BOQS|basic")
    range_fact = next(fact for fact in facts if fact["value_type"] == "range")
    assert (range_fact["kind"], range_fact["min_value"], range_fact["max_value"], range_fact["unit"]) == (
        "tier", 0.6001, 0.7, "fraction",
    )
    assert any(fact["canonical_key"] == "tier.minimum" for fact in facts)
    compact = compact_facts(captured()[2]["record"], "Mortgage|BOQS|basic")
    assert any(fact.get("minValue") == 0.6001 and fact.get("maxValue") == 0.7 for fact in compact)


def test_compact_facts_consolidate_structural_fields_and_keep_exact_conditions():
    compact = compact_facts(captured()[0]["record"], "Mortgage|Up|up-home")
    assert not any(fact["canonicalKey"] in {"feature.type", "currency", "fee.method"} for fact in compact)
    offset = next(fact for fact in compact if fact["canonicalKey"] == "feature.offset" and fact.get("sourceType") == "OFFSET")
    assert offset["label"] == "Offset"
    assert offset["condition"] == "Use your Up spending account and Savers as offsets."
    assert offset["groupId"]
    assert "source_path" not in json.dumps(compact)


def test_audit_proves_every_nonempty_scalar_covered_and_reports_unmatched_text():
    records = [(row["record"]["productId"], row["record"]) for row in captured()]
    report = audit_records(records)
    assert report["unmapped_nonempty_scalar_paths"] == []
    assert report["duplicate_fact_ids"] == []
    assert report["covered_nonempty_scalars"] == report["observed_nonempty_scalars"]
    assert report["text_coverage"]["unmatched"] > 0
    assert report["text_coverage"]["unmatched_semantic_status"] == "preserved_not_equivalent"


def test_semantic_ids_survive_reordering_and_repeated_tiers_remain_unique():
    record = deepcopy(captured()[0]["record"])
    before = extract_product_facts(record, "stable-product")
    record["features"].reverse()
    record["lendingRates"].reverse()
    after = extract_product_facts(record, "stable-product")
    signature = lambda fact: (
        fact["canonical_key"], fact["source_value_json"], fact["mapping"],
        fact["qualifiers"].get("lendingRateType"), fact["qualifiers"].get("featureType"),
    )
    assert {signature(fact): fact["fact_id"] for fact in before} == {
        signature(fact): fact["fact_id"] for fact in after
    }
    tiered = deepcopy(captured()[2]["record"])
    tiered["lendingRates"][0]["tiers"].append(deepcopy(tiered["lendingRates"][0]["tiers"][0]))
    tier_facts = [fact for fact in extract_product_facts(tiered, "repeated-tier") if fact["value_type"] == "range"]
    assert len(tier_facts) == 2
    assert len({fact["fact_id"] for fact in tier_facts}) == 2


def test_audit_reports_source_failures_and_does_not_claim_complete_capture():
    report = audit_records(
        [("up-home", captured()[0]["record"])],
        [{"bank": "Example", "phase": "product_detail", "status": "403"}],
    )
    assert report["complete"] is False
    assert report["detail_failures"][0]["status"] == "403"
    assert report["source_failures"] == report["detail_failures"]


def test_search_index_uses_vetted_fact_values_labels_and_conditions_not_raw_paths_or_urls():
    facts = compact_facts(captured()[0]["record"], "key")
    index = app_payload_mobile.build_search_index([], {"key": {"facts": facts}}, run_date="2026-05-19")
    text = index["products"]["key"]
    assert "feature offset" in text
    assert "use your up spending account and savers as offsets" in text
    assert "source_path" not in text and "http" not in text


def test_compact_payload_has_a_bounded_entity_count_and_size():
    all_facts = [fact for product in captured() for fact in compact_facts(product["record"], product["record"]["productId"])]
    encoded = json.dumps(all_facts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert len(all_facts) < 100
    assert len(encoded) < 40_000


def test_sqlite_fact_constraints_and_filter_indexes_are_used():
    record = captured()[0]["record"]
    base = {"dataset": "Mortgage", "provider": "Up", "product_id": "up-home", "product_key": "Up|up-home", "product_name": "Up Home Loan"}
    rows = clean_fact_rows(record, base)
    with sqlite3.connect(":memory:") as con:
        cdr_outputs.ensure_db(con)
        cdr_outputs.insert_rows(con, "bank_product_facts", [{"run_date": "2026-05-19", **row} for row in rows])
        numeric = con.execute("EXPLAIN QUERY PLAN SELECT product_key FROM bank_product_facts WHERE run_date=? AND dataset=? AND canonical_key=? AND value_number>=?", ("2026-05-19", "Mortgage", "rate.advertised", 0.05)).fetchall()
        categorical = con.execute("EXPLAIN QUERY PLAN SELECT product_key FROM bank_product_facts WHERE run_date=? AND dataset=? AND canonical_key=? AND value_text=?", ("2026-05-19", "Mortgage", "loan.purpose", "OWNER_OCCUPIED")).fetchall()
        assert any("idx_bank_product_facts_numeric" in row[-1] for row in numeric)
        assert any("idx_bank_product_facts_categorical" in row[-1] for row in categorical)


def test_normal_outputs_include_facts_json_xlsx_and_sqlite(tmp_path: Path):
    run = tmp_path / "2026-05-19"
    for index, product in enumerate(captured()):
        path = run / "banks" / product["dataset"] / product["provider"] / f"product-{index}" / "id"
        path.mkdir(parents=True)
        (path / "product-detail.json").write_text(json.dumps({"data": product["record"]}), encoding="utf-8")
    out = tmp_path / "exports"
    cdr_outputs.build_outputs(run, out_dir=out)
    exported = json.loads((out / "banks-2026-05-19.json").read_text(encoding="utf-8"))
    assert exported["product_facts"]
    workbook = openpyxl.load_workbook(out / "banks-2026-05-19.xlsx", read_only=True)
    assert "product_facts" in workbook.sheetnames
    with sqlite3.connect(out / "local-cdr.sqlite") as con:
        assert con.execute("SELECT COUNT(*) FROM bank_product_facts").fetchone()[0] == len(exported["product_facts"])


def test_normal_outputs_index_previous_run_product_changes(tmp_path: Path):
    def write_run(day: str, description: str) -> Path:
        run = tmp_path / day
        path = run / "banks" / "Mortgage" / "Example Bank" / "Home Loan" / "stable-id"
        path.mkdir(parents=True)
        record = {
            "productId": "stable-id", "name": "Home Loan", "brand": "Example Bank",
            "description": description, "features": [], "eligibility": [], "constraints": [],
            "fees": [], "lendingRates": [],
        }
        (path / "product-detail.json").write_text(json.dumps({"data": record}), encoding="utf-8")
        return run

    previous = write_run("2026-05-18", "An offset account is available.")
    current = write_run("2026-05-19", "No offset account is available.")
    cdr_outputs.build_outputs(previous)
    cdr_outputs.build_outputs(current)
    exported = json.loads((current / "_exports" / "banks-2026-05-19.json").read_text(encoding="utf-8"))
    assert exported["product_change_summary"]["previous_run_date"] == "2026-05-18"
    assert exported["product_change_summary"]["change_count"] == len(exported["product_changes"])
    assert exported["product_changes"]
    workbook = openpyxl.load_workbook(current / "_exports" / "banks-2026-05-19.xlsx", read_only=True)
    assert {"product_changes", "change_summary"} <= set(workbook.sheetnames)
    with sqlite3.connect(current / "_exports" / "local-cdr.sqlite") as con:
        assert con.execute("SELECT COUNT(*) FROM bank_product_changes").fetchone()[0] == len(exported["product_changes"])
        plan = con.execute(
            "EXPLAIN QUERY PLAN SELECT product_id FROM bank_product_changes WHERE run_date=? AND provider=? AND event_type=? AND canonical_key=?",
            ("2026-05-19", "Example Bank", "condition_changed", "feature.offset"),
        ).fetchall()
        assert any("idx_bank_product_changes_lookup" in row[-1] for row in plan)
