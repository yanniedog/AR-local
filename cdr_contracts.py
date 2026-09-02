"""Small, normative identities and scalar parsers for CDR observations."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable
from urllib.parse import urlsplit


DATASETS = ("Mortgage", "Savings", "TD")
PROVIDER_UID_PATTERN = (
    r"^(?:provider(?:-fallback)?:v1|provider(?:-interim)?:v2):[0-9a-f]{64}$"
)
PROVIDER_UID_RE = re.compile(PROVIDER_UID_PATTERN)
_ASCII_SPACE = re.compile(r"[\t\n\v\f\r ]+")


def canonical_json_bytes(value: Any) -> bytes:
    """Return the single byte representation used for hashes and sidecars."""

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def parse_rate_string(value: Any) -> str:
    """Validate a CDR ``RateString`` without inferring or changing its unit."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("CDR rate must be a non-empty RateString")
    try:
        number = Decimal(value.strip())
    except InvalidOperation as error:
        raise ValueError("CDR rate must be a finite decimal") from error
    if not number.is_finite() or number < 0 or number > 1:
        raise ValueError("CDR rate must be between 0 and 1 in decimal form")
    rendered = format(number, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in {"", "-0"} else rendered


def _display_name(value: str) -> str:
    normalized = unicodedata.normalize("NFC", str(value or "")).strip()
    return _ASCII_SPACE.sub(" ", normalized)


def canonical_authority(urls: Iterable[str]) -> str:
    """Choose the stable HTTPS ``host[:port]`` authority for fallback identity."""

    authorities: set[str] = set()
    for raw in urls:
        try:
            parsed = urlsplit(str(raw or "").strip())
            host = (parsed.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
            port = parsed.port
        except (UnicodeError, ValueError):
            continue
        if parsed.scheme.lower() != "https" or not host:
            continue
        authorities.add(host if port in (None, 443) else f"{host}:{port}")
    if not authorities:
        raise ValueError("fallback provider identity requires an HTTPS authority")
    return min(authorities)


def provider_uid(
    *,
    data_holder_id: str | None,
    data_holder_brand_id: str | None,
    interim_id: str | None = None,
    endpoint_urls: Iterable[str],
    display_name: str,
) -> tuple[str, str]:
    """Return a stable UID from the strongest Register identity available.

    The current summary supplies ``dataHolderBrandId`` but not ``dataHolderId``;
    requiring both would incorrectly downgrade almost every live brand. A brand
    ID identifies the PRD provider directly. The one transitional brand without
    it is bound to its Register ``interimId`` and disclosed as interim.
    """

    del data_holder_id
    brand = str(data_holder_brand_id or "").strip().casefold()
    if brand:
        digest = hashlib.sha256(
            canonical_json_bytes(["identity-v2", "provider-brand", brand])
        ).hexdigest()
        return f"provider:v2:{digest}", "official_brand"
    interim = str(interim_id or "").strip().casefold()
    if interim:
        digest = hashlib.sha256(
            canonical_json_bytes(["identity-v2", "provider-interim", interim])
        ).hexdigest()
        return f"provider-interim:v2:{digest}", "registry_interim"
    name = _display_name(display_name)
    if not name:
        raise ValueError("fallback provider identity requires a display name")
    authority = canonical_authority(endpoint_urls)
    digest = hashlib.sha256(
        canonical_json_bytes(["provider-fallback-v1", authority, name])
    ).hexdigest()
    return f"provider-fallback:v1:{digest}", "fallback"


def product_uid(provider: str, dataset: str, cdr_product_id: str) -> str:
    """Return the normative product identity, stable across names and categories."""

    provider = str(provider or "").strip()
    product_id = str(cdr_product_id or "").strip()
    if not provider or dataset not in DATASETS or not product_id:
        raise ValueError("provider_uid, known dataset and CDR product ID are required")
    material = f"product-v1\0{provider}\0{dataset}\0{product_id}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()
