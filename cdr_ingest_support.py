"""Shared helpers for ``cdr_ingest_lib.py`` (register, HTTP, filesystem, classification)."""

from __future__ import annotations

import hashlib
import json
import random
import re
import secrets
import threading
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import cached_property
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from cdr_http_policy import (
    DEFAULT_HTTP_POLICY,
    HttpPolicyError,
    pagination_next_url,
    request_https,
)
from cdr_raw_attempt_journal import RawAttemptJournal, utc_now as attempt_utc_now

# -----------------------------------------------------------------------------
# Constants (mirror workers/api/src/ingest/cdr/discovery.ts + http.ts order)
# -----------------------------------------------------------------------------

REGISTER_URL_SUMMARY = (
    "https://api.cdr.gov.au/cdr-register/v1/all/data-holders/brands/summary"
)
REGISTER_URL_BANKING_BRANDS = (
    "https://api.cdr.gov.au/cdr-register/v1/banking/data-holders/brands"
)
REGISTER_URL_BANKING_REGISTER = (
    "https://api.cdr.gov.au/cdr-register/v1/banking/register"
)

# Bank PRD endpoints often negotiate newer x-v; CDR register currently responds at v2 in practice.
REGISTER_FETCH_VERSIONS = [2, 1, 6, 5, 4, 3]
CDR_VERSION_ORDER = [6, 5, 4, 3, 2, 1]

# WAFs in front of ~40 mutual-bank PRD endpoints reject urllib's default
# "Python-urllib/x.y" agent with HTML 403 pages (those banks then ingest zero
# products). Any honest non-default token passes — verified 2026-06-13 against
# P&N Bank, Teachers Mutual, Beyond Bank, UBank and Rabobank.
DEFAULT_USER_AGENT = "ar-local-cdr/1.0 (+https://github.com/yanniedog/AR-local)"

DATASET_CATEGORY_ALIASES: Dict[str, List[str]] = {
    "home_loans": [
        "RESIDENTIAL_MORTGAGES",
        "RESIDENTIAL_MORTGAGE",
        "MORTGAGES",
        "MORTGAGE",
        "HOME_LOANS",
        "HOME_LOAN",
    ],
    "savings": [
        "TRANS_AND_SAVINGS_ACCOUNTS",
        "TRANS_AND_SAVINGS_ACCOUNT",
        "TRANS_AND_SAVINGS",
        "SAVINGS_ACCOUNTS",
        "SAVINGS_ACCOUNT",
        "SAVINGS",
        "TRANSACTION_AND_SAVINGS_ACCOUNTS",
    ],
    "term_deposits": [
        "TERM_DEPOSITS",
        "TERM_DEPOSIT",
        "FIXED_TERM_DEPOSITS",
        "FIXED_TERM_DEPOSIT",
        "FIXED_DEPOSITS",
        "FIXED_DEPOSIT",
    ],
}

DATASET_TO_FOLDER = {
    "home_loans": "Mortgage",
    "savings": "Savings",
    "term_deposits": "TD",
}


@dataclass
class RegisterSnapshot:
    register_ok: bool
    register_provenance_complete: bool
    register_attempts: List[Dict[str, Any]]
    banking_brands: List[Dict[str, str]]
    banking_count_before_filter: int


# -----------------------------------------------------------------------------
# JSON primitives (subset of workers/api/src/ingest/cdr/primitives.ts)
# -----------------------------------------------------------------------------


def is_record(value: Any) -> bool:
    return isinstance(value, dict)


def as_array(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return []


def pick_text(record: Mapping[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        raw = record.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            return text
    return ""


def safe_url(value: str) -> str:
    return value.rstrip("/")


def has_cdr_errors(data: Any) -> bool:
    if not is_record(data):
        return False
    errs = data.get("errors")
    if isinstance(errs, list) and len(errs) > 0:
        return True
    ec = str(data.get("errorCode") or "").strip()
    em = str(data.get("errorMessage") or "").strip()
    return bool(ec or em)


def parse_supported_versions(body: str) -> List[int]:
    available = re.search(r"Versions available:\s*([0-9,\s]+)", body, re.I)
    if available:
        parts = [x.strip() for x in available.group(1).split(",")]
        out: List[int] = []
        for p in parts:
            if p.isdigit():
                out.append(int(p))
        return out

    range_m = re.search(
        r"Minimum version supported is\s*(\d+)\s*and\s*Maximum version supported is\s*(\d+)",
        body,
        re.I,
    )
    if not range_m:
        return []
    lo, hi = int(range_m.group(1)), int(range_m.group(2))
    if lo > hi:
        return []
    return list(range(hi, lo - 1, -1))


# -----------------------------------------------------------------------------
# Classification (mirror workers/api/src/ingest/cdr/product-classification.ts)
# -----------------------------------------------------------------------------


def normalize_category_token(value: str) -> str:
    text = str(value or "").strip().upper()
    text = re.sub(r"[^A-Z0-9]+", "_", text)
    return text.strip("_")


def normalize_cdr_product_category(value: Any) -> Optional[str]:
    token = normalize_category_token(str(value or ""))
    return token if token else None


def extract_cdr_product_category(product: Mapping[str, Any]) -> Optional[str]:
    raw = pick_text(product, ["productCategory", "category", "type"])
    return normalize_cdr_product_category(raw)


def dataset_from_cdr_category(category: Optional[str]) -> Optional[str]:
    normalized = normalize_cdr_product_category(category or "")
    if not normalized:
        return None
    for dataset, aliases in DATASET_CATEGORY_ALIASES.items():
        if normalized in aliases:
            return dataset
    if "MORTGAGE" in normalized or "HOME_LOAN" in normalized:
        return "home_loans"
    if "TERM_DEPOSIT" in normalized or "FIXED_DEPOSIT" in normalized:
        return "term_deposits"
    if "SAVINGS" in normalized or "TRANS_AND_SAVINGS" in normalized:
        return "savings"
    return None


def has_mortgage_structured_signals(product: Mapping[str, Any]) -> bool:
    rates = [x for x in as_array(product.get("lendingRates")) if is_record(x)]
    if not rates:
        return False
    for rate in rates:
        if not is_record(rate):
            continue
        lp = pick_text(rate, ["loanPurpose"])
        rt = pick_text(rate, ["repaymentType"])
        lrt = pick_text(rate, ["lendingRateType"])
        if lp or rt or lrt:
            return True
    return False


def has_deposit_structured_signals(product: Mapping[str, Any]) -> bool:
    dr = [x for x in as_array(product.get("depositRates")) if is_record(x)]
    if dr:
        return True
    generic = [x for x in as_array(product.get("rates")) if is_record(x)]
    for rate in generic:
        if not is_record(rate):
            continue
        dt = pick_text(rate, ["depositRateType", "rateType"])
        at = pick_text(rate, ["applicationType", "rateApplicabilityType"])
        if dt or at:
            return True
    return False


def infer_dataset_from_structured_signals(product: Mapping[str, Any]) -> Optional[str]:
    if has_mortgage_structured_signals(product):
        return "home_loans"
    if has_deposit_structured_signals(product):
        cat_ds = dataset_from_cdr_category(extract_cdr_product_category(product))
        if cat_ds:
            return cat_ds
        return "savings"
    return None


def infer_dataset_from_name(product: Mapping[str, Any]) -> Optional[str]:
    name = pick_text(product, ["name", "productName"]).upper()
    if not name:
        return None
    if "MORTGAGE" in name or "HOME LOAN" in name:
        return "home_loans"
    if "TERM DEPOSIT" in name or "FIXED DEPOSIT" in name:
        return "term_deposits"
    if "SAVINGS" in name or "SAVER" in name or "AT CALL" in name:
        return "savings"
    return None


def infer_cdr_dataset(
    product: Mapping[str, Any],
    *,
    allow_name_fallback: bool = True,
) -> Optional[str]:
    cat_ds = dataset_from_cdr_category(extract_cdr_product_category(product))
    if cat_ds:
        return cat_ds
    structured = infer_dataset_from_structured_signals(product)
    if structured:
        return structured
    if not allow_name_fallback:
        return None
    return infer_dataset_from_name(product)


def detail_inner_record(parsed: Any) -> Optional[Dict[str, Any]]:
    if not is_record(parsed):
        return None
    inner = parsed.get("data")
    if is_record(inner):
        return inner
    return parsed  # type: ignore[return-value]


# -----------------------------------------------------------------------------
# Register + product list parsing (discovery.ts)
# -----------------------------------------------------------------------------


def normalize_banking_products_url(endpoint_raw: str) -> str:
    raw = str(endpoint_raw or "").strip()
    if "/cds-au/v1/banking/products" in raw:
        return safe_url(raw.split("?")[0])
    return safe_url(raw) + "/cds-au/v1/banking/products"


def iter_banking_brands_from_payload(payload: Any) -> Iterable[Dict[str, str]]:
    """Yield banking PRD brand rows from one register payload."""
    if is_record(payload):
        data_array = as_array(payload.get("data"))
    else:
        data_array = as_array(payload)

    for item in data_array:
        if not is_record(item):
            continue
        industries_list = as_array(item.get("industries"))
        if industries_list:
            brand_name = pick_text(item, ["brandName", "dataHolderBrandName"])
            legal_entity = item.get("legalEntity")
            legal_name = ""
            if is_record(legal_entity):
                legal_name = pick_text(legal_entity, ["legalEntityName"])
            base = pick_text(item, ["productBaseUri", "publicBaseUri"])
            if not base:
                continue
            inds = {str(x).strip().lower() for x in industries_list}
            if "banking" in inds:
                yield {
                    "brand_name": brand_name,
                    "legal_entity_name": legal_name,
                    "endpoint_url": normalize_banking_products_url(base),
                }
            continue

        # Legacy register row (e.g. banking data-holders/brands) — no industries array.
        endpoint_detail = item.get("endpointDetail")
        ed: Mapping[str, Any] = endpoint_detail if is_record(endpoint_detail) else {}
        endpoint_raw = (
            pick_text(ed, ["productReferenceDataApi", "publicBaseUri", "resourceBaseUri"])
            or pick_text(item, ["publicBaseUri", "resourceBaseUri", "productBaseUri"])
        )
        if not endpoint_raw:
            continue
        brand_name = pick_text(item, ["brandName", "dataHolderBrandName"])
        legal_entity = item.get("legalEntity")
        legal_name = ""
        if is_record(legal_entity):
            legal_name = pick_text(legal_entity, ["legalEntityName"])
        endpoint_url = normalize_banking_products_url(endpoint_raw)
        yield {
            "brand_name": brand_name,
            "legal_entity_name": legal_name,
            "endpoint_url": endpoint_url,
        }


def extract_products(payload: Any) -> List[Dict[str, Any]]:
    if not is_record(payload):
        return []
    data = payload.get("data")
    if is_record(data):
        inner = data.get("products")
        seq = as_array(inner)
    else:
        seq = as_array(data)
    return [x for x in seq if is_record(x)]


def next_link(payload: Any, current_url: str) -> Optional[str]:
    if not is_record(payload):
        return None
    links = payload.get("links")
    if not is_record(links):
        return None
    nxt = str(links.get("next") or "").strip()
    if not nxt:
        return None
    return pagination_next_url(current_url, nxt)


# -----------------------------------------------------------------------------
# HTTP (mirror workers/api/src/ingest/cdr/http.ts fetchCdrJson / fetchJson)
# -----------------------------------------------------------------------------


@dataclass
class FetchResult:
    ok: bool
    status: int
    url: str
    text: str
    attempts: int = 1
    # Server-requested backoff (seconds, capped) from the last retryable response,
    # so a caller that switches strategy (e.g. version negotiation) can still honor
    # it even when this fetch had no same-version retry budget.
    retry_after: Optional[float] = None
    # The CDR x-v version that produced a successful fetch, so a caller can cache it
    # per holder and try it first instead of re-negotiating from the top each time.
    version: Optional[int] = None

    @cached_property
    def data(self) -> Any:
        if not self.text:
            return None
        try:
            return json.loads(self.text)
        except json.JSONDecodeError:
            return None


# Cap a server-requested Retry-After: an absurd or malicious value must not be
# able to park an ingest worker thread (and starve the pool) for a long time.
MAX_RETRY_AFTER_SECONDS = DEFAULT_HTTP_POLICY.max_retry_after_seconds


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Parse a Retry-After header (delta-seconds or HTTP-date) to seconds-from-now.

    Returns None when absent/unparseable; an already-elapsed HTTP-date clamps to 0;
    the result is capped at MAX_RETRY_AFTER_SECONDS so a huge value can't hang the
    worker pool.
    """
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return min(float(value), MAX_RETRY_AFTER_SECONDS)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    secs = max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
    return min(secs, MAX_RETRY_AFTER_SECONDS)


def http_request(
    url: str,
    headers: Dict[str, str],
    *,
    timeout: float,
    attempt_journal: Optional[RawAttemptJournal] = None,
    attempt_key: Optional[str] = None,
    attempt_context: Optional[Mapping[str, Any]] = None,
) -> Tuple[int, str, Optional[float]]:
    """GET ``url``; return (status, body, retry_after_seconds). retry_after is the
    parsed Retry-After header (None when absent), surfaced so the caller can honor
    a server-requested backoff on 429/503."""
    request_headers = {"User-Agent": DEFAULT_USER_AGENT, **(headers or {})}
    started_at = attempt_utc_now()
    response_headers: Mapping[str, str] = {}
    body = b""
    wire_bytes = 0
    inflated_bytes = 0
    wire_sha256 = hashlib.sha256(b"").hexdigest()
    peer_ip: Optional[str] = None
    redirects: Iterable[Any] = ()
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    try:
        response = request_https(url, request_headers, timeout=timeout)
        status = response.status
        response_headers = response.headers
        body = response.body
        wire_bytes = response.wire_bytes
        inflated_bytes = response.inflated_bytes
        wire_sha256 = response.wire_sha256
        peer_ip = response.peer_ip
        redirects = response.redirects
        retry_after = _parse_retry_after(response.headers.get("retry-after"))
        text = body.decode("utf-8", errors="replace")
        outcome = "success" if status < 400 else "http_error"
    except HttpPolicyError as error:
        status = error.status
        retry_after = None
        text = f"{error.code}: {error.public_message}"
        error_code = error.code
        error_message = error.public_message
        outcome = "transport_error" if status == 599 else "policy_rejected"

    completed_at = attempt_utc_now()
    if attempt_journal is not None:
        key = attempt_key or hashlib.sha256(
            f"{started_at}\0{url}".encode("utf-8")
        ).hexdigest()
        attempt_journal.record(
            key,
            request_url=url,
            request_headers=request_headers,
            started_at=started_at,
            completed_at=completed_at,
            status=status,
            outcome=outcome,
            response_headers=response_headers,
            body=body,
            wire_bytes=wire_bytes,
            inflated_bytes=inflated_bytes,
            wire_sha256=wire_sha256,
            peer_ip=peer_ip,
            redirects=redirects,
            retry_after_seconds=retry_after,
            error_code=error_code,
            error_message=error_message,
            context=attempt_context,
        )
    return status, text, retry_after


def fetch_with_retries(
    url: str,
    headers: Dict[str, str],
    *,
    timeout: float,
    max_retries: int,
    sleep_ms: int,
    retry_on: Callable[[int], bool],
    deadline: Optional[float] = None,
    attempt_journal: Optional[RawAttemptJournal] = None,
    attempt_context: Optional[Mapping[str, Any]] = None,
) -> FetchResult:
    attempt = 0
    last_status = 0
    last_text = ""
    last_retry_after: Optional[float] = None
    max_retries = max(0, min(int(max_retries), DEFAULT_HTTP_POLICY.max_retries))
    timeout = max(0.001, min(float(timeout), DEFAULT_HTTP_POLICY.max_request_seconds))
    if deadline is None:
        deadline = time.monotonic() + DEFAULT_HTTP_POLICY.max_logical_fetch_seconds
    fetch_nonce = secrets.token_hex(8) if attempt_journal is not None else ""
    # Check the shared deadline before every request, so a logical fetch never
    # issues an upstream call (nor sleeps) past its wall-clock budget.
    while attempt <= max_retries and (deadline is None or time.monotonic() < deadline):
        # Cap each request's own timeout to the time left on the shared deadline,
        # so a single slow request can't block past the logical-fetch budget.
        req_timeout = timeout
        if deadline is not None:
            req_timeout = min(timeout, max(0.0, deadline - time.monotonic()))
            if req_timeout <= 0:
                break
        attempt += 1
        if attempt_journal is None:
            status, text, retry_after = http_request(url, headers, timeout=req_timeout)
        else:
            context = dict(attempt_context or {})
            context["retry_ordinal"] = attempt
            request_key = str(context.get("request_id") or url)
            status, text, retry_after = http_request(
                url,
                headers,
                timeout=req_timeout,
                attempt_journal=attempt_journal,
                attempt_key=f"{request_key}|{fetch_nonce}|{attempt}",
                attempt_context=context,
            )
        last_status, last_text = status, text
        last_retry_after = retry_after
        if status < 400 or not retry_on(status):
            return FetchResult(
                ok=status < 400,
                status=status,
                url=url,
                text=text,
                attempts=attempt,
                retry_after=retry_after,
            )
        if attempt > max_retries:
            break
        # backoff + jitter, capped so a sleep never overshoots the deadline.
        base = min(2 ** (attempt - 1), 32)
        delay = base + random.uniform(0, 0.25 * base) + sleep_ms / 1000.0
        # Honor a server-provided Retry-After (429/503) when it asks for at least
        # as long as our backoff — never wait less than the server requested.
        if retry_after is not None:
            delay = max(delay, retry_after)
        if deadline is not None:
            delay = min(delay, max(0.0, deadline - time.monotonic()))
            if delay <= 0:
                break
        time.sleep(delay)
    return FetchResult(
        ok=False, status=last_status, url=url, text=last_text, attempts=attempt,
        retry_after=last_retry_after,
    )


def retryable_status(status: int) -> bool:
    if status in {408, 425, 429, 599}:
        return True
    # Preserve retry coverage for upstream 5xx responses. Locally generated
    # 596-598 policy failures are deterministic and must fail closed immediately.
    return 500 <= status <= 595


def fetch_json_plain(
    url: str,
    *,
    timeout: float,
    max_retries: int,
    sleep_ms: int,
    attempt_journal: Optional[RawAttemptJournal] = None,
    attempt_context: Optional[Mapping[str, Any]] = None,
) -> FetchResult:
    headers = {"Accept": "application/json"}
    return fetch_with_retries(
        url,
        headers,
        timeout=timeout,
        max_retries=max_retries,
        sleep_ms=sleep_ms,
        retry_on=retryable_status,
        attempt_journal=attempt_journal,
        attempt_context=attempt_context,
    )


def fetch_cdr_json(
    url: str,
    *,
    versions: Optional[List[int]] = None,
    timeout: float,
    max_retries: int,
    sleep_ms: int,
    max_total_attempts: Optional[int] = None,
    max_total_seconds: Optional[float] = None,
    attempt_journal: Optional[RawAttemptJournal] = None,
    attempt_context: Optional[Mapping[str, Any]] = None,
) -> FetchResult:
    order = list(versions or CDR_VERSION_ORDER)
    # ONE shared budget for the whole logical fetch. The old code gave every
    # version its own full retry budget and then walked them all a second time, so
    # a persistent outage produced len(versions) * (max_retries + 1) upstream hits
    # (6 * 7 = 42). The budget still lets the preferred version absorb transient
    # 5xx AND lets the walk negotiate down through other versions (406, or a holder
    # that 422/500s on one version but serves another) - it just caps the total.
    if max_total_attempts is None:
        max_total_attempts = max(max_retries + 1, len(CDR_VERSION_ORDER) + 2)
    # A caller may pass 0 to mean "make no request" (e.g. an exhausted quota); a
    # negative value is clamped to 0. None means "use the default budget" above.
    remaining = min(
        max(0, int(max_total_attempts)),
        DEFAULT_HTTP_POLICY.max_total_attempts,
    )
    total_seconds = (
        DEFAULT_HTTP_POLICY.max_logical_fetch_seconds
        if max_total_seconds is None
        else min(
            max(0.0, float(max_total_seconds)),
            DEFAULT_HTTP_POLICY.max_logical_fetch_seconds,
        )
    )
    deadline = time.monotonic() + total_seconds

    # Requested order first, then any remaining known versions as a fallback
    # (preserving the old two-pass coverage), then 406-advertised ones.
    queue: List[int] = list(order)
    for fb in CDR_VERSION_ORDER:
        if fb not in queue:
            queue.append(fb)
    tried: Set[int] = set()
    total_attempts = 0

    def hdr(v: int) -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "x-v": str(v),
            "x-min-v": str(v),
        }

    last: Optional[FetchResult] = None
    while queue and remaining > 0 and (deadline is None or time.monotonic() < deadline):
        v = queue.pop(0)
        if v in tried:
            continue
        tried.add(v)
        # Reserve one attempt for each version we still intend to try, so a
        # retryable 5xx on the preferred version can't consume the whole budget
        # and starve a lower version the holder actually serves (a holder-specific
        # case this change explicitly preserves).
        pending = sum(1 for x in queue if x not in tried)
        reserve = min(pending, remaining - 1)
        per_version_retries = min(max_retries, max(0, remaining - reserve - 1))
        res = fetch_with_retries(
            url,
            hdr(v),
            timeout=timeout,
            max_retries=per_version_retries,
            sleep_ms=sleep_ms,
            retry_on=retryable_status,
            deadline=deadline,
            attempt_journal=attempt_journal,
            attempt_context={
                **dict(attempt_context or {}),
                "cdr_version": v,
            },
        )
        remaining -= res.attempts
        total_attempts += res.attempts
        last = res
        data = res.data
        if res.ok and data is not None and not has_cdr_errors(data):
            return FetchResult(
                ok=True, status=res.status, url=url, text=res.text,
                attempts=total_attempts, version=v,
            )

        if res.status == 406:
            for x in parse_supported_versions(res.text):
                if x not in tried and x not in queue:
                    queue.append(x)

        # Pace version switches on a retryable failure so the shared-budget walk
        # doesn't burst against a rate-limited / failing holder. Honor the server's
        # Retry-After here too (capped at MAX_RETRY_AFTER_SECONDS), since the
        # per-version probe may have had no same-version retry budget to apply it
        # (Codex): without this a 429/503 + Retry-After would be re-probed on the
        # next x-v after only the ~0.25s pace. Still capped by the deadline.
        if retryable_status(res.status) and queue and remaining > 0:
            pace = max(sleep_ms / 1000.0, 0.25)
            if res.retry_after:
                pace = max(pace, res.retry_after)
            if deadline is not None:
                pace = min(pace, max(0.0, deadline - time.monotonic()))
            if pace > 0:
                time.sleep(pace)

    if last is None:
        return FetchResult(ok=False, status=0, url=url, text="", attempts=total_attempts)
    return FetchResult(ok=False, status=last.status, url=url, text=last.text, attempts=total_attempts)


# -----------------------------------------------------------------------------
# Filesystem
# -----------------------------------------------------------------------------

INVALID_PATH_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_path_component(name: str, fallback: str = "_") -> str:
    text = str(name or "").strip()
    text = INVALID_PATH_CHARS.sub("_", text)
    text = text.strip(" .")
    return text if text else fallback


# Device filenames reserved on Windows (stem match).
_WIN_RESERVED_STEMS = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def filesystem_product_id_directory(product_id: str) -> str:
    """Directory name under the product leaf: sanitized id + hash suffix (paths/col/reserved-safe)."""
    raw = str(product_id or "").strip()
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    base = sanitize_path_component(raw, fallback="_")
    if base in (".", ".."):
        base = "_"
    stem = base.upper().split(".", 1)[0]
    if stem in _WIN_RESERVED_STEMS:
        base = f"id_{base}"
    # Keep segment short for nested Windows paths; hash preserves uniqueness.
    if len(base) > 80:
        base = base[:80].rstrip(" .")
        if not base:
            base = "_"
    return f"{base}__{digest}"


def host_token(endpoint_url: str) -> str:
    try:
        host = urllib.parse.urlparse(endpoint_url).hostname or ""
    except Exception:
        host = ""
    host = host.lower().replace(".", "_")
    return sanitize_path_component(host, "_host")


def allocate_bank_dir(
    brand_name: str,
    legal_name: str,
    endpoint_url: str,
    seen_base: Set[str],
) -> str:
    base = sanitize_path_component(brand_name or legal_name or "unknown_bank")
    candidate = base
    suffix = host_token(endpoint_url)
    if candidate not in seen_base:
        seen_base.add(candidate)
        return candidate
    candidate = f"{base}_{suffix}"
    n = 2
    while candidate in seen_base:
        candidate = f"{base}_{suffix}_{n}"
        n += 1
    seen_base.add(candidate)
    return candidate


def append_failure(
    date_root: Path,
    row: Dict[str, Any],
    *,
    lock: Optional[threading.Lock] = None,
) -> None:
    def _write() -> None:
        path = date_root / "failures.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    if lock is not None:
        with lock:
            _write()
    else:
        _write()


def summarize_failures(date_root: Path) -> Dict[str, Any]:
    """Roll up ``failures.jsonl`` into an ingest-status summary.

    Lets the daily run / monitoring detect an INCOMPLETE ingest (some holders or
    products failed, or a holder's circuit breaker opened) from one small file
    instead of parsing every failure record. Counts by ``phase`` and ``status``
    (so e.g. ``circuit_open`` skips are visible distinctly from HTTP errors).
    """
    by_phase: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    by_provider: Dict[str, int] = {}
    total = 0
    corrupt_records = 0
    unattributed_records = 0
    failure_log_readable = False
    try:
        handle = (date_root / "failures.jsonl").open(encoding="utf-8")
    except OSError:
        handle = None
    if handle is not None:
        failure_log_readable = True
        with handle:
            # Stream line-by-line so a large failures log stays memory-bounded.
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    corrupt_records += 1
                    continue
                # A valid-but-non-object JSON line (list/str/number) would crash on
                # rec.get; skip it rather than fail the whole run at the very end.
                if not isinstance(rec, dict):
                    corrupt_records += 1
                    continue
                total += 1
                phase = str(rec.get("phase") or "unknown")
                status = "unknown" if rec.get("status") is None else str(rec.get("status"))
                provider_value = rec.get("bank")
                provider = (
                    str(provider_value).strip() if provider_value is not None else ""
                )
                if not provider:
                    unattributed_records += 1
                    provider = "unknown"
                by_phase[phase] = by_phase.get(phase, 0) + 1
                by_status[status] = by_status.get(status, 0) + 1
                by_provider[provider] = by_provider.get(provider, 0) + 1
    return {
        "total": total,
        "corrupt_records": corrupt_records,
        "unattributed_records": unattributed_records,
        "failure_log_readable": failure_log_readable,
        "failure_provenance_complete": (
            failure_log_readable
            and corrupt_records == 0
            and unattributed_records == 0
        ),
        "incomplete": (
            not failure_log_readable
            or total > 0
            or corrupt_records > 0
            or unattributed_records > 0
        ),
        "by_phase": by_phase,
        "by_status": by_status,
        "by_provider": by_provider,
    }


# -----------------------------------------------------------------------------
# Core ingest
# -----------------------------------------------------------------------------


def collect_register_snapshot(
    *,
    timeout: float,
    max_retries: int,
    sleep_ms: int,
    holders_filter: Optional[str],
    attempt_journal: Optional[RawAttemptJournal] = None,
) -> RegisterSnapshot:
    """Merge banking holder rows from all register URLs."""
    merged_banking: Dict[Tuple[str, str, str], Dict[str, str]] = {}
    register_payload_ok = False
    register_attempts: List[Dict[str, Any]] = []

    attempts: List[Tuple[str, str]] = [
        (REGISTER_URL_SUMMARY, "cdr"),
        (REGISTER_URL_BANKING_BRANDS, "plain"),
        (REGISTER_URL_BANKING_REGISTER, "plain"),
    ]

    for source_index, (url, mode) in enumerate(attempts, start=1):
        attempt_context = {
            "phase": "register_discovery",
            "source_index": source_index,
            "mode": mode,
            "request_id": f"register:{source_index}:{mode}",
        }
        res = (
            fetch_cdr_json(
                url,
                versions=REGISTER_FETCH_VERSIONS,
                timeout=timeout,
                max_retries=max_retries,
                sleep_ms=sleep_ms,
                attempt_journal=attempt_journal,
                attempt_context=attempt_context,
            )
            if mode == "cdr"
            else fetch_json_plain(
                url,
                timeout=timeout,
                max_retries=max_retries,
                sleep_ms=sleep_ms,
                attempt_journal=attempt_journal,
                attempt_context=attempt_context,
            )
        )
        data = res.data
        attempt_ok = res.ok and data is not None and not has_cdr_errors(data)
        register_attempts.append(
            {
                "source_url": url,
                "mode": mode,
                "ok": attempt_ok,
                "status": res.status,
                "bytes": len((res.text or "").encode("utf-8")),
                "sha256": hashlib.sha256((res.text or "").encode("utf-8")).hexdigest(),
            }
        )
        if not attempt_ok:
            continue
        register_payload_ok = True
        for b in iter_banking_brands_from_payload(data):
            key = (
                b["endpoint_url"].lower(),
                (b["brand_name"] or "").lower(),
                (b["legal_entity_name"] or "").lower(),
            )
            merged_banking[key] = b

    banking_all = list(merged_banking.values())
    count_banking = len(banking_all)

    if holders_filter:
        hf = holders_filter.lower()

        def filt(bl: List[Dict[str, str]]) -> List[Dict[str, str]]:
            return [
                b
                for b in bl
                if hf in (b["brand_name"] or "").lower()
                or hf in (b["legal_entity_name"] or "").lower()
                or hf in (b["endpoint_url"] or "").lower()
            ]

        banking_brands = filt(banking_all)
    else:
        banking_brands = banking_all

    banking_brands.sort(
        key=lambda x: (x["brand_name"] or x["legal_entity_name"] or "").lower(),
    )
    return RegisterSnapshot(
        register_ok=register_payload_ok,
        register_provenance_complete=all(
            attempt["ok"] for attempt in register_attempts
        ),
        register_attempts=register_attempts,
        banking_brands=banking_brands,
        banking_count_before_filter=count_banking,
    )

