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
from cdr_public_rates_budget import BudgetDeferred, available_sql, reserve
from cdr_domain.identity import provider_uid, product_uid
from cdr_terms.identity import byte_digest, canonical_json, digest, utc_now
from cdr_terms.public_rates_store import PublicRateStore
from cdr_terms.store import EvidenceStore

COLLECT_ENV = "AR_LOCAL_PUBLIC_RATES_COLLECT"
MAX_PRODUCTS = 20000


class CandidateDeferred(BudgetDeferred):
    """The existing guarded worker can resume this derived cache later."""


def configured() -> bool:
    return os.environ.get(COLLECT_ENV, "") == "1"


def _source_clock_projection(store: EvidenceStore, observation_id: str):
    # Collector contexts, including older mtime-based inputs, contain no bound
    # per-resource verification receipt. Correct derived views without rewriting
    # immutable observations, discovery rows, programme blobs or source evidence.
    unbound = store.db.execute("SELECT 1 FROM public_rate_compile_inputs WHERE observation_id=?",
                              (observation_id,)).fetchone() is not None

    def project(value):
        if not unbound:
            return value
        if isinstance(value, list):
            return [project(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {key: project(item) for key, item in value.items() if key not in {"checkedAt", "lastSuccessAt"}}
        if isinstance(result.get("freshness"), dict):
            fresh = result["freshness"]
            fresh["state"] = "unknown"
            fresh["reasonCodes"] = sorted(set(fresh.get("reasonCodes", []) + ["successful_source_check_unavailable"]))
        return result

    return project


def _section(record: dict) -> str | None:
    category = record.get("productCategory")
    return {"RESIDENTIAL_MORTGAGES": "Mortgage", "TERM_DEPOSITS": "TD",
            "TRANS_AND_SAVINGS_ACCOUNTS": "Savings"}.get(category)


def retain_compile_input(store: EvidenceStore, path: Path, banks: Path, base: dict,
                         body: bytes, observation_id: str) -> None:
    """Archive actual source context while the original guarded capture owns it."""
    if not configured():
        return
    observation = store.db.execute("SELECT * FROM observations WHERE observation_id=?", (observation_id,)).fetchone()
    if not observation or observation["source_sha256"] != byte_digest(body):
        raise ValueError("public_compile_input_does_not_bind_observation")
    if store.db.execute("SELECT 1 FROM public_rate_compile_inputs WHERE observation_id=?", (observation_id,)).fetchone():
        return
    record = inner_record(json.loads(body))
    section = _section(record)
    if section is None:
        return
    if not path.is_file() or path.is_symlink():
        raise ValueError("original_public_source_context_unavailable")
    capture = json.loads(pricing_capture_for_path(body, path, banks, base))
    if not capture["sourceUrl"]:
        envelope = json.loads(body)
        links = envelope.get("links", {})
        source = links.get("self", "") if isinstance(links, dict) else ""
        parsed = urlsplit(source)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("public_cdr_origin_context_unavailable")
        capture["sourceUrl"] = source
    context = {key: value for key, value in capture.items() if key != "record"}
    context.update(providerName=base["provider"], section=section, productKey=observation["product_key"],
                   name=str(record.get("name") or record.get("productId") or observation["product_key"]),
                   productId=product_uid(capture["providerId"], str(record.get("productId") or observation["product_key"])))
    with store.db:
        store.db.execute("INSERT OR IGNORE INTO public_rate_compile_inputs VALUES (?,?,?)",
                         (observation_id, observation["ingest_id"], canonical_json(context)))


def _pending_product(context: dict) -> dict:
    from cdr_domain.public_pricing import semantic_id
    from cdr_public_rates_cdr import ADAPTER_VERSION
    evidence = {"evidenceId": semantic_id("evidence", [context["sourceSha256"], context["pointer"]]),
                "url": context["sourceUrl"], "sha256": context["sourceSha256"], "locator": context["pointer"],
                "extractionVersion": ADAPTER_VERSION}
    freshness = {"state": "unknown", "reasonCodes": ["pricing_compilation_deferred"]}
    return {"productId": context["productId"], "productKey": context["productKey"], "providerId": context["providerId"],
            "providerName": context["providerName"], "name": context["name"], "section": context["section"], "aliases": [],
            "status": "unknown", "programmeIds": [], "referenceIds": [], "reasonCodes": ["pricing_compilation_deferred"],
            "freshness": freshness, "sourceEvidence": evidence}


def _compile_pending(store: EvidenceStore, generation: str, checkpoint) -> None:
    public = PublicRateStore(store)
    rows = store.db.execute("SELECT i.*,o.source_sha256 FROM public_rate_compile_inputs i JOIN observations o USING(observation_id) "
        "WHERE i.ingest_id=? AND NOT EXISTS (SELECT 1 FROM public_rate_product_versions v WHERE v.observation_id=i.observation_id) "
        "ORDER BY i.observation_id", (generation,))
    for entry in rows:
        checkpoint()
        context = json.loads(entry["context_json"])
        body = store.read_blob(entry["source_sha256"])
        record = inner_record(json.loads(body))
        checkpoint()
        item = compile_record(record, provider_name=context["providerName"], section=context["section"],
            source_url=context["sourceUrl"], source_sha256=entry["source_sha256"],
            product_key=context["productKey"], pointer=context["pointer"], provider_id=context["providerId"])
        checkpoint()
        public.record_compiled(entry["observation_id"], item)


def _replay_pending_checks(store, generation, checkpoint):
    public = PublicRateStore(store)
    while True:
        checkpoint()
        pending = public.pending_interpretations(generation, limit=16)
        if not pending:
            return
        for item in pending:
            checkpoint()
            public.record_check(item["request"], item["check"])


def capture_public_rates(store: EvidenceStore, run_root: Path, receipt: dict) -> dict | None:
    """No-network extension; preserve original terms capture receipt unchanged."""
    if not configured():
        return None
    public = PublicRateStore(store)
    generation = receipt["generation_id"]
    try:
        admission = reserve(store, generation, kind="capture")
    except BudgetDeferred as error:
        return {"schemaVersion": 1, "generationId": generation, "status": "deferred", "reasonCode": str(error),
                "networkCalled": False, "modelCalled": False, "publication": "disabled"}
    try:
        with admission:
            return _capture_public_rates(store, run_root, receipt, public, admission)
    except BudgetDeferred as error:
        return {"schemaVersion": 1, "generationId": generation, "status": "deferred", "reasonCode": str(error),
                "networkCalled": False, "modelCalled": False, "publication": "disabled"}
    finally:
        admission.settle(body_bytes=0)


def _capture_public_rates(store, run_root, receipt, public, admission):
    generation = receipt["generation_id"]
    prior = store.db.execute("SELECT * FROM public_rate_compile_jobs WHERE ingest_id=?", (generation,)).fetchone()
    if prior:
        if prior["receipt_sha256"] != byte_digest(canonical_json_bytes(receipt)):
            raise ValueError("public_compile_job_identity_changed")
        requests = public.queue_sources(prior["register_id"], ingest_id=generation, now=receipt["captured_at"])
        return {"schemaVersion": 1, "generationId": generation, "registerId": prior["register_id"],
                "acquisitionRequests": len(requests), "candidate": {"status": "deferred", "reasonCode": "deterministic_compilation_queued", "publication": "disabled"},
                "networkCalled": False, "modelCalled": False, "publication": "disabled"}
    banks = run_root / "banks"
    for entry in receipt["sources"]:
        admission.checkpoint()
        if store.db.execute("SELECT 1 FROM public_rate_compile_inputs WHERE observation_id=?", (entry["observation_id"],)).fetchone():
            continue
        body = store.read_blob(entry["sha256"])
        record = inner_record(json.loads(body))
        section = _section(record)
        if section is None:
            continue
        path = run_root / entry["relative_path"]
        base = bank_base_row(path, banks, record)
        retain_compile_input(store, path, banks, base, body, entry["observation_id"])
    admission.checkpoint()
    products = []
    for row in store.db.execute("SELECT context_json FROM public_rate_compile_inputs WHERE ingest_id=? ORDER BY observation_id", (generation,)):
        admission.checkpoint()
        products.append(_pending_product(json.loads(row[0])))
    holder_root = banks / "_holders"
    holders = sorted(path.name for path in holder_root.iterdir() if path.is_dir()) if holder_root.is_dir() else []
    provider_inventory = inventory_from_compiled({"products": products, "programmes": []}, holders)
    for item in provider_inventory:
        admission.checkpoint()
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
        receipt_sha = store.put_blob(canonical_json_bytes(receipt))
        existing = store.db.execute("SELECT * FROM public_rate_compile_jobs WHERE ingest_id=?", (generation,)).fetchone()
        if existing and (existing["register_id"] != register or existing["receipt_sha256"] != receipt_sha):
            raise ValueError("public_compile_job_identity_changed")
        store.db.execute("INSERT OR IGNORE INTO public_rate_compile_jobs VALUES (?,?,?)", (generation, register, receipt_sha))
        store.db.execute("INSERT OR IGNORE INTO public_rate_candidate_events "
            "(event_id,ingest_id,register_id,status,observed_at) VALUES (?,?,?,?,?)",
            (event, generation, register, "dirty", receipt["captured_at"]))
    return {"schemaVersion": 1, "generationId": generation, "registerId": register,
            "acquisitionRequests": len(requests), "candidate": {"status": "deferred", "reasonCode": "deterministic_compilation_queued", "publication": "disabled"},
            "networkCalled": False, "modelCalled": False, "publication": "disabled"}


def compiled_generation(store: EvidenceStore, generation: str, *, include_programmes: bool = True,
                        include_evidence: bool = True, checkpoint=lambda: None) -> dict:
    checkpoint()
    result = {"products": [], "programmes": [], "evidence": []}
    rows = [dict(row) for row in store.db.execute("SELECT v.*,o.source_sha256,o.observed_at FROM public_rate_product_versions v JOIN observations o "
        "USING(observation_id) WHERE o.ingest_id=? ORDER BY v.product_id", (generation,)).fetchall()
            ]
    current = {row["product_id"] for row in rows}
    pending = [json.loads(row[0]) for row in store.db.execute("SELECT i.context_json FROM public_rate_compile_inputs i WHERE i.ingest_id=? "
        "AND NOT EXISTS (SELECT 1 FROM public_rate_product_versions v WHERE v.observation_id=i.observation_id) ORDER BY i.observation_id", (generation,))]
    current.update(context["productId"] for context in pending)
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
        checkpoint()
        project = _source_clock_projection(store, row["observation_id"])
        product = json.loads(row["discovery_json"])
        # Retain dated public names when the same stable product changes names.
        observed_names = store.db.execute("SELECT json_extract(v.discovery_json,'$.name') name, "
            "MIN(o.observed_at) first_observed_at, MAX(o.observed_at) last_observed_at "
            "FROM public_rate_product_versions v JOIN observations o USING(observation_id) "
            "WHERE v.product_id=? AND julianday(o.observed_at)<=julianday(?) "
            "GROUP BY json_extract(v.discovery_json,'$.name') ORDER BY name LIMIT 64",
            (row["product_id"], clock[0] if clock else row.get("observed_at", ""))).fetchall()
        aliases = {item["name"]: item for item in product["aliases"]}
        for entry in observed_names:
            # These are public observation dates, separate from any explicitly
            # published lender-effective alias period already retained.
            alias = aliases.setdefault(entry["name"], {"name": entry["name"]})
            alias["firstObservedAt"] = entry["first_observed_at"]
            alias["lastObservedAt"] = entry["last_observed_at"]
        product["aliases"] = sorted(aliases.values(), key=lambda item: item["name"])[:64]
        if row.get("historical"):
            if product["status"] != "legacy":
                product["status"] = "unknown"
            product["reasonCodes"] = sorted(set(product["reasonCodes"] + ["historical_public_product_not_in_selected_ingest"]))
            if "freshness" in product:
                product["freshness"] = {**product["freshness"], "state": "stale", "reasonCodes": ["product_source_not_in_selected_ingest"]}
        result["products"].append(project(product))
        if include_programmes:
            result["programmes"].extend(_programmes_for_observation(store, row["observation_id"], historical=bool(row.get("historical"))))
        if include_evidence:
            for source in store.db.execute("SELECT evidence_json FROM public_rate_source_evidence WHERE observation_id=?", (row["observation_id"],)):
                item = project(json.loads(source[0]))
                evidence[item["evidenceId"]] = item
    result["evidence"] = list(evidence.values())
    for context in pending:
        checkpoint()
        result["products"].append(_pending_product(context))
    if len(result["products"]) > MAX_PRODUCTS:
        raise ValueError("public_candidate_product_budget_exceeded")
    if not include_programmes or not include_evidence:
        result["_selection"] = [{"observationId": row["observation_id"], "historical": bool(row.get("historical"))} for row in rows]
    return result


def _programmes_for_observation(store: EvidenceStore, observation_id: str, *, historical: bool):
    project = _source_clock_projection(store, observation_id)
    rows = store.db.execute("SELECT * FROM public_rate_programme_versions WHERE observation_id=? ORDER BY programme_id", (observation_id,))
    for row in rows:
        value = json.loads(store.read_blob(row["body_sha256"]))
        if historical:
            value["freshness"] = {**value["freshness"], "state": "stale", "reasonCodes": ["product_source_not_in_selected_ingest"]}
            value["reasonCodes"] = sorted(set(value["reasonCodes"] + ["historical_public_product_not_in_selected_ingest"]))
        yield project(value)


def write_candidate(store: EvidenceStore, *, generation: str, run_date: str, register_id: str,
                    as_of: str | None = None, deadline: float | None = None, guard=None, admission=None) -> dict:
    owned = admission is None
    token = admission or reserve(store, generation, kind="candidate", deadline=deadline, guard=guard)
    try:
        with token:
            snapshot = store.db.execute("SELECT * FROM public_rate_candidate_events WHERE ingest_id=? AND register_id=? "
                                        "ORDER BY sequence DESC LIMIT 1", (generation, register_id)).fetchone()
            return _write_candidate(store, generation=generation, run_date=run_date, register_id=register_id,
                                    as_of=as_of, admission=token, snapshot=dict(snapshot) if snapshot else None)
    finally:
        if owned:
            token.settle(body_bytes=0)


def _generation_install_reason(store, generation):
    from cdr_public_rates_runtime import selected_public_generation
    from cdr_public_rates_candidate import read_candidate
    selected = selected_public_generation(store.root)
    if selected and selected != generation:
        return "candidate_generation_not_selected"
    pointer = store.root / "public-rate-catalogue-candidate.json"
    if not pointer.exists():
        return None
    try:
        current = read_candidate(pointer)["generationId"]
    except (OSError, ValueError, KeyError, TypeError):
        return "candidate_current_pointer_unreadable"
    if current == generation:
        return None
    clocks = {row["ingest_id"]: row["clock"] for row in store.db.execute(
        "SELECT ingest_id,julianday(source_observed_at) clock FROM ingest_capture_attempts WHERE ingest_id IN (?,?)",
        (generation, current))}
    incoming, installed = clocks.get(generation), clocks.get(current)
    if incoming is None or installed is None:
        return "candidate_generation_order_ambiguous"
    if incoming < installed:
        return "candidate_generation_superseded"
    if incoming == installed and selected != generation:
        return "candidate_generation_order_ambiguous"
    return None


def _write_candidate(store, *, generation, run_date, register_id, as_of, admission, snapshot):
    checkpoint = admission.checkpoint
    checkpoint()
    public = PublicRateStore(store)
    compiled = compiled_generation(store, generation, include_programmes=False, include_evidence=False, checkpoint=checkpoint)
    checkpoint()
    when = as_of or utc_now()
    reference = public.catalogue_inputs(register_id, ingest_id=generation, as_of=when)
    checkpoint()
    for product in compiled["products"]:
        checkpoint()
        product["referenceIds"] = reference_ids_for_product(product, reference["referenceRates"])
    # The register is immutable; completed deterministic compilation updates
    # candidate coverage without changing the retained discovery baseline.
    for coverage in reference["coverage"]:
        checkpoint()
        matching = [product for product in compiled["products"] if product["providerId"] == coverage["providerId"] and product["section"] == coverage["section"]]
        supported = store.db.execute("SELECT COUNT(*) FROM public_rate_programme_versions v "
            "JOIN public_rate_programme_summaries s USING(version_id) JOIN public_rate_programmes p USING(programme_id) "
            "JOIN public_rate_products product USING(product_id) JOIN observations o ON o.observation_id=v.observation_id "
            "WHERE o.ingest_id=? AND product.provider_id=? AND s.has_formula=1 "
            "AND json_extract((SELECT discovery_json FROM public_rate_product_versions pv WHERE pv.observation_id=v.observation_id LIMIT 1),'$.section')=?",
            (generation, coverage["providerId"], coverage["section"])).fetchone()[0]
        coverage["products"] = len(matching)
        coverage["programmesWithFormula"] = supported
        coverage["resolutionStatus"] = "candidate" if supported else "unresolved"
        if any("pricing_compilation_deferred" in product["reasonCodes"] for product in matching):
            coverage["reasonCodes"] = sorted(set(coverage["reasonCodes"] + ["pricing_compilation_deferred"]))
    directory = store.root / "public-rate-candidates" / digest(generation)
    directory.mkdir(parents=True, exist_ok=True)

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
            project = _source_clock_projection(store, selection["observationId"])
            for row in store.db.execute("SELECT evidence_json FROM public_rate_source_evidence WHERE observation_id=? ORDER BY evidence_id", (selection["observationId"],)):
                value = project(json.loads(row[0]))
                if value["evidenceId"] not in seen:
                    seen.add(value["evidenceId"])
                    yield value

    evidence_chunks = write_chunks(directory, generation, "evidence", evidence(), checkpoint=checkpoint)
    candidate = {"schemaVersion": 1, "generationId": generation, "runDate": run_date,
        "products": compiled["products"], "programmes": [], "referenceRates": reference["referenceRates"],
        "evidence": reference["evidence"], "programmeChunks": programme_chunks, "evidenceChunks": evidence_chunks,
        "coverage": reference["coverage"], "enabledProgrammeIds": []}
    checkpoint()
    body = canonical_json_bytes(candidate)
    if len(body) > MAX_ROOT_BYTES:
        raise ValueError("public_candidate_decoded_budget_exceeded")
    identity = byte_digest(body)
    target = directory / (identity + ".json")
    checkpoint()
    atomic_write_json(target, candidate, create_once=True)
    # Mutable discovery pointer is never publication evidence. Builders should
    # take the returned immutable file, and still bind its generation to core.
    result = {"file": str(target), "sha256": byte_digest(target.read_bytes()), "candidateId": identity,
            "programmes": sum(len(chunk["programmeIds"]) for chunk in programme_chunks),
            "products": len(candidate["products"]), "references": len(candidate["referenceRates"]), "publication": "disabled"}
    checkpoint()
    from cdr_public_rates_runtime import queue_candidate_update, public_snapshot_fence
    with public_snapshot_fence(store.root):
        with store.db:
            store.db.execute("BEGIN IMMEDIATE")
            latest = store.db.execute("SELECT * FROM public_rate_candidate_events WHERE ingest_id=? AND register_id=? "
                                     "ORDER BY sequence DESC LIMIT 1", (generation, register_id)).fetchone()
            if (latest["sequence"] if latest else None) != (snapshot["sequence"] if snapshot else None):
                return {**result, "status": "deferred", "reasonCode": "candidate_snapshot_superseded"}
            generation_reason = _generation_install_reason(store, generation)
            if generation_reason:
                return {**result, "status": "deferred", "reasonCode": generation_reason}
            checkpoint()
            atomic_write_json(store.root / "public-rate-catalogue-candidate.json", {"schemaVersion": 1,
                "candidateFile": target.relative_to(store.root).as_posix(), "sha256": identity})
            if latest and latest["status"] == "dirty":
                store.db.execute("INSERT OR IGNORE INTO public_rate_candidate_events "
                    "(event_id,ingest_id,register_id,status,observed_at) VALUES (?,?,?,?,?)",
                    (digest([latest["event_id"], "fresh", result["sha256"]]), generation, register_id, "fresh", utc_now()))
        # The callback reads independently committed source state and takes
        # publisher pending-file locks. Keep the shared fence, but release the
        # source DB transaction before invoking it.
        result["publicationUpdate"] = queue_candidate_update(store.root, result)
    public.record_coverage(register_id, ingest_id=generation, coverage=reference["coverage"], observed_at=when)
    return result


def pending_candidate(store: EvidenceStore) -> dict | None:
    if not configured():
        return None
    public = PublicRateStore(store)
    # An accepted check is durable even if the worker died before linking it
    # to the pricing lane. Queue replay without manufacturing a source check.
    for item in public.pending_interpretations(None, limit=16):
        request, check = item["request"], item["check"]
        for binding in public.bindings(request["document_id"], request["ingest_id"]):
            with store.db:
                store.db.execute("INSERT OR IGNORE INTO public_rate_candidate_events "
                    "(event_id,ingest_id,register_id,status,observed_at) VALUES (?,?,?,?,?)",
                    (digest([binding["register_id"], check["check_id"], "deterministic_replay_pending"]),
                     request["ingest_id"], binding["register_id"], "dirty", utc_now()))
    row = store.db.execute("SELECT * FROM public_rate_candidate_events e WHERE e.sequence="
        "(SELECT MAX(sequence) FROM public_rate_candidate_events p WHERE p.ingest_id=e.ingest_id "
        "AND p.register_id=e.register_id) AND e.status='dirty' AND " + available_sql("e", bytes_required=False) +
        " ORDER BY COALESCE((SELECT MAX(br.observed_at) FROM public_rate_budget_reservations br "
        "WHERE br.ingest_id=e.ingest_id AND br.kind='candidate'),e.observed_at),e.sequence LIMIT 1").fetchone()
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
        token = reserve(store, pending["ingest_id"], kind="candidate", deadline=deadline, guard=guard)
    except BudgetDeferred as error:
        return {"status": "deferred", "reasonCode": str(error), "publication": "disabled"}
    try:
        with token:
            _replay_pending_checks(store, pending["ingest_id"], token.checkpoint)
            _compile_pending(store, pending["ingest_id"], token.checkpoint)
            result = write_candidate(store, generation=pending["ingest_id"], run_date=receipt["source_run_date"],
                                     register_id=pending["register_id"], admission=token)
    except BudgetDeferred as error:
        return {"status": "deferred", "reasonCode": str(error), "publication": "disabled"}
    finally:
        token.settle(body_bytes=0)
    return {**result, "status": result.get("status", "candidate_written"), "generationId": pending["ingest_id"]}
