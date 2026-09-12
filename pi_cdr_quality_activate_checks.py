"""Parse raw GitHub/Jest/app results used by the sealed D-027 evidence contract."""
from __future__ import annotations

from pathlib import Path


def raw(entry):
    from pi_cdr_quality_activate_evidence import checked, read
    return read(checked(entry))


def merged_pr(value: dict, repository: str, target: str) -> str:
    if (value.get("state") != "closed" or value.get("merged") is not True
            or value.get("merge_commit_sha") != target or value.get("base", {}).get("ref") != "main"
            or value.get("base", {}).get("repo", {}).get("full_name") != repository
            or not value.get("number") or not value.get("merged_at")):
        raise ValueError("raw GitHub pull request does not prove the reviewed main merge")
    return value["head"]["sha"]


def completed_checks(document: dict, commit: str) -> dict:
    rows = document.get("check_runs")
    if not isinstance(rows, list) or document.get("total_count") != len(rows):
        raise ValueError("complete raw check-run response required; paginate before sealing")
    result = {}
    for row in sorted(rows, key=lambda row: int(row["id"])):
        if row.get("head_sha") != commit:
            raise ValueError("check run is not an exact-head result")
        if row.get("app", {}).get("slug") != "github-actions":
            continue
        result[row["name"]] = "SUCCESS" if row.get("status") == "completed" and row.get("conclusion") == "success" else "PENDING_OR_FAILED"
    return result


def producer_checks(value: dict, target: str) -> None:
    proof = value["evidence"]
    pr = raw(proof["pull_request"])
    head = merged_pr(pr, "yanniedog/AR-local", target)
    if head != value["head_commit"]:
        raise ValueError("CI summary head differs from raw merged pull request")
    protection = raw(proof["protection"])
    status_rule = protection.get("required_status_checks") or {}
    required = set(status_rule.get("contexts") or []) | {c["context"] for c in status_rule.get("checks") or []}
    # Export GET branches/main/rules into {"rules": <raw-array>} so the object
    # envelope remains compatible with bounded evidence JSON reads.
    rules = raw(proof["rules"])
    if not isinstance(rules.get("rules"), list):
        raise ValueError("raw effective branch rules are required")
    for rule in rules["rules"]:
        if rule.get("type") == "required_status_checks":
            required.update(c["context"] for c in rule["parameters"]["required_status_checks"])
    if "bot-feedback-gate" not in required:
        raise ValueError("raw branch protection does not require the universal review gate")
    checks = completed_checks(raw(proof["check_runs"]), head)
    statuses = raw(proof["statuses"])
    if statuses.get("sha") != head or statuses.get("total_count") != len(statuses.get("statuses", [])):
        raise ValueError("complete exact-head raw commit statuses are required")
    for row in reversed(statuses["statuses"]):
        checks[row["context"]] = "SUCCESS" if row.get("state") == "success" else "PENDING_OR_FAILED"
    # Product CI is substantive for this runtime-changing deployment even when
    # repository branch protection only makes the universal gate required.
    required.update({"payload builder (pytest)", "process liveness (Windows)"})
    if set(value["required_checks"]) != required or any(checks.get(name) != "SUCCESS" for name in required):
        raise ValueError("raw exact-head checks do not satisfy effective protection and producer CI")
    document = raw(proof["review_threads"])
    reviewed = document["data"]["repository"]["pullRequest"]
    threads = reviewed["reviewThreads"]
    if (reviewed.get("number") != pr["number"] or reviewed.get("headRefOid") != head
            or threads.get("pageInfo", {}).get("hasNextPage") is not False
            or not isinstance(threads.get("nodes"), list) or threads.get("totalCount") != len(threads["nodes"])
            or any(row.get("isResolved") is not True for row in threads["nodes"])):
        raise ValueError("raw complete review threads do not prove exact-head closure")


def app_checks(value: dict, canary: dict) -> None:
    from pi_cdr_quality_activate_evidence import checked, read
    app_commit = value["app_commit"]
    head = merged_pr(raw(value["pull_request"]), "yanniedog/AR-app", app_commit)
    checks = completed_checks(raw(value["mobile_ci"]), head)
    if checks.get("mobile-ci") != "SUCCESS":
        raise ValueError("raw mobile-ci did not complete successfully for the merged app")
    jest = raw(value["revision_reader"])
    if (jest.get("success") is not True or jest.get("numFailedTests") != 0
            or jest.get("numFailedTestSuites") != 0 or jest.get("numRuntimeErrorTestSuites") != 0
            or jest.get("numPassedTests", 0) < 1 or not jest.get("testResults")):
        raise ValueError("complete successful raw Jest results are required")
    suites = {Path(row["name"].replace("\\", "/")).name: row for row in jest["testResults"]}
    required = {"payloadRevision.test.ts": 5, "store.payloadRevision.test.ts": 6, "payloadAccounting.test.ts": 4}
    for name, minimum in required.items():
        suite = suites.get(name) or {}
        assertions = suite.get("assertionResults") or []
        if suite.get("status") != "passed" or len(assertions) < minimum or any(row.get("status") != "passed" for row in assertions):
            raise ValueError("Jest lacks completed revision preservation, rejection and accounting cases")
    audit = raw(value["headless_audit"])
    manifest_path = checked(canary["candidate_manifest"])
    manifest = read(manifest_path)
    if (audit.get("schema_version") != 1 or audit.get("status") not in {"PASS", "WARN"}
            or audit.get("app_commit") != app_commit or audit.get("app_worktree_clean") is not True
            or audit.get("run_date") != canary["run_date"]
            or audit.get("manifest_sha256") != canary["candidate_manifest"]["sha256"]
            or audit.get("acquisition") != "private_candidate" or audit.get("publication_verified") is not False
            or audit.get("manifest_url") is not None or audit.get("dates_index_sha256") is not None
            or not audit.get("checks") or any(row.get("status") not in {"pass", "warn"} for row in audit["checks"])):
        raise ValueError("app audit does not prove the exact private canary payload")
    if set(audit.get("assets", {})) != set(manifest["files"]):
        raise ValueError("app audit asset inventory differs from the candidate")
    for name, descriptor in manifest["files"].items():
        observed = audit["assets"][name]
        if observed.get("status") != "PASS" or any(observed.get(k) != descriptor[k] for k in ("sha256", "bytes")):
            raise ValueError("app audit did not verify every candidate asset")
