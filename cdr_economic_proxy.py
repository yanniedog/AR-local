"""Proxy helpers for public macro-data API requests."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from http import HTTPStatus
from urllib.parse import urlencode


class ProxyUpstreamError(Exception):
    def __init__(self, status: int, body: bytes, content_type: str) -> None:
        super().__init__(f"upstream returned HTTP {status}")
        self.status = status
        self.body = body
        self.content_type = content_type


def proxy_upstream_get(upstream_base: str, path: str, query: dict[str, list[str]]) -> tuple[bytes, str]:
    upstream_path = path if path.startswith("/") else "/" + path
    qs = urlencode([(key, value) for key, values in query.items() for value in values], doseq=True)
    url = upstream_base + upstream_path + (("?" + qs) if qs else "")
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "Accept-Language": "en-AU,en;q=0.9",
            "User-Agent": "Mozilla/5.0 (compatible; AR-local Pi dashboard)",
        },
    )
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
