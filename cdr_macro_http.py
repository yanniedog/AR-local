"""Bounded transport for the two official macro-data hosts."""
from __future__ import annotations

import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

HTTP_TIMEOUT_SECONDS = 12.0
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
ALLOWED_HOSTS = frozenset({"www.rba.gov.au", "data.api.abs.gov.au"})
USER_AGENT = "Mozilla/5.0 (compatible; AR-local macro ingest)"


def _validate_url(url: str) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("macro source must be an approved public HTTPS endpoint")


class _OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_url(url: str, accept: str = "text/csv") -> str:
    """At most two attempts, finite response size, and no untrusted redirects."""
    _validate_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    opener = urllib.request.build_opener(_OfficialRedirect())
    for attempt in range(2):
        try:
            with opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                data = response.read(MAX_RESPONSE_BYTES + 1)
            if len(data) > MAX_RESPONSE_BYTES:
                raise ValueError("macro source exceeds the response byte budget")
            return data.decode("utf-8-sig")
        except urllib.error.HTTPError as exc:
            if attempt or exc.code not in {408, 429, 500, 502, 503, 504}:
                raise
            try:
                delay = min(5.0, max(1.0, float(exc.headers.get("Retry-After", "1"))))
            except (TypeError, ValueError):
                delay = 1.0
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt:
                raise
            delay = 1.0
        time.sleep(delay)
    raise RuntimeError("macro transport exhausted its retry budget")
