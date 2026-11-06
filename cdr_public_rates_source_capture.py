"""Bind original CDR bytes to their public endpoint without inventing check time."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote, urlparse

from cdr_domain.identity import provider_uid
from cdr_public_rates_cdr import capture_pricing_source


def pricing_capture_for_path(source: bytes, path: Path, banks_root: Path, base: dict) -> str:
    metadata = banks_root / "_holders" / base["provider"] / "_register-brand.json"
    brand = {}
    if metadata.is_file():
        try:
            loaded = json.loads(metadata.read_bytes())
            brand = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            pass
    endpoint = str(brand.get("endpoint_url") or "").rstrip("/")
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        endpoint = ""
    source_url = endpoint + "/" + quote(str(base["product_id"]), safe="") if endpoint else ""
    identity = provider_uid(
        register_holder_id=brand.get("data_holder_id") or brand.get("dataHolderId"),
        register_brand_id=brand.get("data_holder_brand_id") or brand.get("dataHolderBrandId"),
        authority=parsed.hostname or "public-cdr-unknown", display_name=base["provider"],
    )[0]
    # Recovery copies, imports and local touches can advance mtime without any
    # source request. This context contains no resource-bound HTTP receipt, so
    # retain the bytes and identity while leaving successful check time unknown.
    return capture_pricing_source(source, source_url=source_url, provider_id=identity)
