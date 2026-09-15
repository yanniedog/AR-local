"""Durable interpreter queue. Staged output never equals validated terms."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping

from jsonschema import Draft202012Validator

from .identity import canonical_json, digest, exact_value, timestamp, utc_now
from .historical import build_historical_target, historical_scope, validate_historical_target
from .incorporated import validate_target, output_scope
from .observation_checks import context_document_state
from .parameter_registry import validate_parameter_terms, validate_registry_context
from .store import EvidenceStore, validate_clause_locator

STAGING_SCHEMA = Path(__file__).resolve().parents[1] / "contracts" / "product_terms" / "analysis-staging-v1.schema.json"


def staging_schema(context):
    from .parameter_registry import interpretation_contract,SAVINGS_VERSION
    from .identity import byte_digest
    validate_registry_context(context)
    version=context.get('parameter_registry',{}).get('version');contract=interpretation_contract(version)
    if contract:
        directory='material-fields-v1' if version==SAVINGS_VERSION else 'material-fields-v2'
        raw=(STAGING_SCHEMA.parent/'drafts'/directory/(contract[0]+'.schema.json')).read_bytes()
        if byte_digest(raw)!=contract[1]:raise ValueError('Material staging schema bytes differ')
        return json.loads(raw)
    return json.loads(STAGING_SCHEMA.read_bytes())
_TRANSITIONS = {
    None: {"queued"}, "queued": {"running", "superseded", "blocked"},
    "running": {"staged", "retry_wait", "blocked", "superseded"},
    "retry_wait": {"running", "blocked", "superseded"},
    "blocked": {"queued", "superseded"}, "staged": {"superseded"}, "superseded": set(),
}


class StagingValidationError(ValueError):
    """Deterministic staged-output rejection; retrying transport cannot repair it."""


class TermsQueue:
    def __init__(self, store: EvidenceStore):
        self.store = store

    def enqueue(self, extraction_id: str, context: Mapping[str, Any], *,
                priority: int = 1, now: str | None = None,
                completion_guard: Callable[[], None] | None = None) -> str:
        """Context binds product keys, source snapshots, registry and validator."""
        validate_registry_context(context, new_job=True)
        if priority not in (0, 1, 2):
            raise ValueError("Priorities are 0 changed current, 1 current, 2 historical")
        if not isinstance(context.get("product_keys"), list) or not context["product_keys"]:
            raise ValueError("Analysis context requires explicit product_keys")
        if any(not isinstance(key, str) or not key for key in context["product_keys"]):
            raise ValueError("Every analysis product key must be nonempty text")
        exact_value(context)
        if "historical_target" in context:
            if priority != 2:
                raise ValueError("Historical-only targets cannot become current jobs")
            validate_historical_target(self.store, extraction_id, context)
        if "incorporated_target" in context:
            if priority == 2:
                raise ValueError("Incorporated candidates cannot become historical jobs")
            validate_target(self.store, extraction_id, context)
        context_sha = digest(context)
        identity = digest([extraction_id, context_sha])
        body_sha = self.store.put_blob(canonical_json(context).encode("utf-8"))
        observed = timestamp(now or utc_now())
        with self.store.db:
            if completion_guard:
                # Context blob I/O is outside the transaction. An orphan blob
                # is retained evidence, not authority to admit an analysis job.
                self.store.db.execute("BEGIN IMMEDIATE")
                completion_guard()
            self._insert_job(identity, extraction_id, context_sha, body_sha, priority, observed)
            if completion_guard:
                # Wall-clock lease expiry can occur while SQLite is writing.
                # Refusal rolls back all job/event/priority writes together.
                completion_guard()
        return identity

    def _insert_job(self, identity, extraction_id, context_sha, body_sha, priority, observed):
        self.store.db.execute("INSERT OR IGNORE INTO analysis_jobs VALUES (?,?,?,?,?,?)",
                              (identity, extraction_id, context_sha, body_sha, priority, observed))
        if not self.store.db.execute("SELECT 1 FROM job_events WHERE job_id=?", (identity,)).fetchone():
            self._event(identity, "queued", observed, None, None, None)
        self._prioritize(identity, priority, observed)

    def enqueue_in_transaction(self, extraction_id, context, *, priority, completion_guard):
        """Join an exact guarded graph transaction without committing its owner."""
        validate_registry_context(context, new_job=True)
        if not self.store.db.in_transaction or not callable(completion_guard) or priority not in (0, 1):
            raise ValueError("Incorporated enqueue requires a live guarded current transaction")
        completion_guard()
        validate_target(self.store, extraction_id, context)
        exact_value(context)
        context_sha = digest(context)
        identity = digest([extraction_id, context_sha])
        body_sha = self.store.put_blob(canonical_json(context).encode('utf-8'))
        completion_guard()
        self._insert_job(identity, extraction_id, context_sha, body_sha, priority, timestamp(utc_now()))
        completion_guard()
        return identity

    def enqueue_historical(self, extraction_id: str, observation_ids: list[str], *,
                           registry_context: Mapping[str, Any], now: str | None = None) -> str:
        target = build_historical_target(self.store, extraction_id, observation_ids)
        products = {row["product_key"]: row["source_sha256"] for row in target["observations"]}
        context = {**registry_context, "product_keys": sorted(products),
                   "source_product_sha256": products, "historical_target": target}
        return self.enqueue(extraction_id, context, priority=2, now=now)

    def _prioritize(self, job_id: str, priority: int, observed: str) -> None:
        previous = self.store.db.execute("SELECT MIN(priority) FROM job_priorities WHERE job_id=?", (job_id,)).fetchone()[0]
        if previous is None or priority < previous:
            event_id = digest([job_id, priority, observed])
            self.store.db.execute("INSERT OR IGNORE INTO job_priorities VALUES (?,?,?,?)", (event_id, job_id, priority, observed))

    def next_due(self, now: str | None = None) -> dict[str, Any] | None:
        observed = timestamp(now or utc_now())
        rows = self.store.db.execute(
            "SELECT j.*, (SELECT MIN(priority) FROM job_priorities WHERE job_id=j.job_id) AS effective_priority, "
            "x.document_version_id, x.text_sha256, x.extractor_version, e.status, e.retry_after "
            "FROM analysis_jobs j JOIN extractions x USING(extraction_id) JOIN job_events e ON "
            "e.sequence=(SELECT MAX(sequence) FROM job_events WHERE job_id=j.job_id) "
            "WHERE e.status='queued' OR (e.status='retry_wait' AND e.retry_after<=?) "
            "ORDER BY effective_priority, j.created_at, j.job_id", (observed,))
        for row in rows:
            # Capture/acquisition writes precede their acceptance markers. Keep
            # those jobs pending and allow unrelated admitted work to proceed.
            try:
                if self._source_state(row["job_id"], check_blobs=False) == "pending":
                    continue
            except (ValueError, OSError):
                pass  # claim() records the existing durable integrity failure.
            result = dict(row)
            result["priority"] = result.pop("effective_priority")
            return result
        return None

    def event(self, job_id: str, status: str, now: str | None = None, *,
              retry_after: str | None = None, error_code: str | None = None,
              result_sha256: str | None = None, lease_id: str | None = None) -> str:
        observed = timestamp(now or utc_now())
        retry = timestamp(retry_after) if retry_after else None
        if retry is not None and retry <= observed:
            raise ValueError("Retry deadline must be after this event")
        if status == "running":
            raise ValueError("Use atomic claim() to acquire a running lease")
        if status == "staged":
            if not result_sha256:
                raise ValueError("Staged completion requires retained validated-format output")
            self.validate_staging(job_id, json.loads(self.store.read_blob(result_sha256)))
        with self.store.db:
            self.store.db.execute("BEGIN IMMEDIATE")
            previous = self.store.db.execute("SELECT * FROM job_events WHERE job_id=? ORDER BY sequence DESC LIMIT 1",
                                             (job_id,)).fetchone()
            if previous and previous["status"] == "running":
                self._require_lease(previous, lease_id, observed)
            elif lease_id is not None:
                raise ValueError("Analysis lease is no longer running")
            if status == "staged" and not self._source_current(job_id):
                raise ValueError("Document changed before staged result was committed")
            return self._event(job_id, status, observed, retry, error_code, result_sha256, lease_id)

    def _event(self, job_id: str, status: str, observed: str, retry: str | None,
               error: str | None, result: str | None, lease_id: str | None = None,
               lease_expires_at: str | None = None) -> str:
        if not self.store.db.in_transaction:
            self.store.db.execute("BEGIN IMMEDIATE")
        values = (job_id, status, observed, retry, error, result, lease_id, lease_expires_at)
        identity = digest(values)
        if self.store.db.execute("SELECT 1 FROM job_events WHERE event_id=?", (identity,)).fetchone():
            return identity
        previous = self.store.db.execute("SELECT status FROM job_events WHERE job_id=? ORDER BY sequence DESC LIMIT 1",
                                         (job_id,)).fetchone()
        current = previous[0] if previous else None
        if status not in _TRANSITIONS[current]:
            raise ValueError(f"Invalid analysis job transition: {current} -> {status}")
        self.store.db.execute("INSERT INTO job_events (event_id,job_id,status,observed_at,retry_after,error_code,result_sha256,lease_id,lease_expires_at) "
                              "VALUES (?,?,?,?,?,?,?,?,?)", (identity, *values))
        return identity

    @staticmethod
    def _require_lease(event: Mapping[str, Any], lease_id: str | None, now: str) -> None:
        if not lease_id or lease_id != event["lease_id"] or event["lease_expires_at"] <= now:
            raise ValueError("Analysis lease expired or was replaced; stale output rejected")

    def claim(self, now: str | None = None, *, lease_seconds: int = 900) -> dict[str, Any] | None:
        if not 1 <= lease_seconds <= 3600:
            raise ValueError("Analysis lease must be between one second and one hour")
        observed = timestamp(now or utc_now())
        expiry = timestamp((datetime.fromisoformat(observed.replace("Z", "+00:00"))
                            + timedelta(seconds=lease_seconds)).isoformat())
        with self.store.db:
            self.store.db.execute("BEGIN IMMEDIATE")
            expired = self.store.db.execute(
                "SELECT e.* FROM job_events e WHERE sequence=(SELECT MAX(sequence) FROM job_events WHERE job_id=e.job_id) "
                "AND status='running' AND lease_expires_at<=?", (observed,)).fetchall()
            for row in expired:
                self._event(row["job_id"], "retry_wait", observed, observed, "worker_lease_expired", None)
            job = self.next_due(observed)
            while job:
                try:
                    current = self._source_current(job["job_id"])
                except (ValueError, OSError):
                    self._event(job["job_id"], "blocked", observed, None, "source_integrity_invalid", None)
                    job = self.next_due(observed)
                    continue
                if not current:
                    self._event(job["job_id"], "superseded", observed, None, "source_version_changed", None)
                    job = self.next_due(observed)
                    continue
                lease_id = secrets.token_hex(32)
                self._event(job["job_id"], "running", observed, None, None, None, lease_id, expiry)
                return {**job, "status": "running", "lease_id": lease_id, "lease_expires_at": expiry}
        return None

    def _source_current(self, job_id: str) -> bool:
        return self._source_state(job_id) == "current"

    def _source_state(self, job_id: str, *, check_blobs: bool = True) -> str:
        row = self.store.db.execute("SELECT j.context_sha256,j.context_blob_sha256,x.document_version_id,v.document_id FROM analysis_jobs j "
                                    "JOIN extractions x USING(extraction_id) JOIN document_versions v USING(document_version_id) "
                                    "WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return "superseded"
        # Readiness scans only small contexts; claim/admission still verify every
        # source/extraction blob before any work or accepted state transition.
        context = self.validate_input(job_id) if check_blobs else json.loads(self.store.read_blob(row["context_blob_sha256"]))
        if digest(context) != row["context_sha256"]:
            raise ValueError("Analysis context integrity mismatch")
        if "historical_target" in context:
            return "current"  # Pinned immutable evidence, with historical-only output.
        if "incorporated_target" in context:
            if not check_blobs:
                validate_target(self.store, context['incorporated_target']['extraction_id'], context, check_blobs=False)
            return "current"  # Current ancestry, but legal applicability remains unreviewed.
        return context_document_state(self.store, row["document_id"], row["document_version_id"], context)

    def validate_input(self, job_id: str) -> dict[str, Any]:
        job = self.store.db.execute("SELECT j.*,x.text_sha256,v.content_sha256 FROM analysis_jobs j "
                                    "JOIN extractions x USING(extraction_id) JOIN document_versions v USING(document_version_id) "
                                    "WHERE job_id=?", (job_id,)).fetchone()
        if not job:
            raise ValueError("Analysis job has no retained source input")
        context = json.loads(self.store.read_blob(job["context_blob_sha256"]))
        if digest(context) != job["context_sha256"]:
            raise ValueError("Analysis context integrity mismatch")
        validate_registry_context(context)
        self.store.read_blob(job["text_sha256"])
        self.store.read_blob(job["content_sha256"])
        if "historical_target" in context:
            if job["priority"] != 2:
                raise ValueError("Historical-only target was assigned current priority")
            validate_historical_target(self.store, job["extraction_id"], context)
        if "incorporated_target" in context:
            if job['priority'] == 2:
                raise ValueError('Incorporated candidate was assigned historical priority')
            validate_target(self.store, job['extraction_id'], context)
        return context

    def validate_staging(self, job_id: str, output: Mapping[str, Any]) -> None:
        try:
            self._validate_staging(job_id, output)
        except ValueError as error:
            raise StagingValidationError(str(error)) from error

    def _validate_staging(self, job_id: str, output: Mapping[str, Any]) -> None:
        context = self.validate_input(job_id)
        schema = staging_schema(context)
        if context.get('parameter_registry',{}).get('version')=='terms-parameters-v3':
            from .executable_contract import _bounded
            _bounded(output,4*1024*1024)
        Draft202012Validator(schema).validate(output)
        exact_value(output)
        job = self.store.db.execute("SELECT j.*,x.text_sha256,x.coverage_json FROM analysis_jobs j "
                                    "JOIN extractions x USING(extraction_id) WHERE job_id=?", (job_id,)).fetchone()
        if not job or output["extraction_id"] != job["extraction_id"] or output["context_sha256"] != job["context_sha256"]:
            raise ValueError("Staged output is bound to a different input generation")
        text = self.store.read_blob(job["text_sha256"]).decode("utf-8")
        validate_parameter_terms(context, output["terms"])
        if "historical_target" in context:
            if output.get("historical_scope") != historical_scope(context["historical_target"]):
                raise ValueError("Historical output must preserve its historical-only target scope")
        elif "historical_scope" in output:
            raise ValueError("Current output cannot claim a historical target scope")
        if 'incorporated_target' in context:
            if digest(output.get('incorporated_scope')) != digest(output_scope(context['incorporated_target'])):
                raise ValueError('Incorporated output must preserve candidate-only unreviewed applicability')
        elif 'incorporated_scope' in output:
            raise ValueError('Direct output cannot claim incorporated candidate scope')
        coverage = json.loads(job['coverage_json']) if any(clause['page'] is not None for clause in output['clauses']) else {}
        for clause in output["clauses"]:
            validate_clause_locator(text, coverage, start=clause['start'], end=clause['end'],
                                    page=clause['page'], section=clause['section'])
        for term in output["terms"]:
            if term["product_key"] not in context["product_keys"]:
                raise ValueError("Staged term escaped the input product applicability")
            if any(index >= len(output["clauses"]) for index in term["clause_indexes"]):
                raise ValueError("Staged term cites an absent source clause")

    def save_staging(self, job_id: str, output: Mapping[str, Any], *, lease_id: str,
                     now: str | None = None) -> str:
        self.validate_staging(job_id, output)
        if not self._source_current(job_id):
            self.event(job_id, "superseded", now, error_code="source_version_changed", lease_id=lease_id)
            raise ValueError("Document changed while interpretation was running")
        identity = self.store.put_blob(canonical_json(output).encode("utf-8"))
        self.event(job_id, "staged", now, result_sha256=identity, lease_id=lease_id)
        return identity
