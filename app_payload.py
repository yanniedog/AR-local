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
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from cdr_ribbon_normalize import (
    aggregate_ribbon,
    normalized_rate_value as _normalized_rate_value,
)

from app_payload_brands import (
    _brand_lookup_keys,
    _get_brand_lookup,
    _put_brand_lookup,
    build_brands,
    find_bank_logo_dir,
    load_brand_logos,
    load_brand_shortcodes,
    load_rba_holds,
    load_rba_series,
)
from app_payload_build import (
    _asset,
    _compute_payload,
    _find_banks_json,
    _gzip_bytes,
    _ingest_schedule,
    _ongoing_num,
    _package,
    _package_payload,
    _row_conditional_kind,
    _row_is_base,
    _select_base_sibling,
    attach_ongoing_rates,
    build_and_publish,
    build_and_publish_dual,
    build_payload,
    core_section_summary,
    iter_valid_export_dates,
    seed_from_sample,
)
from app_payload_common import (
    APP_MIN_VERSION,
    BASE_DIR,
    CORE_RATE_FIELDS,
    DATED_TAG_PREFIX,
    DATES_INDEX_FILENAME,
    DEFAULT_REPO,
    DEFAULT_TAG,
    HISTORY_MIN_DATE,
    KEEP_RECENT_ASSETS,
    MAX_EMBEDDED_LOGO_BYTES,
    SCHEMA_VERSION,
    SUBPROCESS_TIMEOUT_SEC,
    SUBPROCESS_UPLOAD_TIMEOUT_SEC,
    VALID_SECTIONS,
    _RUN_DATE_RE,
    _is_blank,
    _load_json,
    compact,
    dated_release_title,
    dated_tag,
    is_dated_tag,
    is_rolling_tag,
    release_display_title,
    release_title,
    section_filter,
    utc_now_iso,
)
from app_payload_details import _detail_items, _detail_links, build_details
from app_payload_publish import (
    _gh_authed,
    _gh_available,
    _list_payload_release_tags,
    _live_manifest_status,
    _manifest_should_replace,
    _prune_release_assets,
    _published_history_dates,
    _release_current_title,
    _release_run_date_for_retitle,
    _update_release_title,
    _upload_dates_index,
    build_dates_index,
    publish_payload,
    refresh_dates_index,
    retitle_payload_releases,
)

__all__ = [
    "APP_MIN_VERSION",
    "BASE_DIR",
    "CORE_RATE_FIELDS",
    "DATED_TAG_PREFIX",
    "DATES_INDEX_FILENAME",
    "DEFAULT_REPO",
    "DEFAULT_TAG",
    "HISTORY_MIN_DATE",
    "KEEP_RECENT_ASSETS",
    "MAX_EMBEDDED_LOGO_BYTES",
    "SCHEMA_VERSION",
    "SUBPROCESS_TIMEOUT_SEC",
    "SUBPROCESS_UPLOAD_TIMEOUT_SEC",
    "VALID_SECTIONS",
    "_RUN_DATE_RE",
    "_asset",
    "_brand_lookup_keys",
    "_compute_payload",
    "_detail_items",
    "_detail_links",
    "_find_banks_json",
    "_get_brand_lookup",
    "_gh_authed",
    "_gh_available",
    "_gzip_bytes",
    "_ingest_schedule",
    "_is_blank",
    "_list_payload_release_tags",
    "_live_manifest_status",
    "_load_json",
    "_manifest_should_replace",
    "_normalized_rate_value",
    "_ongoing_num",
    "_package",
    "_package_payload",
    "_prune_release_assets",
    "_published_history_dates",
    "_put_brand_lookup",
    "_release_current_title",
    "_release_run_date_for_retitle",
    "_row_conditional_kind",
    "_row_is_base",
    "_select_base_sibling",
    "_update_release_title",
    "_upload_dates_index",
    "aggregate_ribbon",
    "attach_ongoing_rates",
    "build_and_publish",
    "build_and_publish_dual",
    "build_brands",
    "build_dates_index",
    "build_details",
    "build_payload",
    "compact",
    "core_section_summary",
    "dated_release_title",
    "dated_tag",
    "find_bank_logo_dir",
    "is_dated_tag",
    "is_rolling_tag",
    "iter_valid_export_dates",
    "load_brand_logos",
    "load_brand_shortcodes",
    "load_rba_holds",
    "load_rba_series",
    "main",
    "publish_payload",
    "refresh_dates_index",
    "release_display_title",
    "release_title",
    "retitle_payload_releases",
    "section_filter",
    "seed_from_sample",
    "subprocess",
    "utc_now_iso",
]


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
