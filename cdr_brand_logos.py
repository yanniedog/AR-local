"""Brand logo URIs from the public CDR Register.

The register's data-holder brand summary publishes a regulator-maintained
``logoUri`` for every banking brand (117 at last check), which closes the gap
left by the 16-PNG canonical pack: providers without an embedded logo get a
``logo_uri`` in ``core.brands`` that the app loads remotely (monogram stays
the offline fallback).

Stdlib-only, cached on disk, and non-fatal: any fetch/parse problem simply
yields an empty map and the payload builds exactly as before.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Callable, Dict, Optional

REGISTER_URL = "https://api.cdr.gov.au/cdr-register/v1/banking/data-holders/brands/summary"
CACHE_MAX_AGE_SEC = 7 * 24 * 3600
FETCH_TIMEOUT_SEC = 30

# RN <Image> can't render SVG (and .ashx handlers are unpredictable). Raster
# URIs ship as ``logo_uri``; SVG URIs travel in a separate ``logo_svg_uri``
# field that raster-only app builds ignore and newer builds render via
# react-native-svg.
_RASTER_RE = re.compile(r"\.(png|jpe?g|gif|webp)(\?[^#]*)?$", re.IGNORECASE)
_SVG_RE = re.compile(r"\.svg(\?[^#]*)?$", re.IGNORECASE)


def is_svg_uri(uri: str) -> bool:
    """True for register logo URIs the app must render via react-native-svg."""
    return bool(_SVG_RE.search(uri))

# Legal suffixes and generic banking words carry no brand identity; keeping
# them lets e.g. "ING BANK (Australia) Ltd" mis-match "Bank Australia".
_SUFFIX_TOKENS = {
    "ltd",
    "limited",
    "pty",
    "plc",
    "co",
    "the",
    "bank",
    "banks",
    "banking",
    "australia",
    "australian",
    "of",
    "and",
}


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _tokens(name: str) -> frozenset[str]:
    return frozenset(t for t in _normalize(name).split() if t not in _SUFFIX_TOKENS)


def _default_fetch(timeout: int) -> bytes:
    req = urllib.request.Request(REGISTER_URL, headers={"x-v": "1"})
    with urllib.request.urlopen(req, timeout=timeout) as res:  # nosec B310 - fixed https URL
        return res.read()


def parse_register_payload(raw: bytes) -> Dict[str, str]:
    """``normalized brandName -> logoUri`` for raster and SVG logo formats."""
    data = json.loads(raw.decode("utf-8"))
    out: Dict[str, str] = {}
    for entry in data.get("data") or []:
        name = str(entry.get("brandName") or "").strip()
        uri = str(entry.get("logoUri") or "").strip()
        if not name or not uri.lower().startswith("https://"):
            continue
        if not (_RASTER_RE.search(uri) or _SVG_RE.search(uri)):
            continue
        out[_normalize(name)] = uri
    return out


def _read_cache_file(cache_path: Path) -> Dict[str, str]:
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(cached, dict) and cached:
            return {str(k): str(v) for k, v in cached.items()}
    except Exception:
        pass
    return {}


def fetch_register_logos(
    cache_path: Optional[Path] = None,
    *,
    timeout: int = FETCH_TIMEOUT_SEC,
    fetcher: Callable[[int], bytes] = _default_fetch,
) -> Dict[str, str]:
    """Cached, non-fatal register fetch. Returns {} on any failure."""
    stale: Dict[str, str] = {}
    if cache_path is not None and cache_path.is_file():
        age = time.time() - cache_path.stat().st_mtime
        cached = _read_cache_file(cache_path)
        if cached and age < CACHE_MAX_AGE_SEC:
            return cached
        stale = cached
    try:
        logos = parse_register_payload(fetcher(timeout))
    except Exception as exc:  # noqa: BLE001 - logos are best-effort
        print(f"[cdr_brand_logos] register fetch failed: {exc!r}")
        return stale
    if logos and cache_path is not None:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(logos, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
    return logos


def logo_uri_for(provider: str, register: Dict[str, str]) -> Optional[str]:
    """Best register logo for a payload provider name.

    Exact normalized match first; otherwise token-subset matching (suffixes like
    Ltd stripped), preferring the candidate sharing the most tokens with the
    fewest left over, so "AMP Bank" prefers brand "AMP Bank" over "AMP Bank GO".
    """
    if not register:
        return None
    norm = _normalize(provider)
    if norm in register:
        return register[norm]
    ptoks = _tokens(provider)
    if not ptoks:
        return None
    best: Optional[str] = None
    best_score: tuple[int, int] | None = None
    for name, uri in register.items():
        rtoks = _tokens(name)
        if not rtoks:
            continue
        if not (rtoks <= ptoks or ptoks <= rtoks):
            continue
        shared = len(rtoks & ptoks)
        extra = len(rtoks ^ ptoks)
        score = (shared, -extra)
        if best_score is None or score > best_score:
            best_score = score
            best = uri
    return best
