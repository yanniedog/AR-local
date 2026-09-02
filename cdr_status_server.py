"""Minimal read-only health and observation status service."""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Mapping

from cdr_atomic import canonical_json_bytes
from cdr_finalization import verified_pointer_export_root
from cdr_observation import load_verified_observation


def _load_verified(exports: Path) -> dict[str, Any] | None:
    try:
        observation, _ = load_verified_observation(exports)
        return observation
    except (OSError, ValueError):
        return None


def _summary(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, int] = {}
    for key, count in sorted(value.items()):
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            result[str(key)] = count
    return result


def status_payload(runs_root: Path) -> tuple[HTTPStatus, dict[str, Any]]:
    runs_root = runs_root.expanduser().resolve()
    exports = verified_pointer_export_root(runs_root.parent / "state")
    if exports is None:
        return HTTPStatus.SERVICE_UNAVAILABLE, {
            "schema_version": 1,
            "service": "ar-local",
            "status": "unavailable",
            "reason": "no_verified_observation",
        }
    try:
        exports.relative_to(runs_root)
    except ValueError:
        return HTTPStatus.SERVICE_UNAVAILABLE, {
            "schema_version": 1,
            "service": "ar-local",
            "status": "unavailable",
            "reason": "no_verified_observation",
        }
    observation = _load_verified(exports)
    if observation is None:
        return HTTPStatus.SERVICE_UNAVAILABLE, {
            "schema_version": 1,
            "service": "ar-local",
            "status": "unavailable",
            "reason": "observation_unreadable",
        }
    accounting = observation.get("accounting")
    if not isinstance(accounting, Mapping):
        accounting = {}
    summaries = observation.get("summaries")
    if not isinstance(summaries, Mapping):
        summaries = {}
    state = str(observation.get("state") or "degraded")
    status = "ok" if state == "complete" else "degraded"
    return HTTPStatus.OK, {
        "schema_version": 1,
        "service": "ar-local",
        "status": status,
        "observation": {
            "date": observation.get("observation_date"),
            "observed_at": observation.get("observed_at"),
            "state": state,
            "accounting_id": accounting.get("accounting_id"),
            "providers": _summary(summaries.get("providers")),
            "products": _summary(summaries.get("products")),
            "issues": _summary(summaries.get("issues")),
        },
    }


def health_payload(_runs_root: Path) -> tuple[HTTPStatus, dict[str, Any]]:
    """Report process liveness; /api/status remains the data-readiness gate."""

    return HTTPStatus.OK, {
        "schema_version": 1,
        "service": "ar-local",
        "status": "ok",
    }


def handler_for(runs_root: Path) -> type[BaseHTTPRequestHandler]:
    root = runs_root.expanduser().resolve()

    class StatusHandler(BaseHTTPRequestHandler):
        server_version = "ARLocalStatus/1"

        def version_string(self) -> str:
            return self.server_version

        def _reply(self, status: HTTPStatus, value: Mapping[str, Any], *, head: bool) -> None:
            body = canonical_json_bytes(value)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; frame-ancestors 'none'",
            )
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            if status == HTTPStatus.METHOD_NOT_ALLOWED:
                self.send_header("Allow", "GET, HEAD")
            self.end_headers()
            if not head:
                self.wfile.write(body)

        def _route(self, *, head: bool = False) -> None:
            path = self.path.split("?", 1)[0]
            if path in {"/", "/status", "/api/status"}:
                self._reply(*status_payload(root), head=head)
                return
            if path == "/healthz":
                self._reply(*health_payload(root), head=head)
                return
            self._reply(
                HTTPStatus.NOT_FOUND,
                {"schema_version": 1, "status": "not_found"},
                head=head,
            )

        def do_GET(self) -> None:  # noqa: N802
            self._route()

        def do_HEAD(self) -> None:  # noqa: N802
            self._route(head=True)

        def _method_not_allowed(self) -> None:
            self._reply(
                HTTPStatus.METHOD_NOT_ALLOWED,
                {"schema_version": 1, "status": "method_not_allowed"},
                head=False,
            )

        do_POST = _method_not_allowed
        do_PUT = _method_not_allowed
        do_PATCH = _method_not_allowed
        do_DELETE = _method_not_allowed

        def log_message(self, format: str, *args: object) -> None:
            return

    return StatusHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=Path("runs"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8808)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    server = HTTPServer((args.host, args.port), handler_for(args.runs))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
