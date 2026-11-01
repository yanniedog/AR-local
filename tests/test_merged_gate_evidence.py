"""Control-plane regressions: recovery never bypasses the unchanged D027 gates."""
import copy

import pytest

import pi_cdr_quality_activate_checks as checks


def proof(monkeypatch):
    head, merge = "a" * 40, "b" * 40
    required = ["bot-feedback-gate", "payload builder (pytest)", "process liveness (Windows)"]
    rows = [{"id": i + 1, "name": name, "head_sha": head, "status": "completed",
             "conclusion": "success", "app": {"slug": "github-actions"}} for i, name in enumerate(required)]
    rows.append({**rows[0], "id": 4, "conclusion": "cancelled"})
    documents = {
        "pull_request": {"number": 42, "state": "closed", "merged": True, "merged_at": "2026-11-02T00:00:00Z",
                         "merge_commit_sha": merge, "head": {"sha": head},
                         "base": {"ref": "main", "repo": {"full_name": "yanniedog/AR-local"}}},
        "protection": {"required_status_checks": {"contexts": [required[0]]}}, "rules": {"rules": []},
        "check_runs": {"total_count": len(rows), "check_runs": rows},
        "statuses": {"sha": head, "total_count": 0, "statuses": []},
        "review_threads": {"data": {"repository": {"pullRequest": {"number": 42, "headRefOid": head,
            "reviewThreads": {"totalCount": 0, "nodes": [], "pageInfo": {"hasNextPage": False}}}}}},
    }
    monkeypatch.setattr(checks, "raw", lambda entry: documents[entry])
    return documents, {"evidence": {key: key for key in documents}, "head_commit": head, "required_checks": required}, merge


def test_new_evaluation_keeps_cancelled_history_and_latest_check_authority(monkeypatch):
    documents, value, merge = proof(monkeypatch)
    with pytest.raises(ValueError, match="checks do not satisfy"):
        checks.producer_checks(value, merge)
    rows = documents["check_runs"]["check_runs"]
    history = copy.deepcopy(rows)
    rows.append({**rows[0], "id": 5, "external_id": f"ar-local-merged-required:42:{value['head_commit']}:{merge}"})
    documents["check_runs"]["total_count"] = len(rows)
    checks.producer_checks(value, merge)
    assert rows[:-1] == history
    for outcome in ("failure", "cancelled", None):
        rows[-1]["conclusion"] = outcome
        with pytest.raises(ValueError, match="checks do not satisfy"):
            checks.producer_checks(value, merge)
    rows[-1]["conclusion"] = "success"
    # A stale pre-merge reporter can still publish after the separate merged
    # writer. Fresh latest-ID acceptance must reject its newer cancelled check.
    rows.append({**rows[0], "id": 6, "conclusion": "cancelled"})
    documents["check_runs"]["total_count"] = len(rows)
    with pytest.raises(ValueError, match="checks do not satisfy"):
        checks.producer_checks(value, merge)


@pytest.mark.parametrize("missing", ["protection", "rules", "unknown_required", "threads", "pagination"])
def test_new_success_does_not_waive_other_d027_requirements(monkeypatch, missing):
    documents, value, merge = proof(monkeypatch)
    documents["check_runs"]["check_runs"][-1]["conclusion"] = "success"
    if missing == "protection":
        documents["protection"] = {}
    elif missing == "rules":
        documents["rules"] = {}
    elif missing == "unknown_required":
        documents["protection"]["required_status_checks"]["contexts"].append("new-required-context")
    elif missing == "threads":
        threads = documents["review_threads"]["data"]["repository"]["pullRequest"]["reviewThreads"]
        threads.update(totalCount=1, nodes=[{"isResolved": False}])
    else:
        documents["check_runs"]["total_count"] += 1
    with pytest.raises(ValueError):
        checks.producer_checks(value, merge)
