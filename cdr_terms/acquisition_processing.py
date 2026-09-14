"""Leased, bounded parser work, independent of successful HTTP capture."""
from __future__ import annotations

import json
import secrets
from typing import Any

from .identity import canonical_json, digest, timestamp, utc_now
from .store import EvidenceStore

SCHEDULE_MAINTENANCE = 64
SCHEDULE_DUE_SQL = (
    "SELECT p.*,s.status,s.event_id schedule_event_id,s.priority schedule_priority,"
    "s.due_at schedule_due_at,s.created_at schedule_created_at,s.evidence_json schedule_evidence_json "
    "FROM acquisition_processing_schedule s INDEXED BY acquisition_processing_schedule_due "
    "JOIN acquisition_processing p USING(processing_id) "
    "WHERE s.status IN ('queued','retry_wait') AND s.priority=? AND s.due_at<=? "
    "ORDER BY s.due_at,s.created_at,s.processing_id LIMIT 1")


class ProcessingGuardFailure(ValueError):
    """No parser disposition can replace rejected source/lease admission."""


class ProcessingQueue:
    def __init__(self, store: EvidenceStore):
        self.store = store

    def enqueue(self, request_id: str, check_id: str, *, now: str, node_id: str | None = None) -> str:
        """Caller commits this with its accepted acquisition/graph transaction."""
        identity = digest([request_id, check_id, node_id])
        self.store.db.execute("INSERT OR IGNORE INTO acquisition_processing VALUES (?,?,?,?,?)",
                              (identity, request_id, check_id, node_id, timestamp(now)))
        if not self.store.db.execute("SELECT 1 FROM acquisition_processing_events WHERE processing_id=?", (identity,)).fetchone():
            self._event(identity, "queued", now, {})
        return identity

    def _event(self, identity: str, status: str, now: str, receipt: dict, *,
               lease_id=None, expiry=None, retry_after=None) -> str:
        values = (identity, status, timestamp(now), lease_id, expiry, retry_after, canonical_json(receipt))
        if not self.store.db.in_transaction:
            self.store.db.execute("BEGIN")
        self.store.db.execute("SAVEPOINT processing_event_schedule")
        try:
            self.store.db.execute("INSERT OR IGNORE INTO acquisition_processing_events "
                                  "(event_id,processing_id,status,observed_at,lease_id,lease_expires_at,retry_after,receipt_json) "
                                  "VALUES (?,?,?,?,?,?,?,?)", (digest(values), *values))
            self._refresh_schedule(identity)
        except Exception:
            self.store.db.execute("ROLLBACK TO processing_event_schedule")
            raise
        finally:
            self.store.db.execute("RELEASE processing_event_schedule")
        return digest(values)

    def schedule_incomplete(self) -> bool:
        row = self.store.db.execute("SELECT complete FROM acquisition_processing_schedule_migration WHERE singleton=1").fetchone()
        if not row:
            raise ValueError("Processing schedule migration state missing")
        return row[0] != 1

    def _refresh_schedule(self, identity: str) -> tuple:
        """Mutable selection hint; only immutable events/source checks authorize."""
        task = self.store.db.execute("SELECT * FROM acquisition_processing WHERE processing_id=?", (identity,)).fetchone()
        event = self.store.db.execute("SELECT * FROM acquisition_processing_events WHERE processing_id=? ORDER BY sequence DESC LIMIT 1", (identity,)).fetchone()
        if not task or not event:
            raise ValueError("Processing schedule requires its authoritative task and event")
        priority, reason, observations = 2, "terminal_or_unverified", []
        if event["status"] in {"queued", "retry_wait"}:
            try:
                request, check, observations = self.validate(dict(task))
                if task["node_id"]:
                    priority, reason = self.analysis_priority(request, check), "accepted_graph_node"
                elif observations:
                    priority, reason = self.analysis_priority(request, check), "accepted_current_capture"
                else:
                    reason = "redundant_graph_only_processing"
            except ValueError as error:
                reason = str(error)
        evidence = canonical_json({"schema_version": 1, "request_id": task["request_id"],
            "check_id": task["check_id"], "observation_ids": observations, "reason": reason})
        due = event["retry_after"] if event["status"] == "retry_wait" else task["created_at"]
        values = (event["event_id"], priority, event["status"], due, task["created_at"], evidence)
        self.store.db.execute("INSERT INTO acquisition_processing_schedule VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(processing_id) DO UPDATE SET event_id=excluded.event_id,priority=excluded.priority,"
            "status=excluded.status,due_at=excluded.due_at,created_at=excluded.created_at,evidence_json=excluded.evidence_json",
            (identity, *values))
        return values

    def _backfill_schedule(self) -> None:
        """Bounded keyset migration; no startup scan or inferred completion."""
        state = self.store.db.execute("SELECT * FROM acquisition_processing_schedule_migration WHERE singleton=1").fetchone()
        if not state:
            raise ValueError("Processing schedule migration state missing")
        if state["complete"]:
            return
        rows = self.store.db.execute("SELECT processing_id FROM acquisition_processing WHERE processing_id>? "
            "ORDER BY processing_id LIMIT ?", (state["after_processing_id"], SCHEDULE_MAINTENANCE)).fetchall()
        for row in rows:
            self._refresh_schedule(row[0])
        self.store.db.execute("UPDATE acquisition_processing_schedule_migration SET after_processing_id=?,complete=? WHERE singleton=1",
            (rows[-1][0] if rows else state["after_processing_id"], int(len(rows) < SCHEDULE_MAINTENANCE)))

    def receipt(self, event_id: str) -> dict:
        row = self.store.db.execute("SELECT e.*,p.request_id,p.check_id,p.node_id FROM acquisition_processing_events e "
                                    "JOIN acquisition_processing p USING(processing_id) WHERE event_id=?", (event_id,)).fetchone()
        if not row or row['status'] not in {'complete', 'retry_wait', 'blocked'}:
            raise ValueError('Processing receipt requires an exact durable disposition')
        return {key: row[key] for key in ('processing_id', 'request_id', 'check_id', 'node_id', 'status', 'lease_id')} | {
            'processing_event_id': event_id, 'outcome': json.loads(row['receipt_json'])}

    def validate_receipt(self, value: dict) -> None:
        """Read back an immutable disposition, not merely its input queue row."""
        if not isinstance(value, dict) or not isinstance(value.get('processing_event_id'), str):
            raise ValueError('Processing receipt requires its durable event identity')
        event_id = value['processing_event_id']
        if canonical_json(value) != canonical_json(self.receipt(event_id)):
            raise ValueError('Processing receipt does not match its durable outcome')
        event = self.store.db.execute('SELECT * FROM acquisition_processing_events WHERE event_id=?', (event_id,)).fetchone()
        if event['lease_id']:
            lease = self.store.db.execute("SELECT * FROM acquisition_processing_events WHERE processing_id=? AND lease_id=? "
                "AND status='running' AND sequence<? ORDER BY sequence DESC LIMIT 1",
                (event['processing_id'], event['lease_id'], event['sequence'])).fetchone()
            if (not lease or event['observed_at'] < lease['observed_at']
                    or (event['status'] == 'complete' and event['observed_at'] >= lease['lease_expires_at'])):
                raise ValueError('Processing outcome does not bind its accepted lease')
        elif event['status'] != 'blocked':
            raise ValueError('Processing completion requires an accepted lease')
        check = self._receipt_capture(value)
        outcome = value['outcome']
        if event['status'] != 'complete':
            if 'analysis_job_id' in outcome or 'graph' in outcome:
                raise ValueError('Failed processing cannot claim completed outputs')
            return
        if set(outcome) - {'analysis_job_id', 'graph', 'legal_completeness'} or outcome.get('legal_completeness') != 'unknown':
            raise ValueError('Unrecognized processing completion output')
        if 'analysis_job_id' in outcome:
            self._receipt_job(value, check)
        if 'graph' in outcome:
            self._receipt_graph(value)

    def _receipt_capture(self, value: dict):
        row = self.store.db.execute(
            "SELECT c.*,r.priority FROM acquisition_checks c JOIN acquisition_requests r ON r.document_id=c.document_id "
            "JOIN acquisition_events e ON e.request_id=r.request_id AND e.check_id=c.check_id "
            "JOIN acquisition_events lease ON lease.request_id=r.request_id AND lease.lease_id=e.lease_id "
            "WHERE r.request_id=? AND c.check_id=? AND c.status IN ('fetched','unchanged') "
            "AND e.status IN ('complete','retry_wait','blocked') AND lease.status='running' AND lease.sequence<e.sequence "
            "AND c.checked_at>=lease.observed_at AND c.checked_at<=e.observed_at AND e.observed_at<lease.lease_expires_at",
            (value['request_id'], value['check_id'])).fetchone()
        if not row or (value['status'] == 'complete' and row['priority'] == 2):
            raise ValueError('Processing receipt does not bind an accepted current capture')
        return row

    def _receipt_job(self, value: dict, check) -> None:
        job = self.store.db.execute('SELECT j.*,x.document_version_id FROM analysis_jobs j JOIN extractions x USING(extraction_id) '
                                    'WHERE job_id=?', (value['outcome']['analysis_job_id'],)).fetchone()
        if (not job or job['priority'] == 2
                or job['document_version_id'] != check['document_version_id']):
            raise ValueError('Processing job does not bind the captured document extraction')
        context = json.loads(self.store.read_blob(job['context_blob_sha256']))
        sources = context.get('source_product_sha256')
        if (digest(context) != job['context_sha256'] or digest([job['extraction_id'], job['context_sha256']]) != job['job_id']
                or 'historical_target' in context or not isinstance(sources, dict) or not sources
                or context.get('product_keys') != sorted(sources)):
            raise ValueError('Processing job does not bind its exact source context')
        if value['node_id'] is not None:
            from .incorporated import validate_target
            target = validate_target(self.store, job['extraction_id'], context, require_current=False)
            if target['node_id'] != value['node_id'] or 'graph' not in value['outcome']:
                raise ValueError('Incorporated job does not bind this exact graph completion')
            return
        if 'incorporated_target' in context:
            raise ValueError('Direct processing cannot claim an incorporated target')
        bindings = {(row[0], row[1]) for row in self.store.db.execute(
            'SELECT o.product_key,o.source_sha256 FROM observations o JOIN acquisition_bindings b USING(observation_id) '
            'JOIN ingest_captures c USING(ingest_id) WHERE b.request_id=?', (value['request_id'],))}
        if any((key, source) not in bindings for key, source in sources.items()):
            raise ValueError('Processing job source escaped the accepted request scope')

    def _receipt_graph(self, value: dict) -> None:
        graph = value['outcome']['graph']
        row = self.store.db.execute('SELECT x.* FROM document_graph_expansions x JOIN document_graph_nodes n USING(node_id) '
            'WHERE node_id=? AND n.request_id=?', (value['node_id'], value['request_id'])).fetchone()
        if (not row or row['check_id'] != value['check_id']
                or canonical_json(graph) != canonical_json({'node_id': value['node_id'], **json.loads(row['receipt_json'])})):
            raise ValueError('Processing graph does not bind its exact durable expansion')

    def _graph_candidates(self, limit: int = 64):
        return self.store.db.execute(
            "SELECT n.node_id FROM document_graph_nodes n WHERE NOT EXISTS "
            "(SELECT 1 FROM document_graph_expansions x WHERE x.node_id=n.node_id) AND NOT EXISTS "
            "(SELECT 1 FROM acquisition_processing p WHERE p.node_id=n.node_id) AND EXISTS "
            "(SELECT 1 FROM acquisition_events e JOIN acquisition_checks c USING(check_id) "
            "WHERE e.request_id=n.request_id AND e.status IN ('complete','retry_wait','blocked') "
            "AND c.status IN ('fetched','unchanged') AND (n.depth>0 OR e.check_id="
            "(SELECT check_id FROM document_graph_roots WHERE root_id=n.root_id))) "
            "ORDER BY n.depth,n.root_id,n.node_id LIMIT ?", (limit,)).fetchall()

    def due(self, now: str | None = None) -> dict | None:
        observed = timestamp(now or utc_now())
        # Each priority is an indexed due-time range: terminal history and
        # future high-priority retries cannot obscure ready lower-priority work.
        for priority in (0, 1, 2):
            row = self.store.db.execute(SCHEDULE_DUE_SQL, (priority, observed)).fetchone()
            if row:
                return dict(row)
        return None

    def has_work(self, now: str | None = None) -> bool:
        observed = timestamp(now or utc_now())
        return bool(self.schedule_incomplete() or self.due(observed) or self._graph_candidates(1) or self.store.db.execute(
            "SELECT 1 FROM acquisition_processing_events e WHERE e.sequence=(SELECT MAX(sequence) "
            "FROM acquisition_processing_events WHERE processing_id=e.processing_id) "
            "AND status='running' AND lease_expires_at<=? LIMIT 1", (observed,)).fetchone())

    def _recover(self, now: str) -> None:
        rows = self.store.db.execute(
            "SELECT * FROM acquisition_processing_events e WHERE e.sequence=(SELECT MAX(sequence) "
            "FROM acquisition_processing_events WHERE processing_id=e.processing_id) "
            "AND status='running' AND lease_expires_at<=? ORDER BY sequence LIMIT 64", (now,)).fetchall()
        for row in rows:
            self._failed(row["processing_id"], now, "processing_lease_expired", row["lease_id"])

    def _failed(self, identity: str, now: str, reason: str, lease_id: str) -> dict:
        from .acquisitions_queue import _after
        attempts = self.store.db.execute("SELECT COUNT(*) FROM acquisition_processing_events "
                                        "WHERE processing_id=? AND status='running'", (identity,)).fetchone()[0]
        exhausted = attempts >= 4
        receipt = {"reason": reason, "attempts": attempts, "exhausted": exhausted,
                   "extraction_completeness": "unknown", "legal_completeness": "unknown"}
        event_id = self._event(identity, "blocked" if exhausted else "retry_wait", now, receipt, lease_id=lease_id,
                              retry_after=None if exhausted else _after(now, min(3600, 300 * 2 ** max(0, attempts - 1))))
        return self.receipt(event_id)

    def validate(self, task: dict, *, expanded: bool = False) -> tuple[dict, dict, list[str]]:
        from .graph import DocumentGraph, current_observations
        from .observation_checks import selected_check
        request = self.store.db.execute("SELECT * FROM acquisition_requests WHERE request_id=?", (task["request_id"],)).fetchone()
        check = self.store.db.execute("SELECT * FROM acquisition_checks WHERE check_id=?", (task["check_id"],)).fetchone()
        accepted = self.store.db.execute(
            "SELECT 1 FROM acquisition_events e JOIN acquisition_events lease ON lease.request_id=e.request_id "
            "AND lease.lease_id=e.lease_id WHERE e.request_id=? AND e.check_id=? "
            "AND e.status IN ('complete','retry_wait','blocked') AND lease.status='running' "
            "AND lease.sequence<e.sequence AND ? >=lease.observed_at AND ?<=e.observed_at "
            "AND e.observed_at<lease.lease_expires_at LIMIT 1",
            (task["request_id"], task["check_id"], check["checked_at"] if check else "", check["checked_at"] if check else "")).fetchone()
        if (not request or not check or not accepted or request["document_id"] != check["document_id"]
                or check["status"] not in {"fetched", "unchanged"} or request["priority"] == 2):
            raise ValueError("accepted_current_capture_required")
        graph = DocumentGraph(self.store)
        observations = current_observations(self.store, request["request_id"])
        if task["node_id"]:
            node = self.store.db.execute("SELECT * FROM document_graph_nodes WHERE node_id=?", (task["node_id"],)).fetchone()
            pinned = graph._check(node) if node else None
            expansion = self.store.db.execute("SELECT check_id FROM document_graph_expansions WHERE node_id=?", (task["node_id"],)).fetchone()
            if (not node or node["request_id"] != task["request_id"] or not pinned or pinned["check_id"] != task["check_id"]
                    or graph._source_reason(node) or (expanded and (not expansion or expansion[0] != task["check_id"]))
                    or (not expanded and graph.pending(task["node_id"]) is None)):
                raise ValueError("graph_processing_source_superseded_or_not_pending")
        elif observations:
            for identity in observations:
                observation = dict(self.store.db.execute("SELECT * FROM observations WHERE observation_id=?", (identity,)).fetchone())
                current = selected_check(self.store, observation, check["document_id"], successful_only=True)
                if not current or current["document_version_id"] != check["document_version_id"]:
                    raise ValueError("processing_document_version_superseded")
        elif not graph.request_hosts(request["request_id"]):
            raise ValueError("processing_source_scope_superseded")
        return dict(request), dict(check), observations

    def claim(self, now: str | None = None, *, lease_seconds: int = 180) -> dict | None:
        from .acquisitions_queue import _after
        from .graph import DocumentGraph
        if not 1 <= lease_seconds <= 180:
            raise ValueError("Processing lease exceeds collector recovery bound")
        observed = timestamp(now or utc_now())
        with self.store.db:
            self.store.db.execute("BEGIN IMMEDIATE")
            self._backfill_schedule()
            self._recover(observed)
            graph = DocumentGraph(self.store)
            for row in self._graph_candidates():
                node = graph.pending(row[0])
                if node:
                    self.enqueue(node["request_id"], graph._check(node)["check_id"], node_id=row[0], now=observed)
            for _ in range(SCHEDULE_MAINTENANCE):
                task = self.due(observed)
                if task is None:
                    return None
                hinted = (task["schedule_event_id"], task["schedule_priority"], task["status"],
                          task["schedule_due_at"], task["schedule_created_at"], task["schedule_evidence_json"])
                if self._refresh_schedule(task["processing_id"]) != hinted:
                    continue  # Changed/tampered hint cannot authorize this claim.
                try:
                    _, _, observations = self.validate(task)
                except ValueError as error:
                    event_id = self._event(task["processing_id"], "blocked", observed, {"reason": str(error), "legal_completeness": "unknown"})
                    return self.receipt(event_id)
                if not task["node_id"] and not observations and graph.request_hosts(task["request_id"]):
                    self._event(task["processing_id"], "blocked", observed,
                        {"reason": "redundant_graph_only_processing", "legal_completeness": "unknown"})
                    continue  # Preserve the old row; process its real node this tick.
                lease, expiry = secrets.token_hex(32), _after(observed, lease_seconds)
                self._event(task["processing_id"], "running", observed, {}, lease_id=lease, expiry=expiry)
                return {**task, "status": "running", "lease_id": lease, "lease_expires_at": expiry}
            return None

    def finish(self, task: dict, receipt: dict, *, error: str | None = None, now: str | None = None) -> dict:
        observed = timestamp(now or utc_now())
        with self.store.db:
            self.store.db.execute("BEGIN IMMEDIATE")
            event = self.store.db.execute("SELECT * FROM acquisition_processing_events WHERE processing_id=? ORDER BY sequence DESC LIMIT 1",
                                          (task["processing_id"],)).fetchone()
            if (not event or event["status"] != "running" or event["lease_id"] != task["lease_id"] or event["lease_expires_at"] <= observed):
                raise ValueError("Stale processing completion rejected")
            try:
                self.validate(task, expanded=bool(task["node_id"]) and not error)
            except ValueError as invalid:
                error = str(invalid)
            if error:
                return self._failed(task["processing_id"], observed, error, task["lease_id"])
            event_id = self._event(task["processing_id"], "complete", observed, receipt, lease_id=task["lease_id"])
        return self.receipt(event_id)

    def _assert_live_lease(self, task: dict) -> None:
        event = self.store.db.execute("SELECT * FROM acquisition_processing_events WHERE processing_id=? ORDER BY sequence DESC LIMIT 1",
                                      (task["processing_id"],)).fetchone()
        if (not event or event["status"] != "running" or event["lease_id"] != task["lease_id"] or event["lease_expires_at"] <= utc_now()):
            raise ProcessingGuardFailure("Stale processing admission rejected")

    def assert_lease(self, task: dict, *, observation_ids: list[str] | None = None,
                     expanded: bool = False) -> None:
        self._assert_live_lease(task)
        try:
            _, _, current = self.validate(task, expanded=expanded)
            if observation_ids is not None and current != observation_ids:
                raise ValueError('processing_observation_scope_superseded')
        except ValueError as error:
            raise ProcessingGuardFailure(str(error)) from error
        self._assert_live_lease(task)  # Source validation can itself cross expiry.

    def assert_expansion(self, task: dict, expected: dict) -> None:
        """Admit only this transaction's exact expansion under its live owner."""
        self.assert_lease(task, expanded=True)
        row = self.store.db.execute('SELECT * FROM document_graph_expansions WHERE node_id=?',
                                    (task['node_id'],)).fetchone()
        if (not row or expected.get('node_id') != task['node_id'] or expected.get('check_id') != task['check_id']
                or canonical_json(dict(row)) != canonical_json(expected)):
            raise ProcessingGuardFailure('processing_graph_expansion_identity_mismatch')
        self._assert_live_lease(task)

    def process_one(self, registry_context: dict) -> dict | None:
        from .acquisitions_queue import enqueue_interpretation
        from .graph import DocumentGraph
        task = self.claim()
        if not task or task["status"] != "running":
            return task
        receipt: dict[str, Any] = {"legal_completeness": "unknown"}
        error = None
        try:
            request, check, observations = self.validate(task)
            if task["node_id"]:
                receipt["graph"] = DocumentGraph(self.store).advance_one(task["node_id"],
                    completion_guard=lambda: self.assert_lease(task),
                    post_write_guard=lambda expansion: self._complete_expansion(task, expansion, request, check, registry_context, receipt))
            else:
                if observations:
                    DocumentGraph(self.store).seed(request, check)
                    receipt["analysis_job_id"] = enqueue_interpretation(self.store, check["document_version_id"], observations,
                        priority=self.analysis_priority(request, check), registry_context=registry_context,
                        completion_guard=lambda: self.assert_lease(task, observation_ids=observations))
        except ProcessingGuardFailure:
            raise
        except (OSError, ValueError, RuntimeError, AssertionError) as exc:
            error = type(exc).__name__ + ":" + str(exc)[:200]
        return self.finish(task, receipt, error=error)

    def _complete_expansion(self, task, expansion, request, check, registry_context, receipt):
        from .incorporated import enqueue_expansion
        guard = lambda: self.assert_expansion(task, expansion)
        guard()
        node = self.store.db.execute('SELECT depth FROM document_graph_nodes WHERE node_id=?', (task['node_id'],)).fetchone()
        if node['depth'] == 0:
            return  # Preserve the original root-expansion guard/caller contract.
        job = enqueue_expansion(self.store, expansion, registry_context,
                                priority=self.analysis_priority(request, check), guard=guard)
        guard()
        if job:
            receipt['analysis_job_id'] = job

    def analysis_priority(self, request: dict, check: dict) -> int:
        # Preserve changed-current priority using earlier accepted checks, not
        # orphan captures. The HTTP request's original priority remains intact.
        previous = self.store.db.execute(
            "SELECT c.document_version_id FROM acquisition_checks c JOIN acquisition_events e USING(check_id) "
            "JOIN acquisition_requests r ON r.request_id=e.request_id AND r.document_id=c.document_id "
            "JOIN ingest_captures accepted_capture ON accepted_capture.ingest_id=r.ingest_id "
            "JOIN acquisition_events lease ON lease.request_id=e.request_id AND lease.lease_id=e.lease_id "
            "WHERE c.document_id=? AND (c.checked_at<? OR (c.checked_at=? AND c.sequence<?)) "
            "AND r.priority!=2 AND c.status IN ('fetched','unchanged') AND e.status IN ('complete','retry_wait','blocked') "
            "AND lease.status='running' AND lease.sequence<e.sequence AND c.checked_at>=lease.observed_at "
            "AND c.checked_at<=e.observed_at AND e.observed_at<lease.lease_expires_at "
            "ORDER BY c.checked_at DESC,c.sequence DESC LIMIT 1",
            (check["document_id"], check["checked_at"], check["checked_at"], check["sequence"])).fetchone()
        return 0 if not previous or previous[0] != check["document_version_id"] else request["priority"]
