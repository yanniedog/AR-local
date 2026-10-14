"""Bind original CDR bytes to registered public endpoint and actual capture time."""
from __future__ import annotations

import json
from datetime import datetime, timezone
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
    checked = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z")
    return capture_pricing_source(source, source_url=source_url, checked_at=checked, provider_id=identity)
