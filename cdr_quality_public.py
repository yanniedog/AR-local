"""Read the exact public selected bundle and reconcile it with source SQLite."""
from __future__ import annotations

import gzip
import io
import json
import tempfile
from pathlib import Path

from app_payload_common import DEFAULT_REPO, DEFAULT_TAG
from app_payload_revisions_github import GitHubRevisionStore, download_manifest_assets, write_once
from app_payload_revisions_state import decode_document, digest, validate_index, validate_manifest
from cdr_product_evidence_acceptance import verified_inventory, receipt
from app_payload_publication_assets import has_evidence
from cdr_quality_accounting import SECTIONS, rate_rows_digest, reconcile_public_core


def audit_public(current: dict, *, repo: str = DEFAULT_REPO, store=None) -> dict:
    backend = store or GitHubRevisionStore(repo)
    index_raw = backend.read(DEFAULT_TAG, "dates-index.json")
    if index_raw is None:
        raise ValueError("public dates-index missing")
    index = decode_document(index_raw)
    validate_index(index, repo=repo)
    head = index.get("revision_heads", {}).get(current["run_date"])
    if index.get("revision_protocol") == 1 and head is None:
        raise ValueError("selected revision missing for current day")
    raw = backend.read_url(head["manifest_url"]) if head else backend.read(DEFAULT_TAG, "manifest.json")
    if raw is None or (head and digest(raw) != head["manifest_sha256"]):
        raise ValueError("selected public manifest missing or hash mismatch")
    manifest = decode_document(raw)
    if manifest.get("run_date") != current["run_date"]:
        raise ValueError("public payload does not match the current observation date")
    with tempfile.TemporaryDirectory(prefix="cdr-public-audit-") as temporary:
        root = Path(temporary)
        write_once(root / 'manifest.json', raw)
        download_manifest_assets(backend, manifest, root)
        if not has_evidence(manifest): validate_manifest(manifest, root)
        assets, optional = verified_inventory(root,manifest,digest(raw))
        if optional is not None:
            revision = manifest.get('payload_revision') or {}
            if (not head or optional['bundle_sha256'] != head['bundle_sha256']
                    or any(revision.get(key) != head.get(key) for key in ('revision','generation_id','bundle_sha256'))
                    or head['manifest_url'] != backend.url(manifest['tag'],'manifest.json')
                    or backend.read(DEFAULT_TAG,'dates-index.json',require_encrypted=True) != index_raw
                    or backend.read_url(head['manifest_url'],require_encrypted=True) != raw):
                raise ValueError('complete optional public audit lacks stable encrypted selected roots')
        if manifest.get("enc"):
            raise ValueError("encrypted public data requires the shipping app audit; no plaintext fallback")
        core_raw = (root / manifest["files"]["core"]["name"]).read_bytes()
        with gzip.GzipFile(fileobj=io.BytesIO(core_raw)) as stream:
            body = stream.read(128 * 1024 * 1024 + 1)
        if len(body) > 128 * 1024 * 1024:
            raise ValueError("decoded core exceeds audit budget")
        core = json.loads(body)
    issues = reconcile_public_core(core, current["accounting"])
    for section in SECTIONS:
        rows = ((core.get("sections") or {}).get(section) or {}).get("rates") or []
        if rate_rows_digest(rows) != current["published_rate_digests"][section]:
            issues.append({"code": "PUBLIC_RATE_CONTENT_MISMATCH", "section": section})
    if head:
        revision = manifest.get("payload_revision") or {}
        if any(revision.get(key) != head.get(key) for key in ("revision", "generation_id", "bundle_sha256")):
            issues.append({"code": "PUBLIC_REVISION_IDENTITY_MISMATCH"})
        observed = manifest.get("source_observation") or {}
        if observed.get("contract_digest") != current["contract_digest"]:
            issues.append({"code": "PUBLIC_OBSERVATION_IDENTITY_MISMATCH"})
    return {"status": "FAIL" if issues else "PASS", "run_date": manifest["run_date"],
            "manifest_sha256": digest(raw), "index_sha256": digest(index_raw), "revision": head,
            "assets_verified": {key: {"sha256": row["sha256"], "bytes": row["bytes"]} for key, row in assets.items()},
            **({'optional_product_evidence': receipt(manifest,digest(raw),assets,scope='public_selected',
                 selected_head_verified=True,public_transport_verified=True)} if optional is not None else {}),
            "issues": issues}
