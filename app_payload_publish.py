"""GitHub release publish helpers for the mobile-app payload."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app_payload_common import (
    DATED_TAG_PREFIX,
    DATES_INDEX_FILENAME,
    DEFAULT_REPO,
    DEFAULT_TAG,
    HISTORY_MIN_DATE,
    KEEP_RECENT_ASSETS,
    SCHEMA_VERSION,
    SUBPROCESS_TIMEOUT_SEC,
    SUBPROCESS_UPLOAD_TIMEOUT_SEC,
    _RUN_DATE_RE,
    _app_payload,
    dated_release_title,
    dated_tag,
    is_dated_tag,
    is_rolling_tag,
    release_display_title,
    release_title,
    _load_json,
)
def _gh_available() -> Optional[str]:
    return shutil.which("gh")



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
    gh = _app_payload("_gh_available")()
    if not gh or not _app_payload("_gh_authed")(gh):
        return []
    try:
        tags = _app_payload("_list_payload_release_tags")(gh, repo)
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
        status, live = _app_payload("_live_manifest_status")(repo, tag)
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
    view = _app_payload("subprocess").run(
        [gh, "release", "view", tag, "--repo", repo],
        capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SEC,
    )
    if view.returncode != 0:
        print(f"[app_payload] dates-index upload skipped: release {tag!r} missing")
        return False
    # nosemgrep: dangerous-subprocess-use-audit, dangerous-subprocess-use-tainted-env-args
    _app_payload("subprocess").run(
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
    gh = _app_payload("_gh_available")()
    if not gh or not _app_payload("_gh_authed")(gh):
        print("[app_payload] dates-index refresh skipped: no gh auth")
        return False

    dates = _published_history_dates(repo, min_date=min_date)
    if not dates:
        from app_payload_build import iter_valid_export_dates

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
        res = _app_payload("subprocess").run(
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
        res = _app_payload("subprocess").run(
            [gh, "auth", "status"], capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SEC
        )
        return res.returncode == 0
    except Exception:
        return False


def _prune_release_assets(gh: str, repo: str, tag: str, keep_names: set[str]) -> int:
    """Delete obsolete content-addressed data assets, keeping the current manifest's
    assets plus the KEEP_RECENT_ASSETS newest. Best-effort; returns count deleted."""
    # nosemgrep: dangerous-subprocess-use-audit, dangerous-subprocess-use-tainted-env-args
    listed = _app_payload("subprocess").run(
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
        res = _app_payload("subprocess").run(
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

    gh = _app_payload("_gh_available")()
    if not gh or not _app_payload("_gh_authed")(gh):
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
    view = _app_payload("subprocess").run(
        [gh, "release", "view", tag, "--repo", repo],
        capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SEC,
    )
    if view.returncode != 0:
        # nosemgrep: dangerous-subprocess-use-audit, dangerous-subprocess-use-tainted-env-args
        _app_payload("subprocess").run(
            [gh, "release", "create", tag, "--repo", repo, "--title", title,
             "--notes", notes, "--latest=false"],
            check=True, timeout=SUBPROCESS_TIMEOUT_SEC,
        )

    # Data assets are content-addressed, so a same-name asset already on the release is
    # byte-identical. Upload only the MISSING ones, WITHOUT --clobber — never delete an
    # asset the current manifest still references (an interrupted clobber could lose it).
    # nosemgrep: dangerous-subprocess-use-audit, dangerous-subprocess-use-tainted-env-args
    listed = _app_payload("subprocess").run(
        [gh, "release", "view", tag, "--repo", repo, "--json", "assets", "-q", ".assets[].name"],
        capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SEC,
    )
    existing = set(listed.stdout.split()) if listed.returncode == 0 else set()
    to_upload = [a for a in data_assets if a.name not in existing]
    if to_upload:
        # nosemgrep: dangerous-subprocess-use-audit, dangerous-subprocess-use-tainted-env-args
        _app_payload("subprocess").run(
            [gh, "release", "upload", tag, *[str(a) for a in to_upload], "--repo", repo],
            check=True, timeout=SUBPROCESS_UPLOAD_TIMEOUT_SEC,
        )
    # ...then replace manifest.json last, so it only ever points at assets already live.
    # First check the live manifest, distinguishing present / missing / transient-error.
    status, live = _app_payload("_live_manifest_status")(repo, tag)

    should_replace, replace_reason = _app_payload("_manifest_should_replace")(
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
        _app_payload("subprocess").run(
            [gh, "release", "upload", tag, str(manifest_path), "--repo", repo, "--clobber"],
            check=True, timeout=SUBPROCESS_UPLOAD_TIMEOUT_SEC,
        )
    except subprocess.SubprocessError:
        # Restore the displaced manifest ONLY after positively confirming it's safe:
        # the live manifest is now genuinely missing, or still the one we displaced
        # (generated_at unchanged). A transient recheck error -> do NOT restore (we can't
        # confirm we wouldn't clobber a newer concurrent publish).
        if backup_manifest.exists():
            recheck, cur = _app_payload("_live_manifest_status")(repo, tag)
            cur_gen = str((cur or {}).get("generated_at") or "")
            safe_to_restore = recheck == "missing" or (
                recheck == "present" and backup_gen is not None and cur_gen <= backup_gen
            )
            if safe_to_restore:
                try:
                    # nosemgrep: dangerous-subprocess-use-audit, dangerous-subprocess-use-tainted-env-args
                    _app_payload("subprocess").run(
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
    _app_payload("_update_release_title")(gh, repo, tag, our_run_date)
    if rolling:
        # Prune obsolete assets so the rolling release never hits GitHub's 1000-asset cap.
        try:
            keep = set(names)
            pruned = _app_payload("_prune_release_assets")(gh, repo, tag, keep)
            if pruned:
                print(f"[app_payload] pruned {pruned} obsolete release asset(s)")
        except Exception as exc:  # noqa: BLE001 - pruning must never fail a publish
            print(f"[app_payload] asset prune skipped (non-fatal): {exc}")
    return True


def _list_payload_release_tags(gh: str, repo: str) -> List[str]:
    """Return sorted ``app-payload-*`` release tag names from GitHub."""
    # nosemgrep: dangerous-subprocess-use-audit, dangerous-subprocess-use-tainted-env-args
    res = _app_payload("subprocess").run(
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
    res = _app_payload("subprocess").run(
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
    status, live = _app_payload("_live_manifest_status")(repo, tag)
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
    gh = _app_payload("_gh_available")()
    if not gh or not _app_payload("_gh_authed")(gh):
        raise RuntimeError(
            "[app_payload] gh CLI / GitHub auth required for retitle "
            "(set GH_TOKEN or gh auth login)"
        )
    tags = _app_payload("_list_payload_release_tags")(gh, repo)
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
        if _app_payload("_update_release_title")(gh, repo, tag, run_date):
            updated += 1
        else:
            skipped += 1
    print(f"[app_payload] retitle finished updated={updated} skipped={skipped}")
    return updated, skipped
