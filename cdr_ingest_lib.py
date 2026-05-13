"""Orchestration: banking + energy holder workers (invoked from ``cdr_full_ingest.py``)."""

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
    extract_energy_plans,
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
)


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
) -> None:
    """Write product-detail.json for one bank product (called from thread pool)."""
    pid, leaf, prefetched = work
    detail_path = leaf / "product-detail.json"

    if prefetched is not None:
        res = prefetched
    else:
        time.sleep(sleep_ms / 1000.0)
        url = f"{safe_url(endpoint_url)}/{urllib.parse.quote(pid, safe='')}"
        res = fetch_cdr_json(url, timeout=timeout, max_retries=max_retries, sleep_ms=sleep_ms)

    parsed = res.data
    if res.ok and parsed is not None and not has_cdr_errors(parsed):
        detail_path.write_text(res.text, encoding="utf-8")
    else:
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


def classify_product_for_ingest(
    product: Mapping[str, Any],
    *,
    fetch_unknown_detail: bool,
    endpoint_url: str,
    timeout: float,
    max_retries: int,
    sleep_ms: int,
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

    detail_url = f"{safe_url(endpoint_url)}/{urllib.parse.quote(pid, safe='')}"
    time.sleep(sleep_ms / 1000.0)
    detail_res = fetch_cdr_json(
        detail_url,
        timeout=timeout,
        max_retries=max_retries,
        sleep_ms=sleep_ms,
    )
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

    while url and not capped:
        if url in visited:
            break
        visited.add(url)
        pages += 1
        if max_pages is not None and pages > max_pages:
            log(f"max-pages reached for {bank_dir_name}")
            break

        time.sleep(sleep_ms / 1000.0)
        res = fetch_cdr_json(url, timeout=timeout, max_retries=max_retries, sleep_ms=sleep_ms)
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
        _fetch_bank_detail(
            work,
            endpoint_url,
            timeout=timeout,
            max_retries=max_retries,
            sleep_ms=sleep_ms,
            date_root=date_root,
            bank_dir_name=bank_dir_name,
            failure_lock=failure_lock,
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


# ─── Energy detail work unit ──────────────────────────────────────────────────

class _EnergyWork(NamedTuple):
    pid: str
    leaf: Path
    list_row: Optional[Dict[str, Any]]  # non-None in lite mode → write directly


def _fetch_energy_plan(
    work: _EnergyWork,
    endpoint_url: str,
    *,
    timeout: float,
    max_retries: int,
    sleep_ms: int,
    date_root: Path,
    provider_dir_name: str,
    failure_lock: Optional[threading.Lock],
) -> None:
    """Write plan-detail.json for one energy plan (called from thread pool)."""
    pid, leaf, list_row = work
    detail_path = leaf / "plan-detail.json"

    if list_row is not None:
        # Lite mode: persist the list row directly (no network call).
        envelope = {"data": list_row}
        detail_path.write_text(
            json.dumps(envelope, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        return

    time.sleep(sleep_ms / 1000.0)
    url = f"{safe_url(endpoint_url)}/{urllib.parse.quote(pid, safe='')}"
    res = fetch_cdr_json(url, timeout=timeout, max_retries=max_retries, sleep_ms=sleep_ms)
    parsed = res.data
    if res.ok and parsed is not None and not has_cdr_errors(parsed):
        detail_path.write_text(res.text, encoding="utf-8")
    else:
        append_failure(
            date_root,
            {
                "phase": "energy_plan_detail",
                "provider": provider_dir_name,
                "plan_id": pid,
                "status": res.status,
                "snippet": (res.text or "")[:500],
            },
            lock=failure_lock,
        )
        (leaf / "plan-detail.error.txt").write_text(res.text or "", encoding="utf-8")


def ingest_energy_brand(
    brand: Dict[str, str],
    *,
    date_root: Path,
    resume: bool,
    sleep_ms: int,
    timeout: float,
    max_retries: int,
    max_pages: Optional[int],
    max_products: Optional[int],
    energy_lite: bool,
    detail_workers: int,
    provider_dir_name: str,
    log: Callable[[str], None],
    failure_lock: Optional[threading.Lock] = None,
) -> None:
    """Ingest one energy retailer's generic plans.

    When ``energy_lite`` is True each list row is written directly (no per-plan
    GET).  Default is False — per-plan detail is fetched so that
    ``customerType``, ``pricingModel``, and ``solarFeedInTariff`` are available
    for taxonomy classification and export.

    Phase 1 (serial): walk paginated plans index, build work list.
    Phase 2 (parallel): write or fetch each plan detail concurrently.
    """
    endpoint_url = brand["endpoint_url"]
    holders_root = date_root / "_holders" / provider_dir_name
    holders_root.mkdir(parents=True, exist_ok=True)

    meta_path = holders_root / "_register-brand.json"
    if not meta_path.exists():
        meta_path.write_text(json.dumps(brand, indent=2, ensure_ascii=False), encoding="utf-8")

    index_dir = holders_root / "_plans-index"
    index_dir.mkdir(parents=True, exist_ok=True)

    # ─── Phase 1: collect all pages ───────────────────────────────────────────

    pending: List[_EnergyWork] = []
    url: Optional[str] = endpoint_url
    visited: Set[str] = set()
    pages = 0
    plans_seen = 0
    capped = False

    while url and not capped:
        if url in visited:
            break
        visited.add(url)
        pages += 1
        if max_pages is not None and pages > max_pages:
            log(f"max-pages reached for {provider_dir_name}")
            break

        time.sleep(sleep_ms / 1000.0)
        res = fetch_cdr_json(url, timeout=timeout, max_retries=max_retries, sleep_ms=sleep_ms)
        page_file = index_dir / f"page-{pages:04d}.json"
        page_file.write_text(res.text, encoding="utf-8")

        parsed = res.data
        if not res.ok or parsed is None or has_cdr_errors(parsed):
            append_failure(
                date_root,
                {
                    "phase": "energy_plans_index",
                    "provider": provider_dir_name,
                    "url": url,
                    "status": res.status,
                    "snippet": (res.text or "")[:500],
                },
                lock=failure_lock,
            )
            break

        for plan in extract_energy_plans(parsed):
            if max_products is not None and plans_seen >= max_products:
                log(f"max-products reached for {provider_dir_name}")
                capped = True
                break
            plans_seen += 1

            if not is_record(plan):
                continue

            pid = pick_text(plan, ["planId", "id"])
            if not pid:
                continue

            pname = sanitize_path_component(
                pick_text(plan, ["displayName", "name", "planName", "brandName"]) or "_unnamed"
            )
            id_dir = filesystem_product_id_directory(pid)
            leaf = date_root / provider_dir_name / pname / id_dir
            leaf.mkdir(parents=True, exist_ok=True)

            id_file = leaf / "plan-id.txt"
            if not id_file.exists():
                id_file.write_text(pid + "\n", encoding="utf-8")

            detail_path = leaf / "plan-detail.json"
            if resume and detail_path.exists() and detail_path.stat().st_size > 0:
                continue

            # In lite mode pass the list row so the worker writes it directly.
            pending.append(_EnergyWork(
                pid=pid,
                leaf=leaf,
                list_row=plan if energy_lite else None,
            ))

        log(
            f"[energy] {provider_dir_name}: index page {pages} done "
            f"({len(extract_energy_plans(parsed))} plans on page; {plans_seen} seen so far)",
        )
        url = next_link(parsed, url)

    # ─── Phase 2: parallel detail writes / fetches ───────────────────────────

    if not pending:
        log(f"[energy] {provider_dir_name}: nothing to write (all resumed or empty)")
        return

    mode_label = "plans stored (index-only)" if energy_lite else "plan-detail fetches"
    n_workers = 1 if energy_lite else min(detail_workers, len(pending))
    log(
        f"[energy] {provider_dir_name}: {len(pending)} {mode_label} "
        f"({n_workers} concurrent)",
    )

    def _do(work: _EnergyWork) -> None:
        _fetch_energy_plan(
            work,
            endpoint_url,
            timeout=timeout,
            max_retries=max_retries,
            sleep_ms=sleep_ms,
            date_root=date_root,
            provider_dir_name=provider_dir_name,
            failure_lock=failure_lock,
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
                    log(f"[energy] {provider_dir_name}: detail error for {futures[fut]}: {exc}")
                if done % 50 == 0:
                    log(f"[energy] {provider_dir_name}: {done}/{len(pending)} done")

    log(
        f"[energy] {provider_dir_name}: complete "
        f"({len(pending)} {mode_label}, {plans_seen} index rows seen)"
        + ("; capped by --max-products" if capped else ""),
    )


# ─── CLI ──────────────────────────────────────────────────────────────────────

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    here = Path(__file__).resolve().parent
    default_out = here / "runs"

    p = argparse.ArgumentParser(
        description="Standalone Australian CDR PRD ingest (banking products + energy plans).",
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
    p.add_argument("--no-banks", action="store_true", help="Skip banking sector")
    p.add_argument("--no-energy", action="store_true", help="Skip energy sector")
    p.add_argument(
        "--resume",
        action="store_true",
        help="Skip existing non-empty product-detail.json / plan-detail.json files",
    )
    p.add_argument(
        "--sleep-ms",
        type=int,
        default=40,
        help="Delay per HTTP call per worker thread (milliseconds, default 40)",
    )
    p.add_argument("--timeout", type=float, default=60.0, help="Per-request timeout seconds")
    p.add_argument("--max-retries", type=int, default=3, help="Retries on 429/5xx")
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
            "Exit 0 when register discovery fails, no holders match filters, or a requested sector "
            "has nothing to ingest (for automation during outages / empty register)"
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
    p.add_argument(
        "--energy-lite",
        action="store_true",
        help=(
            "Energy: store only the plan list row, skip per-plan detail GET. "
            "Much faster but omits customerType, pricingModel, tariffs, and solar fields."
        ),
    )
    # Backwards-compat alias — was the flag to opt INTO detail; now detail is the default.
    p.add_argument("--energy-full-detail", action="store_true", help=argparse.SUPPRESS)
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    run_date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_root: Path = args.out.expanduser().resolve()
    run_root = out_root / run_date
    banks_root = run_root / "banks"
    energy_root = run_root / "energy"

    def log(msg: str) -> None:
        print(msg, file=sys.stderr)

    want_banks = not args.no_banks
    want_energy = not args.no_energy
    if not want_banks and not want_energy:
        log("ERROR: specify at least one sector (remove --no-banks / --no-energy).")
        return 2

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

    if want_banks:
        log(
            f"Banking holders: {len(snap.banking_brands)} after filter "
            f"({snap.banking_count_before_filter} before --holders)",
        )
    if want_energy:
        log(
            f"Energy retailers: {len(snap.energy_brands)} after filter "
            f"({snap.energy_count_before_filter} before --holders)",
        )

    if not snap.register_ok:
        if args.allow_empty_holders:
            log("WARNING: CDR register discovery failed (--allow-empty-holders); exiting 0.")
            return 0
        log("ERROR: CDR register discovery failed.")
        return 2

    run_banks = want_banks and len(snap.banking_brands) > 0
    run_energy = want_energy and len(snap.energy_brands) > 0

    if want_banks and not run_banks:
        if args.allow_empty_holders:
            log("WARNING: no banking holders to ingest; skipping banks/.")
        else:
            if snap.banking_count_before_filter == 0:
                log("ERROR: register returned zero banking PRD brands.")
                return 2
            if args.holders:
                log(f"ERROR: no banking holders matched --holders {args.holders!r}.")
                return 1
            log("ERROR: register contained no banking PRD brands.")
            return 2

    if want_energy and not run_energy:
        if args.allow_empty_holders:
            log("WARNING: no energy retailers to ingest; skipping energy/.")
        elif not want_banks:
            if snap.energy_count_before_filter == 0:
                log("ERROR: register returned zero energy PRD brands.")
                return 2
            if args.holders:
                log(f"ERROR: no energy retailers matched --holders {args.holders!r}.")
                return 1
            log("ERROR: no energy PRD brands.")
            return 2
        else:
            if snap.energy_count_before_filter == 0:
                log(
                    "ERROR: energy ingest enabled but register returned zero energy PRD brands "
                    "(use --no-energy for banking-only, or --allow-empty-holders to skip).",
                )
                return 2
            if args.holders:
                log(f"ERROR: no energy retailers matched --holders {args.holders!r}.")
                return 1
            log("ERROR: no energy PRD brands.")
            return 2

    if not run_banks and not run_energy:
        if args.allow_empty_holders:
            log("WARNING: nothing to ingest (--allow-empty-holders); exiting 0.")
            return 0
        log("ERROR: no holders to ingest for enabled sector(s).")
        return 2

    workers = args.workers
    detail_workers = args.detail_workers
    energy_lite = bool(args.energy_lite)  # default False — full detail

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

    def do_energy() -> None:
        energy_root.mkdir(parents=True, exist_ok=True)
        seen_prov: Set[str] = set()
        energy_work: List[Tuple[Dict[str, str], str]] = []
        for brand in snap.energy_brands:
            pdir = allocate_bank_dir(
                brand["brand_name"],
                brand["legal_entity_name"],
                brand["endpoint_url"],
                seen_prov,
            )
            energy_work.append((brand, pdir))

        log_ts(
            f"Starting energy ingest: {len(energy_work)} retailers, "
            f"--workers {workers}, --detail-workers {detail_workers}"
            + (" (lite mode — no per-plan GET)" if energy_lite else ""),
        )

        def run_one(item: Tuple[Dict[str, str], str]) -> None:
            brand, pdir = item
            log_ts(f"[energy] Ingesting {pdir} ({brand['endpoint_url']})")
            ingest_energy_brand(
                brand,
                date_root=energy_root,
                resume=args.resume,
                sleep_ms=args.sleep_ms,
                timeout=args.timeout,
                max_retries=args.max_retries,
                max_pages=args.max_pages,
                max_products=args.max_products,
                energy_lite=energy_lite,
                detail_workers=detail_workers,
                provider_dir_name=pdir,
                log=log_ts,
                failure_lock=failure_lock,
            )

        if workers == 1:
            for item in energy_work:
                run_one(item)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = {pool.submit(run_one, item): item[1] for item in energy_work}
                for fut in as_completed(futs):
                    try:
                        fut.result()
                    except Exception as exc:
                        log_ts(f"ERROR: energy ingest for {futs[fut]} failed: {exc}")

    # ─── Run both sectors; if both are enabled, run them concurrently ─────────

    if run_banks and run_energy:
        with ThreadPoolExecutor(max_workers=2) as sector_pool:
            sector_futs = {
                sector_pool.submit(do_banks): "banks",
                sector_pool.submit(do_energy): "energy",
            }
            for fut in as_completed(sector_futs):
                try:
                    fut.result()
                except Exception as exc:
                    log_ts(f"ERROR: {sector_futs[fut]} sector failed: {exc}")
    elif run_banks:
        do_banks()
    elif run_energy:
        do_energy()

    log("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
