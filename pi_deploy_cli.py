"""Command handlers for the Pi deploy verifier."""

from __future__ import annotations

import argparse
import os
import sys
from types import ModuleType


def cmd_verify(args: argparse.Namespace, runtime: ModuleType) -> int:
    code = runtime.verify_sync(dry_run=args.dry_run)
    if code != runtime.EXIT_OK:
        return code
    if args.dry_run:
        print(f"pi_deploy_verify: dry-run would smoke {runtime.pi_base_url()}")
        return runtime.EXIT_OK
    smoke = runtime.wait_for_http_smoke(runtime.pi_base_url())
    if smoke != runtime.EXIT_OK:
        return smoke
    data = runtime.verify_production_data(dry_run=False)
    if data != runtime.EXIT_OK:
        return data
    print("pi_deploy_verify: verify OK (sync + status + data)")
    return runtime.EXIT_OK


def cmd_deploy(args: argparse.Namespace, runtime: ModuleType) -> int:
    expected_commit = str(args.expected_commit or "").strip().lower()
    if not runtime.FULL_COMMIT_RE.fullmatch(expected_commit):
        print(
            "pi_deploy_verify: --deploy requires --expected-commit with an exact "
            "40-character lowercase SHA",
            file=sys.stderr,
        )
        return runtime.EXIT_CONFIG
    if args.bootstrap_observation and args.ingest_timeout <= 0:
        print(
            "pi_deploy_verify: --ingest-timeout must be positive",
            file=sys.stderr,
        )
        return runtime.EXIT_CONFIG
    local_main = runtime.origin_main_sha_local()
    if local_main != expected_commit:
        print(
            "pi_deploy_verify: approved commit is not the current local origin/main",
            file=sys.stderr,
        )
        return runtime.EXIT_CONFIG
    if args.dry_run:
        operations = [
            lambda: runtime.deployment_backup_gate(
                expected_commit, expected_commit, dry_run=True
            ),
            lambda: runtime.deploy_pull_all(expected_commit, dry_run=True),
            lambda: runtime.deploy_services(dry_run=True),
        ]
        if args.bootstrap_observation:
            operations.append(
                lambda: runtime.bootstrap_observation(
                    expected_commit,
                    timeout_seconds=args.ingest_timeout,
                    dry_run=True,
                )
            )
        operations.append(lambda: runtime.verify_production_data(dry_run=True))
        for operation in operations:
            code = operation()
            if code != runtime.EXIT_OK:
                return code
        print("pi_deploy_verify: dry-run deploy complete (no changes applied)")
        return runtime.EXIT_OK

    snapshot = runtime.pi_remote_snapshot(dry_run=False)
    if snapshot is None:
        print("pi_deploy_verify: could not read Pi state before deploy", file=sys.stderr)
        return runtime.EXIT_SSH
    if runtime._snap_has_dirty_repos(snapshot, context="— resolve before deploy"):
        return runtime.EXIT_VERIFY_FAIL
    if not runtime.pi_service_paths_ok(snapshot):
        return runtime.EXIT_VERIFY_FAIL
    if snapshot["AR_ORIGIN"] != expected_commit:
        print(
            "pi_deploy_verify: Pi origin/main does not match approved commit",
            file=sys.stderr,
        )
        return runtime.EXIT_VERIFY_FAIL
    if snapshot["SITE_HEAD"] != snapshot["SITE_ORIGIN"]:
        print(
            "pi_deploy_verify: australianrates checkout is behind origin/main; "
            "refusing an unrelated site mutation",
            file=sys.stderr,
        )
        return runtime.EXIT_VERIFY_FAIL

    old_commit = snapshot["AR_HEAD"]
    backup = runtime.deployment_backup_gate(expected_commit, old_commit, dry_run=False)
    if backup != runtime.EXIT_OK:
        return backup
    installed = runtime.deploy_pull_all(expected_commit, dry_run=False)
    if installed != runtime.EXIT_OK:
        return installed

    operations = [
        lambda: runtime.deploy_services(dry_run=False),
        lambda: runtime.verify_sync(dry_run=False, expected_commit=expected_commit),
    ]
    if args.bootstrap_observation:
        operations.append(
            lambda: runtime.bootstrap_observation(
                expected_commit,
                timeout_seconds=args.ingest_timeout,
                dry_run=False,
            )
        )
    operations.append(lambda: runtime.wait_for_http_smoke(runtime.pi_base_url()))
    operations.append(lambda: runtime.verify_production_data(dry_run=False))
    for operation in operations:
        code = operation()
        if code != runtime.EXIT_OK:
            rollback = runtime.rollback_to_protected_commit(
                old_commit, expected_commit, args.effective_command, dry_run=False
            )
            if rollback != runtime.EXIT_OK:
                print(
                    "pi_deploy_verify: CRITICAL candidate failed and rollback was not verified",
                    file=sys.stderr,
                )
            return code

    acceptance = runtime.record_deployment_acceptance(
        expected_commit, old_commit, args.effective_command, dry_run=False
    )
    if acceptance != runtime.EXIT_OK:
        rollback = runtime.rollback_to_protected_commit(
            old_commit, expected_commit, args.effective_command, dry_run=False
        )
        if rollback != runtime.EXIT_OK:
            print(
                "pi_deploy_verify: CRITICAL acceptance failed and rollback was not verified",
                file=sys.stderr,
            )
        return acceptance
    print("pi_deploy_verify: deploy OK")
    return runtime.EXIT_OK


def cmd_needs_pi(args: argparse.Namespace, runtime: ModuleType) -> int:
    files = runtime.changed_files_since(args.ref)
    if not files:
        print(f"pi_deploy_verify: no changed files since {args.ref}")
        return runtime.EXIT_OK
    if runtime.paths_touch_pi_deploy(files):
        print(
            f"pi_deploy_verify: Pi deploy recommended "
            f"({len(files)} files; pi-touching paths present)"
        )
        for path in sorted(files):
            if runtime.paths_touch_pi_deploy([path]):
                print(f"  {path}")
        return runtime.EXIT_OK
    print(f"pi_deploy_verify: no Pi-touching paths in {len(files)} files since {args.ref}")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify or apply Pi deploy "
            "(sync /srv/ar-local to origin/main, smoke status API)."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print remote actions without applying changes or running HTTP verification.",
    )
    parser.add_argument(
        "--expected-commit",
        default=os.environ.get("AR_PI_EXPECTED_COMMIT", ""),
        help="Exact approved 40-character lowercase origin/main commit; required for deploy.",
    )
    parser.add_argument(
        "--bootstrap-observation",
        action="store_true",
        help="Run one explicit canonical ingest before deployment acceptance.",
    )
    parser.add_argument(
        "--ingest-timeout",
        type=float,
        default=22500.0,
        help="Seconds to wait for --bootstrap-observation (default: 22500).",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--verify", action="store_true", help="Verify Pi sync and status.")
    mode.add_argument("--deploy", action="store_true", help="Deploy exact commit and verify.")
    mode.add_argument(
        "--needs-pi",
        action="store_true",
        help="Exit 0 when changed paths require Pi deployment.",
    )
    parser.add_argument(
        "--ref",
        default="origin/main~1",
        help="Diff base for --needs-pi (default: origin/main~1).",
    )
    return parser
