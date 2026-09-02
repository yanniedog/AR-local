"""Deterministic brand metadata derived from checked-in assets."""

from __future__ import annotations

import base64
import hashlib
import os
import re
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

import rba_decisions

from app_payload_common import MAX_EMBEDDED_LOGO_BYTES, compact


_BRAND_PALETTE = (
    "#1f6feb", "#0a7d33", "#b7791f", "#9333ea", "#c2410c",
    "#0e7490", "#be123c", "#4338ca", "#15803d", "#a16207",
    "#7c3aed", "#0369a1", "#b91c1c", "#047857", "#6d28d9",
)


def _normalize_brand_lookup(value: str) -> str:
    words = re.sub(r"[^a-z0-9]+", " ", value.lower()).split()
    ignored = {
        "and", "australia", "australian", "bank", "banking", "corporation",
        "limited", "ltd", "of", "pty", "the", "wholesale",
    }
    return " ".join(word for word in words if word not in ignored)


def _brand_lookup_keys(value: str) -> Tuple[str, ...]:
    exact = value.strip().lower()
    normalized = _normalize_brand_lookup(value)
    return tuple(dict.fromkeys(key for key in (exact, normalized) if key))


def _put_brand_lookup(
    out: Dict[str, str], names: str | Iterable[str], value: str
) -> None:
    for name in (names,) if isinstance(names, str) else names:
        for key in _brand_lookup_keys(name):
            out.setdefault(key, value)


def _get_brand_lookup(values: Dict[str, str], provider: str) -> Optional[str]:
    return next((values[key] for key in _brand_lookup_keys(provider) if key in values), None)


def find_bank_logo_dir(asset_dir: Path) -> Optional[Path]:
    configured = os.environ.get("AR_LOCAL_PAYLOAD_ASSETS", "").strip()
    candidates = [Path(configured) / "banks"] if configured else []
    candidates.append(asset_dir / "banks")
    return next((path for path in candidates if path.is_dir()), None)


def load_brand_logos(asset_dir: Path, logo_dir: Optional[Path] = None) -> Dict[str, str]:
    """Load bounded PNGs; filenames provide the deterministic provider lookup."""
    logo_dir = logo_dir or find_bank_logo_dir(asset_dir)
    if logo_dir is None:
        return {}
    result: Dict[str, str] = {}
    for path in sorted(logo_dir.glob("*.png")):
        size = path.stat().st_size
        if size <= 0 or size > MAX_EMBEDDED_LOGO_BYTES:
            continue
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        _put_brand_lookup(
            result,
            path.stem.replace("-", " "),
            f"data:image/png;base64,{encoded}",
        )
    return result


def _derive_short(provider: str) -> str:
    words = re.sub(r"[^A-Za-z0-9 ]", " ", provider).split()
    if not words:
        return (provider[:3] or "?").upper()
    if len(words) == 1:
        return words[0][:4]
    return "".join(word[0] for word in words[:4]).upper()


def _brand_color(provider: str) -> str:
    digest = hashlib.sha256(provider.casefold().encode("utf-8")).hexdigest()
    return _BRAND_PALETTE[int(digest[:8], 16) % len(_BRAND_PALETTE)]


def build_brands(
    providers: Iterable[str],
    shortcodes: Optional[Dict[str, str]] = None,
    logos: Optional[Dict[str, str]] = None,
    register_logos: Optional[Dict[str, str]] = None,
) -> Dict[str, Dict[str, str]]:
    """Build stable local metadata; network-fetched logos are deliberately ignored."""
    del register_logos
    shortcodes = shortcodes or {}
    logos = logos or {}
    result: Dict[str, Dict[str, str]] = {}
    for provider in sorted({str(value).strip() for value in providers if str(value).strip()}):
        result[provider] = compact(
            {
                "short": _get_brand_lookup(shortcodes, provider) or _derive_short(provider),
                "color": _brand_color(provider),
                "logo": _get_brand_lookup(logos, provider),
            }
        )
    return result


def load_brand_shortcodes(_asset_dir: Path) -> Dict[str, str]:
    """Compatibility shim: short labels now derive from provider names."""
    return {}


def load_rba_series(_asset_dir: Path) -> list[dict[str, object]]:
    return [
        {"date": decision.effective_date.isoformat(), "rate": decision.new_rate}
        for decision in rba_decisions.decisions()
        if decision.delta_bps != 0
    ]


def load_rba_holds(_asset_dir: Path) -> list[str]:
    return [
        decision.date.isoformat()
        for decision in rba_decisions.decisions()
        if decision.delta_bps == 0
    ]
