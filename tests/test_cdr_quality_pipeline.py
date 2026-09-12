"""Quality regressions use retained real public CDR evidence and structural faults."""
from __future__ import annotations

import copy
import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from app_payload_common import section_filter
from cdr_product_classification import infer_cdr_dataset
from cdr_quality_accounting import audit_rows, payload_accounting, rate_rows_digest
from cdr_quality_history import history_context
from cdr_quality_logs import audit_logs
from cdr_quality_public import audit_public
from cdr_quality_sources import AuditIndex, contained, inventory, read_database
from pi_daily_sync import _same_payload_revision, parse_args

EVIDENCE = Path(__file__).parents[1] / "docs/evidence/backup-observation-20260911/publication"
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def public():
    core = json.loads(gzip.decompress((EVIDENCE / "v1-core.json.gz").read_bytes()))
    manifest = json.loads((EVIDENCE / "manifest.json").read_bytes())
    return core, manifest


def source_rows(core):
    # The core omits transport dataset/family columns. Reattach its declared
    # section and shipping family to test the newly explicit category guard.
    return [{**row, "dataset": section, "rate_family": "lending" if section == "Mortgage" else "deposit"}
            for section, data in core["sections"].items() for row in data["rates"]]


def test_real_business_products_do_not_enter_residential_or_deposit_sections(public):
    rows = source_rows(public[0])
    excluded = [row for row in rows if not section_filter(row["dataset"], row)]
    assert len(excluded) == 27
    assert {r["category"] for r in excluded} == {"BUSINESS_LOANS", "OVERDRAFTS", "PERS_LOANS"}
    for row in excluded:
        assert infer_cdr_dataset({"productCategory": row["category"], "name": row["product_name"]}) is None
    accounting = payload_accounting([], rows)
    assert accounting["exclusions"] == {"out_of_section_category": 27}
    assert accounting["source_rates"] == accounting["published_rates"] + accounting["excluded_rates"]


def test_financial_digest_detects_same_count_rate_replacement(public):
    rows = public[0]["sections"]["Mortgage"]["rates"][:2]
    changed = copy.deepcopy(rows)
    changed[0]["rate"] = rows[1]["rate"] if rows[0]["rate"] != rows[1]["rate"] else "0"
    assert rate_rows_digest(rows) != rate_rows_digest(changed)
    assert rate_rows_digest(rows) == rate_rows_digest(list(reversed(rows)))


def real_product():
    record = json.loads((FIXTURES / "canonical_domain_real_observations.json").read_text())["observations"]["bank_of_melbourne_before_rename"]
    raw = record["record"]
    return {"run_date": record["observed_at"][:10], "dataset": record["dataset"], "provider": record["provider"],
            "product_id": raw["productId"], "product_key": f"{record['provider']}|{raw['productId']}",
            "product_name": raw["name"], "details_json": json.dumps(raw), "source_file": record["source_path"]}


def test_history_ignores_capture_date_but_preserves_changed_product_details():
    product = real_product()
    earlier = audit_rows([product], [])
    later_product = {**product, "run_date": "2026-05-26", "source_file": "retained-later-copy"}
    later = audit_rows([later_product], [])
    assert earlier["products"] == later["products"]
    for result, day, key in ((earlier, "2026-05-25", "primary"), (later, "2026-05-26", "revision")):
        result.update(run_date=day, key=key, status={"by_provider": {}}, generation_id=key)
    context = history_context([earlier, later], later)
    assert context["observation_count"] == 2
    assert context["unique_products_ever"] == 1
    assert not context["products_absent_from_selected"]
    assert not context["same_day_revision_comparisons"][0]["changed_in_selected"]


def test_read_database_is_read_only_and_recovers_retained_wal_in_private_copy(tmp_path):
    product = real_product()
    day = product["run_date"]
    db_path = tmp_path / "local-cdr.sqlite"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE runs (run_date TEXT)")
        db.execute("INSERT INTO runs VALUES (?)", (day,))
        db.execute("CREATE TABLE bank_products (" + ",".join(f"{key} TEXT" for key in product) + ")")
        db.execute("INSERT INTO bank_products VALUES (" + ",".join("?" for _ in product) + ")", list(product.values()))
        db.execute("CREATE TABLE bank_rates (run_date TEXT)")
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    products, rates, check = read_database(tmp_path, day)
    assert products == [product] and rates == [] and check["integrity"] == "PASS"
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before
    with sqlite3.connect(db_path) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE audit_probe (value TEXT)")
        writer.commit()
        wal = tmp_path / "local-cdr.sqlite-wal"
        source_bytes = {p.name: p.read_bytes() for p in (db_path, wal)}
        copied_products, _, copied_check = read_database(tmp_path, day)
        assert copied_products == [product]
        assert copied_check["journal_mode"] == "private_copy_recovery"
        assert source_bytes == {p.name: p.read_bytes() for p in (db_path, wal)}


def test_inventory_includes_failed_and_archived_generations(tmp_path):
    expected = {"runs/2026-05-25/_exports", "runs/2026-05-25/_revisions/retry/_exports",
                "runs/2026-05-25/_failed_attempts/failure/exports/_exports", "runs-archive/2026-05-24/_exports"}
    for name in expected:
        (tmp_path / name).mkdir(parents=True)
    sources, errors = inventory(tmp_path)
    assert not errors
    assert {source["key"] for source in sources} == expected
    with pytest.raises(ValueError):
        contained(tmp_path, "../other")


def test_full_log_scan_caches_and_detects_deletion_and_truncated_json(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    raw = (FIXTURES / "cdr_failures_real_2026-09-07.json").read_bytes()
    path = logs / "historical.log"
    path.write_bytes(raw)
    bad = logs / "interrupted.jsonl"
    bad.write_text('{"status":')
    index = AuditIndex(tmp_path / "audit/index.sqlite")
    try:
        first = audit_logs(tmp_path, index)
        second = audit_logs(tmp_path, index)
        assert first["cached_files"] == 0 and second["cached_files"] == 2
        assert next(r for r in first["files"] if r["path"].endswith("interrupted.jsonl"))["invalid_jsonl_lines"] == 1
        path.unlink()
        assert audit_logs(tmp_path, index)["errors"][0]["code"] == "PREVIOUSLY_AUDITED_LOG_MISSING"
    finally:
        index.close()


def test_public_audit_detects_real_out_of_section_rows(public):
    core, manifest = public
    class Store:
        def read(self, tag, name):
            return (EVIDENCE / name).read_bytes()

        def read_url(self, url, limit=None):
            key = next(k for k, v in manifest["files"].items() if v["url"] == url)
            return (EVIDENCE / f"v1-{key}.json.gz").read_bytes()

    current = audit_rows([], source_rows(core))
    current.update(run_date=core["run_date"], contract_digest=None)
    report = audit_public(current, store=Store())
    assert report["status"] == "FAIL"
    assert {i["section"] for i in report["issues"]} == {"Mortgage", "TD"}
    assert len(report["assets_verified"]) == 7


def test_quality_recapture_requires_force_and_cannot_reuse_source():
    with pytest.raises(SystemExit):
        parse_args(["--quality-recapture"])
    with pytest.raises(SystemExit):
        parse_args(["--force", "--quality-recapture", "--resume-same-day"])
    assert parse_args(["--quality-recapture", "--force"]).quality_recapture


def test_revision_success_requires_every_asset_hash(public):
    manifest = copy.deepcopy(public[1])
    manifest["payload_revision"] = {"revision": 1, "generation_id": "bound"}
    changed = copy.deepcopy(manifest)
    changed["files"]["bank_history"]["sha256"] = "0" * 64
    assert _same_payload_revision(manifest, manifest)
    assert not _same_payload_revision(manifest, changed)
