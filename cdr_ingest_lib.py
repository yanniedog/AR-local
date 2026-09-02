"""Orchestration for banking holder workers invoked from ``cdr_full_ingest.py``."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date as calendar_date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, Optional, Set, Tuple

from cdr_atomic import atomic_write_json
from ar_local_ingest_schedule import DAILY_INGEST_TZ
from cdr_http_policy import DEFAULT_HTTP_POLICY, HttpPolicyError, sanitize_url
from cdr_ingest_population import ProductPopulation
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
# An open circuit used to end a holder for the whole run: every remaining product
# was recorded "circuit_open" and never requested again. A holder that was briefly
# unreachable therefore lost its entire remaining catalogue for that day, and a
# day cannot be re-observed (live CDR endpoints serve only current state). The
# 2026-08-11 run recorded 537 circuit_open products on top of 532 HTTP 406s.
# Deferred products now get one bounded second chance, gated behind a single
# probe so a genuinely down holder still costs one request rather than a retry
# storm.
BREAKER_RECOVERY_DELAY_SECONDS = 30.0


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

    def reset(self) -> None:
        """Close the circuit and forget the failed window after a good probe."""
        with self._lock:
            self._attempts = 0
            self._failures = 0
            self._open = False


# ─── Banking detail work unit ─────────────────────────────────────────────────

class _BankWork(NamedTuple):
    pid: str
    leaf: Path
    prefetched: Optional[FetchResult]


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
) -> bool:
    """Write product-detail.json for one bank product (called from thread pool).

    Returns True only for a matching, valid detail. Raw request attempts are kept
    by ``attempt_journal``; the caller records only terminal failures.
    """
    pid, leaf, prefetched = work
    detail_path = leaf / "product-detail.json"

    if prefetched is not None:
        res = prefetched
    else:
        time.sleep(sleep_ms / 1000.0)
        url = f"{safe_url(endpoint_url)}/{urllib.parse.quote(pid, safe='')}"
        res = fetch_cdr_json(
            url, versions=_detail_version_list(),
            timeout=timeout, max_retries=max_retries, sleep_ms=sleep_ms,
            attempt_journal=attempt_journal,
            attempt_context={
                "phase": "product_detail",
                "provider": bank_dir_name,
                "product_id": pid,
                "request_id": f"holder:{bank_dir_name}:detail:{pid}",
            },
        )

    parsed = res.data
    inner = detail_inner_record(parsed)
    detail_pid = pick_text(inner or {}, ["productId", "id"])
    if (
        res.ok
        and parsed is not None
        and not has_cdr_errors(parsed)
        and inner is not None
        and detail_pid == pid
    ):
        detail_path.write_text(res.text, encoding="utf-8")
        (leaf / "product-detail.error.txt").unlink(missing_ok=True)
        return True
    (leaf / "product-detail.error.txt").write_text(res.text or "", encoding="utf-8")
    return False


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
    time.sleep(sleep_ms / 1000.0)
    detail_res = fetch_cdr_json(
        detail_url,
        versions=_detail_version_list(),
        timeout=timeout,
        max_retries=max_retries,
        sleep_ms=sleep_ms,
        attempt_journal=attempt_journal,
        attempt_context={
            "phase": "classification_detail",
            "provider": bank_dir_name,
            "product_id": pid,
            "request_id": f"holder:{bank_dir_name}:classify:{pid}",
        },
    )
    if breaker is not None:
        breaker.record(detail_res.ok)
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
) -> Dict[str, Any]:
    """Ingest one banking holder.

    Phase 1 (serial): walk paginated product index, classify each product,
    create directory skeletons.
    Phase 2 (parallel): fetch all product-detail payloads concurrently using
    up to ``detail_workers`` threads.
    """
    endpoint_url = brand["endpoint_url"]
    try:
        population = ProductPopulation(
            provider_uid=brand["provider_uid"],
            identity_status=brand["provider_identity_status"],
        )
    except KeyError as error:
        raise ValueError(f"register brand is missing identity evidence: {error.args[0]}") from error
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
    terminal_page_reached = False
    page_limit = min(
        DEFAULT_HTTP_POLICY.max_pages,
        max(0, int(max_pages)) if max_pages is not None else DEFAULT_HTTP_POLICY.max_pages,
    )
    # Per-holder version cache: once a fetch succeeds we remember the x-v that
    # worked and try it first for this holder's remaining pages + every product
    # detail, instead of re-negotiating from the top each time. Set serially in
    # Phase 1, then read-only in the Phase 2 thread pool (no shared-state race).
    preferred_version: Optional[int] = None
    # Per-holder circuit breaker, shared across Phase-1 classification probes and
    # the Phase-2 detail workers (so a down detail endpoint trips in either phase).
    breaker = _HolderBreaker()

    while url and not capped:
        if url in visited:
            population.fail_population("pagination_cycle")
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
        population.page_attempted()
        if pages > page_limit:
            population.fail_population("max_pages_reached")
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

        time.sleep(sleep_ms / 1000.0)
        res = fetch_cdr_json(
            url, versions=_index_version_list(preferred_version),
            timeout=timeout, max_retries=max_retries, sleep_ms=sleep_ms,
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
            population.fail_population("page_fetch_failed")
            append_failure(
                date_root,
                {
                    "phase": "products_index",
                    "bank": bank_dir_name,
                    "url": url,
                    "status": res.status,
                    "snippet": (res.text or "")[:500],
                },
                lock=failure_lock,
            )
            break

        if res.version is not None:
            preferred_version = res.version
        population.page_fetched(parsed)

        for product in extract_products(parsed):
            if max_products is not None and products_seen >= max_products:
                population.fail_population("max_products_reached")
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
            pid = pick_text(product, ["productId", "id"])
            if not population.product(product, pid):
                continue
            products_seen += 1

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
            )
            if ds not in DATASET_TO_FOLDER:
                continue
            population.mark_relevant(pid)

            folder = DATASET_TO_FOLDER[ds]
            pname = sanitize_path_component(
                pick_text(product, ["name", "productName"]) or "_unnamed"
            )
            id_dir = filesystem_product_id_directory(pid)
            leaf = date_root / folder / bank_dir_name / pname / id_dir
            leaf.mkdir(parents=True, exist_ok=True)

            id_file = leaf / "product-id.txt"
            if not id_file.exists():
                id_file.write_text(pid + "\n", encoding="utf-8")

            detail_path = leaf / "product-detail.json"
            if resume and detail_path.exists() and detail_path.stat().st_size > 0:
                population.mark_resumed(pid)
                continue

            pending.append(_BankWork(pid=pid, leaf=leaf, prefetched=prefetched))

        try:
            url = next_link(parsed, url)
            if url is None:
                terminal_page_reached = True
        except HttpPolicyError as error:
            population.fail_population(error.code)
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

    population.finish_pages(terminal_page_reached=terminal_page_reached)
    population_snapshot = population.summary()
    for code in population_snapshot["population_errors"]:
        if code in {
            "duplicate_product_conflict",
            "duplicate_product_id",
            "invalid_declared_total",
            "inconsistent_declared_total",
            "declared_total_mismatch",
            "malformed_product",
        }:
            append_failure(
                date_root,
                {
                    "phase": "products_index",
                    "bank": bank_dir_name,
                    "status": code,
                },
                lock=failure_lock,
            )

    def _publish_population() -> Dict[str, Any]:
        summary = population.summary()
        atomic_write_json(index_dir / "index-summary.json", summary)
        return summary

    # ─── Phase 2: parallel detail fetches ────────────────────────────────────

    if not pending:
        return _publish_population()

    def _fetch_one(work: _BankWork) -> bool:
        return _fetch_bank_detail(
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
        )

    def _detail_pass(
        items: List[_BankWork],
    ) -> Tuple[List[_BankWork], List[_BankWork], List[_BankWork]]:
        """Return ``(deferred, failed, crashed)`` without terminal writes.

        Raw attempts remain in the attempt journal. Only the bounded recovery
        decision below promotes failures into terminal ingest evidence.
        """
        deferred: List[_BankWork] = []
        failed: List[_BankWork] = []
        crashed: List[_BankWork] = []
        outcome_lock = threading.Lock()
        n_workers = min(detail_workers, len(items))
        log(
            f"[banks] {bank_dir_name}: fetching {len(items)} product details "
            f"({n_workers} concurrent)",
        )

        def _do(work: _BankWork) -> None:
            # A product whose detail was already prefetched in Phase 1 is written even
            # when the breaker is open — don't discard an already-successful fetch
            # (Codex). The open-circuit skip applies only to work that still needs a
            # network fetch. File I/O stays OUTSIDE the breaker lock (Gemini).
            needs_fetch = work.prefetched is None
            if needs_fetch and breaker.is_open():
                with outcome_lock:
                    deferred.append(work)
                return
            ok = _fetch_one(work)
            with outcome_lock:
                population.mark_detail(work.pid, ok)
                if not ok:
                    failed.append(work)
            # Only true network fetches feed the breaker; a Phase-1 prefetched result
            # was already counted in classify_product_for_ingest.
            if needs_fetch and breaker.record(ok):  # log() runs outside the breaker lock
                failures, attempts = breaker.snapshot()
                log(
                    f"[banks] {bank_dir_name}: circuit opened "
                    f"({failures}/{attempts} detail fetches failed) — deferring remaining details"
                )

        if n_workers <= 1:
            for w in items:
                _do(w)
        else:
            with ThreadPoolExecutor(max_workers=n_workers) as pool:
                futures = {pool.submit(_do, w): w.pid for w in items}
                done = 0
                for fut in as_completed(futures):
                    done += 1
                    try:
                        fut.result()
                    except Exception as exc:
                        log(f"[banks] {bank_dir_name}: detail error for {futures[fut]}: {exc}")
                        work = next(item for item in items if item.pid == futures[fut])
                        with outcome_lock:
                            population.mark_detail(work.pid, False)
                            crashed.append(work)
                    if done % 50 == 0:
                        log(f"[banks] {bank_dir_name}: {done}/{len(items)} details done")
        return deferred, failed, crashed

    def _write_off(items: List[_BankWork], status: str) -> None:
        unique = {work.pid: work for work in items}
        for work in sorted(unique.values(), key=lambda item: item.pid):
            population.mark_detail(work.pid, False)
            append_failure(
                date_root,
                {
                    "phase": "product_detail",
                    "bank": bank_dir_name,
                    "product_id": work.pid,
                    "status": status,
                },
                lock=failure_lock,
            )

    deferred, failed, crashed = _detail_pass(pending)
    recovery = sorted(
        {work.pid: work for work in [*failed, *deferred]}.values(),
        key=lambda work: work.pid,
    )
    if breaker.is_open() and recovery:
        # One bounded recovery attempt. A single probe decides it: a holder that
        # is still down costs one request, while a holder whose outage has passed
        # gets both failed and deferred work back instead of losing the day.
        log(
            f"[banks] {bank_dir_name}: {len(recovery)} details need bounded recovery; open "
            f"circuit; probing once in {BREAKER_RECOVERY_DELAY_SECONDS:g}s"
        )
        time.sleep(BREAKER_RECOVERY_DELAY_SECONDS)
        probe, rest = recovery[0], recovery[1:]
        probe_ok = _fetch_one(probe)
        population.mark_detail(probe.pid, probe_ok)
        if not probe_ok:
            log(f"[banks] {bank_dir_name}: recovery probe failed — holder still unhealthy")
            _write_off(recovery, "holder_unavailable")
        else:
            breaker.reset()
            log(f"[banks] {bank_dir_name}: recovery probe succeeded — retrying failed and deferred details")
            if rest:
                retry_deferred, retry_failed, retry_crashed = _detail_pass(rest)
                _write_off(
                    [*retry_failed, *retry_deferred],
                    "circuit_open_after_recovery",
                )
                _write_off(retry_crashed, "worker_crash")
    else:
        _write_off([*failed, *deferred], "detail_fetch_failed")
    _write_off(crashed, "worker_crash")

    return _publish_population()


# ─── CLI ──────────────────────────────────────────────────────────────────────

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
    coverage_complete = True
    for brand, bdir in bank_work:
        failures = int(by_provider.get(bdir) or 0)
        summary_path = banks_root / "_holders" / bdir / "_products-index" / "index-summary.json"
        try:
            population = json.loads(summary_path.read_text(encoding="utf-8"))
            if (
                not isinstance(population, dict)
                or population.get("schema_version") != 1
                or population.get("provider_uid") != brand["provider_uid"]
            ):
                raise ValueError("invalid holder population summary")
            state = str(population.get("state") or "failed")
            if state not in {"complete", "empty", "partial", "failed"}:
                raise ValueError("invalid holder state")
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            population = {}
            state = "failed"
            coverage_complete = False
        if failures and state in {"complete", "empty"}:
            state = "partial"
        provider_states.append(
            {
                "provider_uid": brand["provider_uid"],
                "identity_status": brand["provider_identity_status"],
                "data_holder_id": brand.get("data_holder_id") or None,
                "data_holder_brand_id": brand.get("data_holder_brand_id") or None,
                "interim_id": brand.get("interim_id") or None,
                "brand_name": brand.get("brand_name") or None,
                "legal_entity_name": brand.get("legal_entity_name") or None,
                "endpoint_url": brand.get("endpoint_url") or None,
                "state": state,
                "failure_records": failures,
                "population_known": bool(population.get("population_known")),
                # Product accounting covers the three datasets this ingest owns,
                # not unrelated products merely present in a holder catalogue.
                "products_discovered": population.get("relevant_products"),
                "products_indexed": population.get("unique_product_ids"),
                "details_present": population.get("details_present"),
            }
        )
    # Registered means selected into this observation. Keep the wider register
    # population as context so filtered diagnostic runs still reconcile exactly.
    status["providers_registered"] = len(bank_work)
    status["providers_available"] = snapshot.banking_count_before_filter
    status["providers_attempted"] = len(bank_work)
    status["provider_states"] = provider_states
    status["coverage_evidence_complete"] = coverage_complete
    status["provider_state_counts"] = {
        state: sum(1 for provider in provider_states if provider["state"] == state)
        for state in ("complete", "empty", "partial", "failed")
    }
    status["incomplete"] = bool(
        status["incomplete"]
        or not coverage_complete
        or any(provider["state"] not in {"complete", "empty"} for provider in provider_states)
    )
    attempt_summary = attempt_journal.summary()
    attempt_summary["path"] = attempt_journal.root.relative_to(run_root).as_posix()
    attempt_summary["path_resolution"] = "relative_to_ingest_run_root"
    attempt_summary["retention"] = "follows_ingest_run_root"
    status["raw_attempt_journal"] = attempt_summary
    atomic_write_json(banks_root / "ingest-status.json", status)
    return status

def _run_date(value: str) -> str:
    try:
        parsed = calendar_date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("run date must be YYYY-MM-DD") from error
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("run date must be YYYY-MM-DD")
    return value


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
        type=_run_date,
        default=None,
        help="Run folder YYYY-MM-DD (default: Australia/Hobart today)",
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

    run_date = args.date or datetime.now(timezone.utc).astimezone(
        DAILY_INGEST_TZ
    ).date().isoformat()
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

    def do_banks() -> None:
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

        def run_one(item: Tuple[Dict[str, str], str]) -> None:
            brand, bdir = item
            log_ts(f"[banks] Ingesting {bdir} ({brand['endpoint_url']})")
            try:
                ingest_brand(
                    brand,
                    date_root=banks_root,
                    resume=args.resume,
                    sleep_ms=args.sleep_ms,
                    timeout=args.timeout,
                    max_retries=args.max_retries,
                    max_pages=args.max_pages,
                    max_products=args.max_products,
                    fetch_unknown_detail=args.fetch_unknown_detail,
                    bank_dir_name=bdir,
                    detail_workers=detail_workers,
                    log=log_ts,
                    failure_lock=failure_lock,
                    attempt_journal=attempt_journal,
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

    do_banks()
    status = _persist_ingest_status(
        banks_root=banks_root,
        run_root=run_root,
        snapshot=snap,
        bank_work=bank_work,
        attempt_journal=attempt_journal,
    )
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
