"""Independently check the two public components required to discover an app day.

Read-only: a stale or withheld observation never authorizes a new ingest or an
upload. Producer completion and a missing retry marker are not publication proof.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import date
from typing import Callable


MANIFEST_URL = "https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/manifest.json"
DATES_INDEX_URL = "https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/dates-index.json"
MAX_DOCUMENT_BYTES = 1024 * 1024


def fetch_document(url: str, timeout: int = 15) -> dict:
    request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(MAX_DOCUMENT_BYTES + 1)
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ValueError("publication_document_too_large")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("publication_document_not_object")
    return result


def _valid_date(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def check_publication(
    expected: str, *, manifest_url: str = MANIFEST_URL,
    index_url: str = DATES_INDEX_URL,
    fetch: Callable[[str], dict] = fetch_document,
) -> dict:
    """Require coherent current rolling/index dates; report each failure separately."""
    if not _valid_date(expected):
        raise ValueError("invalid_expected_date")
    result = {
        "manifest_run_date": "", "dates_index_latest_date": "", "generated_at": "",
        "manifest_error": None, "dates_index_error": None, "publication_issues": [],
    }
    issues = result["publication_issues"]
    manifest_date = ""
    try:
        manifest = fetch(manifest_url)
        manifest_date = manifest.get("run_date")
        if not _valid_date(manifest_date):
            raise ValueError("invalid_manifest_date")
        if manifest.get("schema_version") != 1:
            raise ValueError("unsupported_manifest_schema")
        if manifest.get("publication_state", "accepted") != "accepted":
            raise ValueError("manifest_not_accepted")
        result["manifest_run_date"] = manifest_date
        result["generated_at"] = str(manifest.get("generated_at") or "")
        if manifest_date != expected:
            issues.append("manifest_stale" if manifest_date < expected else "manifest_future")
    except (OSError, ValueError, TypeError, AttributeError) as error:
        result["manifest_error"] = type(error).__name__
        issues.append("manifest_unavailable_or_invalid")
    try:
        index = fetch(index_url)
        dates = index.get("dates")
        if (index.get("schema_version") != 1 or not isinstance(dates, list)
                or not dates or not all(_valid_date(day) for day in dates)
                or dates != sorted(set(dates)) or index.get("latest_date") != dates[-1]):
            raise ValueError("invalid_dates_index")
        if "count" in index and index["count"] != len(dates):
            raise ValueError("invalid_dates_index_count")
        result["dates_index_latest_date"] = dates[-1]
        if dates[-1] != expected:
            issues.append("dates_index_stale" if dates[-1] < expected else "dates_index_future")
        if expected not in dates:
            issues.append("expected_date_not_indexed")
        if manifest_date and manifest_date != dates[-1]:
            issues.append("rolling_index_mismatch")
    except (OSError, ValueError, TypeError, AttributeError) as error:
        result["dates_index_error"] = type(error).__name__
        issues.append("dates_index_unavailable_or_invalid")
    result["publication_current"] = not issues
    return result
