"""Explicit, bounded evidence inventory/archive commands; never publishes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .acquisition import FetchPolicy, acquire_observation
from .acquisitions_queue import process_next_acquisition
from .extraction import extract_version
from .identity import canonical_json, utc_now
from .reporting import build_product_asset
from .store import EvidenceStore


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--store", type=Path, required=True, help="Dedicated private evidence directory")
    sub = result.add_subparsers(dest="command", required=True)
    inventory = sub.add_parser("inventory", help="Inventory one original CDR product response; no requests")
    inventory.add_argument("--input", type=Path, required=True)
    inventory.add_argument("--provider", required=True)
    inventory.add_argument("--product-key", required=True)
    inventory.add_argument("--ingest-id", required=True)
    inventory.add_argument("--observed-at", required=True, help="Actual source observation time with timezone")
    archive = sub.add_parser("archive", help="Retain existing official document bytes; no requests")
    archive.add_argument("--input", type=Path, required=True)
    archive.add_argument("--document-id", required=True)
    archive.add_argument("--media-type", required=True)
    archive.add_argument("--check-id", required=True)
    acquire = sub.add_parser("fetch", help="Fetch a bounded part of an observation's known document inventory")
    acquire.add_argument("--observation-id", required=True)
    acquire.add_argument("--check-prefix", required=True)
    acquire.add_argument("--max-documents", type=int, default=10)
    acquire.add_argument("--max-total-bytes", type=int, default=64 * 1024 * 1024)
    acquire.add_argument("--max-seconds", type=float, default=300)
    acquire.add_argument("--allowed-host", action="append", default=[])
    extract = sub.add_parser("extract", help="Conservative text extraction of one retained version")
    extract.add_argument("--version-id", required=True)
    sub.add_parser("acquire-next", help="Process one due leased acquisition and queue extraction; no model call")
    historical = sub.add_parser("enqueue-historical", help="Pin one retained extraction for historical-only staging; no requests or model call")
    historical.add_argument("--extraction-id", required=True)
    historical.add_argument("--observation-id", action="append", required=True)
    coverage = sub.add_parser("coverage", help="Export measured coverage without promoting a payload")
    coverage.add_argument("--product-key", required=True)
    coverage.add_argument("--output", type=Path)
    return result


def main() -> int:
    args = parser().parse_args()
    with EvidenceStore(args.store) as store:
        if args.command == "inventory":
            body = args.input.read_bytes()
            result = {"observation_id": store.observe(provider=args.provider, product_key=args.product_key,
                       record=json.loads(body), observed_at=args.observed_at, ingest_id=args.ingest_id, source_bytes=body)}
        elif args.command == "archive":
            if args.input.stat().st_size > 64 * 1024 * 1024:
                raise ValueError("Local document exceeds the 64 MiB single-document limit")
            result = {"document_version_id": store.record_check(document_id=args.document_id, check_id=args.check_id,
                       checked_at=utc_now(), status="fetched", body=args.input.read_bytes(), media_type=args.media_type,
                       metadata={"acquisition": "retained_official_file"})}
        elif args.command == "fetch":
            result = {"checks": acquire_observation(store, args.observation_id, check_prefix=args.check_prefix,
                       max_documents=args.max_documents, max_total_bytes=args.max_total_bytes,
                       max_seconds=args.max_seconds, policy=FetchPolicy(allowed_hosts=frozenset(args.allowed_host)))}
        elif args.command == "extract":
            result = {"extraction_id": extract_version(store, args.version_id)}
        elif args.command == "acquire-next":
            from .ingest import registry_context
            result = process_next_acquisition(store, registry_context=registry_context())
        elif args.command == "enqueue-historical":
            from .historical import historical_scope
            from .ingest import registry_context
            from .queue import TermsQueue
            queue = TermsQueue(store)
            job_id = queue.enqueue_historical(args.extraction_id, args.observation_id, registry_context=registry_context())
            result = {"job_id": job_id, "status": "queued", "network_called": False, "codex_called": False,
                      "historical_scope": historical_scope(queue.validate_input(job_id)["historical_target"])}
        else:
            result = build_product_asset(store, args.product_key)
            if args.output:
                # Exclusive creation keeps prior evidence reports unchanged.
                with args.output.open("x", encoding="utf-8", newline="\n") as output:
                    output.write(canonical_json(result) + "\n")
        print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
