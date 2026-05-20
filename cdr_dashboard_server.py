"""Cached local dashboard for generated CDR run artifacts."""

from __future__ import annotations

import argparse
from collections import OrderedDict
import errno
import gzip
import json
import mimetypes
import os
import re
import socket
import sys
from datetime import date as calendar_date, datetime, timezone
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

from ar_local_pi_runtime import latest_exports_root
from ar_local_ingest_schedule import DAILY_INGEST_SCHEDULE_LABEL, latest_daily_due_utc, next_daily_due_utc
from ar_local_sectors import energy_dormant
from cdr_ribbon_normalize import (
    extract_fixed_rate_term_years,
    normalize_rate_structure_group,
    normalize_td_rate_structure_group,
)

BASE_DIR = Path(__file__).resolve().parent
DASHBOARD_ROOT = BASE_DIR / "dashboard"
LATEST_EXPORTS_TTL_SECONDS = 5.0
MAX_ARTIFACT_CACHE_ENTRIES = 4
MAX_HISTORY_CACHE_ENTRIES = 8
DEFAULT_HISTORY_RUN_LIMIT = 90
# Columns dropped from the wire vs. earlier revisions: run_date and dataset (constant
# per response — the envelope already names both), rate_family (server now applies the
# section filter, so the client no longer needs it), comparison_rate (never rendered
# anywhere in the dashboard), taxonomy_path (only used by the energy panel which has
# its own endpoint), and brand_name/brand (not real columns — the legacy SELECT
# emitted them as '' and compact_bank_row stripped them anyway). The client hydrates
# dataset/rate_family per-row from the response section so existing filters and the
# history identity hash keep matching.
BANK_SECTION_COLUMNS = (
    "provider",
    "product_id",
    "product_key",
    "product_name",
    "rate",
    "rate_type",
    "application_type",
    "application_frequency",
    "repayment_type",
    "loan_purpose",
    "term",
    "ribbon_normalized",
    "security_purpose",
    "ribbon_repayment_type",
    "lvr_tier",
    "ribbon_rate_structure",
    "ribbon_fixed_term",
    "account_type",
    "ribbon_deposit_kind",
    "balance_min",
    "balance_max",
    "term_months",
    "interest_payment",
    "feature_set",
    "rate_index",
)
BANK_HISTORY_COLUMNS = (
    "run_date",
    # dataset and rate_family stay in the SELECT so canonicalize_history_row can
    # still key off dataset for Mortgage rows AND the unscoped /api/banks/history
    # endpoint (which mixes Mortgage/Savings/TD) keeps its row provenance. The
    # /api/banks/history/section path drops them post-canonicalise — see
    # read_bank_history_db below.
    "dataset",
    "rate_family",
    "provider",
    "product_id",
    "product_key",
    "product_name",
    "rate",
    "rate_type",
    "application_type",
    "application_frequency",
    "repayment_type",
    "loan_purpose",
    "term",
    "ribbon_normalized",
    "security_purpose",
    "ribbon_repayment_type",
    "lvr_tier",
    "ribbon_rate_structure",
    "ribbon_fixed_term",
    "account_type",
    "ribbon_deposit_kind",
    "balance_min",
    "balance_max",
    "term_months",
    "interest_payment",
    "feature_set",
)
VALID_BANK_SECTIONS = frozenset(("Mortgage", "Savings", "TD"))

# Banking dashboard SPA entry URLs (client app.js sectionToPath / sectionFromPathname).
# Must serve dashboard/index.html — not site_root/savings/ (a directory → 404).
DASHBOARD_BANKING_SECTION_PATHS = frozenset(
    (
        "/",
        "/savings",
        "/savings/",
        "/term-deposits",
        "/term-deposits/",
        "/home-loans",
        "/home-loans/",
    )
)

# Fields that uniquely identify a "rate row template" across run dates.
# When we carry-forward, two rows share an identity iff every field below
# matches; only run_date and the rate / comparison_rate values differ.
HISTORY_IDENTITY_FIELDS = (
    "dataset",
    "provider",
    "product_key",
    "product_id",
    "product_name",
    "rate_family",
    "rate_type",
    "term",
    "repayment_type",
    "loan_purpose",
    "application_type",
    "application_frequency",
    "security_purpose",
    "ribbon_repayment_type",
    "ribbon_rate_structure",
    "ribbon_fixed_term",
    "ribbon_deposit_kind",
    "lvr_tier",
    "balance_min",
    "balance_max",
    "term_months",
    "interest_payment",
    "feature_set",
    "account_type",
)

_RUN_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# gzip the dashboard's bulky JSON/JS/CSS responses on the wire. The Mortgage
# section payload is ~4 MB of JSON that crushes to ~80 KB; history is similar.
# Compressed bytes are stored alongside the raw bytes in each upstream cache
# (section_cache, history_cache, CachedFiles), so the lifetime of the gz
# matches the lifetime of the raw it was produced from — no separate
# fingerprint-keyed cache that could mis-serve when id() is reused.
GZIP_MIN_BYTES = 512
GZIP_LEVEL = 6
_GZIP_COMPRESSIBLE_PREFIXES = (
    "text/",
    "application/json",
    "application/javascript",
    "image/svg+xml",
)


def _content_type_is_compressible(ctype: str) -> bool:
    low = (ctype or "").lower()
    return any(low.startswith(prefix) for prefix in _GZIP_COMPRESSIBLE_PREFIXES)


def maybe_gzip(body: bytes, ctype: str) -> bytes | None:
    """Return gz-encoded body when it's worth compressing, else None."""
    if not body or len(body) < GZIP_MIN_BYTES or not _content_type_is_compressible(ctype):
        return None
    return gzip.compress(body, compresslevel=GZIP_LEVEL)


def _client_accepts_gzip(accept_encoding: str) -> bool:
    if not accept_encoding:
        return False
    for token in accept_encoding.split(","):
        name, _, params = token.strip().partition(";")
        if name.lower() != "gzip":
            continue
        for param in params.split(";"):
            key, _, value = param.strip().partition("=")
            if key.lower() == "q":
                try:
                    if float(value) == 0:
                        return False
                except ValueError:
                    # Malformed q-value — fall back to "accept" (we already know
                    # the token is "gzip"; a bad q shouldn't disable the encoding).
                    pass
        return True
    return False



ECONOMIC_API_UPSTREAM = os.environ.get("AR_ECONOMIC_API_UPSTREAM", "https://www.australianrates.com").rstrip("/")


class BadRequestError(Exception):
    """Client supplied invalid query parameters."""


def parse_run_date_param(raw: str) -> str:
    value = str(raw or "").strip()
    if not _RUN_DATE_RE.fullmatch(value):
        raise BadRequestError("date must be YYYY-MM-DD")
    try:
        calendar_date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError as exc:
        raise BadRequestError("date is not a valid calendar day") from exc
    return value


def parse_bank_section_param(raw: str) -> str:
    value = str(raw or "").strip()
    if value not in VALID_BANK_SECTIONS:
        raise BadRequestError("section must be one of Mortgage, Savings, TD")
    return value


def ingest_schedule_payload() -> bytes:
    now_utc = datetime.now(timezone.utc)
    last_due = latest_daily_due_utc(now_utc)
    next_due = next_daily_due_utc(now_utc)
    payload = {
        "now_utc": now_utc.isoformat(),
        "last_due_utc": last_due.isoformat(),
        "next_due_utc": next_due.isoformat(),
        "schedule": DAILY_INGEST_SCHEDULE_LABEL,
        "timezone": time.tzname[0] if time.tzname else "",
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def bank_rate_columns(con: sqlite3.Connection) -> set[str]:
    rows = con.execute("PRAGMA table_info(bank_rates)").fetchall()
    return {str(row[1]) for row in rows}


def bank_rate_select_list(available: set[str], columns: tuple[str, ...]) -> str:
    parts: list[str] = []
    for column in columns:
        if column in available:
            parts.append(column)
        else:
            parts.append(f"'' AS {column}")
    return ", ".join(parts)


def compact_bank_row(row: dict[str, object]) -> dict[str, object]:
    """Drop absent/empty fields before JSON encoding section chunks."""
    return {key: value for key, value in row.items() if value not in (None, "")}


def canonicalize_history_row(item: dict[str, object]) -> None:
    # Legacy run DBs stored verbose CDR text in ribbon_rate_structure and had no
    # ribbon_fixed_term column; today's ingest writes canonical 'variable'/'fixed'
    # plus a separate term. Realign legacy rows so historyIndexKey matches across
    # the ribbon's full retention window.
    raw_structure = str(item.get("ribbon_rate_structure") or "")
    dataset = str(item.get("dataset") or "")
    if dataset == "Mortgage":
        canonical = normalize_rate_structure_group(raw_structure)
        if canonical == "fixed" and not str(item.get("ribbon_fixed_term") or ""):
            years = extract_fixed_rate_term_years(raw_structure)
            if years:
                item["ribbon_fixed_term"] = years
        item["ribbon_rate_structure"] = canonical
    else:
        deposit_kind = str(item.get("ribbon_deposit_kind") or "")
        item["ribbon_rate_structure"] = normalize_td_rate_structure_group(raw_structure, deposit_kind)


def fill_history_gaps(
    rows: list[dict[str, object]],
    run_dates: list[str],
) -> tuple[list[dict[str, object]], int]:
    """Stabilize the ribbon aggregate against transient ingest gaps.

    For every distinct rate-row identity (provider + product + rate variant)
    we observe a series of (run_date, rate) samples. When the retained set
    contains a date that lies *between* a product's first and last observed
    appearance but the product has no sample on that date, we emit a
    synthetic carry-forward row using the most recent prior sample. This
    keeps the per-day product cohort stable: min/max/mean on a gap day are
    computed from the same set of products as adjacent days, so the ribbon
    does not jump just because one holder failed to respond.

    Carry-forward does NOT extend a product beyond its last observed date —
    a product that disappears for good (CDR delisting) drops out of the
    cohort from then on, which is the correct behaviour.

    Synthetic rows carry ``carry_forward = "1"`` so consumers can flag them.
    Returns ``(filled_rows, synthetic_count)``.
    """
    if not rows or not run_dates:
        return list(rows), 0
    sorted_dates = sorted({d for d in run_dates if d})

    by_identity: dict[tuple[str, ...], dict[str, dict[str, object]]] = {}
    for row in rows:
        identity = tuple(str(row.get(field) or "") for field in HISTORY_IDENTITY_FIELDS)
        date = str(row.get("run_date") or "")
        if not date:
            continue
        bucket = by_identity.setdefault(identity, {})
        # If a duplicate identity+date exists, prefer the first concrete row.
        if date not in bucket:
            bucket[date] = row

    out: list[dict[str, object]] = list(rows)
    synthetic = 0
    # Single moving pointer per identity: walk sorted_dates and the per-identity
    # present list in lockstep so each gap-fill is O(D) not O(D^2).
    for bucket in by_identity.values():
        present = sorted(bucket.keys())
        if len(present) < 2:
            continue  # No interior days possible.
        first, last = present[0], present[-1]
        # Index of the most recent present date <= the current walked date.
        prior_idx = -1
        for date in sorted_dates:
            if date <= first or date >= last:
                # Advance prior_idx so it stays valid once we cross `first`.
                while prior_idx + 1 < len(present) and present[prior_idx + 1] <= date:
                    prior_idx += 1
                continue
            # Advance prior_idx to the latest present date strictly < date.
            while prior_idx + 1 < len(present) and present[prior_idx + 1] < date:
                prior_idx += 1
            if prior_idx + 1 < len(present) and present[prior_idx + 1] == date:
                # date is already present — advance pointer past it for next iter.
                prior_idx += 1
                continue
            if prior_idx < 0:
                continue
            template = bucket[present[prior_idx]]
            synth = dict(template)
            synth["run_date"] = date
            synth["carry_forward"] = "1"
            out.append(synth)
            synthetic += 1
    return out, synthetic


def resolve_site_public_file(site_root: Path, url_path: str) -> Path:
    """Map a public-site URL path to a file under ``site_root`` (path traversal safe)."""
    path = url_path.split("?", 1)[0]
    if path in ("/economic-data", "/economic-data/"):
        target = (site_root / "economic-data" / "index.html").resolve()
    else:
        rel = path.lstrip("/")
        if not rel:
            raise FileNotFoundError(url_path)
        target = (site_root / rel).resolve()
    site_resolved = site_root.resolve()
    if site_resolved not in target.parents and target != site_resolved:
        raise FileNotFoundError(url_path)
    if not target.is_file():
        raise FileNotFoundError(url_path)
    return target


def proxy_upstream_get(upstream_base: str, path: str, query: Dict[str, list[str]]) -> Tuple[bytes, str]:
    upstream_path = path if path.startswith("/") else "/" + path
    qs = urlencode([(key, value) for key, values in query.items() for value in values], doseq=True)
    url = upstream_base + upstream_path + (("?" + qs) if qs else "")
    req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60.0) as resp:
            body = resp.read()
            ctype = resp.headers.get("Content-Type", "application/json")
            return body, ctype.split(";")[0] + ("; charset=utf-8" if "charset" not in ctype.lower() else "")
    except urllib.error.HTTPError as exc:
        body = exc.read()
        ctype = exc.headers.get("Content-Type", "application/json") if exc.headers else "application/json"
        raise ProxyUpstreamError(int(exc.code), body, ctype) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        payload = json.dumps(
            {
                "error": "economic_data_upstream_unavailable",
                "message": str(exc),
                "upstream": upstream_base,
            },
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        raise ProxyUpstreamError(HTTPStatus.BAD_GATEWAY, payload, "application/json; charset=utf-8") from exc


def is_economic_data_page_path(url_path: str) -> bool:
    path = url_path.split("?", 1)[0]
    return path == "/economic-data" or path == "/economic-data/" or path.startswith("/economic-data/")


def is_dashboard_banking_section_path(url_path: str) -> bool:
    """True when the URL should return the local CDR dashboard shell (index.html)."""
    return url_path.split("?", 1)[0] in DASHBOARD_BANKING_SECTION_PATHS


def inject_local_dashboard_css(html: bytes) -> bytes:
    """Append local dashboard overrides so /economic-data/ gets nav focus fixes."""
    if b"/assets/app.css" in html.lower():
        return html
    link = b'    <link rel="stylesheet" href="/assets/app.css">\n'
    patched, count = re.subn(
        br"</head>",
        link + br"</head>",
        html,
        count=1,
        flags=re.IGNORECASE,
    )
    return patched if count else html


class ProxyUpstreamError(Exception):
    def __init__(self, status: int, body: bytes, content_type: str) -> None:
        super().__init__(status)
        self.status = status
        self.body = body
        self.content_type = content_type


def resolve_site_root(explicit: Path | None) -> Path:
    """Locate AustralianRates public shell assets (foundation.css, theme.js, …)."""
    if explicit is not None:
        root = explicit.expanduser().resolve()
        marker = root / "foundation.css"
        if not marker.is_file():
            raise SystemExit(
                f"--site-root {root} is invalid: missing {marker.name}. "
                "Use the `site` folder from the AustralianRates repo."
            )
        return root
    candidates = [
        BASE_DIR / "site",
        BASE_DIR.parent / "australianrates" / "site",
        BASE_DIR.parent / "site",
    ]

    bank_icon_suffixes = (".png", ".webp", ".svg")

    def bank_icon_file_count(root: Path) -> int:
        banks = root / "assets" / "banks"
        if not banks.is_dir():
            return 0
        return sum(
            sum(1 for p in banks.glob(f"*{suf}") if p.is_file()) for suf in bank_icon_suffixes
        )

    resolved = [c.resolve() for c in candidates]
    with_banks = [r for r in resolved if (r / "foundation.css").is_file() and bank_icon_file_count(r) > 0]
    if with_banks:
        return with_banks[0]
    for root in resolved:
        if (root / "foundation.css").is_file():
            return root
    listed = ", ".join(str(c) for c in candidates)
    raise SystemExit(
        "Could not find AustralianRates site static files (foundation.css). "
        f"Tried: {listed}. Clone australianrates beside AR-local, copy its "
        "`site` folder into AR-local, or pass --site-root PATH_TO_SITE."
    )


class CachedFiles:
    def __init__(self, exports_root: Path):
        self.exports_root = exports_root.resolve()
        # (mtime, raw_bytes, gz_or_None). gz is computed lazily by gz_for() when
        # the response handler signals the content-type is compressible — keeps
        # binary assets (PNGs, woff2) from wasting CPU on pointless gzip.
        self.memory: Dict[Path, Tuple[float, bytes, bytes | None]] = {}

    def _entry(self, path: Path) -> Tuple[Path, float, bytes, bytes | None]:
        resolved = path.resolve()
        if self.exports_root not in resolved.parents and resolved != self.exports_root:
            raise FileNotFoundError(path)
        stat = resolved.stat()
        cached = self.memory.get(resolved)
        if cached and cached[0] == stat.st_mtime:
            return resolved, cached[0], cached[1], cached[2]
        data = resolved.read_bytes()
        self.memory[resolved] = (stat.st_mtime, data, None)
        return resolved, stat.st_mtime, data, None

    def read(self, path: Path) -> bytes:
        _, _, data, _ = self._entry(path)
        return data

    def gz_for(self, path: Path, ctype: str) -> bytes | None:
        """Return the precomputed gz for path, lazily compressing on first call."""
        resolved, mtime, data, gz = self._entry(path)
        if gz is not None:
            return gz
        gz = maybe_gzip(data, ctype)
        if gz is not None:
            self.memory[resolved] = (mtime, data, gz)
        return gz


class ExportResolver:
    def __init__(self, exports_value: str, runs_root: Path):
        self.exports_value = exports_value
        self.runs_root = runs_root.expanduser().resolve()
        self.fixed_root = (
            None if exports_value == "latest" else Path(exports_value).expanduser().resolve()
        )
        self.cached_root: Path | None = None
        self.cached_until = 0.0
        self.lock = threading.Lock()

    def root(self) -> Path:
        if self.fixed_root is not None:
            return self.fixed_root
        with self.lock:
            now = time.monotonic()
            if self.cached_root is not None and now < self.cached_until:
                return self.cached_root
            latest = latest_exports_root(self.runs_root)
            if latest is None:
                raise FileNotFoundError("latest exports")
            self.cached_root = latest
            self.cached_until = now + LATEST_EXPORTS_TTL_SECONDS
            return latest

    def root_for_date(self, run_date: str) -> Path:
        if self.fixed_root is not None:
            return self.fixed_root
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", run_date):
            candidate = self.runs_root / run_date / "_exports"
            if (candidate / "dashboard-cache" / run_date).is_dir():
                return candidate.resolve()
        return self.root()


class LocalDashboardServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        elif sys.platform.startswith("linux") and hasattr(socket, "SO_REUSEADDR"):
            # systemd manages mutual exclusion on the Pi; SO_REUSEADDR lets
            # a restart bind through the previous instance's TIME_WAIT.
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        super().server_bind()


def make_handler(export_resolver: ExportResolver, site_root: Path, preload: bool):
    bank_assets_root = site_root / "assets" / "banks"
    artifact_caches: Dict[Path, CachedFiles] = {}
    artifact_cache_lock = threading.Lock()
    dashboard_cache = CachedFiles(DASHBOARD_ROOT)
    site_cache = CachedFiles(site_root)
    # Each entry stores (raw_json, gz_json). gz is computed once at cache-insert
    # time and lives exactly as long as the raw — no cross-payload aliasing.
    history_cache: Dict[Tuple[str, str, Tuple[Tuple[str, float, int], ...]], Tuple[bytes, bytes | None]] = {}
    history_cache_lock = threading.Lock()
    section_cache: OrderedDict[Tuple[str, str, str, float, int], Tuple[bytes, bytes | None]] = OrderedDict()
    section_cache_lock = threading.Lock()

    def artifact_cache(exports_root: Path | None = None) -> Tuple[Path, CachedFiles]:
        exports_root = (exports_root or export_resolver.root()).resolve()
        with artifact_cache_lock:
            cached = artifact_caches.get(exports_root)
            if cached is not None:
                artifact_caches.pop(exports_root)
                artifact_caches[exports_root] = cached
                return exports_root, cached
            if len(artifact_caches) >= MAX_ARTIFACT_CACHE_ENTRIES:
                oldest_root = next(iter(artifact_caches))
                artifact_caches.pop(oldest_root)
            cached = CachedFiles(exports_root)
            artifact_caches[exports_root] = cached
            return exports_root, cached

    def bank_history_db_paths(max_run_date: str) -> list[Path]:
        if export_resolver.fixed_root is not None:
            candidate = export_resolver.fixed_root / "local-cdr.sqlite"
            return [candidate] if candidate.is_file() else []
        runs_root = export_resolver.runs_root
        if not runs_root.is_dir():
            return []
        dbs: list[Path] = []
        for child in sorted(runs_root.iterdir(), key=lambda p: p.name):
            if not child.is_dir() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", child.name):
                continue
            if max_run_date and child.name > max_run_date:
                continue
            candidate = child / "_exports" / "local-cdr.sqlite"
            if candidate.is_file():
                dbs.append(candidate.resolve())
        return dbs[-DEFAULT_HISTORY_RUN_LIMIT:]

    def bank_db_for_date(run_date: str) -> Path:
        exports_root = export_resolver.root_for_date(run_date)
        candidate = exports_root / "local-cdr.sqlite"
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        return candidate.resolve()

    def read_bank_section_db(db_path: Path, run_date: str, section: str) -> list[dict[str, object]]:
        # Apply the same rate_family / non-DISCOUNT filter the client used to do
        # post-fetch (and that /api/banks/ribbon already applies). Saves the wire
        # cost of every Mortgage DISCOUNT row that the dashboard discards anyway.
        filter_sql, filter_params = bank_section_rate_filter(section)
        with sqlite3.connect(db_path) as con:
            available = bank_rate_columns(con)
            select_list = bank_rate_select_list(available, BANK_SECTION_COLUMNS)
            sql = (
                f"SELECT {select_list} FROM bank_rates "
                "WHERE run_date = ? AND dataset = ? AND rate IS NOT NULL AND rate != ''"
                + filter_sql
            )
            params = [run_date, section, *filter_params]
            # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query
            rows = con.execute(sql, params)
            out = []
            for row in rows:
                item = {col: row[index] for index, col in enumerate(BANK_SECTION_COLUMNS)}
                out.append(compact_bank_row(item))
            return out

    def bank_section_rate_filter(section: str) -> tuple[str, list[str]]:
        if section == "Mortgage":
            return " AND rate_family = ? AND COALESCE(rate_type, '') != ?", ["lending", "DISCOUNT"]
        return " AND rate_family = ?", ["deposit"]

    def normalized_rate_value(raw: object, dataset: str, percent_style: bool) -> float | None:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        if not value or value <= 0:
            return None
        if percent_style:
            return value / 100.0
        if dataset == "Mortgage" and 0.3 < value <= 1:
            return value / 10.0
        return value / 100.0 if value > 1 else value

    def aggregate_ribbon_rows(rows: list[sqlite3.Row], section: str) -> dict[str, object]:
        product_keys = [
            str(row["product_key"] or row["product_id"] or row["product_name"] or "")
            for row in rows
        ]
        percent_style_products: set[str] = set()
        for key, row in zip(product_keys, rows):
            try:
                raw_value = float(row["rate"])
            except (TypeError, ValueError):
                continue
            if key and raw_value > 1:
                percent_style_products.add(key)
        providers: dict[str, dict[str, object]] = {}
        rates: list[float] = []
        products: set[str] = set()
        for key, row in zip(product_keys, rows):
            rate = normalized_rate_value(row["rate"], section, key in percent_style_products)
            if rate is None:
                continue
            provider = str(row["provider"] or "Unknown")
            products.add(key)
            rates.append(rate)
            bucket = providers.setdefault(provider, {"rates": [], "products": set()})
            bucket["rates"].append(rate)
            bucket["products"].add(key)

        def stats(values: list[float]) -> dict[str, float | None]:
            if not values:
                return {"min": None, "max": None, "mean": None}
            return {
                "min": min(values),
                "max": max(values),
                "mean": sum(values) / len(values),
            }

        return {
            "counts": {
                "rates": len(rates),
                "products": len(products),
                "providers": len(providers),
            },
            "range": stats(rates),
            "providers": [
                {
                    "provider": provider,
                    "rates": len(bucket["rates"]),
                    "products": len(bucket["products"]),
                    **stats(bucket["rates"]),
                }
                for provider, bucket in sorted(providers.items())
            ],
        }

    def bank_ribbon_payload(run_date: str, section: str) -> bytes:
        db_path = bank_db_for_date(run_date)
        with sqlite3.connect(db_path) as con:
            con.row_factory = sqlite3.Row
            filter_sql, filter_params = bank_section_rate_filter(section)
            where = (
                "run_date = ? AND dataset = ? AND rate IS NOT NULL AND rate != ''"
                + filter_sql
            )
            params = [run_date, section, *filter_params]
            rows = con.execute(
                "SELECT provider, product_key, product_id, product_name, rate "
                f"FROM bank_rates WHERE {where}",
                params,
            ).fetchall()
        aggregate = aggregate_ribbon_rows(rows, section)
        payload = {
            "run_date": run_date,
            "section": section,
            **aggregate,
        }
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return body, maybe_gzip(body, "application/json")

    def bank_section_payload(run_date: str, section: str) -> Tuple[bytes, bytes | None]:
        db_path = bank_db_for_date(run_date)
        stat = db_path.stat()
        cache_key = (run_date, section, str(db_path), stat.st_mtime, stat.st_size)
        with section_cache_lock:
            cached = section_cache.get(cache_key)
            if cached is not None:
                section_cache.move_to_end(cache_key)
                return cached
        rows = read_bank_section_db(db_path, run_date, section)
        body = json.dumps(
            {
                "run_date": run_date,
                "section": section,
                "rates": rows,
                "counts": {"rates": len(rows)},
            },
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        entry = (body, maybe_gzip(body, "application/json"))
        with section_cache_lock:
            if len(section_cache) >= MAX_ARTIFACT_CACHE_ENTRIES * 3:
                section_cache.popitem(last=False)
            section_cache[cache_key] = entry
        return entry

    def read_bank_history_db(db_path: Path, max_run_date: str, section: str) -> list[dict[str, object]]:
        with sqlite3.connect(db_path) as con:
            available = bank_rate_columns(con)
            select_list = bank_rate_select_list(available, BANK_HISTORY_COLUMNS)
            sql = f"SELECT {select_list} FROM bank_rates WHERE rate IS NOT NULL AND rate != ''"
            params: list[str] = []
            if max_run_date:
                sql += " AND run_date <= ?"
                params.append(max_run_date)
            if section:
                sql += " AND dataset = ?"
                params.append(section)
                # Same DISCOUNT / rate_family filter the section endpoint applies,
                # so the history payload doesn't ship rows the dashboard discards.
                filter_sql, filter_params = bank_section_rate_filter(section)
                sql += filter_sql
                params.extend(filter_params)
            # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query
            rows = con.execute(sql, params)
            out = []
            for row in rows:
                item = {col: row[index] for index, col in enumerate(BANK_HISTORY_COLUMNS)}
                # dataset and rate_family are needed by canonicalize_history_row
                # (Mortgage branch) and by callers of the unscoped endpoint to
                # identify which section a row belongs to. When we're scoped to
                # a single section those two fields are constant — the client
                # already knows them from the request — so drop them after
                # canonicalisation to save the wire cost.
                canonicalize_history_row(item)
                if section:
                    item.pop("dataset", None)
                    item.pop("rate_family", None)
                out.append(compact_bank_row(item))
            return out

    def bank_history_payload(max_run_date: str, section: str = "") -> Tuple[bytes, bytes | None]:
        dbs = bank_history_db_paths(max_run_date)
        signature = tuple((str(path), path.stat().st_mtime, path.stat().st_size) for path in dbs)
        cache_key = (max_run_date, section, signature)
        with history_cache_lock:
            cached = history_cache.get(cache_key)
            if cached is not None:
                return cached
        rows: list[dict[str, object]] = []
        for db_path in dbs:
            try:
                rows.extend(read_bank_history_db(db_path, max_run_date, section))
            except sqlite3.Error as exc:
                print(f"Skipping unreadable history DB {db_path}: {exc}")
        run_dates = sorted({str(row.get("run_date") or "") for row in rows if row.get("run_date")})
        filled_rows, carry_forward_count = fill_history_gaps(rows, run_dates)
        body = json.dumps(
            {
                "run_dates": run_dates,
                "section": section,
                "rates": filled_rows,
                "carry_forward_count": carry_forward_count,
            },
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        entry = (body, maybe_gzip(body, "application/json"))
        with history_cache_lock:
            if len(history_cache) >= MAX_HISTORY_CACHE_ENTRIES:
                oldest_key = next(iter(history_cache))
                history_cache.pop(oldest_key)
            history_cache[cache_key] = entry
        return entry

    def warm_common_files() -> None:
        for rel in (
            "index.html",
            "app.css",
            "app.js",
            "ar-bank-brand.js",
            "ar-ribbon-canonical-tiers.js",
            "chart.js",
            "hierarchy.js",
            "cdr-ribbon-map.js",
            "cdr-taxonomy-tree.js",
            "local-brand.js",
            "rba-cash-rate.js",
            "utils.js",
        ):
            try:
                dashboard_cache.read(DASHBOARD_ROOT / rel)
            except FileNotFoundError:
                pass
        for site_rel in (
            "theme.js",
            "foundation.css",
            "ar-ribbon-format.js",
            "ar-ribbon-tree.js",
        ):
            try:
                site_cache.read(site_root / site_rel)
            except FileNotFoundError:
                print(f"Site static missing: {site_root / site_rel}")
        try:
            site_cache.read(site_root / "assets" / "branding" / "ar-mark.svg")
        except FileNotFoundError:
            print(f"Site static missing: {site_root / 'assets' / 'branding' / 'ar-mark.svg'}")
        try:
            exports_root, cache = artifact_cache()
            latest = cache.read(exports_root / "dashboard-cache" / "latest.json")
            manifest = json.loads(latest.decode("utf-8"))
            run_date = str(manifest.get("run_date") or "")
            if run_date:
                bank_ribbon_payload(run_date, "Mortgage")
                bank_section_payload(run_date, "Mortgage")
                if not energy_dormant():
                    cache.read(exports_root / "dashboard-cache" / run_date / "energy.json")
        except (FileNotFoundError, json.JSONDecodeError, sqlite3.Error):
            pass

    if preload:
        warm_common_files()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                body, ctype, gz = self.route(parsed.path, parse_qs(parsed.query))
                encoding = None
                if gz is not None and _client_accepts_gzip(self.headers.get("Accept-Encoding", "")):
                    body = gz
                    encoding = "gzip"
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "public, max-age=300")
                self.send_header("Vary", "Accept-Encoding")
                if encoding:
                    self.send_header("Content-Encoding", encoding)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except ProxyUpstreamError as exc:
                self.send_response(exc.status)
                self.send_header("Content-Type", exc.content_type)
                self.send_header("Cache-Control", "public, max-age=120")
                self.send_header("Content-Length", str(len(exc.body)))
                self.end_headers()
                self.wfile.write(exc.body)
            except BadRequestError as exc:
                self.send_error(HTTPStatus.BAD_REQUEST, explain=str(exc))
            except FileNotFoundError:
                self.send_error(HTTPStatus.NOT_FOUND)

        def log_message(self, fmt: str, *args: object) -> None:
            print(fmt % args)

        def _serve_file(self, cache: CachedFiles, target: Path, ctype: str) -> Tuple[bytes, str, bytes | None]:
            return cache.read(target), ctype, cache.gz_for(target, ctype)

        def route(self, path: str, query: Dict[str, list[str]]) -> Tuple[bytes, str, bytes | None]:
            if is_dashboard_banking_section_path(path):
                return self._serve_file(dashboard_cache, DASHBOARD_ROOT / "index.html", "text/html; charset=utf-8")
            if path == "/assets/app.css":
                return self._serve_file(dashboard_cache, DASHBOARD_ROOT / "app.css", "text/css; charset=utf-8")
            if path in (
                "/assets/app.js",
                "/assets/ar-bank-brand.js",
                "/assets/ar-ribbon-canonical-tiers.js",
                "/assets/chart.js",
                "/assets/hierarchy.js",
                "/assets/cdr-ribbon-map.js",
                "/assets/cdr-taxonomy-tree.js",
                "/assets/local-brand.js",
                "/assets/rba-cash-rate.js",
                "/assets/utils.js",
            ):
                return self._serve_file(
                    dashboard_cache,
                    DASHBOARD_ROOT / path.removeprefix("/assets/"),
                    "application/javascript; charset=utf-8",
                )
            if path == "/assets/branding/ar-mark.svg":
                return self._serve_file(site_cache, site_root / "assets" / "branding" / "ar-mark.svg", "image/svg+xml")
            if path.startswith("/assets/banks/"):
                target = (site_root / path.removeprefix("/")).resolve()
                bank_root = bank_assets_root.resolve()
                if bank_root not in target.parents and target != bank_root:
                    raise FileNotFoundError(path)
                ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                return self._serve_file(site_cache, target, ctype)
            if path == "/api/latest":
                exports_root, cache = artifact_cache()
                return self._serve_file(cache, exports_root / "dashboard-cache" / "latest.json", "application/json")
            if path == "/api/ingest-schedule":
                body = ingest_schedule_payload()
                return body, "application/json; charset=utf-8", maybe_gzip(body, "application/json")
            if path == "/api/energy":
                if energy_dormant():
                    body = json.dumps(
                        {
                            "run_date": "",
                            "plans": [],
                            "counts": {},
                            "dormant": True,
                            "message": "Energy CDR sector is dormant (set AR_ENERGY_DORMANT=0 and use cdr_daily.py --energy to re-enable).",
                        },
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode("utf-8")
                    return body, "application/json; charset=utf-8", maybe_gzip(body, "application/json")
                date = parse_run_date_param(query.get("date", [""])[0])
                exports_root = export_resolver.root_for_date(date)
                exports_root, cache = artifact_cache(exports_root)
                return self._serve_file(cache, exports_root / "dashboard-cache" / date / "energy.json", "application/json")
            if path == "/api/banks":
                date = parse_run_date_param(query.get("date", [""])[0])
                exports_root = export_resolver.root_for_date(date)
                exports_root, cache = artifact_cache(exports_root)
                return self._serve_file(cache, exports_root / "dashboard-cache" / date / "banks.json", "application/json")
            if path == "/api/banks/section":
                date = parse_run_date_param(query.get("date", [""])[0])
                section = parse_bank_section_param(query.get("section", [""])[0])
                body, gz = bank_section_payload(date, section)
                return body, "application/json; charset=utf-8", gz
            if path == "/api/banks/ribbon":
                date = parse_run_date_param(query.get("date", [""])[0])
                section = parse_bank_section_param(query.get("section", [""])[0])
                body, gz = bank_ribbon_payload(date, section)
                return body, "application/json; charset=utf-8", gz
            if path.startswith("/api/economic-data"):
                body, ctype = proxy_upstream_get(ECONOMIC_API_UPSTREAM, path, query)
                return body, ctype, None
            if path == "/api/banks/history":
                raw_date = str(query.get("date", [""])[0] or "").strip()
                date = parse_run_date_param(raw_date) if raw_date else ""
                body, gz = bank_history_payload(date)
                return body, "application/json", gz
            if path == "/api/banks/history/section":
                raw_date = str(query.get("date", [""])[0] or "").strip()
                date = parse_run_date_param(raw_date) if raw_date else ""
                section = parse_bank_section_param(query.get("section", [""])[0])
                body, gz = bank_history_payload(date, section)
                return body, "application/json; charset=utf-8", gz
            if is_economic_data_page_path(path):
                target = resolve_site_public_file(site_root, path)
                body = site_cache.read(target)
                ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                if (ctype or "").startswith("text/html"):
                    injected = inject_local_dashboard_css(body)
                    return injected, "text/html; charset=utf-8", maybe_gzip(injected, "text/html")
                return body, ctype, site_cache.gz_for(target, ctype)
            if path.startswith("/site/"):
                target = (site_root / path.removeprefix("/site/")).resolve()
                site_resolved = site_root.resolve()
                if site_resolved not in target.parents and target != site_resolved:
                    raise FileNotFoundError(path)
                ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                return self._serve_file(site_cache, target, ctype)
            try:
                target = resolve_site_public_file(site_root, path)
                ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                return self._serve_file(site_cache, target, ctype)
            except FileNotFoundError:
                pass
            if path.startswith("/exports/"):
                exports_root, cache = artifact_cache()
                target = exports_root / path.removeprefix("/exports/")
                ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                return self._serve_file(cache, target, ctype)
            raise FileNotFoundError(path)

    return Handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve local CDR dashboard from generated cache.")
    parser.add_argument(
        "--exports",
        required=True,
        help="Export folder containing dashboard-cache/, or 'latest' to serve the newest run under --runs.",
    )
    parser.add_argument("--runs", type=Path, default=BASE_DIR / "runs", help="Runs root used with --exports latest.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default="auto", help="Port number or 'auto' (default: auto from 8800)")
    parser.add_argument("--port-file", type=Path, help="Optional JSON file to write the selected dashboard URL to.")
    parser.add_argument("--preload", action="store_true", help="Warm common dashboard and API payloads into memory at startup.")
    parser.add_argument(
        "--site-root",
        type=Path,
        default=None,
        help="Path to AustralianRates `site` folder (default: auto-detect beside this repo).",
    )
    return parser.parse_args()


def dashboard_url(host: str, port: int) -> str:
    display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    return f"http://{display_host}:{port}/"


def create_server(host: str, value: str, handler):
    if value != "auto":
        port = int(value)
        return LocalDashboardServer((host, port), handler), port
    port = 8800
    while True:
        try:
            return LocalDashboardServer((host, port), handler), port
        except OSError as exc:
            if exc.errno not in (errno.EADDRINUSE, errno.EACCES, 10048):
                raise
            port += 1


def main() -> int:
    args = parse_args()
    site_root = resolve_site_root(args.site_root)
    export_resolver = ExportResolver(str(args.exports), args.runs)
    print(f"Site static root: {site_root}")
    print(f"Dashboard exports: {args.exports}")
    server, port = create_server(args.host, str(args.port), make_handler(export_resolver, site_root, args.preload))
    url = dashboard_url(args.host, port)
    if args.port_file:
        args.port_file.write_text(json.dumps({"host": args.host, "port": port, "url": url}), encoding="utf-8")
    print(f"Local CDR dashboard: {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
