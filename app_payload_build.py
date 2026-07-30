"""Build and package mobile-app payload artifacts from CDR exports."""
from __future__ import annotations

import gzip
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import app_payload_mobile
import cdr_brand_logos
import payload_crypto
import rba_decisions
from cdr_ribbon_normalize import aggregate_ribbon, normalized_rate_value as _normalized_rate_value

from app_payload_brands import (
    build_brands,
    load_brand_logos,
    load_brand_shortcodes,
    load_rba_holds,
    load_rba_series,
)
from app_payload_common import (
    APP_MIN_VERSION,
    BASE_DIR,
    CORE_RATE_FIELDS,
    DEFAULT_REPO,
    DEFAULT_TAG,
    SCHEMA_VERSION,
    VALID_SECTIONS,
    _RUN_DATE_RE,
    _app_payload,
    _is_blank,
    compact,
    dated_tag,
    is_rolling_tag,
    section_filter,
    utc_now_iso,
    _load_json,
)
from app_payload_details import build_details
from app_payload_publish import publish_payload

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
        "rba_holds": load_rba_holds(dashboard_dir),
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
        status, live = _app_payload("_live_manifest_status")(repo, DEFAULT_TAG)
        live_run_date = str((live or {}).get("run_date") or "") if status == "present" else ""
        need_latest = not (live_run_date and live_run_date > run_date)

    # Compute the (tag-independent) payload data ONCE, then package both releases.
    # History/search are rolling-only, so only compute them when the rolling latest
    # will be built. Previously each release rebuilt from scratch every run.
    data = _app_payload("_compute_payload")(exports_dir, include_history=need_latest)

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
