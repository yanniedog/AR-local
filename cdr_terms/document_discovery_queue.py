"""Per-ingest discovery obligations sharing the existing acquisition queue.

No network, scheduler activation or publication occurs here. An obligation with
no official seed stays explicit instead of inventing a lender URL from its name.
"""
import json

from .identity import canonical_json, digest, timestamp, utc_now
from .product_documents import discovery_plan, describe_reference


def register_discovery(store, observation_id, record, *, now):
    observation = store.db.execute("SELECT * FROM observations WHERE observation_id=?", (observation_id,)).fetchone()
    if observation is None:
        raise ValueError("Document discovery requires a retained product observation")
    plan = discovery_plan(record, provider=observation["provider"])
    plan_json = canonical_json(plan)
    with store.db:
        store.db.execute("INSERT OR IGNORE INTO product_document_discovery VALUES (?,?,?,?,?)",
                         (observation_id, plan["policy"], digest(plan), plan_json, timestamp(now)))
        existing = store.db.execute("SELECT plan_sha256 FROM product_document_discovery WHERE observation_id=? AND policy=?",
                                    (observation_id, plan["policy"])).fetchone()
        if existing[0] != digest(plan):
            raise ValueError("Discovery obligation source changed")
        for seed in plan["seeds"]:
            doc_id = store.register_document(seed["url"])
            context = canonical_json(seed)
            app_id = digest([observation_id, doc_id, seed["sourcePath"], context])
            store.db.execute("INSERT OR IGNORE INTO applicability VALUES (?,?,?,?,?,?)",
                             (app_id, observation_id, doc_id, seed["sourcePath"], "discovery_navigation", context))
    return {"status": plan["status"], "plan_sha256": digest(plan), "seeds": len(plan["seeds"])}


def reconcile_capture_discovery(store, receipt):
    """Reconcile a pre-upgrade complete capture without rewriting its receipt.

    Retained bodies are authoritative; no source files, timestamps or completed
    document checks are replaced. The existing enqueue is idempotent per ingest.
    """
    from .acquisitions_queue import AcquisitionQueue
    from .product_documents import POLICY
    if len(receipt["sources"]) > 20000:
        raise ValueError("Discovery reconciliation product budget exceeded")
    count = 0
    observed = utc_now()
    for source in receipt["sources"]:
        existing = store.db.execute("SELECT 1 FROM product_document_discovery WHERE observation_id=? AND policy=?",
                                    (source["observation_id"], POLICY)).fetchone()
        if existing:
            continue
        body = store.read_blob(source["sha256"])
        if len(body) > 16 * 1024**2:
            raise ValueError("Discovery reconciliation source byte budget exceeded")
        register_discovery(store, source["observation_id"], json.loads(body), now=observed)
        AcquisitionQueue(store).enqueue(source["observation_id"], ingest_id=receipt["generation_id"], now=observed)
        count += 1
    return count


def discovery_inventory(store, product_key):
    """Return current source-bound acquired candidates, not legal conclusions.

    Declared roots plus graph children keep the source path/edge provenance.
    Only lease-accepted current graph checks can contribute child documents.
    """
    from .graph import DocumentGraph
    from .observation_checks import current_observation, selected_check
    observation = current_observation(store, product_key)
    raw = json.loads(store.read_blob(observation["source_sha256"]))
    descriptors = []
    for row in store.db.execute("SELECT a.*,d.source_url FROM applicability a JOIN documents d USING(document_id) "
                                "WHERE observation_id=? AND relation!='cdr_source' ORDER BY applicability_id", (observation["observation_id"],)):
        check = selected_check(store, observation, row["document_id"])
        descriptor = describe_reference({"url": row["source_url"], "sourcePath": row["source_path"],
                                         "relation": row["relation"]}, raw, product_key=product_key)
        descriptors.append(_checked(store, descriptor, check))
    roots = store.db.execute("SELECT DISTINCT r.root_id FROM document_graph_roots r JOIN document_graph_scopes s USING(root_id) "
                             "JOIN applicability a USING(applicability_id) WHERE a.observation_id=? ORDER BY r.root_id", (observation["observation_id"],))
    graph = DocumentGraph(store)
    for root in roots:
        inventory = graph.inventory(root[0])
        for node in inventory["nodes"]:
            if node["depth"] == 0 or node["source_reason"] is not None:
                continue
            edges = [edge for edge in inventory["edges"] if edge.get("child_node_id") == node["node_id"]]
            reference = {"url": node["source_url"], "relation": "supporting", "sourcePath": "/discovery/graph/" + node["node_id"]}
            descriptor = describe_reference(reference, raw, product_key=product_key)
            descriptor["discoveryEdges"] = [edge["edge_id"] for edge in edges]
            descriptors.append(_checked(store, descriptor, node["check"]))
    return {"productKey": product_key, "observationId": observation["observation_id"], "documents": descriptors,
            "legalCompleteness": "unknown"}


def _checked(store, descriptor, check):
    if check is None:
        return {**descriptor, "verification": "pending"}
    if check["status"] not in {"fetched", "unchanged"}:
        return {**descriptor, "verification": check["status"], "checkedAt": check["checked_at"]}
    version = store.db.execute("SELECT * FROM document_versions WHERE document_version_id=?", (check["document_version_id"],)).fetchone()
    verify = getattr(store, 'verify_blob', store.read_blob)
    verify(version["content_sha256"])
    metadata = json.loads(check["metadata_json"])
    # Successful retrieval proves byte availability, not product applicability.
    return {**descriptor, "verification": "captured", "checkedAt": check["checked_at"],
            "finalUrl": metadata.get("final_url"), "contentSha256": version["content_sha256"],
            "mediaType": version["media_type"], "documentVersionId": version["document_version_id"]}


def publication_document_inventory(evidence_root, generation_id, product_keys, *, expected_contract_digest=None):
    from .document_publication import publication_document_inventory as read_inventory
    return read_inventory(evidence_root, generation_id, product_keys, expected_contract_digest=expected_contract_digest)
