"""Reuse proof regressions using retained September 7 CDR business responses.

Ledger/journal metadata and fault mutations are test controls. These tests do not
claim new live observations or use invented financial products/rates.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

import cdr_daily
import cdr_same_day_reuse as reuse
from cdr_atomic import atomic_write_json, canonical_json_bytes
from cdr_attempt_evidence_promotion import AttemptEvidencePromotionError, promote_attempt_evidence
from cdr_clean_export import parse_banks_run, summary_counts
from cdr_compatibility import ProductIndexTracker
from cdr_finalization import finalize_observation, verify_completion_marker
from cdr_ingest_support import filesystem_product_id_directory, next_link
from cdr_outputs import rebuild_run_db
from cdr_raw_attempt_journal import RawAttemptJournal


DATE = "2026-09-07"
CAPTURE = "2026-09-06T15:03:56.544797Z"  # September 7 in Hobart.
FIXTURES = Path(__file__).parent / "fixtures"
CANARY = FIXTURES / "cdr-canary-2026-09-07"


def _record(bank="Border Bank"):
    if bank == "Defence Bank":
        wrapper = json.loads((FIXTURES / "cdr-september7" / "defence.json").read_bytes())["product_detail"]
        body, url, dataset = canonical_json_bytes(wrapper["body"]), wrapper["url"], "TD"
    else:
        body = (CANARY / f"{bank}-null-detail.json").read_bytes()
        data = json.loads(body)
        url = data["links"]["self"]
        dataset = "Savings" if bank == "Border Bank" else "Mortgage"
    data = json.loads(body)["data"]
    brand = {"brand_name": bank, "legal_entity_name": data.get("brandName") or data.get("brand") or bank,
             "endpoint_url": url.rsplit("/", 1)[0]}
    identity = "\x1f".join(brand[key].strip().lower() for key in ("endpoint_url", "legal_entity_name", "brand_name"))
    return {
        "body": body, "url": url, "pid": data["productId"], "dataset": dataset,
        "provider": bank, "brand": brand,
        "state": {**brand, "provider_dir": bank, "provider_uid": "legacy-prd:" + hashlib.sha256(identity.encode()).hexdigest(),
                  "identity_status": "derived_legacy", "state": "complete", "failure_records": 0},
    }


def _leaf(run, row):
    return run / "banks" / row["dataset"] / row["provider"] / row.get("fallback_name", "_same_day") / filesystem_product_id_directory(row["pid"])


def _seed(run, row):
    leaf = _leaf(run, row)
    leaf.mkdir(parents=True, exist_ok=True)
    (leaf / "product-detail.json").write_bytes(row["body"])
    (leaf / "product-id.txt").write_text(row["pid"] + "\n", encoding="utf-8")


def _attempt(journal, row, *, status=200, pid=None, captured=CAPTURE):
    return journal.record(
        row["provider"], request_url=row["url"], status=status,
        outcome="success" if status == 200 else "http_error", body=row["body"],
        started_at=captured, completed_at=captured,
        context={"phase": "product_detail", "provider": row["provider"], "product_id": pid or row["pid"]},
    )


def _status(run, journal, records):
    banks = run / "banks"
    banks.mkdir(parents=True, exist_ok=True)
    (banks / "failures.jsonl").touch()
    status = {
        "total": 0, "incomplete": False, "corrupt_records": 0, "unattributed_records": 0,
        "failure_provenance_complete": True, "by_provider": {},
        "register_provenance_complete": True,
        "register_attempts": [{"ok": True, "sha256": hashlib.sha256(records[0]["body"]).hexdigest()}],
        "providers_registered": len(records), "providers_attempted": len(records),
        "provider_states": [copy.deepcopy(row["state"]) for row in records],
        "raw_attempt_journal": {**journal.summary(), "path": journal.root.relative_to(run).as_posix(),
                                "path_resolution": "relative_to_ingest_run_root", "retention": "follows_ingest_run_root"},
    }
    atomic_write_json(banks / "ingest-status.json", status)
    return status


def _export(run, export, _db=None, **_):
    banks = parse_banks_run(run)
    counts = summary_counts(banks)
    rebuild_run_db(export / "local-cdr.sqlite", DATE, banks)
    result = {"run_date": DATE, "banks_counts": counts}
    atomic_write_json(export / "dashboard-cache" / "latest.json", result)
    return result


def _observation(tmp_path, *, name="primary", records=None, captured_records=None, parent=None,
                 status_code=200, context_pid=None, captured=CAPTURE, alter_database=False,
                 legacy_summary=None, registered_records=None):
    records = records or [_record()]
    state, runs = tmp_path / "data" / "state", tmp_path / "data" / "runs"
    export = runs / DATE / "_exports" if name == "primary" else runs / DATE / "_revisions" / name / "_exports"
    run = tmp_path / "scratch" / name / DATE
    journal = RawAttemptJournal(run / "_raw-attempt-journals-v1", "reuse-" + name)
    for row in records:
        _seed(run, row)
    for row in records if captured_records is None else captured_records:
        _attempt(journal, row, status=status_code, pid=context_pid, captured=captured)
    _status(run, journal, registered_records or records)
    result = _export(run, export)
    if alter_database:
        with sqlite3.connect(export / "local-cdr.sqlite") as db:
            detail = json.loads(db.execute("SELECT details_json FROM bank_products LIMIT 1").fetchone()[0])
            detail["description"] = "Fault-injected mismatch with retained response"
            db.execute("UPDATE bank_products SET details_json=?", (json.dumps(detail),))
    promote_attempt_evidence(run, export)
    if legacy_summary:
        status = json.loads((export / "ingest-status.json").read_bytes())
        pointer = status["raw_attempt_journal"]
        manifest_path = export / pointer["promotion_manifest_path"]
        manifest = json.loads(manifest_path.read_bytes())
        manifest["journal"].setdefault("observed_at", captured)
        pointer.setdefault("observed_at", captured)
        if legacy_summary != "pointer-only":
            manifest["journal"].pop("observed_at")
        if legacy_summary != "manifest-only":
            pointer.pop("observed_at")
        atomic_write_json(manifest_path, manifest)
        pointer["promotion_manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        atomic_write_json(export / "ingest-status.json", status)
    marker = state / (f"{DATE}.done.json" if name == "primary" else f"{DATE}.revision.{name}.json")
    finalized = finalize_observation(export, state, marker, observation_date=DATE, result=result, parent_generation_id=parent)
    return state, export, finalized


def _bytes(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_reuses_exact_raw_bytes_with_original_time_and_no_new_http_attempt(tmp_path):
    state, export, marker = _observation(tmp_path)
    before = _bytes(tmp_path / "data")
    plan = reuse.prepare_same_day_reuse(state, DATE)
    stage = tmp_path / "new" / DATE
    reuse.seed_same_day_reuse(plan, stage)
    row = _record()
    assert (_leaf(stage, row) / "product-detail.json").read_bytes() == row["body"]
    assert not (stage / "_raw-attempt-journals-v1").exists()
    evidence = plan.manifest["reused"][0]
    assert evidence["captured_at_utc"] == CAPTURE
    assert evidence["body_sha256"] == hashlib.sha256(row["body"]).hexdigest()
    assert plan.manifest["baseline"]["generation_id"] == marker["generation_id"]
    assert _bytes(tmp_path / "data") == before
    assert len(parse_banks_run(stage)["products"]) == 1


def test_selected_revision_and_original_ancestor_supply_different_products(tmp_path):
    border, greater = _record(), _record("Greater Bank Limited")
    state, _, primary = _observation(tmp_path, records=[border])
    _, _, revision = _observation(tmp_path, name="improved", records=[border, greater], captured_records=[greater], parent=primary["generation_id"])
    plan = reuse.prepare_same_day_reuse(state, DATE)
    assert plan.manifest["baseline"]["generation_id"] == revision["generation_id"]
    assert len(plan.bodies) == 2
    assert {row["source_generation_id"] for _, row in plan.bodies} == {primary["generation_id"], revision["generation_id"]}


def test_legacy_finalized_summary_verifies_without_rewriting_originals(tmp_path):
    state, _, _ = _observation(tmp_path, legacy_summary="both")
    before = _bytes(tmp_path / "data")
    plan = reuse.prepare_same_day_reuse(state, DATE)
    assert plan.manifest["reused"][0]["captured_at_utc"] == CAPTURE
    assert _bytes(tmp_path / "data") == before


@pytest.mark.parametrize("legacy", ["pointer-only", "manifest-only"])
def test_partial_summary_field_deletion_does_not_enable_legacy_compatibility(tmp_path, legacy):
    state, _, _ = _observation(tmp_path, legacy_summary=legacy)
    with pytest.raises(AttemptEvidencePromotionError):
        reuse.prepare_same_day_reuse(state, DATE)


@pytest.mark.parametrize("options", [
    {"status_code": 500}, {"context_pid": "wrong-id"}, {"alter_database": True},
    {"captured": "2026-09-05T15:03:56Z"},
])
def test_unsafe_or_nonmatching_raw_proof_refuses_before_seeding(tmp_path, options):
    state, _, _ = _observation(tmp_path, **options)
    before = _bytes(tmp_path / "data")
    with pytest.raises(ValueError):
        reuse.prepare_same_day_reuse(state, DATE)
    assert _bytes(tmp_path / "data") == before


@pytest.mark.parametrize("artifact", ["local-cdr.sqlite", "raw-body"])
def test_changed_finalized_artifacts_cannot_be_reuse_truth(tmp_path, artifact):
    state, export, _ = _observation(tmp_path)
    path = export / artifact if artifact != "raw-body" else next(export.rglob("*.body"))
    with path.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="artifact"):
        reuse.prepare_same_day_reuse(state, DATE)


@pytest.mark.parametrize("suffix", ["-wal", "-journal"])
def test_empty_read_sidecars_are_preserved_but_pending_writes_refuse(tmp_path, suffix):
    state, export, _ = _observation(tmp_path)
    sidecar = Path(str(export / "local-cdr.sqlite") + suffix)
    sidecar.write_bytes(b"")
    assert len(reuse.prepare_same_day_reuse(state, DATE).bodies) == 1
    assert sidecar.exists() and sidecar.read_bytes() == b""
    sidecar.write_bytes(b"pending")
    with pytest.raises(ValueError, match="pending writes"):
        reuse.prepare_same_day_reuse(state, DATE)
    assert sidecar.read_bytes() == b"pending"


def test_existing_or_colliding_scratch_is_never_overwritten(tmp_path):
    state, _, _ = _observation(tmp_path)
    plan = reuse.prepare_same_day_reuse(state, DATE)
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "keep").write_bytes(b"keep")
    with pytest.raises(ValueError, match="empty isolated"):
        reuse.seed_same_day_reuse(plan, stage)
    assert (stage / "keep").read_bytes() == b"keep"


def test_custom_empty_stage_cannot_nest_in_preserved_export(tmp_path):
    state, export, _ = _observation(tmp_path)
    plan = reuse.prepare_same_day_reuse(state, DATE)
    before = _bytes(tmp_path / "data")
    with pytest.raises(ValueError, match="overlaps preserved"):
        reuse.seed_same_day_reuse(plan, export / "new-empty-stage")
    assert _bytes(tmp_path / "data") == before


def test_missing_detail_name_preserves_index_derived_product_key(tmp_path):
    row = _record()
    payload = json.loads(row["body"])
    row["fallback_name"] = payload["data"].pop("name")
    row["body"] = canonical_json_bytes(payload)
    state, _, _ = _observation(tmp_path, records=[row])
    plan = reuse.prepare_same_day_reuse(state, DATE)
    stage = tmp_path / "new" / DATE
    reuse.seed_same_day_reuse(plan, stage)
    assert plan.manifest["reused"][0]["fallback_product_name"] == row["fallback_name"]
    product = parse_banks_run(stage)["products"][0]
    assert product["product_name"] == row["fallback_name"]
    assert (_leaf(stage, row) / "product-detail.json").read_bytes() == row["body"]


def test_supported_product_id_alias_preserves_exact_raw_identity(tmp_path):
    row = _record()
    payload = json.loads(row["body"])
    payload["data"]["id"] = payload["data"].pop("productId")
    row["body"] = canonical_json_bytes(payload)
    state, _, _ = _observation(tmp_path, records=[row])
    assert reuse.prepare_same_day_reuse(state, DATE).manifest["reused"][0]["product_id"] == row["pid"]


def _pages():
    return [json.loads(path.read_bytes()) for path in sorted(CANARY.glob("Defence Bank-index-*.json"))]


def _fresh_run(stage, row, pages, *, incomplete=False):
    journal = RawAttemptJournal(stage / "_raw-attempt-journals-v1", "fresh-index")
    tracker, total = ProductIndexTracker(), 0
    url = row["brand"]["endpoint_url"]
    index_dir = stage / "banks" / "_holders" / row["provider"] / "_products-index"
    index_dir.mkdir(parents=True, exist_ok=True)
    for number, page in enumerate(pages, 1):
        body = canonical_json_bytes(page)
        (index_dir / f"page-{number:04d}.json").write_bytes(body)
        journal.record(str(number), request_url=url, status=200, outcome="success", body=body,
                       started_at=CAPTURE, completed_at=CAPTURE,
                       context={"phase": "products_index", "provider": row["provider"], "page": number})
        for product in page["data"]["products"]:
            tracker.observe(product["productId"], product)
            total += 1
        url = next_link(page, url)
    status = _status(stage, journal, [row])
    status["index_diagnostics"] = {row["provider"]: tracker.summary(pages=len(pages), raw_records=total,
                                                                         complete=not incomplete, meta=pages[-1]["meta"])}
    atomic_write_json(stage / "banks" / "ingest-status.json", status)
    return journal


def _complete_listing_without(row, *, empty=False):
    pages = _pages()
    products = {item["productId"]: item for page in pages for item in page["data"]["products"]}
    products.pop(row["pid"])
    selected = [] if empty else list(products.values())
    # Protocol fault/control derived solely from captured real index rows.
    return [{"data": {"products": selected}, "links": {"self": row["brand"]["endpoint_url"]},
             "meta": {"totalRecords": len(selected), "totalPages": 1}}]


def test_only_complete_nonempty_index_withdraws_absent_seed_and_retains_body(tmp_path):
    row = _record("Defence Bank")
    state, _, _ = _observation(tmp_path, records=[row])
    stage = tmp_path / "repair" / DATE
    reuse.seed_same_day_reuse(reuse.prepare_same_day_reuse(state, DATE), stage)
    journal = _fresh_run(stage, row, _complete_listing_without(row))
    attempts = journal.summary()["attempts"]
    reuse.reconcile_same_day_reuse(stage)
    status = json.loads((stage / "banks" / "ingest-status.json").read_bytes())
    manifest = status["same_day_reuse"]
    assert manifest["withdrawals"][0]["product_id"] == row["pid"]
    proof = manifest["withdrawal_indexes"][row["provider"]]
    assert proof["complete"] and row["pid"] not in proof["observed_product_ids"]
    assert (_leaf(stage, row) / "withdrawn-product-detail.body").read_bytes() == row["body"]
    assert not parse_banks_run(stage)["products"]
    assert journal.summary()["attempts"] == attempts
    expected_digest = reuse._digest({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    assert manifest["manifest_sha256"] == expected_digest


def test_real_empty_catalogue_retains_captured_product_and_queues_reconfirmation(tmp_path):
    row = _record("Bank of Melbourne")
    state, _, _ = _observation(tmp_path, records=[row])
    stage = tmp_path / "repair" / DATE
    reuse.seed_same_day_reuse(reuse.prepare_same_day_reuse(state, DATE), stage)
    empty = json.loads((CANARY / "Bank of Melbourne-empty-index.json").read_bytes())
    _fresh_run(stage, row, [empty])
    reuse.reconcile_same_day_reuse(stage)
    status = json.loads((stage / "banks" / "ingest-status.json").read_bytes())
    manifest = status["same_day_reuse"]
    assert not manifest["withdrawals"] and not manifest["withdrawal_indexes"]
    assert manifest["unconfirmed"] == [{"provider_dir": row["provider"], "product_id": row["pid"]}]
    assert (_leaf(stage, row) / "product-detail.json").read_bytes() == row["body"]
    assert len(parse_banks_run(stage)["products"]) == 1
    assert status["incomplete"] and status["by_provider"][row["provider"]] == 1
    assert any(q["provider_dir"] == row["provider"] and q["phase"] == "products_index"
               for q in status["unresolved_requests"])


def test_reconciliation_preserves_other_holders_authentication_exemption(tmp_path):
    from app_payload_authentication import authentication_exclusions
    from cdr_ingest_support import append_failure
    row, rejected = _record("Bank of Melbourne"), _record("Greater Bank Limited")
    state, _, parent = _observation(tmp_path, records=[row])
    stage = tmp_path / "repair" / DATE
    reuse.seed_same_day_reuse(reuse.prepare_same_day_reuse(state, DATE), stage)
    empty = json.loads((CANARY / "Bank of Melbourne-empty-index.json").read_bytes())
    journal = _fresh_run(stage, row, [empty])
    path = stage / "banks" / "ingest-status.json"
    diagnostics = json.loads(path.read_bytes())["index_diagnostics"]
    status = _status(stage, journal, [row, rejected])
    status["index_diagnostics"] = diagnostics
    status["provider_states"][0]["failure_categories"] = {}
    status["provider_states"][1].update(state="partial", failure_records=60,
        failure_categories={"public_endpoint_auth_required": 60})
    status["by_provider"] = {rejected["provider"]: 60}
    for _ in range(60):
        append_failure(stage / "banks", {"bank": rejected["provider"], "phase": "products_index",
            "status": 400, "snippet": "This service requires API Key"})
    atomic_write_json(path, status)
    reuse.reconcile_same_day_reuse(stage)
    final = _finalize_repair(state, stage, parent, "auth-reconciliation")
    contract = json.loads((state / final["export_contract_path"]).read_bytes())
    assert contract["coverage"]["failure_records"] == 61
    assert authentication_exclusions(contract)["failure_records"] == 60
    assert authentication_exclusions(contract)["providers_partial"] == 1


def test_real_identical_duplicates_confirm_present_seed_without_extra_failure(tmp_path):
    row = _record("Defence Bank")
    state, _, _ = _observation(tmp_path, records=[row])
    stage = tmp_path / "repair" / DATE
    reuse.seed_same_day_reuse(reuse.prepare_same_day_reuse(state, DATE), stage)
    _fresh_run(stage, row, _pages())
    reuse.reconcile_same_day_reuse(stage)
    status = json.loads((stage / "banks" / "ingest-status.json").read_bytes())
    assert not status["same_day_reuse"]["withdrawals"]
    assert not status["same_day_reuse"]["unconfirmed"]
    assert status["total"] == 0
    assert (_leaf(stage, row) / "product-detail.json").read_bytes() == row["body"]


@pytest.mark.parametrize("mutation", ["capped", "duplicate", "missing-total", "unbound-page"])
def test_ambiguous_omission_keeps_cached_product_and_marks_uncertainty(tmp_path, mutation):
    row = _record("Defence Bank")
    state, _, _ = _observation(tmp_path, records=[row])
    stage = tmp_path / "repair" / DATE
    reuse.seed_same_day_reuse(reuse.prepare_same_day_reuse(state, DATE), stage)
    pages = _complete_listing_without(row)
    if mutation == "duplicate":
        pages[0]["data"]["products"].append(pages[0]["data"]["products"][0])
        pages[0]["meta"]["totalRecords"] += 1
    if mutation == "missing-total":
        del pages[0]["meta"]["totalRecords"]
    _fresh_run(stage, row, pages, incomplete=mutation == "capped")
    if mutation == "unbound-page":
        path = next((stage / "banks" / "_holders").rglob("page-*.json"))
        changed = json.loads(path.read_bytes())
        changed["data"]["products"] = []
        path.write_bytes(canonical_json_bytes(changed))
    reuse.reconcile_same_day_reuse(stage)
    status = json.loads((stage / "banks" / "ingest-status.json").read_bytes())
    assert not status["same_day_reuse"]["withdrawals"]
    assert status["same_day_reuse"]["unconfirmed"]
    assert status["incomplete"]
    assert status["unresolved_requests"][0]["provider_dir"] == row["provider"]
    assert status["unresolved_requests_complete"]
    assert (_leaf(stage, row) / "product-detail.json").read_bytes() == row["body"]


@pytest.mark.parametrize("extra", [[], ["--force", "--date", "2026-09-06"], ["--force", "--daemon"],
                                   ["--force", "--db", "external.sqlite"]])
def test_daily_reuse_requires_force_today_and_isolated_immutable_database(tmp_path, monkeypatch, extra):
    monkeypatch.setattr(cdr_daily, "local_date", lambda: DATE)
    monkeypatch.setattr(cdr_daily, "ensure_runtime_data_writable", lambda *_: None)
    monkeypatch.setattr(cdr_daily, "run_ingest", lambda *_: pytest.fail("unsafe mode started live ingest"))
    args = cdr_daily.parse_args(["--runs", str(tmp_path / "runs"), "--state", str(tmp_path / "state"),
                                 "--resume-same-day", *extra])
    assert cdr_daily.run_once(args) == 2


def test_daily_refuses_unverified_source_before_requests_or_pointer_repair(tmp_path, monkeypatch):
    state, export, _ = _observation(tmp_path)
    (export / "local-cdr.sqlite").write_bytes(b"corrupt")
    before = _bytes(state)
    monkeypatch.setattr(cdr_daily, "local_date", lambda: DATE)
    monkeypatch.setattr(cdr_daily, "ensure_runtime_data_writable", lambda *_: None)
    monkeypatch.setattr(cdr_daily, "run_ingest", lambda *_: pytest.fail("unsafe source started live ingest"))
    monkeypatch.setattr(cdr_daily, "verified_pointer_marker_for_date", lambda *_: pytest.fail("pointer repair is a mutation"))
    args = cdr_daily.parse_args(["--runs", str(tmp_path / "data" / "runs"), "--state", str(state),
                                 "--resume-same-day", "--force", "--no-ram-stage"])
    assert cdr_daily.run_once(args) == 2
    assert _bytes(state) == before


@pytest.mark.parametrize("ram_stage", [False, True])
def test_daily_repair_promotes_bound_reuse_and_parents_selected_revision(tmp_path, monkeypatch, ram_stage):
    row = _record("Defence Bank")
    state, primary_export, primary = _observation(tmp_path, records=[row])
    _, selected_export, selected = _observation(tmp_path, name="selected", records=[row], parent=primary["generation_id"])
    before_primary, before_selected = _bytes(primary_export), _bytes(selected_export)
    monkeypatch.setattr(cdr_daily, "local_date", lambda: DATE)
    monkeypatch.setattr(cdr_daily, "ensure_runtime_data_writable", lambda *_: None)
    monkeypatch.setattr(cdr_daily, "is_raspberry_pi", lambda: False)
    monkeypatch.setattr(cdr_daily, "write_sanity_report", lambda *_: None)
    monkeypatch.setattr(cdr_daily, "_emit_day_manifest", lambda *_: None)
    monkeypatch.setattr(cdr_daily, "build_outputs", _export)
    monkeypatch.setattr(cdr_daily, "verified_pointer_marker_for_date", lambda *_: pytest.fail("reuse must not repair pointers"))

    def ingest(_scripts, output, date, _extra):
        run = output / date
        assert (_leaf(run, row) / "product-detail.json").read_bytes() == row["body"]
        assert not (run / "_raw-attempt-journals-v1").exists()
        _fresh_run(run, row, _pages())

    monkeypatch.setattr(cdr_daily, "run_ingest", ingest)
    argv = ["--runs", str(tmp_path / "data" / "runs"), "--state", str(state),
            "--force", "--resume-same-day", "--ram-root", str(tmp_path / "ram"),
            "--ram-stage" if ram_stage else "--no-ram-stage"]
    assert cdr_daily.run_once(cdr_daily.parse_args(argv)) == 1
    pointer = json.loads((state / "observation-pointers-v2" / "latest-observation.json").read_bytes())
    assert pointer["generation_id"] != selected["generation_id"]
    marker = json.loads((state / pointer["marker_path"]).read_bytes())
    assert verify_completion_marker(marker, state, DATE)
    event = json.loads((state / "ledger-v2" / "events" / DATE / f"{marker['generation_id']}.json").read_bytes())
    assert event["parent_generation_id"] == selected["generation_id"]
    export = state.parent / pointer["export_path"]
    status = json.loads((export / "ingest-status.json").read_bytes())
    assert status["same_day_reuse"]["baseline"]["generation_id"] == selected["generation_id"]
    assert status["same_day_reuse"]["reused"][0]["captured_at_utc"] == CAPTURE
    assert status["raw_attempt_journal"]["attempts"] == 3  # Only the three new index pages.
    assert _bytes(primary_export) == before_primary
    assert _bytes(selected_export) == before_selected


def _new_identity(row, *, legal=None, suffix="v2"):
    result = copy.deepcopy(row)
    result["brand"]["endpoint_url"] = row["brand"]["endpoint_url"].replace("/v1/", f"/{suffix}/")
    if legal:
        result["brand"]["legal_entity_name"] = legal
    material = "\x1f".join(result["brand"][key].strip().lower() for key in ("endpoint_url", "legal_entity_name", "brand_name"))
    result["state"].update(result["brand"], provider_uid="legacy-prd:" + hashlib.sha256(material.encode()).hexdigest())
    return result


def _migrated_pages(original, migrated):
    pages = _pages()
    for page in pages:
        page["links"] = {key: value.replace(original["brand"]["endpoint_url"], migrated["brand"]["endpoint_url"])
                         for key, value in page["links"].items()}
    return pages


def _finalize_repair(state, stage, parent, label):
    export = state.parent / "runs" / DATE / "_revisions" / label / "_exports"
    result = _export(stage, export)
    promote_attempt_evidence(stage, export)
    return finalize_observation(export, state, state / f"{DATE}.revision.{label}.json",
                                observation_date=DATE, result=result, parent_generation_id=parent["generation_id"])


def test_endpoint_only_migration_is_bound_and_reuses_original_capture_again(tmp_path):
    original = _record("Defence Bank")
    migrated = _new_identity(original)
    state, _, parent = _observation(tmp_path, records=[original])
    stage = tmp_path / "migration" / DATE
    reuse.seed_same_day_reuse(reuse.prepare_same_day_reuse(state, DATE), stage)
    _fresh_run(stage, migrated, _migrated_pages(original, migrated))
    reuse.reconcile_same_day_reuse(stage)
    status = json.loads((stage / "banks" / "ingest-status.json").read_bytes())
    transition = status["same_day_reuse"]["endpoint_transitions"][original["provider"]]
    assert transition["from"]["endpoint_url"] == original["brand"]["endpoint_url"]
    assert transition["to"]["endpoint_url"] == migrated["brand"]["endpoint_url"]
    assert transition["current_register_evidence"] == status["register_attempts"]
    assert not status["same_day_reuse"]["identity_blocks"]
    finalized = _finalize_repair(state, stage, parent, "migration")
    plan = reuse.prepare_same_day_reuse(state, DATE)
    assert plan.manifest["baseline"]["generation_id"] == finalized["generation_id"]
    assert plan.manifest["reused"][0]["source_generation_id"] == parent["generation_id"]
    assert plan.bodies[0][0].read_bytes() == original["body"]


def test_register_omission_keeps_proven_identity_for_the_next_recovery(tmp_path):
    original, new = _record(), _record("Greater Bank Limited")
    state, _, parent = _observation(tmp_path, records=[original])
    stage = tmp_path / "omitted" / DATE
    reuse.seed_same_day_reuse(reuse.prepare_same_day_reuse(state, DATE), stage)
    journal = RawAttemptJournal(stage / "_raw-attempt-journals-v1", "omitted")
    _seed(stage, new)
    _attempt(journal, new)
    _status(stage, journal, [new])  # A current register observation omits Border.
    reuse.reconcile_same_day_reuse(stage)
    status = json.loads((stage / "banks" / "ingest-status.json").read_bytes())
    assert status["providers_registered"] == status["providers_attempted"] == len(status["provider_states"]) == 1
    assert status["retained_provider_states"][0]["provider_uid"] == original["state"]["provider_uid"]
    assert status["same_day_reuse"]["unconfirmed"]
    finalized = _finalize_repair(state, stage, parent, "omitted")
    plan = reuse.prepare_same_day_reuse(state, DATE)
    assert plan.manifest["baseline"]["generation_id"] == finalized["generation_id"]
    assert len(plan.bodies) == 2


def test_legal_identity_change_blocks_only_that_provider_and_keeps_other_repairs(tmp_path):
    original, new = _record("Defence Bank"), _record("Greater Bank Limited")
    wrong = _new_identity(original, legal="Fault injected different legal identity")
    state, _, parent = _observation(tmp_path, records=[original])
    stage = tmp_path / "blocked" / DATE
    reuse.seed_same_day_reuse(reuse.prepare_same_day_reuse(state, DATE), stage)
    journal = _fresh_run(stage, wrong, _migrated_pages(original, wrong))
    diagnostics = json.loads((stage / "banks" / "ingest-status.json").read_bytes())["index_diagnostics"]
    _seed(stage, new)
    _attempt(journal, new)
    untrusted = {**new, "provider": original["provider"]}
    _seed(stage, untrusted)  # Wrong-provider candidate remains evidence, not an exported product.
    status = _status(stage, journal, [wrong, new])
    status["index_diagnostics"] = diagnostics
    atomic_write_json(stage / "banks" / "ingest-status.json", status)
    reuse.reconcile_same_day_reuse(stage)
    status = json.loads((stage / "banks" / "ingest-status.json").read_bytes())
    assert original["provider"] in status["same_day_reuse"]["identity_blocks"]
    assert not status["same_day_reuse"]["endpoint_transitions"]
    assert status["by_status"]["provider_identity_migration_blocked"] == 1
    assert (_leaf(stage, untrusted) / "identity-blocked-product-detail.body").read_bytes() == new["body"]
    assert len(parse_banks_run(stage)["products"]) == 2
    _finalize_repair(state, stage, parent, "blocked")
    assert len(reuse.prepare_same_day_reuse(state, DATE).bodies) == 2


def test_duplicate_legal_brand_mapping_cannot_authorize_endpoint_migration():
    from cdr_reuse_identity import endpoint_transition

    original = _record("Defence Bank")
    migrated = _new_identity(original)
    before = {original["provider"]: original["state"]}
    after = {migrated["provider"]: migrated["state"]}
    assert endpoint_transition(before, after, original["provider"])
    after["ambiguous"] = {**migrated["state"], "provider_dir": "ambiguous"}
    assert endpoint_transition(before, after, original["provider"]) is None


def test_register_reordering_cannot_duplicate_retained_provider_products(tmp_path):
    original, new = _record("Defence Bank"), _record("Greater Bank Limited")
    other = _new_identity(original)
    suffix = "Defence Bank_product_defencebank_com_au"
    old_other = {**other, "provider": suffix, "state": {**other["state"], "provider_dir": suffix}}
    state, _, parent = _observation(tmp_path, records=[original], registered_records=[original, old_other])
    stage = tmp_path / "reordered" / DATE
    reuse.seed_same_day_reuse(reuse.prepare_same_day_reuse(state, DATE), stage)
    # Same two register identities, reversed order; A now gets the suffixed folder.
    alias = {**original, "provider": suffix, "state": {**original["state"], "provider_dir": suffix}}
    journal = RawAttemptJournal(stage / "_raw-attempt-journals-v1", "reordered")
    for row in (alias, new):
        _seed(stage, row)
        _attempt(journal, row)
    _status(stage, journal, [other, alias, new])
    reuse.reconcile_same_day_reuse(stage)
    status = json.loads((stage / "banks" / "ingest-status.json").read_bytes())
    assert status["same_day_reuse"]["directory_blocks"][suffix]["retained_provider_dir"] == original["provider"]
    assert (_leaf(stage, alias) / "identity-blocked-product-detail.body").read_bytes() == original["body"]
    products = parse_banks_run(stage)["products"]
    assert len(products) == 2
    assert sum(row["product_id"] == original["pid"] for row in products) == 1
    _finalize_repair(state, stage, parent, "reordered")
    next_plan = reuse.prepare_same_day_reuse(state, DATE)
    assert len(next_plan.bodies) == 2
    assert sum(row["product_id"] == original["pid"] for _, row in next_plan.bodies) == 1
