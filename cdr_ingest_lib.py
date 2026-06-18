"""Orchestration for banking holder workers invoked from ``cdr_full_ingest.py``."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, Optional, Set, Tuple

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


# ─── Per-holder version cache ─────────────────────────────────────────────────

def _version_list(preferred: Optional[int]) -> Optional[List[int]]:
    """Try a holder's known-good x-v first; fetch_cdr_json still falls back through
    the rest of CDR_VERSION_ORDER if it stops working, so this is a hint not a
    lock-in. None means "negotiate from the top" (version not yet known)."""
    return [preferred] if preferred is not None else None


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
) -> bool:
    """Write product-detail.json for one bank product (called from thread pool).

    Returns True when the detail was fetched and written, False on failure, so the
    caller's per-holder circuit breaker can track the failure rate.
    """
    pid, leaf, prefetched = work
    detail_path = leaf / "product-detail.json"

    if prefetched is not None:
        res = prefetched
    else:
        time.sleep(sleep_ms / 1000.0)
        url = f"{safe_url(endpoint_url)}/{urllib.parse.quote(pid, safe='')}"
        res = fetch_cdr_json(
            url, versions=_version_list(preferred_version),
            timeout=timeout, max_retries=max_retries, sleep_ms=sleep_ms,
        )

    parsed = res.data
    if res.ok and parsed is not None and not has_cdr_errors(parsed):
        detail_path.write_text(res.text, encoding="utf-8")
        return True
    append_failure(
        date_root,
        {
            "phase": "product_detail",
            "bank": bank_dir_name,
            "product_id": pid,
            "status": res.status,
            "snippet": (res.text or "")[:500],
        },
        lock=failure_lock,
    )
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
        versions=_version_list(preferred_version),
        timeout=timeout,
        max_retries=max_retries,
        sleep_ms=sleep_ms,
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
            break
        visited.add(url)
        pages += 1
        if max_pages is not None and pages > max_pages:
            log(f"max-pages reached for {bank_dir_name}")
            break

        time.sleep(sleep_ms / 1000.0)
        res = fetch_cdr_json(
            url, versions=_version_list(preferred_version),
            timeout=timeout, max_retries=max_retries, sleep_ms=sleep_ms,
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
                    "status": res.status,
                    "snippet": (res.text or "")[:500],
                },
                lock=failure_lock,
            )
            break

        if res.version is not None:
            preferred_version = res.version

        for product in extract_products(parsed):
            if max_products is not None and products_seen >= max_products:
                log(f"max-products reached for {bank_dir_name}")
                capped = True
                break
            products_seen += 1

            if not is_record(product):
                continue

            pid = pick_text(product, ["productId", "id"])
            if not pid:
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
            )
            if ds not in DATASET_TO_FOLDER:
                continue

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
                continue

            pending.append(_BankWork(pid=pid, leaf=leaf, prefetched=prefetched))

        url = next_link(parsed, url)

    # ─── Phase 2: parallel detail fetches ────────────────────────────────────

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
        ok = _fetch_bank_detail(
            work,
            endpoint_url,
            timeout=timeout,
            max_retries=max_retries,
            sleep_ms=sleep_ms,
            date_root=date_root,
            bank_dir_name=bank_dir_name,
            failure_lock=failure_lock,
            preferred_version=preferred_version,
        )
        # Only true network fetches feed the breaker; a Phase-1 prefetched result
        # was already counted in classify_product_for_ingest.
        if needs_fetch and breaker.record(ok):  # log() runs outside the breaker lock
            failures, attempts = breaker.snapshot()
            log(
                f"[banks] {bank_dir_name}: circuit opened "
                f"({failures}/{attempts} detail fetches failed) — skipping remaining details"
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
                    log(f"[banks] {bank_dir_name}: detail error for {futures[fut]}: {exc}")
                if done % 50 == 0:
                    log(f"[banks] {bank_dir_name}: {done}/{len(pending)} details done")


# ─── CLI ──────────────────────────────────────────────────────────────────────

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

    snap = collect_register_snapshot(
        timeout=args.timeout,
        max_retries=args.max_retries,
        sleep_ms=args.sleep_ms,
        holders_filter=args.holders,
    )

    log(
        f"Banking holders: {len(snap.banking_brands)} after filter "
        f"({snap.banking_count_before_filter} before --holders)",
    )

    if not snap.register_ok:
        if args.allow_empty_holders:
            log("WARNING: CDR register discovery failed (--allow-empty-holders); exiting 0.")
            return 0
        log("ERROR: CDR register discovery failed.")
        return 2

    run_banks = len(snap.banking_brands) > 0

    if not run_banks:
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
        seen_dirs: Set[str] = set()
        bank_work: List[Tuple[Dict[str, str], str]] = []
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

    # Expose an ingest-status rollup so the daily run / monitoring can tell a
    # complete run from one where holders, products, or a tripped circuit breaker
    # left gaps — without parsing failures.jsonl line by line.
    status = summarize_failures(banks_root)
    (banks_root / "ingest-status.json").write_text(
        json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8"
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
