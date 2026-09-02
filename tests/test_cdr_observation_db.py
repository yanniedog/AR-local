from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from cdr_contracts import canonical_json_bytes, product_uid, rate_uid
from cdr_observation_db import (
    APPLICATION_ID,
    FAILURE_STAGES,
    SCHEMA_VERSION,
    ObservationDatabaseError,
    build_observation_database,
    verify_observation_database,
)

FIXTURE = Path(__file__).parent / "fixtures/canonical_domain_real_observations.json"
PROVIDER_UID = "provider:v1:" + "1" * 64
PRODUCT_UID = product_uid(PROVIDER_UID, "Savings", "BOMInvestmentCashAccounts")
RATE_UID = rate_uid(PRODUCT_UID, 1, "0.0045", None)
ACCOUNTING_ID = "ingest-2026-05-25-bank-of-melbourne"


def observation() -> tuple[dict, dict]:
    captured = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"]
    source = captured["bank_of_melbourne_before_rename"]
    record, source_rate = source["record"], source["record"]["depositRates"][0]
    evidence_id = source["source_record_sha256"]
    product = {
        "product_uid": PRODUCT_UID,
        "provider_uid": PROVIDER_UID,
        "cdr_product_id": record["productId"],
        "dataset": source["dataset"],
        "display_name": record["name"],
        "legacy_product_key": f"{source['dataset']}|{source['provider']}|{record['productId']}",
        "disposition": "published_full",
        "reason_codes": [],
        "evidence_ids": [evidence_id],
        "core_valid": True,
        "details_complete": True,
    }
    accounting = {
        "schema_version": 1,
        "observation_date": "2026-05-25",
        "accounting_id": ACCOUNTING_ID,
        "raw_attempt_journal_digest": source["source_sha256"],
        "providers": [
            {
                "provider_uid": PROVIDER_UID,
                "brand_name": source["provider"],
                "datasets": ["Savings"],
                "affected_sections": [],
                "state": "complete",
                "attempted": True,
                "population_known": True,
                "discovered_count": 1,
                "published_full_count": 1,
                "published_core_only_count": 0,
                "omitted_valid_count": 0,
                "quarantined_invalid_count": 0,
                "issue_count": 0,
                "issue_ids": [],
            }
        ],
        "products": [product],
        "issues": [],
        "summary": {
            "providers": {"registered": 1, "attempted": 1, "complete": 1, "partial": 0, "empty": 0, "failed": 0, "not_attempted": 0, "population_unknown": 0},
            "products": {"discovered": 1, "published_full": 1, "published_core_only": 0, "omitted_valid": 0, "quarantined_invalid": 0, "consumer_visible": 1},
            "issues": {"total": 0, "corrupt": 0, "unattributed": 0, "affected_providers": 0, "affected_products": 0, "by_code": {}},
        },
    }
    product_keys = {key: product[key] for key in ("product_uid", "provider_uid", "dataset", "cdr_product_id", "legacy_product_key")}
    product_document = {
        **product_keys, "details_complete": True, "evidence_id": evidence_id
    }
    rate_keys = {"rate_uid": RATE_UID, "product_uid": PRODUCT_UID, "rate_index": 1, "rate": source_rate["rate"], "comparison_rate": None}
    item_keys = {"product_uid": PRODUCT_UID, "item_group": "eligibility", "item_index": 1}
    fact_keys = {
        "product_uid": PRODUCT_UID,
        "fact_id": "advertised-rate",
        "kind": "rate",
        "canonical_key": "rate.advertised",
        "value_type": "rate",
        "value_boolean": None,
        "value_number": 0.0045,
        "value_text": None,
        "min_value": None,
        "max_value": None,
    }
    change_keys = {
        "event_id": "rename-2026-05-26",
        "provider_uid": PROVIDER_UID,
        "product_uid": PRODUCT_UID,
        "event_type": "product_renamed",
        "canonical_key": "product.name",
    }
    projections = {
        "products": [{**product_keys, "document": product_document}],
        "rates": [
            {**rate_keys, "document": {**rate_keys, "evidence_id": evidence_id}}
        ],
        "items": [
            {**item_keys, "document": {**item_keys, "evidence_id": evidence_id}}
        ],
        "product_facts": [
            {**fact_keys, "document": {**fact_keys, "evidence_id": evidence_id}}
        ],
        "product_changes": [
            {
                **change_keys,
                "document": {
                    **change_keys,
                    "dataset": source["dataset"],
                    "product_id": record["productId"],
                    "evidence_id": evidence_id,
                },
            }
        ],
    }
    return accounting, projections


def build(path: Path):
    accounting, projections = observation()
    return build_observation_database(
        path,
        accounting=accounting,
        projections=projections,
        generated_at="2026-05-25T00:01:00+10:00",
        normalization_version="cdr-domain-v1",
    )


def test_atomic_build_full_readback_and_query_indexes(tmp_path: Path):
    path = tmp_path / "banks.sqlite"
    result = build(path)
    accounting, _ = observation()
    assert result.created is True
    assert result.verification.sidecar_bytes == canonical_json_bytes(accounting)
    assert result.verification.counts == {
        "bank_items": 1,
        "bank_product_changes": 1,
        "bank_product_facts": 1,
        "bank_products": 1,
        "bank_rates": 1,
    }
    assert not any(Path(f"{path}{suffix}").exists() for suffix in ("-journal", "-wal", "-shm"))
    assert not list(tmp_path.glob(".banks.sqlite.tmp-*"))
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        assert connection.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        strict = {row[1]: row[5] for row in connection.execute("PRAGMA table_list") if row[1].startswith("bank_") or row[1] in {"runs", "schema_meta"}}
        assert strict and set(strict.values()) == {1}
        indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='index'")}
        assert {"idx_bank_rates_product", "idx_bank_product_facts_numeric", "idx_bank_observation_issues_scope"} <= indexes
        plan = connection.execute(
            "EXPLAIN QUERY PLAN SELECT rate_uid FROM bank_rates WHERE accounting_id=? AND product_uid=? ORDER BY rate_index", (ACCOUNTING_ID, PRODUCT_UID)
        ).fetchall()
        assert any("idx_bank_rates_product" in row[-1] for row in plan)
        plan = connection.execute(
            "EXPLAIN QUERY PLAN SELECT product_uid FROM bank_product_facts WHERE accounting_id=? AND canonical_key=? AND value_number>=?",
            (ACCOUNTING_ID, "rate.advertised", 0.004),
        ).fetchall()
        assert any("idx_bank_product_facts_numeric" in row[-1] for row in plan)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]


def test_create_once_replay_and_collision_preserve_bytes(tmp_path: Path):
    path = tmp_path / "banks.sqlite"
    first = build(path)
    second = build(path)
    assert second.created is False
    assert second.verification.database_sha256 == first.verification.database_sha256
    accounting, projections = observation()
    with pytest.raises(ObservationDatabaseError, match="generated_at"):
        build_observation_database(
            path, accounting=accounting, projections=projections, generated_at="2026-05-25T00:02:00+10:00", normalization_version="cdr-domain-v1"
        )
    projections["products"][0]["document"]["unexpected_change"] = True
    with pytest.raises(ObservationDatabaseError):
        build_observation_database(
            path, accounting=accounting, projections=projections, generated_at="2026-05-25T00:01:00+10:00", normalization_version="cdr-domain-v1"
        )
    assert verify_observation_database(path).database_sha256 == first.verification.database_sha256


def test_public_documents_reject_sensitive_fields_and_unapproved_urls(tmp_path: Path):
    accounting, projections = observation()
    projections["products"][0]["document"]["authorization"] = "Bearer secret"
    with pytest.raises(ObservationDatabaseError, match="outside its contract"):
        build_observation_database(
            tmp_path / "sensitive.sqlite",
            accounting=accounting,
            projections=projections,
            generated_at="2026-05-25T00:01:00+10:00",
            normalization_version="cdr-domain-v1",
        )

    accounting, projections = observation()
    projections["products"][0]["document"]["description"] = "See https://internal.example/token"
    with pytest.raises(ObservationDatabaseError, match="unapproved URL"):
        build_observation_database(
            tmp_path / "url.sqlite",
            accounting=accounting,
            projections=projections,
            generated_at="2026-05-25T00:01:00+10:00",
            normalization_version="cdr-domain-v1",
        )


@pytest.mark.parametrize("stage", [stage for stage in FAILURE_STAGES if stage != "after_install"])
def test_injected_failures_before_install_leave_no_artifact(tmp_path: Path, stage: str):
    path = tmp_path / "banks.sqlite"
    accounting, projections = observation()

    def fail_at(current: str) -> None:
        if current == stage:
            raise RuntimeError("injected failure")

    with pytest.raises(RuntimeError, match="injected"):
        build_observation_database(
            path,
            accounting=accounting,
            projections=projections,
            generated_at="2026-05-25T00:01:00+10:00",
            normalization_version="cdr-domain-v1",
            failure_hook=fail_at,
        )
    assert not path.exists()
    assert not list(tmp_path.glob(".banks.sqlite.tmp-*"))


def test_failure_after_install_leaves_only_verified_artifact(tmp_path: Path):
    path = tmp_path / "banks.sqlite"
    accounting, projections = observation()

    def fail_after_install(stage: str) -> None:
        if stage == "after_install":
            raise RuntimeError("injected failure")

    with pytest.raises(RuntimeError, match="injected"):
        build_observation_database(
            path,
            accounting=accounting,
            projections=projections,
            generated_at="2026-05-25T00:01:00+10:00",
            normalization_version="cdr-domain-v1",
            failure_hook=fail_after_install,
        )
    assert verify_observation_database(path).sidecar_bytes == canonical_json_bytes(accounting)
    assert not list(tmp_path.glob(".banks.sqlite.tmp-*"))


def test_corruption_after_install_removes_unverified_artifact(tmp_path: Path):
    path = tmp_path / "banks.sqlite"
    accounting, projections = observation()

    def corrupt_after_install(stage: str) -> None:
        if stage == "after_install":
            with path.open("ab") as stream:
                stream.write(b"tamper")

    with pytest.raises(ObservationDatabaseError):
        build_observation_database(
            path,
            accounting=accounting,
            projections=projections,
            generated_at="2026-05-25T00:01:00+10:00",
            normalization_version="cdr-domain-v1",
            failure_hook=corrupt_after_install,
        )

    assert not path.exists()
    assert not list(tmp_path.glob(".banks.sqlite.tmp-*"))


@pytest.mark.parametrize("stage,installed", [("before_install", False), ("after_install", True)])
def test_abrupt_process_death_cannot_publish_partial_database(tmp_path: Path, stage: str, installed: bool):
    path, input_path = tmp_path / "banks.sqlite", tmp_path / "input.json"
    accounting, projections = observation()
    input_path.write_text(json.dumps({"accounting": accounting, "projections": projections}), encoding="utf-8")
    script = """
import json, os, sys
from pathlib import Path
from cdr_observation_db import build_observation_database
value=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
def hook(current):
    if current == sys.argv[3]: os._exit(73)
build_observation_database(Path(sys.argv[2]),accounting=value['accounting'],projections=value['projections'],generated_at='2026-05-25T00:01:00+10:00',normalization_version='cdr-domain-v1',failure_hook=hook)
"""
    completed = subprocess.run([sys.executable, "-c", script, str(input_path), str(path), stage], cwd=Path(__file__).parents[1], check=False)
    assert completed.returncode == 73
    assert path.exists() is installed
    if installed:
        verify_observation_database(path)
    assert not any(Path(f"{path}{suffix}").exists() for suffix in ("-journal", "-wal", "-shm"))


@pytest.mark.parametrize("mutation", ["drop_index", "foreign_key", "sidecar", "projection", "metadata"])
def test_tampering_fails_closed(tmp_path: Path, mutation: str):
    original, damaged = tmp_path / "original.sqlite", tmp_path / f"{mutation}.sqlite"
    build(original)
    shutil.copyfile(original, damaged)
    with sqlite3.connect(damaged) as connection:
        if mutation == "drop_index":
            connection.execute("DROP INDEX idx_bank_rates_product")
        elif mutation == "foreign_key":
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute("DELETE FROM bank_products")
        elif mutation == "sidecar":
            connection.execute("UPDATE runs SET sidecar_bytes=?", (b"{}\n",))
        elif mutation == "projection":
            connection.execute("UPDATE bank_rates SET rate='0.9'")
        else:
            connection.execute("UPDATE schema_meta SET value=? WHERE key='accounting_sha256'", ("0" * 64,))
        connection.commit()
    with pytest.raises(ObservationDatabaseError):
        verify_observation_database(damaged)


def test_sidecar_files_are_rejected_and_restored_copy_verifies(tmp_path: Path):
    source, restored = tmp_path / "source.sqlite", tmp_path / "restored.sqlite"
    built = build(source)
    shutil.copyfile(source, restored)
    assert verify_observation_database(restored).database_sha256 == built.verification.database_sha256
    wal = Path(f"{restored}-wal")
    wal.write_bytes(b"unexpected")
    with pytest.raises(ObservationDatabaseError):
        verify_observation_database(restored)


def test_symlink_alias_is_rejected(tmp_path: Path):
    source, alias = tmp_path / "source.sqlite", tmp_path / "alias.sqlite"
    build(source)
    try:
        alias.symlink_to(source)
    except OSError:
        pytest.skip("symlinks are unavailable")
    with pytest.raises(ObservationDatabaseError, match="symlink"):
        verify_observation_database(alias)


def test_database_constraints_reject_orphans_type_drift_and_visibility_drift(tmp_path: Path):
    path = tmp_path / "banks.sqlite"
    build(path)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO bank_rates VALUES(?,?,?,?,?,?,?)", (ACCOUNTING_ID, "4" * 64, "9" * 64, 2, "0.1", None, "{}")
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO bank_items VALUES(?,?,?,?,?)", (ACCOUNTING_ID, PRODUCT_UID, "fees", "not-an-integer", "{}"))
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO bank_product_changes VALUES(?,?,?,?,?,?,?)",
                (
                    ACCOUNTING_ID, "orphan-change", PROVIDER_UID, "9" * 64,
                    "product_changed", None, "{}",
                ),
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="cannot become non-publishable"):
            connection.execute("UPDATE bank_product_dispositions SET disposition='omitted_valid' WHERE product_uid=?", (PRODUCT_UID,))
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE bank_product_facts SET value_number=100 WHERE product_uid=?",
                (PRODUCT_UID,),
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE bank_product_facts SET kind='tier',value_type='range',"
                "value_number=NULL,min_value=2,max_value=1 WHERE product_uid=?",
                (PRODUCT_UID,),
            )


@pytest.mark.parametrize("bad_rate", ["5", "NaN", "0.00450", "5.0e-2"])
def test_noncanonical_or_wrong_magnitude_rates_fail_before_disk(tmp_path: Path, bad_rate: str):
    accounting, projections = observation()
    projections["rates"][0]["rate"] = bad_rate
    with pytest.raises(ObservationDatabaseError):
        build_observation_database(
            tmp_path / "banks.sqlite",
            accounting=accounting,
            projections=projections,
            generated_at="2026-05-25T00:01:00+10:00",
            normalization_version="cdr-domain-v1",
        )
    assert not (tmp_path / "banks.sqlite").exists()


def test_rate_uid_is_recomputed_from_canonical_rate_identity(tmp_path: Path):
    accounting, projections = observation()
    projections["rates"][0]["rate_uid"] = "4" * 64
    projections["rates"][0]["document"]["rate_uid"] = "4" * 64
    with pytest.raises(ObservationDatabaseError, match="rate identity"):
        build_observation_database(
            tmp_path / "banks.sqlite",
            accounting=accounting,
            projections=projections,
            generated_at="2026-05-25T00:01:00+10:00",
            normalization_version="cdr-domain-v1",
        )


def test_rate_fact_outside_decimal_fraction_fails_before_disk(tmp_path: Path):
    accounting, projections = observation()
    projections["product_facts"][0]["value_number"] = 100.0
    projections["product_facts"][0]["document"]["value_number"] = 100.0
    with pytest.raises(ObservationDatabaseError, match="rate fact"):
        build_observation_database(
            tmp_path / "banks.sqlite",
            accounting=accounting,
            projections=projections,
            generated_at="2026-05-25T00:01:00+10:00",
            normalization_version="cdr-domain-v1",
        )


def test_reversed_fact_range_fails_before_disk(tmp_path: Path):
    accounting, projections = observation()
    row = projections["product_facts"][0]
    row.update(
        kind="tier",
        value_type="range",
        value_number=None,
        min_value=2.0,
        max_value=1.0,
    )
    row["document"].update(
        kind="tier",
        value_type="range",
        value_number=None,
        min_value=2.0,
        max_value=1.0,
    )
    with pytest.raises(ObservationDatabaseError, match="range bounds are reversed"):
        build_observation_database(
            tmp_path / "banks.sqlite",
            accounting=accounting,
            projections=projections,
            generated_at="2026-05-25T00:01:00+10:00",
            normalization_version="cdr-domain-v1",
        )


@pytest.mark.parametrize(
    "group", ("products", "rates", "items", "product_facts", "product_changes")
)
def test_projection_documents_require_the_product_evidence(
    tmp_path: Path, group: str
) -> None:
    accounting, projections = observation()
    projections[group][0]["document"]["evidence_id"] = "f" * 64
    with pytest.raises(ObservationDatabaseError, match="accounting-bound evidence"):
        build_observation_database(
            tmp_path / "banks.sqlite",
            accounting=accounting,
            projections=projections,
            generated_at="2026-05-25T00:01:00+10:00",
            normalization_version="cdr-domain-v1",
        )


def test_overlapping_tier_ranges_fail_before_disk(tmp_path: Path) -> None:
    accounting, projections = observation()
    first = projections["product_facts"][0]
    first.update(
        fact_id="tier-one", kind="tier", canonical_key="range.amount",
        value_type="range", value_number=None, min_value=0.0, max_value=100.0,
    )
    first["document"].update(
        fact_id="tier-one", kind="tier", canonical_key="range.amount",
        value_type="range", value_number=None, min_value=0.0, max_value=100.0,
        source_pattern="depositRates[].tiers[]",
        qualifiers_json='{"groupId": "parent"}', unit="AUD",
    )
    second = json.loads(json.dumps(first))
    second.update(fact_id="tier-two", min_value=50.0, max_value=200.0)
    second["document"].update(
        fact_id="tier-two", min_value=50.0, max_value=200.0
    )
    projections["product_facts"] = [first, second]

    with pytest.raises(ObservationDatabaseError, match="tier ranges overlap"):
        build_observation_database(
            tmp_path / "banks.sqlite",
            accounting=accounting,
            projections=projections,
            generated_at="2026-05-25T00:01:00+10:00",
            normalization_version="cdr-domain-v1",
        )


def test_product_document_details_completeness_is_bound_to_accounting(tmp_path: Path):
    accounting, projections = observation()
    projections["products"][0]["document"]["details_complete"] = False
    with pytest.raises(ObservationDatabaseError, match="outside its contract"):
        build_observation_database(
            tmp_path / "banks.sqlite",
            accounting=accounting,
            projections=projections,
            generated_at="2026-05-25T00:01:00+10:00",
            normalization_version="cdr-domain-v1",
        )


def test_database_generated_at_must_match_observation_date(tmp_path: Path):
    accounting, projections = observation()
    with pytest.raises(ObservationDatabaseError, match="observation date"):
        build_observation_database(
            tmp_path / "banks.sqlite",
            accounting=accounting,
            projections=projections,
            generated_at="2027-05-25T00:01:00+10:00",
            normalization_version="cdr-domain-v1",
        )


def test_unreconciled_accounting_fails_before_disk(tmp_path: Path):
    accounting, projections = observation()
    accounting["summary"]["products"]["consumer_visible"] = 0
    with pytest.raises(ObservationDatabaseError, match="summary"):
        build_observation_database(
            tmp_path / "banks.sqlite",
            accounting=accounting,
            projections=projections,
            generated_at="2026-05-25T00:01:00+10:00",
            normalization_version="cdr-domain-v1",
        )
