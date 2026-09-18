"""Bounded public-document acquisition with pinned DNS and explicit receipts."""
from __future__ import annotations

import http.client
import ipaddress
import json
import math
import socket
import ssl
import threading
import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

from .discovery import document_url
from .acquisition_throttle import HOST_THROTTLE, HostThrottleFailure
from .identity import digest, utc_now
from .observation_checks import bind_manual_check
from .store import EvidenceStore


@dataclass(frozen=True)
class FetchPolicy:
    max_bytes: int = 16 * 1024 * 1024
    timeout_seconds: float = 30
    max_redirects: int = 5
    allowed_hosts: frozenset[str] = field(default_factory=frozenset)
    allow_http: bool = False
    request_guard: Callable[[], str | None] | None = None
    deadline_monotonic: float | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.max_bytes <= 64 * 1024 * 1024:
            raise ValueError("Document byte bound must be between 1 and 64 MiB")
        if not 0 < self.timeout_seconds <= 120 or not 0 <= self.max_redirects <= 10:
            raise ValueError("Document request timeout/redirect bounds are invalid")
        if self.deadline_monotonic is not None and (type(self.deadline_monotonic) not in (int, float)
                                                   or not math.isfinite(self.deadline_monotonic)):
            raise ValueError("Document admission deadline must be finite")


class FetchFailure(Exception):
    def __init__(self, code: str, http_status: int | None = None):
        self.code = code
        self.http_status = http_status
        super().__init__(code)


class OperationalDeferral(FetchFailure):
    """Only a live policy guard produces this scheduling disposition."""

    def __init__(self, reason: str):
        if not isinstance(reason, str) or not reason or len(reason) > 200:
            reason = "operational_guard_unavailable"
        self.reason = reason
        super().__init__("operational_guard:" + reason)


def deferral_metadata(document_id: str, check_id: str, error_code: str) -> dict:
    return {"operational_deferral_v1": {"document_id": document_id, "check_id": check_id,
                                       "error_code": error_code}}


def _public_address(host: str, port: int, timeout: float = 30) -> str:
    # System getaddrinfo has no per-call timeout. A daemon resolver cannot hold
    # the bounded collector process open if the OS resolver becomes stuck.
    result: list[Any] = []
    finished = threading.Event()
    def resolve() -> None:
        try:
            result.append(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
        except OSError as exc:
            result.append(exc)
        finally:
            finished.set()
    threading.Thread(target=resolve, daemon=True).start()
    if not finished.wait(timeout):
        raise FetchFailure("dns_deadline")
    if not result or isinstance(result[0], OSError):
        raise FetchFailure("dns_failed")
    addresses = sorted({entry[4][0] for entry in result[0]})
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise FetchFailure("non_public_address")
    return addresses[0]


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str, port: int, timeout: float):
        super().__init__(host, port=port, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self) -> None:
        started = time.monotonic()
        sock = socket.create_connection((self.address, self.port), self.timeout)
        try:
            remaining = self.timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError("TLS connection deadline")
            sock.settimeout(remaining)
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def _connection(url: str, policy: FetchPolicy, remaining: float) -> http.client.HTTPConnection:
    parsed = urlsplit(url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if policy.allowed_hosts and host not in policy.allowed_hosts:
        raise FetchFailure("host_not_allowed")
    if parsed.scheme != "https" and not policy.allow_http:
        raise FetchFailure("insecure_http_not_enabled")
    if port not in (443, 80):
        raise FetchFailure("port_not_allowed")
    started = time.monotonic()
    address = _public_address(host, port, remaining)
    remaining -= time.monotonic() - started
    if remaining <= 0:
        raise FetchFailure("request_deadline")
    if parsed.scheme == "https":
        connection = _PinnedHTTPS(host, address, port, remaining)
        connection.connect()
        return connection
    # HTTP is explicit opt-in. Pin its socket too; avoid a second DNS lookup.
    connection = http.client.HTTPConnection(host, port, timeout=remaining)
    connection.sock = socket.create_connection((address, port), remaining)
    return connection


def _throttle_request(url: str, policy: FetchPolicy, deadline: float) -> None:
    def check_guard() -> None:
        if policy.request_guard:
            try:
                reason = policy.request_guard()
            except Exception:
                reason = "operational_guard_unavailable"
            if reason:
                raise OperationalDeferral(reason)
    try:
        HOST_THROTTLE.wait(urlsplit(url).hostname, deadline, check_guard)
    except HostThrottleFailure as exc:
        raise FetchFailure(str(exc)) from exc


def _body(response: http.client.HTTPResponse, connection: http.client.HTTPConnection,
          limit: int, deadline: float) -> bytes:
    raw_length = response.getheader("Content-Length")
    if raw_length:
        try:
            if int(raw_length) > limit:
                raise FetchFailure("document_too_large", response.status)
        except ValueError as exc:
            raise FetchFailure("invalid_content_length", response.status) from exc
    chunks: list[bytes] = []
    length = 0
    while length <= limit:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FetchFailure("request_deadline", response.status)
        if connection.sock:
            connection.sock.settimeout(remaining)
        chunk = response.read1(min(65536, limit + 1 - length))
        if not chunk:
            break
        chunks.append(chunk)
        length += len(chunk)
    if length > limit:
        raise FetchFailure("document_too_large", response.status)
    if not length:
        raise FetchFailure("empty_document", response.status)
    return b"".join(chunks)


def fetch_document(url: str, *, policy: FetchPolicy,
                   conditional: dict[str, str] | None = None,
                   conditional_url: str | None = None) -> dict[str, Any]:
    current = document_url(url)
    if not current:
        raise FetchFailure("invalid_document_url")
    deadline = time.monotonic() + policy.timeout_seconds
    if policy.deadline_monotonic is not None:
        deadline = min(deadline, policy.deadline_monotonic)
    redirects: list[str] = []
    validator_url = document_url(conditional_url) if conditional_url else None
    for _ in range(policy.max_redirects + 1):
        if policy.request_guard:
            try:
                reason = policy.request_guard()
            except Exception:
                reason = "operational_guard_unavailable"
            if reason:
                raise OperationalDeferral(reason)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FetchFailure("request_deadline")
        connection = _connection(current, policy, remaining)
        socket_at_deadline = connection.sock
        def expire(target: Any = socket_at_deadline) -> None:
            try:
                target.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        timer = threading.Timer(max(0, deadline - time.monotonic()), expire)
        timer.daemon = True
        timer.start()
        try:
            # Charge spacing after DNS/TLS so slow connection setup cannot bunch
            # requests together. The original timer covers this wait as well.
            _throttle_request(current, policy, deadline)
            parsed = urlsplit(current)
            headers = {"Accept": "application/pdf,text/html,text/plain,application/json;q=0.8,*/*;q=0.1",
                       "Accept-Encoding": "identity", "User-Agent": "AR-local-document-evidence/1"}
            if current == validator_url:
                headers.update(conditional or {})
            target = parsed.path + (("?" + parsed.query) if parsed.query else "")
            connection.request("GET", target, headers=headers)
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                next_url = document_url(urljoin(current, response.getheader("Location") or ""))
                if not next_url or next_url == current or next_url in redirects:
                    raise FetchFailure("invalid_redirect", response.status)
                redirects.append(current)
                current = next_url
                continue
            metadata = {"final_url": current, "redirects": redirects,
                        "etag": response.getheader("ETag"),
                        "last_modified": response.getheader("Last-Modified")}
            if response.status == 304:
                if current != validator_url or not conditional:
                    raise FetchFailure("unbound_not_modified", 304)
                return {"status": "unchanged", "http_status": 304, "metadata": metadata}
            if response.status != 200:
                raise FetchFailure("http_error", response.status)
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise FetchFailure("unsupported_content_encoding", response.status)
            return {"status": "fetched", "http_status": 200, "metadata": metadata,
                    "media_type": response.getheader("Content-Type", "application/octet-stream"),
                    "body": _body(response, connection, policy.max_bytes, deadline)}
        finally:
            timer.cancel()
            connection.close()
    raise FetchFailure("redirect_limit")


def acquire_document(store: EvidenceStore, document_id: str, *, check_id: str,
                     policy: FetchPolicy | None = None) -> dict[str, Any]:
    """One attempt per durable key; retry with a new key to preserve failures."""
    previous_check = store.db.execute("SELECT * FROM acquisition_checks WHERE check_id=?", (check_id,)).fetchone()
    if previous_check:
        if previous_check["document_id"] != document_id:
            raise ValueError("Attempt identity is already bound to another document")
        return dict(previous_check)
    row = store.db.execute("SELECT * FROM documents WHERE document_id=?", (document_id,)).fetchone()
    if not row:
        raise ValueError("Document must originate from the evidence inventory")
    previous = store.last_success(document_id)
    headers: dict[str, str] = {}
    validator_url = None
    if previous:
        metadata = json.loads(previous["metadata_json"])
        validator_url = document_url(metadata.get("final_url"))
        for field, header in (("etag", "If-None-Match"), ("last_modified", "If-Modified-Since")):
            if metadata.get(field):
                headers[header] = metadata[field]
    checked_at = utc_now()
    try:
        result = fetch_document(row["source_url"], policy=policy or FetchPolicy(),
                                conditional=headers, conditional_url=validator_url)
        if result["status"] == "unchanged":
            if not previous:
                raise FetchFailure("unchanged_without_retained_version", 304)
            if (not validator_url or not headers
                    or document_url(result.get("metadata", {}).get("final_url")) != validator_url):
                raise FetchFailure("unbound_not_modified", 304)
            result["previous_version_id"] = previous["document_version_id"]
            # Servers may omit validators on 304. Retain the previously bound
            # values instead of silently turning the next check unconditional.
            old_metadata = json.loads(previous["metadata_json"])
            result["metadata"] = {**old_metadata, **{key: value for key, value in result.get("metadata", {}).items() if value is not None}}
    except OperationalDeferral as exc:
        result = {"status": "deferred", "error_code": exc.code,
                  "metadata": deferral_metadata(document_id, check_id, exc.code)}
    except FetchFailure as exc:
        result = {"status": "failed", "error_code": exc.code, "http_status": exc.http_status}
    except (OSError, http.client.HTTPException, ValueError):
        result = {"status": "failed", "error_code": "transport_error"}
    store.record_check(document_id=document_id, check_id=check_id, checked_at=checked_at, **result)
    return dict(store.db.execute("SELECT * FROM acquisition_checks WHERE check_id=?", (check_id,)).fetchone())


def acquire_observation(store: EvidenceStore, observation_id: str, *, check_prefix: str,
                        max_documents: int = 10, max_total_bytes: int = 64 * 1024 * 1024,
                        max_seconds: float = 300, policy: FetchPolicy | None = None) -> list[dict[str, Any]]:
    if not check_prefix or not 1 <= max_documents <= 100 or not 0 < max_seconds <= 600:
        raise ValueError("Explicit bounded acquisition settings are required")
    if not 1 <= max_total_bytes <= 256 * 1024 * 1024:
        raise ValueError("Invalid batch byte budget")
    rows = store.db.execute("SELECT DISTINCT document_id FROM applicability WHERE observation_id=? AND relation!='cdr_source' ORDER BY document_id",
                            (observation_id,)).fetchall()
    chosen = policy or FetchPolicy()
    deadline = time.monotonic() + max_seconds
    if chosen.deadline_monotonic is not None:
        deadline = min(deadline, chosen.deadline_monotonic)
    results: list[dict[str, Any]] = []
    spent = 0
    for row in rows:
        check_id = digest([check_prefix, observation_id, row[0]])
        if len(results) >= max_documents or spent >= max_total_bytes or time.monotonic() >= deadline:
            # Unattempted references remain pending. No artificial success receipt.
            break
        bounded = replace(chosen, max_bytes=min(chosen.max_bytes, max_total_bytes - spent),
                          timeout_seconds=min(chosen.timeout_seconds, deadline - time.monotonic()),
                          deadline_monotonic=deadline)
        result = acquire_document(store, row[0], check_id=check_id, policy=bounded)
        bind_manual_check(store, observation_id, check_id)
        results.append(result)
        if result["status"] == "fetched":
            version = store.db.execute("SELECT byte_size FROM document_versions WHERE document_version_id=?",
                                       (result["document_version_id"],)).fetchone()
            spent += version[0]
    return results
