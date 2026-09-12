"""Activation evidence and rollback tests; payload bytes come from retained CDR."""
from __future__ import annotations

import copy
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import pi_cdr_quality_activate as activate
import pi_cdr_quality_activate_evidence as evidence
from cdr_quality_accounting import canonical_digest

TARGET, PREVIOUS = "a" * 40, "b" * 40
PUBLIC = Path(__file__).parents[1] / "docs/evidence/backup-observation-20260911/publication"


def save(path: Path, value: dict) -> dict:
    path.write_text(json.dumps(value), encoding="utf-8")
    return evidence.record(path)


def pull_request(repository, target, head):
    return {"number": 1, "state": "closed", "merged": True, "merged_at": "2026-09-12T00:00:00Z",
            "merge_commit_sha": target, "base": {"ref": "main", "repo": {"full_name": repository}}, "head": {"sha": head}}


def checks(commit, names):
    return {"total_count": len(names), "check_runs": [{"id": number + 1, "head_sha": commit, "name": name,
            "status": "completed", "conclusion": "success", "app": {"slug": "github-actions"}} for number, name in enumerate(names)]}


def ci_proof(operation):
    head = "c" * 40
    required = {name: "SUCCESS" for name in ("bot-feedback-gate", "payload builder (pytest)", "process liveness (Windows)")}
    documents = {"pull_request": pull_request("yanniedog/AR-local", TARGET, head),
        "protection": {"required_status_checks": {"contexts": ["bot-feedback-gate"]}}, "rules": {"rules": []},
        "check_runs": checks(head, required), "statuses": {"sha": head, "total_count": 0, "statuses": []},
        "review_threads": {"data": {"repository": {"pullRequest": {"number": 1, "headRefOid": head,
            "reviewThreads": {"pageInfo": {"hasNextPage": False}, "totalCount": 0, "nodes": []}}}}}}
    return save(operation / "ci.json", {"result": "PASS", "repository": "yanniedog/AR-local", "merge_commit": TARGET,
        "head_commit": head, "base": "main", "merged": True, "review_dispositions_complete": True,
        "required_checks": required, "evidence": {name: save(operation / f"{name}.json", doc) for name, doc in documents.items()}})


def app_proof(operation, manifest, candidate):
    commit, head = "d" * 40, "f" * 40
    suites = {"payloadRevision.test.ts": 5, "store.payloadRevision.test.ts": 6, "payloadAccounting.test.ts": 4}
    jest = {"success": True, "numFailedTests": 0, "numFailedTestSuites": 0, "numRuntimeErrorTestSuites": 0,
        "numPassedTests": 15, "testResults": [{"name": name, "status": "passed",
            "assertionResults": [{"status": "passed"}] * count} for name, count in suites.items()]}
    audit = {"schema_version": 1, "status": "PASS", "app_commit": commit, "app_worktree_clean": True, "run_date": manifest["run_date"],
        "manifest_sha256": candidate["sha256"], "acquisition": "private_candidate", "publication_verified": False,
        "manifest_url": None, "dates_index_sha256": None, "checks": [{"code": "metadata fixture", "status": "pass"}],
        "assets": {key: {"status": "PASS", "sha256": row["sha256"], "bytes": row["bytes"]} for key, row in manifest["files"].items()}}
    documents = {"mobile_ci": checks(head, ["mobile-ci"]), "revision_reader": jest, "headless_audit": audit}
    return save(operation / "app.json", {"result": "PASS", "producer_commit": TARGET, "app_commit": commit,
        "pull_request": save(operation / "app-pr.json", pull_request("yanniedog/AR-app", commit, head)),
        "revision_protocol": 1, **{name: {"result": "PASS", **save(operation / f"{name}.json", doc)} for name, doc in documents.items()}})


@pytest.fixture
def sealed(tmp_path):
    source, production, data, operation = (tmp_path / n for n in ("source", "production", "data", "operation"))
    for directory in (source, production, data, operation):
        directory.mkdir()
    (source / "worker.py").write_text("# candidate code\n")
    (production / "worker.py").write_text("# previous code\n")
    files = {"worker.py": evidence.sha(source / "worker.py")}
    ci = ci_proof(operation)
    junit = operation / "pytest.xml"
    junit.write_text('<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0"><testcase name="metadata"/></testsuite></testsuites>')
    audit = save(operation / "audit.json", {"status": "BLOCKED", "run_date": "2026-09-11", "issues": [],
        "capture": {"status": "PASS", "generation_id": "recorded-generation"}, "ledger": {"ok": True, "findings": []},
        "sources": [{"generation_id": "recorded-generation", "key": "runs/2026-09-11/_exports", "sqlite_to_export": {"status": "PASS"}}]})
    manifest = json.loads((PUBLIC / "manifest.json").read_bytes())
    manifest["files"] = {key: manifest["files"][key] for key in ("core", "details")}
    payload = operation / "payload"
    payload.mkdir()
    for key, descriptor in manifest["files"].items():
        shutil.copy2(PUBLIC / f"v1-{key}.json.gz", payload / descriptor["name"])
    candidate = save(payload / "manifest.json", manifest)
    app = app_proof(operation, manifest, candidate)
    protected = {"state/pointer.json": "e" * 64}
    canary = save(operation / "canary.json", {"schema": evidence.CANARY_SCHEMA, "result": "PASS", "target_commit": TARGET,
        "source_files": files, "protected_files": protected, "tests": evidence.junit_result(junit),
        "source_audit": audit, "candidate_manifest": candidate, "run_date": "2026-09-11", "generation_id": "recorded-generation", "dispositions": {}})
    bundle = save(operation / "candidate.bundle", {"artifact": "candidate bundle metadata fixture"})
    rollback = save(operation / "rollback.bundle", {"artifact": "rollback bundle metadata fixture"})
    current = datetime.now(timezone.utc)
    value = {"schema": evidence.SCHEMA, "authority": "D-027", "target_commit": TARGET, "previous_commit": PREVIOUS,
        "source_root": str(source), "production_root": str(production), "data_root": str(data), "operation_root": str(operation),
        "created_at": current.isoformat(), "expires_at": (current + timedelta(hours=1)).isoformat(), "source_files": files,
        "changed_files": files, "protected_files": protected,
        "evidence": {"candidate_bundle": bundle, "rollback_bundle": rollback, "ci": ci, "app": app, "canary": canary},
        "backup": {"status": "UNVERIFIED"}}
    path = operation / "activation.json"
    save(path, value)
    return path, value


def test_valid_manifest_preserves_independent_backup_and_source_diagnostic_status(sealed):
    path, _ = sealed
    result = evidence.validate_manifest(path, evidence.sha(path))
    assert result["backup"]["status"] == "UNVERIFIED"


@pytest.mark.parametrize("change", ["hash", "source", "expiry", "ci", "app", "asset"])
def test_changed_or_incomplete_evidence_rejects_activation(sealed, change):
    path, value = sealed
    expected = evidence.sha(path)
    if change == "hash":
        path.write_bytes(path.read_bytes() + b" ")
    elif change == "source":
        (Path(value["source_root"]) / "worker.py").write_text("changed")
    elif change == "expiry":
        value["expires_at"] = value["created_at"]
        save(path, value)
        expected = evidence.sha(path)
    elif change in {"ci", "app"}:
        proof_path = Path(value["evidence"][change]["path"])
        proof = evidence.read(proof_path)
        proof["result"] = "FAIL"
        value["evidence"][change] = save(proof_path, proof)
        save(path, value)
        expected = evidence.sha(path)
    else:
        candidate = evidence.read(Path(value["operation_root"]) / "payload/manifest.json")
        (Path(value["operation_root"]) / "payload" / candidate["files"]["core"]["name"]).write_bytes(b"changed")
    with pytest.raises(ValueError):
        evidence.validate_manifest(path, expected)


def test_historical_findings_need_exact_dispositions_but_remain_failed():
    issue = {"code": "DUPLICATE_PRODUCT_KEYS", "source": "runs/2026-05-31/_exports", "count": 1}
    report = {"status": "FAIL", "run_date": "2026-09-12", "capture": {"status": "PASS", "generation_id": "current"}, "ledger": {"ok": True, "findings": []},
        "sources": [{"generation_id": "current", "key": "runs/2026-09-12/_exports", "sqlite_to_export": {"status": "PASS"}},
                    {"key": "runs/2026-05-31/_exports", "binding": {"contract_bound": False}}], "issues": [issue]}
    with pytest.raises(ValueError, match="disposition"):
        evidence.source_acceptance(report, "current", {})
    evidence.source_acceptance(report, "current", {canonical_digest(issue): "Retained historical duplicate rows; original evidence remains unchanged."})
    assert report["status"] == "FAIL"
    report["issues"][0]["source"] = "runs/2026-09-12/_exports"
    with pytest.raises(ValueError, match="current-source"):
        evidence.source_acceptance(report, "current", {})


@pytest.mark.parametrize("issue", [
    {"code": "LOG_AUDIT_FAILED", "path": "logs/old.log"},
    {"code": "SOURCE_AUDIT_FAILED", "source": "runs/2026-05-31/_exports", "detail": "artifact binding mismatch"},
    {"code": "PREVIOUSLY_AUDITED_SOURCE_MISSING", "source": "runs/2026-05-31/_exports"},
    {"code": "SOURCE_AUDIT_FAILED", "source": "runs/2026-09-12/_failed_attempts/other/exports/_exports", "detail": "one finalized daily SQLite database is required"},
])
def test_control_plane_hash_or_disguised_current_issue_cannot_be_dispositioned(sealed, issue):
    _, value = sealed
    canary = evidence.read(Path(value["evidence"]["canary"]["path"]))
    report = evidence.read(Path(canary["source_audit"]["path"]))
    report["run_date"] = "2026-09-12"
    report["issues"] = [issue]
    with pytest.raises(ValueError):
        evidence.source_acceptance(report, "recorded-generation", {canonical_digest(issue): "Attempted blanket waiver must not become valid historical acceptance."})


@pytest.mark.parametrize("part", ["pull_request", "check_runs", "review_threads", "protection"])
def test_arbitrary_or_nonterminal_raw_github_proof_is_rejected(sealed, part):
    _, value = sealed
    ci = evidence.read(Path(value["evidence"]["ci"]["path"]))
    entry = ci["evidence"][part]
    ci["evidence"][part] = save(Path(entry["path"]), {"result": "PASS", "text": "not a GitHub result"})
    with pytest.raises((ValueError, KeyError, TypeError)):
        evidence.ci_binding(ci, TARGET)


@pytest.mark.parametrize("part", ["mobile_ci", "revision_reader", "headless_audit"])
def test_arbitrary_or_nonterminal_raw_app_proof_is_rejected(sealed, part):
    _, value = sealed
    app = evidence.read(Path(value["evidence"]["app"]["path"]))
    canary = evidence.read(Path(value["evidence"]["canary"]["path"]))
    app[part] = {"result": "PASS", **save(Path(app[part]["path"]), {"result": "PASS"})}
    with pytest.raises((ValueError, KeyError, TypeError)):
        evidence.app_binding(app, TARGET, canary)


def test_current_artifact_mutation_cannot_reuse_unchanged_pointer_or_contract(tmp_path, monkeypatch):
    import cdr_export_contract
    data = tmp_path / "data"
    exports = data / "runs/2026-09-11/_exports"
    exports.mkdir(parents=True)
    state = data / "state"
    for name in ("observation-pointers-v2", "ledger-v2/events/2026-09-11", "markers", "contracts"):
        (state / name).mkdir(parents=True)
    core_path = exports / "retained-core.json.gz"
    shutil.copy2(PUBLIC / "v1-core.json.gz", core_path)
    contract = {"source_path": "runs/2026-09-11/_exports", "generation_id": "recorded-generation", "observation_date": "2026-09-11",
        "artifacts": [{"path": core_path.name, "sha256": evidence.sha(core_path), "bytes": core_path.stat().st_size}]}
    save(state / "observation-pointers-v2/latest-observation.json", {"generation_id": "recorded-generation",
        "marker_path": "markers/current.json", "export_path": contract["source_path"]})
    save(state / "markers/current.json", {"export_contract_path": "contracts/current.json"})
    save(state / "contracts/current.json", contract)
    save(state / "ledger-v2/head.json", {"generation_id": "recorded-generation"})
    save(state / "ledger-v2/events/2026-09-11/current.json", {"generation_id": "recorded-generation"})
    monkeypatch.setattr(cdr_export_contract, "load_contract", lambda _: contract)
    before = activate.protected_files(data)
    assert "runs/2026-09-11/_exports/retained-core.json.gz" in before
    assert "state/ledger-v2/events/2026-09-11/current.json" in before
    core_path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="immutable contract"):
        activate.protected_files(data)


@pytest.mark.parametrize("xml", ['<testsuites/>', '<testsuite tests="2"><testcase/></testsuite>',
    '<testsuite tests="1" skipped="1"><testcase><skipped/></testcase></testsuite>',
    '<testsuite tests="1"><testcase><failure/></testcase></testsuite>'])
def test_incomplete_or_false_zero_exit_junit_is_not_success(tmp_path, xml):
    path = tmp_path / "result.xml"
    path.write_text(xml)
    with pytest.raises(ValueError):
        evidence.junit_result(path)


@pytest.fixture
def runtime(sealed, monkeypatch):
    path, manifest = sealed
    production = Path(manifest["production_root"])
    state = {"head": PREVIOUS, "checkout": [], "verify_failure": False, "timer_failure": False,
             "timers": {unit: "active" for unit in activate.TIMERS}}
    monkeypatch.setattr(activate, "guard", lambda *_: None)
    monkeypatch.setattr(activate, "main_commit", lambda _: TARGET)
    monkeypatch.setattr(activate, "clean_commit", lambda root: state["head"] if root == production else TARGET)
    monkeypatch.setattr(activate, "protected_files", lambda _: manifest["protected_files"])
    monkeypatch.setattr(activate, "current_state", lambda _: ("2026-09-12", "recorded-generation", production))
    monkeypatch.setattr(activate, "smoke", lambda _: None)
    monkeypatch.setattr(activate, "active", lambda unit: state["timers"].get(unit, "inactive"))
    def verify(*_):
        if state["verify_failure"]:
            raise RuntimeError("runtime hash mismatch")
    monkeypatch.setattr(activate, "verify_runtime", verify)
    def git(_root, *args, **_kwargs):
        if args[:2] == ("bundle", "list-heads"):
            return f"{TARGET if Path(args[2]).name == 'candidate.bundle' else PREVIOUS} HEAD"
        if args[0] == "checkout":
            state["head"] = args[-1]
            state["checkout"].append(args[-1])
        return ""
    monkeypatch.setattr(activate, "git", git)
    def run(args, **_kwargs):
        if "WorkingDirectory" in args:
            return str(production)
        if "stop" in args:
            state["timers"][args[-1]] = "inactive"
        if "start" in args:
            if state["timer_failure"]:
                state["timer_failure"] = False
                raise RuntimeError("timer start failure")
            state["timers"][args[-1]] = "active"
        return ""
    monkeypatch.setattr(activate, "run", run)
    return SimpleNamespace(manifest=path, manifest_sha256=evidence.sha(path), dry_run=False), state


def test_dry_run_does_not_checkout_or_write_activation_receipt(runtime):
    args, state = runtime
    args.dry_run = True
    assert activate.activate(args)["result"] == "READY"
    assert state["checkout"] == []
    assert not list(args.manifest.parent.glob("activation-*"))


@pytest.mark.parametrize("failure", ["verify_failure", "timer_failure"])
def test_post_switch_failure_rolls_back_and_restores_coordination(runtime, failure):
    args, state = runtime
    state[failure] = True
    with pytest.raises(RuntimeError, match="activation failed"):
        activate.activate(args)
    assert state["checkout"] == [TARGET, PREVIOUS]
    assert all(value == "active" for value in state["timers"].values())
    result = evidence.read(next(args.manifest.parent.glob("activation-*/result.json")))
    assert result["result"] == "FAIL" and result["rollback"] == "PASS"


def test_success_keeps_exact_candidate_and_no_backup_claim(runtime):
    args, state = runtime
    result = activate.activate(args)
    assert result["result"] == "PASS" and state["checkout"] == [TARGET]
    assert result["backup"]["status"] == "UNVERIFIED"


def test_main_moving_before_lock_rejects_without_checkout(runtime, monkeypatch):
    args, state = runtime
    values = iter([TARGET, "e" * 40])
    monkeypatch.setattr(activate, "main_commit", lambda _: next(values))
    with pytest.raises(RuntimeError, match="activation failed"):
        activate.activate(args)
    assert state["checkout"] == []
    assert all(value == "active" for value in state["timers"].values())


def test_overlapping_or_parent_escaping_workspaces_are_rejected(tmp_path):
    for name in ("source", "production", "data"):
        (tmp_path / name).mkdir()
    with pytest.raises(ValueError, match="separate"):
        activate.layout(tmp_path / "source", tmp_path / "production", tmp_path / "data", tmp_path / "data/work")
    with pytest.raises(ValueError, match="unsafe"):
        evidence.relative(tmp_path, "../outside")
