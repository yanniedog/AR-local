"""Independent rolling v2 acceleration sidecar for the mobile app.

The existing ``manifest.json`` v1 contract is intentionally not involved here.
This module reads finalized exports, writes staging artifacts outside the ledger,
and publishes ``manifest-v2.json`` only after the caller has completed v1.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import app_payload_mobile
from app_payload_common import (
    DEFAULT_REPO,
    DEFAULT_TAG,
    SUBPROCESS_TIMEOUT_SEC,
    SUBPROCESS_UPLOAD_TIMEOUT_SEC,
    VALID_SECTIONS,
    _load_json,
    section_filter,
    utc_now_iso,
)
from app_payload_publish import _gh_authed, _gh_available

V2_SCHEMA_VERSION = 2
V2_MANIFEST_FILENAME = "manifest-v2.json"
V2_PRODUCT_HISTORY_PREFIX = "v2-product-history-"
V2_RETAIN_GENERATIONS = 8
_MOVE_EPSILON = 1e-12


def _finite_positive(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    # Exact AR-app `toFraction` compatibility for legacy cores that contain
    # percent-form rates such as 5.5 instead of 0.055.
    return number / 100 if number > 1 else number


def _product_identity(row: Dict[str, Any], product_key: str) -> str:
    """Stable identity that survives a bank renaming a product."""
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


def _best_rates_for_day(
    rates: List[Dict[str, Any]],
) -> Tuple[Dict[str, float], Dict[str, set[str]], int]:
    """Match AR-app's section-aware selection, grouped by stable product identity."""
    best: Dict[str, float] = {}
    aliases: Dict[str, set[str]] = {}
    unkeyed = 0
    for section in VALID_SECTIONS:
        lower_is_best = section == "Mortgage"
        for row in rates:
            if row.get("dataset") != section or not section_filter(section, row):
                continue
            key = str(row.get("product_key") or "")
            if not key:
                unkeyed += 1
                continue
            identity = _product_identity(row, key)
            aliases.setdefault(identity, set()).add(key)
            value = _finite_positive(row.get("rate"))
            if value is None:
                continue
            current = best.get(identity)
            if current is None or (value < current if lower_is_best else value > current):
                best[identity] = value
    return best, aliases, unkeyed


def _moves(series: List[Optional[float]], dates: List[str]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    previous: Optional[float] = None
    for index, value in enumerate(series):
        if value is None:
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


def build_product_history(exports_dir: Path, *, run_date: str) -> Dict[str, Any]:
    """Build complete graph-ready history over every retained discovered snapshot.

    The product set is the union across the full date axis. Missing observations stay
    ``null`` and no values are interpolated or fabricated.
    """
    dates = app_payload_mobile._history_dates(exports_dir, run_date)
    identities: Dict[str, List[Optional[float]]] = {}
    aliases_by_identity: Dict[str, set[str]] = {}
    unkeyed_rows = 0

    for index, date in enumerate(dates):
        path = app_payload_mobile._banks(exports_dir, date)
        rates: List[Dict[str, Any]] = []
        if path is not None:
            raw = _load_json(path).get("rates") or []
            rates = [row for row in raw if isinstance(row, dict)]
        best, aliases, unkeyed = _best_rates_for_day(rates)
        unkeyed_rows += unkeyed

        for identity, keys in aliases.items():
            aliases_by_identity.setdefault(identity, set()).update(keys)
        for series in identities.values():
            series.append(None)
        for identity in aliases:
            identities.setdefault(identity, [None] * (index + 1))
        for identity, value in best.items():
            identities[identity][index] = value

    ordered_products: Dict[str, List[Optional[float]]] = {}
    for identity in sorted(identities):
        for key in sorted(aliases_by_identity.get(identity) or (identity,)):
            # Every historical/current alias resolves the complete stable series.
            ordered_products[key] = list(identities[identity])
    moves = {
        key: events
        for key, series in ordered_products.items()
        if (events := _moves(series, dates))
    }
    observation_count = sum(
        value is not None
        for series in ordered_products.values()
        for value in series
    )
    return {
        "schema_version": V2_SCHEMA_VERSION,
        "run_date": run_date,
        "run_dates": dates,
        "products": ordered_products,
        "moves": moves,
        "coverage": {
            "date_count": len(dates),
            "product_count": len(ordered_products),
            "identity_count": len(identities),
            "observation_count": observation_count,
            "move_count": sum(len(events) for events in moves.values()),
            "unkeyed_rate_rows": unkeyed_rows,
            "first_date": dates[0] if dates else None,
            "last_date": dates[-1] if dates else None,
        },
    }


def _gzip_bytes(payload: Dict[str, Any]) -> bytes:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return gzip.compress(raw, compresslevel=9, mtime=0)


def build_v2_sidecar(
    exports_dir: Path,
    out_dir: Path,
    *,
    v1_manifest: Dict[str, Any],
    repo: str = DEFAULT_REPO,
    tag: str = DEFAULT_TAG,
) -> Dict[str, Any]:
    """Build one independent product-history sidecar bound to an exact v1 revision."""
    if tag != DEFAULT_TAG and tag != "app-payload-latest":
        raise ValueError("v2 sidecars are rolling-only")
    run_date = str(v1_manifest.get("run_date") or "")
    files = v1_manifest.get("files") or {}
    core_sha = str((files.get("core") or {}).get("sha256") or "")
    details_sha = str((files.get("details") or {}).get("sha256") or "")
    if not run_date or not core_sha or not details_sha:
        raise ValueError("v1 manifest must provide run_date plus core/details sha256")

    product_history = build_product_history(exports_dir, run_date=run_date)
    product_history["core_sha"] = core_sha
    gz = _gzip_bytes(product_history)
    sha = hashlib.sha256(gz).hexdigest()
    name = f"{V2_PRODUCT_HISTORY_PREFIX}{run_date}-{sha[:12]}.json.gz"
    release_base = f"https://github.com/{repo}/releases/download/{tag}"

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / name).write_bytes(gz)
    manifest = {
        "schema_version": V2_SCHEMA_VERSION,
        "run_date": run_date,
        "generated_at": utc_now_iso(),
        "base": {
            "manifest_schema": 1,
            "core_sha": core_sha,
            "details_sha": details_sha,
        },
        "files": {
            "product_history": {
                "name": name,
                "sha256": sha,
                "bytes": len(gz),
                "encoding": "gzip",
                "url": f"{release_base}/{name}",
            }
        },
    }
    (out_dir / V2_MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


def _live_v2_manifest_status(
    repo: str, tag: str
) -> Tuple[str, Optional[Dict[str, Any]]]:
    url = f"https://github.com/{repo}/releases/download/{tag}/{V2_MANIFEST_FILENAME}"
    try:
        with urllib.request.urlopen(url, timeout=SUBPROCESS_TIMEOUT_SEC) as response:  # nosec B310
            return "present", json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return ("missing", None) if exc.code == 404 else ("error", None)
    except Exception:
        return "error", None


def _prune_v2_assets(
    gh: str, repo: str, tag: str, keep_names: set[str]
) -> int:
    """Prune only the v2 namespace; v1 assets are never candidates."""
    listed = subprocess.run(  # nosec B603
        [
            gh,
            "release",
            "view",
            tag,
            "--repo",
            repo,
            "--json",
            "assets",
            "-q",
            '.assets[] | "\\(.name)\\t\\(.createdAt)"',
        ],
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_SEC,
        check=False,
    )
    if listed.returncode != 0:
        return 0
    assets: List[Tuple[str, str]] = []
    for line in listed.stdout.splitlines():
        name, _, created = line.partition("\t")
        if name.startswith(V2_PRODUCT_HISTORY_PREFIX) and name.endswith(".json.gz"):
            assets.append((name, created))
    assets.sort(key=lambda item: item[1], reverse=True)
    deleted = 0
    for index, (name, _created) in enumerate(assets):
        if name in keep_names or index < V2_RETAIN_GENERATIONS:
            continue
        result = subprocess.run(  # nosec B603
            [gh, "release", "delete-asset", tag, name, "--repo", repo, "-y"],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_SEC,
            check=False,
        )
        if result.returncode == 0:
            deleted += 1
    return deleted


def publish_v2_sidecar(
    payload_dir: Path,
    *,
    repo: str = DEFAULT_REPO,
    tag: str = DEFAULT_TAG,
    require_token: bool = False,
) -> bool:
    """Publish v2 data first and ``manifest-v2.json`` last on the existing release."""
    manifest_path = payload_dir / V2_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise FileNotFoundError(f"no {V2_MANIFEST_FILENAME} in {payload_dir}")
    manifest = _load_json(manifest_path)
    names = [str(entry.get("name") or "") for entry in manifest["files"].values()]
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

    release = subprocess.run(  # nosec B603
        [gh, "release", "view", tag, "--repo", repo],
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_SEC,
        check=False,
    )
    if release.returncode != 0:
        raise RuntimeError("v1 rolling release is absent; refusing to create it from v2")

    listed = subprocess.run(  # nosec B603
        [gh, "release", "view", tag, "--repo", repo, "--json", "assets", "-q", ".assets[].name"],
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_SEC,
        check=False,
    )
    existing = set(listed.stdout.split()) if listed.returncode == 0 else set()
    uploads = [path for path in data_assets if path.name not in existing]
    if uploads:
        subprocess.run(  # nosec B603
            [gh, "release", "upload", tag, *map(str, uploads), "--repo", repo],
            check=True,
            timeout=SUBPROCESS_UPLOAD_TIMEOUT_SEC,
        )

    status, live = _live_v2_manifest_status(repo, tag)
    if status == "error":
        print("[app_payload_v2] publish skipped reason=live_manifest_verify_error exit=0")
        return False
    live_date = str((live or {}).get("run_date") or "")
    our_date = str(manifest.get("run_date") or "")
    if live_date and live_date > our_date:
        print(
            f"[app_payload_v2] publish skipped run_date={our_date} "
            f"reason=live_newer live_run_date={live_date}"
        )
        return False

    backup_dir = payload_dir / ".prev-manifest-v2"
    backup_dir.mkdir(exist_ok=True)
    backup = backup_dir / V2_MANIFEST_FILENAME
    if backup.exists():
        backup.unlink()
    if live is not None:
        backup.write_text(json.dumps(live), encoding="utf-8")
    try:
        subprocess.run(  # nosec B603
            [
                gh,
                "release",
                "upload",
                tag,
                str(manifest_path),
                "--repo",
                repo,
                "--clobber",
            ],
            check=True,
            timeout=SUBPROCESS_UPLOAD_TIMEOUT_SEC,
        )
    except subprocess.SubprocessError:
        if backup.is_file():
            recheck, current = _live_v2_manifest_status(repo, tag)
            current_date = str((current or {}).get("run_date") or "")
            if recheck == "missing" or (recheck == "present" and current_date <= live_date):
                subprocess.run(  # nosec B603
                    [
                        gh,
                        "release",
                        "upload",
                        tag,
                        str(backup),
                        "--repo",
                        repo,
                        "--clobber",
                    ],
                    check=True,
                    timeout=SUBPROCESS_UPLOAD_TIMEOUT_SEC,
                )
        raise

    try:
        _prune_v2_assets(gh, repo, tag, set(names))
    except Exception as exc:  # noqa: BLE001 - pruning must not invalidate publication
        print(f"[app_payload_v2] asset prune skipped (non-fatal): {exc}")
    print(
        f"[app_payload_v2] publish succeeded run_date={our_date} "
        f"new_data_assets={len(uploads)} exit=0"
    )
    return True


def build_and_publish_v2(
    exports_dir: Path,
    *,
    v1_manifest: Dict[str, Any],
    out_dir: Path,
    repo: str = DEFAULT_REPO,
    tag: str = DEFAULT_TAG,
) -> Tuple[Dict[str, Any], bool]:
    manifest = build_v2_sidecar(
        exports_dir, out_dir, v1_manifest=v1_manifest, repo=repo, tag=tag
    )
    return manifest, publish_v2_sidecar(out_dir, repo=repo, tag=tag)
