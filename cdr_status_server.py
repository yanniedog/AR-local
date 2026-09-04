"""Minimal read-only health and observation status service."""

from __future__ import annotations

import argparse
import json
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import Any, Mapping

from cdr_atomic import canonical_json_bytes
from cdr_export_contract import load_contract
from cdr_finalization import verified_pointer_export_root
from cdr_ledger_v2 import ledger_root
from cdr_observation import load_verified_observation


_GENERATION = re.compile(r"^obs-\d{4}-\d{2}-\d{2}-[0-9a-f]{16}$")


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


def _safe_child(root: Path, value: Any) -> Path:
    relative = Path(str(value or ""))
    if not str(value or "") or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("unsafe status cache path")
    child = (root / relative).resolve()
    child.relative_to(root)
    return child


def _mapping_file(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("status cache document must be an object")
    return value


def _generation_paths(runs_root: Path) -> tuple[Path, ...]:
    """Return every immutable file covered by the selected ledger ancestry."""

    state = runs_root.parent / "state"
    pointer_path = state / "observation-pointers-v2" / "latest-observation.json"
    pointer = _mapping_file(pointer_path)
    marker_path = _safe_child(state, pointer.get("marker_path"))
    marker = _mapping_file(marker_path)
    ledger = ledger_root(state)
    ledger_head = ledger / "head.json"
    events_root = ledger / "events"
    _mapping_file(ledger_head)
    paths = {
        pointer_path,
        marker_path,
        _safe_child(state, marker.get("export_contract_path")),
        ledger_head,
        events_root,
    }
    for date_dir in events_root.iterdir():
        if not date_dir.is_dir():
            continue
        paths.add(date_dir)
        paths.update(path for path in date_dir.iterdir() if path.is_file())
    date = str(pointer.get("observation_date") or "")
    generation = str(pointer.get("generation_id") or "")
    seen: set[str] = set()
    while _GENERATION.fullmatch(generation) and generation not in seen:
        seen.add(generation)
        event_path = ledger_root(state) / "events" / date / f"{generation}.json"
        event = _mapping_file(event_path)
        contract_path = _safe_child(state, event.get("contract_path"))
        contract = load_contract(contract_path)
        source = _safe_child(state.parent, contract.get("source_path"))
        paths.update({event_path, contract_path})
        for artifact in contract["artifacts"]:
            artifact_path = _safe_child(source, artifact["path"])
            paths.add(artifact_path)
            if artifact_path.suffix == ".sqlite":
                paths.update(Path(f"{artifact_path}{suffix}") for suffix in ("-journal", "-wal", "-shm"))
        if event.get("event_type") != "revision_finalized":
            break
        generation = str(event.get("parent_generation_id") or "")
    return tuple(sorted(paths, key=lambda path: str(path).casefold()))


def _path_stamps(paths: tuple[Path, ...]) -> tuple[tuple[int, ...], ...]:
    def fields(value: Any) -> tuple[int, ...]:
        return (
            value.st_mode,
            value.st_dev,
            value.st_ino,
            value.st_nlink,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    stamps = []
    for path in paths:
        try:
            stamps.append(fields(path.lstat()) + fields(path.stat()))
        except FileNotFoundError:
            stamps.append((-1,))
    return tuple(stamps)


class _StatusResolver:
    """Cache a fully verified immutable generation; invalidate on metadata drift."""

    def __init__(self, runs_root: Path):
        self.runs_root = runs_root
        self._lock = Lock()
        self._paths: tuple[Path, ...] = ()
        self._stamps: tuple[tuple[int, ...], ...] = ()
        self._cached: tuple[HTTPStatus, dict[str, Any]] | None = None

    def resolve(self) -> tuple[HTTPStatus, dict[str, Any]]:
        with self._lock:
            try:
                if self._cached is not None and _path_stamps(self._paths) == self._stamps:
                    return self._cached
                before_paths = _generation_paths(self.runs_root)
                before_stamps = _path_stamps(before_paths)
            except (KeyError, OSError, ValueError, json.JSONDecodeError):
                before_paths, before_stamps = (), ()
            result = status_payload(self.runs_root)
            self._cached = None
            if result[0] != HTTPStatus.OK:
                return result
            try:
                after_paths = _generation_paths(self.runs_root)
                after_stamps = _path_stamps(after_paths)
            except (KeyError, OSError, ValueError, json.JSONDecodeError):
                after_paths, after_stamps = (), ()
            if before_paths != after_paths or before_stamps != after_stamps:
                return HTTPStatus.SERVICE_UNAVAILABLE, {
                    "schema_version": 1,
                    "service": "ar-local",
                    "status": "unavailable",
                    "reason": "observation_changed_during_verification",
                }
            self._paths, self._stamps, self._cached = after_paths, after_stamps, result
            return result


def handler_for(runs_root: Path) -> type[BaseHTTPRequestHandler]:
    root = runs_root.expanduser().resolve()
    resolver = _StatusResolver(root)

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
            if path in {"/status", "/api/status"}:
                self._reply(*resolver.resolve(), head=head)
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
    server = ThreadingHTTPServer((args.host, args.port), handler_for(args.runs))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
