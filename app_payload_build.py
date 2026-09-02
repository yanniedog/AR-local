"""Build and package mobile-app payload artifacts from CDR exports."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import math
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import app_payload_mobile
import rba_decisions
from cdr_ribbon_normalize import aggregate_ribbon, normalized_rate_value as _normalized_rate_value
from cdr_clean_export import app_coverage_aliases, coverage_summary
from cdr_observation import load_verified_observation

from app_payload_contracts import validate_coverage

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
    _load_json,
)
from app_payload_details import build_details
from app_payload_publish import publish_payload

def _ingest_schedule() -> Dict[str, Any]:
    try:
        import ar_local_ingest_schedule as sched  # local module

        return {"label": sched.DAILY_INGEST_SCHEDULE_LABEL}
    except Exception:  # pragma: no cover - schedule is informational only
        return {"label": "Daily"}


def _gzip_bytes(obj: Any) -> bytes:
    raw = json.dumps(
        obj,
        separators=(",", ":"),
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    stream = io.BytesIO()
    # GzipFile fixes filename, mtime, compression, and the cross-platform OS byte.
    with gzip.GzipFile(
        filename="", mode="wb", fileobj=stream, compresslevel=9, mtime=0
    ) as archive:
        archive.write(raw)
    encoded = stream.getvalue()
    if encoded[9] != 255:
        raise RuntimeError("gzip OS header is not reproducible")
    return encoded


def _asset(
    out_dir: Path,
    kind: str,
    run_date: str,
    gz: bytes,
    release_base: str,
) -> Dict[str, Any]:
    # Content-addressed name (kind-<run_date>-<sha12>.json.gz[.enc]): a new/corrected
    # payload gets a NEW filename, so uploading it never overwrites an asset the
    # previously published manifest still references. Old manifests stay internally
    # consistent until the new manifest.json is published last.
    sha = hashlib.sha256(gz).hexdigest()
    name = f"{kind}-{run_date}-{sha[:12]}.json.gz"
    (out_dir / name).write_bytes(gz)
    entry: Dict[str, Any] = {
        "name": name,
        "bytes": len(gz),
        "sha256": sha,
        "url": f"{release_base}/{name}",
    }
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
    asset_dir: Path = BASE_DIR / "payload_assets",
    contract_coverage: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build manifest + core + details into ``out_dir``; return the manifest dict."""
    # Only the rolling release ships search-index + history assets (see _package's
    # is_rolling_tag gate), so a dated build needn't compute them at all.
    data = _compute_payload(
        exports_dir,
        asset_dir=asset_dir,
        include_history=is_rolling_tag(tag),
        contract_coverage=contract_coverage,
    )
    return _package_payload(data, out_dir, repo=repo, tag=tag)


def _apply_contract_provider_counts(
    coverage: Dict[str, Any], contract_coverage: Mapping[str, Any]
) -> None:
    """Make the ingest's audited provider accounting the one the app is told.

    ``coverage_summary`` re-derives provider health from the exported rows:
    ``providers_failed`` is "has a failure record and produced no rows".
    ``cdr_finalization`` derives it from the per-provider attempt state machine in
    ``ingest-status.json``. Those are different questions, and they disagree — the
    live 2026-08-17 payload advertised 2 failed providers for a run whose contract
    had to report 0 for publication to be allowed at all. The contract is the
    audited, ledger-bound side and the side that gates publication, so it wins;
    row-derived totals (products, rates, failure records, brands) stay as they are,
    because those genuinely describe the export.
    """
    counts = coverage.get("counts")
    if not isinstance(counts, dict):
        return
    try:
        attempted = int(contract_coverage["providers_attempted"])
        partial = int(contract_coverage["providers_partial"])
        failed = int(contract_coverage["providers_failed"])
        registered = int(contract_coverage["providers_registered"])
    except (KeyError, TypeError, ValueError):
        return
    counts["providers_registered"] = registered
    counts["providers_attempted"] = attempted
    counts["providers_partial"] = partial
    counts["providers_failed"] = failed
    # "Succeeded" in the app's sense has always meant "yielded usable data", which
    # includes a partially-observed provider — so it is attempted minus failed,
    # not the contract's stricter providers_complete.
    counts["providers_succeeded"] = max(0, attempted - failed)
    counts["provider_counts_source"] = "export_contract_v2"
    # app_coverage_aliases only setdefaults these, and clean_export may already
    # have written the row-derived values at export time.
    coverage["providers_attempted"] = counts["providers_attempted"]
    coverage["providers_succeeded"] = counts["providers_succeeded"]


def _stable_payload_coverage(
    banks: Dict[str, Any],
    latest: Dict[str, Any],
    run_date: str,
    contract_coverage: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    existing = banks.get("coverage")
    if isinstance(existing, dict):
        coverage = deepcopy(existing)
    else:
        coverage = coverage_summary(banks, run_date)
        coverage["failure_provenance_complete"] = False
        counts_hint = latest.get("banks_counts") or {}
        try:
            coverage["counts"]["failure_records"] = int(counts_hint.get("failures") or 0)
        except (TypeError, ValueError):
            pass
    if contract_coverage:
        _apply_contract_provider_counts(coverage, contract_coverage)
    # Keep rebuild wall-clock metadata out of the content-hashed core. Coverage
    # is dated by its stable source observation (`observed_on`).
    coverage.pop("source_generated_at", None)
    coverage = app_coverage_aliases(coverage)
    validate_coverage(coverage)
    return coverage


def _canonical_coverage(
    observation: Mapping[str, Any], accounting: Mapping[str, Any]
) -> Dict[str, Any]:
    products = [row["document"] for row in observation["products"]]
    rates = [row["document"] for row in observation["rates"]]
    providers = accounting["summary"]["providers"]
    product_counts = accounting["summary"]["products"]
    issue_counts = accounting["summary"]["issues"]
    sections: Dict[str, Any] = {}
    for section in VALID_SECTIONS:
        section_rates = [row for row in rates if row.get("dataset") == section]
        sections[section] = {
            "rates": len(section_rates),
            "products": len({str(row.get("product_uid") or "") for row in section_rates} - {""}),
            "providers": len({str(row.get("provider_uid") or "") for row in section_rates} - {""}),
            "standard_rates": sum(row.get("account_class") == "standard" for row in section_rates),
            "non_standard_rates": sum(row.get("account_class") == "non_standard" for row in section_rates),
            "unclassified_rates": sum(
                row.get("account_class") not in {"standard", "non_standard"}
                for row in section_rates
            ),
        }
    names = {row["provider_uid"]: row["brand_name"] for row in accounting["providers"]}
    grouped: Dict[tuple[str, str, str], int] = {}
    for issue in accounting["issues"]:
        if issue["public_safe"] is not True:
            continue
        provider = names.get(issue["provider_uid"], "Observation")
        key = (provider, issue["phase"], issue["code"])
        grouped[key] = grouped.get(key, 0) + issue["occurrence_count"]
    failures = [
        {"provider": provider, "phase": phase, "status": status, "count": count}
        for (provider, phase, status), count in sorted(grouped.items())
    ]
    coverage = {
        "schema_version": 1,
        "observed_on": observation["observation_date"],
        "observed_at": observation["observed_at"],
        "source": "consumer_data_right_observation_v1",
        "counts": {
            "brands_observed": len({row["provider_uid"] for row in observation["products"]}),
            "products": len(products),
            "rates": len(rates),
            "issues": issue_counts["total"],
            "providers_registered": providers["registered"],
            "providers_attempted": providers["attempted"],
            "providers_succeeded": providers["attempted"] - providers["failed"],
            "providers_complete": providers["complete"],
            "providers_partial": providers["partial"],
            "providers_failed": providers["failed"],
            "products_discovered": product_counts["discovered"],
            "products_omitted": product_counts["omitted_valid"],
            "products_quarantined": product_counts["quarantined_invalid"],
        },
        "sections": sections,
        "provider_failures": failures,
        "failures": failures,
    }
    validate_coverage(coverage)
    return coverage


def _verify_contract_coverage(
    supplied: Mapping[str, Any], observation: Mapping[str, Any], accounting: Mapping[str, Any]
) -> None:
    providers = accounting["summary"]["providers"]
    products = accounting["summary"]["products"]
    expected = {
        "providers_registered": providers["registered"],
        "providers_attempted": providers["attempted"],
        "providers_complete": providers["complete"],
        "providers_partial": providers["partial"],
        "providers_failed": providers["failed"],
        "products_discovered": products["discovered"],
        "products_published": products["consumer_visible"],
        "products_omitted": products["omitted_valid"],
        "products_quarantined": products["quarantined_invalid"],
        "eligible_rate_rows": observation["row_counts"]["rates"],
    }
    mismatches = {
        key: (supplied.get(key), value)
        for key, value in expected.items()
        if key in supplied and supplied.get(key) != value
    }
    if mismatches:
        raise ValueError(f"export contract disagrees with canonical observation: {mismatches}")


def _compute_payload(
    exports_dir: Path,
    *,
    asset_dir: Path = BASE_DIR / "payload_assets",
    include_history: bool = True,
    state_dir: Optional[Path] = None,
    contract_coverage: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build tag-independent mobile data from one verified observation."""
    observation, accounting = load_verified_observation(exports_dir)
    run_date = observation["observation_date"]
    rates: List[Dict[str, Any]] = [row["document"] for row in observation["rates"]]
    products: List[Dict[str, Any]] = [row["document"] for row in observation["products"]]
    coverage = _canonical_coverage(observation, accounting)
    if contract_coverage:
        _verify_contract_coverage(contract_coverage, observation, accounting)

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

    shortcodes = load_brand_shortcodes(asset_dir)
    logos = load_brand_logos(asset_dir)
    # NB: no wall-clock field inside core/details. They are content-hashed (sha256
    # in the manifest) and the app skips re-download when the hash is unchanged, so
    # a same-day rebuild (e.g. the watchdog rerun) must yield identical bytes.
    del state_dir
    rba_calendar = rba_decisions.calendar_payload()
    rba_decision_models = [
        rba_decisions.Decision(
            date.fromisoformat(decision["date"]),
            date.fromisoformat(decision["effective"]) if decision.get("effective") else None,
            int(Decimal(str(decision["rate"])) * 100),
            int(decision["delta_bps"]),
        )
        for decision in rba_calendar["decisions"]
    ]

    rba_series = load_rba_series(asset_dir)
    series_by_date = {str(item.get("date") or ""): item for item in rba_series}
    rba_holds = set(load_rba_holds(asset_dir))
    for decision in rba_calendar["decisions"]:
        if decision["outcome"] == "hold":
            rba_holds.add(decision["date"])
        elif _decision_is_effective(decision, run_date):
            series_by_date[decision["effective"]] = {
                "date": decision["effective"],
                "rate": decision["rate"],
            }

    core = {
        "schema_version": SCHEMA_VERSION,
        "run_date": run_date,
        "sections": sections,
        "brands": build_brands(providers_seen, shortcodes, logos),
        "rba": sorted(series_by_date.values(), key=lambda item: item["date"]),
        "rba_holds": sorted(rba_holds),
        "coverage": coverage,
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
            rba_calendar=rba_decision_models,
        )
    counts = dict(observation["row_counts"])
    counts["providers"] = accounting["summary"]["providers"]["registered"]
    counts["issues"] = accounting["summary"]["issues"]["total"]
    return {
        "core": core,
        "details": details,
        "run_date": run_date,
        "observed_at": observation["observed_at"],
        "counts": counts,
        "search_index": search_index,
        "history_banks": history_banks,
        "bank_history": bank_history,
        "rba_calendar": rba_calendar,
    }


def _decision_is_effective(decision: Dict[str, Any], run_date: str) -> bool:
    """Whether a change belongs in the prevailing core series for this run."""
    effective = str(decision.get("effective") or "")[:10]
    as_of = str(run_date or "")[:10]
    return bool(effective and as_of and effective <= as_of)


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
        observed_at=data.get("observed_at"),
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
    observed_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Gzip core/details (+ optional search/history), write manifest into out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    release_base = f"https://github.com/{repo}/releases/download/{tag}"
    files: Dict[str, Any] = {
        "core": _asset(out_dir, "core", run_date, _gzip_bytes(core), release_base),
        "details": _asset(out_dir, "details", run_date, _gzip_bytes(details), release_base),
    }
    if is_rolling_tag(tag) and search_index and search_index.get("products"):
        files["search_index"] = _asset(
            out_dir, "search-index", run_date, _gzip_bytes(search_index), release_base
        )
    if is_rolling_tag(tag) and history_banks and history_banks.get("sections"):
        files["history_banks"] = _asset(
            out_dir, "history-banks", run_date, _gzip_bytes(history_banks), release_base
        )
    if is_rolling_tag(tag) and bank_history and bank_history.get("banks"):
        files["bank_history"] = _asset(
            out_dir, "bank-history", run_date, _gzip_bytes(bank_history), release_base
        )
    if is_rolling_tag(tag) and rba_calendar is not None:
        files["rba_calendar"] = _asset(
            out_dir, "rba-calendar", run_date, _gzip_bytes(rba_calendar), release_base
        )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_date": run_date,
        "generated_at": observed_at or f"{run_date}T00:00:00Z",
        "app_min_version": APP_MIN_VERSION,
        "repo": repo,
        "tag": tag,
        "counts": counts,
        "schedule": _ingest_schedule(),
        "files": files,
    }
    manifest_text = json.dumps(manifest, indent=2, ensure_ascii=False)
    from app_payload_network_budget import validate_payload_network_budget

    transfer_report = validate_payload_network_budget(
        manifest,
        manifest_bytes=len(manifest_text.encode("utf-8")),
        asset_root=out_dir,
    )
    print(
        "[app_payload] transfer budget "
        f"critical_core={transfer_report['journeys']['critical_core']} "
        f"current_standard_home={transfer_report['journeys']['current_standard_home']}"
    )
    (out_dir / "manifest.json").write_text(manifest_text, encoding="utf-8")
    return manifest


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
    state_dir: Optional[Path] = None,
    contract_coverage: Optional[Mapping[str, Any]] = None,
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
    observation, _accounting = load_verified_observation(exports_dir)
    run_date = observation["observation_date"]

    need_latest = False
    live_run_date = ""
    if update_latest:
        status, live = _app_payload("_live_manifest_status")(repo, DEFAULT_TAG)
        live_run_date = str((live or {}).get("run_date") or "") if status == "present" else ""
        need_latest = not (live_run_date and live_run_date > run_date)

    # Compute the (tag-independent) payload data ONCE, then package both releases.
    # History/search are rolling-only, so only compute them when the rolling latest
    # will be built. Previously each release rebuilt from scratch every run.
    data = _app_payload("_compute_payload")(
        exports_dir,
        include_history=need_latest,
        state_dir=state_dir,
        contract_coverage=contract_coverage,
    )

    dated = dated_tag(run_date)
    out_dated = out_dir or (
        state_dir / "v1-dated" if state_dir is not None else exports_dir / "app-payload"
    )
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
            out_latest = (
                state_dir / "v1-latest"
                if state_dir is not None
                else exports_dir / "app-payload-latest"
            )
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
