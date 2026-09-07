from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import laptop_backup_runtime_lineage as ancestry
import laptop_backup_runtime_transition as transition
import laptop_backup_scheduled as scheduled
import laptop_backup_scheduled_lineage as lineage
import laptop_pull_backup as receiver

EXPECTED = {"operator": "pytest", "plan_git_commit": receiver.PLAN_GIT_COMMIT}


def _record(target, label, production, candidate, previous=None, **changes):
    value = {
        "schema_version": 1, "plan_document_id": receiver.PLAN_DOCUMENT_ID,
        "plan_version": receiver.PLAN_VERSION, "plan_git_commit": receiver.PLAN_GIT_COMMIT,
        "plan_sha256": receiver.PLAN_SHA256,
        "plan_normalized_raw_sha256": receiver.PLAN_NORMALIZED_RAW_SHA256,
        "plan_raw_sha256": next(iter(receiver.PLAN_VALID_RAW_SHA256S)),
        "operator": "pytest", "protected_code_sha": production,
        "candidate_code_sha": candidate, "timestamps": {"completed_at": "2026-09-07T00:00:00Z"},
        "exact_commands": ["pytest"], "action": "NO_BACKUP_DATA_WRITE", "result": "PASS",
        "detail": {"status": "UP_TO_DATE"}, "deviations": [], "deviation_authorization": None,
        "previous_execution": previous, **changes,
    }
    path = target / f"catalog/scheduled-runs/{label}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(receiver.canonical_json_bytes(value))
    return {"record_path": path.relative_to(target).as_posix(), "record_sha256": receiver.sha256_file(path)}


def _pin(target, pointer):
    value = json.loads((target / pointer["record_path"]).read_bytes())
    return {"production_sha": value["protected_code_sha"], "receiver_sha": value["candidate_code_sha"],
            "record_sha256": pointer["record_sha256"]}


def _chain(target):
    pointers, previous = [], None
    for index, (production, candidate) in enumerate(zip("1234", "abcd")):
        fields = {"runtime_predecessor": _pin(target, previous)} if previous else {}
        previous = _record(target, str(index), production * 40, candidate * 40, previous, **fields)
        pointers.append(previous)
    return pointers


def _observation(target, day, production, candidate):
    value = {
        "result": "PASS", "kind": "observation", "observation_date": day,
        "plan_document_id": receiver.PLAN_DOCUMENT_ID, "plan_version": receiver.PLAN_VERSION,
        "plan_git_commit": receiver.PLAN_GIT_COMMIT, "plan_sha256": receiver.PLAN_SHA256,
        "plan_raw_sha256": next(iter(receiver.PLAN_VALID_RAW_SHA256S)),
        "protected_code_sha": production, "candidate_code_sha": candidate,
        "source_manifest_sha256": "e" * 64, "archive_sha256": "f" * 64,
        "checks": {"observation": {"quick_check": "ok"}}, "deviations": [],
    }
    path = target / f"observations/{day}/retained/receipt.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(receiver.canonical_json_bytes(value))
    receiver.append_catalog(target, value, path)
    return path


def test_three_runtime_transitions_preserve_exact_historical_pairs(tmp_path):
    chain = _chain(tmp_path)
    pinned = _pin(tmp_path, chain[-1])
    before = {path: path.read_bytes() for path in (tmp_path / "catalog/scheduled-runs").glob("*.json")}
    pairs = ancestry.authenticated_runtime_pairs(tmp_path, pinned, EXPECTED)
    assert pairs == frozenset((p * 40, c * 40) for p, c in zip("1234", "abcd"))
    _observation(tmp_path, "2026-05-22", "1" * 40, "a" * 40)
    _observation(tmp_path, "2026-05-23", "1" * 40, "e" * 40)  # Same production, unproven receiver.
    result = scheduled.inventory_status(tmp_path, [
        {"date": "2026-05-22", "status": "completed"}, {"date": "2026-05-23", "status": "completed"}],
        {"diagnostics": {}}, protected_sha="5" * 40, plan_commit=receiver.PLAN_GIT_COMMIT,
        previous_runtime=pinned, historical_runtime_pairs=pairs)
    assert result["missing_completed_dates"] == ["2026-05-23"]
    assert all(path.read_bytes() == payload for path, payload in before.items())


def test_unbound_and_failed_runtime_pairs_do_not_grant_coverage(tmp_path):
    first = _record(tmp_path, "first", "1" * 40, "a" * 40)
    failed = _record(tmp_path, "failed", "2" * 40, "b" * 40, first,
                     action="BACKFILL", result="FAIL", detail={"error": "interrupted"})
    latest = _record(tmp_path, "latest", "3" * 40, "c" * 40, failed)
    _record(tmp_path, "unbound", "4" * 40, "d" * 40)
    assert ancestry.authenticated_runtime_pairs(tmp_path, _pin(tmp_path, latest), EXPECTED) == {
        ("1" * 40, "a" * 40), ("3" * 40, "c" * 40)}


@pytest.mark.parametrize("malformed", [{"receiver": "a" * 40}, ["a" * 40], None])
def test_malformed_receipt_runtime_remains_uncovered(tmp_path, malformed):
    _observation(tmp_path, "2026-05-22", "1" * 40, malformed)
    result = scheduled.inventory_status(tmp_path, [{"date": "2026-05-22", "status": "completed"}],
        {"diagnostics": {}}, protected_sha="2" * 40, plan_commit=receiver.PLAN_GIT_COMMIT,
        historical_runtime_pairs=frozenset({("1" * 40, "a" * 40)}))
    assert result["missing_completed_dates"] == ["2026-05-22"]


@pytest.mark.parametrize("change", ["bytes", "missing", "operator", "plan", "cycle", "unsafe", "no_link", "runtime_pin"])
def test_broken_or_foreign_ancestry_is_never_silently_skipped(tmp_path, change):
    first = _record(tmp_path, "first", "1" * 40, "a" * 40)
    path = tmp_path / first["record_path"]
    value = json.loads(path.read_bytes())
    if change == "operator":
        value["operator"] = "someone else"
    elif change == "plan":
        value["plan_git_commit"] = "f" * 40
    elif change == "cycle":
        value["previous_execution"] = dict(first)
    elif change == "unsafe":
        value["previous_execution"] = {"record_path": "../elsewhere.json", "record_sha256": "e" * 64}
    elif change == "no_link":
        value.pop("previous_execution")
    elif change == "runtime_pin":
        value["runtime_predecessor"] = {"production_sha": "9" * 40, "receiver_sha": "f" * 40,
                                        "record_sha256": "e" * 64}
    if change not in {"bytes", "missing"}:
        path.write_bytes(receiver.canonical_json_bytes(value))
        first["record_sha256"] = receiver.sha256_file(path)
    latest = _record(tmp_path, "latest", "2" * 40, "b" * 40, first)
    if change == "bytes":
        path.write_bytes(path.read_bytes() + b" ")
    elif change == "missing":
        path.unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        ancestry.authenticated_runtime_pairs(tmp_path, _pin(tmp_path, latest), EXPECTED)


@pytest.mark.parametrize("fault", ["pin_hash", "pin_pair", "failed_pin", "bound", "size", "reparse"])
def test_anchor_and_resource_bounds_are_enforced(tmp_path, monkeypatch, fault):
    chain = _chain(tmp_path)
    pin = _pin(tmp_path, chain[-1])
    if fault == "pin_hash":
        pin["record_sha256"] = "e" * 64
    elif fault == "pin_pair":
        pin["receiver_sha"] = "f" * 40
    elif fault == "failed_pin":
        last = _record(tmp_path, "failed", "4" * 40, "d" * 40, chain[-1],
                       action="BACKFILL", result="FAIL")
        pin = _pin(tmp_path, last)
    elif fault == "bound":
        monkeypatch.setattr(ancestry, "MAX_RECORDS", 3)
    elif fault == "size":
        monkeypatch.setattr(ancestry, "MAX_RECORD_BYTES", 64)
    elif fault == "reparse":
        monkeypatch.setattr(lineage, "_is_link", lambda path: path.name == "0.json")
    with pytest.raises(ValueError):
        ancestry.authenticated_runtime_pairs(tmp_path, pin, EXPECTED)


def test_runtime_predecessor_link_can_preserve_prior_authenticated_history(tmp_path):
    prior = _record(tmp_path, "prior", "1" * 40, "a" * 40)
    current = _record(tmp_path, "current", "2" * 40, "b" * 40,
                      runtime_predecessor=_pin(tmp_path, prior))
    assert ancestry.authenticated_runtime_pairs(tmp_path, _pin(tmp_path, current), EXPECTED) == {
        ("1" * 40, "a" * 40), ("2" * 40, "b" * 40)}


def test_receiver_upgrade_keeps_failed_descendant_and_original_pass_pin(tmp_path, monkeypatch):
    prior = _record(tmp_path, "natural-pass", "1" * 40, "a" * 40)
    pin = _pin(tmp_path, prior)
    failed = _record(tmp_path, "failed-current", "2" * 40, "a" * 40, prior,
                     action="BACKFILL", result="FAIL")
    pointer = tmp_path / "catalog/latest-scheduled.json"
    pointer.write_bytes(receiver.canonical_json_bytes(dict(failed, result="FAIL")))
    before = {name: (tmp_path / entry["record_path"]).read_bytes()
              for name, entry in (("prior", prior), ("failed", failed))}
    monkeypatch.setattr(transition, "authority", lambda _: pin)
    args = SimpleNamespace(operator="pytest", plan_git_commit=receiver.PLAN_GIT_COMMIT,
                           protected_code_sha="2" * 40, candidate_code_sha="b" * 40)
    scheduled.prepare_execution_lineage(tmp_path, args)
    assert json.loads(pointer.read_bytes())["result"] == "FAIL"
    path = scheduled.record_execution(tmp_path, args, "FAIL", "BACKFILL", {"error": "new attempt failed"})
    value = json.loads(path.read_bytes())
    assert value["previous_execution"] == failed
    assert value["runtime_predecessor"] == pin
    assert (tmp_path / prior["record_path"]).read_bytes() == before["prior"]
    assert (tmp_path / failed["record_path"]).read_bytes() == before["failed"]


@pytest.mark.parametrize("fault", ["unbound", "foreign_pair", "foreign_operator", "tampered_parent"])
def test_receiver_upgrade_rejects_unproven_failed_descendants(tmp_path, fault):
    prior = _record(tmp_path, "natural-pass", "1" * 40, "a" * 40)
    pin = _pin(tmp_path, prior)
    failed = _record(tmp_path, "failed", ("9" if fault == "foreign_pair" else "2") * 40,
                     "a" * 40, None if fault == "unbound" else prior,
                     action="BACKFILL", result="FAIL", operator="foreign" if fault == "foreign_operator" else "pytest")
    if fault == "tampered_parent":
        path = tmp_path / prior["record_path"]
        path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        ancestry.authenticate_pointer_descendant(tmp_path, dict(failed, result="FAIL"), {
            **EXPECTED, "protected_code_sha": "2" * 40, "candidate_code_sha": "b" * 40,
            "runtime_predecessor": pin})


@pytest.mark.parametrize("phase,action,result", [
    ("preflight", "PREFLIGHT_FAILED", "BLOCKED"),
    ("backup", "BACKFILL", "FAIL"),
    ("post-verify", "POST_BACKUP_VERIFY", "FAIL"),
])
def test_cleanup_exception_becomes_execution_failure_and_preserves_components(
    tmp_path, monkeypatch, phase, action, result
):
    target = tmp_path / "backup"
    baseline = _record(target, "baseline", "9" * 40, "c" * 40)
    (target / "catalog/latest-scheduled.json").write_bytes(receiver.canonical_json_bytes(dict(baseline, result="PASS")))
    calls, preserved = [], {}

    def invoke(argv):
        command = argv[0]
        calls.append(command)
        if ((phase == "preflight" and len(calls) == 1)
                or (phase == "post-verify" and len(calls) == 3)):
            raise RuntimeError("remote helper cleanup failed: banner timeout")
        if command == "preflight":
            print(json.dumps({"target": str(target)}))
            return 0
        path = _observation(target, "2026-05-22", "9" * 40, "c" * 40)
        preserved[path] = path.read_bytes()
        if phase == "backup":
            raise RuntimeError("remote helper cleanup failed: banner timeout")
        return 0

    monkeypatch.setattr(receiver, "main", invoke)
    monkeypatch.setattr(scheduled, "receiver_arguments", lambda args, command, *extra: [command])
    monkeypatch.setattr(scheduled, "open_transition_allows_invocation", lambda _: (True, None))
    monkeypatch.setattr(scheduled, "scheduled_status", lambda *args: {
        "status": "STALE", "backup_command": "backfill", "backfill_dates": ["2026-05-22"],
        "inventory": {"stale_diagnostics": []}})
    assert scheduled.main(["--target", str(target), "--recovery-image", str(tmp_path / "recovery.img"),
        "--candidate-code-sha", "c" * 40, "--protected-code-sha", "9" * 40,
        "--plan-git-commit", receiver.PLAN_GIT_COMMIT, "--operator", "pytest"]) == 1
    pointer = json.loads((target / "catalog/latest-scheduled.json").read_bytes())
    record = json.loads((target / pointer["record_path"]).read_bytes())
    assert (record["action"], record["result"]) == (action, result)
    assert record["previous_execution"] == baseline
    assert "cleanup failed" in record["detail"]["error"]
    assert all(path.read_bytes() == payload for path, payload in preserved.items())
    if preserved:
        assert receiver.catalog_entries(target / "catalog/generations.jsonl")[0]["result"] == "PASS"
