from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

import cdr_status_server
import verify_local
from tests.support_observation import write_finalized_observation


@contextmanager
def running_status(runs: Path) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), cdr_status_server.handler_for(runs))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def request(url: str, method: str = "GET") -> tuple[int, bytes, dict[str, str]]:
    try:
        response = urllib.request.urlopen(
            urllib.request.Request(url, method=method), timeout=2
        )
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return (
            int(response.status),
            response.read(),
            {key.lower(): value for key, value in response.headers.items()},
        )


def test_status_http_surface_is_json_read_only_and_uncacheable(tmp_path: Path) -> None:
    write_finalized_observation(tmp_path)
    with running_status(tmp_path / "runs") as base:
        code, body, headers = request(base + "api/status")
        assert code == 200
        assert json.loads(body)["observation"]["date"] == "2026-09-02"
        assert headers["cache-control"] == "no-store"
        assert headers["content-security-policy"] == (
            "default-src 'none'; frame-ancestors 'none'"
        )
        assert headers["server"] == "ARLocalStatus/1"
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["content-type"].startswith("application/json")

        code, body, _ = request(base + "api/status", method="HEAD")
        assert code == 200 and body == b""
        code, body, headers = request(base + "api/status", method="POST")
        assert code == 405
        assert json.loads(body)["status"] == "method_not_allowed"
        assert headers["allow"] == "GET, HEAD"
        code, body, _ = request(base + "api/latest")
        assert code == 404 and json.loads(body)["status"] == "not_found"
        code, body, _ = request(base)
        assert code == 404 and json.loads(body)["status"] == "not_found"


def test_nginx_proxies_only_the_three_status_routes() -> None:
    config = (Path(__file__).parents[1] / "deploy/pi/ar-local-status-nginx.conf").read_text(
        encoding="utf-8"
    )
    assert "^/(?:healthz|status|api/status)$" in config
    assert "api/latest" not in config
    assert "api/status)?$" not in config


def test_minimal_verifier_rechecks_database_bytes(tmp_path: Path) -> None:
    write_finalized_observation(tmp_path)
    exports = tmp_path / "runs/2026-09-02/_exports"
    with running_status(tmp_path / "runs") as base:
        assert verify_local.main([
            "--base-url", base, "--expect-run-date", "2026-09-02", "--timeout", "2"
        ]) == 0
        with (exports / "local-cdr.sqlite").open("ab") as stream:
            stream.write(b"tamper")
        assert verify_local.main(["--base-url", base, "--timeout", "2"]) == 1
