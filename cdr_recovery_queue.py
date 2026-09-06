"""Bounded terminal-request metadata for later, honest same-day gap recovery."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from cdr_http_policy import sanitize_url
from cdr_ingest_support import allocate_bank_dir
from cdr_reuse_identity import captured_provider_directories

MAX_FAILURE_LINE_BYTES = 64 * 1024
MAX_REQUESTS_PER_PROVIDER = 128
MAX_RECOVERY_REQUESTS = 8192


def add_recovery_requests(status: dict, banks_root: Path, bank_work: list) -> None:
    """Keep terminal failures discoverable without parsing the large data export.

    A bounded queue is a sample of unresolved requests, never a completion claim.
    The original failure journal/aggregate counts remain authoritative.
    """
    states = status.get("provider_states") or []
    seen_directories: set[str] = set()
    fresh = {}
    for row in states:
        derived = allocate_bank_dir(str(row.get("brand_name") or ""),
                                    str(row.get("legal_entity_name") or ""),
                                    str(row.get("endpoint_url") or ""), seen_directories)
        directory = str(row.get("provider_dir") or derived)
        if directory != derived:
            raise ValueError("recovery provider directory does not reconcile")
        row["provider_dir"] = directory
        fresh[directory] = row
    # Reconciliation may add retained identities after the fresh population.
    # Never zip these different populations or alter fresh-register counters.
    providers = captured_provider_directories(status, fresh)
    identities = {name: row.get("provider_uid") for name, row in providers.items()}
    requests: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    counts: dict[str, int] = {}
    complete = True
    digest = hashlib.sha256()
    try:
        with (banks_root / "failures.jsonl").open("rb") as stream:
            while line := stream.readline(MAX_FAILURE_LINE_BYTES + 1):
                digest.update(line)
                if len(line) > MAX_FAILURE_LINE_BYTES:
                    complete = False
                    while line and not line.endswith(b"\n"):
                        line = stream.readline(MAX_FAILURE_LINE_BYTES + 1)
                        digest.update(line)
                    continue
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError("failure is not an object")
                    provider = str(row.get("bank") or "")
                    brand = providers[provider]
                    phase = str(row.get("phase") or "")
                    pid = str(row.get("product_id") or "")
                    endpoint = str(brand.get("endpoint_url") or "").rstrip("/")
                    url = str(row.get("url") or (endpoint + "/" + quote(pid, safe="") if pid else endpoint))
                    if phase not in {"products_index", "product_detail", "classification_detail"}:
                        phase = "product_detail" if pid else "products_index"
                    if phase != "products_index" and not pid:
                        raise ValueError("detail failure lacks an identity")
                    key = (provider, phase, pid, url)
                    if key in seen:
                        continue
                    unrepresented = len(providers) - len(counts)
                    reserved_for_others = min(unrepresented, MAX_RECOVERY_REQUESTS)
                    budget_full = len(requests) >= MAX_RECOVERY_REQUESTS
                    extra_budget_full = counts.get(provider, 0) > 0 and len(requests) >= MAX_RECOVERY_REQUESTS - reserved_for_others
                    if counts.get(provider, 0) >= MAX_REQUESTS_PER_PROVIDER or budget_full or extra_budget_full:
                        complete = False
                        continue
                    seen.add(key)
                    counts[provider] = counts.get(provider, 0) + 1
                    requests.append({
                        "provider_dir": provider, "provider_uid": identities.get(provider),
                        "phase": phase, "product_id": pid, "url": sanitize_url(url),
                        "status": row.get("status"),
                        "failure_category": row.get("failure_category") or "unknown",
                    })
                except (KeyError, TypeError, ValueError):
                    complete = False
    except OSError:
        complete = False
    status.update(
        unresolved_requests=requests, unresolved_requests_complete=complete,
        unresolved_requests_source_sha256=digest.hexdigest(),
        unresolved_request_sample_count=len(requests),
    )
