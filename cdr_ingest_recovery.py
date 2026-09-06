"""One bounded recovery pass before an observation is finalized.

Successful same-run details are reused. Terminal failures are only removed
after positive recapture evidence; the first-pass failure journal is retained.
This module never reads a previous day's products or edits finalized exports.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Callable

from cdr_atomic import atomic_write_json
from cdr_compatibility import pagination_accounting_error, response_shape_error
from cdr_http_policy import DEFAULT_HTTP_POLICY

RECOVERY_SECONDS = 180.0
RECOVERY_PROVIDERS = 12
MAX_RETAINED_FAILURE_BYTES = 256 * 1024


def _read_failures(path: Path) -> list[dict]:
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("failure journal exceeds recovery limit")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if any(not isinstance(row, dict) or not row.get("bank") for row in rows):
        raise ValueError("failure journal has unattributed records")
    return rows


def _retryable(row: dict) -> bool:
    if isinstance(row.get("retryable"), bool):
        return row["retryable"]
    # Compatibility for old/control records. Explicit business/schema errors
    # from new fetchers carry retryable=False and never enter this fallback.
    return str(row.get("status")) in {"408", "429", "500", "502", "503", "504", "599", "circuit_open"}


def _captured_products(root: Path, provider: str) -> set[str]:
    result = set()
    for section in ("Mortgage", "Savings", "TD"):
        for path in (root / section / provider).glob("*/*/product-detail.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                data = value.get("data")
                pid = path.with_name("product-id.txt").read_text(encoding="utf-8").strip()
                if isinstance(data, dict) and not value.get("errors") and data.get("productId") == pid:
                    result.add(pid)
            except (OSError, ValueError, AttributeError):
                continue
    return result


def _index_captured(root: Path, provider: str) -> bool:
    directory = root / "_holders" / provider / "_products-index"
    products = 0
    try:
        for number in range(1, DEFAULT_HTTP_POLICY.max_pages + 1):
            path = directory / f"page-{number:04d}.json"
            if path.stat().st_size > DEFAULT_HTTP_POLICY.max_body_bytes:
                return False
            value = json.loads(path.read_text(encoding="utf-8"))
            if response_shape_error(value, phase="products_index") or value.get("errors"):
                return False
            products += len(value["data"]["products"])
            has_next = bool((value.get("links") or {}).get("next"))
            if pagination_accounting_error(value, pages=number, products=products, has_next=has_next):
                return False
            # A recovered catalog can shrink. Files beyond its validated final
            # page are earlier request evidence, not pages of the current index.
            if not has_next:
                return True
    except (OSError, ValueError, AttributeError):
        return False
    return False


def _reconcile(root: Path, before: list[dict], after: list[dict], provider: str) -> list[dict]:
    fresh = after[len(before):]
    if after[:len(before)] != before or any(row.get("bank") != provider for row in fresh):
        raise ValueError("failure journal changed outside sequential recovery")
    captured = _captured_products(root, provider)
    # A new index failure cannot prove recovery of an old missing page. Even a
    # detail disappearing from the second index isn't proof of successful fetch.
    index_failed = (any(row.get("phase") in {"products_index", "holder"} for row in fresh)
                    or not _index_captured(root, provider))
    kept = []
    fresh_keys = {(row.get("phase"), row.get("product_id")) for row in fresh}
    for row in before:
        if row.get("bank") != provider:
            kept.append(row)
        elif row.get("phase") in {"product_detail", "classification_detail"}:
            if row.get("product_id") not in captured and (row.get("phase"), row.get("product_id")) not in fresh_keys:
                kept.append(row)
        elif row.get("phase") != "products_index" or index_failed:
            if (row.get("phase"), row.get("product_id")) not in fresh_keys:
                kept.append(row)
    return kept + fresh


def _write_failures(path: Path, rows: list[dict]) -> None:
    pending = path.with_suffix(".recovery.tmp")
    with pending.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, path)


def recover_transient_providers(
    root: Path,
    bank_work: list,
    run_one: Callable,
    *,
    log: Callable[[str], None],
    budget_seconds: float = RECOVERY_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Retry affected providers once, sequentially, under a shared deadline."""
    path = root / "failures.jsonl"
    report = {"attempted": [], "budget_seconds": budget_seconds, "result": "not_needed"}
    try:
        rows = _read_failures(path)
    except (OSError, ValueError):
        return {**report, "result": "invalid_failure_evidence"}
    eligible = {str(row["bank"]) for row in rows if _retryable(row)}
    work = [item for item in bank_work if item[1] in eligible][:RECOVERY_PROVIDERS]
    if not work or budget_seconds <= 0:
        return report
    report.update(result="completed", initial_failures=len(rows))
    original = path.read_bytes()
    if len(original) > MAX_RETAINED_FAILURE_BYTES:
        return {**report, "result": "failure_evidence_budget_exhausted"}
    digest = hashlib.sha256(original).hexdigest()
    archive = root / "_recovery" / f"failures-{digest}.jsonl"
    archive.parent.mkdir(exist_ok=True)
    if not archive.exists():
        with archive.open("xb") as stream:
            stream.write(original)
    report["initial_failure_sha256"] = digest
    # ingest-status.json is hash-bound and promoted before the RAM tree is
    # removed. Embed the exact small journal there, not only a staging path.
    report["initial_failure_journal"] = original.decode("utf-8")
    deadline = clock() + budget_seconds
    sleep(min(5.0, max(0.0, budget_seconds / 10)))
    for item in work:
        if clock() >= deadline:
            report["result"] = "budget_exhausted"
            break
        log(f"[banks] bounded recovery: {item[1]}")
        report["attempted"].append(item[1])
        # A failed/crashed callback leaves the initial failures in place.
        try:
            run_one(item, recovery_deadline=deadline)
            after = _read_failures(path)
            rows = _reconcile(root, rows, after, item[1])
            _write_failures(path, rows)
        except Exception as exc:
            report.update(result="recovery_error", error=type(exc).__name__)
            break
    try:
        report["remaining_failures"] = len(_read_failures(path))
    except (OSError, ValueError):
        report["result"] = "invalid_failure_evidence"
    atomic_write_json(root / "_recovery" / "report.json", report)
    return report
