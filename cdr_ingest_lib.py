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
from typing import Any, Callable, Dict, List, Mapping, Optional, Set, Tuple

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
    log: Callable[[str], None],
    failure_lock: Optional[threading.Lock] = None,
) -> None:
    endpoint_url = brand["endpoint_url"]
    # Holder-level artifacts live beside Mortgage/Savings/TD so the product tree matches the plan.
    holders_root = date_root / "_holders" / bank_dir_name
    holders_root.mkdir(parents=True, exist_ok=True)

    meta_path = holders_root / "_register-brand.json"
    if not meta_path.exists():
        meta_path.write_text(json.dumps(brand, indent=2, ensure_ascii=False), encoding="utf-8")

    index_dir = holders_root / "_products-index"
    index_dir.mkdir(parents=True, exist_ok=True)

    url: Optional[str] = endpoint_url
    visited: Set[str] = set()
    pages = 0
    products_seen = 0

    while url:
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

        products = extract_products(parsed)
        for product in products:
            if max_products is not None and products_seen >= max_products:
                log(f"max-products reached for {bank_dir_name}")
                return
            products_seen += 1

            if not is_record(product):
                continue

            pid = pick_text(product, ["productId", "id"])
            if not pid:
                continue

            ds, prefetched_detail = classify_product_for_ingest(
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

            if prefetched_detail is not None:
                detail_res = prefetched_detail
            else:
                time.sleep(sleep_ms / 1000.0)
                detail_url = f"{safe_url(endpoint_url)}/{urllib.parse.quote(pid, safe='')}"
                detail_res = fetch_cdr_json(
                    detail_url,
                    timeout=timeout,
                    max_retries=max_retries,
                    sleep_ms=sleep_ms,
                )

            parsed_detail = detail_res.data
            ok = (
                detail_res.ok
                and parsed_detail is not None
                and not has_cdr_errors(parsed_detail)
            )
            if ok:
                detail_path.write_text(detail_res.text, encoding="utf-8")
            else:
                append_failure(
                    date_root,
                    {
                        "phase": "product_detail",
                        "bank": bank_dir_name,
                        "product_id": pid,
                        "dataset": folder,
                        "status": detail_res.status,
                        "snippet": (detail_res.text or "")[:500],
                    },
                    lock=failure_lock,
                )
                err_path = leaf / "product-detail.error.txt"
                err_path.write_text(detail_res.text or "", encoding="utf-8")

        nxt = next_link(parsed, url)
        url = nxt


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
    provider_dir_name: str,
    log: Callable[[str], None],
    failure_lock: Optional[threading.Lock] = None,
) -> None:
    """Ingest one energy retailer's generic plans (CDS ``.../energy/plans``)."""
    endpoint_url = brand["endpoint_url"]
    holders_root = date_root / "_holders" / provider_dir_name
    holders_root.mkdir(parents=True, exist_ok=True)

    meta_path = holders_root / "_register-brand.json"
    if not meta_path.exists():
        meta_path.write_text(json.dumps(brand, indent=2, ensure_ascii=False), encoding="utf-8")

    index_dir = holders_root / "_plans-index"
    index_dir.mkdir(parents=True, exist_ok=True)

    url: Optional[str] = endpoint_url
    visited: Set[str] = set()
    pages = 0
    plans_seen = 0

    while url:
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

        plans = extract_energy_plans(parsed)
        for plan in plans:
            if max_products is not None and plans_seen >= max_products:
                log(f"max-products reached for {provider_dir_name}")
                return
            plans_seen += 1

            if not is_record(plan):
                continue

            pid = pick_text(plan, ["planId", "id"])
            if not pid:
                continue

            pname = sanitize_path_component(
                pick_text(
                    plan,
                    ["displayName", "name", "planName", "brandName"],
                )
                or "_unnamed"
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

            time.sleep(sleep_ms / 1000.0)
            detail_url = f"{safe_url(endpoint_url)}/{urllib.parse.quote(pid, safe='')}"
            detail_res = fetch_cdr_json(
                detail_url,
                timeout=timeout,
                max_retries=max_retries,
                sleep_ms=sleep_ms,
            )

            parsed_detail = detail_res.data
            ok = (
                detail_res.ok
                and parsed_detail is not None
                and not has_cdr_errors(parsed_detail)
            )
            if ok:
                detail_path.write_text(detail_res.text, encoding="utf-8")
            else:
                append_failure(
                    date_root,
                    {
                        "phase": "energy_plan_detail",
                        "provider": provider_dir_name,
                        "plan_id": pid,
                        "status": detail_res.status,
                        "snippet": (detail_res.text or "")[:500],
                    },
                    lock=failure_lock,
                )
                err_path = leaf / "plan-detail.error.txt"
                err_path.write_text(detail_res.text or "", encoding="utf-8")

        nxt = next_link(parsed, url)
        url = nxt


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
    p.add_argument(
        "--no-banks",
        action="store_true",
        help="Skip banking sector (no banks/ tree)",
    )
    p.add_argument(
        "--no-energy",
        action="store_true",
        help="Skip energy sector (no energy/ tree)",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help="Skip existing banking product-detail.json or energy plan-detail.json when non-empty",
    )
    p.add_argument(
        "--sleep-ms",
        type=int,
        default=40,
        help="Delay between HTTP calls (milliseconds)",
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
    p.add_argument("--max-products", type=int, default=None, help="Cap products processed per holder")
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
        help="Parallel holder ingests (default: 8). Use 1 for strictly serial per-holder runs.",
    )
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    run_date = args.date
    if not run_date:
        run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

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

    log(f"Run folder: {run_root} (banks under banks/, energy under energy/)")
    run_root.mkdir(parents=True, exist_ok=True)

    if args.workers < 1:
        log("ERROR: --workers must be >= 1")
        return 2
    workers = args.workers

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
            log(
                "WARNING: CDR register discovery failed — no successful JSON payload from "
                "any register URL (--allow-empty-holders); exiting 0.",
            )
            return 0
        log(
            "ERROR: CDR register discovery failed — no successful JSON payload from "
            "any register URL (network outage, HTTP errors, or non-JSON body).",
        )
        return 2

    run_banks = want_banks and len(snap.banking_brands) > 0
    run_energy = want_energy and len(snap.energy_brands) > 0

    if want_banks and not run_banks:
        if args.allow_empty_holders:
            log("WARNING: no banking holders to ingest; skipping banks/.")
        else:
            if snap.banking_count_before_filter == 0:
                log(
                    "ERROR: register responded but extracted zero banking PRD brands "
                    "before applying --holders filter (not a filter miss).",
                )
                return 2
            if args.holders:
                log(
                    f"ERROR: no banking holders matched --holders {args.holders!r} "
                    "(register returned banking rows but none matched the filter).",
                )
                return 1
            log("ERROR: register contained no banking PRD brands to ingest.")
            return 2

    if want_energy and not run_energy:
        if args.allow_empty_holders:
            log("WARNING: no energy retailers to ingest; skipping energy/.")
        elif not want_banks:
            if snap.energy_count_before_filter == 0:
                log(
                    "ERROR: register contained zero energy PRD brands "
                    "before applying --holders filter.",
                )
                return 2
            if args.holders:
                log(
                    f"ERROR: no energy retailers matched --holders {args.holders!r} "
                    "(register returned energy rows but none matched the filter).",
                )
                return 1
            log("ERROR: no energy PRD brands to ingest.")
            return 2
        else:
            if snap.energy_count_before_filter == 0:
                log(
                    "ERROR: energy ingest is enabled but register contained zero energy PRD brands "
                    "before --holders (use --no-energy for banking-only, or --allow-empty-holders "
                    "to skip energy).",
                )
                return 2
            if args.holders:
                log(
                    f"ERROR: no energy retailers matched --holders {args.holders!r} "
                    "(register returned energy rows but none matched the filter).",
                )
                return 1
            log("ERROR: no energy PRD brands to ingest.")
            return 2

    if not run_banks and not run_energy:
        if args.allow_empty_holders:
            log("WARNING: nothing to ingest (--allow-empty-holders); exiting 0.")
            return 0
        log("ERROR: no holders to ingest for enabled sector(s).")
        return 2

    failure_lock = threading.Lock() if workers > 1 else None
    log_lock = threading.Lock() if workers > 1 else None

    def log_threadsafe(msg: str) -> None:
        if log_lock is not None:
            with log_lock:
                log(msg)
        else:
            log(msg)

    if run_banks:
        banks_root.mkdir(parents=True, exist_ok=True)
        seen_bank_dirs: Set[str] = set()
        bank_work: List[Tuple[Dict[str, str], str]] = []
        for brand in snap.banking_brands:
            bank_dir = allocate_bank_dir(
                brand["brand_name"],
                brand["legal_entity_name"],
                brand["endpoint_url"],
                seen_bank_dirs,
            )
            bank_work.append((brand, bank_dir))

        log(
            f"Starting banking ingest: {len(bank_work)} holders, "
            f"--workers {workers}",
        )

        def run_bank_holder(item: Tuple[Dict[str, str], str]) -> None:
            brand, bank_dir = item
            log_threadsafe(f"[banks] Ingesting {bank_dir} ({brand['endpoint_url']})")
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
                bank_dir_name=bank_dir,
                log=log_threadsafe,
                failure_lock=failure_lock,
            )

        if workers == 1:
            for item in bank_work:
                run_bank_holder(item)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                future_to_bank = {
                    pool.submit(run_bank_holder, item): item[1] for item in bank_work
                }
                for fut in as_completed(future_to_bank):
                    bank_name = future_to_bank[fut]
                    try:
                        fut.result()
                    except Exception as e:
                        log_threadsafe(
                            f"ERROR: Banking ingest for {bank_name} failed: {e}",
                        )

    if run_energy:
        energy_root.mkdir(parents=True, exist_ok=True)
        seen_prov: Set[str] = set()
        energy_work: List[Tuple[Dict[str, str], str]] = []
        for brand in snap.energy_brands:
            prov_dir = allocate_bank_dir(
                brand["brand_name"],
                brand["legal_entity_name"],
                brand["endpoint_url"],
                seen_prov,
            )
            energy_work.append((brand, prov_dir))

        log(
            f"Starting energy ingest: {len(energy_work)} retailers, "
            f"--workers {workers}",
        )

        def run_energy_holder(item: Tuple[Dict[str, str], str]) -> None:
            brand, prov_dir = item
            log_threadsafe(f"[energy] Ingesting {prov_dir} ({brand['endpoint_url']})")
            ingest_energy_brand(
                brand,
                date_root=energy_root,
                resume=args.resume,
                sleep_ms=args.sleep_ms,
                timeout=args.timeout,
                max_retries=args.max_retries,
                max_pages=args.max_pages,
                max_products=args.max_products,
                provider_dir_name=prov_dir,
                log=log_threadsafe,
                failure_lock=failure_lock,
            )

        if workers == 1:
            for item in energy_work:
                run_energy_holder(item)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                fut_map = {pool.submit(run_energy_holder, item): item[1] for item in energy_work}
                for fut in as_completed(fut_map):
                    name = fut_map[fut]
                    try:
                        fut.result()
                    except Exception as e:
                        log_threadsafe(
                            f"ERROR: Energy ingest for {name} failed: {e}",
                        )

    log("Done.")
    return 0
