"""D-027 sealed canary and exact-commit activation; no moving-main checkout."""
from __future__ import annotations

import argparse
import getpass
import gzip
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ar_local_operation_lock import production_lock
from pi_cdr_quality_activate_evidence import (
    CANARY_SCHEMA, SCHEMA, app_binding, checked, ci_binding, junit_result, read,
    record, relative, sha, source_acceptance, validate_manifest,
)

TIMERS = ("ar-local-daily-watchdog.timer", "ar-local-runtime-health.timer")
TZ = ZoneInfo("Australia/Hobart")


def run(argv, *, cwd=None, timeout=120, output: Path | None = None) -> str:
    result = subprocess.run(list(map(str, argv)), cwd=cwd, text=True, encoding="utf-8", errors="replace",
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, shell=False)
    if output:
        write_bytes(output, result.stdout.encode("utf-8"))
    if result.returncode:
        raise RuntimeError(f"{Path(str(argv[0])).name} command failed with exit {result.returncode}; see private operation evidence")
    return result.stdout.strip()


def git(repo: Path, *args, **kwargs) -> str:
    return run(["git", "--no-optional-locks", "-C", repo, *args], **kwargs)


def write_bytes(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def write(path: Path, value: dict) -> None:
    write_bytes(path, (json.dumps(value, sort_keys=True, indent=2) + "\n").encode())


def layout(source: Path, production: Path, data: Path, operation: Path) -> None:
    roots = (source, production, data, operation)
    if any(p is None or not p.is_absolute() or p.resolve() != p or any(x.is_symlink() for x in (p, *p.parents)) for p in roots):
        raise ValueError("absolute canonical paths without symlinks are required")
    if any(not p.is_dir() for p in roots[:3]):
        raise ValueError("source, production and data directories must already exist")
    if any(a == b or a in b.parents or b in a.parents for i, a in enumerate(roots) for b in roots[i + 1:]):
        raise ValueError("candidate, production, data and operation directories must be separate")


def clean_commit(repo: Path) -> str:
    if git(repo, "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none"):
        raise ValueError("checkout contains uncommitted or untracked files")
    return git(repo, "rev-parse", "HEAD")


def source_files(repo: Path) -> dict:
    return {name: sha(relative(repo, name)) for name in git(repo, "ls-files", "-z").split("\0") if name}


def main_commit(repo: Path) -> str:
    # Reading the remote ref never changes a checkout or trusts a stale tracking ref.
    url = git(repo, "remote", "get-url", "origin")
    if url not in {"https://github.com/yanniedog/AR-local.git", "https://github.com/yanniedog/AR-local",
                   "git@github.com:yanniedog/AR-local.git"}:
        raise ValueError("origin must be the authoritative AR-local repository")
    result = git(repo, "ls-remote", "--exit-code", "origin", "refs/heads/main").split()
    if len(result) != 2 or result[1] != "refs/heads/main":
        raise ValueError("cannot resolve authoritative main")
    return result[0]


def protected_files(data: Path) -> dict:
    from cdr_export_contract import load_contract
    from cdr_quality_sources import source_files as audit_files
    pointer = data / "state/observation-pointers-v2/latest-observation.json"
    selected = read(pointer)
    marker = relative(data / "state", selected["marker_path"])
    completion = read(marker)
    exports = relative(data, selected["export_path"])
    contract_path = relative(data / "state", completion["export_contract_path"])
    contract = load_contract(contract_path)
    if relative(data, contract["source_path"]) != exports or contract["generation_id"] != selected["generation_id"]:
        raise ValueError("selected source differs from its export contract")
    source = {"root": exports, "contract": contract, "run_date": contract["observation_date"]}
    paths = {pointer, data / "state/ledger-v2/head.json", marker, contract_path}
    paths.update((data / "state/ledger-v2/events").glob("*/*.json"))
    for path, descriptor in audit_files(source):
        digest = sha(path)
        if descriptor and (digest != descriptor["sha256"] or path.stat().st_size != descriptor["bytes"]):
            raise ValueError("current source artifact differs from its immutable contract")
        paths.add(path)
    return {p.relative_to(data).as_posix(): sha(p) for p in sorted(paths)}


def guard(data: Path, production: Path) -> None:
    if os.name != "posix":
        raise RuntimeError("activation requires the Pi Linux host")
    from pi_cdr_recovery import assert_recovery_start_safe
    from ar_local_pi_runtime import data_root
    if data_root(production) != data:
        raise ValueError("requested data root differs from production runtime data root")
    assert_recovery_start_safe(production)
    if data.resolve() != data or production.resolve() != production:
        raise ValueError("canonical production paths required")
    if run(["systemctl", "show", "ar-local-daily.timer", "-p", "ActiveState", "--value"]) != "active":
        raise RuntimeError("mandatory natural ingest timer is not active")
    values = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    if int(values["MemAvailable"].split()[0]) * 1024 < 2 * 1024**3:
        raise RuntimeError("less than 2 GiB available memory")
    pressure = Path("/proc/pressure/memory").read_text().splitlines()[0]
    if float(dict(item.split("=") for item in pressure.split()[1:])["avg10"]) >= 10:
        raise RuntimeError("memory pressure exceeds canary/activation bound")


def current_state(data: Path) -> tuple[str, str, Path]:
    pointer = read(data / "state/observation-pointers-v2/latest-observation.json")
    run_date = str(pointer.get("run_date") or pointer.get("date") or pointer["generation_id"][4:14])
    if run_date != datetime.now(TZ).date().isoformat():
        raise ValueError("selected observation is not current-day")
    return run_date, pointer["generation_id"], relative(data, pointer["export_path"])


def canary_worker(args) -> dict:
    from app_payload_build import build_payload
    from app_payload_revisions_state import validate_manifest as validate_payload
    from app_payload_details import build_details
    from cdr_quality_accounting import SECTIONS, canonical_digest, rate_rows_digest, reconcile_public_core
    from cdr_quality_audit import audit
    source, data, operation = args.source, args.data_root, args.operation
    layout(source, args.production, data, operation)
    if os.name != "posix" or any(os.access(p, os.W_OK) for p in (source, args.production, data)):
        raise ValueError("canary worker requires read-only production, data and candidate mounts")
    target = clean_commit(source)
    before, files = protected_files(data), source_files(source)
    run_date, generation, exports = current_state(data)
    tests = operation / "pytest.xml"
    run([args.python, "-B", "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider",
         "--basetemp", operation / "pytest-temp", f"--junitxml={tests}"], cwd=source,
        timeout=3600, output=operation / "pytest.txt")
    test_result = junit_result(tests)
    report = audit(data, run_date, scrub=True, public=False, audit_root=operation / "source-audit")
    if report["capture"]["status"] != "PASS":
        raise ValueError("canary has no verified current source")
    dispositions = read(args.dispositions) if args.dispositions else {}
    source_acceptance(report, generation, dispositions)
    output = operation / "payload"
    manifest = build_payload(exports, output)
    validate_payload(manifest, output)
    if manifest.get("enc"):
        raise ValueError("canary must build private plaintext for local reconciliation")
    core = json.loads(gzip.decompress((output / manifest["files"]["core"]["name"]).read_bytes()))
    if reconcile_public_core(core, report["capture"]["coverage"]):
        raise ValueError("candidate payload does not reconcile with verified source")
    current = next(row for row in report["sources"] if row["generation_id"] == generation)
    for section in SECTIONS:
        rows = ((core.get("sections") or {}).get(section) or {}).get("rates") or []
        if rate_rows_digest(rows) != current["published_rate_digests"][section]:
            raise ValueError("candidate payload rate content differs from verified source")
    details = json.loads(gzip.decompress((output / manifest["files"]["details"]["name"]).read_bytes()))
    exported = json.loads((exports / "dashboard-cache" / run_date / "banks.json").read_bytes())
    if canonical_digest(details["products"]) != canonical_digest(build_details(exported["products"])):
        raise ValueError("candidate payload product details differ from verified source")
    if protected_files(data) != before or source_files(source) != files or clean_commit(source) != target:
        raise ValueError("canary changed production evidence or candidate code")
    latest = read(operation / "source-audit/latest.json")
    return {"schema": CANARY_SCHEMA, "result": "PASS", "target_commit": target,
            "run_date": run_date, "generation_id": generation, "protected_files": before,
            "source_files": files, "tests": test_result,
            "source_audit": record(operation / "source-audit" / latest["path"]),
            "candidate_manifest": record(output / "manifest.json"),
            "dispositions": dispositions, "scope": "full pytest and retained-real-source replay; no live capture or publication",
            "completed_at": datetime.now(timezone.utc).isoformat()}


def canary(args) -> dict:
    layout(args.source, args.production, args.data_root, args.operation)
    guard(args.data_root, args.production)
    if clean_commit(args.source) != args.expected_commit or main_commit(args.source) != args.expected_commit:
        raise ValueError("canary must use exact clean authoritative main")
    args.operation.mkdir(parents=True, exist_ok=False)
    (args.operation / "tmp").mkdir()
    command = ["sudo", "-n", "systemd-run", "--wait", "--pipe", "--collect",
               f"--unit=ar-local-quality-canary-{uuid.uuid4().hex[:12]}"]
    current = datetime.now(TZ)
    closing = current.replace(hour=22, minute=0, second=0, microsecond=0)
    runtime = min(5400, int((closing - current).total_seconds()) - 45)
    if runtime < 300:
        raise ValueError("insufficient time for canary before recovery cutoff")
    properties = [f"User={getpass.getuser()}", f"WorkingDirectory={args.source}", "ProtectSystem=strict",
                  "ProtectHome=true", "PrivateTmp=true", "PrivateNetwork=true", "NoNewPrivileges=true",
                  f"ReadOnlyPaths={args.production}", f"ReadOnlyPaths={args.data_root}",
                  f"ReadWritePaths={args.operation}", "InaccessiblePaths=-/etc/ar-local",
                  "InaccessiblePaths=-/var/lib/ar-local-drive-backup/credentials",
                  "Environment=PYTHONDONTWRITEBYTECODE=1",
                  f"Environment=TMPDIR={args.operation / 'tmp'}",
                  f"Environment=AR_LOCAL_DATA_ROOT={args.operation / 'private-data'}",
                  f"Environment=AR_LOCAL_PORTABLE_ROOT={args.operation / 'private-portable'}",
                  "MemoryHigh=2500M", "MemoryMax=3G", "MemorySwapMax=0", "CPUQuota=200%",
                  "IOWeight=10", "TasksMax=256", "OOMPolicy=stop", "KillMode=control-group",
                  "TimeoutStopSec=30s", f"RuntimeMaxSec={runtime}s"]
    command += [f"--property={p}" for p in properties]
    command += [args.python, "-B", args.source / "pi_cdr_quality_activate.py", "canary-worker",
                "--source", args.source, "--production", args.production, "--data-root", args.data_root,
                "--operation", args.operation, "--python", args.python]
    if args.dispositions:
        command += ["--dispositions", args.dispositions]
    run(command, timeout=runtime + 60, output=args.operation / "canary-service.txt")
    return read(args.operation / "canary.json")


def seal(args) -> dict:
    layout(args.source, args.production, args.data_root, args.operation)
    target = clean_commit(args.source)
    if target != args.expected_commit or main_commit(args.source) != target:
        raise ValueError("seal requires exact clean authoritative main")
    canary_path = args.operation / "canary.json"
    canary_result = read(canary_path)
    ci_binding(read(args.ci_binding), target)
    app_binding(read(args.app_acceptance), target, canary_result)
    if canary_result.get("result") != "PASS" or canary_result.get("target_commit") != target:
        raise ValueError("candidate canary missing or failed")
    guard(args.data_root, args.production)
    with production_lock(args.data_root / "state/daily-ingest.lock", "quality-seal"):
        guard(args.data_root, args.production)
        current_state(args.data_root)
        previous = clean_commit(args.production)
        before = protected_files(args.data_root)
        if before != canary_result["protected_files"]:
            raise ValueError("current observation changed since canary")
        bundle = args.operation / "candidate.bundle"
        rollback = args.operation / "rollback.bundle"
        git(args.source, "bundle", "create", bundle, "HEAD", timeout=300)
        git(args.production, "bundle", "create", rollback, "HEAD", timeout=300)
        # Resolve the predecessor in the candidate's object store read-only.
        changed = git(args.source, "diff", "--name-only", "-z", previous, target).split("\0")
        changed_files = {name: sha(relative(args.source, name)) if relative(args.source, name).exists() else None
                         for name in changed if name}
        created = datetime.now(timezone.utc)
        expires = min(created + timedelta(hours=6), created.astimezone(TZ).replace(hour=22, minute=0, second=0, microsecond=0))
        value = {"schema": SCHEMA, "authority": "D-027", "target_commit": target, "previous_commit": previous,
                 "source_root": str(args.source), "production_root": str(args.production), "data_root": str(args.data_root),
                 "operation_root": str(args.operation), "created_at": created.isoformat(), "expires_at": expires.isoformat(),
                 "source_files": source_files(args.source), "changed_files": changed_files, "protected_files": before,
                 "evidence": {"candidate_bundle": record(bundle), "rollback_bundle": record(rollback),
                              "ci": record(args.ci_binding), "app": record(args.app_acceptance), "canary": record(canary_path)},
                 "backup": {"status": "UNVERIFIED", "reason": "independent Drive receipt; never inferred from activation"}}
        manifest = args.operation / "activation.json"
        write(manifest, value)
        validate_manifest(manifest, sha(manifest))
        return {"result": "SEALED", **record(manifest), "target_commit": target}


def active(unit: str) -> str:
    return run(["systemctl", "show", unit, "-p", "ActiveState", "--value"])


def smoke(source: Path) -> None:
    from pi_deploy_verify import wait_for_http_smoke
    if wait_for_http_smoke("http://100.78.28.10/", require_rates=True, budget_seconds=120) != 0:
        raise RuntimeError("dashboard did not become ready within 120 seconds")
    run([sys.executable, source / "verify_local.py", "--base-url=http://100.78.28.10/", "--require-banks-rates"], timeout=120)


def verify_runtime(production: Path, target: str, files: dict, data: Path, protected: dict) -> None:
    if clean_commit(production) != target or source_files(production) != files:
        raise ValueError("deployed code does not match sealed candidate")
    if protected_files(data) != protected:
        raise ValueError("protected observation changed during activation")
    if active("ar-local-daily.timer") != "active" or active("ar-local-dashboard.service") != "active":
        raise RuntimeError("required production units are not active")
    smoke(production)


def activate(args) -> dict:
    manifest = validate_manifest(args.manifest, args.manifest_sha256)
    source, production, data, operation = (Path(manifest[key]) for key in
                                         ("source_root", "production_root", "data_root", "operation_root"))
    layout(source, production, data, operation)
    guard(data, production)
    if main_commit(source) != manifest["target_commit"] or clean_commit(production) != manifest["previous_commit"]:
        raise ValueError("main or production changed since sealing")
    for unit in ("ar-local-dashboard.service", "ar-local-daily.service"):
        if run(["systemctl", "show", unit, "-p", "WorkingDirectory", "--value"]) != str(production):
            raise ValueError("service uses a different production checkout")
    if args.dry_run:
        if protected_files(data) != manifest["protected_files"]:
            raise ValueError("protected observation changed since sealing")
        return {"result": "READY", "target_commit": manifest["target_commit"], "mutated": False}
    transaction = operation / ("activation-" + uuid.uuid4().hex)
    transaction.mkdir()
    timers = {unit: active(unit) for unit in TIMERS}
    receipt = {"schema": SCHEMA, "result": "RUNNING", "manifest": record(args.manifest),
               "started_at": datetime.now(timezone.utc).isoformat(), "timers_before": timers, "backup": manifest["backup"]}
    write(transaction / "intent.json", receipt)
    switched = False
    failure = None
    try:
        for unit, state in timers.items():
            if state == "active":
                run(["sudo", "-n", "systemctl", "stop", unit])
        for unit in ("ar-local-daily-watchdog.service", "ar-local-runtime-health.service"):
            if active(unit) not in {"inactive", "failed"}:
                raise RuntimeError("coordination service still running; retry after it finishes")
        with production_lock(data / "state/daily-ingest.lock", "quality-activation"):
            guard(data, production)
            current_state(data)
            validate_manifest(args.manifest, args.manifest_sha256)
            if (main_commit(source) != manifest["target_commit"] or clean_commit(production) != manifest["previous_commit"]
                    or protected_files(data) != manifest["protected_files"]):
                raise ValueError("production or protected data changed before activation lock")
            smoke(production)
            candidate_bundle = checked(manifest["evidence"]["candidate_bundle"])
            rollback_bundle = checked(manifest["evidence"]["rollback_bundle"])
            for bundle, expected in ((candidate_bundle, manifest["target_commit"]), (rollback_bundle, manifest["previous_commit"])):
                if git(production, "bundle", "list-heads", bundle).splitlines() != [f"{expected} HEAD"]:
                    raise ValueError("code bundle does not identify its sealed commit")
                git(production, "bundle", "verify", bundle)
            try:
                git(production, "fetch", "--no-tags", candidate_bundle, "HEAD", timeout=300)
                # Mark before checkout so a partially failed checkout also rolls back.
                switched = True
                git(production, "checkout", "--detach", manifest["target_commit"])
                run(["sudo", "-n", "systemctl", "restart", "ar-local-dashboard.service"])
                verify_runtime(production, manifest["target_commit"], manifest["source_files"], data, manifest["protected_files"])
                # Restore coordination while still holding the lease. A failure
                # here takes the same rollback path as a failed runtime probe.
                for unit, state in timers.items():
                    if state == "active":
                        run(["sudo", "-n", "systemctl", "start", unit])
                    if active(unit) != state:
                        raise RuntimeError("coordination timer restoration failed")
            except BaseException:
                if switched:
                    git(production, "checkout", "--detach", manifest["previous_commit"])
                    run(["sudo", "-n", "systemctl", "restart", "ar-local-dashboard.service"])
                    if clean_commit(production) != manifest["previous_commit"]:
                        raise RuntimeError("CRITICAL: rollback commit could not be verified")
                    smoke(production)
                    receipt["rollback"] = "PASS"
                raise
        receipt.update(result="PASS", target_commit=manifest["target_commit"], protected_data="UNCHANGED", dashboard="PASS")
    except BaseException as error:
        receipt.update(result="FAIL", error=type(error).__name__ + ": " + str(error))
        failure = error
    finally:
        restoration = []
        for unit, state in timers.items():
            try:
                if state == "active":
                    run(["sudo", "-n", "systemctl", "start", unit])
                if active(unit) != state:
                    raise RuntimeError("timer state differs from pre-activation")
            except BaseException as error:
                restoration.append(f"{unit}: {type(error).__name__}")
        if restoration:
            receipt.update(result="FAIL", timer_restoration_errors=restoration)
        receipt["completed_at"] = datetime.now(timezone.utc).isoformat()
        write(transaction / "result.json", receipt)
    if failure or receipt["result"] != "PASS":
        raise RuntimeError(f"activation failed; inspect {transaction / 'result.json'}")
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("canary", "canary-worker", "seal", "activate"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--production", type=Path, default=Path("/srv/ar-local/AR-local"))
    parser.add_argument("--data-root", type=Path, default=Path("/srv/ar-local/data"))
    parser.add_argument("--operation", type=Path)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--expected-commit")
    parser.add_argument("--dispositions", type=Path)
    parser.add_argument("--ci-binding", type=Path)
    parser.add_argument("--app-acceptance", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "activate" and (not args.manifest or not args.manifest_sha256):
            raise ValueError("activate requires --manifest and --manifest-sha256")
        if args.command != "activate" and (not args.source or not args.operation):
            raise ValueError("canary/seal requires --source and --operation")
        if args.command == "seal" and (not args.ci_binding or not args.app_acceptance):
            raise ValueError("seal requires --ci-binding and --app-acceptance")
        if args.command == "canary-worker":
            result = canary_worker(args)
            write(args.operation / "canary.json", result)
        else:
            result = {"canary": canary, "seal": seal, "activate": activate}[args.command](args)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as error:
        result = {"result": "BLOCKED", "error": type(error).__name__ + ": " + str(error)}
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if result["result"] in {"PASS", "READY", "SEALED"} else 2


if __name__ == "__main__":
    if os.name == "posix":
        def interrupted(_signal, _frame):
            raise RuntimeError("activation interrupted; attempting bounded cleanup")
        signal.signal(signal.SIGTERM, interrupted)
    raise SystemExit(main())
