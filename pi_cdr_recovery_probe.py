"""Small, bounded public GET probes; these never claim a complete capture."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace
from urllib.parse import quote, urlsplit, urlunsplit

from cdr_compatibility import classify_fetch_failure, parse_supported_versions, response_shape_error
from cdr_http_policy import (
    DEFAULT_HTTP_POLICY, HttpPolicyError, canonical_https_url, pagination_next_url,
    request_https, sanitize_url,
)
from cdr_ingest_support import (
    DEFAULT_USER_AGENT, REGISTER_URL_SUMMARY, has_cdr_errors,
    allocate_bank_dir, iter_banking_brands_from_payload,
)

PROBE_HTTP_POLICY = replace(
    DEFAULT_HTTP_POLICY, max_redirects=1, max_request_seconds=8,
    max_logical_fetch_seconds=12, max_total_attempts=2,
    max_compressed_bytes=2 * 1024 * 1024, max_inflated_bytes=2 * 1024 * 1024,
    max_body_bytes=2 * 1024 * 1024,
)


def probe_request(url: str, *, phase: str, product_id: str = "", deadline: float,
                  version_offset: int = 0) -> dict:
    versions = [2, 1] if phase == "register_discovery" else ([6, 5, 4, 3, 2, 1] if phase == "products_index" else [7, 6, 5, 4, 3, 2, 1])
    offset = version_offset % len(versions)
    versions = versions[offset:] + versions[:offset]
    stop = min(deadline, time.monotonic() + PROBE_HTTP_POLICY.max_logical_fetch_seconds)
    attempts = []
    attempted_versions = set()
    while versions and len(attempts) < 2 and time.monotonic() < stop:
        version = versions.pop(0)
        if version in attempted_versions:
            continue
        attempted_versions.add(version)
        try:
            response = request_https(
                url, {"Accept": "application/json", "User-Agent": DEFAULT_USER_AGENT,
                      "x-v": str(version), "x-min-v": str(version)},
                timeout=min(8.0, max(0.001, stop - time.monotonic())),
                deadline=stop, policy=PROBE_HTTP_POLICY,
            )
            body = response.body
            status = response.status
            try:
                data = json.loads(body)
            except (UnicodeError, ValueError):
                data = None
            shape_error = response_shape_error(data, phase=phase, product_id=product_id)
            valid = status == 200 and not has_cdr_errors(data) and shape_error is None
            attempt = {"status": status, "version": version, "body_bytes": len(body),
                       "body_sha256": hashlib.sha256(body).hexdigest(), "valid": valid}
            attempts.append(attempt)
            if valid:
                return {"ok": True, "url": sanitize_url(url), "attempts": attempts,
                        "body_sha256": attempt["body_sha256"], "data": data,
                        "complete_capture": False}
            text = body.decode("utf-8", errors="replace")
            failure = classify_fetch_failure(status, text)
            attempt["failure_category"] = failure.category
            if shape_error:
                attempt["validation_error"] = shape_error
            if failure.category == "incompatible_version":
                versions = [v for v in parse_supported_versions(text) if v not in attempted_versions] + versions
            if not failure.negotiate:
                break
        except HttpPolicyError as error:
            attempts.append({"status": error.status, "version": version,
                             "failure_category": error.code, "valid": False})
            break
    return {"ok": False, "url": sanitize_url(url), "attempts": attempts,
            "complete_capture": False}


def probe_register(*, deadline: float) -> tuple[dict, list[dict]]:
    report = probe_request(REGISTER_URL_SUMMARY, phase="register_discovery", deadline=deadline)
    data = report.pop("data", None)
    brands = list(iter_banking_brands_from_payload(data)) if report["ok"] else []
    if not brands:
        report.update(ok=False, failure_category="register_population_unavailable")
    return report, brands


def current_target_url(request: dict, provider: dict, brands: list[dict]) -> str:
    """Use the fresh register; endpoint changes require a unique identity match."""
    identity = tuple(" ".join(str(provider.get(key) or "").split()).casefold()
                     for key in ("brand_name", "legal_entity_name"))
    if not any(identity):
        raise ValueError("provider identity unavailable")
    matches = [row for row in brands if tuple(" ".join(str(row.get(key) or "").split()).casefold()
               for key in ("brand_name", "legal_entity_name")) == identity]
    if len(matches) != 1:
        raise ValueError("fresh register provider identity is missing or ambiguous")
    seen = set()
    for row in sorted(brands, key=lambda value: (value.get("brand_name") or value.get("legal_entity_name") or "").lower()):
        directory = allocate_bank_dir(str(row.get("brand_name") or ""), str(row.get("legal_entity_name") or ""),
                                      str(row.get("endpoint_url") or ""), seen)
        if row is matches[0] and directory != provider.get("provider_dir"):
            raise ValueError("fresh register changed the provider directory identity")
    base = canonical_https_url(matches[0]["endpoint_url"]).url.rstrip("/")
    if request["phase"] != "products_index":
        if not request.get("product_id"):
            raise ValueError("detail probe lacks product identity")
        return base + "/" + quote(request["product_id"], safe="")
    prior = canonical_https_url(str(provider["endpoint_url"])).url.rstrip("/")
    original = pagination_next_url(prior, str(request.get("url") or prior))
    old_parts, original_parts, new_parts = urlsplit(prior), urlsplit(original), urlsplit(base)
    if not original_parts.path.startswith(old_parts.path):
        if base != prior:
            raise ValueError("changed endpoint cannot resolve its old pagination path")
        return original
    suffix = original_parts.path[len(old_parts.path):]
    if suffix and not suffix.startswith("/"):
        raise ValueError("probe path is outside the product-index endpoint")
    return urlunsplit((new_parts.scheme, new_parts.netloc, new_parts.path + suffix,
                       original_parts.query, ""))
