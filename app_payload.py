"""Build and publish the compact mobile-app payload for AR-local.

The Raspberry Pi daily ingest already produces a compact, dashboard-ready
``dashboard-cache/<run_date>/banks.json`` plus a ``dashboard-cache/latest.json``
manifest. This module reshapes those (pure Python, no SQLite and no running
dashboard server) into three small artifacts the mobile app downloads from GitHub Releases:

  * ``manifest.json``          - tiny; the app polls this first.
  * ``core-<date>.json.gz``    - section rates + ribbon stats + brands + RBA series.
  * ``details-<date>.json.gz`` - per-product fees/features/eligibility/constraints.

Rolling tag ``app-payload-latest`` is the canonical "newest" manifest the mobile app
polls. Each ingest ``run_date`` also gets an immutable dated release
``app-payload-<YYYY-MM-DD>`` with its own manifest + assets (no pruning).

Usage::

    python app_payload.py build  --exports runs/2026-05-19/_exports --out <dir>
    python app_payload.py publish --dir <app-payload dir> [--tag app-payload-2026-05-19]

``build`` is deterministic and CI-friendly. ``publish`` uploads via the ``gh``
CLI and is token-gated: with no ``gh`` auth / ``GH_TOKEN`` it prints a clear
message and no-ops (exit 0) so it is safe to wire into the daily pipeline before
the Pi has a token.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Iterable, List, Optional, Tuple

import app_payload_mobile
import cdr_brand_logos
import payload_crypto
import rba_decisions
from cdr_ribbon_normalize import (
    aggregate_ribbon,
    normalized_rate_value as _normalized_rate_value,
)

BASE_DIR = Path(__file__).resolve().parent

SCHEMA_VERSION = 1
DEFAULT_REPO = os.environ.get("AR_LOCAL_REPO", "yanniedog/AR-local")
DEFAULT_TAG = os.environ.get("AR_LOCAL_APP_PAYLOAD_TAG", "app-payload-latest")
DATED_TAG_PREFIX = "app-payload-"
DATES_INDEX_FILENAME = "dates-index.json"
HISTORY_MIN_DATE = "2026-05-13"
_RUN_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
APP_MIN_VERSION = "1.0.0"
# Bound every gh subprocess so a network/CLI stall can never hang the Pi's daily
# pipeline. Uploads get a longer budget than metadata calls.
SUBPROCESS_TIMEOUT_SEC = 30
SUBPROCESS_UPLOAD_TIMEOUT_SEC = 600
# Content-addressed assets accumulate on the rolling release; GitHub caps a release at
# 1000 assets. Keep the current manifest's assets plus a recent buffer (covers any
# in-flight client still holding the just-superseded manifest) and prune older ones.
KEEP_RECENT_ASSETS = 48  # backfill window (~2 assets/day)
MAX_EMBEDDED_LOGO_BYTES = 64 * 1024

VALID_SECTIONS = ("Mortgage", "Savings", "TD")

# Curated subset of the flattened rate-row columns (a superset of the dashboard's
# BANK_SECTION_COLUMNS, plus comparison_rate / last_updated which banks.json carries
# but the section API drops). Empty values are stripped per-row before encoding.
CORE_RATE_FIELDS = (
    "provider",
    "product_id",
    "product_key",
    "product_name",
    "category",
    "rate",
    "comparison_rate",
    "rate_type",
    "repayment_type",
    "loan_purpose",
    "term",
    "term_months",
    "lvr_tier",
    "ribbon_normalized",
    "security_purpose",
    "ribbon_repayment_type",
    "ribbon_rate_structure",
    "ribbon_fixed_term",
    "account_type",
    "ribbon_deposit_kind",
    "balance_min",
    "balance_max",
    "interest_payment",
    "feature_set",
    "account_class",
    "rate_index",
    "last_updated",
    "taxonomy_path",  # dot-delimited hierarchy that drives the app's drill-down tree
)


# --------------------------------------------------------------------------- #
# Small shared helpers
# --------------------------------------------------------------------------- #
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_blank(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def compact(row: Dict[str, Any]) -> Dict[str, Any]:
    """Drop absent/empty fields before JSON encoding (matches the dashboard)."""
    return {key: value for key, value in row.items() if not _is_blank(value)}


def section_filter(dataset: str, row: Dict[str, Any]) -> bool:
    """Mirror cdr_dashboard_server.bank_section_rate_filter."""
    rate = row.get("rate")
    if _is_blank(rate):
        return False
    family = row.get("rate_family")
    if dataset == "Mortgage":
        return family == "lending" and (row.get("rate_type") or "") != "DISCOUNT"
    return family == "deposit"


# --------------------------------------------------------------------------- #
# Ribbon aggregate: the single implementation now lives in cdr_ribbon_normalize
# (aggregate_ribbon / normalized_rate_value, imported above) so this payload
# builder and the dashboard server can never diverge on the rate metric again.
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Brands (canonical embedded logos + monogram fallback, no external CDN)
# --------------------------------------------------------------------------- #
_BRAND_ENTRY_RE = re.compile(r"""['"]([^'"]+)['"]\s*:\s*\{([^}]*)\}""")
_BRAND_SHORT_IN_ENTRY_RE = re.compile(r"""short\s*:\s*['"]([^'"]+)['"]""")
_BRAND_ICON_IN_ENTRY_RE = re.compile(r"""icon\s*:\s*['"]/assets/banks/([^'"]+\.png)['"]""")
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


def find_bank_logo_dir(dashboard_dir: Path) -> Optional[Path]:
    """Find the canonical logo pack (vendored in-repo; legacy site checkouts as fallback)."""
    configured = os.environ.get("AR_LOCAL_SITE_ROOT") or os.environ.get("AR_SITE_ROOT")
    candidates = [dashboard_dir / "assets" / "banks"]
    if configured:
        root = Path(configured).expanduser()
        candidates.extend((root / "assets" / "banks", root / "site" / "assets" / "banks"))
    repo_dir = dashboard_dir.parent
    candidates.extend(
        (
            repo_dir.parent / "australianrates" / "site" / "assets" / "banks",
            repo_dir.parent / "AustralianRates" / "site" / "assets" / "banks",
            repo_dir / "site" / "assets" / "banks",
        )
    )
    for path in candidates:
        if path.is_dir():
            return path
    return None


def load_brand_logos(dashboard_dir: Path, logo_dir: Optional[Path] = None) -> Dict[str, str]:
    """Extract ``lower(name) -> data:image/png`` for locally available canonical logos."""
    brand_path = dashboard_dir / "ar-bank-brand.js"
    logo_dir = logo_dir or find_bank_logo_dir(dashboard_dir)
    if not brand_path.exists() or not logo_dir:
        return {}
    text = brand_path.read_text(encoding="utf-8", errors="ignore")
    out: Dict[str, str] = {}
    for name, body in _BRAND_ENTRY_RE.findall(text):
        icon_match = _BRAND_ICON_IN_ENTRY_RE.search(body)
        if not icon_match:
            continue
        filename = icon_match.group(1)
        path = logo_dir / Path(filename).name
        if not path.is_file() or path.stat().st_size > MAX_EMBEDDED_LOGO_BYTES:
            continue
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        _put_brand_lookup(
            out,
            _brand_entry_names(name, body),
            f"data:image/png;base64,{encoded}",
        )
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


def build_brands(
    providers: Iterable[str],
    shortcodes: Dict[str, str],
    logos: Optional[Dict[str, str]] = None,
    register_logos: Optional[Dict[str, str]] = None,
) -> Dict[str, Dict[str, str]]:
    brands: Dict[str, Dict[str, str]] = {}
    logos = logos or {}
    register_logos = register_logos or {}
    for provider in sorted({p for p in providers if p}):
        short = _get_brand_lookup(shortcodes, provider) or _derive_short(provider)
        embedded = _get_brand_lookup(logos, provider)
        # Register URI only when there is no embedded logo: the app prefers
        # embedded/bundled art, so shipping both wastes bytes. SVG URIs ride a
        # separate field — RN <Image> can't render SVG, so raster-only builds
        # ignore it while newer builds render it via react-native-svg.
        register_uri = None if embedded else cdr_brand_logos.logo_uri_for(provider, register_logos)
        register_is_svg = register_uri is not None and cdr_brand_logos.is_svg_uri(register_uri)
        brands[provider] = compact(
            {
                "short": short,
                "color": _brand_color(provider),
                "logo": embedded,
                "logo_uri": None if register_is_svg else register_uri,
                "logo_svg_uri": register_uri if register_is_svg else None,
            }
        )
    return brands


# --------------------------------------------------------------------------- #
# RBA cash-rate series (single source of truth: dashboard/rba-cash-rate.js)
# --------------------------------------------------------------------------- #
_RBA_ENTRY_RE = re.compile(r"date:\s*'([0-9]{4}-[0-9]{2}-[0-9]{2})'\s*,\s*rate:\s*([0-9.]+)")


def load_rba_series(dashboard_dir: Path) -> List[Dict[str, Any]]:
    path = dashboard_dir / "rba-cash-rate.js"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    return [{"date": d, "rate": float(r)} for d, r in _RBA_ENTRY_RE.findall(text)]


# --------------------------------------------------------------------------- #
# Per-product detail (parsed from products[].details_json in banks.json)
# --------------------------------------------------------------------------- #
def _detail_items(record: Dict[str, Any], key: str, type_key: str) -> List[Dict[str, Any]]:
    items = record.get(key)
    if not isinstance(items, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out.append(
            compact(
                {
                    "label": item.get(type_key) or item.get("name"),
                    "name": item.get("name"),
                    "value": item.get("additionalValue") or item.get("amount"),
                    "info": item.get("additionalInfo"),
                }
            )
        )
    return out


def build_details(products: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    details: Dict[str, Dict[str, Any]] = {}
    for product in products:
        key = product.get("product_key")
        if not key:
            continue
        raw = product.get("details_json") or "{}"
        try:
            record = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (ValueError, TypeError):
            record = {}
        if not isinstance(record, dict):
            record = {}
        entry = compact(
            {
                "description": product.get("description") or record.get("description"),
                "last_updated": product.get("last_updated"),
                "fees": _detail_items(record, "fees", "feeType"),
                "features": _detail_items(record, "features", "featureType"),
                "eligibility": _detail_items(record, "eligibility", "eligibilityType"),
                "constraints": _detail_items(record, "constraints", "constraintType"),
            }
        )
        details[key] = entry
    return details


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #
def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_banks_json(exports_dir: Path, run_date: str) -> Path:
    # Require the banks.json that matches latest.json's run_date. Never substitute a
    # different date's file — that would publish older rates under a newer run_date.
    candidate = exports_dir / "dashboard-cache" / run_date / "banks.json"
    if not candidate.exists():
        raise FileNotFoundError(
            f"banks.json for run_date {run_date} not found at {candidate}; "
            "refusing to package a different run's data"
        )
    return candidate


def _ingest_schedule() -> Dict[str, Any]:
    try:
        import ar_local_ingest_schedule as sched  # local module

        now = datetime.now(timezone.utc)
        return {
            "label": sched.DAILY_INGEST_SCHEDULE_LABEL,
            "next_due_utc": sched.next_daily_due_utc(now).isoformat().replace("+00:00", "Z"),
        }
    except Exception:  # pragma: no cover - schedule is informational only
        return {"label": "Daily"}


def _gzip_bytes(obj: Any) -> bytes:
    raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    # mtime=0 keeps output stable across runs for the same input.
    return gzip.compress(raw, compresslevel=9, mtime=0)


def _asset(
    out_dir: Path,
    kind: str,
    run_date: str,
    gz: bytes,
    release_base: str,
    enc_key: Optional[bytes] = None,
) -> Dict[str, Any]:
    # Content-addressed name (kind-<run_date>-<sha12>.json.gz[.enc]): a new/corrected
    # payload gets a NEW filename, so uploading it never overwrites an asset the
    # previously published manifest still references. Old manifests stay internally
    # consistent until the new manifest.json is published last. Encryption uses a
    # plaintext-derived nonce, so encrypted bytes are equally rebuild-stable.
    data = payload_crypto.encrypt_asset(gz, enc_key) if enc_key else gz
    sha = hashlib.sha256(data).hexdigest()
    suffix = ".json.gz.enc" if enc_key else ".json.gz"
    name = f"{kind}-{run_date}-{sha[:12]}{suffix}"
    (out_dir / name).write_bytes(data)
    entry: Dict[str, Any] = {
        "name": name,
        "bytes": len(data),
        "sha256": sha,
        "url": f"{release_base}/{name}",
    }
    if enc_key:
        entry["enc"] = {"alg": payload_crypto.ALG, "key_id": payload_crypto.key_id(enc_key)}
    return entry


# --------------------------------------------------------------------------- #
# Ongoing/base-rate join (rate-honesty: what a bonus/intro headline reverts to)
# --------------------------------------------------------------------------- #
# A savings/TD product publishes its conditional headline (bonus / introductory)
# and its unconditional ongoing tier as SEPARATE rows of the same product_key.
# The app shows "Bonus 5.00%" but a typical customer earns the ongoing tier once
# the conditions lapse, so we attach that published base tier's rate as
# ``ongoing_rate``. We copy the bank's own base-tier figure verbatim — never
# arithmetic on the bonus — so the disclosure can't itself become misleading.
def _ongoing_num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _row_conditional_kind(row: Dict[str, Any], section: str) -> str:
    if section == "Savings":
        kind = str(row.get("ribbon_deposit_kind") or "").lower().strip()
    elif section == "TD":
        kind = str(row.get("ribbon_rate_structure") or "").lower().strip()
    else:
        return ""
    if kind == "bonus":
        return "bonus"
    if kind in ("introductory", "intro"):
        return "intro"
    return ""


def _row_is_base(row: Dict[str, Any], section: str) -> bool:
    field = "ribbon_deposit_kind" if section == "Savings" else "ribbon_rate_structure"
    return str(row.get(field) or "").lower().strip() == "base"


def _select_base_sibling(
    target: Dict[str, Any], candidates: List[Dict[str, Any]], section: str
) -> Optional[Dict[str, Any]]:
    pool = candidates
    if section == "TD":
        term = _ongoing_num(target.get("term_months"))
        if term is not None:
            pool = [c for c in pool if _ongoing_num(c.get("term_months")) == term]
            # Never disclose a different term's base rate as this offer's ongoing
            # rate (a 6-month base is not the reversion rate of a 12-month TD).
            if not pool:
                return None
    if len(pool) == 1:
        return pool[0]
    bmin = _ongoing_num(target.get("balance_min"))
    if bmin is not None:
        exact = [c for c in pool if _ongoing_num(c.get("balance_min")) == bmin]
        if exact:
            return exact[0]
        bmax = _ongoing_num(target.get("balance_max"))
        hi = bmax if bmax is not None else math.inf
        overlapping = []
        for c in pool:
            c_min = _ongoing_num(c.get("balance_min")) or 0.0
            c_max_raw = _ongoing_num(c.get("balance_max"))
            c_max = c_max_raw if c_max_raw is not None else math.inf
            # Parse balance_max once so an unparseable string can't raise TypeError.
            if c_min <= hi and bmin <= c_max:
                overlapping.append(c)
        if overlapping:
            return overlapping[0]
    return pool[0]


def attach_ongoing_rates(
    section_rows: List[Dict[str, Any]],
    compact_rows: List[Dict[str, Any]],
    section: str,
) -> None:
    """Set ``ongoing_rate`` on each bonus/intro row (in-place on ``compact_rows``)."""
    if section not in ("Savings", "TD"):
        return
    bases: Dict[str, List[Dict[str, Any]]] = {}
    for row in section_rows:
        if _row_is_base(row, section):
            bases.setdefault(str(row.get("product_key") or ""), []).append(row)
    if not bases:
        return
    for raw, comp in zip(section_rows, compact_rows):
        if not _row_conditional_kind(raw, section):
            continue
        candidates = bases.get(str(raw.get("product_key") or ""))
        if not candidates:
            continue
        base = _select_base_sibling(raw, candidates, section)
        ongoing = base.get("rate") if base else None
        if ongoing not in (None, ""):
            comp["ongoing_rate"] = ongoing


def build_payload(
    exports_dir: Path,
    out_dir: Path,
    *,
    repo: str = DEFAULT_REPO,
    tag: str = DEFAULT_TAG,
    dashboard_dir: Path = BASE_DIR / "dashboard",
) -> Dict[str, Any]:
    """Build manifest + core + details into ``out_dir``; return the manifest dict."""
    # Only the rolling release ships search-index + history assets (see _package's
    # is_rolling_tag gate), so a dated build needn't compute them at all.
    data = _compute_payload(
        exports_dir, dashboard_dir=dashboard_dir, include_history=is_rolling_tag(tag)
    )
    return _package_payload(data, out_dir, repo=repo, tag=tag)


def _compute_payload(
    exports_dir: Path,
    *,
    dashboard_dir: Path = BASE_DIR / "dashboard",
    include_history: bool = True,
) -> Dict[str, Any]:
    """Parse the run's exports into the (tag-independent) payload data.

    Parsing the multi-MB current banks.json is always needed (core/details). The
    search index and history scan — the most expensive part, and rolling-only — are
    computed only when ``include_history`` is set, so the dated build and the
    skip-rolling backfill path don't pay for assets no release will ship.
    """
    latest = _load_json(exports_dir / "dashboard-cache" / "latest.json")
    run_date = str(latest.get("run_date") or "")
    if not run_date:
        raise ValueError("latest.json has no run_date")
    banks = _load_json(_find_banks_json(exports_dir, run_date))
    rates: List[Dict[str, Any]] = banks.get("rates") or []
    products: List[Dict[str, Any]] = banks.get("products") or []

    sections: Dict[str, Any] = {}
    providers_seen: set[str] = set()
    for section in VALID_SECTIONS:
        section_rows = [r for r in rates if r.get("dataset") == section and section_filter(section, r)]
        for r in section_rows:
            providers_seen.add(str(r.get("provider") or ""))
        compact_rows = [compact({k: r.get(k) for k in CORE_RATE_FIELDS}) for r in section_rows]
        attach_ongoing_rates(section_rows, compact_rows, section)
        sections[section] = {
            "rates": compact_rows,
            "ribbon": aggregate_ribbon(section_rows, section),
        }

    shortcodes = load_brand_shortcodes(dashboard_dir)
    logos = load_brand_logos(dashboard_dir)
    # NB: no wall-clock field inside core/details. They are content-hashed (sha256
    # in the manifest) and the app skips re-download when the hash is unchanged, so
    # a same-day rebuild (e.g. the watchdog rerun) must yield identical bytes.
    # v2: cache name bumped when SVG logoUris started being kept, so a fresh
    # raster-only cache can't suppress SVG entries for up to 7 days.
    register_logos = cdr_brand_logos.fetch_register_logos(
        cache_path=exports_dir / "cdr-brand-logos-v2.json"
    )
    core = {
        "schema_version": SCHEMA_VERSION,
        "run_date": run_date,
        "sections": sections,
        "brands": build_brands(providers_seen, shortcodes, logos, register_logos),
        "rba": load_rba_series(dashboard_dir),
    }
    details = {
        "schema_version": SCHEMA_VERSION,
        "run_date": run_date,
        "products": build_details(products),
    }

    search_index = None
    history_banks = None
    bank_history = None
    if include_history:
        all_core_rows: List[Dict[str, Any]] = []
        for section in VALID_SECTIONS:
            all_core_rows.extend(core["sections"][section]["rates"])
        search_index = app_payload_mobile.build_search_index(
            all_core_rows, details["products"], run_date=run_date, schema_version=SCHEMA_VERSION
        )
        history_banks, bank_history = app_payload_mobile.build_history_assets(
            exports_dir,
            run_date=run_date,
            load_json=_load_json,
            section_filter=section_filter,
            normalized_rate_value=_normalized_rate_value,
            schema_version=SCHEMA_VERSION,
        )
    counts = latest.get("banks_counts") or banks.get("counts") or {}
    return {
        "core": core,
        "details": details,
        "run_date": run_date,
        "counts": counts,
        "search_index": search_index,
        "history_banks": history_banks,
        "bank_history": bank_history,
        "rba_calendar": rba_decisions.calendar_payload(),
    }


def _package_payload(
    data: Dict[str, Any],
    out_dir: Path,
    *,
    repo: str = DEFAULT_REPO,
    tag: str = DEFAULT_TAG,
) -> Dict[str, Any]:
    """Gzip + write the manifest for one tag's release from precomputed payload data."""
    return _package(
        data["core"],
        data["details"],
        data["run_date"],
        out_dir,
        repo=repo,
        tag=tag,
        counts=data["counts"],
        search_index=data["search_index"],
        history_banks=data["history_banks"],
        bank_history=data["bank_history"],
        rba_calendar=data.get("rba_calendar"),
        # Phase A (docs/SECURITY_CDR_PIPELINE.md): ciphertext-only release when
        # AR_LOCAL_PAYLOAD_ENC=1. Stays off until the app ships decrypt support.
        enc_key=payload_crypto.resolve_key_from_env(),
    )


def _package(
    core: Dict[str, Any],
    details: Dict[str, Any],
    run_date: str,
    out_dir: Path,
    *,
    repo: str,
    tag: str,
    counts: Dict[str, Any],
    search_index: Optional[Dict[str, Any]] = None,
    history_banks: Optional[Dict[str, Any]] = None,
    bank_history: Optional[Dict[str, Any]] = None,
    rba_calendar: Optional[Dict[str, Any]] = None,
    enc_key: Optional[bytes] = None,
) -> Dict[str, Any]:
    """Gzip core/details (+ optional search/history), write manifest into out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    release_base = f"https://github.com/{repo}/releases/download/{tag}"
    files: Dict[str, Any] = {
        "core": _asset(out_dir, "core", run_date, _gzip_bytes(core), release_base, enc_key),
        "details": _asset(out_dir, "details", run_date, _gzip_bytes(details), release_base, enc_key),
    }
    if is_rolling_tag(tag) and search_index and search_index.get("products"):
        files["search_index"] = _asset(
            out_dir, "search-index", run_date, _gzip_bytes(search_index), release_base, enc_key
        )
    if is_rolling_tag(tag) and history_banks and history_banks.get("sections"):
        files["history_banks"] = _asset(
            out_dir, "history-banks", run_date, _gzip_bytes(history_banks), release_base, enc_key
        )
    if is_rolling_tag(tag) and bank_history and bank_history.get("banks"):
        files["bank_history"] = _asset(
            out_dir, "bank-history", run_date, _gzip_bytes(bank_history), release_base, enc_key
        )
    if is_rolling_tag(tag) and rba_calendar and rba_calendar.get("schedule"):
        files["rba_calendar"] = _asset(
            out_dir, "rba-calendar", run_date, _gzip_bytes(rba_calendar), release_base, enc_key
        )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_date": run_date,
        "generated_at": utc_now_iso(),
        "app_min_version": APP_MIN_VERSION,
        "repo": repo,
        "tag": tag,
        "counts": counts,
        "schedule": _ingest_schedule(),
        "files": files,
    }
    if enc_key:
        manifest["enc"] = {"alg": payload_crypto.ALG, "key_id": payload_crypto.key_id(enc_key)}
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


def seed_from_sample(
    sample_dir: Path,
    out_dir: Path,
    *,
    repo: str = DEFAULT_REPO,
    tag: str = DEFAULT_TAG,
) -> Dict[str, Any]:
    """Repackage the app's committed sample (core.json/details.json) into a publishable
    payload. Used by the manual workflow to bootstrap the release before the Pi's first
    real run, so the app's release URL resolves immediately."""
    core = _load_json(sample_dir / "core.json")
    details = _load_json(sample_dir / "details.json")
    run_date = str(core.get("run_date") or "sample")
    counts: Dict[str, Any] = {}
    sample_manifest = sample_dir / "manifest.json"
    if sample_manifest.exists():
        counts = _load_json(sample_manifest).get("counts") or {}
    return _package(core, details, run_date, out_dir, repo=repo, tag=tag, counts=counts)


# --------------------------------------------------------------------------- #
# Publish (gh release upload, token-gated)
# --------------------------------------------------------------------------- #
def _gh_available() -> Optional[str]:
    return shutil.which("gh")


def dated_tag(run_date: str) -> str:
    """Immutable per-run_date release tag (``app-payload-YYYY-MM-DD``)."""
    if not _RUN_DATE_RE.match(run_date):
        raise ValueError(f"invalid run_date for dated tag: {run_date!r}")
    return f"{DATED_TAG_PREFIX}{run_date}"


def is_rolling_tag(tag: str) -> bool:
    """True for the canonical rolling latest tag the mobile app polls."""
    return tag in (DEFAULT_TAG, "app-payload-latest")


def is_dated_tag(tag: str) -> bool:
    """True for immutable per-run_date snapshot tags."""
    if not tag.startswith(DATED_TAG_PREFIX):
        return False
    return bool(_RUN_DATE_RE.match(tag[len(DATED_TAG_PREFIX) :]))


def release_title(run_date: str) -> str:
    """Human-readable rolling-release title for a given payload run_date."""
    return f"Australian Rates payload — latest ({run_date})"


def dated_release_title(run_date: str) -> str:
    """Human-readable title for an immutable per-run_date snapshot release."""
    return f"Australian Rates payload — {run_date}"


def release_display_title(tag: str, run_date: str) -> str:
    """GitHub release title for ``tag`` using manifest ``run_date``."""
    return release_title(run_date) if is_rolling_tag(tag) else dated_release_title(run_date)


def iter_valid_export_dates(
    runs_root: Path,
    *,
    from_date: str = "",
    to_date: str = "",
) -> Iterable[Tuple[str, Path]]:
    """Yield ``(run_date, exports_dir)`` for valid exports in the optional date range."""
    from ar_local_pi_runtime import export_manifest_is_valid, load_exports_manifest

    runs_root = runs_root.expanduser().resolve()
    if not runs_root.is_dir():
        return iter(())
    for child in sorted(runs_root.iterdir()):
        if not child.is_dir() or not _RUN_DATE_RE.match(child.name):
            continue
        run_date = child.name
        if from_date and run_date < from_date:
            continue
        if to_date and run_date > to_date:
            continue
        exports = child / "_exports"
        manifest = load_exports_manifest(exports)
        if manifest is not None and export_manifest_is_valid(manifest):
            yield run_date, exports


def build_dates_index(
    dates: Iterable[str],
    *,
    min_date: str = HISTORY_MIN_DATE,
    repo: str = DEFAULT_REPO,
    tag: str = DEFAULT_TAG,
) -> Dict[str, Any]:
    """Build the mobile history dates index (sorted, bounded, with download URL hints)."""
    valid = sorted(
        {d for d in dates if _RUN_DATE_RE.match(d) and (not min_date or d >= min_date)}
    )
    latest = valid[-1] if valid else ""
    base = f"https://github.com/{repo}/releases/download"
    return {
        "schema_version": SCHEMA_VERSION,
        "dates": valid,
        "count": len(valid),
        "min_date": min_date,
        "latest_date": latest,
        "dates_index_url": f"{base}/{tag}/{DATES_INDEX_FILENAME}",
        "dated_manifest_url_pattern": f"{base}/{DATED_TAG_PREFIX}{{run_date}}/manifest.json",
    }


def _published_history_dates(
    repo: str,
    *,
    min_date: str = HISTORY_MIN_DATE,
) -> List[str]:
    """Return sorted run_dates with a live, COMPLETE dated snapshot release on GitHub.

    A dated tag (``app-payload-<run_date>``, date format validated by is_dated_tag)
    is included only when its manifest.json is actually present with a matching
    run_date — this excludes an incomplete release whose tag was created but whose
    manifest upload failed (which would otherwise advertise a date that 404s for the
    app). The per-release manifest checks run CONCURRENTLY, so the refresh costs ~one
    round-trip's latency instead of the former N sequential GETs (the N+1).
    """
    gh = _gh_available()
    if not gh or not _gh_authed(gh):
        return []
    try:
        tags = _list_payload_release_tags(gh, repo)
    except RuntimeError as exc:
        print(f"[app_payload] dates-index tag list failed (non-fatal) error={exc!r}")
        return []
    candidates: List[Tuple[str, str]] = []
    for tag in tags:
        if not is_dated_tag(tag):
            continue
        run_date = tag[len(DATED_TAG_PREFIX) :]
        if min_date and run_date < min_date:
            continue
        candidates.append((tag, run_date))
    if not candidates:
        return []

    def _verified_date(item: Tuple[str, str]) -> Optional[str]:
        tag, run_date = item
        status, live = _live_manifest_status(repo, tag)
        if status == "present" and live and str(live.get("run_date") or "") == run_date:
            return run_date
        return None

    with ThreadPoolExecutor(max_workers=min(8, len(candidates))) as pool:
        verified = [d for d in pool.map(_verified_date, candidates) if d]
    return sorted(set(verified))


def _upload_dates_index(
    gh: str,
    repo: str,
    tag: str,
    index_path: Path,
) -> bool:
    """Upload ``dates-index.json`` to the rolling release (clobber)."""
    if not index_path.is_file():
        return False
    # nosemgrep: dangerous-subprocess-use-audit, dangerous-subprocess-use-tainted-env-args
    view = subprocess.run(
        [gh, "release", "view", tag, "--repo", repo],
        capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SEC,
    )
    if view.returncode != 0:
        print(f"[app_payload] dates-index upload skipped: release {tag!r} missing")
        return False
    # nosemgrep: dangerous-subprocess-use-audit, dangerous-subprocess-use-tainted-env-args
    subprocess.run(
        [gh, "release", "upload", tag, str(index_path), "--repo", repo, "--clobber"],
        check=True, timeout=SUBPROCESS_UPLOAD_TIMEOUT_SEC,
    )
    return True


def refresh_dates_index(
    runs_root: Path,
    *,
    repo: str = DEFAULT_REPO,
    tag: str = DEFAULT_TAG,
    min_date: str = HISTORY_MIN_DATE,
) -> bool:
    """Rebuild ``dates-index.json`` from published dated releases and upload to rolling tag."""
    gh = _gh_available()
    if not gh or not _gh_authed(gh):
        print("[app_payload] dates-index refresh skipped: no gh auth")
        return False

    dates = _published_history_dates(repo, min_date=min_date)
    if not dates:
        disk_dates = [d for d, _ in iter_valid_export_dates(runs_root, from_date=min_date)]
        dates = sorted(set(disk_dates))
    if not dates:
        print("[app_payload] dates-index refresh skipped: no published dates")
        return False

    index = build_dates_index(dates, min_date=min_date, repo=repo, tag=tag)
    payload = {
        "schema_version": index["schema_version"],
        "dates": index["dates"],
        "count": index["count"],
        "min_date": index["min_date"],
        "latest_date": index["latest_date"],
    }
    out_dir = runs_root.expanduser().resolve() / ".dates-index"
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / DATES_INDEX_FILENAME
    index_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    try:
        ok = _upload_dates_index(gh, repo, tag, index_path)
    except subprocess.SubprocessError as exc:
        print(f"[app_payload] dates-index upload failed error={exc!r}")
        return False
    print(
        f"[app_payload] dates-index refresh finished count={index['count']} "
        f"latest={index['latest_date']} uploaded={ok}"
    )
    return ok


def _update_release_title(gh: str, repo: str, tag: str, run_date: str) -> bool:
    """Refresh a release title to match the manifest run_date (rolling or dated)."""
    if not run_date:
        return False
    title = release_display_title(tag, run_date)
    try:
        # nosemgrep: dangerous-subprocess-use-audit, dangerous-subprocess-use-tainted-env-args
        res = subprocess.run(
            [gh, "release", "edit", tag, "--repo", repo, "--title", title],
            capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SEC,
        )
        if res.returncode == 0:
            print(f"[app_payload] release title updated to {title!r}")
            return True
        print(
            f"[app_payload] release title update failed (exit={res.returncode}): "
            f"{(res.stderr or res.stdout or '').strip()}"
        )
        return False
    except Exception as exc:  # noqa: BLE001 - title sync must never fail publish
        print(f"[app_payload] release title update skipped (non-fatal): {exc}")
        return False


def _gh_authed(gh: str) -> bool:
    if os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"):
        return True
    try:
        # nosemgrep: dangerous-subprocess-use-audit - fixed argv, shell=False, no user input.
        res = subprocess.run(
            [gh, "auth", "status"], capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SEC
        )
        return res.returncode == 0
    except Exception:
        return False


def _prune_release_assets(gh: str, repo: str, tag: str, keep_names: set[str]) -> int:
    """Delete obsolete content-addressed data assets, keeping the current manifest's
    assets plus the KEEP_RECENT_ASSETS newest. Best-effort; returns count deleted."""
    # nosemgrep: dangerous-subprocess-use-audit, dangerous-subprocess-use-tainted-env-args
    listed = subprocess.run(
        [gh, "release", "view", tag, "--repo", repo, "--json", "assets",
         "-q", '.assets[] | "\\(.name)\\t\\(.createdAt)"'],
        capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SEC,
    )
    if listed.returncode != 0:
        return 0
    data: List[Tuple[str, str]] = []
    for line in listed.stdout.splitlines():
        name, _, created = line.partition("\t")
        if name.startswith(("core-", "details-", "search-index-", "history-banks-", "bank-history-", "rba-calendar-")) and name.endswith((".json.gz", ".json.gz.enc")):
            data.append((name, created))
    data.sort(key=lambda x: x[1], reverse=True)  # newest first
    deleted = 0
    for idx, (name, _created) in enumerate(data):
        if name in keep_names or idx < KEEP_RECENT_ASSETS:
            continue
        # nosemgrep: dangerous-subprocess-use-audit, dangerous-subprocess-use-tainted-env-args
        res = subprocess.run(
            [gh, "release", "delete-asset", tag, name, "--repo", repo, "-y"],
            capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SEC,
        )
        if res.returncode == 0:
            deleted += 1
    return deleted


def _manifest_should_replace(
    status: str,
    live: Optional[Dict[str, Any]],
    *,
    our_run_date: str,
    our_gen: str,
    tag: str,
    force: bool,
) -> Tuple[bool, str]:
    """Decide whether to replace the live manifest on ``tag`` (rolling vs dated rules)."""
    if force:
        return True, "force"
    if status == "error":
        return False, "live_manifest_verify_error"
    if status == "missing":
        return True, "missing"
    live_run_date = str((live or {}).get("run_date") or "")
    live_gen = str((live or {}).get("generated_at") or "")
    if is_rolling_tag(tag):
        live_newer = bool(live_run_date) and (
            live_run_date > our_run_date
            or (live_run_date == our_run_date and live_gen > our_gen)
        )
    else:
        # Dated snapshots only skip a same-day correction with a newer generated_at.
        live_newer = live_run_date == our_run_date and live_gen > our_gen
    if live_newer:
        return False, "live_newer"
    return True, "ok"


def _live_manifest_status(repo: str, tag: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Return the live release manifest's state, distinguishing a transient failure from
    a genuinely missing manifest: ("present", dict) | ("missing", None) | ("error", None).
    Uses the public asset URL (follows the 302 redirect) so a 404 is unambiguous."""
    url = f"https://github.com/{repo}/releases/download/{tag}/manifest.json"
    try:
        with urllib.request.urlopen(url, timeout=SUBPROCESS_TIMEOUT_SEC) as resp:  # nosec B310 - https URL
            return "present", json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return ("missing", None) if exc.code == 404 else ("error", None)
    except Exception:
        return "error", None


def publish_payload(
    payload_dir: Path,
    *,
    repo: str = DEFAULT_REPO,
    tag: str = DEFAULT_TAG,
    dry_run: bool = False,
    require_token: bool = False,
    force: bool = False,
) -> bool:
    """Upload manifest + core + details to the rolling release. Returns True on upload.

    Token-gated: with no gh/auth it prints a message and returns False (a no-op),
    unless ``require_token`` is set, in which case it raises. ``force`` overrides the
    "don't overwrite a newer live manifest" guard (operator-confirmed downgrade).
    """
    manifest_path = payload_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"no manifest.json in {payload_dir} (run build first)")
    manifest = _load_json(manifest_path)
    names = [entry["name"] for entry in manifest["files"].values()]
    # Upload the data assets first and the manifest LAST, so the rolling manifest is
    # never left pointing at a missing/half-replaced asset if an upload fails.
    data_assets = [payload_dir / n for n in names]
    assets = data_assets + [manifest_path]
    missing = [str(a) for a in assets if not a.exists()]
    if missing:
        raise FileNotFoundError(f"missing payload assets: {missing}")

    gh = _gh_available()
    if not gh or not _gh_authed(gh):
        msg = (
            "[app_payload] gh CLI / GitHub auth not available - skipping publish. "
            "Set GH_TOKEN (contents:read+write) to enable the daily upload."
        )
        if require_token:
            raise RuntimeError(msg)
        print(msg)
        print(
            f"[app_payload] publish skipped run_date={str(manifest.get('run_date') or '')} "
            "reason=no_gh_auth exit=0"
        )
        return False

    our_run_date = str(manifest.get("run_date") or "")
    our_gen = str(manifest.get("generated_at") or "")
    print(
        f"[app_payload] publish starting run_date={our_run_date} tag={tag} repo={repo} "
        f"assets={[*names, 'manifest.json']}"
    )
    rolling = is_rolling_tag(tag)
    title = release_title(our_run_date) if rolling else dated_release_title(our_run_date)
    notes = (
        "Rolling mobile-app data payload. Updated automatically by the daily Pi ingest."
        if rolling
        else f"Immutable mobile-app data snapshot for run_date {our_run_date}."
    )
    if dry_run:
        print(
            f"[app_payload] publish dry-run run_date={our_run_date} tag={tag} repo={repo} "
            f"assets={[a.name for a in assets]}"
        )
        return False

    # Ensure the release/tag exists (idempotent). All calls use a fixed argv with
    # shell=False and a timeout; repo/tag/paths are operator-controlled, not untrusted.
    # nosemgrep: dangerous-subprocess-use-audit, dangerous-subprocess-use-tainted-env-args
    view = subprocess.run(
        [gh, "release", "view", tag, "--repo", repo],
        capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SEC,
    )
    if view.returncode != 0:
        # nosemgrep: dangerous-subprocess-use-audit, dangerous-subprocess-use-tainted-env-args
        subprocess.run(
            [gh, "release", "create", tag, "--repo", repo, "--title", title,
             "--notes", notes, "--latest=false"],
            check=True, timeout=SUBPROCESS_TIMEOUT_SEC,
        )

    # Data assets are content-addressed, so a same-name asset already on the release is
    # byte-identical. Upload only the MISSING ones, WITHOUT --clobber — never delete an
    # asset the current manifest still references (an interrupted clobber could lose it).
    # nosemgrep: dangerous-subprocess-use-audit, dangerous-subprocess-use-tainted-env-args
    listed = subprocess.run(
        [gh, "release", "view", tag, "--repo", repo, "--json", "assets", "-q", ".assets[].name"],
        capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SEC,
    )
    existing = set(listed.stdout.split()) if listed.returncode == 0 else set()
    to_upload = [a for a in data_assets if a.name not in existing]
    if to_upload:
        # nosemgrep: dangerous-subprocess-use-audit, dangerous-subprocess-use-tainted-env-args
        subprocess.run(
            [gh, "release", "upload", tag, *[str(a) for a in to_upload], "--repo", repo],
            check=True, timeout=SUBPROCESS_UPLOAD_TIMEOUT_SEC,
        )
    # ...then replace manifest.json last, so it only ever points at assets already live.
    # First check the live manifest, distinguishing present / missing / transient-error.
    status, live = _live_manifest_status(repo, tag)

    should_replace, replace_reason = _manifest_should_replace(
        status,
        live,
        our_run_date=our_run_date,
        our_gen=our_gen,
        tag=tag,
        force=force,
    )
    if not should_replace:
        reason = replace_reason
        if reason == "live_manifest_verify_error":
            print(
                "[app_payload] publish failed run_date="
                f"{our_run_date} reason=live_manifest_verify_error exit=0"
            )
            return False
        live_run_date = str((live or {}).get("run_date") or "")
        live_gen = str((live or {}).get("generated_at") or "")
        print(
            f"[app_payload] publish skipped manifest run_date={our_run_date} tag={tag} "
            f"(live run_date={live_run_date} generated_at={live_gen} is newer; "
            f"uploaded {len(to_upload)} new data asset(s); pass force=true to override)"
        )
        return False

    # Keep the displaced manifest so a failed --clobber replacement can be rolled back.
    backup_gen = str((live or {}).get("generated_at") or "") if status == "present" else None
    backup_dir = payload_dir / ".prev-manifest"
    backup_manifest = backup_dir / "manifest.json"
    backup_dir.mkdir(exist_ok=True)
    if backup_manifest.exists():
        backup_manifest.unlink()
    if status == "present" and live is not None:
        backup_manifest.write_text(json.dumps(live), encoding="utf-8")

    try:
        # nosemgrep: dangerous-subprocess-use-audit, dangerous-subprocess-use-tainted-env-args
        subprocess.run(
            [gh, "release", "upload", tag, str(manifest_path), "--repo", repo, "--clobber"],
            check=True, timeout=SUBPROCESS_UPLOAD_TIMEOUT_SEC,
        )
    except subprocess.SubprocessError:
        # Restore the displaced manifest ONLY after positively confirming it's safe:
        # the live manifest is now genuinely missing, or still the one we displaced
        # (generated_at unchanged). A transient recheck error -> do NOT restore (we can't
        # confirm we wouldn't clobber a newer concurrent publish).
        if backup_manifest.exists():
            recheck, cur = _live_manifest_status(repo, tag)
            cur_gen = str((cur or {}).get("generated_at") or "")
            safe_to_restore = recheck == "missing" or (
                recheck == "present" and backup_gen is not None and cur_gen <= backup_gen
            )
            if safe_to_restore:
                try:
                    # nosemgrep: dangerous-subprocess-use-audit, dangerous-subprocess-use-tainted-env-args
                    subprocess.run(
                        [gh, "release", "upload", tag, str(backup_manifest), "--repo", repo, "--clobber"],
                        check=True, timeout=SUBPROCESS_UPLOAD_TIMEOUT_SEC,
                    )
                    print("[app_payload] restored previous manifest after a failed replacement upload")
                except subprocess.SubprocessError:
                    print("[app_payload] WARNING: manifest upload failed AND restore failed")
            else:
                print(f"[app_payload] not restoring backup (live recheck={recheck}); avoiding a clobber")
        raise
    print(
        f"[app_payload] publish succeeded run_date={our_run_date} tag={tag} repo={repo} "
        f"manifest_replaced=true new_data_assets={len(to_upload)} exit=0"
    )
    _update_release_title(gh, repo, tag, our_run_date)
    if rolling:
        # Prune obsolete assets so the rolling release never hits GitHub's 1000-asset cap.
        try:
            keep = set(names)
            pruned = _prune_release_assets(gh, repo, tag, keep)
            if pruned:
                print(f"[app_payload] pruned {pruned} obsolete release asset(s)")
        except Exception as exc:  # noqa: BLE001 - pruning must never fail a publish
            print(f"[app_payload] asset prune skipped (non-fatal): {exc}")
    return True


def _list_payload_release_tags(gh: str, repo: str) -> List[str]:
    """Return sorted ``app-payload-*`` release tag names from GitHub."""
    # nosemgrep: dangerous-subprocess-use-audit, dangerous-subprocess-use-tainted-env-args
    res = subprocess.run(
        [gh, "release", "list", "--repo", repo, "--limit", "500", "--json", "tagName",
         "-q", ".[].tagName"],
        capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SEC,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"gh release list failed (exit={res.returncode}): "
            f"{(res.stderr or res.stdout or '').strip()}"
        )
    tags = [line.strip() for line in res.stdout.splitlines() if line.strip()]
    return sorted(t for t in tags if is_rolling_tag(t) or is_dated_tag(t))


def _release_current_title(gh: str, repo: str, tag: str) -> str:
    # nosemgrep: dangerous-subprocess-use-audit, dangerous-subprocess-use-tainted-env-args
    res = subprocess.run(
        [gh, "release", "view", tag, "--repo", repo, "--json", "name", "-q", ".name"],
        capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SEC,
    )
    if res.returncode != 0:
        return ""
    return res.stdout.strip()


def _release_run_date_for_retitle(repo: str, tag: str) -> str:
    """Resolve manifest run_date for retitle (tag suffix or live manifest)."""
    if is_dated_tag(tag):
        return tag[len(DATED_TAG_PREFIX) :]
    status, live = _live_manifest_status(repo, tag)
    if status == "present" and live:
        return str(live.get("run_date") or "")
    return ""


def retitle_payload_releases(
    *,
    repo: str = DEFAULT_REPO,
    from_date: str = "",
    to_date: str = "",
    dry_run: bool = False,
) -> Tuple[int, int]:
    """Retitle existing app-payload releases. Returns ``(updated, skipped)``."""
    gh = _gh_available()
    if not gh or not _gh_authed(gh):
        raise RuntimeError(
            "[app_payload] gh CLI / GitHub auth required for retitle "
            "(set GH_TOKEN or gh auth login)"
        )
    tags = _list_payload_release_tags(gh, repo)
    updated = 0
    skipped = 0
    print(
        f"[app_payload] retitle starting repo={repo} tags={len(tags)} "
        f"from={from_date or '*'} to={to_date or '*'} dry_run={dry_run}"
    )
    for tag in tags:
        run_date = _release_run_date_for_retitle(repo, tag)
        if not run_date:
            print(f"[app_payload] retitle skip tag={tag} reason=no_run_date")
            skipped += 1
            continue
        if from_date and run_date < from_date:
            continue
        if to_date and run_date > to_date:
            continue
        want = release_display_title(tag, run_date)
        current = _release_current_title(gh, repo, tag)
        if current == want:
            print(f"[app_payload] retitle skip tag={tag} reason=already_current")
            skipped += 1
            continue
        if dry_run:
            print(f"[app_payload] retitle dry-run tag={tag} {current!r} -> {want!r}")
            updated += 1
            continue
        if _update_release_title(gh, repo, tag, run_date):
            updated += 1
        else:
            skipped += 1
    print(f"[app_payload] retitle finished updated={updated} skipped={skipped}")
    return updated, skipped

def build_and_publish(
    exports_dir: Path,
    *,
    repo: str = DEFAULT_REPO,
    tag: str = DEFAULT_TAG,
    out_dir: Optional[Path] = None,
) -> Tuple[Dict[str, Any], bool]:
    """Build + publish to a single release tag (legacy / CI helper)."""
    out_dir = out_dir or (exports_dir / "app-payload")
    manifest = build_payload(exports_dir, out_dir, repo=repo, tag=tag)
    published = publish_payload(out_dir, repo=repo, tag=tag)
    return manifest, published


def build_and_publish_dual(
    exports_dir: Path,
    *,
    repo: str = DEFAULT_REPO,
    out_dir: Optional[Path] = None,
    update_latest: bool = True,
) -> Tuple[Dict[str, Any], bool, bool]:
    """Build + publish immutable dated snapshot and rolling latest (when allowed).

    Returns ``(manifest, published_dated, published_latest)``. The dated release uses
    ``app-payload-<run_date>``; rolling ``app-payload-latest`` is updated only when
    ``run_date`` is not older than the live rolling manifest (unless ``--force`` on
    the latest publish path — not exposed here; backfill handles end-of-run refresh).
    """
    # Decide whether the rolling latest will actually be (re)published BEFORE the
    # expensive compute (one live-manifest check, reused below): if a newer release
    # is already live (e.g. a backfill), the rolling build is skipped — and so is
    # the rolling-only history/search scan.
    latest = _load_json(exports_dir / "dashboard-cache" / "latest.json")
    run_date = str(latest.get("run_date") or "")
    if not run_date:
        raise ValueError("latest.json has no run_date")

    need_latest = False
    live_run_date = ""
    if update_latest:
        status, live = _live_manifest_status(repo, DEFAULT_TAG)
        live_run_date = str((live or {}).get("run_date") or "") if status == "present" else ""
        need_latest = not (live_run_date and live_run_date > run_date)

    # Compute the (tag-independent) payload data ONCE, then package both releases.
    # History/search are rolling-only, so only compute them when the rolling latest
    # will be built. Previously each release rebuilt from scratch every run.
    data = _compute_payload(exports_dir, include_history=need_latest)

    dated = dated_tag(run_date)
    out_dated = out_dir or (exports_dir / "app-payload")
    manifest = _package_payload(data, out_dated, repo=repo, tag=dated)
    try:
        published_dated = publish_payload(out_dated, repo=repo, tag=dated)
    except Exception as exc:  # noqa: BLE001 - rolling latest must still run
        published_dated = False
        print(
            f"[app_payload] dated publish failed run_date={run_date} tag={dated} error={exc!r}"
        )
    else:
        print(
            f"[app_payload] dated publish finished run_date={run_date} tag={dated} "
            f"published={published_dated}"
        )

    published_latest = False
    if update_latest:
        if need_latest:
            out_latest = exports_dir / "app-payload-latest"
            _package_payload(data, out_latest, repo=repo, tag=DEFAULT_TAG)
            published_latest = publish_payload(out_latest, repo=repo, tag=DEFAULT_TAG)
            print(
                f"[app_payload] rolling latest publish finished run_date={run_date} "
                f"tag={DEFAULT_TAG} published={published_latest}"
            )
        else:
            print(
                f"[app_payload] rolling latest skipped run_date={run_date} "
                f"(live run_date={live_run_date} is newer)"
            )
    return manifest, published_dated, published_latest


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _cmd_build(args: argparse.Namespace) -> int:
    exports_dir = Path(args.exports).resolve()
    out_dir = Path(args.out).resolve() if args.out else (exports_dir / "app-payload")
    manifest = build_payload(exports_dir, out_dir, repo=args.repo, tag=args.tag)
    core = manifest["files"]["core"]
    details = manifest["files"]["details"]
    print(f"[app_payload] built payload for run_date={manifest['run_date']} -> {out_dir}")
    print(f"  manifest.json")
    print(f"  {core['name']} ({core['bytes'] / 1024:.0f} KiB gz)")
    print(f"  {details['name']} ({details['bytes'] / 1024:.0f} KiB gz)")
    for section, data in core_section_summary(out_dir).items():
        print(f"  {section}: {data}")
    if args.publish:
        publish_payload(out_dir, repo=args.repo, tag=args.tag, dry_run=args.dry_run)
    return 0


def core_section_summary(out_dir: Path) -> Dict[str, str]:
    """Read back the built core for a one-line per-section summary (CLI nicety)."""
    manifest = _load_json(out_dir / "manifest.json")
    core_path = out_dir / manifest["files"]["core"]["name"]
    core = json.loads(gzip.decompress(core_path.read_bytes()).decode("utf-8"))
    summary: Dict[str, str] = {}
    for section, data in core.get("sections", {}).items():
        rng = data.get("ribbon", {}).get("range", {})
        lo = rng.get("min")
        hi = rng.get("max")
        lo_s = f"{lo * 100:.2f}%" if isinstance(lo, (int, float)) else "-"
        hi_s = f"{hi * 100:.2f}%" if isinstance(hi, (int, float)) else "-"
        summary[section] = f"{len(data.get('rates', []))} rates, range {lo_s}..{hi_s}"
    return summary


def _cmd_publish(args: argparse.Namespace) -> int:
    payload_dir = Path(args.dir).resolve()
    publish_payload(
        payload_dir,
        repo=args.repo,
        tag=args.tag,
        dry_run=args.dry_run,
        require_token=args.require_token,
        force=args.force,
    )
    return 0


def _cmd_seed(args: argparse.Namespace) -> int:
    sample_dir = Path(args.sample).resolve()
    out_dir = Path(args.out).resolve()
    manifest = seed_from_sample(sample_dir, out_dir, repo=args.repo, tag=args.tag)
    print(f"[app_payload] seeded payload from sample run_date={manifest['run_date']} -> {out_dir}")
    if args.publish:
        publish_payload(out_dir, repo=args.repo, tag=args.tag, dry_run=args.dry_run)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build/publish the AR-local mobile app payload.")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub repo (default: %(default)s)")
    parser.add_argument(
        "--tag",
        default=DEFAULT_TAG,
        help="Release tag: app-payload-latest (rolling) or app-payload-YYYY-MM-DD (dated snapshot)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="Build manifest + core + details from a run export.")
    b.add_argument("--exports", required=True, help="Path to a run's _exports directory.")
    b.add_argument("--out", default="", help="Output dir (default <exports>/app-payload).")
    b.add_argument("--publish", action="store_true", help="Publish after building.")
    b.add_argument("--dry-run", action="store_true", help="With --publish, only print intended uploads.")
    b.set_defaults(func=_cmd_build)

    p = sub.add_parser("publish", help="Publish an already-built payload dir to the release.")
    p.add_argument("--dir", required=True, help="Payload dir containing manifest.json + assets.")
    p.add_argument("--dry-run", action="store_true", help="Only print intended uploads.")
    p.add_argument("--require-token", action="store_true", help="Fail (non-zero) if no gh/token.")
    p.add_argument("--force", action="store_true", help="Overwrite even a newer live manifest.")
    p.set_defaults(func=_cmd_publish)

    s = sub.add_parser("seed", help="Repackage the committed app sample into a publishable payload.")
    s.add_argument("--sample", default="mobile/assets/sample", help="Dir with core.json/details.json (default: %(default)s).")
    s.add_argument("--out", required=True, help="Output payload dir.")
    s.add_argument("--publish", action="store_true", help="Publish after seeding.")
    s.add_argument("--dry-run", action="store_true", help="With --publish, only print intended uploads.")
    s.set_defaults(func=_cmd_seed)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
