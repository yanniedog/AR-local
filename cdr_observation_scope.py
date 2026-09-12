"""Prove explicit CDR scope exclusions without treating missing products as gone.

The source must still list the exact product in a complete, fresh, contract-bound
index. Only the ingest classifier's explicit out-of-scope categories qualify.
An unknown category, failed detail request, or absent ID never qualifies.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from typing import Mapping

from cdr_atomic import canonical_json_bytes
from cdr_product_classification import OUT_OF_SCOPE_CATEGORIES, extract_cdr_product_category
from cdr_reuse_identity import captured_provider_directories, provider_identity


def _index_events(observation: Mapping, providers: set[str]) -> dict[str, dict[int, dict]]:
    from cdr_observation_selection import read_bound_json

    contract, root = observation["contract"], observation["export_root"]
    journal = observation["status"].get("raw_attempt_journal") or {}
    prefix = str(journal.get("path") or "")
    if prefix != f"attempt-evidence/raw-attempt-journals-v1/{journal.get('session_id')}":
        return {}
    events: dict[str, dict[int, dict]] = defaultdict(dict)
    for record in sorted(contract["artifacts"], key=lambda row: row["path"]):
        if not record["path"].startswith(prefix + "/events/"):
            continue
        event = read_bound_json(root, {"artifacts": [record]}, record["path"])
        context = event.get("context") or {}
        provider, page = context.get("provider"), context.get("page")
        if provider not in providers or context.get("phase") != "products_index":
            continue
        if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= 1000:
            raise ValueError("scope index has an invalid page identity")
        sequence, response = event.get("sequence"), event.get("response") or {}
        if (not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1
                or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                       for value in (event.get("event_digest"), response.get("body_sha256")))):
            raise ValueError("scope index has invalid event identity")
        material = {key: value for key, value in event.items() if key != "event_digest"}
        if hashlib.sha256(canonical_json_bytes(material)).hexdigest() != event["event_digest"]:
            raise ValueError("scope index event digest changed")
        # Match the final attempt at each page, including a terminal failure.
        # A prior successful response must not override a failed final attempt.
        previous = events[provider].get(page)
        if previous is None or event["sequence"] > previous["sequence"]:
            events[provider][page] = event
    return events


def _index_products(observation: Mapping, provider: str, events: dict[int, dict]) -> dict:
    from cdr_ingest_support import extract_products
    from cdr_observation_selection import _verified_withdrawal_index, read_bound_json

    status, contract, root = observation["status"], observation["contract"], observation["export_root"]
    diagnostic = (status.get("index_diagnostics") or {}).get(provider) or {}
    count = diagnostic.get("pages")
    if (diagnostic.get("pagination_complete") is not True
            or diagnostic.get("conflicting_duplicate_records") != 0
            or diagnostic.get("declared_total_records") != diagnostic.get("raw_records")
            or not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 1000
            or set(events) != set(range(1, count + 1))):
        return {}
    journal = status["raw_attempt_journal"]
    pages, products = [], {}
    for number in range(1, count + 1):
        event = events[number]
        response = event.get("response") or {}
        if response.get("status") != 200 or response.get("outcome") != "success":
            return {}
        digest = response.get("body_sha256")
        body = read_bound_json(root, contract, f"{journal['path']}/bodies/{digest}.body",
                               max_bytes=32 * 1024 * 1024)
        for product in extract_products(body):
            pid = str(product.get("productId") or product.get("id") or "")
            if not pid or pid in products:
                raise ValueError("scope index has ambiguous product identities")
            products[pid] = {"record": product, "body_sha256": digest,
                             "event_digest": event["event_digest"], "page": number}
        pages.append({"body_sha256": digest, "event_digest": event["event_digest"],
                      "event_seq": event["sequence"], "journal_session_id": journal["session_id"]})
    proof = {"complete": True, "pages": pages, "observed_product_ids": sorted(products),
             "fresh_index_sha256": hashlib.sha256(canonical_json_bytes({
                 "page_body_sha256": [row["body_sha256"] for row in pages]
             })).hexdigest()}
    # Reuse the existing withdrawal verifier for full pagination, endpoint,
    # event/body hashes, current-day timestamps, counts and exact membership.
    if _verified_withdrawal_index(observation, provider, proof) != set(products):
        raise ValueError("scope index proof did not reconcile")
    return products


def verified_scope_exclusions(observation: Mapping, source: Mapping,
                              missing: set[tuple[str, str]]) -> list[dict]:
    """Return only re-observed products excluded by the existing category rule."""
    try:
        return _scope_exclusions(observation, source, missing)
    except (KeyError, TypeError, AttributeError, OverflowError) as error:
        raise ValueError("scope exclusion evidence has an invalid structure") from error


def _scope_exclusions(observation: Mapping, source: Mapping,
                      missing: set[tuple[str, str]]) -> list[dict]:
    from cdr_observation_selection import provider_directories

    if not missing or observation["status"].get("register_provenance_complete") is not True:
        return []
    previous = captured_provider_directories(source["status"], provider_directories(source["status"]))
    current = provider_directories(observation["status"])
    providers = {provider for provider, _ in missing if provider in previous and provider in current
                 and current[provider].get("provider_uid")
                 and provider_identity(previous[provider]) == provider_identity(current[provider])
                 and sum(row.get("provider_uid") == current[provider]["provider_uid"]
                         for row in current.values()) == 1}
    events = _index_events(observation, providers) if providers else {}
    exclusions = []
    for provider in sorted(providers):
        products = _index_products(observation, provider, events.get(provider, {}))
        for name, pid in sorted(missing):
            if name != provider or pid not in products:
                continue
            proof = products[pid]
            category = extract_cdr_product_category(proof["record"])
            if category in OUT_OF_SCOPE_CATEGORIES:
                exclusions.append({"provider": provider, "product_id": pid, "category": category,
                                   **{key: proof[key] for key in ("body_sha256", "event_digest", "page")}})
    return exclusions


def add_excluded_rate_counts(source: Mapping, exclusions: list[dict]) -> int:
    """Reconcile prior normalized rows; source DB was verified by identity audit."""
    from cdr_observation_selection import safe_child

    if not exclusions:
        return 0
    names = {"local-cdr.sqlite", f"banks-{source['contract']['observation_date']}.sqlite"}
    records = [row for row in source["contract"]["artifacts"] if row["path"] in names]
    if len(records) != 1:
        raise ValueError("scope reconciliation requires one bound source database")
    path = safe_child(source["export_root"], records[0]["path"])
    if any(sidecar.exists() and sidecar.stat().st_size
           for sidecar in (Path(str(path) + suffix) for suffix in ("-wal", "-journal"))):
        raise ValueError("scope reconciliation refuses pending source database writes")
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            db.execute("PRAGMA query_only=ON")
            for row in exclusions:
                row["previous_rate_rows"] = db.execute(
                    "SELECT count(*) FROM bank_rates WHERE provider=? AND product_id=? AND run_date=?",
                    (row["provider"], row["product_id"], source["contract"]["observation_date"]),
                ).fetchone()[0]
    except sqlite3.Error as error:
        raise ValueError("scope reconciliation source database is unreadable") from error
    return sum(row["previous_rate_rows"] for row in exclusions)
