"""Source-bound staged terms and independent append-only review decisions."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any, Mapping, Sequence

from .identity import canonical_json, digest, exact_value, require_sha, timestamp
from .revision_staging import require_staged_term
from .store import EvidenceStore

APPLICABILITY_FIELDS = {"product_key", "tier", "package", "cohort", "effective_from", "effective_to"}
REVIEW_CHECKS = {"source_alignment", "applicability", "value_units", "conditions_exceptions", "effective_dates"}


def register_rule_set(store: EvidenceStore, contract: Mapping[str, Any], *,
                      validator_version: str, benchmark_sha256: str) -> str:
    """Controller-only registration of reviewed declarative pattern evidence."""
    exact_value(contract)
    store.read_blob(benchmark_sha256)
    if not validator_version or not contract.get("parameter_keys"):
        raise ValueError("Reviewed rule sets require validator version and parameter keys")
    identity = digest([contract, validator_version, benchmark_sha256])
    with store.db:
        store.db.execute("INSERT OR IGNORE INTO rule_sets VALUES (?,?,?,?)",
                         (identity, canonical_json(contract), validator_version, benchmark_sha256))
    return identity


def _applicability(value: Mapping[str, Any], product_key: str) -> None:
    if set(value) != APPLICABILITY_FIELDS or value["product_key"] != product_key:
        raise ValueError("Explicit complete applicability contract is required")
    if any(item is not None and not isinstance(item, str) for item in value.values()):
        raise ValueError("Applicability values must be source-supported text or null")
    endpoints = []
    for key in ("effective_from", "effective_to"):
        if value[key] is not None:
            # Preserve source spelling; compare UTC instants or calendar dates.
            if len(value[key]) == 10:
                endpoints.append(date.fromisoformat(value[key]))
            else:
                endpoints.append(datetime.fromisoformat(timestamp(value[key]).replace("Z", "+00:00")))
    if len(endpoints) == 2:
        if type(endpoints[0]) is not type(endpoints[1]):
            raise ValueError("Mixed effective date precision requires source-supported timezone clarification")
        if endpoints[0] > endpoints[1]:
            raise ValueError("Effective interval is inverted")


def stage_term(store: EvidenceStore, *, observation_id: str, parameter_key: str,
               value: Any, unit: str | None, applicability: Mapping[str, Any],
               clause_ids: Sequence[str], interpreter: str, context_sha256: str,
               observed_at: str, rule_set_id: str | None = None) -> str:
    exact_value(value)
    require_sha(context_sha256)
    if (not re.fullmatch(r"[a-z][a-z0-9_.]*", parameter_key)
            or not isinstance(interpreter, str) or not interpreter.strip()):
        raise ValueError("A canonical parameter key and interpreter identity are required")
    observation = store.db.execute("SELECT * FROM observations WHERE observation_id=?", (observation_id,)).fetchone()
    if not observation or not clause_ids or len(set(clause_ids)) != len(clause_ids):
        raise ValueError("Term requires an observation and distinct source clauses")
    _applicability(applicability, observation["product_key"])
    if rule_set_id:
        rule = store.db.execute("SELECT * FROM rule_sets WHERE rule_set_id=?", (rule_set_id,)).fetchone()
        if not rule or parameter_key not in json.loads(rule["contract_json"])["parameter_keys"]:
            raise ValueError("Parameter has no reviewed executable rule pattern")
    observed = timestamp(observed_at)
    fields = (observation_id, parameter_key, canonical_json(value), unit,
              canonical_json(applicability), rule_set_id, observed, interpreter, context_sha256)
    identity = digest([*fields, sorted(clause_ids)])
    with store.db:
        # Hold the source/job generation through both append-only insertions.
        store.db.execute("BEGIN IMMEDIATE")
        require_staged_term(store, observation=observation, context_sha256=context_sha256,
                            parameter_key=parameter_key, value=value, unit=unit,
                            applicability=applicability, clause_ids=clause_ids)
        store.db.execute("INSERT OR IGNORE INTO term_revisions VALUES (?,?,?,?,?,?,?,?,?,?)", (identity, *fields))
        for clause_id in sorted(clause_ids):
            store.db.execute("INSERT OR IGNORE INTO term_sources VALUES (?,?)", (identity, clause_id))
    return identity


def review_term(store: EvidenceStore, term_revision_id: str, *, status: str,
                reviewer: str, reviewer_kind: str, reviewed_at: str,
                evidence_sha256: str, reason: str) -> str:
    term = store.db.execute("SELECT * FROM term_revisions WHERE term_revision_id=?", (term_revision_id,)).fetchone()
    # Compare normalized identities without rewriting append-only actor history.
    if (not term or not isinstance(reviewer, str) or not reviewer.strip()
            or not isinstance(term["interpreter"], str) or not term["interpreter"].strip()
            or reviewer.strip() == term["interpreter"].strip()):
        raise ValueError("A separate reviewer must assess staged interpretation")
    if reviewer_kind not in {"human", "deterministic"} or status not in {"validated", "rejected"}:
        raise ValueError("A model's second pass is not independent validation")
    evidence = json.loads(store.read_blob(evidence_sha256))
    if evidence.get("term_revision_id") != term_revision_id:
        raise ValueError("Review evidence is bound to a different term")
    if status == "validated":
        if evidence.get("passed") is not True or not REVIEW_CHECKS <= set(evidence.get("checks", [])):
            raise ValueError("Required independent source and applicability checks are missing")
        if reviewer_kind == "deterministic" and not term["rule_set_id"]:
            raise ValueError("Deterministic validation requires a benchmarked rule set")
    values = (term_revision_id, status, reviewer, reviewer_kind, timestamp(reviewed_at), evidence_sha256, reason)
    identity = digest(values)
    with store.db:
        store.db.execute("INSERT OR IGNORE INTO reviews "
                         "(review_id,term_revision_id,status,reviewer,reviewer_kind,reviewed_at,evidence_sha256,reason) "
                         "VALUES (?,?,?,?,?,?,?,?)", (identity, *values))
    return identity


def term_source_versions(store: EvidenceStore, term_id: str) -> set[str]:
    return {row[0] for row in store.db.execute(
        "SELECT DISTINCT x.document_version_id FROM term_sources s JOIN clauses c USING(clause_id) "
        "JOIN extractions x USING(extraction_id) WHERE term_revision_id=?", (term_id,))}


def record_change(store: EvidenceStore, *, product_key: str, before_revision_id: str | None,
                  after_revision_id: str | None, kind: str, observed_at: str,
                  evidence_sha256: str) -> str:
    evidence = json.loads(store.read_blob(evidence_sha256))
    shape = {"added": (False, True), "removed": (True, False),
             "changed": (True, True), "extraction_corrected": (True, True)}
    if shape.get(kind) != (bool(before_revision_id), bool(after_revision_id)):
        raise ValueError("Change kind does not match its before/after revisions")
    if before_revision_id == after_revision_id:
        raise ValueError("A change must identify different revisions")
    revisions = [identity for identity in (before_revision_id, after_revision_id) if identity]
    if not revisions or evidence.get("passed") is not True or evidence.get("kind") != kind:
        raise ValueError("Change requires an independent reviewed disposition")
    if evidence.get("before_revision_id") != before_revision_id or evidence.get("after_revision_id") != after_revision_id:
        raise ValueError("Change evidence refers to another revision pair")
    for identity in revisions:
        term = store.db.execute("SELECT o.product_key,r.status FROM term_revisions t JOIN observations o USING(observation_id) "
                                "JOIN reviews r ON r.sequence=(SELECT MAX(sequence) FROM reviews WHERE term_revision_id=t.term_revision_id) "
                                "WHERE t.term_revision_id=?", (identity,)).fetchone()
        if not term or term["product_key"] != product_key or term["status"] != "validated":
            raise ValueError("Changes require validated revisions belonging to this product")
    if kind == "removed":
        _require_replacement(store, product_key, evidence)
        if evidence["replacement_document_version_id"] in term_source_versions(store, before_revision_id):
            raise ValueError("Unchanged source bytes cannot establish a bank's term removal")
    if before_revision_id and after_revision_id and kind == "changed":
        if term_source_versions(store, before_revision_id) == term_source_versions(store, after_revision_id):
            raise ValueError("Unchanged source bytes require extraction_corrected disposition")
    values = (product_key, before_revision_id, after_revision_id, kind,
              timestamp(observed_at), canonical_json({"evidence_sha256": evidence_sha256}))
    identity = digest(values)
    with store.db:
        store.db.execute("INSERT OR IGNORE INTO term_changes VALUES (?,?,?,?,?,?,?)", (identity, *values))
    return identity


def _require_replacement(store: EvidenceStore, product_key: str, evidence: Mapping[str, Any]) -> None:
    if evidence.get("full_replacement_validated") is not True:
        raise ValueError("Disappearance/fetch failure cannot prove term removal")
    version_id = evidence.get("replacement_document_version_id")
    replacement = store.db.execute(
        "SELECT 1 FROM document_versions v JOIN extractions x USING(document_version_id) "
        "JOIN applicability a USING(document_id) JOIN observations o USING(observation_id) "
        "WHERE v.document_version_id=? AND o.product_key=? AND x.status='complete'", (version_id, product_key)).fetchone()
    if not replacement:
        raise ValueError("Removal needs a retained, completely extracted replacement applicable to the product")
