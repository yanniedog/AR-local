"""Controller admission of a revision from one immutable accepted analysis result."""
from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from .identity import canonical_json, digest
from .queue import TermsQueue
from .store import EvidenceStore


def _source_clauses(store: EvidenceStore, observation_id: str, clause_ids: Sequence[str]) -> list[dict]:
    sources = []
    for clause_id in clause_ids:
        source = store.db.execute(
            "SELECT c.* FROM clauses c JOIN extractions x USING(extraction_id) "
            "JOIN document_versions v USING(document_version_id) JOIN applicability a USING(document_id) "
            "WHERE c.clause_id=? AND a.observation_id=?", (clause_id, observation_id)).fetchone()
        if not source:
            raise ValueError("Term source has no product applicability evidence")
        sources.append(dict(source))
    return sources


def _accepted_result(store: EvidenceStore, job_id: str) -> dict[str, Any]:
    event = store.db.execute("SELECT * FROM job_events WHERE job_id=? ORDER BY sequence DESC LIMIT 1", (job_id,)).fetchone()
    if not event or event["status"] != "staged" or not event["result_sha256"] or not event["lease_id"]:
        raise ValueError("Term requires an accepted current staged result")
    previous = store.db.execute("SELECT * FROM job_events WHERE job_id=? AND sequence<? ORDER BY sequence DESC LIMIT 1",
                                (job_id, event["sequence"])).fetchone()
    if (not previous or previous["status"] != "running" or previous["lease_id"] != event["lease_id"]
            or previous["lease_expires_at"] <= event["observed_at"]):
        raise ValueError("Term requires a lease-accepted staged result")
    return json.loads(store.read_blob(event["result_sha256"]))


def _clause_ids(output: Mapping[str, Any], term: Mapping[str, Any], text: str) -> list[str]:
    extraction_id = output["extraction_id"]
    identities = []
    for index in term["clause_indexes"]:
        clause = output["clauses"][index]
        if clause["disposition"] != "parameter":
            return []
        locator = {key: clause[key] for key in ("start", "end", "page", "section") if clause[key] is not None}
        identities.append(digest([extraction_id, locator, text[clause["start"]:clause["end"]]]))
    return sorted(identities)


def require_staged_term(store: EvidenceStore, *, observation: Mapping[str, Any], context_sha256: str,
                        parameter_key: str, value: Any, unit: str | None,
                        applicability: Mapping[str, Any], clause_ids: Sequence[str]) -> None:
    """Human and model interpretations both require durable, source-bound staging.

    The caller holds an immediate transaction until revision/source insertion.
    A context can belong to several extraction jobs; the exact clause extraction
    selects one, never an arbitrary first matching context or a historical job.
    """
    sources = _source_clauses(store, observation["observation_id"], clause_ids)
    extraction_ids = {source["extraction_id"] for source in sources}
    if len(extraction_ids) != 1:
        raise ValueError("Term clauses must bind one exact analysis job extraction")
    jobs = store.db.execute("SELECT job_id FROM analysis_jobs WHERE context_sha256=? AND extraction_id=?",
                            (context_sha256, next(iter(extraction_ids)))).fetchall()
    if len(jobs) != 1:
        raise ValueError("Term requires one existing source-bound analysis job")
    queue = TermsQueue(store)
    job_id = jobs[0]["job_id"]
    context = queue.validate_input(job_id)
    if "historical_target" in context:
        raise ValueError("Historical-only staging cannot enter current term revisions")
    if "incorporated_target" in context:
        raise ValueError("Incorporated candidate staging has no reviewed legal applicability")
    products = context.get("source_product_sha256")
    if (context.get("product_keys", []).count(observation["product_key"]) != 1
            or not isinstance(products, dict) or products.get(observation["product_key"]) != observation["source_sha256"]):
        raise ValueError("Analysis context does not bind this exact product source")
    store.read_blob(observation["source_sha256"])
    output = _accepted_result(store, job_id)
    queue.validate_staging(job_id, output)
    if not queue._source_current(job_id):
        raise ValueError("Analysis source document changed before term admission")
    expected = {"parameter_key": parameter_key, "value": value, "unit": unit, **applicability}
    expected_json = canonical_json(expected)
    row = store.db.execute("SELECT text_sha256 FROM extractions WHERE extraction_id=?", (output["extraction_id"],)).fetchone()
    text = store.read_blob(row["text_sha256"]).decode("utf-8")
    matches = [term for term in output["terms"]
               if canonical_json({key: term[key] for key in expected}) == expected_json
               and _clause_ids(output, term, text) == sorted(clause_ids)]
    if len(matches) != 1:
        raise ValueError("Revision must bind one exact staged term and its parameter clauses")
    # The current revision envelope has no fields for these qualifiers. Retain
    # them in staging until a reviewed adapter can preserve their semantics.
    if matches[0]["conditions"] or matches[0]["exceptions"]:
        raise ValueError("Staged term qualifiers cannot be discarded by the revision contract")
    if matches[0]["rule_pattern"] is not None:
        raise ValueError("Staged rule pattern requires an explicit reviewed binding adapter")
