"""Public-pricing lane in existing finalized capture and guarded acquisition.

No independent schedule, daemon, model job or production publication is created.
Collection is opt-in; candidates are a derived cache backed by immutable evidence.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

from cdr_atomic import atomic_write_json, canonical_json_bytes
from cdr_clean_export import bank_base_row, inner_record
from cdr_public_rates_cdr import compile_record, inventory_from_compiled
from cdr_public_rates_source_capture import pricing_capture_for_path
from cdr_public_rates_sources import source_inventory, reference_ids_for_product
from cdr_public_rates_candidate import MAX_ROOT_BYTES, write_chunks
from cdr_domain.identity import provider_uid
from cdr_terms.identity import byte_digest, digest, utc_now
from cdr_terms.public_rates_store import PublicRateStore
from cdr_terms.store import EvidenceStore

COLLECT_ENV = "AR_LOCAL_PUBLIC_RATES_COLLECT"
MAX_PRODUCTS = 20000


class CandidateDeferred(RuntimeError):
    """The existing guarded worker can resume this derived cache later."""


def configured() -> bool:
    return os.environ.get(COLLECT_ENV, "") == "1"


def _section(record: dict) -> str | None:
    category = record.get("productCategory")
    return {"RESIDENTIAL_MORTGAGES": "Mortgage", "TERM_DEPOSITS": "TD",
            "TRANS_AND_SAVINGS_ACCOUNTS": "Savings"}.get(category)


def capture_public_rates(store: EvidenceStore, run_root: Path, receipt: dict) -> dict | None:
    """No-network extension; preserve original terms capture receipt unchanged."""
    if not configured():
        return None
    public = PublicRateStore(store)
    generation = receipt["generation_id"]
    compiled = {"products": [], "programmes": [], "evidence": []}
    banks = run_root / "banks"
    for entry in receipt["sources"]:
        body = store.read_blob(entry["sha256"])
        record = inner_record(json.loads(body))
        section = _section(record)
        if section is None:
            continue
        path = run_root / entry["relative_path"]
        prior = store.db.execute("SELECT 1 FROM public_rate_product_versions WHERE observation_id=?", (entry["observation_id"],)).fetchone()
        if prior:
            continue
        if not path.is_file() or path.is_symlink():
            raise ValueError("original_public_source_context_unavailable")
        base = bank_base_row(path, banks, record)
        capture = json.loads(pricing_capture_for_path(body, path, banks, base))
        if not capture["sourceUrl"]:
            links = json.loads(body).get("links", {})
            source = links.get("self", "") if isinstance(links, dict) else ""
            parsed = urlsplit(source)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("public_cdr_origin_context_unavailable")
            capture["sourceUrl"] = source
        item = compile_record(record, provider_name=base["provider"], section=section,
            source_url=capture["sourceUrl"], source_sha256=entry["sha256"], checked_at=capture["checkedAt"],
            product_key=entry["product_key"], pointer=capture["pointer"], provider_id=capture["providerId"])
        public.record_compiled(entry["observation_id"], item)
    compiled = compiled_generation(store, generation, include_programmes=False, include_evidence=False)
    holder_root = banks / "_holders"
    holders = sorted(path.name for path in holder_root.iterdir() if path.is_dir()) if holder_root.is_dir() else []
    summaries = []
    for selection in compiled["_selection"]:
        for row in store.db.execute("SELECT v.programme_id,s.has_formula,v.body_sha256,v.version_id FROM public_rate_programme_versions v "
            "LEFT JOIN public_rate_programme_summaries s USING(version_id) WHERE v.observation_id=?", (selection["observationId"],)):
            supported = row["has_formula"]
            if supported is None:
                supported = int(bool(json.loads(store.read_blob(row["body_sha256"])).get("formula")))
                with store.db:
                    store.db.execute("INSERT OR IGNORE INTO public_rate_programme_summaries VALUES (?,?)", (row["version_id"], supported))
            # Inventory consumes the availability flag only. Executable formulas
            # remain in immutable programme blobs and bounded candidate chunks.
            summaries.append({"programmeId": row["programme_id"], "formula": bool(supported)})
    provider_inventory = inventory_from_compiled({"products": compiled["products"], "programmes": summaries}, holders)
    for item in provider_inventory:
        metadata = holder_root / item["providerName"] / "_register-brand.json"
        if not metadata.is_file():
            continue
        brand = json.loads(metadata.read_bytes())
        parsed = urlsplit(str(brand.get("endpoint_url") or ""))
        item["providerId"] = provider_uid(register_holder_id=brand.get("data_holder_id") or brand.get("dataHolderId"),
            register_brand_id=brand.get("data_holder_brand_id") or brand.get("dataHolderBrandId"),
            authority=parsed.hostname or "public-cdr-unknown", display_name=item["providerName"])[0]
    inventory = source_inventory(provider_inventory)
    register = public.register(inventory, observed_at=receipt["captured_at"])
    requests = public.queue_sources(register, ingest_id=generation, now=receipt["captured_at"])
    event = digest([generation, register, "captured_public_programmes"])
    with store.db:
        store.db.execute("INSERT OR IGNORE INTO public_rate_candidate_events "
            "(event_id,ingest_id,register_id,status,observed_at) VALUES (?,?,?,?,?)",
            (event, generation, register, "dirty", receipt["captured_at"]))
    try:
        candidate = write_candidate(store, generation=generation, run_date=receipt["source_run_date"], register_id=register)
    except CandidateDeferred as error:
        candidate = {"status": "deferred", "reasonCode": str(error), "publication": "disabled"}
    else:
        with store.db:
            latest = store.db.execute("SELECT event_id FROM public_rate_candidate_events WHERE ingest_id=? "
                "AND register_id=? ORDER BY sequence DESC LIMIT 1", (generation, register)).fetchone()
            if latest and latest[0] == event:
                store.db.execute("INSERT OR IGNORE INTO public_rate_candidate_events "
                    "(event_id,ingest_id,register_id,status,observed_at) VALUES (?,?,?,?,?)",
                    (digest([event, "fresh", candidate["sha256"]]), generation, register, "fresh", utc_now()))
    return {"schemaVersion": 1, "generationId": generation, "registerId": register,
            "acquisitionRequests": len(requests), "candidate": candidate,
            "networkCalled": False, "modelCalled": False, "publication": "disabled"}


def compiled_generation(store: EvidenceStore, generation: str, *, include_programmes: bool = True,
                        include_evidence: bool = True) -> dict:
    result = {"products": [], "programmes": [], "evidence": []}
    rows = [dict(row) for row in store.db.execute("SELECT v.*,o.source_sha256,o.observed_at FROM public_rate_product_versions v JOIN observations o "
        "USING(observation_id) WHERE o.ingest_id=? ORDER BY v.product_id", (generation,)).fetchall()
            ]
    current = {row["product_id"] for row in rows}
    clock = store.db.execute("SELECT source_observed_at FROM ingest_capture_attempts WHERE ingest_id=?", (generation,)).fetchone()
    if clock:
        past = store.db.execute("SELECT v.*,o.source_sha256,o.observed_at FROM public_rate_product_versions v JOIN observations o "
            "USING(observation_id) WHERE o.observed_at<=? AND v.observation_id=(SELECT newest.observation_id "
            "FROM public_rate_product_versions history JOIN observations newest USING(observation_id) "
            "WHERE history.product_id=v.product_id AND newest.observed_at<=? ORDER BY newest.observed_at DESC LIMIT 1) "
            "ORDER BY v.product_id", (clock[0], clock[0])).fetchall()
        rows.extend({**dict(row), "historical": True} for row in past if row["product_id"] not in current)
    if len(rows) > MAX_PRODUCTS:
        raise ValueError("public_candidate_product_budget_exceeded")
    evidence = {}
    for row in rows:
        product = json.loads(row["discovery_json"])
        # Retain dated public names when the same stable product changes names.
        older = store.db.execute("SELECT DISTINCT json_extract(v.discovery_json,'$.name') name FROM public_rate_product_versions v "
            "JOIN observations o USING(observation_id) WHERE v.product_id=? AND o.observed_at<=? "
            "AND json_extract(v.discovery_json,'$.name')!=? ORDER BY name LIMIT 64",
            (row["product_id"], clock[0] if clock else row.get("observed_at", ""), product["name"])).fetchall()
        aliases = {item["name"]: item for item in product["aliases"]}
        for entry in older:
            if entry[0] != product["name"]:
                # A source observation date establishes when the name was
                # publicly observed, not the lender's effective alias period.
                aliases.setdefault(entry[0], {"name": entry[0]})
        product["aliases"] = sorted(aliases.values(), key=lambda item: item["name"])[:64]
        if row.get("historical"):
            if product["status"] != "legacy":
                product["status"] = "unknown"
            product["reasonCodes"] = sorted(set(product["reasonCodes"] + ["historical_public_product_not_in_selected_ingest"]))
            if "freshness" in product:
                product["freshness"] = {**product["freshness"], "state": "stale", "reasonCodes": ["product_source_not_in_selected_ingest"]}
        result["products"].append(product)
        if include_programmes:
            result["programmes"].extend(_programmes_for_observation(store, row["observation_id"], historical=bool(row.get("historical"))))
        if include_evidence:
            for source in store.db.execute("SELECT evidence_json FROM public_rate_source_evidence WHERE observation_id=?", (row["observation_id"],)):
                item = json.loads(source[0])
                evidence[item["evidenceId"]] = item
    result["evidence"] = list(evidence.values())
    if not include_programmes or not include_evidence:
        result["_selection"] = [{"observationId": row["observation_id"], "historical": bool(row.get("historical"))} for row in rows]
    return result


def _programmes_for_observation(store: EvidenceStore, observation_id: str, *, historical: bool):
    rows = store.db.execute("SELECT * FROM public_rate_programme_versions WHERE observation_id=? ORDER BY programme_id", (observation_id,))
    for row in rows:
        value = json.loads(store.read_blob(row["body_sha256"]))
        if historical:
            value["freshness"] = {**value["freshness"], "state": "stale", "reasonCodes": ["product_source_not_in_selected_ingest"]}
            value["reasonCodes"] = sorted(set(value["reasonCodes"] + ["historical_public_product_not_in_selected_ingest"]))
        yield value


def write_candidate(store: EvidenceStore, *, generation: str, run_date: str, register_id: str,
                    as_of: str | None = None, deadline: float | None = None, guard=None) -> dict:
    public = PublicRateStore(store)
    compiled = compiled_generation(store, generation, include_programmes=False, include_evidence=False)
    when = as_of or utc_now()
    reference = public.catalogue_inputs(register_id, ingest_id=generation, as_of=when)
    for product in compiled["products"]:
        product["referenceIds"] = reference_ids_for_product(product, reference["referenceRates"])
    directory = store.root / "public-rate-candidates" / digest(generation)
    directory.mkdir(parents=True, exist_ok=True)
    stop_at = deadline if deadline is not None else time.monotonic() + 300

    def checkpoint():
        if time.monotonic() >= stop_at:
            raise CandidateDeferred("candidate_admission_deadline")
        if guard:
            reason = guard()
            if reason:
                raise CandidateDeferred("candidate_operational_guard:" + reason)

    products = {product["productId"]: product for product in compiled["products"]}

    def programmes():
        for selection in compiled["_selection"]:
            for value in _programmes_for_observation(store, selection["observationId"], historical=selection["historical"]):
                product = products[value["productId"]]
                product["reasonCodes"] = sorted(set(product["reasonCodes"] + value["reasonCodes"]))
                yield value

    programme_chunks = write_chunks(directory, generation, "programme", programmes(), checkpoint=checkpoint)

    def evidence():
        seen = {item["evidenceId"] for item in reference["evidence"]}
        for selection in compiled["_selection"]:
            for row in store.db.execute("SELECT evidence_json FROM public_rate_source_evidence WHERE observation_id=? ORDER BY evidence_id", (selection["observationId"],)):
                value = json.loads(row[0])
                if value["evidenceId"] not in seen:
                    seen.add(value["evidenceId"])
                    yield value

    evidence_chunks = write_chunks(directory, generation, "evidence", evidence(), checkpoint=checkpoint)
    candidate = {"schemaVersion": 1, "generationId": generation, "runDate": run_date,
        "products": compiled["products"], "programmes": [], "referenceRates": reference["referenceRates"],
        "evidence": reference["evidence"], "programmeChunks": programme_chunks, "evidenceChunks": evidence_chunks,
        "coverage": reference["coverage"], "enabledProgrammeIds": []}
    body = canonical_json_bytes(candidate)
    if len(body) > MAX_ROOT_BYTES:
        raise ValueError("public_candidate_decoded_budget_exceeded")
    identity = byte_digest(body)
    target = directory / (identity + ".json")
    atomic_write_json(target, candidate, create_once=True)
    # Mutable discovery pointer is never publication evidence. Builders should
    # take the returned immutable file, and still bind its generation to core.
    atomic_write_json(store.root / "public-rate-catalogue-candidate.json", {"schemaVersion": 1,
        "candidateFile": target.relative_to(store.root).as_posix(), "sha256": identity})
    public.record_coverage(register_id, ingest_id=generation, coverage=reference["coverage"], observed_at=when)
    return {"file": str(target), "sha256": byte_digest(target.read_bytes()), "candidateId": identity,
            "programmes": sum(len(chunk["programmeIds"]) for chunk in programme_chunks),
            "products": len(candidate["products"]), "references": len(candidate["referenceRates"]), "publication": "disabled"}


def pending_candidate(store: EvidenceStore) -> dict | None:
    if not configured():
        return None
    row = store.db.execute("SELECT * FROM public_rate_candidate_events e WHERE e.sequence="
        "(SELECT MAX(sequence) FROM public_rate_candidate_events p WHERE p.ingest_id=e.ingest_id "
        "AND p.register_id=e.register_id) AND e.status='dirty' ORDER BY e.sequence LIMIT 1").fetchone()
    return dict(row) if row else None


def refresh_one_pending_candidate(store: EvidenceStore, *, deadline: float | None = None, guard=None) -> dict | None:
    pending = pending_candidate(store)
    if not pending:
        return None
    capture = store.db.execute("SELECT receipt_sha256 FROM ingest_captures WHERE ingest_id=?", (pending["ingest_id"],)).fetchone()
    if not capture:
        return {"status": "deferred", "reasonCode": "finalized_source_capture_pending"}
    receipt = json.loads(store.read_blob(capture[0]))
    try:
        result = write_candidate(store, generation=pending["ingest_id"], run_date=receipt["source_run_date"], register_id=pending["register_id"], deadline=deadline, guard=guard)
    except CandidateDeferred as error:
        return {"status": "deferred", "reasonCode": str(error), "publication": "disabled"}
    # Complete only the snapshot read above. A later check's dirty event wins
    # even if it arrived while this immutable candidate was being written.
    with store.db:
        latest = store.db.execute("SELECT sequence FROM public_rate_candidate_events WHERE ingest_id=? "
            "AND register_id=? ORDER BY sequence DESC LIMIT 1", (pending["ingest_id"], pending["register_id"])).fetchone()
        if latest and latest[0] == pending["sequence"]:
            store.db.execute("INSERT OR IGNORE INTO public_rate_candidate_events "
                "(event_id,ingest_id,register_id,status,observed_at) VALUES (?,?,?,?,?)",
                (digest([pending["event_id"], "fresh", result["sha256"]]), pending["ingest_id"], pending["register_id"], "fresh", utc_now()))
    return {"status": "candidate_written", "sha256": result["sha256"], "generationId": pending["ingest_id"], "publication": "disabled"}
