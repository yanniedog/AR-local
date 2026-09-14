"""Measured per-stage coverage and immutable, independently gated projections."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from .identity import canonical_json, digest, exact_value, timestamp
from .observation_checks import current_observation, selected_check
from .revisions import term_source_versions
from .store import EvidenceStore

PUBLIC_SCHEMA = Path(__file__).resolve().parents[1] / "contracts" / "product_terms" / "terms-v1.schema.json"


def _stage(status: str, expected: int | None, observed: int) -> dict[str, Any]:
    return {"status": status, "expected": expected, "observed": observed}


def _documents(store: EvidenceStore, observation: Mapping[str, Any]) -> tuple[list[dict[str, Any]], int, int, int, list[str]]:
    rows = store.db.execute("SELECT DISTINCT document_id,source_url FROM applicability JOIN documents USING(document_id) "
                            "WHERE observation_id=? ORDER BY document_id", (observation["observation_id"],)).fetchall()
    documents: list[dict[str, Any]] = []
    gaps = []
    success = failure = 0
    for row in rows:
        latest = selected_check(store, observation, row["document_id"])
        status = latest["status"] if latest else "pending"
        success += status in {"fetched", "unchanged"}
        failure += status == "failed"
        if status not in {"fetched", "unchanged"}:
            gaps.append(f"Document {status}: {row['source_url']}"
                        + (f" ({latest['error_code']})" if latest and latest["error_code"] else ""))
            continue
        version = store.db.execute("SELECT v.*,d.source_url FROM document_versions v JOIN documents d USING(document_id) "
                                    "WHERE document_version_id=?", (latest["document_version_id"],)).fetchone()
        # Verify originals still exist before claiming archived coverage.
        store.read_blob(version["content_sha256"])
        documents.append({key: version[key] for key in (
            "document_version_id", "source_url", "content_sha256", "media_type", "byte_size",
            "observed_at", "effective_from", "effective_to")})
    return sorted(documents, key=lambda doc: doc["document_version_id"]), len(rows), success, failure, gaps


def _revisions(store: EvidenceStore, observation: Mapping[str, Any], versions: set[str]
               ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates = store.db.execute(
        "SELECT t.* FROM term_revisions t JOIN observations o USING(observation_id) JOIN reviews r ON "
        "r.sequence=(SELECT MAX(sequence) FROM reviews WHERE term_revision_id=t.term_revision_id) "
        "WHERE o.product_key=? AND o.source_sha256=? AND r.status='validated' ORDER BY t.term_revision_id",
        (observation["product_key"], observation["source_sha256"])).fetchall()
    superseded = {row[0] for row in store.db.execute(
        "SELECT before_revision_id FROM term_changes WHERE product_key=? AND kind IN ('changed','removed','extraction_corrected')",
        (observation["product_key"],))}
    revisions: list[dict[str, Any]] = []
    clauses: dict[str, dict[str, Any]] = {}
    for term in candidates:
        source_versions = term_source_versions(store, term["term_revision_id"])
        if term["term_revision_id"] in superseded or not source_versions <= versions:
            continue
        sources = store.db.execute("SELECT c.*,x.document_version_id FROM term_sources s JOIN clauses c USING(clause_id) "
                                   "JOIN extractions x USING(extraction_id) WHERE term_revision_id=? ORDER BY clause_id",
                                   (term["term_revision_id"],)).fetchall()
        for source in sources:
            clauses[source["clause_id"]] = {
                "clause_id": source["clause_id"], "document_version_id": source["document_version_id"],
                "locator": json.loads(source["locator_json"]), "text": source["text"][:2000],
                "excerpt_truncated": len(source["text"]) > 2000, "disposition": "interpreted",
            }
        revisions.append({
            "term_revision_id": term["term_revision_id"], "parameter_key": term["parameter_key"],
            "value": json.loads(term["value_json"]), "unit": term["unit"],
            "applicability": json.loads(term["applicability_json"]),
            "clause_ids": [source["clause_id"] for source in sources], "rule_set_id": term["rule_set_id"],
            "status": "validated", "observed_at": term["observed_at"],
        })
    return revisions, sorted(clauses.values(), key=lambda clause: clause["clause_id"])


def _coverage(store: EvidenceStore, documents: list[dict[str, Any]], expected: int,
              successes: int, failures: int, revisions: list[dict[str, Any]]) -> dict[str, Any]:
    extraction_complete = extracted = 0
    for document in documents:
        rows = store.db.execute("SELECT status,text_sha256 FROM extractions WHERE document_version_id=?",
                                (document["document_version_id"],)).fetchall()
        for row in rows:
            store.read_blob(row["text_sha256"])
        extraction_complete += any(row[0] == "complete" for row in rows)
        extracted += any(row[0] in {"partial", "complete"} for row in rows)
    acquisition = ("complete" if expected and successes == expected else
                   "failed" if failures and not successes else "partial" if successes else "pending")
    extraction = ("complete" if expected and extraction_complete == expected else
                  "partial" if extracted else "pending")
    gaps = ["Incorporated documents and full discovery scope have not been independently reconciled.",
            "Complete clause interpretation and applicability have not been independently reconciled.",
            "Calculation rules and material fee completeness have not been certified."]
    if failures:
        gaps.append(f"Latest acquisition failed for {failures} known documents; retained versions are historical evidence.")
    if expected > successes:
        gaps.append(f"{expected - successes} known documents lack a successful latest check.")
    return {
        "discovery": _stage("partial" if expected else "unknown", None, expected),
        "acquisition": _stage(acquisition if expected else "unknown", expected or None, successes),
        "extraction": _stage(extraction if expected else "unknown", expected or None, extraction_complete),
        "interpretation": _stage("partial" if revisions else "pending", None, len(revisions)),
        "calculation": _stage("unknown", None, 0), "gaps": gaps,
    }


def build_product_asset(store: EvidenceStore, product_key: str) -> dict[str, Any]:
    observation = current_observation(store, product_key)
    documents, expected, successes, failures, gaps = _documents(store, observation)
    revisions, clauses = _revisions(store, observation, {doc["document_version_id"] for doc in documents})
    changes = [{key: row[key] for key in ("term_change_id", "before_revision_id", "after_revision_id", "kind", "observed_at")}
               for row in store.db.execute("SELECT * FROM term_changes WHERE product_key=? ORDER BY observed_at,term_change_id", (product_key,))]
    payload = {
        "schema_version": 1, "product_key": product_key, "documents": documents,
        "clauses": clauses, "revisions": revisions,
        "coverage": _coverage(store, documents, expected, successes, failures, revisions), "changes": changes,
    }
    payload["coverage"]["gaps"].extend(sorted(gaps))
    payload["identity_sha256"] = digest(payload)
    validate_public_asset(payload)
    return payload


def validate_public_asset(payload: Mapping[str, Any]) -> None:
    if "historical_scope" in payload or "historical_target" in payload:
        raise ValueError("Historical-only staging cannot enter current product publication")
    schema = json.loads(PUBLIC_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
    exact_value(payload)
    if payload["identity_sha256"] != digest({key: value for key, value in payload.items() if key != "identity_sha256"}):
        raise ValueError("Product terms identity mismatch")
    documents = {item["document_version_id"] for item in payload["documents"]}
    clauses = {item["clause_id"] for item in payload["clauses"]}
    revisions = {item["term_revision_id"] for item in payload["revisions"]}
    if len(documents) != len(payload["documents"]) or len(clauses) != len(payload["clauses"]) or len(revisions) != len(payload["revisions"]):
        raise ValueError("Duplicate product evidence identities")
    for clause in payload["clauses"]:
        if clause["document_version_id"] not in documents or clause["locator"]["start"] >= clause["locator"]["end"]:
            raise ValueError("Clause has no document or has an invalid locator")
    for revision in payload["revisions"]:
        if not set(revision["clause_ids"]) <= clauses or revision["applicability"]["product_key"] != payload["product_key"]:
            raise ValueError("Term source/applicability mismatch")
    for name in ("discovery", "acquisition", "extraction", "interpretation", "calculation"):
        stage = payload["coverage"][name]
        if stage["expected"] is not None and stage["observed"] > stage["expected"]:
            raise ValueError("Coverage numerator exceeds its denominator")
        if stage["status"] == "complete" and (stage["expected"] is None or stage["observed"] != stage["expected"]):
            raise ValueError("Complete coverage requires an exact measured denominator")


def publish_product_asset(store: EvidenceStore, payload: Mapping[str, Any], *,
                          expected_previous_identity: str | None,
                          expected_observation_id: str, published_at: str) -> str:
    """Controller-only local projection CAS. This does not upload or deploy."""
    validate_public_asset(payload)
    product_key = payload["product_key"]
    with store.db:
        store.db.execute("BEGIN IMMEDIATE")
        previous = store.db.execute("SELECT * FROM publications WHERE product_key=? ORDER BY sequence DESC LIMIT 1", (product_key,)).fetchone()
        identity = previous["identity_sha256"] if previous else None
        if identity != expected_previous_identity:
            raise ValueError("Product terms publication changed; stale promotion rejected")
        if current_observation(store, product_key)["observation_id"] != expected_observation_id:
            raise ValueError("Product source observation changed; stale promotion rejected")
        if build_product_asset(store, product_key) != payload:
            raise ValueError("Document, validation or coverage changed before publication")
        if identity == payload["identity_sha256"]:
            return previous["publication_id"]
        fields = (product_key, expected_observation_id, payload["identity_sha256"],
                  expected_previous_identity, timestamp(published_at), canonical_json(payload))
        publication_id = digest(fields)
        store.db.execute("INSERT INTO publications (publication_id,product_key,observation_id,identity_sha256,previous_identity_sha256,published_at,payload_json) "
                         "VALUES (?,?,?,?,?,?,?)", (publication_id, *fields))
    return publication_id
