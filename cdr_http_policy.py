"""Bounded HTTPS transport policy for public CDR ingest endpoints.

The register is an untrusted source of holder URLs.  Every request therefore
resolves and validates all addresses before connecting, pins the socket to one
of those validated addresses, and repeats the validation for every redirect.
Only same-origin HTTPS redirects and pagination links are accepted.
"""

from __future__ import annotations

import gzip
import hashlib
import http.client
import io
import ipaddress
import queue
import re
import socket
import ssl
import threading
import time
import urllib.parse
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Optional, Sequence


@dataclass(frozen=True)
class HttpPolicy:
    max_url_chars: int = 4096
    max_redirects: int = 3
    max_request_seconds: float = 60.0
    max_logical_fetch_seconds: float = 240.0
    max_retries: int = 6
    max_total_attempts: int = 12
    max_retry_after_seconds: float = 60.0
    max_compressed_bytes: int = 8 * 1024 * 1024
    max_inflated_bytes: int = 32 * 1024 * 1024
    max_body_bytes: int = 32 * 1024 * 1024
    max_pages: int = 1000


DEFAULT_HTTP_POLICY = HttpPolicy()


class HttpPolicyError(RuntimeError):
    """A stable, safe-to-record policy or transport failure."""

    def __init__(self, code: str, message: str, *, status: int = 495) -> None:
        super().__init__(message)
        self.code = code
        self.public_message = message
        self.status = status


@dataclass(frozen=True)
class CanonicalUrl:
    url: str
    host: str
    port: int
    origin: str
    request_target: str


@dataclass(frozen=True)
class ValidatedTarget(CanonicalUrl):
    addresses: tuple[str, ...]


@dataclass(frozen=True)
class WireResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes
    wire_bytes: int
    inflated_bytes: int
    wire_sha256: str
    peer_ip: Optional[str]


@dataclass(frozen=True)
class RedirectEvidence:
    status: int
    source_url: str
    target_url: str


@dataclass(frozen=True)
class PolicyResponse:
    status: int
    url: str
    headers: Mapping[str, str]
    body: bytes
    wire_bytes: int
    inflated_bytes: int
    wire_sha256: str
    peer_ip: Optional[str]
    redirects: tuple[RedirectEvidence, ...]


Resolver = Callable[..., Sequence[tuple]]
Exchange = Callable[[ValidatedTarget, Mapping[str, str], float, HttpPolicy], WireResponse]

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_FORBIDDEN_REQUEST_HEADERS = frozenset(
    {
        "authorization",
        "connection",
        "content-length",
        "cookie",
        "host",
        "proxy-authorization",
        "transfer-encoding",
    }
)
_SENSITIVE_QUERY_NAMES = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "code",
        "key",
        "password",
        "secret",
        "signature",
        "sig",
        "token",
    }
)
_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_SINGLETON_RESPONSE_HEADERS = frozenset(
    {"content-encoding", "content-length", "location", "retry-after"}
)


def _reject_control_characters(value: str, *, code: str) -> None:
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise HttpPolicyError(code, "URL or header contains control characters")


def canonical_https_url(url: str, *, policy: HttpPolicy = DEFAULT_HTTP_POLICY) -> CanonicalUrl:
    """Validate and canonicalize an HTTPS URL without performing DNS."""
    if not isinstance(url, str) or not url or len(url) > policy.max_url_chars:
        raise HttpPolicyError("invalid_url", "URL is empty or exceeds the length limit")
    _reject_control_characters(url, code="invalid_url")
    if "\\" in url:
        raise HttpPolicyError("invalid_url", "Backslashes are not permitted in HTTPS URLs")
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise HttpPolicyError("invalid_url", "URL authority is invalid") from error
    if parsed.scheme.lower() != "https":
        raise HttpPolicyError("https_required", "Only HTTPS endpoints are permitted")
    if parsed.username is not None or parsed.password is not None:
        raise HttpPolicyError("credentials_forbidden", "URL credentials are not permitted")
    if parsed.fragment:
        raise HttpPolicyError("fragment_forbidden", "URL fragments are not permitted")
    raw_host = (parsed.hostname or "").rstrip(".").lower()
    if not raw_host:
        raise HttpPolicyError("invalid_url", "URL hostname is missing")
    try:
        host = raw_host.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise HttpPolicyError("invalid_url", "URL hostname is invalid") from error
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise HttpPolicyError("ip_literal_forbidden", "IP-literal endpoints are not permitted")
    port = port or 443
    if port != 443:
        raise HttpPolicyError("port_forbidden", "Only the standard HTTPS port is permitted")
    path = urllib.parse.quote(
        parsed.path or "/",
        safe="/%:@!$&'()*+,;=-._~",
    )
    if path.startswith("//"):
        raise HttpPolicyError("invalid_url", "Network-path request targets are not permitted")
    query = urllib.parse.quote(
        parsed.query,
        safe="=&?/:@!$'()*+,;%-._~",
    )
    request_target = path + (f"?{query}" if query else "")
    origin = f"https://{host}"
    canonical_url = urllib.parse.urlunsplit(("https", host, path, query, ""))
    if len(canonical_url) > policy.max_url_chars:
        raise HttpPolicyError("invalid_url", "Canonical URL exceeds the length limit")
    return CanonicalUrl(
        url=canonical_url,
        host=host,
        port=port,
        origin=origin,
        request_target=request_target,
    )


def _public_address(value: str) -> str:
    candidate = value.split("%", 1)[0]
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError as error:
        raise HttpPolicyError("dns_invalid_address", "DNS returned an invalid address") from error
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if not address.is_global:
        raise HttpPolicyError("ssrf_address_forbidden", "DNS returned a non-public address")
    return address.compressed


def resolve_public_https_url(
    url: str,
    *,
    policy: HttpPolicy = DEFAULT_HTTP_POLICY,
    resolver: Resolver = socket.getaddrinfo,
) -> ValidatedTarget:
    """Resolve an HTTPS hostname and reject the whole set if any answer is private."""
    canonical = canonical_https_url(url, policy=policy)
    try:
        answers = resolver(canonical.host, canonical.port, 0, socket.SOCK_STREAM)
    except (OSError, UnicodeError) as error:
        raise HttpPolicyError("dns_resolution_failed", "Public DNS resolution failed", status=599) from error
    addresses: set[str] = set()
    for answer in answers:
        try:
            raw_address = answer[4][0]
        except (IndexError, TypeError) as error:
            raise HttpPolicyError("dns_invalid_answer", "DNS returned a malformed answer") from error
        addresses.add(_public_address(str(raw_address)))
    if not addresses:
        raise HttpPolicyError("dns_no_addresses", "DNS returned no usable addresses", status=599)
    ordered = tuple(sorted(addresses, key=lambda item: (ipaddress.ip_address(item).version, item)))
    return ValidatedTarget(**canonical.__dict__, addresses=ordered)


def pagination_next_url(
    current_url: str,
    next_value: str,
    *,
    policy: HttpPolicy = DEFAULT_HTTP_POLICY,
) -> str:
    """Resolve a pagination link and require it to remain on the current origin."""
    current = canonical_https_url(current_url, policy=policy)
    candidate = urllib.parse.urljoin(current.url, str(next_value or "").strip())
    target = canonical_https_url(candidate, policy=policy)
    if target.origin != current.origin:
        raise HttpPolicyError(
            "pagination_cross_origin",
            "Pagination links must remain on the holder origin",
        )
    return target.url


def sanitize_url(url: str) -> str:
    """Return bounded evidence text with credentials and sensitive query values removed."""
    try:
        parsed = urllib.parse.urlsplit(str(url or ""))
        host = (parsed.hostname or "").lower()
        if not parsed.scheme or not host:
            return "<invalid-url>"
        query = []
        for name, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
            safe_value = "[REDACTED]" if name.lower() in _SENSITIVE_QUERY_NAMES else value[:256]
            query.append((name[:128], safe_value))
        authority = host
        if parsed.port and parsed.port != 443:
            authority = f"{authority}:{parsed.port}"
        result = urllib.parse.urlunsplit(
            (parsed.scheme.lower(), authority, parsed.path or "/", urllib.parse.urlencode(query), "")
        )
        return result[:4096]
    except (TypeError, ValueError):
        return "<invalid-url>"


def _request_headers(headers: Mapping[str, str]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    if len(headers or {}) > 32:
        raise HttpPolicyError("invalid_header", "Request contains too many headers")
    for raw_name, raw_value in (headers or {}).items():
        name = str(raw_name).strip()
        value = str(raw_value).strip()
        _reject_control_characters(name, code="invalid_header")
        _reject_control_characters(value, code="invalid_header")
        if (
            not name
            or len(name) > 128
            or len(value) > 4096
            or not _HEADER_NAME_RE.fullmatch(name)
        ):
            raise HttpPolicyError("invalid_header", "Request header is invalid")
        key = name.lower()
        if key in _FORBIDDEN_REQUEST_HEADERS:
            raise HttpPolicyError("forbidden_header", "Request contains a forbidden header")
        if key in cleaned:
            raise HttpPolicyError("invalid_header", "Request repeats a case-insensitive header")
        cleaned[key] = value
    cleaned.setdefault("accept-encoding", "gzip")
    cleaned.setdefault("connection", "close")
    return cleaned


def _header_map(headers: Iterable[tuple[str, str]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, value in headers:
        key = str(name).strip().lower()
        cleaned_value = str(value).strip()
        if key in result:
            if key in _SINGLETON_RESPONSE_HEADERS and result[key] != cleaned_value:
                raise HttpPolicyError(
                    "ambiguous_response_header",
                    "Response contains conflicting singleton headers",
                    status=598,
                )
            continue
        if key:
            result[key] = cleaned_value
    return result


def _declared_length(headers: Mapping[str, str]) -> Optional[int]:
    value = headers.get("content-length")
    if value is None:
        return None
    try:
        length = int(value)
    except (TypeError, ValueError) as error:
        raise HttpPolicyError("invalid_content_length", "Response Content-Length is invalid", status=598) from error
    if length < 0:
        raise HttpPolicyError("invalid_content_length", "Response Content-Length is invalid", status=598)
    return length


def _read_wire_body(
    response: http.client.HTTPResponse,
    limit: int,
    *,
    too_large_code: str,
) -> bytes:
    wire = bytearray()
    while True:
        remaining = limit - len(wire)
        chunk = response.read(min(64 * 1024, remaining + 1))
        if not chunk:
            break
        wire.extend(chunk)
        if len(wire) > limit:
            raise HttpPolicyError(too_large_code, "Response exceeds the wire-byte limit", status=596)
    return bytes(wire)


def decode_limited_body(
    wire_body: bytes,
    *,
    content_encoding: str,
    policy: HttpPolicy = DEFAULT_HTTP_POLICY,
) -> bytes:
    """Decode a body while enforcing independent wire, inflated, and final caps."""
    encoding = str(content_encoding or "identity").strip().lower()
    if encoding in {"", "identity"}:
        if len(wire_body) > policy.max_body_bytes:
            raise HttpPolicyError("body_too_large", "Response exceeds the body-byte limit", status=596)
        return wire_body
    if encoding != "gzip":
        raise HttpPolicyError("unsupported_content_encoding", "Response encoding is not supported", status=598)
    if len(wire_body) > policy.max_compressed_bytes:
        raise HttpPolicyError("compressed_body_too_large", "Response exceeds the compressed-byte limit", status=596)
    output_limit = min(policy.max_inflated_bytes, policy.max_body_bytes)
    output = bytearray()
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(wire_body), mode="rb") as stream:
            while True:
                chunk = stream.read(min(64 * 1024, output_limit - len(output) + 1))
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > output_limit:
                    code = (
                        "inflated_body_too_large"
                        if policy.max_inflated_bytes <= policy.max_body_bytes
                        else "body_too_large"
                    )
                    raise HttpPolicyError(code, "Inflated response exceeds the byte limit", status=596)
    except HttpPolicyError:
        raise
    except (EOFError, OSError) as error:
        raise HttpPolicyError("invalid_compressed_body", "Compressed response is invalid", status=598) from error
    return bytes(output)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, target: ValidatedTarget, *, timeout: float, context: ssl.SSLContext) -> None:
        super().__init__(target.host, target.port, timeout=timeout, context=context)
        self._validated_addresses = target.addresses
        self.peer_ip: Optional[str] = None

    def connect(self) -> None:
        last_error: Optional[OSError] = None
        for address in self._validated_addresses:
            raw: Optional[socket.socket] = None
            try:
                raw = socket.create_connection((address, self.port), self.timeout, self.source_address)
                self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
                self.peer_ip = address
                return
            except OSError as error:
                if raw is not None:
                    raw.close()
                last_error = error
        raise last_error or OSError("no validated address could be connected")


def _exchange_once(
    target: ValidatedTarget,
    headers: Mapping[str, str],
    timeout: float,
    policy: HttpPolicy,
) -> WireResponse:
    connection = _PinnedHTTPSConnection(target, timeout=timeout, context=ssl.create_default_context())
    timeout_guard = threading.Timer(timeout, connection.close)
    timeout_guard.daemon = True
    timeout_guard.start()
    try:
        connection.request("GET", target.request_target, headers=dict(headers))
        response = connection.getresponse()
        response_headers = _header_map(response.getheaders())
        if response.status in _REDIRECT_STATUSES:
            return WireResponse(
                status=response.status,
                headers=response_headers,
                body=b"",
                wire_bytes=0,
                inflated_bytes=0,
                wire_sha256=hashlib.sha256(b"").hexdigest(),
                peer_ip=connection.peer_ip,
            )
        encoding = response_headers.get("content-encoding", "identity").lower()
        if encoding not in {"", "identity", "gzip"}:
            raise HttpPolicyError(
                "unsupported_content_encoding",
                "Response encoding is not supported",
                status=598,
            )
        declared = _declared_length(response_headers)
        wire_limit = policy.max_compressed_bytes if encoding == "gzip" else policy.max_body_bytes
        if declared is not None and declared > wire_limit:
            code = "compressed_body_too_large" if encoding == "gzip" else "body_too_large"
            raise HttpPolicyError(code, "Declared response length exceeds the byte limit", status=596)
        too_large_code = "compressed_body_too_large" if encoding == "gzip" else "body_too_large"
        wire = _read_wire_body(response, wire_limit, too_large_code=too_large_code)
        body = decode_limited_body(wire, content_encoding=encoding, policy=policy)
        return WireResponse(
            status=response.status,
            headers=response_headers,
            body=body,
            wire_bytes=len(wire),
            inflated_bytes=len(body),
            wire_sha256=hashlib.sha256(wire).hexdigest(),
            peer_ip=connection.peer_ip,
        )
    finally:
        timeout_guard.cancel()
        connection.close()


def _resolver_with_timeout(resolver: Resolver, timeout: float) -> Resolver:
    """Bound blocking getaddrinfo without relying on process-global socket state."""

    def bounded(*args):
        if timeout <= 0:
            raise HttpPolicyError(
                "deadline_exceeded",
                "HTTP request deadline was exhausted during DNS resolution",
                status=599,
            )
        result: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

        def resolve() -> None:
            try:
                result.put((True, resolver(*args)))
            except Exception as error:  # noqa: BLE001 - relay resolver failures
                result.put((False, error))

        worker = threading.Thread(target=resolve, daemon=True)
        worker.start()
        try:
            ok, value = result.get(timeout=timeout)
        except queue.Empty as error:
            raise HttpPolicyError(
                "deadline_exceeded",
                "HTTP request deadline was exhausted during DNS resolution",
                status=599,
            ) from error
        if not ok:
            if isinstance(value, BaseException):
                raise value
            raise HttpPolicyError("dns_resolution_failed", "Public DNS resolution failed", status=599)
        return value

    return bounded


def request_https(
    url: str,
    headers: Mapping[str, str],
    *,
    timeout: float,
    deadline: Optional[float] = None,
    policy: HttpPolicy = DEFAULT_HTTP_POLICY,
    resolver: Resolver = socket.getaddrinfo,
    exchange: Exchange = _exchange_once,
    clock: Callable[[], float] = time.monotonic,
) -> PolicyResponse:
    """Perform one bounded logical GET, following only same-origin redirects."""
    if timeout <= 0:
        raise HttpPolicyError("invalid_timeout", "Request timeout must be positive")
    safe_headers = _request_headers(headers)
    initial = canonical_https_url(url, policy=policy)
    current_url = initial.url
    redirects: list[RedirectEvidence] = []
    absolute_deadline = (
        clock() + min(timeout, policy.max_request_seconds)
        if deadline is None
        else deadline
    )

    while True:
        remaining = absolute_deadline - clock()
        if remaining <= 0:
            raise HttpPolicyError("deadline_exceeded", "HTTP request deadline was exhausted", status=599)
        target = resolve_public_https_url(
            current_url,
            policy=policy,
            resolver=_resolver_with_timeout(resolver, remaining),
        )
        remaining = absolute_deadline - clock()
        if remaining <= 0:
            raise HttpPolicyError("deadline_exceeded", "HTTP request deadline was exhausted", status=599)
        request_timeout = min(timeout, policy.max_request_seconds, remaining)
        try:
            response = exchange(target, safe_headers, request_timeout, policy)
        except HttpPolicyError:
            raise
        except (OSError, TimeoutError, ssl.SSLError, http.client.HTTPException) as error:
            raise HttpPolicyError("transport_error", "HTTPS transport failed", status=599) from error
        response_headers = {str(name).lower(): str(value) for name, value in response.headers.items()}
        if response.status not in _REDIRECT_STATUSES:
            return PolicyResponse(
                status=response.status,
                url=target.url,
                headers=response_headers,
                body=response.body,
                wire_bytes=response.wire_bytes,
                inflated_bytes=response.inflated_bytes,
                wire_sha256=response.wire_sha256,
                peer_ip=response.peer_ip,
                redirects=tuple(redirects),
            )
        location = response_headers.get("location")
        if not location:
            raise HttpPolicyError("redirect_missing_location", "Redirect response has no Location", status=597)
        if len(redirects) >= policy.max_redirects:
            raise HttpPolicyError("redirect_limit", "HTTPS redirect limit exceeded", status=597)
        candidate = canonical_https_url(
            urllib.parse.urljoin(target.url, location),
            policy=policy,
        )
        if candidate.origin != initial.origin:
            raise HttpPolicyError("redirect_cross_origin", "Cross-origin redirects are not permitted", status=597)
        redirects.append(
            RedirectEvidence(status=response.status, source_url=target.url, target_url=candidate.url)
        )
        current_url = candidate.url
