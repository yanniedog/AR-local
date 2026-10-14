"""Public capture/store/queue acceptance with retained real lender material."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest

from cdr_atomic import canonical_json_bytes
from cdr_public_rates_cdr import compile_record, inventory_from_compiled
from cdr_public_rates_collector import compiled_generation, write_candidate
from cdr_public_rates_candidate import read_candidate, programme_ids, selected_programmes
from cdr_public_rates_sources import source_inventory
from cdr_terms.acquisition import FetchPolicy, acquire_document
from cdr_terms.acquisition_batch import request_scope
from cdr_terms.acquisitions_queue import AcquisitionQueue
from cdr_terms.identity import digest
from cdr_terms.public_rates_store import PublicRateStore
from cdr_terms.store import EvidenceStore
from tests.test_public_rate_sources import capture

CDF = Path(__file__).parent / "fixtures/public_rates/nab-tailored-cdr-20261013.json"
WHEN = "2026-10-14T11:50:00Z"


def retained_product(store, *, generation="retained-public-fixture", observed_at=WHEN):
    body = CDF.read_bytes()
    envelope = json.loads(body)
    product = envelope["data"]
    url = envelope["links"]["self"]
    key = "public-cdr:" + product["productId"]
    observation = store.observe(provider="NAB", product_key=key, record=envelope, source_bytes=body,
                                observed_at=observed_at, ingest_id=generation)
    result = compile_record(product, provider_name="NAB", section="Mortgage", source_url=url,
                            source_sha256=hashlib.sha256(body).hexdigest(), checked_at=observed_at,
                            product_key=key, pointer="/data")
    receipt = {"generation_id": generation, "source_run_date": observed_at[:10], "observed_at": observed_at}
    with store.db:
        store.db.execute("INSERT INTO ingest_captures VALUES (?,?,?,?)", (generation, store.put_blob(canonical_json_bytes(receipt)), observed_at, 1))
        store.db.execute("INSERT INTO ingest_capture_attempts VALUES (?,?,?,?)", (generation, observed_at, observed_at, '{}'))
    PublicRateStore(store).record_compiled(observation, result)
    compiled = {"products": [result["product"]], "programmes": result["programmes"], "evidence": result["evidence"]}
    return observation, result, source_inventory(inventory_from_compiled(compiled))


def retain_reference_check(store, register, *, generation="retained-public-fixture", now=WHEN, fail=False, suffix=b"", acknowledge=True, unconditional=False):
    public = PublicRateStore(store)
    requests = public.queue_sources(register, ingest_id=generation, now=now)
    queue = AcquisitionQueue(store)
    request = queue.claim(now=now)
    assert request is not None and request["request_id"] in requests
    body, context = capture("nab-indicator")
    body += suffix
    check_id = digest([generation, now, "retained-public-reference-check"])
    if fail:
        store.record_check(document_id=request["document_id"], check_id=check_id, checked_at=now,
                           status="failed", error_code="http_error", http_status=503)
    else:
        store.record_check(document_id=request["document_id"], check_id=check_id, checked_at=now,
            status="fetched", body=body, media_type="application/pdf", http_status=200,
            metadata={"final_url": context["sourceUrl"], "etag": '"retained-public-nab"',
                      **({"unconditional_checked_at": now} if unconditional else {})})
    check = dict(store.db.execute("SELECT * FROM acquisition_checks WHERE check_id=?", (check_id,)).fetchone())
    queue.finish(request, check_id, now=now, terminal=fail)
    if acknowledge:
        public.record_check(request, check)
    return request, check


def test_populated_additive_migration_retains_terms_and_is_immutable(tmp_path):
    root = tmp_path / "evidence"
    with EvidenceStore(root) as store:
        original, _, _ = retained_product(store)
        before = store.db.execute("SELECT * FROM observations WHERE observation_id=?", (original,)).fetchone()
    with EvidenceStore(root) as store:
        assert tuple(store.db.execute("SELECT * FROM observations WHERE observation_id=?", (original,)).fetchone()) == tuple(before)
        assert store.db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            store.db.execute("DELETE FROM public_rate_programmes")
        assert len(compiled_generation(store, "retained-public-fixture")["products"]) == 1


def test_idempotent_capture_queue_and_original_public_bindings(tmp_path):
    with EvidenceStore(tmp_path / "evidence") as store:
        observation, result, inventory = retained_product(store)
        public = PublicRateStore(store)
        public.record_compiled(observation, result)
        register = public.register(inventory, observed_at=WHEN)
        first = public.queue_sources(register, ingest_id="retained-public-fixture", now=WHEN)
        assert first == public.queue_sources(register, ingest_id="retained-public-fixture", now=WHEN)
        assert len(first) == 1  # Shared lender URL checked once, not per rate/product.
        records = compiled_generation(store, "retained-public-fixture")
        assert records["evidence"] == result["evidence"] or sorted(records["evidence"], key=lambda e:e["evidenceId"]) == sorted(result["evidence"], key=lambda e:e["evidenceId"])
        assert all(item["url"].startswith("https://openbank.api.nab.com.au/") for item in records["evidence"])


def test_current_failed_stale_and_retained_rate_states(tmp_path):
    with EvidenceStore(tmp_path / "evidence") as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        retain_reference_check(store, register)
        current = public.catalogue_inputs(register, ingest_id="retained-public-fixture", as_of=WHEN)
        assert len(current["referenceRates"]) == 106
        assert all(rate["freshness"]["state"] == "current" for rate in current["referenceRates"])
        next_generation = "retained-public-fixture-next"
        retained_product(store, generation=next_generation, observed_at="2026-10-14T12:50:00Z")
        retain_reference_check(store, register, generation=next_generation, now="2026-10-14T12:50:00Z", fail=True)
        failed = public.catalogue_inputs(register, ingest_id=next_generation, as_of="2026-10-14T12:50:00Z")
        assert all(rate["freshness"]["state"] == "failed" for rate in failed["referenceRates"])
        assert [r["value"] for r in failed["referenceRates"]] == [r["value"] for r in current["referenceRates"]]
        stale = public.catalogue_inputs(register, ingest_id=next_generation, as_of="2026-10-17T12:50:00Z")
        assert all(rate["freshness"]["state"] == "stale" for rate in stale["referenceRates"])
        assert "http_error" in stale["referenceRates"][0]["freshness"]["reasonCodes"]


def test_provider_inventory_change_retains_last_verified_reference_values(tmp_path):
    with EvidenceStore(tmp_path / "evidence") as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        first = public.register(inventory, observed_at=WHEN)
        retain_reference_check(store, first)
        # Coverage/register editions can change without inventing a new rate.
        inventory["coverage"][0]["publicationStatus"] = "candidate"
        second = public.register(inventory, observed_at=WHEN)
        public.queue_sources(second, ingest_id="retained-public-fixture", now=WHEN)
        result = public.catalogue_inputs(second, ingest_id="retained-public-fixture", as_of=WHEN)
        assert len(result["referenceRates"]) == 106
        # Exact source context, adapter and retained bytes share the original
        # accepted check; changing coverage does not invent a new price/check.
        assert all(rate["freshness"]["state"] == "current" for rate in result["referenceRates"])


def test_304_has_retained_bytes_and_unconditional_refresh_omits_validators(tmp_path, monkeypatch):
    with EvidenceStore(tmp_path / "evidence") as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        request, original = retain_reference_check(store, register)
        body, context = capture("nab-indicator")
        calls = []
        def fetched(url, *, policy, conditional, conditional_url):
            calls.append((conditional, conditional_url))
            if conditional:
                return {"status":"unchanged", "http_status":304,"metadata":{"final_url":context["sourceUrl"]}}
            return {"status":"fetched","http_status":200,"body":body,"media_type":"application/pdf","metadata":{"final_url":context["sourceUrl"]}}
        monkeypatch.setattr("cdr_terms.acquisition.fetch_document", fetched)
        monkeypatch.setattr("cdr_terms.acquisition.utc_now", lambda: "2026-10-14T12:00:00Z")
        unchanged = acquire_document(store, request["document_id"], check_id="retained-304", policy=FetchPolicy())
        assert unchanged["document_version_id"] == original["document_version_id"]
        acquire_document(store, request["document_id"], check_id="retained-unconditional", force_refresh=True)
        assert calls[0][0] == {"If-None-Match":'"retained-public-nab"'}
        assert calls[1] == ({}, None)
        assert public.needs_unconditional(request["document_id"], now="2026-10-21T12:00:00Z")


def test_candidate_hash_and_disabled_publication(tmp_path):
    with EvidenceStore(tmp_path / "evidence") as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        retain_reference_check(store, register)
        descriptor = write_candidate(store, generation="retained-public-fixture", run_date="2026-10-14", register_id=register, as_of=WHEN)
        file = Path(descriptor["file"])
        assert file.stem == descriptor["sha256"] == hashlib.sha256(file.read_bytes()).hexdigest()
        candidate = json.loads(file.read_bytes())
        assert candidate["enabledProgrammeIds"] == []
        archived = read_candidate(file)
        assert any(p.get("formula",{}).get("op")=="range" for p in selected_programmes(archived, programme_ids(archived)))
        assert candidate["programmes"] == [] and candidate["programmeChunks"]
        assert read_candidate(store.root / "public-rate-catalogue-candidate.json").capture_sha256 == archived.capture_sha256
        assert all(row["publicationStatus"] == "disabled" for row in candidate["coverage"])


def test_same_name_public_reference_retains_customer_and_purpose_scope(tmp_path):
    with EvidenceStore(tmp_path / "evidence") as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        retain_reference_check(store, register)
        references = public.catalogue_inputs(register, ingest_id="retained-public-fixture", as_of=WHEN)["referenceRates"]
        base = [rate for rate in references if rate["name"] == "Base Variable Rate for Home Loans"]
        assert {rate["value"] for rate in base} == {"8.89", "9.77"}
        assert len({rate["scopeId"] for rate in base}) == 2
        scopes = {rate["value"]: {condition["field"]: condition.get("value") for condition in rate["conditions"]} for rate in base}
        assert scopes["8.89"] == {"purpose": "OWNER_OCCUPIED", "repayment": "PRINCIPAL_AND_INTEREST"}
        assert scopes["9.77"] == {"customerCategory": "OVERSEAS_BORROWER", "repayment": "PRINCIPAL_AND_INTEREST"}


def test_registered_reference_check_survives_missing_current_cdr_product(tmp_path):
    with EvidenceStore(tmp_path / "evidence") as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        future = "public-fixture-no-current-product"
        receipt = {"generation_id":future,"source_run_date":"2026-10-15"}
        with store.db:
            store.db.execute("INSERT INTO ingest_captures VALUES (?,?,?,?)", (future,store.put_blob(canonical_json_bytes(receipt)),"2026-10-15T00:00:00Z",1))
        ids = public.queue_sources(register, ingest_id=future, now="2026-10-15T00:00:00Z")
        request = dict(store.db.execute("SELECT * FROM acquisition_requests WHERE request_id=?", (ids[0],)).fetchone())
        observations, hosts, proof = request_scope(store, request)
        assert observations == [] and hosts == frozenset({"www.nab.com.au"}) and proof == {}


def test_future_check_cannot_make_an_earlier_generation_current(tmp_path):
    with EvidenceStore(tmp_path / "evidence") as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        retain_reference_check(store, register)
        earlier = public.catalogue_inputs(register, ingest_id="retained-public-fixture", as_of="2026-10-14T11:49:59Z")
        assert earlier["referenceRates"] == []
        assert earlier["evidence"] == []
        assert next(row for row in earlier["coverage"] if row["section"] == "Mortgage")["referenceSourceStatus"] == "deferred"


def _scenario_adapter(monkeypatch, transform):
    """Exercise hypothetical observation dates/routing/prices on retained bytes.

    These mutations are unit-test scenarios, not claims about lender changes.
    Public lender acceptance uses the unchanged captures in separate tests.
    """
    from cdr_public_rates_reference import extract_reference

    def adapted(body, context):
        result = extract_reference(body, context)
        assert result["status"] == "validated"
        transform(result, context)
        return result

    monkeypatch.setattr("cdr_public_rates_reference.extract_reference", adapted)


def _unit_alternate_source_inventory(inventory):
    """Controlled URL migration, not an asserted public lender endpoint."""
    changed = deepcopy(inventory)
    for source in changed['sources']:
        source['url'] += ('&' if '?' in source['url'] else '?') + 'unit_source_document=alternate'
    return changed


def test_unit_unverified_new_source_registration_cannot_borrow_old_document_history(tmp_path):
    with EvidenceStore(tmp_path / 'evidence') as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        original = public.register(inventory, observed_at=WHEN)
        _, check = retain_reference_check(store, original)
        original_count = store.db.execute('SELECT COUNT(*) FROM public_rate_observations').fetchone()[0]
        original_body = capture('nab-indicator')[0]
        original_sha = hashlib.sha256(original_body).hexdigest()
        later = '2026-10-14T12:50:00Z'
        generation = 'unit-unverified-source-migration'
        retained_product(store, generation=generation, observed_at=later)
        changed = public.register(_unit_alternate_source_inventory(inventory), observed_at=later)
        public.queue_sources(changed, ingest_id=generation, now=later)
        current = public.catalogue_inputs(changed, ingest_id=generation, as_of=later)
        assert current['referenceRates'] == []
        assert current['coverage'][0]['referenceSourceStatus'] == 'deferred'
        historical = public.catalogue_inputs(original, ingest_id='retained-public-fixture', as_of=WHEN)
        assert len(historical['referenceRates']) == 106
        assert store.db.execute('SELECT COUNT(*) FROM public_rate_observations').fetchone()[0] == original_count
        assert store.read_blob(original_sha) == original_body


def test_unit_late_old_source_url_prices_cannot_inherit_new_document_verification(tmp_path, monkeypatch):
    # Deliberate route/price controls prove context isolation; public lender
    # acceptance remains bound to the unchanged captures in the source tests.
    body, context = capture('nab-indicator')
    original_url = context['url']
    def price_by_route(result, extraction_context):
        result['referenceRates'] = result['referenceRates'][:1]
        if extraction_context['url'] == original_url:
            result['referenceRates'][0]['value'] = '9.99'  # Unit old-route price.
    _scenario_adapter(monkeypatch, price_by_route)
    with EvidenceStore(tmp_path / 'evidence') as store:
        old_generation, current_generation = 'unit-late-old-route', 'unit-current-public-route'
        _, _, inventory = retained_product(store, generation=old_generation, observed_at='2026-10-14T11:48:00Z')
        public = PublicRateStore(store)
        original = public.register(inventory, observed_at='2026-10-14T11:48:00Z')
        public.queue_sources(original, ingest_id=old_generation, now='2026-10-14T11:48:00Z')
        queue = AcquisitionQueue(store)
        late = queue.claim(now='2026-10-14T11:48:00Z')
        retained_product(store, generation=current_generation)
        changed = public.register(_unit_alternate_source_inventory(inventory), observed_at=WHEN)
        retain_reference_check(store, changed, generation=current_generation, now=WHEN)
        expected = public.catalogue_inputs(changed, ingest_id=current_generation, as_of=WHEN)['referenceRates'][0]
        assert expected['value'] != '9.99' and expected['freshness']['state'] == 'current'
        after = '2026-10-14T11:50:01Z'
        old_body = body + b'\n% unit scenario: late old registered URL\n'
        check_id = digest([late['request_id'], late['lease_id']])
        store.record_check(document_id=late['document_id'], check_id=check_id, checked_at=after,
                           status='fetched', body=old_body, media_type='application/pdf', http_status=200,
                           metadata={'final_url': context['sourceUrl']})
        queue.finish(late, check_id, now=after)
        public.record_check(late, dict(store.db.execute('SELECT * FROM acquisition_checks WHERE check_id=?', (check_id,)).fetchone()))
        current = public.catalogue_inputs(changed, ingest_id=current_generation, as_of=after)
        assert len(current['referenceRates']) == 1
        assert current['referenceRates'][0]['referenceId'] == expected['referenceId']
        assert current['referenceRates'][0]['value'] == expected['value']
        assert current['referenceRates'][0]['freshness']['state'] == 'current'
        assert all(item['sha256'] == hashlib.sha256(body).hexdigest() for item in current['evidence'])
        retained = public.catalogue_inputs(original, ingest_id=old_generation, as_of=after)
        assert retained['referenceRates'][0]['value'] == '9.99'
        assert store.read_blob(hashlib.sha256(old_body).hexdigest()) == old_body


def test_announced_future_reference_is_retained_and_bounds_the_current_period(tmp_path, monkeypatch):
    def dates(result, context):
        result["referenceRates"] = result["referenceRates"][:1]
        rate = result["referenceRates"][0]
        if context["checkedAt"].startswith("2026-10-14T11:50:00"):
            rate["effectiveFrom"] = "2026-10-12T00:00:00Z"
        else:
            rate.update(effectiveFrom="2026-10-15T00:00:00Z", value="9.15")
    _scenario_adapter(monkeypatch, dates)
    with EvidenceStore(tmp_path / "evidence") as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        retain_reference_check(store, register)
        retained_product(store, generation="future-announcement", observed_at="2026-10-14T12:50:00Z")
        retain_reference_check(store, register, generation="future-announcement", now="2026-10-14T12:50:00Z", suffix=b"\n% unit scenario: future date\n")
        before = public.catalogue_inputs(register, ingest_id="future-announcement", as_of="2026-10-14T12:50:00Z")
        versions = sorted(before["referenceRates"], key=lambda rate: rate["effectiveFrom"])
        assert len(versions) == 2
        assert versions[0]["effectiveTo"] == versions[1]["effectiveFrom"] == "2026-10-15T00:00:00Z"
        assert set(versions[1]["evidenceIds"]) <= set(versions[0]["evidenceIds"])
        assert before["coverage"][0]["referenceRatesCurrent"] == 1
        assert before["coverage"][0]["futureReferenceObservations"] == 1
        after = public.catalogue_inputs(register, ingest_id="future-announcement", as_of="2026-10-15T00:00:00Z")
        assert len(after["referenceRates"]) == 1
        assert after["referenceRates"][0]["value"] == "9.15"
        assert after["coverage"][0]["futureReferenceObservations"] == 0


def test_latest_expired_reference_does_not_fall_back_to_an_old_open_period(tmp_path, monkeypatch):
    def dates(result, context):
        result["referenceRates"] = result["referenceRates"][:1]
        rate = result["referenceRates"][0]
        rate["effectiveFrom"] = "2026-10-12T00:00:00Z" if context["checkedAt"].startswith("2026-10-14T11:50:00") else "2026-10-14T12:00:00Z"
        if not context["checkedAt"].startswith("2026-10-14T11:50:00"):
            rate["effectiveTo"] = "2026-10-14T13:00:00Z"
    _scenario_adapter(monkeypatch, dates)
    with EvidenceStore(tmp_path / "evidence") as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        retain_reference_check(store, register)
        retained_product(store, generation="expired-period", observed_at="2026-10-14T12:50:00Z")
        retain_reference_check(store, register, generation="expired-period", now="2026-10-14T12:50:00Z", suffix=b"\n% unit scenario: expired period\n")
        result = public.catalogue_inputs(register, ingest_id="expired-period", as_of="2026-10-14T13:00:00Z")
        assert len(result["referenceRates"]) == 1
        rate = result["referenceRates"][0]
        assert rate["effectiveFrom"] == "2026-10-14T12:00:00Z"
        assert rate["freshness"]["state"] == "unknown"
        assert "public_reference_effective_period_ended" in rate["freshness"]["reasonCodes"]
        assert result["coverage"][0]["referenceRatesCurrent"] == 0


def test_removed_family_preserves_value_without_inheriting_a_later_verification(tmp_path, monkeypatch):
    removed = []
    def families(result, context):
        removed.append(result["referenceRates"][0]["referenceId"])
        result["referenceRates"] = result["referenceRates"][:2] if context["checkedAt"].startswith("2026-10-14T11:50:00") else result["referenceRates"][1:2]
    _scenario_adapter(monkeypatch, families)
    with EvidenceStore(tmp_path / "evidence") as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        retain_reference_check(store, register)
        retained_product(store, generation="removed-family", observed_at="2026-10-14T12:50:00Z")
        retain_reference_check(store, register, generation="removed-family", now="2026-10-14T12:50:00Z", suffix=b"\n% unit scenario: removed family\n")
        result = public.catalogue_inputs(register, ingest_id="removed-family", as_of="2026-10-14T12:50:00Z")
        rate = next(item for item in result["referenceRates"] if item["referenceId"] == removed[0])
        assert rate["freshness"]["state"] == "unknown"
        assert datetime.fromisoformat(rate["freshness"]["lastSuccessAt"].replace("Z", "+00:00")) == datetime.fromisoformat(WHEN.replace("Z", "+00:00"))
        assert "reference_family_not_in_latest_public_source" in rate["freshness"]["reasonCodes"]
        assert "value" in rate
        assert result["coverage"][0]["referenceRatesCurrent"] == 1


def test_contradictory_reference_rows_enter_review_without_current_claims(tmp_path, monkeypatch):
    def conflict(result, context):
        first = result["referenceRates"][0]
        result["referenceRates"] = [first, {**first, "value": "9.99"}]
    _scenario_adapter(monkeypatch, conflict)
    with EvidenceStore(tmp_path / "evidence") as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        retain_reference_check(store, register)
        result = public.catalogue_inputs(register, ingest_id="retained-public-fixture", as_of=WHEN)
        assert result["referenceRates"] == []
        assert result["coverage"][0]["referenceSourceStatus"] == "failed"
        assert result["coverage"][0]["sourceAcquisition"] == "fetched"
        assert result["coverage"][0]["extraction"] == "unresolved"
        assert store.db.execute("SELECT reason_code FROM public_rate_review_queue").fetchone()[0] == "conflicting_reference_rows"


def test_interpretation_commit_requeues_a_snapshot_consumed_while_parsing(tmp_path, monkeypatch):
    from cdr_public_rates_reference import extract_reference
    with EvidenceStore(tmp_path / "evidence") as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        def interleaved(body, context):
            pending = store.db.execute("SELECT * FROM public_rate_candidate_events ORDER BY sequence DESC LIMIT 1").fetchone()
            assert pending["status"] == "dirty"
            with store.db:
                store.db.execute("INSERT INTO public_rate_candidate_events "
                    "(event_id,ingest_id,register_id,status,observed_at) VALUES (?,?,?,?,?)",
                    (digest([pending["event_id"], "unit_snapshot_consumed"]), pending["ingest_id"], register, "fresh", WHEN))
            return extract_reference(body, context)
        monkeypatch.setattr("cdr_public_rates_reference.extract_reference", interleaved)
        retain_reference_check(store, register)
        latest = store.db.execute("SELECT * FROM public_rate_candidate_events ORDER BY sequence DESC LIMIT 1").fetchone()
        assert latest["status"] == "dirty"
        assert len(public.catalogue_inputs(register, ingest_id="retained-public-fixture", as_of=WHEN)["referenceRates"]) == 106


def test_accepted_capture_replays_after_parser_crash_without_a_new_network_check(tmp_path, monkeypatch):
    from cdr_public_rates_reference import extract_reference
    with EvidenceStore(tmp_path / "evidence") as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        def interrupted(body, context):
            raise TimeoutError("unit parser interruption")
        monkeypatch.setattr("cdr_public_rates_reference.extract_reference", interrupted)
        with pytest.raises(TimeoutError, match="interruption"):
            retain_reference_check(store, register)
        replay = public.pending_interpretations("retained-public-fixture")
        assert len(replay) == 1
        assert replay[0]["request"]["lease_id"]
        count = store.db.execute("SELECT COUNT(*) FROM acquisition_checks").fetchone()[0]
        monkeypatch.setattr("cdr_public_rates_reference.extract_reference", extract_reference)
        public.record_check(replay[0]["request"], replay[0]["check"])
        assert public.pending_interpretations("retained-public-fixture") == []
        assert store.db.execute("SELECT COUNT(*) FROM acquisition_checks").fetchone()[0] == count
        assert len(public.catalogue_inputs(register, ingest_id="retained-public-fixture", as_of=WHEN)["referenceRates"]) == 106


def test_unaccepted_orphan_is_not_a_pending_interpretation(tmp_path):
    with EvidenceStore(tmp_path / "evidence") as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        request_id = public.queue_sources(register, ingest_id="retained-public-fixture", now=WHEN)[0]
        request = dict(store.db.execute("SELECT * FROM acquisition_requests WHERE request_id=?", (request_id,)).fetchone())
        body, context = capture("nab-indicator")
        store.record_check(document_id=request["document_id"], check_id="unit-orphan", checked_at=WHEN,
                           status="fetched", body=body, media_type="application/pdf", http_status=200)
        binding = store.db.execute("SELECT binding_id FROM public_rate_sources WHERE register_id=?", (register,)).fetchone()[0]
        with store.db:
            store.db.execute("INSERT INTO public_rate_checks VALUES (?,?,?,?)", (binding, "unit-orphan", request["ingest_id"], request_id))
        assert public.pending_interpretations(request["ingest_id"]) == []


@pytest.mark.parametrize("failed", [False, True])
def test_accepted_check_before_pricing_ack_is_replayed_once(tmp_path, failed):
    with EvidenceStore(tmp_path / "evidence") as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        retain_reference_check(store, register, fail=failed, acknowledge=False)
        assert store.db.execute("SELECT COUNT(*) FROM public_rate_checks").fetchone()[0] == 0
        replay = public.pending_interpretations(None)
        assert len(replay) == 1
        before = store.db.execute("SELECT COUNT(*) FROM acquisition_checks").fetchone()[0]
        public.record_check(replay[0]["request"], replay[0]["check"])
        assert public.pending_interpretations(None) == []
        assert public.pending_interpretations("retained-public-fixture") == []
        assert store.db.execute("SELECT COUNT(*) FROM acquisition_checks").fetchone()[0] == before


def test_unacknowledged_failed_check_removes_current_claim_even_when_replay_budget_is_exhausted(tmp_path):
    from cdr_public_rates_budget import reserve
    with EvidenceStore(tmp_path / "evidence") as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        retain_reference_check(store, register)
        generation, later = "interrupted-pricing-ack", "2026-10-14T12:50:00Z"
        retained_product(store, generation=generation, observed_at=later)
        retain_reference_check(store, register, generation=generation, now=later, fail=True, acknowledge=False)
        # Two crashed supervised windows retain their whole reservations.
        reserve(store, generation, kind="source")
        reserve(store, generation, kind="source")
        assert public.pending_interpretations(None) == []
        assert len(public.pending_interpretations(generation)) == 1
        catalogue = public.catalogue_inputs(register, ingest_id=generation, as_of=later)
        assert all(rate["freshness"]["state"] == "failed" for rate in catalogue["referenceRates"])
        assert all("http_error" in rate["freshness"]["reasonCodes"] for rate in catalogue["referenceRates"])
        assert catalogue["coverage"][0]["referenceRatesCurrent"] == 0
        assert catalogue["coverage"][0]["sourceAcquisition"] == "failed"
        assert catalogue["coverage"][0]["extraction"] == "unavailable"


def test_conditional_daily_200_responses_cannot_postpone_weekly_unconditional_refresh(tmp_path):
    with EvidenceStore(tmp_path / "evidence") as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        request, _ = retain_reference_check(store, register, unconditional=True)
        document = request["document_id"]
        assert not public.needs_unconditional(document, now=WHEN)
        for day in (15, 18, 20):
            when, generation = f"2026-10-{day}T11:50:00Z", f"conditional-{day}"
            retained_product(store, generation=generation, observed_at=when)
            retain_reference_check(store, register, generation=generation, now=when)
        assert not public.needs_unconditional(document, now="2026-10-21T11:49:59Z")
        assert public.needs_unconditional(document, now="2026-10-21T11:50:00Z")
        refreshed, generation = "2026-10-21T11:50:00Z", "weekly-refresh"
        retained_product(store, generation=generation, observed_at=refreshed)
        retain_reference_check(store, register, generation=generation, now=refreshed, unconditional=True)
        assert not public.needs_unconditional(document, now="2026-10-22T11:50:00Z")


def test_late_older_ingest_failure_invalidates_newer_shared_source_before_ack(tmp_path):
    with EvidenceStore(tmp_path / "evidence") as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        retain_reference_check(store, register)
        retained_product(store, generation="older-in-flight", observed_at="2026-10-14T11:55:00Z")
        public.queue_sources(register, ingest_id="older-in-flight", now="2026-10-14T11:55:00Z")
        queue = AcquisitionQueue(store)
        older = queue.claim(now="2026-10-14T11:55:00Z")
        assert older["ingest_id"] == "older-in-flight"
        generation, success = "selected-recapture", "2026-10-14T11:55:10Z"
        retained_product(store, generation=generation, observed_at="2026-10-14T11:55:05Z")
        retain_reference_check(store, register, generation=generation, now=success)
        before = public.catalogue_inputs(register, ingest_id=generation, as_of="2026-10-14T11:55:15Z")
        assert all(rate["freshness"]["state"] == "current" for rate in before["referenceRates"])
        failed = "2026-10-14T11:55:20Z"
        check_id = digest([older["request_id"], older["lease_id"], "late-failure"])
        store.record_check(document_id=older["document_id"], check_id=check_id, checked_at="2026-10-14T11:55:00Z",
                           status="failed", error_code="http_error", http_status=503)
        queue.finish(older, check_id, now=failed, terminal=True)
        # Crash before pricing acknowledgement: the accepted response alone
        # invalidates the newer edition, with the true last successful date.
        assert not store.db.execute("SELECT 1 FROM public_rate_checks WHERE check_id=?", (check_id,)).fetchone()
        after = public.catalogue_inputs(register, ingest_id=generation, as_of=failed)
        assert all(rate["freshness"]["state"] == "failed" for rate in after["referenceRates"])
        assert all(datetime.fromisoformat(rate["freshness"]["lastSuccessAt"].replace("Z", "+00:00")) ==
                   datetime.fromisoformat(success.replace("Z", "+00:00")) for rate in after["referenceRates"])
        assert after["coverage"][0]["referenceRatesCurrent"] == 0
        historical = public.catalogue_inputs(register, ingest_id=generation, as_of="2026-10-14T11:55:15Z")
        assert all(rate["freshness"]["state"] == "current" for rate in historical["referenceRates"])
        recovery = "2026-10-14T11:55:26Z"
        retained_product(store, generation="verified-recovery", observed_at="2026-10-14T11:55:25Z")
        retain_reference_check(store, register, generation="verified-recovery", now=recovery)
        recovered = public.catalogue_inputs(register, ingest_id=generation, as_of=recovery)
        assert all(rate["freshness"]["state"] == "current" for rate in recovered["referenceRates"])


def test_shared_check_cannot_donate_a_different_adapter_interpretation(tmp_path):
    with EvidenceStore(tmp_path / "evidence") as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        original = public.register(inventory, observed_at=WHEN)
        retain_reference_check(store, original)
        inventory["sources"][0]["adapterVersion"] = "2"
        changed = public.register(inventory, observed_at=WHEN)
        public.queue_sources(changed, ingest_id="retained-public-fixture", now=WHEN)
        binding = dict(store.db.execute("SELECT * FROM public_rate_sources WHERE register_id=?", (changed,)).fetchone())
        state = public.source_freshness(binding, ingest_id="retained-public-fixture", as_of=WHEN)
        assert state["state"] == "deferred"
        assert "source_extraction_pending" in state["reasonCodes"]
