"""Cached local dashboard for generated CDR run artifacts."""

from __future__ import annotations

import argparse
import errno
import json
import mimetypes
import re
import socket
import sqlite3
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Tuple
from urllib.parse import parse_qs, urlparse

from ar_local_pi_runtime import latest_exports_root

BASE_DIR = Path(__file__).resolve().parent
DASHBOARD_ROOT = BASE_DIR / "dashboard"
LATEST_EXPORTS_TTL_SECONDS = 5.0
MAX_ARTIFACT_CACHE_ENTRIES = 4
MAX_HISTORY_CACHE_ENTRIES = 8
DEFAULT_HISTORY_RUN_LIMIT = 90
BANK_HISTORY_COLUMNS = (
    "run_date",
    "dataset",
    "provider",
    "product_id",
    "product_key",
    "product_name",
    "rate_family",
    "rate",
    "comparison_rate",
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
    "account_type",
    "ribbon_deposit_kind",
    "balance_min",
    "balance_max",
    "term_months",
    "interest_payment",
    "feature_set",
)
BANK_HISTORY_SELECT_SQL = """
SELECT run_date, dataset, provider, product_id, product_key, product_name,
       rate_family, rate, comparison_rate, rate_type, application_type,
       application_frequency, repayment_type, loan_purpose, term,
       ribbon_normalized, security_purpose, ribbon_repayment_type, lvr_tier,
       ribbon_rate_structure, account_type, ribbon_deposit_kind, balance_min,
       balance_max, term_months, interest_payment, feature_set
FROM bank_rates
WHERE rate IS NOT NULL AND rate != ''
"""
BANK_HISTORY_SELECT_UNTIL_SQL = BANK_HISTORY_SELECT_SQL + " AND run_date <= ?"


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
        self.memory: Dict[Path, Tuple[float, bytes]] = {}

    def read(self, path: Path) -> bytes:
        resolved = path.resolve()
        if self.exports_root not in resolved.parents and resolved != self.exports_root:
            raise FileNotFoundError(path)
        stat = resolved.stat()
        cached = self.memory.get(resolved)
        if cached and cached[0] == stat.st_mtime:
            return cached[1]
        data = resolved.read_bytes()
        self.memory[resolved] = (stat.st_mtime, data)
        return data


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
        super().server_bind()


def make_handler(export_resolver: ExportResolver, site_root: Path, preload: bool):
    bank_assets_root = site_root / "assets" / "banks"
    artifact_caches: Dict[Path, CachedFiles] = {}
    artifact_cache_lock = threading.Lock()
    dashboard_cache = CachedFiles(DASHBOARD_ROOT)
    site_cache = CachedFiles(site_root)
    history_cache: Dict[Tuple[str, Tuple[Tuple[str, float, int], ...]], bytes] = {}
    history_cache_lock = threading.Lock()

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

    def read_bank_history_db(db_path: Path, max_run_date: str) -> list[dict[str, object]]:
        with sqlite3.connect(db_path) as con:
            if max_run_date:
                # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query
                rows = con.execute(BANK_HISTORY_SELECT_UNTIL_SQL, (max_run_date,))
            else:
                # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query
                rows = con.execute(BANK_HISTORY_SELECT_SQL)
            out = []
            for row in rows:
                item = {col: row[index] for index, col in enumerate(BANK_HISTORY_COLUMNS)}
                out.append(item)
            return out

    def bank_history_payload(max_run_date: str) -> bytes:
        dbs = bank_history_db_paths(max_run_date)
        signature = tuple((str(path), path.stat().st_mtime, path.stat().st_size) for path in dbs)
        cache_key = (max_run_date, signature)
        with history_cache_lock:
            cached = history_cache.get(cache_key)
            if cached is not None:
                return cached
        rows: list[dict[str, object]] = []
        for db_path in dbs:
            try:
                rows.extend(read_bank_history_db(db_path, max_run_date))
            except sqlite3.Error as exc:
                print(f"Skipping unreadable history DB {db_path}: {exc}")
        run_dates = sorted({str(row.get("run_date") or "") for row in rows if row.get("run_date")})
        payload = json.dumps(
            {"run_dates": run_dates, "rates": rows},
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        with history_cache_lock:
            if len(history_cache) >= MAX_HISTORY_CACHE_ENTRIES:
                oldest_key = next(iter(history_cache))
                history_cache.pop(oldest_key)
            history_cache[cache_key] = payload
        return payload

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
            "utils.js",
        ):
            try:
                dashboard_cache.read(DASHBOARD_ROOT / rel)
            except FileNotFoundError:
                pass
        try:
            site_cache.read(site_root / "assets" / "branding" / "ar-mark.svg")
        except FileNotFoundError:
            pass
        try:
            exports_root, cache = artifact_cache()
            latest = cache.read(exports_root / "dashboard-cache" / "latest.json")
            manifest = json.loads(latest.decode("utf-8"))
            run_date = str(manifest.get("run_date") or "")
            if run_date:
                cache.read(exports_root / "dashboard-cache" / run_date / "banks.json")
                cache.read(exports_root / "dashboard-cache" / run_date / "energy.json")
                bank_history_payload(run_date)
        except (FileNotFoundError, json.JSONDecodeError, sqlite3.Error):
            pass

    if preload:
        warm_common_files()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                body, ctype = self.route(parsed.path, parse_qs(parsed.query))
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "public, max-age=300")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except FileNotFoundError:
                self.send_error(HTTPStatus.NOT_FOUND)

        def log_message(self, fmt: str, *args: object) -> None:
            print(fmt % args)

        def route(self, path: str, query: Dict[str, list[str]]) -> Tuple[bytes, str]:
            if path == "/":
                return dashboard_cache.read(DASHBOARD_ROOT / "index.html"), "text/html; charset=utf-8"
            if path == "/assets/app.css":
                return dashboard_cache.read(DASHBOARD_ROOT / "app.css"), "text/css; charset=utf-8"
            if path in (
                "/assets/app.js",
                "/assets/ar-bank-brand.js",
                "/assets/ar-ribbon-canonical-tiers.js",
                "/assets/chart.js",
                "/assets/hierarchy.js",
                "/assets/cdr-ribbon-map.js",
                "/assets/cdr-taxonomy-tree.js",
                "/assets/local-brand.js",
                "/assets/utils.js",
            ):
                return dashboard_cache.read(DASHBOARD_ROOT / path.removeprefix("/assets/")), "application/javascript; charset=utf-8"
            if path == "/assets/branding/ar-mark.svg":
                return site_cache.read(site_root / "assets" / "branding" / "ar-mark.svg"), "image/svg+xml"
            if path.startswith("/assets/banks/"):
                target = (site_root / path.removeprefix("/")).resolve()
                bank_root = bank_assets_root.resolve()
                if bank_root not in target.parents and target != bank_root:
                    raise FileNotFoundError(path)
                return site_cache.read(target), mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            if path.startswith("/site/"):
                target = (site_root / path.removeprefix("/site/")).resolve()
                site_resolved = site_root.resolve()
                if site_resolved not in target.parents and target != site_resolved:
                    raise FileNotFoundError(path)
                return site_cache.read(target), mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            if path == "/api/latest":
                exports_root, cache = artifact_cache()
                return cache.read(exports_root / "dashboard-cache" / "latest.json"), "application/json"
            if path in ("/api/banks", "/api/energy"):
                date = query.get("date", [""])[0]
                exports_root = export_resolver.root_for_date(date)
                exports_root, cache = artifact_cache(exports_root)
                name = path.rsplit("/", 1)[1] + ".json"
                return cache.read(exports_root / "dashboard-cache" / date / name), "application/json"
            if path == "/api/banks/history":
                date = query.get("date", [""])[0]
                return bank_history_payload(date), "application/json"
            if path.startswith("/exports/"):
                exports_root, cache = artifact_cache()
                target = exports_root / path.removeprefix("/exports/")
                return cache.read(target), mimetypes.guess_type(str(target))[0] or "application/octet-stream"
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
