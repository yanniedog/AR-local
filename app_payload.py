"""Build and publish the compact mobile-app payload for AR-local.

The Raspberry Pi daily ingest already produces a compact, dashboard-ready
``dashboard-cache/<run_date>/banks.json`` plus a ``dashboard-cache/latest.json``
manifest. This module reshapes those (pure Python, no SQLite and no running
dashboard server) into three small artifacts the mobile app downloads from a
rolling GitHub Release:

  * ``manifest.json``          - tiny; the app polls this first.
  * ``core-<date>.json.gz``    - section rates + ribbon stats + brands + RBA series.
  * ``details-<date>.json.gz`` - per-product fees/features/eligibility/constraints.

Usage::

    python app_payload.py build  --exports runs/2026-05-19/_exports --out <dir>
    python app_payload.py publish --dir <app-payload dir> [--repo owner/name]

``build`` is deterministic and CI-friendly. ``publish`` uploads via the ``gh``
CLI and is token-gated: with no ``gh`` auth / ``GH_TOKEN`` it prints a clear
message and no-ops (exit 0) so it is safe to wire into the daily pipeline before
the Pi has a token.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent

SCHEMA_VERSION = 1
DEFAULT_REPO = os.environ.get("AR_LOCAL_REPO", "yanniedog/AR-local")
DEFAULT_TAG = os.environ.get("AR_LOCAL_APP_PAYLOAD_TAG", "app-payload-latest")
APP_MIN_VERSION = "1.0.0"

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
# Ribbon aggregate (faithful port of aggregate_ribbon_rows in the dashboard server)
# --------------------------------------------------------------------------- #
def _normalized_rate_value(raw: Any, dataset: str, percent_style: bool) -> Optional[float]:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not value or value <= 0:
        return None
    if percent_style:
        return value / 100.0
    if dataset == "Mortgage" and 0.3 < value <= 1:
        return value / 10.0
    return value / 100.0 if value > 1 else value


def _stats(values: List[float]) -> Dict[str, Optional[float]]:
    if not values:
        return {"min": None, "max": None, "mean": None, "median": None}
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    median = ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    return {
        "min": ordered[0],
        "max": ordered[-1],
        "mean": sum(ordered) / n,
        "median": median,
    }


def aggregate_ribbon(rows: List[Dict[str, Any]], section: str) -> Dict[str, Any]:
    keys = [
        str(row.get("product_key") or row.get("product_id") or row.get("product_name") or "")
        for row in rows
    ]
    percent_style: set[str] = set()
    for key, row in zip(keys, rows):
        try:
            raw = float(row.get("rate"))
        except (TypeError, ValueError):
            continue
        if key and raw > 1:
            percent_style.add(key)

    providers: Dict[str, Dict[str, Any]] = {}
    rates: List[float] = []
    products: set[str] = set()
    for key, row in zip(keys, rows):
        rate = _normalized_rate_value(row.get("rate"), section, key in percent_style)
        if rate is None:
            continue
        provider = str(row.get("provider") or "Unknown")
        products.add(key)
        rates.append(rate)
        bucket = providers.setdefault(provider, {"rates": [], "products": set()})
        bucket["rates"].append(rate)
        bucket["products"].add(key)

    return {
        "counts": {
            "rates": len(rates),
            "products": len(products),
            "providers": len(providers),
        },
        "range": _stats(rates),
        "providers": [
            {
                "provider": provider,
                "rates": len(bucket["rates"]),
                "products": len(bucket["products"]),
                **_stats(bucket["rates"]),
            }
            for provider, bucket in sorted(providers.items())
        ],
    }


# --------------------------------------------------------------------------- #
# Brands (monogram avatars - short code + deterministic colour, no external CDN)
# --------------------------------------------------------------------------- #
_BRAND_SHORT_RE = re.compile(r"""['"]([^'"]+)['"]\s*:\s*\{[^}]*?short\s*:\s*['"]([^'"]+)['"]""")

# Pleasant, high-contrast palette for monogram avatars (deterministic per provider).
_BRAND_PALETTE = (
    "#1f6feb", "#0a7d33", "#b7791f", "#9333ea", "#c2410c",
    "#0e7490", "#be123c", "#4338ca", "#15803d", "#a16207",
    "#7c3aed", "#0369a1", "#b91c1c", "#047857", "#6d28d9",
)


def load_brand_shortcodes(rba_dir: Path) -> Dict[str, str]:
    """Extract ``lower(name) -> short`` from dashboard/ar-bank-brand.js (best effort)."""
    path = rba_dir / "ar-bank-brand.js"
    out: Dict[str, str] = {}
    if not path.exists():
        return out
    text = path.read_text(encoding="utf-8", errors="ignore")
    for name, short in _BRAND_SHORT_RE.findall(text):
        out[name.strip().lower()] = short.strip()
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


def build_brands(providers: Iterable[str], shortcodes: Dict[str, str]) -> Dict[str, Dict[str, str]]:
    brands: Dict[str, Dict[str, str]] = {}
    for provider in sorted({p for p in providers if p}):
        key = provider.lower()
        short = shortcodes.get(key) or _derive_short(provider)
        brands[provider] = {"short": short, "color": _brand_color(provider)}
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
    candidate = exports_dir / "dashboard-cache" / run_date / "banks.json"
    if candidate.exists():
        return candidate
    # Fall back to any banks.json under dashboard-cache/<date>/.
    matches = sorted((exports_dir / "dashboard-cache").glob("*/banks.json"))
    if matches:
        return matches[-1]
    raise FileNotFoundError(f"banks.json not found under {exports_dir / 'dashboard-cache'}")


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


def _asset(out_dir: Path, name: str, gz: bytes, release_base: str) -> Dict[str, Any]:
    (out_dir / name).write_bytes(gz)
    return {
        "name": name,
        "bytes": len(gz),
        "sha256": hashlib.sha256(gz).hexdigest(),
        "url": f"{release_base}/{name}",
    }


def build_payload(
    exports_dir: Path,
    out_dir: Path,
    *,
    repo: str = DEFAULT_REPO,
    tag: str = DEFAULT_TAG,
    dashboard_dir: Path = BASE_DIR / "dashboard",
) -> Dict[str, Any]:
    """Build manifest + core + details into ``out_dir``; return the manifest dict."""
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
        sections[section] = {
            "rates": [compact({k: r.get(k) for k in CORE_RATE_FIELDS}) for r in section_rows],
            "ribbon": aggregate_ribbon(section_rows, section),
        }

    shortcodes = load_brand_shortcodes(dashboard_dir)
    # NB: no wall-clock field inside core/details. They are content-hashed (sha256
    # in the manifest) and the app skips re-download when the hash is unchanged, so
    # a same-day rebuild (e.g. the watchdog rerun) must yield identical bytes.
    core = {
        "schema_version": SCHEMA_VERSION,
        "run_date": run_date,
        "sections": sections,
        "brands": build_brands(providers_seen, shortcodes),
        "rba": load_rba_series(dashboard_dir),
    }
    details = {
        "schema_version": SCHEMA_VERSION,
        "run_date": run_date,
        "products": build_details(products),
    }

    counts = latest.get("banks_counts") or banks.get("counts") or {}
    return _package(core, details, run_date, out_dir, repo=repo, tag=tag, counts=counts)


def _package(
    core: Dict[str, Any],
    details: Dict[str, Any],
    run_date: str,
    out_dir: Path,
    *,
    repo: str,
    tag: str,
    counts: Dict[str, Any],
) -> Dict[str, Any]:
    """Gzip core/details, write them + a manifest (sha256/bytes/urls) into out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    release_base = f"https://github.com/{repo}/releases/download/{tag}"
    files = {
        "core": _asset(out_dir, f"core-{run_date}.json.gz", _gzip_bytes(core), release_base),
        "details": _asset(out_dir, f"details-{run_date}.json.gz", _gzip_bytes(details), release_base),
    }
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


def _gh_authed(gh: str) -> bool:
    if os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"):
        return True
    try:
        res = subprocess.run([gh, "auth", "status"], capture_output=True, text=True, timeout=30)
        return res.returncode == 0
    except Exception:
        return False


def publish_payload(
    payload_dir: Path,
    *,
    repo: str = DEFAULT_REPO,
    tag: str = DEFAULT_TAG,
    dry_run: bool = False,
    require_token: bool = False,
) -> bool:
    """Upload manifest + core + details to the rolling release. Returns True on upload.

    Token-gated: with no gh/auth it prints a message and returns False (a no-op),
    unless ``require_token`` is set, in which case it raises.
    """
    manifest_path = payload_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"no manifest.json in {payload_dir} (run build first)")
    manifest = _load_json(manifest_path)
    names = [manifest["files"]["core"]["name"], manifest["files"]["details"]["name"]]
    assets = [manifest_path] + [payload_dir / n for n in names]
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
        return False

    title = f"App payload (rolling) - {manifest.get('run_date')}"
    notes = "Rolling mobile-app data payload. Updated automatically by the daily Pi ingest."
    if dry_run:
        print(f"[app_payload] DRY-RUN would publish {len(assets)} assets to {repo}@{tag}:")
        for a in assets:
            print(f"  - {a.name}")
        return False

    # Ensure the release/tag exists (idempotent), then clobber-upload the assets.
    view = subprocess.run(
        [gh, "release", "view", tag, "--repo", repo], capture_output=True, text=True
    )
    if view.returncode != 0:
        subprocess.run(
            [gh, "release", "create", tag, "--repo", repo, "--title", title,
             "--notes", notes, "--latest=false"],
            check=True,
        )
    subprocess.run(
        [gh, "release", "upload", tag, *[str(a) for a in assets], "--repo", repo, "--clobber"],
        check=True,
    )
    print(f"[app_payload] published {len(assets)} assets to {repo}@{tag} (run_date={manifest.get('run_date')})")
    return True


def build_and_publish(
    exports_dir: Path,
    *,
    repo: str = DEFAULT_REPO,
    tag: str = DEFAULT_TAG,
    out_dir: Optional[Path] = None,
) -> Tuple[Dict[str, Any], bool]:
    """Convenience entry point for the Pi daily pipeline (build then best-effort publish)."""
    out_dir = out_dir or (exports_dir / "app-payload")
    manifest = build_payload(exports_dir, out_dir, repo=repo, tag=tag)
    published = publish_payload(out_dir, repo=repo, tag=tag)
    return manifest, published


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
        payload_dir, repo=args.repo, tag=args.tag, dry_run=args.dry_run, require_token=args.require_token
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
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"GitHub repo (default {DEFAULT_REPO})")
    parser.add_argument("--tag", default=DEFAULT_TAG, help=f"Rolling release tag (default {DEFAULT_TAG})")
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
    p.set_defaults(func=_cmd_publish)

    s = sub.add_parser("seed", help="Repackage the committed app sample into a publishable payload.")
    s.add_argument("--sample", default="mobile/assets/sample", help="Dir with core.json/details.json.")
    s.add_argument("--out", required=True, help="Output payload dir.")
    s.add_argument("--publish", action="store_true", help="Publish after seeding.")
    s.add_argument("--dry-run", action="store_true", help="With --publish, only print intended uploads.")
    s.set_defaults(func=_cmd_seed)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
