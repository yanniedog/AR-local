"""Orchestration for banking holder workers invoked from ``cdr_full_ingest.py``."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, Optional, Set, Tuple

from cdr_atomic import atomic_write_json
from cdr_compatibility import (
    HolderVersionCache, ProductIndexTracker, classify_fetch_failure, pagination_accounting_error,
    compact_failure_evidence,
)
from cdr_ingest_resume import existing_product_leaves, usable_cached_detail
from cdr_http_policy import DEFAULT_HTTP_POLICY, HttpPolicyError, sanitize_url
from cdr_ingest_support import (
    DATASET_TO_FOLDER,
    FetchResult,
    RegisterSnapshot,
    allocate_bank_dir,
    append_failure,
    collect_register_snapshot,
    detail_inner_record,
    extract_products,
    fetch_cdr_json,
    filesystem_product_id_directory,
    has_cdr_errors,
    infer_cdr_dataset,
    is_record,
    next_link,
    pick_text,
    safe_url,
    sanitize_path_component,
    summarize_failures,
)
from cdr_raw_attempt_journal import RawAttemptJournal, new_session_id

# ─── Per-holder version cache ─────────────────────────────────────────────────

PRODUCT_INDEX_VERSION_ORDER = [6, 5, 4, 3, 2, 1]
PRODUCT_DETAIL_VERSION_ORDER = [7, 6, 5, 4, 3, 2, 1]


def _index_version_list(preferred: Optional[int]) -> List[int]:
    """Try a holder's known-good x-v first; fetch_cdr_json still falls back through
    the rest of CDR_VERSION_ORDER if it stops working, so this is a hint not a
    lock-in. None means "negotiate from the top" (version not yet known)."""
    if preferred is None:
        return list(PRODUCT_INDEX_VERSION_ORDER)
    return [preferred, *(version for version in PRODUCT_INDEX_VERSION_ORDER if version != preferred)]


def _detail_version_list() -> List[int]:
    """Detail capability is independent from the products-index endpoint."""
    return list(PRODUCT_DETAIL_VERSION_ORDER)


# Per-holder circuit breaker: once a holder's product-detail fetches are mostly
# failing (a real outage, not just a few bad products), stop probing the rest of
# that holder and fail them fast — bounding the wasted work + load on a down holder.
BREAKER_MIN_SAMPLE = 20    # require this many attempts before the breaker can trip
BREAKER_FAIL_RATIO = 0.8   # trip when >= this fraction of attempts have failed


class _HolderBreaker:
    """Per-holder circuit breaker shared across a holder's fetches.

    Lock-internal and I/O-free on purpose: callers do failure logging / log() OUTSIDE
    the lock based on the returned flags, so a slow append_failure never serializes
    the detail workers (Gemini). Rate-based so a handful of bad products doesn't trip
    a healthy holder.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._attempts = 0
        self._failures = 0
        self._open = False

    def is_open(self) -> bool:
        with self._lock:
            return self._open

    def record(self, ok: bool) -> bool:
        """Record one outcome; return True iff this call just opened the breaker."""
        with self._lock:
            self._attempts += 1
            if not ok:
                self._failures += 1
            if (
                not self._open
                and self._attempts >= BREAKER_MIN_SAMPLE
                and self._failures >= BREAKER_FAIL_RATIO * self._attempts
            ):
                self._open = True
                return True
            return False

    def snapshot(self) -> Tuple[int, int]:
        with self._lock:
            return self._failures, self._attempts


# ─── Banking detail work unit ─────────────────────────────────────────────────

class _BankWork(NamedTuple):
    pid: str
    leaf: Path
    prefetched: Optional[FetchResult]


class _DetailOutcome(NamedTuple):
    ok: bool
    provider_available: Optional[bool]


def _provider_available(result: FetchResult) -> Optional[bool]:
    if result.attempts == 0:
        return None
    retryable = result.retryable if result.failure_category else classify_fetch_failure(result.status, result.text).retryable
    return result.ok or not retryable


def _fetch_failure_fields(result: FetchResult) -> Dict[str, Any]:
    failure = classify_fetch_failure(result.status, result.text)
    category = result.failure_category or failure.category
    return {
        "status": "recovery_budget_exhausted" if category == "recovery_budget_exhausted" else result.status,
        "failure_category": category,
        "retryable": result.retryable if result.failure_category else failure.retryable,
        # Preserve late credential text without overflowing recovery journals.
        **({"classification_text": compact_failure_evidence(result.status, result.text)}
           if len(result.text or "") > 500 else {}),
        **({"validation_error": result.validation_error} if result.validation_error else {}),
    }


def _pace_fetch(sleep_ms: int, deadline: Optional[float]) -> None:
    delay = max(0.0, sleep_ms / 1000.0)
    if deadline is not None:
        delay = min(delay, max(0.0, deadline - time.monotonic()))
    if delay > 0:
        time.sleep(delay)


def _fetch_detail(
    url: str, *, timeout: float, max_retries: int, sleep_ms: int,
    version_cache: Optional[HolderVersionCache], deadline: Optional[float],
    attempt_journal: Optional[RawAttemptJournal], context: Mapping[str, Any],
) -> FetchResult:
    remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
    if remaining == 0:
        return FetchResult(False, 0, url, "", attempts=0, failure_category="recovery_budget_exhausted")
    order = version_cache.order() if version_cache is not None else _detail_version_list()
    result = fetch_cdr_json(
        url, versions=order, timeout=timeout, max_retries=max_retries, sleep_ms=sleep_ms,
        **({"max_total_seconds": remaining} if remaining is not None else {}),
        attempt_journal=attempt_journal, attempt_context=context,
    )
    if version_cache is not None and (result.ok or result.failure_category in {
        "incompatible_version", "invalid_response",
    }):
        version_cache.record(ok=result.ok, version=result.version, attempted=order[0])
    return result


def _fetch_bank_detail(
    work: _BankWork,
    endpoint_url: str,
    *,
    timeout: float,
    max_retries: int,
    sleep_ms: int,
    date_root: Path,
    bank_dir_name: str,
    failure_lock: Optional[threading.Lock],
    preferred_version: Optional[int] = None,
    attempt_journal: Optional[RawAttemptJournal] = None,
    detail_version_cache: Optional[HolderVersionCache] = None,
    deadline: Optional[float] = None,
    with_availability: bool = False,
) -> bool | _DetailOutcome:
    """Write product-detail.json for one bank product (called from thread pool).

    The default return remains a row-success boolean. Ingest also requests the
    independent provider-availability outcome for its transport circuit breaker.
    """
    pid, leaf, prefetched = work
    detail_path = leaf / "product-detail.json"

    if prefetched is not None:
        res = prefetched
    else:
        _pace_fetch(sleep_ms, deadline)
        url = f"{safe_url(endpoint_url)}/{urllib.parse.quote(pid, safe='')}"
        res = _fetch_detail(
            url,
            timeout=timeout, max_retries=max_retries, sleep_ms=sleep_ms,
            version_cache=detail_version_cache, deadline=deadline,
            attempt_journal=attempt_journal,
            context={
                "phase": "product_detail",
                "provider": bank_dir_name,
                "product_id": pid,
                "request_id": f"holder:{bank_dir_name}:detail:{pid}",
            },
        )

    parsed = res.data
    if res.ok and parsed is not None and not has_cdr_errors(parsed):
        detail_path.write_text(res.text, encoding="utf-8")
        return _DetailOutcome(True, _provider_available(res)) if with_availability else True
    append_failure(
        date_root,
        {
            "phase": "product_detail",
            "bank": bank_dir_name,
            "product_id": pid,
            **_fetch_failure_fields(res),
            "snippet": (res.text or "")[:500],
        },
        lock=failure_lock,
    )
    (leaf / "product-detail.error.txt").write_text(res.text or "", encoding="utf-8")
    return _DetailOutcome(False, _provider_available(res)) if with_availability else False


def classify_product_for_ingest(
    product: Mapping[str, Any],
    *,
    fetch_unknown_detail: bool,
    endpoint_url: str,
    timeout: float,
    max_retries: int,
    sleep_ms: int,
    preferred_version: Optional[int] = None,
    breaker: "Optional[_HolderBreaker]" = None,
    bank_dir_name: str = "unknown",
    attempt_journal: Optional[RawAttemptJournal] = None,
    detail_version_cache: Optional[HolderVersionCache] = None,
    deadline: Optional[float] = None,
) -> Tuple[Optional[str], Optional[FetchResult]]:
    """Returns (dataset_kind or None, optional detail_fetch_if_unknown_path)."""
    ds = infer_cdr_dataset(product, allow_name_fallback=True)
    if ds in DATASET_TO_FOLDER:
        return ds, None
    if not fetch_unknown_detail:
        return None, None

    pid = pick_text(product, ["productId", "id"])
    if not pid:
        return None, None

    # Share the holder breaker with these Phase-1 classification probes (Codex): a
    # down detail endpoint trips here too, so we stop probing every ambiguous
    # product instead of waiting until Phase 2.
    if breaker is not None and breaker.is_open():
        return None, None

    detail_url = f"{safe_url(endpoint_url)}/{urllib.parse.quote(pid, safe='')}"
    _pace_fetch(sleep_ms, deadline)
    detail_res = _fetch_detail(
        detail_url,
        timeout=timeout,
        max_retries=max_retries,
        sleep_ms=sleep_ms,
        version_cache=detail_version_cache, deadline=deadline,
        attempt_journal=attempt_journal,
        context={
            "phase": "classification_detail",
            "provider": bank_dir_name,
            "product_id": pid,
            "request_id": f"holder:{bank_dir_name}:classify:{pid}",
        },
    )
    availability = _provider_available(detail_res)
    if breaker is not None and availability is not None:
        breaker.record(availability)
    parsed = detail_res.data
    inner = detail_inner_record(parsed)
    if inner is None:
        return None, detail_res

    ds2 = infer_cdr_dataset(inner, allow_name_fallback=True)
    if ds2 in DATASET_TO_FOLDER:
        return ds2, detail_res
    return None, detail_res


def ingest_brand(
    brand: Dict[str, str],
    *,
    date_root: Path,
    resume: bool,
    sleep_ms: int,
    timeout: float,
    max_retries: int,
    max_pages: Optional[int],
    max_products: Optional[int],
    fetch_unknown_detail: bool,
    bank_dir_name: str,
    detail_workers: int,
    log: Callable[[str], None],
    failure_lock: Optional[threading.Lock] = None,
    attempt_journal: Optional[RawAttemptJournal] = None,
    deadline: Optional[float] = None,
) -> None:
    """Ingest one banking holder.

    Phase 1 (serial): walk paginated product index, classify each product,
    create directory skeletons.
    Phase 2 (parallel): fetch all product-detail payloads concurrently using
    up to ``detail_workers`` threads.
    """
    endpoint_url = brand["endpoint_url"]
    holders_root = date_root / "_holders" / bank_dir_name
    holders_root.mkdir(parents=True, exist_ok=True)

    meta_path = holders_root / "_register-brand.json"
    if not meta_path.exists():
        meta_path.write_text(json.dumps(brand, indent=2, ensure_ascii=False), encoding="utf-8")

    index_dir = holders_root / "_products-index"
    index_dir.mkdir(parents=True, exist_ok=True)

    # ─── Phase 1: collect all pages, build work list ──────────────────────────

    pending: List[_BankWork] = []
    url: Optional[str] = endpoint_url
    visited: Set[str] = set()
    pages = 0
    products_seen = 0
    capped = False
    page_limit = min(
        DEFAULT_HTTP_POLICY.max_pages,
        max(0, int(max_pages)) if max_pages is not None else DEFAULT_HTTP_POLICY.max_pages,
    )
    # Index and detail contracts version independently. Cache detail success for
    # this holder/run only, including classification probes and parallel fetches.
    preferred_version: Optional[int] = None
    detail_version_cache = HolderVersionCache(PRODUCT_DETAIL_VERSION_ORDER)
    index_tracker = ProductIndexTracker()
    last_meta: Dict[str, Any] = {}
    accounting_error: Optional[str] = None
    existing_leaves, resume_conflicts = existing_product_leaves(date_root, bank_dir_name) if resume else ({}, set())
    # Per-holder circuit breaker, shared across Phase-1 classification probes and
    # the Phase-2 detail workers (so a down detail endpoint trips in either phase).
    breaker = _HolderBreaker()

    while url and not capped:
        if deadline is not None and time.monotonic() >= deadline:
            append_failure(date_root, {
                "phase": "products_index", "bank": bank_dir_name,
                "status": "recovery_budget_exhausted", "retryable": False,
            }, lock=failure_lock)
            break
        if url in visited:
            append_failure(
                date_root,
                {
                    "phase": "products_index",
                    "bank": bank_dir_name,
                    "status": "pagination_cycle",
                    "url": sanitize_url(url),
                },
                lock=failure_lock,
            )
            break
        visited.add(url)
        pages += 1
        if pages > page_limit:
            log(f"max-pages reached for {bank_dir_name}")
            append_failure(
                date_root,
                {
                    "phase": "products_index",
                    "bank": bank_dir_name,
                    "status": "max_pages_reached",
                    "configured_limit": max_pages,
                    "effective_limit": page_limit,
                },
                lock=failure_lock,
            )
            break

        _pace_fetch(sleep_ms, deadline)
        res = fetch_cdr_json(
            url, versions=_index_version_list(preferred_version),
            timeout=timeout, max_retries=max_retries, sleep_ms=sleep_ms,
            **({"max_total_seconds": max(0.0, deadline - time.monotonic())} if deadline is not None else {}),
            attempt_journal=attempt_journal,
            attempt_context={
                "phase": "products_index",
                "provider": bank_dir_name,
                "page": pages,
                "request_id": f"holder:{bank_dir_name}:page:{pages}",
            },
        )
        page_file = index_dir / f"page-{pages:04d}.json"
        page_file.write_text(res.text, encoding="utf-8")

        parsed = res.data
        if not res.ok or parsed is None or has_cdr_errors(parsed):
            append_failure(
                date_root,
                {
                    "phase": "products_index",
                    "bank": bank_dir_name,
                    "url": url,
                    **_fetch_failure_fields(res),
                    "snippet": (res.text or "")[:500],
                },
                lock=failure_lock,
            )
            break

        if res.version is not None:
            preferred_version = res.version
        last_meta = parsed.get("meta") or {}

        for product in extract_products(parsed):
            if deadline is not None and time.monotonic() >= deadline:
                append_failure(date_root, {
                    "phase": "products_index", "bank": bank_dir_name,
                    "status": "recovery_budget_exhausted", "retryable": False,
                }, lock=failure_lock)
                capped = True
                break
            if max_products is not None and products_seen >= max_products:
                log(f"max-products reached for {bank_dir_name}")
                append_failure(
                    date_root,
                    {
                        "phase": "products_index",
                        "bank": bank_dir_name,
                        "status": "max_products_reached",
                        "configured_limit": max_products,
                    },
                    lock=failure_lock,
                )
                capped = True
                break
            products_seen += 1

            if not is_record(product):
                continue

            pid = pick_text(product, ["productId", "id"])
            if not pid:
                continue
            identity_state = index_tracker.observe(pid, product)
            if identity_state != "new":
                if identity_state == "conflicting":
                    append_failure(date_root, {
                        "phase": "products_index", "bank": bank_dir_name,
                        "status": "conflicting_product_identity", "product_id": pid,
                        "failure_category": "invalid_response", "retryable": False,
                    }, lock=failure_lock)
                continue
            if pid in resume_conflicts:
                append_failure(date_root, {
                    "phase": "products_index", "bank": bank_dir_name,
                    "status": "resume_identity_conflict", "product_id": pid,
                    "failure_category": "invalid_response", "retryable": False,
                }, lock=failure_lock)
                continue
            existing_leaf = existing_leaves.get(pid)
            if existing_leaf is not None and usable_cached_detail(existing_leaf, pid):
                continue

            ds, prefetched = classify_product_for_ingest(
                product,
                fetch_unknown_detail=fetch_unknown_detail,
                endpoint_url=endpoint_url,
                timeout=timeout,
                max_retries=max_retries,
                sleep_ms=sleep_ms,
                preferred_version=preferred_version,
                breaker=breaker,
                bank_dir_name=bank_dir_name,
                attempt_journal=attempt_journal,
                detail_version_cache=detail_version_cache,
                deadline=deadline,
            )
            if ds not in DATASET_TO_FOLDER:
                if prefetched is not None and not prefetched.ok:
                    append_failure(date_root, {
                        "phase": "classification_detail", "bank": bank_dir_name,
                        "product_id": pid, **_fetch_failure_fields(prefetched),
                        "snippet": (prefetched.text or "")[:500],
                    }, lock=failure_lock)
                continue

            folder = DATASET_TO_FOLDER[ds]
            pname = sanitize_path_component(
                pick_text(product, ["name", "productName"]) or "_unnamed"
            )
            id_dir = filesystem_product_id_directory(pid)
            leaf = existing_leaf or date_root / folder / bank_dir_name / pname / id_dir
            leaf.mkdir(parents=True, exist_ok=True)

            id_file = leaf / "product-id.txt"
            if not id_file.exists():
                id_file.write_text(pid + "\n", encoding="utf-8")

            pending.append(_BankWork(pid=pid, leaf=leaf, prefetched=prefetched))

        try:
            url = next_link(parsed, url)
            accounting_error = pagination_accounting_error(
                parsed, pages=pages, products=products_seen, has_next=bool(url),
            ) if not capped else None
            if accounting_error:
                append_failure(date_root, {
                    "phase": "products_index", "bank": bank_dir_name,
                    "status": "pagination_incomplete", "validation_error": accounting_error,
                    "failure_category": "invalid_response", "retryable": False,
                }, lock=failure_lock)
                break
        except HttpPolicyError as error:
            append_failure(
                date_root,
                {
                    "phase": "products_index",
                    "bank": bank_dir_name,
                    "status": error.code,
                    "error": error.public_message,
                },
                lock=failure_lock,
            )
            break

    # ─── Phase 2: parallel detail fetches ────────────────────────────────────

    atomic_write_json(index_dir / "diagnostics.json", index_tracker.summary(
        pages=pages, raw_records=products_seen,
        complete=not url and not capped and accounting_error is None, meta=last_meta,
    ))
    if not pending:
        return

    n_workers = min(detail_workers, len(pending))
    log(
        f"[banks] {bank_dir_name}: fetching {len(pending)} product details "
        f"({n_workers} concurrent)",
    )

    def _do(work: _BankWork) -> None:
        # A product whose detail was already prefetched in Phase 1 is written even
        # when the breaker is open — don't discard an already-successful fetch
        # (Codex). The open-circuit skip applies only to work that still needs a
        # network fetch. File I/O stays OUTSIDE the breaker lock (Gemini).
        needs_fetch = work.prefetched is None
        if needs_fetch and deadline is not None and time.monotonic() >= deadline:
            append_failure(date_root, {
                "phase": "product_detail", "bank": bank_dir_name,
                "product_id": work.pid, "status": "recovery_budget_exhausted",
                "failure_category": "recovery_budget_exhausted", "retryable": False,
            }, lock=failure_lock)
            return
        if needs_fetch and breaker.is_open():
            append_failure(
                date_root,
                {
                    "phase": "product_detail",
                    "bank": bank_dir_name,
                    "product_id": work.pid,
                    "status": "circuit_open",
                },
                lock=failure_lock,
            )
            return
        outcome = _fetch_bank_detail(
            work,
            endpoint_url,
            timeout=timeout,
            max_retries=max_retries,
            sleep_ms=sleep_ms,
            date_root=date_root,
            bank_dir_name=bank_dir_name,
            failure_lock=failure_lock,
            preferred_version=preferred_version,
            attempt_journal=attempt_journal,
            detail_version_cache=detail_version_cache,
            deadline=deadline,
            with_availability=True,
        )
        # Only true network fetches feed the breaker; a Phase-1 prefetched result
        # was already counted in classify_product_for_ingest.
        if needs_fetch and outcome.provider_available is not None and breaker.record(outcome.provider_available):
            failures, attempts = breaker.snapshot()
            log(
                f"[banks] {bank_dir_name}: circuit opened "
                f"({failures}/{attempts} detail requests unavailable) — skipping remaining details"
            )

    if n_workers <= 1:
        for w in pending:
            _do(w)
    else:
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {pool.submit(_do, w): w.pid for w in pending}
            done = 0
            for fut in as_completed(futures):
                done += 1
                try:
                    fut.result()
                except Exception as exc:
                    # An unexpected detail-worker crash (not a normal fetch failure,
                    # which _fetch_bank_detail already records) is otherwise only
                    # logged; record it so the status rollup counts it (Codex).
                    log(f"[banks] {bank_dir_name}: detail error for {futures[fut]}: {exc}")
                    append_failure(
                        date_root,
                        {
                            "phase": "product_detail",
                            "bank": bank_dir_name,
                            "product_id": futures[fut],
                            "status": "worker_crash",
                            "error": str(exc)[:500],
                        },
                        lock=failure_lock,
                    )
                if done % 50 == 0:
                    log(f"[banks] {bank_dir_name}: {done}/{len(pending)} details done")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _provider_index_diagnostics(banks_root: Path, bank_work: list) -> Dict[str, Any]:
    diagnostics = {}
    for _, provider in bank_work:
        path = banks_root / "_holders" / provider / "_products-index" / "diagnostics.json"
        try:
            if path.stat().st_size > 4096:
                raise ValueError("index diagnostics exceed the bounded metadata size")
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("schema_version") != 1:
                raise ValueError("index diagnostics are invalid")
            diagnostics[provider] = data
        except (OSError, ValueError):
            diagnostics[provider] = {"available": False}
    return diagnostics


def _persist_ingest_status(
    *,
    banks_root: Path,
    run_root: Path,
    snapshot: RegisterSnapshot,
    bank_work: List[Tuple[Dict[str, str], str]],
    attempt_journal: RawAttemptJournal,
) -> Dict[str, Any]:
    """Publish a discoverable evidence pointer on success and every early exit."""
    banks_root.mkdir(parents=True, exist_ok=True)
    status = summarize_failures(banks_root)
    status["index_diagnostics"] = _provider_index_diagnostics(banks_root, bank_work)
    status["register_attempts"] = snapshot.register_attempts
    status["register_provenance_complete"] = snapshot.register_provenance_complete
    status["failure_provenance_complete"] = bool(
        status.get("failure_provenance_complete")
        and snapshot.register_provenance_complete
    )
    status["incomplete"] = bool(
        status.get("incomplete") or not snapshot.register_provenance_complete
    )
    by_provider = status.get("by_provider") or {}
    provider_states = []
    for brand, bdir in bank_work:
        identity_material = "\x1f".join(
            (
                str(brand.get("endpoint_url") or "").strip().lower(),
                str(brand.get("legal_entity_name") or "").strip().lower(),
                str(brand.get("brand_name") or "").strip().lower(),
            )
        ).encode("utf-8")
        failures = int(by_provider.get(bdir) or 0)
        provider_states.append(
            {
                "provider_uid": f"legacy-prd:{hashlib.sha256(identity_material).hexdigest()}",
                "identity_status": "derived_legacy",
                "provider_dir": bdir,
                "brand_name": brand.get("brand_name") or None,
                "legal_entity_name": brand.get("legal_entity_name") or None,
                "endpoint_url": brand.get("endpoint_url") or None,
                "state": "partial" if failures else "complete",
                "failure_records": failures,
                "failure_categories": status["by_provider_failure_category"].get(bdir, {}),
            }
        )
    status["providers_registered"] = snapshot.banking_count_before_filter
    status["providers_attempted"] = len(bank_work)
    status["provider_states"] = provider_states
    attempt_summary = attempt_journal.summary()
    attempt_summary["path"] = attempt_journal.root.relative_to(run_root).as_posix()
    attempt_summary["path_resolution"] = "relative_to_ingest_run_root"
    attempt_summary["retention"] = "follows_ingest_run_root"
    status["raw_attempt_journal"] = attempt_summary
    from cdr_recovery_queue import add_recovery_requests

    add_recovery_requests(status, banks_root, bank_work)
    atomic_write_json(banks_root / "ingest-status.json", status)
    return status

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    here = Path(__file__).resolve().parent
    default_out = here / "runs"

    p = argparse.ArgumentParser(
        description="Standalone Australian CDR PRD ingest for banking products.",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=default_out,
        help=f"Output root (default: {default_out})",
    )
    p.add_argument(
        "--date",
        type=str,
        default=None,
        help="Run folder YYYY-MM-DD (default: UTC today)",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help="Skip existing non-empty product-detail.json files",
    )
    p.add_argument(
        "--sleep-ms",
        type=int,
        default=40,
        help="Delay per HTTP call per worker thread (milliseconds, default 40)",
    )
    p.add_argument("--timeout", type=float, default=90.0, help="Per-request timeout seconds")
    p.add_argument("--max-retries", type=int, default=6, help="Retries on 429/5xx (exponential backoff with jitter)")
    p.add_argument(
        "--holders",
        type=str,
        default=None,
        help="Substring filter on brand name, legal name, or endpoint URL",
    )
    p.add_argument("--max-pages", type=int, default=None, help="Cap index pages per holder")
    p.add_argument("--max-products", type=int, default=None, help="Cap products per holder")
    p.add_argument(
        "--fetch-unknown-detail",
        action="store_true",
        help="GET detail once when list classification is ambiguous; classify from detail body",
    )
    p.add_argument(
        "--allow-empty-holders",
        action="store_true",
        help=(
            "Exit 0 when register discovery fails or no holders match filters "
            "(for automation during outages / empty register)"
        ),
    )
    p.add_argument(
        "--workers",
        type=int,
        default=8,
        metavar="N",
        help="Parallel holder ingests (default: 8). Use 1 for serial per-holder runs.",
    )
    p.add_argument(
        "--detail-workers",
        type=int,
        default=4,
        metavar="N",
        help=(
            "Parallel detail GETs within each holder (default: 4). "
            "Total concurrent requests ~= workers x detail-workers."
        ),
    )
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    run_date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_root: Path = args.out.expanduser().resolve()
    run_root = out_root / run_date
    banks_root = run_root / "banks"

    def log(msg: str) -> None:
        print(msg, file=sys.stderr)

    if args.workers < 1:
        log("ERROR: --workers must be >= 1")
        return 2
    if args.detail_workers < 1:
        log("ERROR: --detail-workers must be >= 1")
        return 2

    log(f"Run folder: {run_root}")
    run_root.mkdir(parents=True, exist_ok=True)
    attempt_journal = RawAttemptJournal(
        run_root / "_raw-attempt-journals-v1",
        new_session_id(),
    )
    bank_work: List[Tuple[Dict[str, str], str]] = []

    snap = collect_register_snapshot(
        timeout=args.timeout,
        max_retries=args.max_retries,
        sleep_ms=args.sleep_ms,
        holders_filter=args.holders,
        attempt_journal=attempt_journal,
    )
    log(
        f"Banking holders: {len(snap.banking_brands)} after filter "
        f"({snap.banking_count_before_filter} before --holders)",
    )

    if not snap.register_ok:
        _persist_ingest_status(
            banks_root=banks_root,
            run_root=run_root,
            snapshot=snap,
            bank_work=bank_work,
            attempt_journal=attempt_journal,
        )
        if args.allow_empty_holders:
            log("WARNING: CDR register discovery failed (--allow-empty-holders); exiting 0.")
            return 0
        log("ERROR: CDR register discovery failed.")
        return 2

    run_banks = len(snap.banking_brands) > 0
    if not run_banks:
        _persist_ingest_status(
            banks_root=banks_root,
            run_root=run_root,
            snapshot=snap,
            bank_work=bank_work,
            attempt_journal=attempt_journal,
        )
        if args.allow_empty_holders:
            log("WARNING: no banking holders to ingest (--allow-empty-holders); exiting 0.")
            return 0
        else:
            if snap.banking_count_before_filter == 0:
                log("ERROR: register returned zero banking PRD brands.")
                return 2
            if args.holders:
                log(f"ERROR: no banking holders matched --holders {args.holders!r}.")
                return 1
            log("ERROR: register contained no banking PRD brands.")
            return 2

    workers = args.workers
    detail_workers = args.detail_workers
    failure_lock = threading.Lock() if workers > 1 else None
    log_lock = threading.Lock() if workers > 1 else None

    def log_ts(msg: str) -> None:
        if log_lock is not None:
            with log_lock:
                log(msg)
        else:
            log(msg)

    # ─── Sector runner closures ───────────────────────────────────────────────

    def do_banks() -> Callable:
        banks_root.mkdir(parents=True, exist_ok=True)
        # Start each run with a clean failure log so the end-of-run status rollup
        # reflects THIS run, not stale failures left by a prior same-day --resume
        # rerun (append-only failures.jsonl would otherwise double-count) (Codex).
        failure_log = banks_root / "failures.jsonl"
        failure_log.unlink(missing_ok=True)
        # A retained zero-byte journal is positive evidence that no failure was
        # recorded. Missing or unreadable evidence is never equivalent to zero.
        with failure_log.open("x", encoding="utf-8"):
            pass
        seen_dirs: Set[str] = set()
        for brand in snap.banking_brands:
            bdir = allocate_bank_dir(
                brand["brand_name"],
                brand["legal_entity_name"],
                brand["endpoint_url"],
                seen_dirs,
            )
            bank_work.append((brand, bdir))

        log_ts(
            f"Starting banking ingest: {len(bank_work)} holders, "
            f"--workers {workers}, --detail-workers {detail_workers}",
        )

        def run_one(item: Tuple[Dict[str, str], str], *, recovery_deadline: Optional[float] = None) -> None:
            brand, bdir = item
            log_ts(f"[banks] Ingesting {bdir} ({brand['endpoint_url']})")
            try:
                ingest_brand(
                    brand,
                    date_root=banks_root,
                    resume=args.resume or recovery_deadline is not None,
                    sleep_ms=args.sleep_ms,
                    timeout=args.timeout,
                    max_retries=min(args.max_retries, 1) if recovery_deadline is not None else args.max_retries,
                    max_pages=args.max_pages,
                    max_products=args.max_products,
                    fetch_unknown_detail=args.fetch_unknown_detail,
                    bank_dir_name=bdir,
                    detail_workers=1 if recovery_deadline is not None else detail_workers,
                    log=log_ts,
                    failure_lock=failure_lock,
                    attempt_journal=attempt_journal,
                    **({"deadline": recovery_deadline} if recovery_deadline is not None else {}),
                )
            except Exception as exc:  # noqa: BLE001
                # A holder worker that crashes before/while recording its own
                # failures would otherwise be invisible to the status rollup
                # (do_banks only logs it). Record it so the run reads as INCOMPLETE
                # (Codex).
                log_ts(f"ERROR: banking ingest for {bdir} failed: {exc}")
                append_failure(
                    banks_root,
                    {"phase": "holder", "bank": bdir, "status": "worker_crash", "error": str(exc)[:500]},
                    lock=failure_lock,
                )

        if workers == 1:
            for item in bank_work:
                run_one(item)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = {pool.submit(run_one, item): item[1] for item in bank_work}
                for fut in as_completed(futs):
                    try:
                        fut.result()
                    except Exception as exc:
                        log_ts(f"ERROR: banking ingest for {futs[fut]} failed: {exc}")

        return run_one

    run_one = do_banks()
    # Recovery stays inside the original current-day staging transaction.
    # Export and ledger finalization only see reconciled terminal failures.
    from cdr_ingest_recovery import recover_transient_providers

    recovery = recover_transient_providers(
        banks_root, bank_work, run_one, log=log_ts,
        budget_seconds=0 if args.max_pages is not None or args.max_products is not None else 180.0,
    )
    status = _persist_ingest_status(
        banks_root=banks_root,
        run_root=run_root,
        snapshot=snap,
        bank_work=bank_work,
        attempt_journal=attempt_journal,
    )
    status["recovery"] = recovery
    atomic_write_json(banks_root / "ingest-status.json", status)
    if status["incomplete"]:
        log(
            f"Ingest INCOMPLETE: {status['total']} failure(s) "
            f"by_status={status['by_status']}; see {banks_root / 'ingest-status.json'}"
        )
    else:
        log("Ingest complete: no recorded failures.")

    log("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
