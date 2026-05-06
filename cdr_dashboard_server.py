"""Cached local dashboard for generated CDR run artifacts."""

from __future__ import annotations

import argparse
import errno
import json
import mimetypes
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Tuple
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent
DASHBOARD_ROOT = BASE_DIR / "dashboard"
SITE_ROOT = BASE_DIR.parent / "site"
BANK_ASSETS_ROOT = SITE_ROOT / "assets" / "banks"


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


class LocalDashboardServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_handler(exports_root: Path):
    artifact_cache = CachedFiles(exports_root)
    dashboard_cache = CachedFiles(DASHBOARD_ROOT)
    site_cache = CachedFiles(SITE_ROOT)

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
            if path in ("/assets/app.js", "/assets/chart.js", "/assets/hierarchy.js", "/assets/local-brand.js", "/assets/utils.js"):
                return dashboard_cache.read(DASHBOARD_ROOT / path.removeprefix("/assets/")), "application/javascript; charset=utf-8"
            if path == "/assets/branding/ar-mark.svg":
                return site_cache.read(SITE_ROOT / "assets" / "branding" / "ar-mark.svg"), "image/svg+xml"
            if path.startswith("/assets/banks/"):
                target = (SITE_ROOT / path.removeprefix("/")).resolve()
                bank_root = BANK_ASSETS_ROOT.resolve()
                if bank_root not in target.parents and target != bank_root:
                    raise FileNotFoundError(path)
                return site_cache.read(target), mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            if path.startswith("/site/"):
                target = (SITE_ROOT / path.removeprefix("/site/")).resolve()
                if SITE_ROOT.resolve() not in target.parents and target != SITE_ROOT.resolve():
                    raise FileNotFoundError(path)
                return site_cache.read(target), mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            if path == "/api/latest":
                return artifact_cache.read(exports_root / "dashboard-cache" / "latest.json"), "application/json"
            if path in ("/api/banks", "/api/energy"):
                date = query.get("date", [""])[0]
                name = path.rsplit("/", 1)[1] + ".json"
                return artifact_cache.read(exports_root / "dashboard-cache" / date / name), "application/json"
            if path.startswith("/exports/"):
                target = exports_root / path.removeprefix("/exports/")
                return artifact_cache.read(target), mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            raise FileNotFoundError(path)

    return Handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve local CDR dashboard from generated cache.")
    parser.add_argument("--exports", type=Path, required=True, help="Export folder containing dashboard-cache/")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default="auto", help="Port number or 'auto' (default: auto from 8800)")
    parser.add_argument("--port-file", type=Path, help="Optional JSON file to write the selected dashboard URL to.")
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
    server, port = create_server(args.host, str(args.port), make_handler(args.exports))
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
