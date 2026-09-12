"""Independent, additive mobile insight sidecars published beside payload v1.

``manifest.json`` remains the compatibility contract. This module writes
content-addressed assets and replaces ``manifest-v2.json`` only after payload v1
is live, so an insight build can fail without delaying rates publication.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import sqlite3
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import urlsplit

import app_payload_mobile
from app_payload_history_projection import POLICY as HISTORY_PROJECTION_POLICY, project_standard_history_rows
from app_payload_common import (
    BASE_DIR,
    DEFAULT_REPO,
    DEFAULT_TAG,
    SUBPROCESS_TIMEOUT_SEC,
    SUBPROCESS_UPLOAD_TIMEOUT_SEC,
    VALID_SECTIONS,
    _load_json,
    section_filter,
    utc_now_iso,
)
from app_payload_contracts import (
    MAX_V2_ASSET_BYTES,
    MAX_V2_ASSET_UNCOMPRESSED_BYTES,
    MAX_V2_MANIFEST_BYTES,
    STANDARD_COHORT,
    validate_economic_outlook,
    validate_product_history,
    validate_v2_manifest,
)
from app_payload_publish import _gh_authed, _gh_available, _live_manifest_status
from app_payload_network_budget import validate_v2_network_budget
from cdr_public_api_shims import connect_readonly
from cdr_macro_store import read_store
from cdr_macro_sources import LOCAL_SERIES_IDS, SERIES_VISIBLE_FROM
from cdr_macro_freshness import assess_freshness, observation_value, series_metadata, source_definition_current
from pi_payload_freshness import fresh_document_url
from app_payload_v2_archive import archive_v2, is_archive_tag, preserve_current_v2, read_manifest
from app_payload_revisions_github import GitHubRevisionStore, write_once
from app_payload_revisions_state import RevisionError, digest

V2_SCHEMA_VERSION = 2
V2_MANIFEST_FILENAME = "manifest-v2.json"
V2_PRODUCT_HISTORY_PREFIX = "v2-product-history-"
V2_ECONOMIC_OUTLOOK_PREFIX = "v2-economic-outlook-"
V2_RETAIN_GENERATIONS = 8
_MOVE_EPSILON = 1e-12


def _finite_positive(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number / 100 if number > 1 else number


def _product_identity(row: Mapping[str, Any], product_key: str) -> str:
    product_id = str(row.get("product_id") or "").strip()
    if not product_id:
        return f"key:{product_key}"
    return "\x1f".join(
        (
            str(row.get("provider") or "").strip(),
            product_id,
            str(row.get("category") or "").strip(),
            str(row.get("dataset") or "").strip(),
        )
    )


def _standard_best_for_day(
    rates: Iterable[Mapping[str, Any]],
) -> Tuple[Dict[str, float], Dict[str, set[str]], Dict[str, str], Dict[str, int]]:
    best: Dict[str, float] = {}
    aliases: Dict[str, set[str]] = {}
    sections: Dict[str, str] = {}
    excluded = {"non_standard": 0, "unclassified": 0, "unkeyed": 0}
    for section in VALID_SECTIONS:
        lower_is_best = section == "Mortgage"
        for row in rates:
            if row.get("dataset") != section or not section_filter(section, dict(row)):
                continue
            account_class = str(row.get("account_class") or "")
            if account_class != "standard":
                excluded["non_standard" if account_class == "non_standard" else "unclassified"] += 1
                continue
            key = str(row.get("product_key") or "")
            if not key:
                excluded["unkeyed"] += 1
                continue
            identity = _product_identity(row, key)
            aliases.setdefault(identity, set()).add(key)
            sections.setdefault(identity, section)
            value = _finite_positive(row.get("rate"))
            current = best.get(identity)
            if value is not None and (
                current is None or (value < current if lower_is_best else value > current)
            ):
                best[identity] = value
    return best, aliases, sections, excluded


def _moves(series: List[Optional[float]], dates: List[str]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    previous: Optional[float] = None
    for index, value in enumerate(series):
        if value is None:
            # A gap breaks observed continuity. Never date a movement on
            # reappearance when the actual change could have happened earlier.
            previous = None
            continue
        if previous is not None and abs(value - previous) > _MOVE_EPSILON:
            events.append(
                {
                    "date": dates[index],
                    "from_rate": previous,
                    "to_rate": value,
                    "bps": round((value - previous) * 10000, 1),
                }
            )
        previous = value
    return events


def _aggregate(values: Iterable[float]) -> Optional[Dict[str, Any]]:
    ordered = sorted(values)
    if not ordered:
        return None
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    return {
        "min": ordered[0],
        "max": ordered[-1],
        "median": median,
        "mean": sum(ordered) / len(ordered),
        "count": len(ordered),
    }


def build_product_history(exports_dir: Path, *, run_date: str) -> Dict[str, Any]:
    """Build standard-only per-product best-rate history; never interpolate gaps."""
    dates = app_payload_mobile._history_dates(exports_dir, run_date)
    identities: Dict[str, List[Optional[float]]] = {}
    aliases_by_identity: Dict[str, set[str]] = {}
    alias_dates: Dict[str, set[str]] = {}
    section_by_identity: Dict[str, str] = {}
    excluded = {"non_standard": 0, "unclassified": 0, "unkeyed": 0}
    projection_changes, projection_unknown, restricted_products = [], {}, set()
    daily_aggregates: Dict[str, List[Dict[str, Any]]] = {section: [] for section in VALID_SECTIONS}
    for index, date in enumerate(dates):
        path = app_payload_mobile._banks(exports_dir, date)
        banks = _load_json(path) if path is not None else {}
        rates, projection = project_standard_history_rows(banks, date)
        projection_changes.extend(projection["changes"])
        restricted_products.update(projection["restricted_products"])
        for identity, issue in projection["unknown"].items():
            projection_unknown.setdefault(identity, []).append((index, issue))
        best, aliases, sections, day_excluded = _standard_best_for_day(rates)
        for key, count in day_excluded.items():
            excluded[key] += count
        for identity, keys in aliases.items():
            aliases_by_identity.setdefault(identity, set()).update(keys)
            for key in keys:
                alias_dates.setdefault(key, set()).add(date)
        section_by_identity.update(sections)
        for series in identities.values():
            series.append(None)
        for identity in aliases:
            identities.setdefault(identity, [None] * (index + 1))
        for identity, value in best.items():
            identities[identity][index] = value

    # If a product has an evidenced winner tier, a different day's missing or
    # ambiguous source cannot prove its ordinary best rate. Leave a gap rather
    # than invent a zero, carry today's tier backwards, or emit a false move.
    for identity in restricted_products:
        for index, issue in projection_unknown.get(identity, []):
            if identity in identities:
                identities[identity][index] = None
            projection_changes.append({**issue, "action": "hold_unresolved_product_day"})
    for index, date in enumerate(dates):
        for section in VALID_SECTIONS:
            point = _aggregate(series[index] for identity, series in identities.items()
                               if section_by_identity.get(identity) == section and series[index] is not None)
            if point:
                daily_aggregates[section].append({"date": date, **point})

    products: Dict[str, List[Optional[float]]] = {}
    product_meta: Dict[str, Dict[str, str]] = {}
    for identity in sorted(identities):
        for key in sorted(aliases_by_identity.get(identity) or (identity,)):
            observed = alias_dates.get(key, set())
            products[key] = [
                value if date in observed else None
                for date, value in zip(dates, identities[identity])
            ]
            product_meta[key] = {"section": section_by_identity.get(identity, "")}
    moves = {key: events for key, series in products.items() if (events := _moves(series, dates))}
    payload = {
        "schema_version": V2_SCHEMA_VERSION,
        "run_date": run_date,
        "run_dates": dates,
        "cohort": dict(STANDARD_COHORT),
        "aggregation": "best_advertised_rate_per_product_section",
        "products": products,
        "product_meta": product_meta,
        "moves": moves,
        "section_aggregates": {
            section: {"cohort": dict(STANDARD_COHORT), "points": points}
            for section, points in daily_aggregates.items()
            if points
        },
        "classification_projection": {"schema_version": 1, "policy": HISTORY_PROJECTION_POLICY,
                                      "reclassified_rate_rows": sum(row["action"] == "exclude_winner_rate" for row in projection_changes),
                                      "held_product_days": sum(row["action"] == "hold_unresolved_product_day" for row in projection_changes),
                                      "records": sorted(projection_changes, key=lambda row: (row["date"], row["product_key"], row["action"]))},
        "coverage": {
            "date_count": len(dates),
            "product_count": len(products),
            "identity_count": len(identities),
            "observation_count": sum(v is not None for series in products.values() for v in series),
            "move_count": sum(len(events) for events in moves.values()),
            "excluded_rate_rows": excluded,
            "first_date": dates[0] if dates else None,
            "last_date": dates[-1] if dates else None,
        },
    }
    validate_product_history(payload)
    return payload


def _catalog_index(catalog_path: Path) -> Dict[str, Dict[str, Any]]:
    catalog = _load_json(catalog_path)
    return {
        str(series["id"]): series
        for category in catalog.get("categories", [])
        for series in category.get("series", [])
        if isinstance(series, dict) and series.get("id")
    }


def _public_https_url(value: Any) -> Optional[str]:
    raw = str(value or "").strip()
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    return raw.split("#", 1)[0]


def _latest_observations(con: sqlite3.Connection) -> Dict[str, List[Dict[str, Any]]]:
    rows = con.execute(
        """SELECT series_id, observation_date, raw_value, release_date
           FROM series_observations WHERE raw_value IS NOT NULL
           ORDER BY series_id, observation_date DESC"""
    ).fetchall()
    out: Dict[str, List[Dict[str, Any]]] = {}
    for series_id, observed_on, value, released_on in rows:
        value = observation_value(series_id, value)
        if value is None or observed_on < SERIES_VISIBLE_FROM.get(series_id, ""):
            continue
        bucket = out.setdefault(str(series_id), [])
        if len(bucket) < 2:
            bucket.append(
                {"observed_on": observed_on, "value": value, "released_on": released_on}
            )
    return out


def _freshness(con: sqlite3.Connection) -> Dict[str, Dict[str, Any]]:
    rows = con.execute(
        """SELECT series_id, last_checked_at, last_success_at,
                  last_observation_date, status, source_url FROM ingest_runs"""
    ).fetchall()
    return {
        str(row[0]): {
            "last_checked_at": row[1],
            "last_success_at": row[2],
            "last_observation_date": row[3],
            "status": row[4],
            "source_url": _public_https_url(row[5]),
        }
        for row in rows
    }


def build_economic_outlook(store_path: Path, *, generated_at: str) -> Dict[str, Any]:
    """Snapshot observed local indicators; no forecast or calibrated confidence claim."""
    payload: Dict[str, Any] = {
        "schema_version": 1,
        "kind": "observed_economic_indicators",
        "generated_at": generated_at,
        "signal_label": "signal_balance",
        "series": [],
    }
    observations, freshness = {}, {}
    try:
        with read_store(store_path) as con:
            observations = _latest_observations(con)
            freshness = _freshness(con)
    except sqlite3.Error:
        pass
    catalog = _catalog_index(BASE_DIR / "dashboard" / "economic-data-catalog.json")
    for series_id in sorted(LOCAL_SERIES_IDS | observations.keys()):
        meta = series_metadata(series_id, catalog.get(series_id, {}))
        stored = freshness.get(series_id)
        series_observations = observations.get(series_id, []) if source_definition_current(series_id, stored) else []
        payload["series"].append(
            {
                "id": series_id,
                "label": meta.get("label", series_id),
                "unit": meta.get("unit"),
                "frequency": meta.get("frequency"),
                "source_label": meta.get("source_label"),
                "source_url": _public_https_url(
                    (freshness.get(series_id) or {}).get("source_url") or meta.get("source_url")
                ),
                "freshness": assess_freshness(series_id, stored, frequency=meta.get("frequency"), now=generated_at),
                "observations": list(reversed(series_observations)),
            }
        )
    validate_economic_outlook(payload)
    return payload


def _write_asset(
    out_dir: Path,
    kind: str,
    prefix: str,
    run_date: str,
    payload: Mapping[str, Any],
    base: str,
) -> Dict[str, Any]:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_V2_ASSET_UNCOMPRESSED_BYTES[kind]:
        raise ValueError(f"{kind} exceeds the uncompressed size limit")
    data = gzip.compress(raw, compresslevel=9, mtime=0)
    if len(data) > MAX_V2_ASSET_BYTES[kind]:
        raise ValueError(f"{kind} exceeds the compressed size limit")
    sha = hashlib.sha256(data).hexdigest()
    name = f"{prefix}{run_date}-{sha[:12]}.json.gz"
    (out_dir / name).write_bytes(data)
    return {
        "name": name,
        "sha256": sha,
        "bytes": len(data),
        "uncompressed_bytes": len(raw),
        "encoding": "gzip",
        "url": f"{base}/{name}",
    }


def build_v2_sidecar(
    exports_dir: Path,
    out_dir: Path,
    *,
    v1_manifest: Mapping[str, Any],
    economic_store_path: Optional[Path] = None,
    repo: str = DEFAULT_REPO,
    tag: str = DEFAULT_TAG,
) -> Dict[str, Any]:
    if tag not in (DEFAULT_TAG, "app-payload-latest"):
        raise ValueError("v2 sidecars are rolling-only")
    run_date = str(v1_manifest.get("run_date") or "")
    v1_files = v1_manifest.get("files") or {}
    core_sha = str((v1_files.get("core") or {}).get("sha256") or "")
    details_sha = str((v1_files.get("details") or {}).get("sha256") or "")
    if not run_date or not core_sha or not details_sha:
        raise ValueError("v1 manifest must provide run_date plus core/details sha256")
    generated_at = utc_now_iso()
    release_base = f"https://github.com/{repo}/releases/download/{tag}"
    out_dir.mkdir(parents=True, exist_ok=True)
    history = build_product_history(exports_dir, run_date=run_date)
    history["core_sha"] = core_sha
    files = {
        "product_history": _write_asset(
            out_dir,
            "product_history",
            V2_PRODUCT_HISTORY_PREFIX,
            run_date,
            history,
            release_base,
        )
    }
    if economic_store_path is not None:
        economic = build_economic_outlook(economic_store_path, generated_at=generated_at)
        if economic["series"]:
            files["economic_outlook"] = _write_asset(
                out_dir,
                "economic_outlook",
                V2_ECONOMIC_OUTLOOK_PREFIX,
                run_date,
                economic,
                release_base,
            )
    manifest = {
        "schema_version": V2_SCHEMA_VERSION,
        "run_date": run_date,
        "generated_at": generated_at,
        "base": {"manifest_schema": 1, "core_sha": core_sha, "details_sha": details_sha},
        "capabilities": sorted(files),
        "files": files,
    }
    validate_v2_manifest(manifest)
    manifest_text = json.dumps(manifest, indent=2, ensure_ascii=False)
    if len(manifest_text.encode("utf-8")) > MAX_V2_MANIFEST_BYTES:
        raise ValueError("manifest-v2 exceeds the size limit")
    transfer_report = validate_v2_network_budget(
        manifest,
        manifest_bytes=len(manifest_text.encode("utf-8")),
        asset_root=out_dir,
    )
    print(f"[app_payload_v2] transfer budget {transfer_report}")
    (out_dir / V2_MANIFEST_FILENAME).write_text(manifest_text, encoding="utf-8")
    return manifest


def _validate_local_assets(payload_dir: Path, manifest: Mapping[str, Any]) -> None:
    for kind, entry in manifest["files"].items():
        name = str(entry["name"])
        if Path(name).name != name:
            raise ValueError(f"manifest-v2 {kind} has an unsafe asset name")
        path = payload_dir / name
        if not path.is_file() or path.stat().st_size != int(entry["bytes"]):
            raise ValueError(f"manifest-v2 {kind} asset size does not match")
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"manifest-v2 {kind} asset hash does not match")
        total = 0
        with gzip.open(path, "rb") as stream:
            while chunk := stream.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_V2_ASSET_UNCOMPRESSED_BYTES[kind]:
                    raise ValueError(f"manifest-v2 {kind} expands beyond the size limit")
        if total != int(entry["uncompressed_bytes"]):
            raise ValueError(f"manifest-v2 {kind} uncompressed size does not match")


def _live_v2_manifest_status(repo: str, tag: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    url = fresh_document_url(f"https://github.com/{repo}/releases/download/{tag}/{V2_MANIFEST_FILENAME}")
    try:
        with urllib.request.urlopen(url, timeout=SUBPROCESS_TIMEOUT_SEC) as response:  # nosec B310
            return "present", json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return ("missing", None) if exc.code == 404 else ("error", None)
    except Exception:
        return "error", None


def _prune_v2_assets(gh: str, repo: str, tag: str, keep_names: set[str]) -> int:
    if is_archive_tag(tag):
        return 0
    listed = subprocess.run(  # nosec B603
        [
            gh, "release", "view", tag, "--repo", repo, "--json", "assets", "-q",
            '.assets[] | "\\(.name)\\t\\(.createdAt)"',
        ],
        capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SEC, check=False,
    )
    if listed.returncode != 0:
        return 0
    deleted = 0
    for prefix in (V2_PRODUCT_HISTORY_PREFIX, V2_ECONOMIC_OUTLOOK_PREFIX):
        assets = [
            tuple(line.partition("\t")[::2])
            for line in listed.stdout.splitlines()
            if line.startswith(prefix)
        ]
        assets.sort(key=lambda item: item[1], reverse=True)
        for index, (name, _created) in enumerate(assets):
            if name in keep_names or index < V2_RETAIN_GENERATIONS:
                continue
            result = subprocess.run(  # nosec B603
                [gh, "release", "delete-asset", tag, name, "--repo", repo, "-y"],
                capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SEC, check=False,
            )
            deleted += result.returncode == 0
    return deleted


def _replace_v2_manifest(
    gh: str,
    repo: str,
    tag: str,
    manifest_path: Path,
    predecessor: bytes | None,
    store,
) -> None:
    incoming = manifest_path.read_bytes()
    if store.read(tag, V2_MANIFEST_FILENAME, MAX_V2_MANIFEST_BYTES) != predecessor:
        raise RevisionError("v2 selector predecessor changed before promotion")
    backup = None
    if predecessor is not None:
        backup = manifest_path.parent / "v2-preservation" / "predecessors" / digest(predecessor) / V2_MANIFEST_FILENAME
        write_once(backup, predecessor)
    try:
        subprocess.run(  # nosec B603
            [gh, "release", "upload", tag, str(manifest_path), "--repo", repo, "--clobber"],
            check=True, timeout=SUBPROCESS_UPLOAD_TIMEOUT_SEC,
        )
    except subprocess.SubprocessError:
        current = store.read(tag, V2_MANIFEST_FILENAME, MAX_V2_MANIFEST_BYTES)
        if current == incoming:
            return  # An uncertain upload succeeded, proved by exact public bytes.
        if backup is not None and current is None:
            # Never replace an independently appearing selector during recovery.
            # Both bundles are already immutable; retain the failed attempt.
            try:
                subprocess.run(  # nosec B603
                    [gh, "release", "upload", tag, str(backup), "--repo", repo],
                    check=True, timeout=SUBPROCESS_UPLOAD_TIMEOUT_SEC,
                )
            except subprocess.SubprocessError:
                pass
        raise
    if store.read(tag, V2_MANIFEST_FILENAME, MAX_V2_MANIFEST_BYTES) != incoming:
        raise RevisionError("v2 selector failed exact public readback")


def publish_v2_sidecar(
    payload_dir: Path,
    *,
    repo: str = DEFAULT_REPO,
    tag: str = DEFAULT_TAG,
    require_token: bool = False,
) -> bool:
    if is_archive_tag(tag):
        raise RevisionError("immutable v2 archives cannot be published as mutable selectors")
    manifest_path = payload_dir / V2_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise FileNotFoundError(f"no {V2_MANIFEST_FILENAME} in {payload_dir}")
    if manifest_path.stat().st_size > MAX_V2_MANIFEST_BYTES:
        raise ValueError("manifest-v2 exceeds the size limit")
    incoming_raw = manifest_path.read_bytes()
    manifest = read_manifest(incoming_raw)
    _validate_local_assets(payload_dir, manifest)
    names = [str(entry["name"]) for entry in manifest["files"].values()]
    data_assets = [payload_dir / name for name in names]
    missing = [str(path) for path in [*data_assets, manifest_path] if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing v2 payload assets: {missing}")
    gh = _gh_available()
    if not gh or not _gh_authed(gh):
        if require_token:
            raise RuntimeError("gh CLI / GitHub auth required for v2 sidecar publish")
        print("[app_payload_v2] publish skipped reason=no_gh_auth exit=0")
        return False
    store = GitHubRevisionStore(repo, gh=gh)
    predecessor = preserve_current_v2(payload_dir / "v2-preservation", repo=repo, tag=tag, store=store)
    v1_status, live_v1 = _live_manifest_status(repo, tag)
    live_files = (live_v1 or {}).get("files") or {}
    expected_base = manifest["base"]
    base_matches = v1_status == "present" and all(
        str((live_files.get(kind) or {}).get("sha256") or "")
        == str(expected_base.get(f"{kind}_sha") or "")
        for kind in ("core", "details")
    )
    if not base_matches:
        print(
            "[app_payload_v2] publish skipped "
            f"reason=v1_base_mismatch live_status={v1_status} exit=0"
        )
        return False
    release = subprocess.run(  # nosec B603
        [gh, "release", "view", tag, "--repo", repo], capture_output=True, text=True,
        timeout=SUBPROCESS_TIMEOUT_SEC, check=False,
    )
    if release.returncode != 0:
        raise RuntimeError("v1 rolling release is absent; refusing to create it from v2")
    listed = subprocess.run(  # nosec B603
        [gh, "release", "view", tag, "--repo", repo, "--json", "assets", "-q", ".assets[].name"],
        capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SEC, check=False,
    )
    existing = set(listed.stdout.split()) if listed.returncode == 0 else set()
    uploads = [path for path in data_assets if path.name not in existing]
    if uploads:
        subprocess.run(  # nosec B603
            [gh, "release", "upload", tag, *map(str, uploads), "--repo", repo],
            check=True, timeout=SUBPROCESS_UPLOAD_TIMEOUT_SEC,
        )
    live = json.loads(predecessor) if predecessor is not None else None
    live_date = str((live or {}).get("run_date") or "")
    our_date = str(manifest.get("run_date") or "")
    live_gen = str((live or {}).get("generated_at") or "")
    our_gen = str(manifest.get("generated_at") or "")
    if live_date and (live_date > our_date or (live_date == our_date and live_gen > our_gen)):
        print(
            f"[app_payload_v2] publish skipped run_date={our_date} "
            f"reason=live_newer live_run_date={live_date}"
        )
        return False
    incoming_tag = archive_v2(incoming_raw, payload_dir / "v2-preservation", store=store,
                              source_tag=tag, payload_dir=payload_dir)
    # A content-addressed name is not evidence by itself: verify every published
    # insight before allowing its mutable selector to point at it.
    for entry in manifest["files"].values():
        public = store.read(tag, entry["name"], entry["bytes"])
        if public is None or len(public) != entry["bytes"] or digest(public) != entry["sha256"]:
            raise RevisionError("v2 public insight failed hash/size readback")
    preserved_manifest = payload_dir / "v2-preservation" / incoming_tag / V2_MANIFEST_FILENAME
    _replace_v2_manifest(gh, repo, tag, preserved_manifest, predecessor, store)
    try:
        _prune_v2_assets(gh, repo, tag, set(names))
    except Exception as exc:  # noqa: BLE001
        print(f"[app_payload_v2] asset prune skipped (non-fatal): {exc}")
    print(f"[app_payload_v2] publish succeeded run_date={our_date} new_data_assets={len(uploads)} exit=0")
    return True


def build_and_publish_v2(
    exports_dir: Path,
    *,
    v1_manifest: Mapping[str, Any],
    out_dir: Path,
    economic_store_path: Optional[Path] = None,
    repo: str = DEFAULT_REPO,
    tag: str = DEFAULT_TAG,
) -> Tuple[Dict[str, Any], bool]:
    manifest = build_v2_sidecar(
        exports_dir,
        out_dir,
        v1_manifest=v1_manifest,
        economic_store_path=economic_store_path,
        repo=repo,
        tag=tag,
    )
    return manifest, publish_v2_sidecar(out_dir, repo=repo, tag=tag)
