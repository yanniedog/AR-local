"""Brand/logo and RBA series loading for the mobile-app payload."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app_payload_common import MAX_EMBEDDED_LOGO_BYTES
from app_payload_provider_avatar import provider_avatar
from app_payload_logo_acquisition import logo_key

_BRAND_ENTRY_RE = re.compile(r"""['"]([^'"]+)['"]\s*:\s*\{([^}]*)\}""")
_BRAND_SHORT_IN_ENTRY_RE = re.compile(r"""short\s*:\s*['"]([^'"]+)['"]""")
_BRAND_ALIASES_IN_ENTRY_RE = re.compile(r"""aliases\s*:\s*\[([^\]]*)\]""")
_QUOTED_VALUE_RE = re.compile(r"""['"]([^'"]+)['"]""")

# Pleasant, high-contrast palette for monogram avatars (deterministic per provider).
_BRAND_PALETTE = (
    "#1f6feb", "#0a7d33", "#b7791f", "#9333ea", "#c2410c",
    "#0e7490", "#be123c", "#4338ca", "#15803d", "#a16207",
    "#7c3aed", "#0369a1", "#b91c1c", "#047857", "#6d28d9",
)


def _normalize_brand_lookup(value: str) -> str:
    words = re.sub(r"[^a-z0-9]+", " ", value.lower()).split()
    ignored = {
        "and",
        "australia",
        "australian",
        "bank",
        "banking",
        "corporation",
        "limited",
        "ltd",
        "of",
        "pty",
        "the",
        "wholesale",
    }
    return " ".join(word for word in words if word not in ignored)


def _brand_lookup_keys(value: str) -> Tuple[str, ...]:
    exact = value.strip().lower()
    normalized = _normalize_brand_lookup(value)
    return tuple(dict.fromkeys(key for key in (exact, normalized) if key))


def _brand_entry_names(name: str, body: str) -> List[str]:
    aliases_match = _BRAND_ALIASES_IN_ENTRY_RE.search(body)
    aliases = _QUOTED_VALUE_RE.findall(aliases_match.group(1)) if aliases_match else []
    return [name, *aliases]


def _put_brand_lookup(out: Dict[str, str], names: Iterable[str], value: str) -> None:
    for name in names:
        for key in _brand_lookup_keys(name):
            # Source order is canonical. Keep the first mapping on collisions.
            out.setdefault(key, value)


def _get_brand_lookup(values: Dict[str, str], provider: str) -> Optional[str]:
    for key in _brand_lookup_keys(provider):
        if key in values:
            return values[key]
    return None


def load_brand_shortcodes(rba_dir: Path) -> Dict[str, str]:
    """Extract ``lower(name) -> short`` from dashboard/ar-bank-brand.js (best effort)."""
    path = rba_dir / "ar-bank-brand.js"
    out: Dict[str, str] = {}
    if not path.exists():
        return out
    text = path.read_text(encoding="utf-8", errors="ignore")
    for name, body in _BRAND_ENTRY_RE.findall(text):
        short_match = _BRAND_SHORT_IN_ENTRY_RE.search(body)
        if short_match:
            _put_brand_lookup(out, _brand_entry_names(name, body), short_match.group(1).strip())
    return out


def _derive_short(provider: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 ]", " ", provider).strip()
    words = [w for w in cleaned.split() if w]
    if not words:
        return (provider[:3] or "?").upper()
    if len(words) == 1:
        return words[0][:4]
    initials = "".join(w[0] for w in words[:4]).upper()
    return initials


def _brand_color(provider: str) -> str:
    digest = hashlib.md5(provider.lower().encode("utf-8")).hexdigest()
    return _BRAND_PALETTE[int(digest[:8], 16) % len(_BRAND_PALETTE)]


def load_provider_logos(dashboard_dir: Path) -> Dict[str, str]:
    """Read the producer-owned pack, checking assets against their provenance."""
    root = dashboard_dir / "assets" / "provider-logos"
    catalog = root / "sources.json"
    try:
        manifest = json.loads(catalog.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(manifest, dict):
        return {}
    logos: Dict[str, str] = {}
    entries = manifest.get("brands")
    for entry in entries if isinstance(entries, list) else ():
        if not isinstance(entry, dict):
            continue
        filename, key, provider = (entry.get(field) for field in ("file", "key", "provider"))
        if (not all(isinstance(value, str) for value in (filename, key, provider))
                or Path(filename).name != filename or not filename.endswith(".png")
                or logo_key(provider) != key or key in logos):
            continue
        try:
            with (root / filename).open("rb") as stream:
                image = stream.read(MAX_EMBEDDED_LOGO_BYTES + 1)
        except OSError:
            continue
        if (len(image) > MAX_EMBEDDED_LOGO_BYTES or not image.startswith(b"\x89PNG\r\n\x1a\n")
                or hashlib.sha256(image).hexdigest() != entry.get("sha256")):
            continue
        logos[key] = "data:image/png;base64," + base64.b64encode(image).decode("ascii")
    aliases = manifest.get("aliases")
    if isinstance(aliases, dict):
        for alias, key in aliases.items():
            if isinstance(key, str) and alias not in logos and key in logos:
                logos[alias] = logos[key]
    return logos


def build_brands(
    providers: Iterable[str],
    shortcodes: Dict[str, str],
    logos: Optional[Dict[str, str]] = None,
) -> Dict[str, Dict[str, str]]:
    brands: Dict[str, Dict[str, str]] = {}
    logos = logos or {}
    for provider in sorted({p for p in providers if p}):
        short = _get_brand_lookup(shortcodes, provider) or _derive_short(provider)
        color = _brand_color(provider)
        logo = logos.get(logo_key(provider))
        brands[provider] = {
            "short": short,
            "color": color,
            "logo": logo or provider_avatar(short, color),
            "logo_source": "artwork" if logo else "monogram",
        }
    return brands


# --------------------------------------------------------------------------- #
# RBA cash-rate series (single source of truth: dashboard/rba-cash-rate.js)
# --------------------------------------------------------------------------- #
_RBA_ENTRY_RE = re.compile(r"date:\s*'([0-9]{4}-[0-9]{2}-[0-9]{2})'\s*,\s*rate:\s*([0-9.]+)")
# HOLDS is a flat array of meeting dates where the RBA left the rate unchanged.
_RBA_HOLD_BLOCK_RE = re.compile(r"const\s+HOLDS\s*=\s*\[(.*?)\]", re.DOTALL)
_RBA_HOLD_DATE_RE = re.compile(r"'([0-9]{4}-[0-9]{2}-[0-9]{2})'")


def load_rba_series(dashboard_dir: Path) -> List[Dict[str, Any]]:
    path = dashboard_dir / "rba-cash-rate.js"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    return [{"date": d, "rate": float(r)} for d, r in _RBA_ENTRY_RE.findall(text)]


def load_rba_holds(dashboard_dir: Path) -> List[str]:
    """RBA meeting dates that left the cash-rate target unchanged (holds)."""
    path = dashboard_dir / "rba-cash-rate.js"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    block = _RBA_HOLD_BLOCK_RE.search(text)
    if not block:
        return []
    return _RBA_HOLD_DATE_RE.findall(block.group(1))
