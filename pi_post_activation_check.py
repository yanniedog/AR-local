#!/usr/bin/env python3
"""Fail-closed post-activation checklist for Pi safe-head rollouts.

Checks HTTP acceptance and optional read-only checkout identity.
Never deploys, never enables timers, never writes Drive, never mutates git.

Exit codes:
  0  all requested checks passed
  1  one or more checks failed
  2  invalid flags
  3  SSH unreachable (only when --with-ssh-identity)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Optional, Sequence

from ar_local_pi_runtime import PI_PUBLIC_BASE_URL, manifest_banks_rate_count

FULL_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_CONFIG = 2
EXIT_SSH = 3


def _http_latest(base_url: str, *, timeout: float = 30.0) -> tuple[int, Optional[dict]]:
    latest = base_url.rstrip("/") + "/api/latest"
    try:
        with urllib.request.urlopen(latest, timeout=timeout) as resp:
            if int(resp.status) != 200:
                print(f"pi_post_activation_check: {latest} HTTP {resp.status}", file=sys.stderr)
                return EXIT_FAIL, None
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"pi_post_activation_check: {latest} HTTP {exc.code}", file=sys.stderr)
        return EXIT_FAIL, None
    except Exception as exc:
        print(f"pi_post_activation_check: {latest} failed: {exc}", file=sys.stderr)
        return EXIT_FAIL, None
    if not isinstance(payload, dict):
        print("pi_post_activation_check: /api/latest is not a JSON object", file=sys.stderr)
        return EXIT_FAIL, None
    return EXIT_OK, payload


def check_http(base_url: str, *, expect_run_date: str = "") -> int:
    code, payload = _http_latest(base_url)
    if code != EXIT_OK or payload is None:
        return EXIT_FAIL
    rates = manifest_banks_rate_count(payload)
    run_date = payload.get("run_date")
    print(f"pi_post_activation_check: HTTP OK run_date={run_date!r} rates={rates}")
    if rates <= 0:
        print("pi_post_activation_check: banks_counts.rates must be > 0", file=sys.stderr)
        return EXIT_FAIL
    if expect_run_date and str(run_date) != expect_run_date:
        print(
            f"pi_post_activation_check: run_date {run_date!r} != expected {expect_run_date!r}",
            file=sys.stderr,
        )
        return EXIT_FAIL
    return EXIT_OK


def check_ssh_identity(expected_commit: str) -> int:
    # Local import keeps HTTP-only runs free of SSH helpers.
    import pi_deploy_verify

    # fetch=False: read-only identity must not mutate FETCH_HEAD / remote refs.
    try:
        snap = pi_deploy_verify.pi_remote_snapshot(dry_run=False, fetch=False)
    except Exception as exc:
        print(
            f"pi_post_activation_check: SSH checkout read failed: {exc}",
            file=sys.stderr,
        )
        return EXIT_SSH
    if snap is None:
        print("pi_post_activation_check: could not read Pi checkout via SSH", file=sys.stderr)
        return EXIT_SSH
    head = snap.get("AR_HEAD", "")
    origin = snap.get("AR_ORIGIN", "")
    ar_dirty = (snap.get("AR_DIRTY") or "").strip()
    site_dirty = (snap.get("SITE_DIRTY") or "").strip()
    print(f"pi_post_activation_check: AR_HEAD={head} AR_ORIGIN={origin}")
    print(f"pi_post_activation_check: SITE_HEAD={snap.get('SITE_HEAD')} SITE_ORIGIN={snap.get('SITE_ORIGIN')}")
    print(f"pi_post_activation_check: DASHBOARD={snap.get('DASHBOARD')}")
    ok = True
    if head != expected_commit:
        print(
            f"pi_post_activation_check: AR_HEAD {head[:12]} != expected {expected_commit[:12]}",
            file=sys.stderr,
        )
        ok = False
    if ar_dirty:
        print("pi_post_activation_check: AR-local checkout is dirty", file=sys.stderr)
        ok = False
    if site_dirty:
        print(
            "pi_post_activation_check: australianrates checkout is dirty (shell integrity)",
            file=sys.stderr,
        )
        ok = False
    if snap.get("DASHBOARD") != "active":
        print("pi_post_activation_check: dashboard service not active", file=sys.stderr)
        ok = False
    # Intentionally do not require ingest timers armed (held-timer rollouts).
    print(
        "pi_post_activation_check: timer arming not required by this checklist "
        "(use pi:deploy:verify separately when timers must be armed)"
    )
    return EXIT_OK if ok else EXIT_FAIL


def print_manual_remainder(expected_commit: str) -> None:
    print("pi_post_activation_check: remaining operator gates (not auto-asserted here):")
    print(f"  - soak >= 2h after activation of {expected_commit}")
    print("  - npm run verify:pi (history series) when authorized")
    print("  - natural-ingest closeout after next terminal NATURAL day")
    print("  - day-archive timer remains separately authorized (do not enable here)")
    print("  - append handoff/evidence packet; do not rewrite prior records")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail-closed post-activation checks (no deploy / no timer enable)."
    )
    parser.add_argument(
        "--expected-commit",
        required=True,
        help="Exact 40-character lowercase SHA that must be active after activation.",
    )
    env_base = os.environ.get("AR_PI_BASE_URL", "").strip()
    parser.add_argument(
        "--base-url",
        default=env_base or PI_PUBLIC_BASE_URL,
        help="Dashboard base URL (default: AR_PI_BASE_URL or Pi public URL).",
    )
    parser.add_argument(
        "--expect-run-date",
        default="",
        help="Optional YYYY-MM-DD that /api/latest run_date must equal.",
    )
    parser.add_argument(
        "--with-ssh-identity",
        action="store_true",
        help="Also read Pi checkout identity over SSH (read-only). Still never deploys.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    expected = str(args.expected_commit or "").strip().lower()
    if not FULL_COMMIT_RE.fullmatch(expected):
        print(
            "pi_post_activation_check: --expected-commit must be 40 lowercase hex",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    print(f"pi_post_activation_check: expected_commit={expected}")
    print("pi_post_activation_check: mode=no-deploy no-timer-enable fail-closed")

    http_rc = check_http(args.base_url, expect_run_date=str(args.expect_run_date or ""))
    ssh_rc = EXIT_OK
    identity_checked = False
    if args.with_ssh_identity:
        ssh_rc = check_ssh_identity(expected)
        identity_checked = True
    else:
        print(
            "pi_post_activation_check: SSH identity skipped "
            "(--expected-commit was NOT compared to any Pi checkout; "
            "pass --with-ssh-identity for read-only HEAD + dirty checks)"
        )

    print_manual_remainder(expected)

    if http_rc != EXIT_OK:
        return http_rc
    if ssh_rc != EXIT_OK:
        return ssh_rc
    if identity_checked:
        print("pi_post_activation_check: PASS (HTTP + SSH identity gates)")
    else:
        print(
            "pi_post_activation_check: PASS_HTTP_ONLY "
            "(commit identity not verified; not a full post-activation PASS)"
        )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
