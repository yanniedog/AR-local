"""Bounded candidate link traversal, never a legal applicability/completeness proof.

One graph roots in one acquired CDR-referenced URL and all exact raw source
pointers for that request. Nodes dedupe fetch identities; edges preserve every
anchor occurrence. The acquisition queue supplies leases and restart recovery.
"""
from __future__ import annotations

import ipaddress
import json
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from typing import Any, Mapping
from urllib.parse import urlsplit

from .discovery import document_url
from .extraction import extract_version
from .identity import canonical_json, digest, require_sha, timestamp, utc_now
from .store import EvidenceStore


@dataclass(frozen=True)
class GraphPolicy:
    max_depth: int = 3
    max_nodes: int = 32
    max_links: int = 128
    # Exact hostname -> immutable review evidence hash. No subdomain wildcards.
    reviewed_hosts: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for value, low, high in ((self.max_depth, 0, 8), (self.max_nodes, 1, 128), (self.max_links, 1, 256)):
            if type(value) is not int or not low <= value <= high:
                raise ValueError("Invalid bounded graph policy")
        for host, evidence in self.reviewed_hosts.items():
            if (not isinstance(host, str) or not host or host != host.lower() or "/" in host or "*" in host
                    or document_url("https://" + host) != "https://" + host + "/"
                    or urlsplit("https://" + host).hostname != host):
                raise ValueError("Reviewed graph grants require exact canonical hosts")
            require_sha(evidence)


def current_observations(store: EvidenceStore, request_id: str) -> list[str]:
    return [row[0] for row in store.db.execute(
        "SELECT b.observation_id FROM acquisition_bindings b JOIN observations o USING(observation_id) "
        "JOIN ingest_captures captured ON captured.ingest_id=o.ingest_id "
        "WHERE b.request_id=? AND NOT EXISTS (SELECT 1 FROM observations newer "
        "JOIN ingest_captures newer_capture ON newer_capture.ingest_id=newer.ingest_id WHERE newer.product_key=o.product_key "
        "AND (newer.observed_at>o.observed_at OR (newer.observed_at=o.observed_at AND newer.observation_id!=o.observation_id))) "
        "ORDER BY b.observation_id", (request_id,))]


class DocumentGraph:
    def __init__(self, store: EvidenceStore):
        self.store = store

    def seed(self, request: Mapping[str, Any], check: Mapping[str, Any], *, policy: GraphPolicy | None = None) -> str | None:
        """Today's fetch never becomes a historical capture or effective date."""
        self._validate_seed(request, check)
        if request["priority"] == 2 or check["status"] not in {"fetched", "unchanged"}:
            return None
        observations = current_observations(self.store, request["request_id"])
        if not observations:
            return None  # Graph-only requests inherit their existing pinned roots.
        chosen = policy or GraphPolicy()
        scopes = [dict(row) for row in self.store.db.execute(
            "SELECT a.* FROM applicability a JOIN acquisition_bindings b USING(observation_id) "
            "WHERE b.request_id=? AND a.document_id=? AND a.relation!='cdr_source' ORDER BY a.applicability_id",
            (request["request_id"], request["document_id"])) if row["observation_id"] in observations]
        if not scopes:
            return None
        grants = self._grants(observations, chosen)
        policy_json = canonical_json({**asdict(chosen), "host_grants": grants, "scope": "current_capture_candidate_only"})
        root = digest([request["request_id"], check["check_id"], policy_json])
        with self.store.db:
            self.store.db.execute("INSERT OR IGNORE INTO document_graph_roots VALUES (?,?,?,?,?)",
                                  (root, request["request_id"], check["check_id"], policy_json, utc_now()))
            self.store.db.executemany("INSERT OR IGNORE INTO document_graph_scopes VALUES (?,?)",
                                      [(root, row["applicability_id"]) for row in scopes])
            self.store.db.execute("INSERT OR IGNORE INTO document_graph_nodes VALUES (?,?,?,?,?,0)",
                                  (digest([root, request["document_id"]]), root, request["document_id"], None, request["request_id"]))
        return root

    def _validate_seed(self, request: Mapping[str, Any], check: Mapping[str, Any]) -> None:
        stored = self.store.db.execute("SELECT * FROM acquisition_requests WHERE request_id=?", (request["request_id"],)).fetchone()
        observed = self.store.db.execute("SELECT * FROM acquisition_checks WHERE check_id=?", (check["check_id"],)).fetchone()
        request_keys = ("request_id", "document_id", "ingest_id", "priority")
        check_keys = ("check_id", "document_id", "document_version_id", "status", "metadata_json")
        if (not stored or not observed or stored["document_id"] != observed["document_id"]
                or digest([request.get(key) for key in request_keys]) != digest([stored[key] for key in request_keys])
                or digest([check.get(key) for key in check_keys]) != digest([observed[key] for key in check_keys])):
            raise ValueError("Graph root requires exact retained request and acquisition identities")

    def _grants(self, observations: list[str], policy: GraphPolicy) -> dict[str, list[dict[str, str]]]:
        grants: dict[str, list[dict[str, str]]] = {}
        for observation in observations:
            for row in self.store.db.execute("SELECT a.applicability_id,d.source_url FROM applicability a "
                                               "JOIN documents d USING(document_id) WHERE a.observation_id=? AND a.relation!='cdr_source'",
                                               (observation,)):
                host = urlsplit(row["source_url"]).hostname
                grants.setdefault(host, []).append({"raw_applicability_id": row["applicability_id"]})
        for host, evidence in policy.reviewed_hosts.items():
            receipt = json.loads(self.store.read_blob(evidence))
            if (not isinstance(receipt, dict) or type(receipt.get("schema_version")) is not int or receipt["schema_version"] != 1
                    or receipt.get("kind") != "official_document_host_grant"
                    or receipt.get("host") != host or receipt.get("decision") != "approved"
                    or not isinstance(receipt.get("reviewer"), str) or not receipt["reviewer"].strip()):
                raise ValueError("Official host grant requires a matching explicit review receipt")
            timestamp(receipt.get("reviewed_at"))
            grants.setdefault(host, []).append({"review_evidence_sha256": evidence})
        return {host: sorted(values, key=canonical_json) for host, values in sorted(grants.items())}

    def _check(self, node: Mapping[str, Any]) -> dict[str, Any] | None:
        # The root binds the exact successful attempt; child nodes bind only their
        # lease-accepted successful capture, never an arbitrary/latest version.
        # Interpretation failure may leave its request in retry_wait/blocked.
        if node["depth"] == 0:
            row = self.store.db.execute("SELECT c.* FROM document_graph_roots r JOIN acquisition_checks c USING(check_id) WHERE r.root_id=?",
                                        (node["root_id"],)).fetchone()
        else:
            row = self.store.db.execute("SELECT c.* FROM acquisition_events e JOIN acquisition_checks c USING(check_id) "
                                        "WHERE e.request_id=? AND e.status IN ('complete','retry_wait','blocked') "
                                        "AND c.status IN ('fetched','unchanged') ORDER BY e.sequence LIMIT 1", (node["request_id"],)).fetchone()
        return dict(row) if row else None

    def _source_reason(self, node: Mapping[str, Any]) -> str | None:
        root = self.store.db.execute("SELECT request_id FROM document_graph_roots WHERE root_id=?", (node["root_id"],)).fetchone()
        current = set(current_observations(self.store, root[0]))
        scopes = self.store.db.execute("SELECT a.observation_id FROM document_graph_scopes s JOIN applicability a USING(applicability_id) WHERE s.root_id=?",
                                       (node["root_id"],)).fetchall()
        if any(row[0] not in current for row in scopes):
            return "source_observation_superseded"
        cursor = node
        while cursor:
            check = self._check(cursor)
            latest = self.store.last_success(cursor["document_id"])
            if check and (not latest or check["document_version_id"] != latest["document_version_id"]
                          or json.loads(check["metadata_json"]).get("final_url") != json.loads(latest["metadata_json"]).get("final_url")):
                return "parent_source_version_or_location_superseded"
            cursor = self.store.db.execute("SELECT * FROM document_graph_nodes WHERE node_id=?", (cursor["parent_node_id"],)).fetchone() if cursor["parent_node_id"] else None
        return None

    def pending(self) -> dict[str, Any] | None:
        row = self.store.db.execute(
            "SELECT n.* FROM document_graph_nodes n WHERE NOT EXISTS (SELECT 1 FROM document_graph_expansions x WHERE x.node_id=n.node_id) "
            "AND EXISTS (SELECT 1 FROM acquisition_events e JOIN acquisition_checks c USING(check_id) "
            "WHERE e.request_id=n.request_id AND e.status IN ('complete','retry_wait','blocked') AND c.status IN ('fetched','unchanged') "
            "AND (n.depth>0 OR e.check_id=(SELECT check_id FROM document_graph_roots WHERE root_id=n.root_id))) "
            "ORDER BY n.depth,n.root_id,n.node_id LIMIT 1").fetchone()
        return dict(row) if row else None

    def request_hosts(self, request_id: str) -> frozenset[str]:
        hosts = set()
        for node in self.store.db.execute("SELECT * FROM document_graph_nodes WHERE request_id=? AND depth>0", (request_id,)):
            if self._source_reason(node) is None:
                row = self.store.db.execute("SELECT policy_json FROM document_graph_roots WHERE root_id=?", (node["root_id"],)).fetchone()
                hosts.update(json.loads(row[0])["host_grants"])
        return frozenset(hosts)

    def inventory(self, root_id: str) -> dict[str, Any]:
        """Read one bounded graph with source scopes and unresolved work intact."""
        root = self.store.db.execute("SELECT * FROM document_graph_roots WHERE root_id=?", (root_id,)).fetchone()
        if not root:
            raise ValueError("Unknown document graph root")
        scopes = [dict(row) for row in self.store.db.execute(
            "SELECT a.*,o.provider,o.product_key,o.observed_at,o.source_sha256 FROM document_graph_scopes s "
            "JOIN applicability a USING(applicability_id) JOIN observations o USING(observation_id) "
            "WHERE s.root_id=? ORDER BY a.applicability_id", (root_id,))]
        nodes = []
        for row in self.store.db.execute("SELECT n.*,d.source_url FROM document_graph_nodes n JOIN documents d USING(document_id) WHERE root_id=? ORDER BY depth,node_id", (root_id,)):
            check = self._check(row)
            expansion = self.store.db.execute("SELECT * FROM document_graph_expansions WHERE node_id=?", (row["node_id"],)).fetchone()
            event = self.store.db.execute("SELECT status,error_code FROM acquisition_events WHERE request_id=? ORDER BY sequence DESC LIMIT 1", (row["request_id"],)).fetchone()
            nodes.append({**dict(row), "check": check, "source_reason": self._source_reason(row),
                          "expansion": dict(expansion) if expansion else None, "acquisition": dict(event) if event else None})
        edges = [dict(row) for row in self.store.db.execute("SELECT e.* FROM document_graph_edges e JOIN document_graph_nodes n ON n.node_id=e.parent_node_id WHERE n.root_id=? ORDER BY e.edge_id", (root_id,))]
        return {"schema_version": 1, "root": dict(root), "scopes": scopes, "nodes": nodes, "edges": edges,
                "scope": "current_capture_candidate_only", "effective_dates": "unknown", "legal_completeness": "unknown"}

    def advance_one(self) -> dict[str, Any] | None:
        """One bounded retained node per collector cycle, entirely offline.

        Expansion and new requests commit together. An interrupted transaction
        restarts from the same node; extraction blobs are independently idempotent.
        """
        node = self.pending()
        if node is None:
            return None
        check = self._check(node)
        try:
            extraction = extract_version(self.store, check["document_version_id"], check_id=check["check_id"])
        except (OSError, ValueError):
            return self._failed_expansion(node, check, "retained_evidence_unreadable_or_invalid")
        row = self.store.db.execute("SELECT * FROM extractions WHERE extraction_id=?", (extraction,)).fetchone()
        coverage = json.loads(row["coverage_json"])
        with self.store.db:
            self.store.db.execute("BEGIN IMMEDIATE")
            if self.store.db.execute("SELECT 1 FROM document_graph_expansions WHERE node_id=?", (node["node_id"],)).fetchone():
                return None
            policy = json.loads(self.store.db.execute("SELECT policy_json FROM document_graph_roots WHERE root_id=?", (node["root_id"],)).fetchone()[0])
            reason = self._source_reason(node) or self._base_reason(coverage, policy)
            links = coverage.get("candidate_links", [])
            counts: dict[str, int] = {}
            for index, link in enumerate(links):
                disposition = reason or ("frontier_link_limit" if index >= policy["max_links"] else None)
                disposition, child = self._edge(node, link, policy, disposition)
                counts[disposition] = counts.get(disposition, 0) + 1
                self.store.db.execute("INSERT OR IGNORE INTO document_graph_edges VALUES (?,?,?,?,?,?,?)",
                    (digest([node["node_id"], extraction, link]), node["node_id"], check["document_version_id"],
                     extraction, child, canonical_json(link), disposition))
            receipt = {"reason": reason or "candidate_links_accounted_legal_scope_unreviewed", "counts": counts,
                       "links_observed": coverage.get("candidate_links_total", len(links)),
                       "links_omitted": coverage.get("candidate_links_omitted", 0),
                       "omitted_reason": "extractor_link_limit" if coverage.get("candidate_links_omitted") else None,
                       "extraction_status": row["status"], "extraction_reason": coverage.get("reason"),
                       "legal_completeness": "unknown"}
            self.store.db.execute("INSERT INTO document_graph_expansions VALUES (?,?,?,?,?,?)",
                                  (node["node_id"], check["check_id"], extraction, utc_now(), receipt["reason"], canonical_json(receipt)))
        return {"node_id": node["node_id"], **receipt}

    def _failed_expansion(self, node: Mapping[str, Any], check: Mapping[str, Any], reason: str) -> dict[str, Any]:
        receipt = {"node_id": node["node_id"], "reason": reason, "extraction_status": "failed",
                   "links_observed": None, "legal_completeness": "unknown"}
        with self.store.db:
            self.store.db.execute("INSERT OR IGNORE INTO document_graph_expansions VALUES (?,?,NULL,?,?,?)",
                                  (node["node_id"], check["check_id"], utc_now(), reason, canonical_json(receipt)))
        return receipt

    @staticmethod
    def _base_reason(coverage: Mapping[str, Any], policy: Mapping[str, Any]) -> str | None:
        if "candidate_links" not in coverage:
            return "incorporated_reference_extraction_unsupported"
        if not coverage.get("resolution_base_verified"):
            return "unverified_resolution_base"
        if urlsplit(coverage["resolution_base_url"]).hostname not in policy["host_grants"]:
            return "redirect_host_not_authorized"
        if coverage.get("html_base_href_requires_review"):
            return "html_base_href_requires_review"
        return None

    def _edge(self, node: Mapping[str, Any], link: Mapping[str, Any], policy: Mapping[str, Any],
              reason: str | None) -> tuple[str, str | None]:
        reason = reason or reference_reason(link, policy["host_grants"])
        if reason:
            return reason, None
        doc = self.store.register_document(link["url"])
        existing = self.store.db.execute("SELECT * FROM document_graph_nodes WHERE root_id=? AND document_id=?", (node["root_id"], doc)).fetchone()
        if existing:
            cursor = node
            while cursor:
                if cursor["node_id"] == existing["node_id"]:
                    return "cycle_retained", existing["node_id"]
                cursor = self.store.db.execute("SELECT * FROM document_graph_nodes WHERE node_id=?", (cursor["parent_node_id"],)).fetchone() if cursor["parent_node_id"] else None
            return "existing_url_frontier", existing["node_id"]
        if node["depth"] >= policy["max_depth"]:
            return "frontier_depth_limit", None
        count = self.store.db.execute("SELECT COUNT(*) FROM document_graph_nodes WHERE root_id=?", (node["root_id"],)).fetchone()[0]
        if count >= policy["max_nodes"]:
            return "frontier_node_limit", None
        request = self._enqueue(node, doc)
        identity = digest([node["root_id"], doc])
        self.store.db.execute("INSERT INTO document_graph_nodes VALUES (?,?,?,?,?,?)",
                              (identity, node["root_id"], doc, node["node_id"], request, node["depth"] + 1))
        return "candidate_fetch_queued", identity

    def _enqueue(self, node: Mapping[str, Any], document_id: str) -> str:
        from .acquisitions_queue import AcquisitionQueue
        request = self.store.db.execute("SELECT * FROM acquisition_requests WHERE request_id=?", (node["request_id"],)).fetchone()
        identity = digest([request["ingest_id"], document_id])
        self.store.db.execute("INSERT OR IGNORE INTO acquisition_requests VALUES (?,?,?,?,?)",
                              (identity, document_id, request["ingest_id"], utc_now(), request["priority"]))
        if not self.store.db.execute("SELECT 1 FROM acquisition_events WHERE request_id=?", (identity,)).fetchone():
            AcquisitionQueue(self.store)._event(identity, "queued", utc_now())
        return identity


def reference_reason(link: Mapping[str, Any], grants: Mapping[str, Any]) -> str | None:
    url = document_url(link.get("sourceUrl"))
    if url is None or url != link.get("url"):
        return "unsupported_or_unsafe_reference"
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.port not in (None, 443):
        return "unsupported_scheme_or_port"
    try:
        if not ipaddress.ip_address(parsed.hostname).is_global:
            return "non_public_address"
    except ValueError:
        pass  # DNS resolution/rebinding checks belong to the guarded fetcher.
    if parsed.hostname not in grants:
        return "host_not_authorized"
    if PurePosixPath(parsed.path.lower()).suffix in {".png", ".jpg", ".jpeg", ".svg", ".gif", ".css", ".js", ".zip", ".exe", ".mp4", ".woff", ".ico"}:
        return "non_document_asset"
    return None
