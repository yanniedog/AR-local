"""Real captured fact roundtrip plus deliberately invalid protocol controls."""
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3

import pytest

import app_payload_product_evidence as evidence
from app_payload_product_evidence_contract import Limits, canonical, digest, fact
from cdr_clean_export import bank_product_key
from cdr_export_contract import build_contract
from cdr_outputs import ensure_db, insert_rows
from cdr_product_facts import clean_fact_rows

DAY = "2026-05-19"


def make_contract(database, root):
    retained = json.loads((Path(__file__).parent / "fixtures/publication-accounting-2026-09-22.json").read_bytes())
    payload = build_contract(database.parent, observation_date=DAY, observed_at=DAY + "T01:00:00+11:00",
                             observation_state="partial", source_path=f"runs/{DAY}/_exports",
                             completion_marker_path=f"{DAY}.done.json", coverage=retained["coverage"],
                             provider_states=retained["provider_states"], register_hashes=retained["register_hashes"],
                             normalization_version="legacy-v1",
                             artifacts=[dict(path="local-cdr.sqlite", bytes=database.stat().st_size,
                                             sha256=digest(database.read_bytes()))])
    path = root / "state/contract.json"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(canonical(payload))
    return path


@pytest.fixture
def source(tmp_path):
    captured = json.loads((Path(__file__).parent / "fixtures/product_facts_real_2026-05-19.json").read_bytes())
    rows = []
    for product in captured["products"]:
        record = product["record"]
        base = dict(dataset=product["dataset"], provider=product["provider"], product_id=record["productId"],
                    product_name=record.get("name") or "Captured product", category=record.get("productCategory", ""))
        base["product_key"] = bank_product_key(base)
        rows.extend(dict(run_date=DAY, **row) for row in clean_fact_rows(record, base))
    database = tmp_path / "exports/local-cdr.sqlite"
    database.parent.mkdir()
    with closing(sqlite3.connect(database)) as connection:
        ensure_db(connection)
        insert_rows(connection, "bank_product_facts", rows)
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return database, make_contract(database, tmp_path), rows


def build(source, tmp_path, **kwargs):
    database, contract, _ = source
    output = tmp_path / "snapshot"
    value = evidence.prepare_snapshot(database, contract, output, **kwargs)
    return output, value


def mutate_db(source, root, sql, values=()):
    database, _, rows = source
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute(sql, values)
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return database, make_contract(database, root), rows


def test_real_captured_rows_roundtrip_and_source_unchanged(source, tmp_path):
    before = [path.read_bytes() for path in source[:2]]
    output, value = build(source, tmp_path, limits=replace(Limits(), page_rows=3))
    assert evidence.validate_snapshot(output) == value
    assert value["source"]["contract_normalization"] == "legacy-v1"
    assert value["source"]["fact_normalization"] == "cdr-product-facts-2"
    assert value["publication_authorized"] is False and value["selection_verified"] is False
    assert "null_empty" in value["scope"]
    assert value["totals"]["facts"] == len(source[2])
    for product in value["products"]:
        key = product["identity"]["product_key"]
        expected = {row["fact_id"]: fact({**row, "value_boolean": int(row["value_boolean"]) if row["value_boolean"] is not None else None})
                    for row in source[2] if row["product_key"] == key}
        assert {row["fact_id"]: row for row in evidence.iter_product_facts(output, key)} == expected
    assert [path.read_bytes() for path in source[:2]] == before


def test_deterministic_complete_bytes(source, tmp_path):
    first, _ = build(source, tmp_path)
    second = tmp_path / "second"
    evidence.prepare_snapshot(source[0], source[1], second)
    assert {p.name: p.read_bytes() for p in first.iterdir()} == {p.name: p.read_bytes() for p in second.iterdir()}


@pytest.mark.parametrize("sql,values", [
    ("UPDATE schema_meta SET value='next' WHERE key='normalization_version'", ()),
    ("UPDATE schema_meta SET value='999' WHERE key='version'", ()),
    ("UPDATE bank_product_facts SET run_date='2026-05-20'", ()),
    ("ALTER TABLE bank_product_facts ADD COLUMN new_field TEXT", ()),
    ("DROP INDEX idx_bank_product_facts_product", ()),
    ("UPDATE bank_product_facts SET source_value_json='NaN'", ()),
    ("UPDATE bank_product_facts SET source_value_json='1e400'", ()),
    ("UPDATE bank_product_facts SET qualifiers_json='[]'", ()),
    ("UPDATE bank_product_facts SET qualifiers_json=?", ('{"x":1,"x":2}',)),
    ("UPDATE bank_product_facts SET value_number=77", ()),
    ("UPDATE bank_product_facts SET product_name=''", ()),
    ("UPDATE bank_product_facts SET provider='changed' WHERE rowid=1", ()),
    ("UPDATE bank_product_facts SET mapping='invented'", ()),
    ("DELETE FROM bank_product_facts", ()),
])
def test_invalid_bound_database_never_completes(source, tmp_path, sql, values):
    source = mutate_db(source, tmp_path, sql, values)
    with pytest.raises((ValueError, sqlite3.Error)):
        build(source, tmp_path)
    assert not (tmp_path / "snapshot/snapshot.json").exists()


@pytest.mark.parametrize("limit", [
    dict(database_bytes=1), dict(facts=1), dict(product_facts=1), dict(pages=1, page_rows=1),
    dict(raw_bytes=1), dict(compressed_bytes=1), dict(page_raw_bytes=1024),
    dict(page_compressed_bytes=1), dict(index_bytes=1), dict(products=1),
])
def test_budget_refusal_never_silently_truncates(source, tmp_path, limit):
    with pytest.raises((ValueError, sqlite3.Error)):
        build(source, tmp_path, limits=replace(Limits(), **limit))
    assert not (tmp_path / "snapshot/snapshot.json").exists()


def test_source_hash_mismatch_refused(source, tmp_path):
    with source[0].open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="differs"):
        build(source, tmp_path)


@pytest.mark.parametrize("suffix", ["-wal", "-journal"])
def test_uncommitted_journal_refused(source, tmp_path, suffix):
    Path(str(source[0]) + suffix).write_bytes(b"pending")
    with pytest.raises(ValueError, match="journal"):
        build(source, tmp_path)


def test_existing_and_overlapping_outputs_preserved(source, tmp_path):
    output, _ = build(source, tmp_path)
    before = (output / "snapshot.json").read_bytes()
    for target in (output, source[0].parent / "snapshot", tmp_path, source[1].parent / "snapshot"):
        with pytest.raises(ValueError, match="destination"):
            evidence.prepare_snapshot(*source[:2], target)
    assert (output / "snapshot.json").read_bytes() == before


def test_unknown_original_scalar_and_pointer_survive():
    base = dict(dataset="Savings", provider="Protocol control", product_id="01", product_key="key", product_name="Control")
    rows = clean_fact_rows({"future": {"opaque": "000123", "url": "https://bank.example/terms", "empty": None}}, base)
    values = [fact({**row, "value_boolean": int(row["value_boolean"]) if row["value_boolean"] is not None else None}) for row in rows]
    opaque = next(row for row in values if row["source_path"] == "future.opaque")
    assert opaque["source_value"] == "000123"
    assert next(row for row in values if row["source_path"] == "future.url")["source_value"] == "https://bank.example/terms"
    assert not any(row["source_path"] == "future.empty" for row in values)


@pytest.mark.parametrize("change", ["missing", "bytes", "descriptor", "count", "generation", "authority", "traversal"])
def test_snapshot_verifier_rejects_detached_or_missing_evidence(source, tmp_path, change):
    output, manifest = build(source, tmp_path)
    page = manifest["products"][0]["pages"][0]
    if change == "missing":
        (output / page["name"]).unlink()
    elif change == "bytes":
        (output / page["name"]).write_bytes(b"changed")
    elif change == "descriptor":
        page["sha256"] = "0" * 64
    elif change == "count":
        manifest["totals"]["facts"] += 1
    elif change == "generation":
        manifest["source"]["generation_id"] += "changed"
    elif change == "authority":
        manifest["publication_authorized"] = True
    else:
        page["name"] = "../escape"
    (output / "snapshot.json").write_bytes(canonical(manifest))
    with pytest.raises(ValueError):
        evidence.validate_snapshot(output)


def test_undeclared_product_does_not_claim_withdrawal(source, tmp_path):
    output, _ = build(source, tmp_path)
    with pytest.raises(ValueError, match="not withdrawal"):
        list(evidence.iter_product_facts(output, "absent"))


def test_source_change_during_stream_leaves_no_marker(source, tmp_path, monkeypatch):
    original = evidence.write_page

    def changed(*args, **kwargs):
        page = original(*args, **kwargs)
        source[1].write_bytes(source[1].read_bytes() + b" ")
        return page

    monkeypatch.setattr(evidence, "write_page", changed)
    with pytest.raises(ValueError, match="changed"):
        build(source, tmp_path)
    assert not (tmp_path / "snapshot/snapshot.json").exists()


def test_source_contract_hash_tamper_is_not_accepted(source, tmp_path):
    contract = json.loads(source[1].read_bytes())
    contract["generation_id"] += "bad"
    source[1].write_bytes(canonical(contract))
    with pytest.raises(ValueError):
        build(source, tmp_path)


def test_increased_or_boolean_budget_refused(source, tmp_path):
    for limits in (replace(Limits(), pages=999999), replace(Limits(), facts=True)):
        with pytest.raises(ValueError, match="budget"):
            build(source, tmp_path, limits=limits)


def test_deadline_refusal_keeps_partial_without_completion(source, tmp_path, monkeypatch):
    original = evidence.write_page

    def expired(*args, **kwargs):
        page = original(*args, **kwargs)
        args[-1].deadline = 0
        return page

    monkeypatch.setattr(evidence, "write_page", expired)
    with pytest.raises(ValueError, match="deadline"):
        build(source, tmp_path)
    assert not (tmp_path / "snapshot/snapshot.json").exists()


def test_symlink_input_refused(source, tmp_path):
    alias = tmp_path / "alias.sqlite"
    try:
        alias.symlink_to(source[0])
    except OSError:
        pytest.skip("symlink creation not permitted on this host")
    with pytest.raises(ValueError, match="symlink"):
        evidence.prepare_snapshot(alias, source[1], tmp_path / "snapshot")


def test_validator_honours_reduced_aggregate_budget(source, tmp_path):
    output, _ = build(source, tmp_path)
    with pytest.raises(ValueError, match="budget"):
        evidence.validate_snapshot(output, limits=replace(Limits(), raw_bytes=1))


def test_forged_page_rebound_to_wrong_product_fails(source, tmp_path):
    import gzip
    output, manifest = build(source, tmp_path)
    descriptor = manifest["products"][0]["pages"][0]
    body = json.loads(gzip.decompress((output / descriptor["name"]).read_bytes()))
    body["product"]["product_id"] = "not-this-product"
    raw = canonical(body)
    blob = gzip.compress(raw, mtime=0)
    old_raw, old_bytes = descriptor["raw_bytes"], descriptor["bytes"]
    descriptor.update(sha256=digest(blob), bytes=len(blob), raw_bytes=len(raw))
    descriptor["name"] = "facts-" + descriptor["sha256"] + ".json.gz"
    (output / descriptor["name"]).write_bytes(blob)
    manifest["totals"]["raw_bytes"] += len(raw) - old_raw
    manifest["totals"]["compressed_bytes"] += len(blob) - old_bytes
    (output / "snapshot.json").write_bytes(canonical(manifest))
    with pytest.raises(ValueError, match="detached"):
        evidence.validate_snapshot(output)
