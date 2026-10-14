"""Public pricing observations in the existing append-only evidence archive."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from .identity import canonical_json, digest, timestamp, utc_now
from .store import EvidenceStore

MAX_REFERENCE_FAMILIES_PER_SOURCE = 4096


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("public_pricing_clock_requires_timezone")
    return parsed.astimezone(timezone.utc)


class PublicRateStore:
    def __init__(self, store: EvidenceStore):
        self.store = store

    def register(self, inventory: dict, *, observed_at: str) -> str:
        if inventory.get("publicOnly") is not True or inventory.get("schemaVersion") != 1:
            raise ValueError("public_source_inventory_required")
        sha = self.store.put_blob(canonical_json(inventory).encode("utf-8"))
        identity = digest([inventory["registerVersion"], sha])
        with self.store.db:
            self.store.db.execute("INSERT OR IGNORE INTO public_rate_registers VALUES (?,?,?,?)",
                (identity, inventory["registerVersion"], sha, timestamp(observed_at)))
            for source in inventory["sources"]:
                document = self.store.register_document(source["url"])
                binding = digest([identity, source["sourceId"]])
                self.store.db.execute("INSERT OR IGNORE INTO public_rate_sources VALUES (?,?,?,?,?,?,?)",
                    (binding, source["sourceId"], identity, document, source["adapterId"], source["adapterVersion"], canonical_json(source)))
        return identity

    def record_compiled(self, observation_id: str, compiled: dict) -> None:
        observation = self.store.db.execute("SELECT * FROM observations WHERE observation_id=?", (observation_id,)).fetchone()
        if not observation:
            raise ValueError("pricing_requires_retained_public_cdr_observation")
        product = compiled["product"]
        if observation["product_key"] != product["productKey"]:
            raise ValueError("pricing_product_observation_mismatch")
        sources = {source["evidenceId"]: source for source in compiled["evidence"]}
        with self.store.db:
            for source in sources.values():
                if source["sha256"] != observation["source_sha256"]:
                    raise ValueError("public_source_hash_mismatch")
                self._insert_exact("public_rate_source_evidence", (source["evidenceId"], observation_id, canonical_json(source)),
                    "evidence_id=? AND observation_id=?", (source["evidenceId"], observation_id))
            self.store.db.execute("INSERT OR IGNORE INTO public_rate_products VALUES (?,?,?)",
                (product["productId"], product["providerId"], product["productKey"]))
            self._insert_exact("public_rate_product_versions", (product["productId"], observation_id, canonical_json(product)),
                "product_id=? AND observation_id=?", (product["productId"], observation_id))
            for programme in compiled["programmes"]:
                self.store.db.execute("INSERT OR IGNORE INTO public_rate_programmes VALUES (?,?,?)",
                    (programme["programmeId"], product["productId"], programme["offerId"]))
                body = self.store.put_blob(canonical_json(programme).encode("utf-8"))
                version = digest([programme["programmeId"], observation_id, body])
                self._insert_exact("public_rate_programme_versions", (version, programme["programmeId"], observation_id, body),
                    "programme_id=? AND observation_id=?", (programme["programmeId"], observation_id))
                self._insert_exact("public_rate_programme_summaries", (version, int(bool(programme.get("formula")))),
                    "version_id=?", (version,))
                for evidence_id in programme["evidenceIds"]:
                    source = sources.get(evidence_id)
                    if not source or source["sha256"] != observation["source_sha256"]:
                        raise ValueError("programme_evidence_does_not_bind_public_observation")
                    self.store.db.execute("INSERT OR IGNORE INTO public_rate_evidence_bindings VALUES (?,?,?,?,?)",
                        (version, evidence_id, observation_id, None, canonical_json(source["locator"])))

    def _insert_exact(self, table: str, values: tuple, clause: str, key: tuple) -> None:
        # Table/column names are checked-in literals from this controller only.
        previous = self.store.db.execute(f"SELECT * FROM {table} WHERE {clause}", key).fetchone()
        if previous and tuple(previous) != values:
            raise ValueError("public_pricing_immutable_version_changed")
        self.store.db.execute(f"INSERT OR IGNORE INTO {table} VALUES ({','.join('?' for _ in values)})", values)

    def queue_sources(self, register_id: str, *, ingest_id: str, now: str) -> list[str]:
        from .acquisitions_queue import AcquisitionQueue
        queue = AcquisitionQueue(self.store)
        requests = set()
        bindings = self.store.db.execute("SELECT * FROM public_rate_sources WHERE register_id=? ORDER BY source_id", (register_id,)).fetchall()
        with self.store.db:
            for binding in bindings:
                source = json.loads(binding["context_json"])
                request_id = digest([ingest_id, binding["document_id"]])
                self.store.db.execute("INSERT OR IGNORE INTO acquisition_requests VALUES (?,?,?,?,?)",
                    (request_id, binding["document_id"], ingest_id, timestamp(now), 1))
                self.store.db.execute("INSERT OR IGNORE INTO public_rate_request_bindings VALUES (?,?)",
                    (request_id, binding["binding_id"]))
                if not self.store.db.execute("SELECT 1 FROM acquisition_events WHERE request_id=?", (request_id,)).fetchone():
                    queue._event(request_id, "queued", timestamp(now))
                requests.add(request_id)
                rows = self.store.db.execute("SELECT o.observation_id FROM observations o JOIN public_rate_product_versions v "
                    "USING(observation_id) JOIN public_rate_products p USING(product_id) WHERE o.ingest_id=? AND p.provider_id=?",
                    (ingest_id, source["providerId"])).fetchall()
                for row in rows:
                    path = "/public_rate_register/" + source["registeredSourceId"]
                    context = canonical_json({"public_rate_binding_id": binding["binding_id"], "url": source["url"], "allowed_hosts": source["allowedHosts"]})
                    applicability = digest([row[0], binding["document_id"], path, context])
                    self.store.db.execute("INSERT OR IGNORE INTO applicability VALUES (?,?,?,?,?,?)",
                        (applicability, row[0], binding["document_id"], path, "registered_public_reference", context))
                    self.store.db.execute("INSERT OR IGNORE INTO acquisition_bindings VALUES (?,?)", (request_id, row[0]))
        return sorted(requests)

    def bindings(self, document_id: str, ingest_id: str) -> list[dict]:
        # A source must have been explicitly registered for this ingest's scope.
        direct = self.store.db.execute("SELECT s.* FROM public_rate_sources s JOIN public_rate_request_bindings b USING(binding_id) "
            "JOIN acquisition_requests r USING(request_id) WHERE r.document_id=? AND r.ingest_id=? ORDER BY s.binding_id",
            (document_id, ingest_id)).fetchall()
        if direct:
            return [dict(row) for row in direct]
        rows = self.store.db.execute("SELECT DISTINCT s.* FROM public_rate_sources s JOIN applicability a USING(document_id) "
            "JOIN observations o USING(observation_id) WHERE s.document_id=? AND o.ingest_id=? "
            "AND a.relation='registered_public_reference' AND a.context_json LIKE ? ORDER BY s.binding_id",
            (document_id, ingest_id, '%public_rate_binding_id%')).fetchall()
        result = []
        for row in rows:
            found = self.store.db.execute("SELECT 1 FROM applicability a JOIN observations o USING(observation_id) "
                "WHERE a.document_id=? AND o.ingest_id=? AND a.relation='registered_public_reference' "
                "AND json_extract(a.context_json,'$.public_rate_binding_id')=? LIMIT 1",
                (document_id, ingest_id, row["binding_id"])).fetchone()
            if found:
                result.append(dict(row))
        return result

    def request_hosts(self, request_id: str) -> frozenset[str]:
        rows = self.store.db.execute("SELECT s.context_json FROM public_rate_sources s JOIN public_rate_request_bindings b "
            "USING(binding_id) WHERE b.request_id=?", (request_id,)).fetchall()
        return frozenset(host for row in rows for host in json.loads(row[0])["allowedHosts"])

    def needs_unconditional(self, document_id: str, *, now: str | None = None) -> bool:
        previous = self.store.db.execute("SELECT checked_at FROM acquisition_checks WHERE document_id=? "
            "AND status='fetched' ORDER BY checked_at DESC,sequence DESC LIMIT 1", (document_id,)).fetchone()
        return not previous or _time(now or utc_now()) - _time(previous[0]) >= timedelta(days=7)

    def record_check(self, request: dict, check: dict) -> list[dict]:
        from cdr_public_rates_reference import extract_reference
        retained = self.store.db.execute("SELECT * FROM acquisition_checks WHERE check_id=?", (check["check_id"],)).fetchone()
        actual = self.store.db.execute("SELECT * FROM acquisition_requests WHERE request_id=?", (request["request_id"],)).fetchone()
        if (not retained or dict(retained) != check or not actual
                or actual["document_id"] != request["document_id"] or actual["ingest_id"] != request["ingest_id"]):
            raise ValueError("pricing_check_identity_mismatch")
        accepted = self.store.db.execute("SELECT 1 FROM acquisition_events e JOIN acquisition_events lease ON "
            "e.request_id=lease.request_id AND e.lease_id=lease.lease_id WHERE e.request_id=? AND e.check_id=? "
            "AND e.status IN ('complete','retry_wait','blocked') AND lease.status='running' AND lease.sequence<e.sequence "
            "AND ?>=lease.observed_at AND ?<=e.observed_at AND e.observed_at<lease.lease_expires_at LIMIT 1",
            (request["request_id"], check["check_id"], check["checked_at"], check["checked_at"])).fetchone()
        if not accepted or retained["document_id"] != actual["document_id"]:
            raise ValueError("pricing_check_requires_accepted_source_lease")
        outcomes = []
        for binding in self.bindings(request["document_id"], request["ingest_id"]):
            with self.store.db:
                self.store.db.execute("INSERT OR IGNORE INTO public_rate_checks VALUES (?,?,?,?)",
                    (binding["binding_id"], check["check_id"], request["ingest_id"], request["request_id"]))
                self.store.db.execute("INSERT OR IGNORE INTO public_rate_candidate_events "
                    "(event_id,ingest_id,register_id,status,observed_at) VALUES (?,?,?,?,?)",
                    (digest([binding["register_id"], check["check_id"], "dirty"]), request["ingest_id"],
                     binding["register_id"], "dirty", check["checked_at"]))
            if check["status"] not in {"fetched", "unchanged"}:
                continue
            previous = self.store.db.execute("SELECT * FROM public_rate_extractions WHERE binding_id=? "
                "AND document_version_id=? AND adapter_version=?", (binding["binding_id"], check["document_version_id"], binding["adapter_version"])).fetchone()
            if previous:
                self._retain_extraction_evidence(previous["extraction_id"], json.loads(self.store.read_blob(previous["result_sha256"])))
                outcomes.append(dict(previous))
                continue
            source = json.loads(binding["context_json"])
            version = self.store.db.execute("SELECT * FROM document_versions WHERE document_version_id=?", (check["document_version_id"],)).fetchone()
            metadata = json.loads(check["metadata_json"])
            context = {**source, "sourceUrl": metadata.get("final_url") or source["url"],
                       "sourceSha256": version["content_sha256"], "checkedAt": check["checked_at"]}
            result = extract_reference(self.store.read_blob(version["content_sha256"]), context)
            if result["status"] == "validated":
                values = {}
                for rate in result["referenceRates"]:
                    meaning = canonical_json({field: rate.get(field) for field in
                        ("value", "unit", "conditions", "effectiveFrom", "effectiveTo")})
                    if rate["referenceId"] in values and values[rate["referenceId"]] != meaning:
                        result.update(status="unresolved", reasonCode="conflicting_reference_rows")
                        break
                    values[rate["referenceId"]] = meaning
            sha = self.store.put_blob(canonical_json(result).encode("utf-8"))
            identity = digest([binding["binding_id"], check["document_version_id"], binding["adapter_version"]])
            with self.store.db:
                self.store.db.execute("INSERT OR IGNORE INTO public_rate_extractions VALUES (?,?,?,?,?,?,?,?,?)",
                    (identity, binding["binding_id"], check["document_version_id"], binding["adapter_version"], result["semanticSha256"], sha,
                     result["status"], check["checked_at"], result.get("reasonCode")))
                if result["status"] == "validated":
                    for rate in result["referenceRates"]:
                        key = digest([rate["referenceId"], identity])
                        self.store.db.execute("INSERT OR IGNORE INTO public_rate_observations VALUES (?,?,?,?,?,?)",
                            (key, rate["referenceId"], identity, canonical_json(rate), rate.get("effectiveFrom"), rate.get("effectiveTo")))
                elif result["status"] in {"review_required", "unresolved"}:
                    self.store.db.execute("INSERT OR IGNORE INTO public_rate_review_queue VALUES (?,?,?,?,?)",
                        (digest([identity, "adapter-review"]), identity, result["reasonCode"], check["checked_at"], "reviewed_adapter_change_required"))
                self._retain_extraction_evidence(identity, result)
            outcomes.append({"extraction_id": identity, "status": result["status"], "reason_code": result.get("reasonCode")})
        return outcomes

    def _retain_extraction_evidence(self, extraction_id: str, result: dict) -> None:
        # A narrow additive projection avoids rereading every historical result
        # blob to serve current evidence. Existing extraction bodies stay frozen.
        with self.store.db:
            for evidence in result["evidence"]:
                self._insert_exact("public_rate_extraction_evidence",
                    (extraction_id, evidence["evidenceId"], canonical_json(evidence)),
                    "extraction_id=? AND evidence_id=?", (extraction_id, evidence["evidenceId"]))

    def source_freshness(self, binding: dict, *, ingest_id: str, as_of: str) -> dict:
        check = self.store.db.execute("SELECT c.* FROM public_rate_checks p JOIN acquisition_checks c USING(check_id) "
            "WHERE p.binding_id=? AND p.ingest_id=? AND julianday(c.checked_at)<=julianday(?) "
            "ORDER BY c.checked_at DESC,c.sequence DESC LIMIT 1", (binding["binding_id"], ingest_id, as_of)).fetchone()
        last = self.store.db.execute("SELECT c.checked_at FROM public_rate_checks p JOIN acquisition_checks c USING(check_id) "
            "JOIN public_rate_sources s ON s.binding_id=p.binding_id "
            "JOIN public_rate_extractions x ON x.binding_id=p.binding_id AND x.document_version_id=c.document_version_id "
            "WHERE s.source_id=? AND s.document_id=? AND s.adapter_id=? AND x.status='validated' "
            "AND julianday(c.checked_at)<=julianday(?) ORDER BY c.checked_at DESC,c.sequence DESC LIMIT 1",
            (binding["source_id"], binding["document_id"], binding["adapter_id"], as_of)).fetchone()
        state, reasons = "deferred", ["source_check_deferred"]
        if check:
            if check["status"] in {"failed", "deferred"}:
                state, reasons = check["status"], [check["error_code"]]
            else:
                parsed = self.store.db.execute("SELECT status,reason_code FROM public_rate_extractions WHERE binding_id=? "
                    "AND document_version_id=? AND adapter_version=?", (binding["binding_id"], check["document_version_id"], binding["adapter_version"])).fetchone()
                state, reasons = ("current", []) if parsed and parsed[0] == "validated" else ("failed", [parsed[1] if parsed else "source_extraction_pending"])
        if last and _time(as_of) - _time(last[0]) > timedelta(hours=48):
            state, reasons = "stale", [*reasons, "source_check_older_than_48_hours"]
        output = {"state": state, "reasonCodes": sorted(set(reasons))}
        if check:
            output["checkedAt"] = check["checked_at"]
        if last:
            output["lastSuccessAt"] = last[0]
        return output

    def catalogue_inputs(self, register_id: str, *, ingest_id: str, as_of: str) -> dict:
        row = self.store.db.execute("SELECT body_sha256 FROM public_rate_registers WHERE register_id=?", (register_id,)).fetchone()
        inventory = json.loads(self.store.read_blob(row[0]))
        bindings = [dict(row) for row in self.store.db.execute("SELECT * FROM public_rate_sources WHERE register_id=? ORDER BY source_id", (register_id,))]
        freshness = {binding["source_id"]: self.source_freshness(binding, ingest_id=ingest_id, as_of=as_of) for binding in bindings}
        references, evidence = {}, {}
        for binding in bindings:
            source = json.loads(binding["context_json"])
            fresh = dict(freshness[binding["source_id"]])
            for dependency in source.get("dependencies", []):
                dependency_fresh = freshness.get(dependency + ":" + digest(source["providerId"])[:16])
                if not dependency_fresh or dependency_fresh["state"] != "current":
                    fresh = {**fresh, "state": (dependency_fresh or {}).get("state", "unknown"),
                             "reasonCodes": [*fresh["reasonCodes"], "reference_definition_check_unverified"]}
            latest = self.store.db.execute("SELECT x.* FROM public_rate_extractions x JOIN public_rate_sources s USING(binding_id) "
                "WHERE s.source_id=? AND s.adapter_id=? AND x.status='validated' AND julianday(x.observed_at)<=julianday(?) "
                "ORDER BY x.observed_at DESC,x.extraction_id DESC LIMIT 1", (binding["source_id"], binding["adapter_id"], as_of)).fetchone()
            latest_families = {row[0] for row in self.store.db.execute(
                "SELECT reference_id FROM public_rate_observations WHERE extraction_id=?", (latest["extraction_id"],))} if latest else set()
            # Select one applicable observation per semantic family in SQLite.
            # Collection history must not create an unbounded Python blob scan.
            selected = [dict(row) for row in self.store.db.execute("WITH ranked AS (SELECT r.*,x.document_version_id,x.adapter_version,x.observed_at,"
                "ROW_NUMBER() OVER (PARTITION BY r.reference_id ORDER BY COALESCE(julianday(r.effective_from),0) DESC,x.observed_at DESC,x.extraction_id DESC) place "
                "FROM public_rate_observations r JOIN public_rate_extractions x USING(extraction_id) "
                "JOIN public_rate_sources s USING(binding_id) WHERE s.source_id=? AND s.adapter_id=? AND x.status='validated' "
                "AND julianday(x.observed_at)<=julianday(?) "
                "AND (r.effective_from IS NULL OR julianday(r.effective_from)<=julianday(?))) "
                "SELECT * FROM ranked WHERE place=1 ORDER BY reference_id LIMIT ?",
                (binding["source_id"], binding["adapter_id"], as_of, as_of, MAX_REFERENCE_FAMILIES_PER_SOURCE + 1)).fetchall()]
            future = [dict(row) for row in self.store.db.execute("WITH ranked AS (SELECT r.*,x.document_version_id,x.adapter_version,x.observed_at,"
                "ROW_NUMBER() OVER (PARTITION BY r.reference_id,r.effective_from ORDER BY x.observed_at DESC,x.extraction_id DESC) place "
                "FROM public_rate_observations r JOIN public_rate_extractions x USING(extraction_id) JOIN public_rate_sources s USING(binding_id) "
                "WHERE s.source_id=? AND s.adapter_id=? AND x.status='validated' AND julianday(x.observed_at)<=julianday(?) "
                "AND julianday(r.effective_from)>julianday(?)) SELECT * FROM ranked WHERE place=1 "
                "ORDER BY reference_id,effective_from LIMIT ?", (binding["source_id"], binding["adapter_id"], as_of, as_of,
                MAX_REFERENCE_FAMILIES_PER_SOURCE + 1)).fetchall()]
            selected.extend(future)
            if len(selected) > MAX_REFERENCE_FAMILIES_PER_SOURCE:
                raise ValueError("public_reference_family_budget_exceeded")
            used_extractions = set()
            for observation in selected:
                rate = json.loads(observation["value_json"])
                family = rate["referenceId"]
                key = (family, rate.get("effectiveFrom"))
                projected = {field: rate[field] for field in ("referenceId", "providerId", "name", "value", "unit", "scopeId", "conditions", "evidenceIds", "effectiveFrom", "effectiveTo") if field in rate}
                observed_fresh = dict(fresh)
                if family not in latest_families or observation["adapter_version"] != binding["adapter_version"]:
                    observed_fresh = {**fresh, "state": "unknown", "reasonCodes": [*fresh["reasonCodes"], "reference_family_not_in_latest_public_source"]}
                    verified = self.store.db.execute("SELECT c.checked_at FROM public_rate_checks p JOIN acquisition_checks c USING(check_id) "
                        "JOIN public_rate_sources s USING(binding_id) WHERE s.source_id=? AND c.document_version_id=? "
                        "AND c.status IN ('fetched','unchanged') AND julianday(c.checked_at)<=julianday(?) "
                        "ORDER BY c.checked_at DESC LIMIT 1", (binding["source_id"], observation["document_version_id"], as_of)).fetchone()
                    if verified:
                        observed_fresh["lastSuccessAt"] = verified[0]
                if rate.get("effectiveTo") and _time(rate["effectiveTo"]) <= _time(as_of):
                    observed_fresh = {**observed_fresh, "state": "unknown", "reasonCodes": [*observed_fresh["reasonCodes"], "public_reference_effective_period_ended"]}
                projected["freshness"] = observed_fresh if "value" in rate else {**observed_fresh, "state": "unknown", "reasonCodes": ["public_reference_unavailable"]}
                if key in references:
                    existing = references[key]
                    existing["evidenceIds"] = sorted(set(existing["evidenceIds"] + projected["evidenceIds"]))
                    if (existing.get("value"), existing["unit"], existing.get("effectiveTo")) != (projected.get("value"), projected["unit"], projected.get("effectiveTo")):
                        existing.pop("value", None)
                        existing["freshness"] = {**existing["freshness"], "state": "failed", "reasonCodes": ["conflicting_reference_sources"]}
                    elif projected["freshness"]["state"] != "current":
                        existing["freshness"] = projected["freshness"]
                else:
                    references[key] = projected
                used_extractions.add(observation["extraction_id"])
            for identity in used_extractions:
                retained = self.store.db.execute("SELECT evidence_json FROM public_rate_extraction_evidence WHERE extraction_id=?", (identity,)).fetchall()
                if not retained:
                    previous = self.store.db.execute("SELECT result_sha256 FROM public_rate_extractions WHERE extraction_id=?", (identity,)).fetchone()
                    self._retain_extraction_evidence(identity, json.loads(self.store.read_blob(previous[0])))
                    retained = self.store.db.execute("SELECT evidence_json FROM public_rate_extraction_evidence WHERE extraction_id=?", (identity,)).fetchall()
                for entry in retained:
                    item = json.loads(entry[0])
                    evidence.setdefault(item["evidenceId"], item)
        coverage = inventory["coverage"]
        # A known future change bounds the old observation now. It cannot remain
        # a verified current rate tomorrow merely because its check is <48h old.
        families = {}
        for rate in references.values():
            families.setdefault(rate["referenceId"], []).append(rate)
        for versions in families.values():
            versions.sort(key=lambda rate: _time(rate["effectiveFrom"]) if rate.get("effectiveFrom") else datetime.min.replace(tzinfo=timezone.utc))
            for older, newer in zip(versions, versions[1:]):
                boundary = newer.get("effectiveFrom")
                if boundary and (not older.get("effectiveTo") or _time(boundary) < _time(older["effectiveTo"])):
                    older["effectiveTo"] = boundary
                    older["evidenceIds"] = sorted(set(older["evidenceIds"] + newer["evidenceIds"]))
        for item in coverage:
            matching = [freshness[source["sourceId"]] for source in inventory["sources"] if source["providerId"] == item["providerId"] and item["section"] in source["sections"]]
            if matching:
                state = next((state for state in ("failed", "stale", "deferred", "unknown") if any(value["state"] == state for value in matching)), "current")
                item.update(referenceSourceStatus=state,
                    sourceAcquisition=state, extraction="validated" if state == "current" else "unresolved", pricingInterpretation="deterministic_adapter", costCompleteness="unknown")
                item["reasonCodes"] = sorted({*item["reasonCodes"], *(reason for value in matching for reason in value["reasonCodes"])})
            available = [rate for rate in references.values() if rate["providerId"] == item["providerId"]]
            item["referenceRatesObserved"] = len({rate["referenceId"] for rate in available})
            item["referenceRatesCurrent"] = sum("value" in rate and rate["freshness"]["state"] == "current"
                and (not rate.get("effectiveFrom") or _time(rate["effectiveFrom"]) <= _time(as_of))
                and (not rate.get("effectiveTo") or _time(as_of) < _time(rate["effectiveTo"])) for rate in available)
            item["futureReferenceObservations"] = sum(bool(rate.get("effectiveFrom") and _time(rate["effectiveFrom"]) > _time(as_of)) for rate in available)
        return {"referenceRates": list(references.values()), "evidence": list(evidence.values()), "coverage": coverage,
                }

    def record_coverage(self, register_id: str, *, ingest_id: str, coverage: list[dict], observed_at: str) -> str:
        sha = self.store.put_blob(canonical_json(coverage).encode("utf-8"))
        identity = digest([ingest_id, register_id, sha])
        with self.store.db:
            self.store.db.execute("INSERT OR IGNORE INTO public_rate_coverage VALUES (?,?,?,?,?)",
                (identity, ingest_id, register_id, sha, timestamp(observed_at)))
        return identity
